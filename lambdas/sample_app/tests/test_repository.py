import pytest
from unittest.mock import MagicMock

from sample_app.repository import SampleAppRepository, ScopeMissingError

PARTITION = "ENV#e-test#TENANT#t-1"


def make_repo():
    dynamo = MagicMock()
    table = MagicMock()
    dynamo.Table.return_value = table
    return SampleAppRepository(dynamo, environment="e-test", tenant_id="t-1"), table


# --- the scope is a property of the repository, not an argument --------------


def test_the_partition_carries_environment_and_tenant():
    repo, _ = make_repo()
    assert repo.partition == PARTITION


@pytest.mark.parametrize(
    "environment,tenant_id",
    [("", "t-1"), ("e-test", ""), ("", ""), (None, "t-1"), ("e-test", None)],
)
def test_a_half_specified_scope_refuses_to_build(environment, tenant_id):
    """Raised, never defaulted. An empty environment yields ENV##TENANT#t-1 —
    written successfully, matching no session policy, never read back. The
    failure would surface as "the invoice I just created is not in the list"."""
    with pytest.raises(ScopeMissingError):
        SampleAppRepository(MagicMock(), environment=environment, tenant_id=tenant_id)


def test_no_method_takes_a_tenant(): 
    """TS-MC.1: a tenant that is a free string at the call site is one a call
    site can get wrong. There is no parameter to pass."""
    import inspect

    for name in ("list_invoices", "list_bills", "list_pending_approvals",
                 "create_invoice", "create_bill", "approve", "reject",
                 "dashboard_summary"):
        params = inspect.signature(getattr(SampleAppRepository, name)).parameters
        assert "tenant_id" not in params, f"{name} still takes a tenant"


# --- writes ------------------------------------------------------------------


def test_create_invoice_keys():
    repo, table = make_repo()
    repo.create_invoice({"customer_name": "Acme", "amount": 100.0})
    item = table.put_item.call_args[1]["Item"]
    assert item["pk"] == PARTITION
    assert item["sk"].startswith("INVOICE#")
    assert item["customer_name"] == "Acme"
    assert item["environment"] == "e-test"


def test_create_bill_keys():
    repo, table = make_repo()
    repo.create_bill({"vendor_name": "Vendor", "amount": 50.0})
    item = table.put_item.call_args[1]["Item"]
    assert item["pk"] == PARTITION
    assert item["sk"].startswith("BILL#")


def test_approve_sets_status_on_the_source_record():
    """The key is the INVOICE#, not an APPROVAL#. PORTH-597: the decision is a
    status on the record itself, so there is no second row to keep in step."""
    repo, table = make_repo()
    table.update_item.return_value = {"Attributes": {"status": "approved"}}
    repo.approve("invoice", "i-1")
    kw = table.update_item.call_args[1]
    assert kw["ExpressionAttributeValues"][":to"] == "approved"
    assert kw["Key"] == {"pk": PARTITION, "sk": "INVOICE#i-1"}


def test_reject_sets_status_on_the_source_record():
    repo, table = make_repo()
    table.update_item.return_value = {"Attributes": {"status": "rejected"}}
    repo.reject("bill", "b-1")
    kw = table.update_item.call_args[1]
    assert kw["ExpressionAttributeValues"][":to"] == "rejected"
    assert kw["Key"] == {"pk": PARTITION, "sk": "BILL#b-1"}


# --- reads -------------------------------------------------------------------


def test_list_invoices_queries_this_partition():
    repo, table = make_repo()
    table.query.return_value = {"Items": []}
    assert repo.list_invoices() == []
    table.query.assert_called_once()


def _condition_values(condition) -> set:
    """Every literal operand in a boto3 key condition, however nested.

    repr() on one of these yields `<boto3.dynamodb.conditions.And object at
    0x…>` — which contains no operand at all, so an assertion against it passes
    whatever partition was queried. Same helper, same reason, as the one in
    test_director.py.
    """
    values: set = set()
    expression = getattr(condition, "get_expression", None)
    if expression is None:
        return {condition} if isinstance(condition, str) else values
    for operand in expression()["values"]:
        if isinstance(operand, str):
            values.add(operand)
        else:
            values |= _condition_values(operand)
    return values


