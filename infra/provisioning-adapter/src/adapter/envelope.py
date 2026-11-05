"""The contract envelope — PROVISIONING-CONTRACT §2 (shape), §9 (outcomes), §10 (versions), and the
addendum v1.1 (Confluence 74448898): two-part versions, `prune`, and `environment` on every 1.1 answer.

Every answer this adapter gives passes through here, so the two rules that are easiest to break
by hand are enforced in one place: a non-ok outcome always carries a reason code from the closed
list, and an ok outcome never does. The response schema rejects both mistakes, and so do the tests.
"""
from __future__ import annotations

import os
import re
import time

#: Every contract version this adapter can answer in, as (major, minor). §4.1: "every version the
#: adapter can speak, not just the newest." Contract 1.1 (Confluence 74448898) made the version two
#: parts. A caller still sending three parts speaks the 1.0 schemas, which know nothing of 1.1, so it
#: is answered in "1.0.0" whatever minor it names; a two-part caller is negotiated up to 1.1.
SPOKEN: tuple[tuple[int, int], ...] = ((1, 0), (1, 1))
V1_0, V1_1 = SPOKEN

#: The core verbs (ADR-P1 §4.1), plus `prune` from contract 1.1. A verb outside this list is still
#: answered `unsupported` rather than refused: C2 says every undeclared verb gets `unsupported`.
VERBS_1_0: tuple[str, ...] = (
    "capabilities", "bootstrap", "seed", "reset", "ensure", "absent", "teardown", "status",
)
VERBS: tuple[str, ...] = VERBS_1_0 + ("prune",)
#: Contract 1.1: every verb that writes or deletes must name its slot, even on a one-slot target.
WRITE_VERBS: tuple[str, ...] = ("bootstrap", "seed", "reset", "ensure", "absent", "teardown", "prune")

_VERSION = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)(?:\.(0|[1-9]\d*))?$")


class ContractError(Exception):
    """A non-ok answer: exactly the two things §9 requires, an outcome and a reason code."""

    def __init__(self, outcome: str, reason_code: str, message: str) -> None:
        super().__init__(message)
        self.outcome = outcome
        self.reason_code = reason_code
        self.message = message


class Version(str):
    """The version a call is answered in: the string that goes on the wire, and what it speaks."""

    parts: tuple[int, int]

    def __new__(cls, parts: tuple[int, int], three_part: bool) -> "Version":
        text = f"{parts[0]}.{parts[1]}" + (".0" if three_part else "")
        v = super().__new__(cls, text)
        v.parts = parts
        return v

    @property
    def is_1_1(self) -> bool:
        return self.parts >= V1_1


def spoken(three_part: bool = True) -> list[str]:
    """`contract_versions` for capabilities, in the form the answering version uses."""
    if three_part:
        return [f"{a}.{b}.0" for a, b in SPOKEN if (a, b) == V1_0]
    return [f"{a}.{b}" for a, b in SPOKEN]


def negotiate(requested: object) -> Version:
    """Pick the version to answer in (§10).

    Same major as the caller, and no newer than what the caller speaks - a minor version only adds.
    A different major has no common version: `refused` with `version_incompatible`.
    """
    m = _VERSION.fullmatch(requested) if isinstance(requested, str) else None
    if not m:
        raise ContractError(
            "refused", "version_incompatible",
            f"contract_version {requested!r} is not MAJOR.MINOR (or MAJOR.MINOR.PATCH for 1.0)",
        )
    three_part = m.group(3) is not None
    want = (int(m.group(1)), 0 if three_part else int(m.group(2)))
    common = [v for v in SPOKEN if v[0] == want[0] and v <= want]
    if not common:
        raise ContractError(
            "refused", "version_incompatible",
            f"no common contract version: the caller speaks {requested}, "
            f"this adapter speaks {', '.join(spoken(False))}",
        )
    return Version(max(common), three_part=three_part)


def adapter_version() -> str:
    """The build identity (I6). Set at deploy from the commit; never a hand-typed number."""
    return os.environ.get("ADAPTER_VERSION") or "0.0.0-dev"


def _diagnostics(started: float, messages: list[str]) -> dict:
    return {
        "duration_ms": max(0, int((time.monotonic() - started) * 1000)),
        "messages": list(messages),
    }


def _where(version: str, environment: dict | None) -> dict:
    # Contract 1.1: every response says where it acted. A 1.0 response has no field for it.
    if environment and getattr(version, "is_1_1", False):
        return {"environment": dict(environment)}
    return {}


def ok(version: str, results: list, started: float, messages: list[str] | None = None,
       environment: dict | None = None) -> dict:
    return {
        "contract_version": str(version),
        "adapter_version": adapter_version(),
        "outcome": "ok",
        **_where(version, environment),
        "results": list(results),
        "diagnostics": _diagnostics(started, messages or []),
    }


def not_ok(version: str, error: ContractError, started: float, environment: dict | None = None) -> dict:
    return {
        "contract_version": str(version),
        "adapter_version": adapter_version(),
        "outcome": error.outcome,
        "reason_code": error.reason_code,
        **_where(version, environment),
        "results": [],
        "diagnostics": _diagnostics(started, [error.message]),
    }
