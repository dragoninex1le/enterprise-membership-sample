"""The bus consumer — the half that runs with nobody calling ffug.

The consumption discipline (PORTH-546) is enforced by DynamoDB, not by branches
in ``lifecycle.py``: one conditional write does de-duplication and version
gating at once. So most of these tests assert on the *expression sent*, and say
so where they do. Asserting behaviour would mean reimplementing DynamoDB's
condition evaluation in a fake and then testing the fake.
"""

from unittest.mock import MagicMock

import pytest

from ffug import lifecycle


class ConditionalCheckFailed(Exception):
    """What botocore raises when our order gate refuses the write."""

    response = {"Error": {"Code": "ConditionalCheckFailedException"}}


class Throttled(Exception):
    response = {"Error": {"Code": "ProvisionedThroughputExceededException"}}


@pytest.fixture(autouse=True)
def table():
    mock = MagicMock()
    mock.query.return_value = {"Items": []}
    lifecycle._table = mock
    yield mock
    lifecycle._table = None


def event(action="created", tenant="acme", env="prod", at="2026-08-20T10:00:00Z", **data):
    return {
        "source": "porth.user-management",
        "detail-type": f"tenant.{action}",
        "detail": {
            "contract_version": 1,
            "environment": env,
            "tenant_id": tenant,
            "action": action,
            "occurred_at": at,
            "data": data,
        },
    }


def update_call(table):
    return table.update_item.call_args[1]


# --- seeding ----------------------------------------------------------------


def test_created_seeds_the_projection_under_the_tenant_partition(table):
    result = lifecycle.handler(event("created"))

    assert result == {"ok": True, "applied": True, "action": "created"}
    call = update_call(table)
    assert call["Key"] == {"pk": "ENV#prod#TENANT#acme", "sk": "PROJECTION"}
    assert call["ExpressionAttributeValues"][":status"] == "active"
    assert call["ExpressionAttributeValues"][":occurred_at"] == "2026-08-20T10:00:00Z"


def test_the_seeded_salt_is_a_prime(table):
    from ffug import salt

    lifecycle.handler(event("created"))

    minted = update_call(table)["ExpressionAttributeValues"][":prime"]
    assert salt.is_prime(int(minted))


def test_two_tenants_are_seeded_with_different_salts(table):
    lifecycle.handler(event("created", tenant="acme"))
    acme = update_call(table)["ExpressionAttributeValues"][":prime"]
    lifecycle.handler(event("created", tenant="globex"))
    globex = update_call(table)["ExpressionAttributeValues"][":prime"]

    assert acme != globex


def test_a_redelivered_create_can_never_re_mint_the_salt(table):
    """The single most damaging thing this consumer could do.

    Re-minting would silently change every digest ffug has ever returned for
    that tenant, and nothing would report it — the service keeps working and
    keeps answering differently. ``if_not_exists`` is what makes the mint
    write-once, evaluated by DynamoDB inside the same atomic update.
    """
    lifecycle.handler(event("created"))

    assert "#prime = if_not_exists(#prime, :prime)" in update_call(table)["UpdateExpression"]


# --- ordering and idempotence ----------------------------------------------


@pytest.mark.parametrize("action", ["created", "updated", "suspended", "reactivated"])
def test_every_write_carries_the_order_gate(table, action):
    """Duplicate delivery and stale delivery are the same condition.

    A re-delivered event has an EQUAL occurred_at, so ``<`` is false and the
    write is a no-op — the dedupe set the in-memory reference consumer keeps is
    not needed, and cannot grow unboundedly in a Lambda.
    """
    lifecycle.handler(event(action))

    assert (
        update_call(table)["ConditionExpression"]
        == "attribute_not_exists(pk) OR #occurred_at < :occurred_at"
    )


def test_a_refused_write_is_reported_and_not_raised(table):
    """A duplicate is the expected case, not a failure. Raising would ask
    EventBridge to redeliver an event we have already applied."""
    table.update_item.side_effect = ConditionalCheckFailed()

    result = lifecycle.handler(event("created"))

    assert result == {"ok": True, "applied": False, "reason": "duplicate_or_stale"}


def test_a_real_failure_is_raised_so_the_delivery_retries(table):
    table.update_item.side_effect = Throttled()

    with pytest.raises(Throttled):
        lifecycle.handler(event("created"))


# --- status transitions -----------------------------------------------------


@pytest.mark.parametrize(
    "action,status",
    [("created", "active"), ("reactivated", "active"), ("suspended", "suspended")],
)
def test_status_follows_the_contract_mapping(table, action, status):
    lifecycle.handler(event(action))

    assert update_call(table)["ExpressionAttributeValues"][":status"] == status


def test_updated_takes_the_status_off_the_event_data(table):
    lifecycle.handler(event("updated", status="suspended"))

    assert update_call(table)["ExpressionAttributeValues"][":status"] == "suspended"