def test_reads_are_confined_to_one_partition():
    """Every read this repository can perform names the same partition. Not the
    isolation boundary — IAM is — but a repository that can compose a second
    partition is one a bug can point at another tenant."""
    repo, table = make_repo()
    table.query.return_value = {"Items": []}
    repo.list_invoices(); repo.list_bills(); repo.list_pending_approvals()
    # Four, not three: list_pending_approvals reads both approvable prefixes,
    # because an approval IS an invoice or a bill (PORTH-597).
    assert table.query.call_count == 4
    for call in table.query.call_args_list:
        assert PARTITION in _condition_values(call[1]["KeyConditionExpression"])


# --- approvals are derived from the records (PORTH-597) ----------------------


class _ConditionalCheckFailed(Exception):
    response = {"Error": {"Code": "ConditionalCheckFailedException"}}


def _invoice(status, iid="i-1"):
    return {"invoice_id": iid, "customer_name": "Acme", "amount": "100",
            "status": status, "submitted_by": "u-1", "submitted_at": "2026-08-21T00:00:00Z"}


def _bill(status, bid="b-1"):
    return {"bill_id": bid, "vendor_name": "Vendor", "amount": "50",
            "status": status, "submitted_by": "u-2", "submitted_at": "2026-08-21T01:00:00Z"}


def test_approvals_come_from_the_records_not_an_approval_prefix():
    """The bug this replaces: the list queried APPROVAL#, which nothing has ever
    written, so it was structurally always empty rather than intermittently so."""
    repo, table = make_repo()
    table.query.side_effect = [
        {"Items": [_invoice("pending_approval"), _invoice("draft", "i-2")]},
        {"Items": [_bill("pending_approval")]},
    ]

    pending = repo.list_pending_approvals()

    prefixes = [_condition_values(c[1]["KeyConditionExpression"]) for c in table.query.call_args_list]
    assert not any("APPROVAL#" in v for values in prefixes for v in values)
    assert [a["record_type"] for a in pending] == ["invoice", "bill"]
    assert [a["record_id"] for a in pending] == ["i-1", "b-1"]


def test_only_records_awaiting_a_decision_are_listed():
    repo, table = make_repo()
    table.query.side_effect = [
        {"Items": [_invoice("draft"), _invoice("approved", "i-2")]},
        {"Items": [_bill("pending")]},
    ]

    assert repo.list_pending_approvals() == []


def test_the_listed_shape_is_the_one_the_screen_reads():
    """`record_type`, `amount`, `submitted_by` and `submitted_at` have always
    been expected by ApprovalsPage. Nothing produced them before."""
    repo, table = make_repo()
    table.query.side_effect = [{"Items": [_invoice("pending_approval")]}, {"Items": []}]

    entry = repo.list_pending_approvals()[0]

    assert set(entry) == {"record_id", "record_type", "counterparty", "amount",
                          "status", "submitted_by", "submitted_at",
                          "fingerprint_prime", "fingerprint_digest",
                          # PORTH-621 — the screen has to distinguish "queued"
                          # from "ffug never saw this", and needs the trace to
                          # show alongside the digest it will produce.
                          "fingerprint_status", "fingerprint_trace_id",
                          # PORTH-622 — H, so the screen can show what was
                          # committed BEFORE ffug was asked, beside the answer.
                          "fingerprint_correlation_hash"}


# --- transitions are guarded by DynamoDB, not by a prior read ----------------


def test_submit_records_who_and_when_and_guards_the_source_state():
    repo, table = make_repo()
    table.update_item.return_value = {"Attributes": _invoice("pending_approval")}

    repo.submit_for_approval("invoice", "i-1", by="u-9")

    kw = table.update_item.call_args[1]
    assert kw["Key"] == {"pk": PARTITION, "sk": "INVOICE#i-1"}
    assert kw["ExpressionAttributeValues"][":to"] == "pending_approval"
    assert "draft" in kw["ExpressionAttributeValues"].values()
    assert "u-9" in kw["ExpressionAttributeValues"].values()


def test_approving_a_record_that_does_not_exist_cannot_create_one():
    """The regression that matters most here.

    UpdateItem is an UPSERT. The previous approve() wrote to APPROVAL#{id} with
    no condition, so approving an id that did not exist silently CREATED a row
    holding a pk, an sk and a status and nothing else — and because the list
    filtered on status, that row was invisible junk. `attribute_exists(pk)` is
    what stops it.
    """
    repo, table = make_repo()
    table.update_item.return_value = {"Attributes": _invoice("approved")}

    repo.approve("invoice", "i-1")

    assert "attribute_exists(pk)" in table.update_item.call_args[1]["ConditionExpression"]


