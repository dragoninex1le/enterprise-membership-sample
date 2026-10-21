"""The session-policy index binds this app's host to this app's role.

Composed by ``deploy/porth/scripts/compose_session_index.py`` and seeded by
EMS's own ``porth-install.yml``. Tested here because the failure it guards
against is not a crash: an index the authorizer cannot resolve does not deny
the request, it falls through to the tenant role with NO session policy — the
role's full ceiling, every tenant readable. PORTH-550 is that bug, found in
production, and the reason these assertions exist rather than a schema check.

The authorizer substitutes ``${role_type}``, ``{account}`` and ``{region}`` into
a binding's ARNs and nothing else. There is no ``$env``, so two environments
cannot share a binding — which is the whole reason this file composes rather
than renders (PORTH-627).
"""
from __future__ import annotations

import importlib.util
import json
import pathlib

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[3]
_TEMPLATE = _ROOT / "deploy" / "porth" / "session-policy" / "index.template.json"
_SCRIPT = _ROOT / "deploy" / "porth" / "scripts" / "compose_session_index.py"

_spec = importlib.util.spec_from_file_location("compose_session_index", _SCRIPT)
composer = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(composer)


@pytest.fixture
def template() -> dict:
    return json.loads(_TEMPLATE.read_text())


ENVIRONMENTS = ["porth-sample", "porth-dau"]


def test_each_environment_gets_its_own_host_rule(template):
    index = composer.compose(template, "dev", ENVIRONMENTS)
    hosts = [r["match"]["host_pattern"] for r in index["context_rules"]]

    for env in ENVIRONMENTS:
        assert f"sample-api.{env}.ems.estynsoftware.cloud" in hosts


def test_the_catch_all_stays_last(template):
    """`_resolve_context_hint` returns the FIRST pattern that matches.

    The `*` rule matches every host, so above a specific one it swallows it —
    the sample app's requests would resolve Porth's binding, get Porth's role,
    and be refused on this app's table with a denial naming the wrong role. The
    composer expands in place to preserve template order; this is what says so.
    """
    index = composer.compose(template, "dev", ENVIRONMENTS)
    patterns = [r["match"]["host_pattern"] for r in index["context_rules"]]

    assert patterns[-1] == "*", patterns
    assert patterns.count("*") == 1, patterns


def test_no_two_environments_share_a_role(template):
    """The point of the whole change. One role per environment, and the
    partition prefix its session policy narrows to is derived from the same
    word — so a shared role here would silently un-separate the data."""
    index = composer.compose(template, "dev", ENVIRONMENTS)
    app = {k: v for k, v in index["bindings"].items() if k.startswith("sample-")}

    assert len(app) == len(ENVIRONMENTS)
    arns = [b["role_arn"] for b in app.values()]
    assert len(set(arns)) == len(arns), arns
    for env in ENVIRONMENTS:
        assert any(env in a for a in arns), env


def test_porths_own_binding_is_emitted_once_on_the_branch_axis(template):
    """Porth's roles are named by its stack's Environment parameter — the
    CONFIGURATION axis — not by the ADR-Z8 slot. One binding, `dev`, however
    many environments there are. Fanning this one out too would invent roles
    that do not exist."""
    index = composer.compose(template, "dev", ENVIRONMENTS)
    porth = index["bindings"]["porth:/"]

    assert porth["role_arn"].endswith("-dev")
    assert not any(e in porth["role_arn"] for e in ENVIRONMENTS)


def test_nothing_unrendered_survives(template):
    index = composer.compose(template, "dev", ENVIRONMENTS)
    assert not composer.PLACEHOLDER.findall(json.dumps(index))


def test_an_empty_environment_list_is_refused():
    """Not a defaulting decision — a refusal.

    With no environments the app's rule and binding vanish, every host falls to
    the `*` catch-all, and the app's requests resolve Porth's binding. That
    renders as valid JSON and seeds without complaint, which is exactly why it
    has to fail here.
    """
    with pytest.raises(SystemExit):
        composer.main(["compose", str(_TEMPLATE), "ENV=dev", "ENVIRONMENTS="])
