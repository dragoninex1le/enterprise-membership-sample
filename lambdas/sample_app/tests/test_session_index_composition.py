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


def test_there_is_no_catch_all_host_rule(template):
    """PORTH-655: a `*` rule matched every host nobody named — the API's raw
    execute-api URL included — and handed it Porth's role. Every host this
    install serves is named."""
    index = composer.compose(template, "dev", ENVIRONMENTS)
    patterns = [r["match"]["host_pattern"] for r in index["context_rules"]]
    assert "*" not in patterns, patterns


def test_the_index_matches_the_path_as_sent(template):
    """PORTH-655: "as_sent" — Porth's routes keep their /porth mapping key, so
    they cannot collide with this app's root-mapped routes, and nothing is bound
    at "/" for an unlisted app route to fall into."""
    index = composer.compose(template, "dev", ENVIRONMENTS)
    assert index["path_basis"] == "as_sent"
    assert not [k for k in index["bindings"] if k.partition(":")[2] in ("", "/")]


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


def test_porths_binding_names_porths_roles_on_the_branch_axis(template):
    """Porth's roles are named by its stack's Environment parameter — the
    CONFIGURATION axis — not by the ADR-Z8 slot. Every slot's Porth binding
    names the same `-dev` roles; fanning the name out would invent roles that do
    not exist."""
    index = composer.compose(template, "dev", ENVIRONMENTS)
    for env in ENVIRONMENTS:
        porth = index["bindings"][f"api-{env}:/porth"]
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


# --------------------------------------------------------------------------
# PORTH-656 — tenant-named API hosts
# --------------------------------------------------------------------------
#
# On a tenant-API-host slot the browser calls {tenant}.api.{slot}.{zone} (and
# api.{slot}.{zone} for the platform), and BOTH APIs answer on that one host:
# this app at the root, Porth under the `porth` mapping key. So the host alone
# cannot pick the binding any more; the path does, and the host's rule has to
# carry a binding for each.


def _api_rules(index, env):
    return [
        r for r in index["context_rules"]
        if r["match"]["host_pattern"] in (
            f"*.api.{env}.ems.estynsoftware.cloud", f"api.{env}.ems.estynsoftware.cloud"
        )
    ]


def test_each_environment_gets_both_api_host_rules(template):
    index = composer.compose(template, "dev", ENVIRONMENTS)
    for env in ENVIRONMENTS:
        rules = _api_rules(index, env)
        assert len(rules) == 2, (env, rules)
        assert {r["context_hint"] for r in rules} == {f"api-{env}"}


def test_on_an_api_host_the_path_picks_the_app_or_porth(template):
    """/sample → this app's role for THIS environment; /porth/... → Porth's role
    on the branch axis. Longest prefix on whole segments, no fallback, so both
    bindings have to exist."""
    index = composer.compose(template, "dev", ENVIRONMENTS)
    for env in ENVIRONMENTS:
        app = index["bindings"][f"api-{env}:/sample"]
        porth = index["bindings"][f"api-{env}:/porth"]
        assert app["role_arn"].endswith(f"-{env}"), app
        assert porth["role_arn"].endswith("-dev"), porth


def test_every_binding_has_an_auth_policy_prefix(template):
    """`porth-install policies apply` refuses an index whose bindings the
    auth-policy index does not cover — every request there would deny no_policy
    after its credentials were issued."""
    prefixes = json.loads((_ROOT / "deploy/porth/auth-policy/index.json").read_text())
    index = composer.compose(template, "dev", ENVIRONMENTS)
    for key in index["bindings"]:
        path = key.partition(":")[2].rstrip("/")
        assert any(path == p.rstrip("/") or path.startswith(p.rstrip("/") + "/") for p in prefixes) \
            or any(p.rstrip("/").startswith(path + "/") for p in prefixes), key
