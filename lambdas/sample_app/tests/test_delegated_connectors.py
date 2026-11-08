"""deploy/porth/delegated-connectors.json agrees with what the app and the install say.

The file is what porth-install.yml enables with `porth-install delegated-config put`.
A connector enabled with a role nobody seeds, on a slot that does not exist, or on a
slot whose portal cannot sign a mint request, deploys cleanly and then refuses every
supplier session. These checks keep that from reaching a deploy.
"""

import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[3]
CONFIG = json.loads((ROOT / "deploy" / "porth" / "delegated-connectors.json").read_text())
ROLES = json.loads((ROOT / "deploy" / "sample-app" / "roles.json").read_text())["roles"]
SLOTS = set(json.loads((ROOT / "deploy" / "porth" / "environments.json").read_text())["environments"])

sys.path.insert(0, str(ROOT / "supplier_portal"))
from supplier_portal import CONNECTOR  # noqa: E402


def _mint_caller_slots() -> set[str]:
    text = (ROOT / "infra" / "terraform" / "ems-install-once" / "variables.tf").read_text()
    block = text[text.index('variable "delegated_mint_caller_slots"'):]
    default = block[block.index("default = {"):block.index("}\n}")]
    return set(re.findall(r'"([^"]+)"', re.search(r"\bdev\s*=\s*\[([^\]]*)\]", default).group(1)))


def test_the_portal_s_connector_is_the_one_enabled():
    assert [c["connector"] for c in CONFIG["connectors"]] == [CONNECTOR]


def test_each_entry_is_complete():
    for entry in CONFIG["connectors"]:
        assert set(entry) == {"connector", "enabled", "allowed_roles", "slots"}
        assert isinstance(entry["enabled"], bool)
        assert entry["allowed_roles"] and entry["slots"]


def test_the_ceiling_names_roles_the_app_defines():
    for entry in CONFIG["connectors"]:
        assert set(entry["allowed_roles"]) <= set(ROLES), entry["allowed_roles"]


def test_enabled_slots_exist_and_their_portals_may_sign():
    for entry in CONFIG["connectors"]:
        slots = set(entry["slots"])
        assert slots <= SLOTS
        if entry["enabled"]:
            # Enabled without the KMS grant is refused as a signing failure;
            # granted without being enabled is refused as connector_not_enabled.
            assert slots == _mint_caller_slots()
