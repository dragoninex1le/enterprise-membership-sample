"""`capabilities` — PROVISIONING-CONTRACT §4.1. The first call of every run.

**Identity comes from ground truth, never from the request.** The caller names a slot; this module
does not report that name back on the caller's say-so. The slot must exist in the target's own map,
and it must actually be bootstrapped — its platform tenant row present under `ENV#{scope}#` — or
the answer is `refused`. An adapter that echoed the requested slot would agree with the caller by
construction, and TAM §2.2's run-start check would compare the request against itself.

`environment_class` comes from the target's own map (D5). There is no request field for it, and
none is read.
"""
from __future__ import annotations

import os

import aws
import catalogue
import slots
from envelope import CONTRACT_VERSIONS, ContractError, adapter_version


def _confirm_bootstrapped(env_scope: str) -> None:
    table = os.environ["PORTH_TENANTS_TABLE"]
    pk = f"ENV#{env_scope}#TENANT#platform"
    try:
        # Tenants uses UPPERCASE PK/SK; permissions and roles use lowercase. Part of the shape.
        item = slots.data_session(env_scope).get_item(
            TableName=table,
            Key={"PK": {"S": pk}, "SK": {"S": "METADATA"}},
            ProjectionExpression="PK",
        ).get("Item")
    except Exception as e:  # noqa: BLE001 - any failure to read is an upstream failure, loudly
        raise ContractError(
            "failed", "upstream_error",
            f"could not read the platform tenant for scope {env_scope!r}: {type(e).__name__}",
        ) from e
    if not item:
        raise ContractError(
            "refused", "scope_violation",
            f"scope {env_scope!r} is not bootstrapped: no {pk} in {table}",
        )


def _candidate_version() -> tuple[str | None, str | None]:
    """The Porth release this slot is running, from the SAR stack's own tag."""
    try:
        stack = aws.client("cloudformation").describe_stacks(
            StackName=os.environ["PORTH_STACK_NAME"],
        )["Stacks"][0]
    except Exception as e:  # noqa: BLE001 - optional field; say why it is missing
        return None, f"candidate_version unavailable: {type(e).__name__} reading the Porth stack"
    tags = {t["Key"]: t["Value"] for t in stack.get("Tags", [])}
    version = tags.get("serverlessrepo:semanticVersion")
    if not version:
        return None, "candidate_version unavailable: the Porth stack has no serverlessrepo:semanticVersion tag"
    return version, None


def answer(slot_name: str, slot_cfg: dict) -> tuple[dict, list[str]]:
    _confirm_bootstrapped(slot_cfg["env_scope"])
    version, note = _candidate_version()

    environment = {"id": slot_cfg["environment_id"], "slot": slot_name}
    if version:
        environment["candidate_version"] = version

    result = {
        "contract_versions": list(CONTRACT_VERSIONS),
        "adapter_version": adapter_version(),
        "environment": environment,
        "environment_class": slot_cfg["environment_class"],
        "verbs": list(catalogue.INSTALL_VERBS),
        "entities": catalogue.declared(),
        "async": False,
    }
    return result, [note] if note else []
