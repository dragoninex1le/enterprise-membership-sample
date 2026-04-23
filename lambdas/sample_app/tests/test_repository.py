from unittest.mock import MagicMock
from sample_app.repository import SampleAppRepository

def make_repo():
    dynamo = MagicMock()
    table = MagicMock()
    dynamo.Table.return_value = table
    return SampleAppRepository(dynamo), table

def test_create_invoice_pk_sk():
    repo, table = make_repo()
    repo.create_invoice("t-1", {"customer_name": "Acme", "amount": 100.0})
    item = table.put_item.call_args[1]["Item"]
    assert item["pk"] == "TENANT#t-1"
    assert item["sk"].startswith("INVOICE#")
    assert item["customer_name"] == "Acme"

def test_create_bill_pk_sk():
    repo, table = make_repo()
    repo.create_bill("t-1", {"vendor_name": "Vendor", "amount": 50.0})
    item = table.put_item.call_args[1]["Item"]
    assert item["pk"] == "TENANT#t-1"
    assert item["sk"].startswith("BILL#")

def test_approve_sets_status():
    repo, table = make_repo()
    table.update_item.return_value = {"Attributes": {"status": "approved"}}
    repo.approve("t-1", "rec-1")
    kw = table.update_item.call_args[1]
    assert kw["ExpressionAttributeValues"][":v"] == "approved"
    assert kw["Key"] == {"pk": "TENANT#t-1", "sk": "APPROVAL#rec-1"}

def test_reject_sets_status():
    repo, table = make_repo()
    table.update_item.return_value = {"Attributes": {"status": "rejected"}}
    repo.reject("t-1", "rec-1")
    kw = table.update_item.call_args[1]
    assert kw["ExpressionAttributeValues"][":v"] == "rejected"

def test_list_invoices_calls_query():
    repo, table = make_repo()
    table.query.return_value = {"Items": []}
    result = repo.list_invoices("t-1")
    assert result == []
    table.query.assert_called_once()
