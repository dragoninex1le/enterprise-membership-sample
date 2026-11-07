"""The entity catalogue — PRF-9's deliverable (PROVISIONING-CONTRACT §3, ADR-P1 D12).

Each entry names an entity and maps it to the Porth resources behind it. `capabilities` projects
only the four fields the schema allows (`id`, `description`, `verbs`, `destructive`); the rest is
here so the mapping lives next to the code that will one day act on it, not in a document that
drifts from it.

**An entity declares only the verbs it implements.** Conformance C1: whatever is declared must be
genuinely implemented. PRF-9 declared `verbs: []` everywhere, with `["capabilities"]` the honest
install list (the schema's `minItems: 1`). Each slice flips one cell of the verb x entity matrix
from `[]` to implemented - PRF-12 and PRF-15 flipped `porth-tenant`'s `seed` and `teardown`, and PRF-20
`porth`'s `bootstrap`, `reset` and `prune`. `planned` records which
slice, and `ruled_out` records every verb that will never apply, with its reason — a verb ruled out
with a reason is a finding; a verb ruled out silently is a gap.

Key shapes: `{s}` is the slot's env_scope (ADR-Z8), `{tid}` a tenant id. Partition keys carry the
scope; sort keys never do. Attribute case differs by table and is part of the shape.

**`porth` is the install's baseline** (contract 1.1, PRF-20): every row of the slot in Porth's
tables, captured by `bootstrap` and restored by `reset` (snapshot.py). It is the only entity with a
`baseline_kind`, and the seed entities declare none - they hold only what prawf seeds, so no piece of
state is covered by two baselines. Reset is `porth`'s alone: returning the slot to its baseline is
what clears every seeded entity (Richard, 2026-11-05), so they no longer reset one by one.

**`porth-org` is its own entity** - the porth-org ruling, Option A (Richard, 2026-10-23). An
organisation is seeded before the tenants that belong to it, and torn down after them.

**A tenant's IdP config is part of the tenant**, not an entity of its own (Richard, 2026-10-25): it
is an attribute of the tenant row (`idp_config_override`), set with the tenant.
"""
from __future__ import annotations

from dataclasses import dataclass, field

#: Install-level verbs actually implemented, per contract version. A 1.0 call can bootstrap nothing:
#: the baseline needs an installed version, which only 1.1 can carry. Reset in 1.0 is porth-session's.
INSTALL_VERBS: tuple[str, ...] = ("capabilities", "seed", "reset", "teardown")
INSTALL_VERBS_1_1: tuple[str, ...] = ("capabilities", "bootstrap", "seed", "reset", "teardown", "prune")
VERBS_1_1_ONLY = ("prune",)


@dataclass(frozen=True)
class Entity:
    id: str
    description: str
    destructive: bool
    resources: tuple[str, ...]
    planned: dict[str, str] = field(default_factory=dict)
    ruled_out: dict[str, str] = field(default_factory=dict)
    verbs: tuple[str, ...] = ()
    #: Contract 1.1: `snapshot`, `definition`, or None for an entity holding only seeded data.
    baseline_kind: str | None = None
    #: Usable only in contract 1.1; a 1.0 answer declares it with no verbs.
    only_1_1: bool = False

    def declared(self, is_1_1: bool = False) -> dict:
        if is_1_1:
            verbs = list(self.verbs)
        elif self.only_1_1:
            verbs = []
        else:
            verbs = [v for v in self.verbs if v not in VERBS_1_1_ONLY]
        out = {"id": self.id, "description": self.description, "verbs": verbs, "destructive": self.destructive}
        if is_1_1 and self.baseline_kind:
            out["baseline_kind"] = self.baseline_kind
        return out


ENTITIES: tuple[Entity, ...] = (
    Entity(
        id="porth",
        description="The install's own Porth data in this slot, as the deploy left it. Contract 1.1.",
        destructive=True,
        resources=tuple(
            f"{t}: every row whose partition key starts ENV#{{s}}#, verbatim"
            for t in ("tenants", "roles", "permissions", "claim-mapping-configs", "users", "org-units")
        ),
        verbs=("bootstrap", "reset", "prune"),
        baseline_kind="snapshot",
        only_1_1=True,
        ruled_out={
            "seed": "an override of the baseline; not built yet",
            "teardown": "the baseline is no run's fixture; nothing here is labelled with a run",
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
            "users: PK=ENV#{s}#TENANT#{tid}#USER#{uuid}, removed by reset and teardown (Porth creates them at login)",
            "roles: pk=ENV#{s}#TENANT#{tid}#USER#{uuid} sk=ROLE#{uuid} (a user's role assignment), removed with the user",
            "org-units: PK=ENV#{s}#TENANT#{tid} sk=ORG_UNIT#{uuid}, removed by reset and teardown",
        ),
        verbs=("seed", "teardown"),
    ),
    Entity(
        id="porth-session",
        description="Porth's login sessions. Reset clears the whole table, in every environment.",
        destructive=True,
        resources=("sessions: the whole table. Its keys carry no environment, so this is not held to a slot",),
        verbs=("reset",),
    ),
    Entity(
        id="porth-org",
        description="An organisation for fixture tenants. Seeded before them, torn down after them.",
        destructive=True,
        resources=("tenants: PK=ENV#{s}#ORG#{uuid} SK=METADATA, gsi1pk=ENV#{s}#ORG_SLUG#{slug}",),
        verbs=("seed", "teardown"),
    ),
    Entity(
        id="porth-claim-mapping",
        description="A tenant's versioned claim-mapping configuration.",
        destructive=True,
        resources=(
            "claim-mapping-configs: PK=ENV#{s}#TENANT#{tid} SK=VERSION#{n:06d} (compiled_hash computed, never supplied)",
        ),
        verbs=("seed", "teardown"),
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
        description="Permissions added to a role the seed does not own, such as tenant-admin. Unioned, never "
                    "replaced. A seeded role's own grants are porth-role's.",
        destructive=True,
        resources=(
            "roles: pk=ENV#{s}#TENANT#{tid}#ROLE#{uuid} sk=PERM#{key} (PORTH-604 tenant-leading; PORTH-609 union)",
        ),
        planned={"ensure": "Track 2", "absent": "Track 2"},
    ),
    Entity(
        id="porth-role",
        description="The application's roles and the permissions they link to, and arranged roles such as one "
                    "with no grants for a denial test. A grant must name a permission the install already has.",
        destructive=True,
        resources=("roles: pk=ENV#{s}#TENANT#{tid} sk=ROLE#{uuid} (not a system role)",
                   "roles: pk=ENV#{s}#TENANT#{tid}#ROLE#{uuid} sk=PERM#{key} (its grants)"),
        # PRF-18 seeds roles (never system roles) with their grants; reset of `porth` removes them with the rest.
        verbs=("seed", "teardown"),
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


def declared(is_1_1: bool = False) -> list[dict]:
    """The catalogue as `capabilities` reports it, in the contract version it is answered in."""
    return [e.declared(is_1_1) for e in ENTITIES]