@pytest.mark.parametrize("action", ["approve", "reject"])
def test_a_decision_is_only_legal_from_pending_approval(action):
    repo, table = make_repo()
    table.update_item.return_value = {"Attributes": _invoice("approved")}

    getattr(repo, action)("invoice", "i-1")

    values = table.update_item.call_args[1]["ExpressionAttributeValues"]
    assert "pending_approval" in values.values()
    assert "draft" not in values.values()


@pytest.mark.parametrize("call", [
    lambda r: r.approve("invoice", "i-1"),
    lambda r: r.reject("bill", "b-1"),
    lambda r: r.submit_for_approval("invoice", "i-1", by="u-1"),
])
def test_a_refused_guard_is_a_typed_error_not_a_crash(call):
    from sample_app.repository import TransitionNotAllowedError

    repo, table = make_repo()
    table.update_item.side_effect = _ConditionalCheckFailed()

    with pytest.raises(TransitionNotAllowedError):
        call(repo)


def test_a_real_failure_still_propagates():
    """Only the guard is translated. A throttle is not a business outcome."""
    class Throttled(Exception):
        response = {"Error": {"Code": "ProvisionedThroughputExceededException"}}

    repo, table = make_repo()
    table.update_item.side_effect = Throttled()

    with pytest.raises(Throttled):
        repo.approve("invoice", "i-1")


def test_an_unapprovable_record_type_is_refused():
    from sample_app.repository import UnknownRecordTypeError

    repo, _ = make_repo()
    with pytest.raises(UnknownRecordTypeError):
        repo.approve("purchase_order", "p-1")


# --- the fingerprint ffug returns (PORTH-599) --------------------------------


def test_the_fingerprint_document_is_the_records_substance():
    """Small and fixed on purpose. The point of showing a digest to a human is
    that they can see what went into it; a document nobody can reproduce by hand
    proves nothing to the person looking at it."""
    from sample_app.repository import fingerprint_document

    doc = fingerprint_document({
        "record_type": "invoice", "record_id": "i-1", "counterparty": "Acme",
        "amount": "100", "status": "approved", "submitted_by": "u-1",
    })

    assert doc == {"record_type": "invoice", "record_id": "i-1",
                   "counterparty": "Acme", "amount": "100"}


def test_the_fingerprint_document_has_a_stable_field_order():
    """Two calls must produce the same bytes, or the digest is not a
    fingerprint. Guards against a future dict comprehension over a set."""
    from sample_app.repository import fingerprint_document

    a = fingerprint_document({"record_type": "invoice", "record_id": "i-1",
                              "counterparty": "Acme", "amount": "100"})
    b = fingerprint_document({"amount": "100", "counterparty": "Acme",
                              "record_id": "i-1", "record_type": "invoice"})

    assert list(a) == list(b)


def test_attaching_a_fingerprint_cannot_conjure_a_record():
    """Same upsert trap PORTH-597 removed, in the newest write."""
    repo, table = make_repo()
    table.update_item.return_value = {"Attributes": _invoice("approved")}

    repo.attach_fingerprint("invoice", "i-1", prime="11", digest="abc")

    kw = table.update_item.call_args[1]
    assert kw["ConditionExpression"] == "attribute_exists(pk)"
    assert kw["Key"] == {"pk": PARTITION, "sk": "INVOICE#i-1"}
    assert kw["ExpressionAttributeValues"] == {
        ":p": "11", ":d": "abc", ":s": "complete"
    }


def test_a_listed_approval_carries_its_fingerprint_when_it_has_one():
    repo, table = make_repo()
    item = _invoice("pending_approval")
    item.update({"fingerprint_prime": "11", "fingerprint_digest": "abc"})
    table.query.side_effect = [{"Items": [item]}, {"Items": []}]

    entry = repo.list_pending_approvals()[0]

    assert entry["fingerprint_prime"] == "11"
    assert entry["fingerprint_digest"] == "abc"


def test_a_record_with_no_fingerprint_reports_empty_not_missing():
    """Empty is a real state — approved before the fingerprint existed, or ffug
    was unreachable — and the screen distinguishes it from 'never wanted'."""
    repo, table = make_repo()
    table.query.side_effect = [{"Items": [_invoice("pending_approval")]}, {"Items": []}]

    entry = repo.list_pending_approvals()[0]

    assert entry["fingerprint_prime"] == ""
    assert entry["fingerprint_digest"] == ""


# --- the fingerprint lifecycle (PORTH-621) -----------------------------------


