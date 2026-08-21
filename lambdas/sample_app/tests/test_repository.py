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


def test_approve_sets_status():
    repo, table = make_repo()
    table.update_item.return_value = {"Attributes": {"status": "approved"}}
    repo.approve("rec-1")
    kw = table.update_item.call_args[1]
    assert kw["ExpressionAttributeValues"][":v"] == "approved"
    assert kw["Key"] == {"pk": PARTITION, "sk": "APPROVAL#rec-1"}


def test_reject_sets_status():
    repo, table = make_repo()
    table.update_item.return_value = {"Attributes": {"status": "rejected"}}
    repo.reject("rec-1")
    assert table.update_item.call_args[1]["ExpressionAttributeValues"][":v"] == "rejected"


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
    assert table.query.call_count == 3
    for call in table.query.call_args_list:
        assert PARTITION in _condition_values(call[1]["KeyConditionExpression"])