def test_a_tenant_first_seen_on_update_is_still_provisioned(table):
    """Self-healing, deliberately: ffug deployed after a tenant existed should
    converge on the next event it sees rather than stay blind to that tenant."""
    lifecycle.handler(event("updated"))

    call = update_call(table)
    assert call["Key"]["pk"] == "ENV#prod#TENANT#acme"
    assert ":prime" in call["ExpressionAttributeValues"]


# --- deletion: terminal, and residue-free on both sides ---------------------


def test_deleted_strips_the_salt_rather_than_overwriting_it(table):
    lifecycle.handler(event("deleted"))

    call = update_call(table)
    assert "REMOVE #prime" in call["UpdateExpression"]
    assert call["ExpressionAttributeValues"][":deleted"] == "deleted"
    assert ":prime" not in call["ExpressionAttributeValues"]


def test_deleted_leaves_only_a_bounded_marker(table):
    """What survives names a tenant and a time, carries a TTL, and holds no
    tenant data. That is the agreed residue definition (PORTH-587)."""
    lifecycle.handler(event("deleted"))

    values = update_call(table)["ExpressionAttributeValues"]
    assert set(values) == {":deleted", ":occurred_at", ":environment", ":tenant_id", ":expires_at"}
    assert values[":expires_at"] > 0


def test_deleted_purges_every_domain_row_in_the_partition(table):
    table.query.side_effect = [
        {"Items": [{"pk": "ENV#prod#TENANT#acme", "sk": "ITEM#a"}], "LastEvaluatedKey": {"k": 1}},
        {"Items": [{"pk": "ENV#prod#TENANT#acme", "sk": "ITEM#b"}]},
    ]

    lifecycle.handler(event("deleted"))

    batch = table.batch_writer.return_value.__enter__.return_value
    assert [c[1]["Key"]["sk"] for c in batch.delete_item.call_args_list] == ["ITEM#a", "ITEM#b"]


def test_the_purge_paginates_and_reads_only_keys(table):
    """Transient data with no per-tenant bound: fetching whole items to throw
    them away would page in payloads there is no reason to read."""
    table.query.side_effect = [
        {"Items": [], "LastEvaluatedKey": {"k": 1}},
        {"Items": []},
    ]

    lifecycle.handler(event("deleted"))

    assert table.query.call_count == 2
    assert table.query.call_args_list[0][1]["ProjectionExpression"] == "pk, sk"
    assert table.query.call_args_list[1][1]["ExclusiveStartKey"] == {"k": 1}


def test_the_marker_is_written_before_the_domain_rows_are_purged(table):
    """If the purge fails halfway, the retry must find a tenant already closed
    for business — not one that still looks active and is missing half its rows."""
    order = []
    table.update_item.side_effect = lambda **_: order.append("marker")
    table.query.side_effect = lambda **_: (order.append("purge"), {"Items": []})[1]

    lifecycle.handler(event("deleted"))

    assert order == ["marker", "purge"]


def test_deletion_is_terminal_against_a_late_pre_deletion_event(table):
    """The marker carries the deletion timestamp, so the same order gate that
    de-duplicates also refuses a late `created` — DynamoDB evaluates it."""
    lifecycle.handler(event("deleted", at="2026-08-20T11:00:00Z"))
    delete_gate = update_call(table)["ConditionExpression"]

    table.update_item.side_effect = ConditionalCheckFailed()
    late = lifecycle.handler(event("created", at="2026-08-20T09:00:00Z"))

    assert delete_gate == "attribute_not_exists(pk) OR #occurred_at < :occurred_at"
    assert late == {"ok": True, "applied": False, "reason": "duplicate_or_stale"}


# --- contract violations ----------------------------------------------------


@pytest.mark.parametrize(
    "bad",
    [
        {"detail-type": "tenant.created", "detail": {}},
        {"detail-type": "tenant.created", "detail": {"contract_version": 2, "tenant_id": "a",
                                                     "action": "created", "occurred_at": "t"}},
        # detail-type disagrees with the action — malformed, never reinterpreted
        {"detail-type": "tenant.deleted", "detail": {"contract_version": 1, "tenant_id": "a",
                                                     "action": "created", "occurred_at": "t"}},
        {"detail-type": "", "detail": {}},
        {},
    ],
)
def test_a_malformed_event_is_refused_without_touching_the_table(table, bad):
    """Swallowed rather than raised: redelivering will not make it well-formed,
    and raising would loop the same bad event until the retry budget is spent."""
    result = lifecycle.handler(bad)

    assert result == {"ok": False, "reason": "contract_violation"}
    assert not table.update_item.called
    assert not table.query.called


def test_the_internal_domain_events_are_not_this_contract(table):
    """`Tenant.*` (capitalised) is the audit/search feed. Subscribing to it from
    a consuming service is explicitly wrong — and it must not half-work here."""
    result = lifecycle.handler(
        {"detail-type": "Tenant.Created", "detail": {"contract_version": 1, "tenant_id": "a",
                                                     "action": "created", "occurred_at": "t"}}
    )

    assert result == {"ok": False, "reason": "contract_violation"}
    assert not table.update_item.called
