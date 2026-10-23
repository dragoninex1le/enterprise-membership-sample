"""The entity catalogue — PRF-9's deliverable (PROVISIONING-CONTRACT §3, ADR-P1 D12).

Each entry names an entity and maps it to the Porth resources behind it. `capabilities` projects
only the four fields the schema allows (`id`, `description`, `verbs`, `destructive`); the rest is
here so the mapping lives next to the code that will one day act on it, not in a document that
drifts from it.

**An entity declares only the verbs it implements.** Conformance C1: whatever is declared must be
genuinely implemented. PRF-9 declared `verbs: []` everywhere, with `["capabilities"]` the honest
install list (the schema's `minItems: 1`). Each slice flips one cell of the verb x entity matrix
from `[]` to implemented - PRF-12 and PRF-15 flipped `porth-tenant`'s `seed` and `teardown`. `planned` records which
slice, and `ruled_out` records every verb that will never apply, with its reason — a verb ruled out
with a reason is a finding; a verb ruled out silently is a gap.

Key shapes: `{s}` is the slot's env_scope (ADR-Z8), `{tid}` a tenant id. Partition keys carry the
scope; sort keys never do. Attribute case differs by table and is part of the shape.

**`porth-org` is its own entity** - the porth-org ruling, Option A (Richard, 2026-10-23). An
organisation is seeded before the tenants that belong to it, and torn down after them.
"""
from __future__ import annotations

from dataclasses import dataclass, field

#: Install-level verbs actually implemented. Grows one verb at a time, with the slice that adds it.
INSTALL_VERBS: tuple[str, ...] = ("capabilities", "seed", "teardown")


@dataclass(frozen=True)
class Entity:
    id: str
    description: str
    destructive: bool
    resources: tuple[str, ...]
    planned: dict[str, str] = field(default_factory=dict)
    ruled_out: dict[str, str] = field(default_factory=dict)
    verbs: tuple[str, ...] = ()

    def declared(self) -> dict:
        return {
            "id": self.id,
            "description": self.description,
            "verbs": list(self.verbs),
            "destructive": self.destructive,
        }


ENTITIES: tuple[Entity, ...] = (
    Entity(
        id="porth-platform",
        description="Porth-installed platform state. Verified, never written.",
        destructive=False,
        resources=(
            "tenants: PK=ENV#{s}#ORG#{uuid} SK=METADATA (platform org)",
            "tenants: PK=ENV#{s}#TENANT#platform SK=METADATA (role_type=platform-admin is load-bearing, PORTH-585)",
            "permissions: pk=ENV#{s}#TENANT#platform#NS#porth-platform sk=PERM#{key}",
            "roles: pk=ENV#{s}#TENANT#platform sk=ROLE#{uuid} (platform-admin)",
            "roles: pk=ENV#{s}#TENANT#platform#ROLE#{uuid} sk=PERM#{key} (grants)",
        ),
        planned={"bootstrap": "PRF-11 - dry_run only: verify the install, write nothing"},
        ruled_out={
            "reset": "resetting the platform tenant breaks every subsequent sign-in, including the one that would report it",
            "seed": "porth-install owns this data; the adapter verifies it",
            "teardown": "nothing here is created by a run",
        },
    ),
    Entity(
        id="porth-tenant",
        description="A tenant beyond the install's own template, as a test fixture.",
        destructive=True,
        resources=(
            "tenants: PK=ENV#{s}#TENANT#{tid} SK=METADATA (in an existing porth-org)",
            "roles: pk=ENV#{s}#TENANT#{tid} sk=ROLE#{uuid} (tenant-admin) + pk=...#ROLE#{uuid} sk=PERM#{key}",
            "permissions: pk=ENV#{s}#TENANT#{tid}#NS#porth-tenant sk=PERM#{key}",
        ),
        planned={"reset": "PRF-14"},
        verbs=("seed", "teardown"),
    ),
    Entity(
        id="porth-org",
        description="An organisation for fixture tenants. Seeded before them, torn down after them.",
        destructive=True,
        resources=("tenants: PK=ENV#{s}#ORG#{uuid} SK=METADATA, gsi1pk=ENV#{s}#ORG_SLUG#{slug}",),
        verbs=("seed", "teardown"),
    ),
    Entity(
        id="porth-idp-config",
        description="Porth's stored record of a tenant's IdP. Not the IdP itself.",
        destructive=True,
        resources=(
            "tenants: PK=ENV#{s}#TENANT#{tid} SK=METADATA, attribute idp_config_override",
        ),
        planned={"seed": "PRF-12/13 area", "reset": "PRF-14"},
        # Shares a physical item with porth-tenant. Both must write with UpdateItem on disjoint
        # attributes: a PutItem from either would erase the other's half of the row.
    ),
    Entity(
        id="porth-claim-mapping",
        description="A tenant's versioned claim-mapping configuration.",
        destructive=True,
        resources=(
            "claim-mapping-configs: PK=ENV#{s}#TENANT#{tid} SK=VERSION#{n:06d} (compiled_hash computed, never supplied)",
        ),
        planned={"seed": "PRF-13", "reset": "PRF-14"},
    ),
    Entity(
        id="porth-app-permission",
        description="An application's own permission catalogue, in its own namespace.",
        destructive=True,
        resources=(
            "permissions: pk=ENV#{s}#TENANT#{tid}#NS#{app} sk=PERM#{key}",
        ),
        planned={"seed": "Track 2", "absent": "Track 2"},
    ),
    Entity(
        id="porth-role-grant",
        description="Application permissions bound to a role. Unioned, never replaced.",
        destructive=True,
        resources=(
            "roles: pk=ENV#{s}#TENANT#{tid}#ROLE#{uuid} sk=PERM#{key} (PORTH-604 tenant-leading; PORTH-609 union)",
        ),
        planned={"ensure": "Track 2", "absent": "Track 2"},
    ),
    Entity(
        id="porth-role",
        description="Arranged roles, such as a role with no grants for a denial test.",
        destructive=True,
        resources=("roles: pk=ENV#{s}#TENANT#{tid} sk=ROLE#{uuid}",),
        planned={"ensure": "PRF-18", "absent": "PRF-18"},
    ),
    Entity(
        id="porth-idp",
        description="The identity provider itself. Unreachable from this account.",
        destructive=False,
        resources=("Auth0 users, Organizations and role assignments - provider Management API",),
        ruled_out={
            verb: "needs the provider's Management API, which does not live in the EMS account"
            for verb in ("bootstrap", "seed", "reset", "ensure", "absent", "teardown")
        },
    ),
)

IDS: frozenset[str] = frozenset(e.id for e in ENTITIES)


def declared() -> list[dict]:
    """The catalogue as `capabilities` reports it."""
    return [e.declared() for e in ENTITIES]
