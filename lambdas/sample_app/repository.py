"""The sample app's data access — one tenant, one environment, per instance.

PORTH-594. This table predates ADR-Z8. Porth gained the environment dimension
and every Porth row moved to ``ENV#{slot}#…``; this one never followed, so its
rows sat at ``TENANT#{tenant}`` with the environment carried by the table NAME.
That is why the session policy could not fence the environment in
``dynamodb:LeadingKeys``: there was no environment in the key to fence.

Two things changed together, because half a migration on an empty table is
invisible until the first row is written:

**The key carries the environment.** ``ENV#{slot}#TENANT#{tenant}``, the same
shape as Porth's own rows and the shape ``SampleAppSessionPolicy`` now matches.

**The scope is a property of the repository, not an argument to its methods.**
Every method used to take ``tenant_id``, which made the tenant a free string at
each call site — the shape TS-MC.1 exists to prevent, and the one the Director
was adopted to remove. A repository is now built FOR a scope and cannot be asked
about another one. There is no parameter to get wrong.

Both values come from the Director, which got them from the authorizer's own
resolution. Neither is read from the environment: ``PORTH_ENVIRONMENT`` suffixes
the table name and is a DIFFERENT VALUE from the ADR-Z8 slot — ``dev`` versus
``prod`` on this install. Composing the key from the wrong one produces rows
nothing can read and a policy that matches nothing, and each looks like the
other's fault.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone

from boto3.dynamodb.conditions import Key

#: The table NAME's environment — the deployment axis. Not the data axis; see
#: the module docstring. These are different values and conflating them is the
#: specific mistake this module is arranged to prevent.
TABLE_NAME = f"porth-sample-app-{os.environ.get('PORTH_ENVIRONMENT', 'dev')}"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ScopeMissingError(ValueError):
    """The repository was built without a full scope, so it refuses to exist.

    Raised rather than defaulted. An empty environment yields
    ``ENV##TENANT#acme`` — a key that is written successfully, matches no
    session policy, and is never read back. The failure would surface as "the
    invoice I just created is not in the list", several layers from its cause.
    """


class SampleAppRepository:
    """This app's table, bound to one tenant in one environment."""

    def __init__(self, dynamodb_resource, *, environment: str, tenant_id: str) -> None:
        if not environment or not tenant_id:
            raise ScopeMissingError(
                f"repository needs both an environment and a tenant; got "
                f"environment={environment!r} tenant_id={tenant_id!r}"
            )
        self.table = dynamodb_resource.Table(TABLE_NAME)
        self.environment = environment
        self.tenant_id = tenant_id
        #: Every row this instance can address. Composed once: a second place
        #: that builds this string is a second place it can be built wrong.
        self.partition = f"ENV#{environment}#TENANT#{tenant_id}"

    # -- reads ---------------------------------------------------------------

    def _list(self, sk_prefix: str) -> list[dict]:
        resp = self.table.query(
            KeyConditionExpression=Key("pk").eq(self.partition)
            & Key("sk").begins_with(sk_prefix)
        )
        return resp.get("Items", [])

    def list_invoices(self) -> list[dict]:
        return self._list("INVOICE#")

    def list_bills(self) -> list[dict]:
        return self._list("BILL#")

    def list_pending_approvals(self) -> list[dict]:
        return [i for i in self._list("APPROVAL#") if i.get("status") == "pending"]

    # -- writes --------------------------------------------------------------

    def create_invoice(self, data: dict) -> dict:
        invoice_id = str(uuid.uuid4())
        item = {
            "pk": self.partition, "sk": f"INVOICE#{invoice_id}",
            "invoice_id": invoice_id, "tenant_id": self.tenant_id,
            "environment": self.environment,
            "customer_name": data["customer_name"], "amount": str(data["amount"]),
            "status": "draft", "due_date": data.get("due_date", ""),
            "created_by": data.get("created_by", ""), "created_at": _now(),
        }
        self.table.put_item(Item=item)
        return item

    def create_bill(self, data: dict) -> dict:
        bill_id = str(uuid.uuid4())
        item = {
            "pk": self.partition, "sk": f"BILL#{bill_id}",
            "bill_id": bill_id, "tenant_id": self.tenant_id,
            "environment": self.environment,
            "vendor_name": data["vendor_name"], "amount": str(data["amount"]),
            "status": "pending", "due_date": data.get("due_date", ""),
            "created_by": data.get("created_by", ""), "created_at": _now(),
        }
        self.table.put_item(Item=item)
        return item

    def _set_approval_status(self, record_id: str, status: str) -> dict:
        resp = self.table.update_item(
            Key={"pk": self.partition, "sk": f"APPROVAL#{record_id}"},
            UpdateExpression="SET #s = :v",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={":v": status},
            ReturnValues="ALL_NEW",
        )
        return resp.get("Attributes", {})

    def approve(self, record_id: str) -> dict:
        return self._set_approval_status(record_id, "approved")

    def reject(self, record_id: str) -> dict:
        return self._set_approval_status(record_id, "rejected")

    # -- derived -------------------------------------------------------------

    def dashboard_summary(self) -> dict:
        invoices = self.list_invoices()
        bills = self.list_bills()
        approvals = self.list_pending_approvals()
        outstanding = sum(1 for i in invoices if i.get("status") != "paid")
        total_ar = sum(float(i.get("amount", 0)) for i in invoices if i.get("status") != "paid")
        bills_due = sum(1 for b in bills if b.get("status") == "pending")
        total_ap = sum(float(b.get("amount", 0)) for b in bills if b.get("status") == "pending")
        return {
            "outstanding_invoices": outstanding, "total_ar": total_ar,
            "bills_due": bills_due, "total_ap": total_ap,
            "pending_approvals": len(approvals), "cash_position": total_ar - total_ap,
        }
