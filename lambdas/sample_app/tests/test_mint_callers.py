"""Every slot's supplier portal is a named delegated-mint caller, by the role name it really has.

Porth's mint key lets only the roles in delegated_mint_caller_role_arns sign a mint
request (infra/terraform/ems-install-once/porth.tf). That list is built from slot
names and template.yml's role-name convention, so these three must agree:

* the slots in deploy/porth/environments.json,
* delegated_mint_caller_slots in ems-install-once/variables.tf,
* the portal's RoleName in template.yml and the name porth.tf and the deploy's
  check build from a slot.
"""

import json
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[3]
TF = ROOT / "infra" / "terraform" / "ems-install-once"


def _slots() -> set[str]:
    return set(json.loads((ROOT / "deploy" / "porth" / "environments.json").read_text())["environments"])


def _caller_slots(environment: str) -> set[str]:
    text = (TF / "variables.tf").read_text()
    block = text[text.index('variable "delegated_mint_caller_slots"'):]
    default = block[block.index("default = {"):block.index("}\n}")]
    match = re.search(rf"\b{environment}\s*=\s*\[([^\]]*)\]", default)
    assert match, f"delegated_mint_caller_slots names no {environment!r}"
    return set(re.findall(r'"([^"]+)"', match.group(1)))


def test_every_slot_may_mint_on_the_porth_environment():
    assert _caller_slots("dev") == _slots()


def test_the_caller_role_is_the_portal_role_template_yml_creates():
    template = (ROOT / "template.yml").read_text()
    assert "RoleName: !Sub ems-supplier-portal-${EnvironmentSlot}" in template
    assert ':role/ems-supplier-portal-${slot}"' in (TF / "porth.tf").read_text()
    workflow = (ROOT / ".github" / "workflows" / "deploy-sample-app.yml").read_text()
    assert ':role/ems-supplier-portal-${ENVIRONMENT_SLOT}"' in workflow


def test_the_install_once_inputs_are_committed_not_in_a_tfvars():
    porth = (TF / "porth.tf").read_text()
    assert "delegated_mint_caller_role_arns = local.delegated_mint_callers" in porth
    # Pinned: a moving ref would change Porth's install-once without a reviewed diff.
    assert re.search(r"porth-install-once\?ref=[0-9a-f]{40}\"", porth)
