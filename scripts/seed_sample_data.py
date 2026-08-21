"""Give a tenant something to look at in the sample app.

The app's table is populated by SampleAppEventConsumerFunction, from Porth
entity events. That is fine for a tenant created after the consumer existed and
useless for one created before it: the events fired into a void and nothing will
ever replay them. EMS's one tenant is in exactly that state — the pages render,
correctly, with nothing in them, which is indistinguishable from the pages being
broken.

So this writes records directly, in the shape the repository queries for. It is
a TEST FIXTURE and says so: every row it writes carries ``seeded: true``, so a
seeded record can always be told from one the app produced.

Deliberately not an API call. The routes are behind the authorizer and a browser
session, which is the thing being tested — seeding through them would make the
fixture depend on the mechanism it exists to give us something to test.

    PORTH_ENVIRONMENT=dev TENANT_ID=ems-test AWS_REGION=us-east-1 \
        python3 scripts/seed_sample_data.py
"""
from __future__ import annotations

import os
import sys
import uuid
from datetime import datetime, timedelta, timezone

import boto3

TABLE_NAME = f"porth-sample-app-{os.environ.get('PORTH_ENVIRONMENT', 'dev')}"
TENANT_ID = os.environ.get("TENANT_ID", "")
COUNT = int(os.environ.get("SEED_COUNT", "5"))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _due(days: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=days)).date().isoformat()


def main() -> int:
    if not TENANT_ID:
        print("::error::TENANT_ID is required — records are written under "
              "pk=TENANT#{id} and a blank one would create an unreachable partition")
        return 1

    table = boto3.resource("dynamodb").Table(TABLE_NAME)
    pk = f"TENANT#{TENANT_ID}"
    written = 0

    for n in range(COUNT):
        invoice_id = str(uuid.uuid4())
        table.put_item(Item={
            "pk": pk, "sk": f"INVOICE#{invoice_id}",
            "invoice_id": invoice_id, "tenant_id": TENANT_ID,
            "customer_name": f"Seeded Customer {n + 1}",
            "amount": str(1000 + n * 250), "status": "draft",
            "due_date": _due(30 + n), "created_by": "seed_sample_data.py",
            "created_at": _now(), "seeded": True,
        })

        bill_id = str(uuid.uuid4())
        table.put_item(Item={
            "pk": pk, "sk": f"BILL#{bill_id}",
            "bill_id": bill_id, "tenant_id": TENANT_ID,
            "vendor_name": f"Seeded Vendor {n + 1}",
            "amount": str(500 + n * 125), "status": "pending",
            "due_date": _due(14 + n), "created_by": "seed_sample_data.py",
            "created_at": _now(), "seeded": True,
        })

        # status MUST be "pending": list_pending_approvals filters on it in
        # Python after the query, so any other value writes a row the Approvals
        # page will never show — a seed that looks successful and changes nothing.
        approval_id = str(uuid.uuid4())
        table.put_item(Item={
            "pk": pk, "sk": f"APPROVAL#{approval_id}",
            "record_id": approval_id, "tenant_id": TENANT_ID,
            "description": f"Seeded approval {n + 1}",
            "amount": str(750 + n * 100), "status": "pending",
            "requested_by": "seed_sample_data.py", "created_at": _now(),
            "seeded": True,
        })
        written += 3

    print(f"✅ wrote {written} records under {pk} in {TABLE_NAME} "
          f"({COUNT} invoices, {COUNT} bills, {COUNT} pending approvals)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
