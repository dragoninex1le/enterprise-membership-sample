"""prawf provisioning adapter for EMS — entry point (PRF-9).

Invoked directly by ARN (PROVISIONING-CONTRACT §1.1). There is no HTTP surface: the event IS the
request envelope, and the return value IS the response envelope. No API-Gateway wrapping in either
direction — one shape, so no caller ever has to double-decode.

Implemented: `capabilities` (PRF-9); `seed` and `teardown` on `porth-org`, `porth-tenant`,
`porth-claim-mapping` and `porth-role` (PRF-12, PRF-13, PRF-15, PRF-18); `reset` on `porth-session`;
and, in contract 1.1 only, `bootstrap`, `reset` and `prune` on `porth` - the install's snapshot
baseline (PRF-20, snapshot.py).
Every other verb x entity answers `unsupported` with `not_implemented`, which prawf reads as "skip",
not "fail" (D3). That is the honest answer, and C1 forbids any other.

Order of checks, each the stronger failure first:
  1. the request is an envelope, in a contract version we share      -> refused
  2. in 1.1, a verb that writes names its slot                        -> refused / slot_required
  3. the slot resolves to one this target serves                     -> refused
  4. a named entity is in the catalogue                               -> refused / unknown_entity
  5. the verb is implemented                                          -> unsupported
"""
from __future__ import annotations

import json
import time

import capabilities
import catalogue
import porth_claim_mapping
import porth_org
import porth_role
import porth_tenant
import reset
import slots
import snapshot
from envelope import V1_0, VERBS, WRITE_VERBS, ContractError, Version, negotiate, not_ok, ok


def _envelope(event: object) -> dict:
    if not isinstance(event, dict) or "contract_version" not in event or "verb" not in event:
        # The closed reason-code list has no code for "this is not an envelope". A caller that
        # cannot produce one shares no contract version with us, which is the nearest honest code.
        raise ContractError(
            "refused", "version_incompatible",
            "the request is not a contract envelope: expected an object with contract_version and verb",
        )
    return event


def _log(request: object, response: dict) -> None:
    # Outcome only — never payload contents, which in later slices carry emails and IdP config.
    verb = request.get("verb") if isinstance(request, dict) else None
    print(json.dumps({
        "verb": verb if verb in VERBS else "<other>",
        "slot": request.get("slot") if isinstance(request, dict) else None,
        "outcome": response["outcome"],
        "reason_code": response.get("reason_code"),
        "duration_ms": response["diagnostics"]["duration_ms"],
    }))


SEEDS = {porth_org.ENTITY: porth_org.seed, porth_tenant.ENTITY: porth_tenant.seed,
         porth_claim_mapping.ENTITY: porth_claim_mapping.seed, porth_role.ENTITY: porth_role.seed}
#: Ordered: arranged roles and the claim mapping go before their tenant, a tenant before its organisation.
TEARDOWNS = {porth_role.ENTITY: porth_role.teardown, porth_claim_mapping.ENTITY: porth_claim_mapping.teardown,
             porth_tenant.ENTITY: porth_tenant.teardown, porth_org.ENTITY: porth_org.teardown}

#: §3.4, C17: these carry entity-specific data, so omitting the entity is refused - there is nothing
#: to infer a destination from. Only teardown may omit it. Reset may not: `porth` declares a baseline,
#: and contract 1.1 refuses the every-entity form when any addressed entity does.
NEEDS_ENTITY = ("bootstrap", "seed", "ensure", "absent", "reset", "prune")
#: The snapshot baseline exists only in contract 1.1: a 1.0 call has no way to name a version or a baseline.
BASELINE_VERBS = ("bootstrap", "reset", "prune")