def test_the_expectation_is_committed_before_the_work_is_requested():
    """The correlation hash is stored, never derived on arrival.

    Porth computes and compares; the application stores. A hash derived when the
    callback lands would be derived FROM the callback and would match itself,
    which is the whole check gone while every test still passes.
    """
    repo, table = make_repo()
    table.update_item.return_value = {"Attributes": _invoice("approved")}

    repo.begin_fingerprint("invoice", "i-1", trace_id="t-9", correlation_hash="H")

    kw = table.update_item.call_args[1]
    assert kw["ConditionExpression"] == "attribute_exists(pk)"
    assert kw["Key"] == {"pk": PARTITION, "sk": "INVOICE#i-1"}
    assert kw["ExpressionAttributeValues"] == {":s": "queued", ":t": "t-9", ":h": "H"}


def test_queueing_removes_the_previous_answer():
    """A stale digest beside a `queued` status reads as "here it is, still
    working" — which is the one thing it is not. It also verifies against the
    OLD document, so leaving it standing is worse than showing nothing."""
    repo, table = make_repo()
    table.update_item.return_value = {"Attributes": _invoice("approved")}

    repo.begin_fingerprint("invoice", "i-1", trace_id="t-9", correlation_hash="H")

    expression = table.update_item.call_args[1]["UpdateExpression"]
    assert "REMOVE fingerprint_prime, fingerprint_digest" in expression


def test_work_ffug_never_took_leaves_no_expectation_behind():
    """REMOVE, not a status of its own. A record left `queued` after a refused
    call waits forever, and polls forever, for a completion nobody will send."""
    repo, table = make_repo()
    table.update_item.return_value = {"Attributes": _invoice("approved")}

    repo.abandon_fingerprint("invoice", "i-1")

    kw = table.update_item.call_args[1]
    assert kw["UpdateExpression"].startswith("REMOVE fingerprint_status")
    assert "fingerprint_correlation_hash" in kw["UpdateExpression"]
    assert kw["ConditionExpression"] == "attribute_exists(pk)"


def test_a_callback_finds_its_record_by_the_trace_the_app_minted():
    """Across both record types, and within this tenant's partition only.

    The callback does not say which record it completes. If it did, a completing
    service could aim an authentic completion at a different row.
    """
    repo, table = make_repo()
    waiting = {**_bill("approved", "b-7"), "fingerprint_trace_id": "t-9"}
    table.query.side_effect = [
        {"Items": [{**_invoice("approved"), "fingerprint_trace_id": "t-other"}]},
        {"Items": [waiting]},
    ]

    assert repo.find_by_fingerprint_trace("t-9") == ("bill", waiting)


def test_a_trace_nobody_is_waiting_on_finds_nothing():
    repo, table = make_repo()
    table.query.side_effect = [{"Items": [_invoice("approved")]}, {"Items": []}]

    assert repo.find_by_fingerprint_trace("t-9") is None


def test_an_empty_trace_matches_nothing_rather_than_the_first_blank_record():
    """Every record approved before ffug existed has no trace at all. Falling
    through to one of them would attach a stranger's digest to it."""
    repo, table = make_repo()
    table.query.side_effect = [{"Items": [_invoice("approved")]}, {"Items": []}]

    assert repo.find_by_fingerprint_trace("") is None
    assert not table.query.called


def test_the_fingerprint_survives_the_invoice_list():
    """AR and AP render the fingerprint off the RAW row, not off _as_approval.

    `_list` returns items as DynamoDB gave them and `attach_fingerprint` writes
    to that same row, so every `fingerprint_*` attribute is already on the wire
    for /sample/ar/invoices. The screens depend on that, and it is currently a
    happy accident of two functions agreeing rather than anything stated.

    Asserted so it becomes a contract: a projection added to `_list` — the
    obvious optimisation on a widening table — would blank both screens while
    every other test stayed green.
    """
    repo, table = make_repo()
    table.query.return_value = {
        "Items": [{
            **_invoice("approved"),
            "fingerprint_correlation_hash": "H",
            "fingerprint_prime": "11",
            "fingerprint_digest": "abc",
            "fingerprint_status": "complete",
            "fingerprint_trace_id": "t-9",
        }]
    }

    listed = repo.list_invoices()[0]

    for field in ("fingerprint_correlation_hash", "fingerprint_prime",
                  "fingerprint_digest", "fingerprint_status", "fingerprint_trace_id"):
        assert field in listed, f"{field} did not survive list_invoices"
