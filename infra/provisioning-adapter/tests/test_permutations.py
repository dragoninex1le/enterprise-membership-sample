"""scripts/permutations.py, run against the real handler with AWS faked.

The script is what an operator runs against the deployed adapter. If its expectations drifted from
the code, a live run would report failures that are the script's, not the adapter's - and each live
run costs. So every case it sends is sent here first, judged by the same `judge`, schema included.
"""
import copy
import importlib.util
import sys
from pathlib import Path

import pytest
from prawf_schemas import validate_contract_response

from test_adapter import handler, world  # noqa: F401 - world is a fixture

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("permutations", HERE.parent / "scripts" / "permutations.py")
permutations = importlib.util.module_from_spec(_spec)
sys.modules["permutations"] = permutations
_spec.loader.exec_module(permutations)

CASES = permutations.cases("porth-dau")


def validate(resp):
    result = validate_contract_response(resp)
    return [] if result.valid else [f"schema: {e}" for e in result.errors]


@pytest.mark.parametrize("case", CASES, ids=[f"{c.group}/{c.name}" for c in CASES])
def test_the_adapter_answers_every_permutation_as_the_script_expects(world, case):  # noqa: F811
    resp = handler.handler(copy.deepcopy(case.request), None)
    assert permutations.judge(case, resp, validate) == []


def test_the_script_covers_every_verb_and_entity_in_the_catalogue():
    import catalogue
    import envelope

    assert set(permutations.ENTITIES) == set(catalogue.IDS)
    assert set(permutations.VERBS) | {"capabilities"} == set(envelope.VERBS)
    covered = {(c.group, c.name) for c in CASES}
    for verb in permutations.VERBS:
        for entity in permutations.ENTITIES:
            assert (f"verb:{verb}", entity) in covered


def test_the_reason_codes_are_the_schemas_closed_list():
    import json
    import prawf_schemas

    root = Path(prawf_schemas.__file__).resolve().parent
    common = next(root.rglob("common.schema.json"))
    enum = json.loads(common.read_text("utf-8"))["$defs"]["reasonCode"]["enum"]
    assert permutations.REASON_CODES == set(enum)
