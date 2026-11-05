"""`capabilities` — PROVISIONING-CONTRACT §4.1. The first call of every run.

**Identity comes from the target's own configuration, never from the request.** The caller names a
slot; the slot must be in the target's own map, and what is reported is that entry - its
environment id and class (D5) - not the caller's words. There is no request field for the class, and
none is read.

Whether a slot is *bootstrapped* is no longer judged here. That judgement used to be "the platform
tenant row exists", which is a guess about what an install contains (Richard, 2026-11-05). A slot is
bootstrapped for prawf when prawf holds a current baseline for its deployed version - prawf's record,
not the adapter's.

Contract 1.1 adds each entity's `baseline_kind` and the `prune` verb; a 1.0 answer carries neither,
and declares the 1.1-only `porth` entity with no verbs (C1: nothing declared that a 1.0 call can use).
"""
from __future__ import annotations

import os

import aws
import catalogue
import datasets
from envelope import adapter_version, spoken


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


def answer(slot_name: str, slot_cfg: dict, contract: object = None) -> tuple[dict, list[str]]:
    is_1_1 = bool(getattr(contract, "is_1_1", False))
    version, note = _candidate_version()

    environment = {"id": slot_cfg["environment_id"], "slot": slot_name}
    if version:
        environment["candidate_version"] = version

    result = {
        "contract_versions": spoken(three_part=not is_1_1),
        "adapter_version": adapter_version(),
        "environment": environment,
        "environment_class": slot_cfg["environment_class"],
        "verbs": list(catalogue.INSTALL_VERBS_1_1 if is_1_1 else catalogue.INSTALL_VERBS),
        "entities": catalogue.declared(is_1_1),
        "resource_types": ["tenant"],
        # What the seed entities write, beyond the core `tenant`.
        "extension_types": ["porth.org", "porth.role", "porth.claim-mapping"],
        "dataset_forms": list(datasets.FORMS),
        "async": False,
    }
    return result, [note] if note else []
