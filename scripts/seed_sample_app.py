#!/usr/bin/env python3
from __future__ import annotations
import argparse, uuid, boto3
from datetime import datetime, timezone, timedelta

def _now(): return datetime.now(timezone.utc).isoformat()
def _due(d): return (datetime.now(timezone.utc) + timedelta(days=d)).date().isoformat()

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--tenant-id", required=True)
    p.add_argument("--env", default="dev")
    args = p.parse_args()
    table = boto3.resource("dynamodb").Table(f"porth-sample-app-{args.env}")
    tid = args.tenant_id

    for inv in [
        {"customer_name": "Acme Corp",   "amount": "12500.00", "status": "sent",  "due_date": _due(14)},
        {"customer_name": "Globex Inc",  "amount": "4800.00",  "status": "paid",  "due_date": _due(-5)},
        {"customer_name": "Initech Ltd", "amount": "9200.00",  "status": "draft", "due_date": _due(30)},
    ]:
        iid = str(uuid.uuid4())
        table.put_item(Item={"pk": f"TENANT#{tid}", "sk": f"INVOICE#{iid}",
            "invoice_id": iid, "tenant_id": tid, "created_by": "seed", "created_at": _now(), **inv})
    print("Seeded 3 invoices")

    for bill in [
        {"vendor_name": "Office Supplies Co", "amount": "650.00",  "status": "pending",  "due_date": _due(7)},
        {"vendor_name": "Cloud Services Ltd",  "amount": "3200.00", "status": "approved", "due_date": _due(21)},
        {"vendor_name": "Utilities Corp",      "amount": "480.00",  "status": "pending",  "due_date": _due(3)},
    ]:
        bid = str(uuid.uuid4())
        table.put_item(Item={"pk": f"TENANT#{tid}", "sk": f"BILL#{bid}",
            "bill_id": bid, "tenant_id": tid, "created_by": "seed", "created_at": _now(), **bill})
    print("Seeded 3 bills")

    rid = str(uuid.uuid4())
    table.put_item(Item={"pk": f"TENANT#{tid}", "sk": f"APPROVAL#{rid}",
        "record_id": rid, "tenant_id": tid, "type": "invoice", "amount": "12500.00",
        "submitted_by": "seed", "status": "pending", "submitted_at": _now()})
    print("Seeded 1 approval")

if __name__ == "__main__":
    main()
