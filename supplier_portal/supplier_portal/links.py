"""Buyer links: which EMS tenant a SupplierLink buyer account belongs to.

When a tenant admin links their buyer account, this records the link together with
the tenant's ``PersistedContext``, captured from that admin's own request. When a
supplier later presents an assertion naming the buyer, the session is minted in the
tenant this row names — never one the request names.

The context is trustworthy because of where it lives: only this function's role can
write this table (template.yml), and it writes only from an authenticated tenant
admin. A buyer account links to one tenant; another tenant claiming it is refused.

    pk  BUYER#{buyer}      tenant, porth_context, linked_by, linked_at
    tenant_pk TENANT#{t}   (index ``by_tenant``)
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from boto3.dynamodb.conditions import Key


class ClaimedByAnotherTenant(Exception):
    pass


@dataclass(frozen=True)
class BuyerLink:
    buyer: str
    tenant: str
    porth_context: str
    linked_by: str
    linked_at: str

    def shown(self) -> dict[str, str]:
        return {"buyer": self.buyer, "linked_by": self.linked_by, "linked_at": self.linked_at}


class Links:
    def __init__(self, table: Any = None) -> None:
        if table is None:
            import boto3

            table = boto3.resource("dynamodb").Table(os.environ["BUYER_LINKS_TABLE"])
        self.table = table

    @staticmethod
    def _row(item: dict[str, Any]) -> BuyerLink:
        return BuyerLink(buyer=item["buyer"], tenant=item["tenant"], porth_context=item["porth_context"],
                         linked_by=item.get("linked_by", ""), linked_at=item.get("linked_at", ""))

    def find(self, buyer: str) -> BuyerLink | None:
        item = self.table.get_item(Key={"pk": f"BUYER#{buyer}"}).get("Item")
        return self._row(item) if item else None

    def of_tenant(self, tenant: str) -> list[BuyerLink]:
        found = self.table.query(IndexName="by_tenant", KeyConditionExpression=Key("tenant_pk").eq(f"TENANT#{tenant}"))
        return [self._row(i) for i in found.get("Items", [])]

    def link(self, *, buyer: str, tenant: str, porth_context: str, by: str) -> BuyerLink:
        from botocore.exceptions import ClientError

        item = {"pk": f"BUYER#{buyer}", "tenant_pk": f"TENANT#{tenant}", "buyer": buyer, "tenant": tenant,
                "porth_context": porth_context, "linked_by": by,
                "linked_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        try:
            self.table.put_item(Item=item, ConditionExpression="attribute_not_exists(pk) OR tenant = :me",
                                ExpressionAttributeValues={":me": tenant})
        except ClientError as exc:
            if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
                raise ClaimedByAnotherTenant(buyer) from exc
            raise
        return self._row(item)

    def unlink(self, *, buyer: str, tenant: str) -> bool:
        from botocore.exceptions import ClientError

        try:
            self.table.delete_item(Key={"pk": f"BUYER#{buyer}"}, ConditionExpression="tenant = :me",
                                   ExpressionAttributeValues={":me": tenant})
            return True
        except ClientError as exc:
            if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
                return False
            raise