def _dispatch(verb: str, entity: str | None, request: dict, slot_cfg: dict, version: Version) -> tuple[list, list[str]]:
    """One implemented cell of the verb x entity matrix, or `unsupported` (C1, C2)."""
    if entity is None and verb in NEEDS_ENTITY:
        raise ContractError("refused", "unknown_entity", f"{verb} must name the entity it writes to (§3.4)")
    env_scope = slot_cfg["env_scope"]
    run = request.get("run") if isinstance(request.get("run"), dict) else {}
    run_id = run.get("run_id")
    payload = request.get("payload")
    dry_run = bool(run.get("dry_run"))
    if entity == snapshot.ENTITY and verb in BASELINE_VERBS:
        if not version.is_1_1:
            raise ContractError(
                "refused", "version_incompatible",
                f"{verb} on {snapshot.ENTITY} is contract 1.1: a {version} call cannot name an installed version or a baseline",
            )
        if verb == "bootstrap":
            return snapshot.bootstrap(env_scope, _run_id(run_id), dry_run, payload)
        if verb == "prune":
            return snapshot.prune(env_scope, _run_id(run_id), dry_run, payload)
    if verb == "reset" and entity in reset.RESETS:
        return reset.reset(entity, slot_cfg, _run_id(run_id), dry_run, payload)
    if verb == "seed" and entity in SEEDS:
        return SEEDS[entity](env_scope, _run_id(run_id), bool(run.get("dry_run")), payload)
    # §3.4: teardown may omit the entity, meaning every entity that supports it - in TEARDOWN order,
    # tenants before the organisations they belong to.
    if verb == "teardown" and (entity is None or entity in TEARDOWNS):
        target = payload.get("run_id") if isinstance(payload, dict) else None
        if not isinstance(target, str) or not target:
            raise ContractError("refused", "scope_violation", "teardown needs payload.run_id: the run whose writes to remove")
        results, notes = [], []
        for name, fn in TEARDOWNS.items():
            if entity in (None, name):
                r, n = fn(env_scope, _run_id(run_id), target)
                results += r
                notes += n
        return results, notes
    raise ContractError(
        "unsupported", "not_implemented",
        f"verb {verb!r} is not implemented by this adapter at this version"
        + (f" for entity {entity!r}" if entity else ""),
    )


def _run_id(value: object) -> str:
    # D6: everything written is labelled with the run. Without one there is no label to write.
    if not isinstance(value, str) or not value:
        raise ContractError("refused", "scope_violation", "a mutating call needs run.run_id (§2.1)")
    return value


def handler(event, context):  # noqa: ARG001 - Lambda signature
    started = time.monotonic()
    version = Version(V1_0, three_part=True)
    environment = None
    try:
        request = _envelope(event)
        version = negotiate(request["contract_version"])
        verb = request["verb"]
        if version.is_1_1 and verb in WRITE_VERBS and request.get("slot") is None:
            raise ContractError(
                "refused", "slot_required",
                f"{verb} writes or deletes, so it must name its slot - even on a target that serves one",
            )

        try:
            slot_map = slots.load()
        except Exception as e:  # noqa: BLE001 - the target's own config is broken: fail loudly
            raise ContractError(
                "failed", "upstream_error", f"the adapter's slot map is unusable: {e}",
            ) from e
        slot_name, slot_cfg = slots.resolve(slot_map, request.get("slot"), version)
        environment = {"id": slot_cfg["environment_id"], "slot": slot_name}

        if verb == "capabilities":
            result, notes = capabilities.answer(slot_name, slot_cfg, version)
            response = ok(version, [result], started, notes, environment)
        else:
            entity = request.get("entity")
            if entity is not None and entity not in catalogue.IDS:
                raise ContractError(
                    "refused", "unknown_entity",
                    f"entity {entity!r} is not in this target's catalogue",
                )
            try:
                results, notes = _dispatch(verb, entity, request, slot_cfg, version)
            except ContractError:
                raise
            except Exception as e:  # noqa: BLE001 - silence is never an outcome (§9)
                # Porth's code raised part way. The ledger was written ahead of every write, so the
                # run can still be torn down; say so, and say what failed - never a credential, which
                # boto's messages do not carry.
                raise ContractError(
                    "failed", "upstream_error",
                    f"{verb} on {entity or 'every entity'} failed part way: {type(e).__name__}: {str(e)[:300]}. "
                    "Anything written is labelled with the run; tear it down to remove it.",
                ) from e
            response = ok(version, results, started, notes, environment)
    except ContractError as e:
        response = not_ok(version, e, started, environment)

    _log(event, response)
    return response
