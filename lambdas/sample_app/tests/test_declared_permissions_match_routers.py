"""The declared permissions must be the ones the app enforces (PORTH-610).

deploy/sample-app/permissions.json is what the deploy hands to `porth-install
register-permissions`. Its keys and the routers' require_permission(...) calls
are two statements of the same fact, and the failure mode when they drift is
one-directional and quiet:

* a key enforced but never declared -> the page 403s for everyone, forever, and
  no amount of granting fixes it because the permission does not exist;
* a key declared but never enforced -> a permission appears in the admin UI that
  controls nothing.

Neither shows up in Porth's logs, because Porth allowed the request — the app
refused it. So the two lists are compared here rather than by eye.

deploy/sample-app/roles.json (the business roles a tenant seeder creates) is
held to the same declaration: a role granted a key that is not declared would
be granted nothing.
"""
from __future__ import annotations

import json
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[3]
ROUTERS = ROOT / "lambdas" / "sample_app" / "routers"
DECLARED = ROOT / "deploy" / "sample-app" / "permissions.json"
ROLES = ROOT / "deploy" / "sample-app" / "roles.json"
#: The supplier portal function enforces its own key on the buyer-link routes, as a
#: module constant rather than a require_permission call.
SUPPLIER_PORTAL = ROOT / "supplier_portal" / "supplier_portal" / "web.py"
_PORTAL_KEY = re.compile(r'^MANAGE = "([^"]+)"', re.M)

_ENFORCED = re.compile(r"require_permission\(\s*[\"']([^\"']+)[\"']\s*\)")


def _enforced() -> set[str]:
    keys: set[str] = set()
    for path in ROUTERS.glob("*.py"):
        keys |= set(_ENFORCED.findall(path.read_text()))
    keys |= set(_PORTAL_KEY.findall(SUPPLIER_PORTAL.read_text()))
    return keys


def _declaration() -> dict:
    return json.loads(DECLARED.read_text())


def _declared() -> set[str]:
    return {p["key"] for p in _declaration()["permissions"]}


def test_every_enforced_permission_is_declared():
    """The direction that breaks the app outright."""
    missing = _enforced() - _declared()

    assert not missing, (
        f"the app enforces {sorted(missing)} but permissions.json never declares them, "
        f"so those routes 403 for every user and granting cannot help — the "
        f"permission does not exist to grant"
    )


def test_every_declared_permission_is_enforced():
    """The direction that produces a checkbox controlling nothing."""
    extra = _declared() - _enforced()

    assert not extra, f"permissions.json declares {sorted(extra)} but no router enforces them"


def test_the_routers_enforce_anything_at_all():
    """Guards the regex: two empty sets would satisfy both tests above."""
    assert len(_enforced()) >= 5, "found almost no require_permission calls — regex drift?"


def test_the_declaration_is_one_register_permissions_accepts():
    """The shape porth-install's AppPermissionFile validates (extra keys forbidden),
    checked here so a typo fails CI rather than the deploy."""
    doc = _declaration()
    assert set(doc) == {"namespace", "permissions"}
    assert doc["namespace"] == "sample-app"
    allowed = {"key", "display_name", "category", "admin_role", "description",
               "icon_hint", "sort_order"}
    keys = [p["key"] for p in doc["permissions"]]
    assert len(keys) == len(set(keys)), "a key is declared twice"
    for p in doc["permissions"]:
        assert set(p) <= allowed, f"{p['key']}: unknown fields {sorted(set(p) - allowed)}"
        assert {"key", "display_name", "category", "admin_role"} <= set(p)
        assert p["admin_role"] in ("tenant-admin", "platform-admin")


def test_every_role_grant_is_a_declared_permission():
    roles = json.loads(ROLES.read_text())
    assert roles["namespace"] == _declaration()["namespace"]
    for name, grants in roles["roles"].items():
        unknown = set(grants) - _declared()
        assert not unknown, f"role {name} is granted undeclared {sorted(unknown)}"


def test_only_the_controller_can_approve():
    """Segregation of duties as data: the clerks author, the controller approves,
    and nobody both authors and approves."""
    roles = json.loads(ROLES.read_text())["roles"]
    approvers = {n for n, g in roles.items() if "approvals.write" in g}
    assert not set(roles["supplier"]) & {"approvals.write", "ap.bills.read", "ar.invoices.read"}, (
        "a supplier reads and approves nothing of the buyer's")
    authors = {n for n, g in roles.items() if {"ar.invoices.write", "ap.bills.write"} & set(g)}
    assert approvers == {"controller"}
    assert not approvers & authors
