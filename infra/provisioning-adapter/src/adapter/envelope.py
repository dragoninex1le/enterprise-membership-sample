"""The contract envelope — PROVISIONING-CONTRACT §2 (shape), §9 (outcomes), §10 (versions).

Every answer this adapter gives passes through here, so the two rules that are easiest to break
by hand are enforced in one place: a non-ok outcome always carries a reason code from the closed
list, and an ok outcome never does. The response schema rejects both mistakes, and so do the tests.
"""
from __future__ import annotations

import os
import re
import time

#: Every contract version this adapter can answer in. §4.1: "every version the adapter can speak,
#: not just the newest." PRF-19 adds 1.1.0 (the optional `slot`); until it publishes, 1.0.0 only.
CONTRACT_VERSIONS: tuple[str, ...] = ("1.0.0",)

#: The eight core verbs (ADR-P1 §4.1). A verb outside this list is still answered `unsupported`
#: rather than refused: C2 says every undeclared verb gets `unsupported`, not an opaque failure.
VERBS: tuple[str, ...] = (
    "capabilities", "bootstrap", "seed", "reset", "ensure", "absent", "teardown", "status",
)

_SEMVER = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")


class ContractError(Exception):
    """A non-ok answer: exactly the two things §9 requires, an outcome and a reason code."""

    def __init__(self, outcome: str, reason_code: str, message: str) -> None:
        super().__init__(message)
        self.outcome = outcome
        self.reason_code = reason_code
        self.message = message


def _parts(version: str) -> tuple[int, int, int]:
    major, minor, patch = (int(p) for p in version.split("."))
    return major, minor, patch


def negotiate(requested: object) -> str:
    """Pick the version to answer in (§10).

    Same major as the caller, and no newer than what the caller speaks — a 1.1.0 caller can be
    answered in 1.0.0, because a minor version only adds. A different major has no common
    version, and §10 says that is `refused` with `version_incompatible`, caught at run start.
    """
    if not isinstance(requested, str) or not _SEMVER.fullmatch(requested):
        raise ContractError(
            "refused", "version_incompatible",
            f"contract_version {requested!r} is not a semantic version",
        )
    want = _parts(requested)
    common = [v for v in CONTRACT_VERSIONS if _parts(v)[0] == want[0] and _parts(v) <= want]
    if not common:
        raise ContractError(
            "refused", "version_incompatible",
            f"no common contract version: the caller speaks {requested}, "
            f"this adapter speaks {', '.join(CONTRACT_VERSIONS)}",
        )
    return max(common, key=_parts)


def adapter_version() -> str:
    """The build identity (I6). Set at deploy from the commit; never a hand-typed number."""
    return os.environ.get("ADAPTER_VERSION") or "0.0.0-dev"


def _diagnostics(started: float, messages: list[str]) -> dict:
    return {
        "duration_ms": max(0, int((time.monotonic() - started) * 1000)),
        "messages": list(messages),
    }


def ok(version: str, results: list, started: float, messages: list[str] | None = None) -> dict:
    return {
        "contract_version": version,
        "adapter_version": adapter_version(),
        "outcome": "ok",
        "results": list(results),
        "diagnostics": _diagnostics(started, messages or []),
    }


def not_ok(version: str, error: ContractError, started: float) -> dict:
    return {
        "contract_version": version,
        "adapter_version": adapter_version(),
        "outcome": error.outcome,
        "reason_code": error.reason_code,
        "results": [],
        "diagnostics": _diagnostics(started, [error.message]),
    }
