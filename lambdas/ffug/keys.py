"""ffug key shapes — ONE definition, used by both the request path and the bus.

ADR-Z8: tenant isolation is a property of the key, not of a code check. Every
row sits under ``ENV#{environment}#TENANT#{tenant_id}``, which is what the
``dynamodb:LeadingKeys`` condition on the narrowed session binds to.

This module exists because of the standing note in Porth's EMS upgrade log:
seven of its entries are the same shape — a value fixed at one site and missed
at its sibling, both in the same directory. ``handler.py`` and ``lifecycle.py``
write to the same partitions from opposite directions; a second copy of the key
format is exactly how one of them silently stops matching the other, and the
symptom would be an empty read rather than an error.
"""

from __future__ import annotations

#: The tenant's projection row — status, and the salt the digest is built from.
#: Deliberately the bare partition with a fixed sort key: it is one bounded row
#: per tenant (non-transient reference data), read by exact key, never scanned.
PROJECTION_SK = "PROJECTION"

#: Prefix for the transient echo rows. Purged wholesale on ``tenant.deleted``.
ITEM_SK_PREFIX = "ITEM#"


def partition(environment: str, tenant_id: str) -> str:
    """The partition every row for this tenant in this environment sits under."""
    return f"ENV#{environment}#TENANT#{tenant_id}"


def projection_key(environment: str, tenant_id: str) -> dict[str, str]:
    return {"pk": partition(environment, tenant_id), "sk": PROJECTION_SK}


def item_key(environment: str, tenant_id: str, item_id: str) -> dict[str, str]:
    return {"pk": partition(environment, tenant_id), "sk": f"{ITEM_SK_PREFIX}{item_id}"}
