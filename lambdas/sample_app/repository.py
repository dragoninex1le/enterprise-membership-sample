from __future__ import annotations
import os
import uuid
from datetime import datetime, timezone

from boto3.dynamodb.conditions import Key

TABLE_NAME = f"porth-sample-app-{os.environ.get('PORTH_ENVIRONMENT', 'dev')}"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class SampleAppRepository:
    def __init__(self, dynamodb_resource):
        self.table = dynamodb_resource.Table(TABLE_NAME)

    def list_invoices(self, tenant_id: str) -> list[dict]:
        resp = self.table.query(
            KeyConditionExpression=Key("pk").eq(f"TENANT#{tenant_id}") & Key("sk").begins_with("INVOICE#")
        )
        return resp.get("Items", [])

    def create_invoice(self, tenant_id: str, data: dict) -> dict:
        invoice_id = str(uuid.uuid4())
        item = {
            "pk": f"TENANT#{tenant_id}", "sk": f"INVOICE#{invoice_id}",
            "invoice_id": invoice_id, "tenant_id": tenant_id,
            "customer_name": data["customer_name"], "amount": str(data["amount"]),
            "status": "draft", "due_date": data.get("due_date", ""),
            "created_by": data.get("created_by", ""), "created_at": _now(),
        }
        self.table.put_item(Item=item)
        return item

    def list_bills(self, tenant_id: str) -> list[dict]:
        resp = self.table.query(
            KeyConditionExpression=Key("pk").eq(f"TENANT#{tenant_id}") & Key("sk").begins_with("BILL#")
        )
        return resp.get("Items", [])

    def create_bill(self, tenant_id: str, data: dict) -> dict:
        bill_id = str(uuid.uuid4())
        item = {
            "pk": f"TENANT#{tenant_id}", "sk": f"BILL#{bill_id}",
            "bill_id": bill_id, "tenant_id": tenant_id,
            "vendor_name": data["vendor_name"], "amount": str(data["amount"]),
            "status": "pending", "due_date": data.get("due_date", ""),
            "created_by": data.get("created_by", ""), "created_at": _now(),
        }
        self.table.put_item(Item=item)
        return item

    def list_pending_approvals(self, tenant_id: str) -> list[dict]:
        resp = self.table.query(
            KeyConditionExpression=Key("pk").eq(f"TENANT#{tenant_id}") & Key("sk").begins_with("APPROVAL#")
        )
        return [i for i in resp.get("Items", []) if i.get("status") == "pending"]

    def approve(self, tenant_id: str, record_id: str) -> dict:
        resp = self.table.update_item(
            Key={"pk": f"TENANT#{tenant_id}", "sk": f"APPROVAL#{record_id}"},
            UpdateExpression="SET #s = :v",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={":v": "approved"},
            ReturnValues="ALL_NEW",
        )
        return resp.get("Attributes", {})

    def reject(self, tenant_id: str, record_id: str) -> dict:
        resp = self.table.update_item(
            Key={"pk": f"TENANT#{tenant_id}", "sk": f"APPROVAL#{record_id}"},
            UpdateExpression="SET #s = :v",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={":v": "rejected"},
            ReturnValues="ALL_NEW",
        )
        return resp.get("Attributes", {})

    def dashboard_summary(self, tenant_id: str) -> dict:
        invoices = self.list_invoices(tenant_id)
        bills = self.list_bills(tenant_id)
        approvals = self.list_pending_approvals(tenant_id)
        outstanding = sum(1 for i in invoices if i.get("status") != "paid")
        total_ar = sum(float(i.get("amount", 0)) for i in invoices if i.get("status") != "paid")
        bills_due = sum(1 for b in bills if b.get("status") == "pending")
        total_ap = sum(float(b.get("amount", 0)) for b in bills if b.get("status") == "pending")
        return {
            "outstanding_invoices": outstanding, "total_ar": total_ar,
            "bills_due": bills_due, "total_ap": total_ap,
            "pending_approvals": len(approvals), "cash_position": total_ar - total_ap,
        }
