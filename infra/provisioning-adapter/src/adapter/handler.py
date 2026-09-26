"""prawf provisioning adapter for EMS — entry point (PRF-9).

Invoked directly by ARN (PROVISIONING-CONTRACT §1.1). There is no HTTP surface: the event IS the
request envelope, and the return value IS the response envelope. No API-Gateway wrapping in either
direction — one shape, so no caller ever has to double-decode.

This slice implements `capabilities` and nothing else. Every other verb answers `unsupported` with
`not_implemented`, which prawf reads as "skip", not "fail" (D3). That is the honest answer, and C1
forbids any other.

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
            raise ContractError(
                "unsupported", "not_implemented",
                f"verb {verb!r} is not implemented by this adapter at this version",
            )
    except ContractError as e:
        response = not_ok(version, e, started)

    _log(event, response)
    return response
