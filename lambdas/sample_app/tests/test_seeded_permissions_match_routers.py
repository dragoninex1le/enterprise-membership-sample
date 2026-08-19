"""The seeded permissions must be the ones the app enforces (PORTH-610).

scripts/seed_app_permissions.py registers the app's permissions into Porth. Its
list and the routers' require_permission(...) calls are two statements of the
same fact, and the failure mode when they drift is one-directional and quiet:

* a key enforced but never seeded  -> the page 403s for everyone, forever, and
  no amount of granting fixes it because the permission does not exist;
* a key seeded but never enforced  -> a permission appears in the admin UI that
  controls nothing.

Neither shows up in Porth's logs, because Porth allowed the request — the app
refused it. So the two lists are compared here rather than by eye.
"""
from __future__ import annotations

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[3]
ROUTERS = ROOT / "lambdas" / "sample_app" / "routers"
SEEDER = ROOT / "scripts" / "seed_app_permissions.py"

_ENFORCED = re.compile(r"require_permission\(\s*[\"']([^\"']+)[\"']\s*\)")
_SEEDED = re.compile(r"\{\"key\":\s*\"([^\"]+)\"")


def _enforced() -> set[str]:
    keys: set[str] = set()
    for path in ROUTERS.glob("*.py"):
        keys |= set(_ENFORCED.findall(path.read_text()))
    return keys


def _seeded() -> set[str]:
    return set(_SEEDED.findall(SEEDER.read_text()))


def test_every_enforced_permission_is_seeded():
    """The direction that breaks the app outright."""
    missing = _enforced() - _seeded()

    assert not missing, (
        f"the app enforces {sorted(missing)} but the seeder never registers them, "
        f"so those routes 403 for every user and granting cannot help — the "
        f"permission does not exist to grant"
    )


def test_every_seeded_permission_is_enforced():
    """The direction that produces a checkbox controlling nothing."""
    extra = _seeded() - _enforced()

    assert not extra, (
        f"the seeder registers {sorted(extra)} but no router enforces them"
    )


def test_the_routers_enforce_anything_at_all():
    """Guards the regexes: two empty sets would satisfy both tests above."""
    assert len(_enforced()) >= 5, "found almost no require_permission calls — regex drift?"
