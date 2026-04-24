from __future__ import annotations
from dataclasses import dataclass


@dataclass
class PorthContext:
    tenant_id: str
    user_id: str
    organization_id: str
    external_id: str
    roles: list[str]
    permissions: set[str]
    _dynamodb: object

    def has_permission(self, key: str) -> bool:
        return key in self.permissions

    @property
    def dynamodb(self):
        return self._dynamodb
