"""prawf provisioning adapter for EMS — entry point (PRF-9).

Invoked directly by ARN (PROVISIONING-CONTRACT §1.1). There is no HTTP surface: the event IS the
request envelope, and the return value IS the response envelope. No API-Gateway wrapping in either
direction — one shape, so no caller ever has to double-decode.

Implemented: `capabilities` (PRF-9); `seed` and `teardown` on `porth-org` and `porth-tenant`
(PRF-12, PRF-15); `bootstrap` on `porth-platform` (PRF-11); and `reset` on `porth-claim-mapping`,
`porth-tenant` and `porth-org` (PRF-14).
Every other verb x entity answers `unsupported` with `not_implemented`, which prawf reads as "skip",
not "fail" (D3). That is the honest answer, and C1 forbids any other.

Order of checks, each the stronger failure first:
  1. the request is an envelope, in a contract version we share      -> refused
  2. the slot resolves to one this target serves                     -> refused
  3. a named entity is in the catalogue                               -> refused / unknown_entity
  4. the verb is implemented                                          -> unsupported
"""
from __future__ import annotations

import json
import time

import capabilities
import catalogue
import porth_org
import porth_platform
import porth_tenant
import reset
import slots
from envelope import CONTRACT_VERSIONS, VERBS, ContractError, negotiate, not_ok, ok


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


SEEDS = {porth_org.ENTITY: porth_org.seed, porth_tenant.ENTITY: porth_tenant.seed}
#: Ordered: an organisation cannot be removed while tenants belong to it.
TEARDOWNS = {porth_tenant.ENTITY: porth_tenant.teardown, porth_org.ENTITY: porth_org.teardown}

#: §3.4, C17: these carry entity-specific data, so omitting the entity is refused - there is nothing
#: to infer a destination from. Only teardown and reset may omit it.
NEEDS_ENTITY = ("bootstrap", "seed", "ensure", "absent")


def _dispatch(verb: str, entity: str | None, request: dict, slot_cfg: dict) -> tuple[list, list[str]]:
    """One implemented cell of the verb x entity matrix, or `unsupported` (C1, C2)."""
    if entity is None and verb in NEEDS_ENTITY:
        raise ContractError("refused", "unknown_entity", f"{verb} must name the entity it writes to (§3.4)")
    env_scope = slot_cfg["env_scope"]
    run = request.get("run") if isinstance(request.get("run"), dict) else {}
    run_id = run.get("run_id")
    payload = request.get("payload")
    if verb == "bootstrap" and entity == porth_platform.ENTITY:
        return porth_platform.bootstrap(env_scope, _run_id(run_id), bool(run.get("dry_run")), payload)
    # §3.4: reset may omit the entity too - every resettable entity, in reset.ORDER.
    if verb == "reset" and (entity is None or entity in reset.RESETS):
        return reset.reset(entity, slot_cfg, _run_id(run_id), bool(run.get("dry_run")), payload)
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
    version = CONTRACT_VERSIONS[-1]
    try:
        request = _envelope(event)
        version = negotiate(request["contract_version"])

        try:
            slot_map = slots.load()
        except Exception as e:  # noqa: BLE001 - the target's own config is broken: fail loudly
            raise ContractError(
                "failed", "upstream_error", f"the adapter's slot map is unusable: {e}",
            ) from e
        slot_name, slot_cfg = slots.resolve(slot_map, request.get("slot"))

        verb = request["verb"]
        if verb == "capabilities":
            result, notes = capabilities.answer(slot_name, slot_cfg)
            response = ok(version, [result], started, notes)
        else:
            entity = request.get("entity")
            if entity is not None and entity not in catalogue.IDS:
                raise ContractError(
                    "refused", "unknown_entity",
                    f"entity {entity!r} is not in this target's catalogue",
                )
            try:
                results, notes = _dispatch(verb, entity, request, slot_cfg)
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
            response = ok(version, results, started, notes)
    except ContractError as e:
        response = not_ok(version, e, started)

    _log(event, response)
    return response
