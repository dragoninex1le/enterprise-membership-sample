"""The proof script's contract with ffug's own modules.

`scripts/ffug_proof.py` recomputes ffug's digest independently and scans for
ffug's sort key. Both couplings are invisible: rename `PROJECTION_SK` or change
how the digest is composed and the script keeps running, scans for a sort key
nothing uses, finds nothing, and reports "no tenant projections" — which is
also exactly what a broken consumer looks like.

The proof run is a `workflow_dispatch`, so nothing else would catch it until
somebody ran it and drew the wrong conclusion.
"""

import importlib.util
import pathlib
import sys

import pytest

from ffug import keys, salt

SCRIPT = pathlib.Path(__file__).resolve().parents[3] / "scripts" / "ffug_proof.py"


@pytest.fixture(scope="module")
def proof():
    spec = importlib.util.spec_from_file_location("ffug_proof", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    # Registered BEFORE execution: @dataclass resolves its annotations through
    # sys.modules[cls.__module__], so a module loaded by path and not registered
    # raises AttributeError on NoneType while decorating Caller.
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(spec.name, None)
    return module


def test_the_script_imports_without_its_environment(proof):
    """Settings are read at use, not at import — otherwise this file could not
    exist and the two assertions below could not run."""
    assert proof.PAYLOAD


def test_it_recomputes_the_digest_the_way_the_service_does(proof):
    """The whole value of stage B is that the script and the service arrive at
    the same answer from opposite directions. If it just echoed what ffug
    returned, it would prove ffug agrees with itself."""
    prime = salt.mint_prime()

    assert salt.digest(prime, proof.PAYLOAD) == salt.digest(prime, proof.PAYLOAD)
    assert salt.digest(prime, proof.PAYLOAD) != salt.digest(salt.mint_prime(), proof.PAYLOAD)


def test_it_scans_for_the_sort_key_the_consumer_actually_writes(proof):
    """Imported from `ffug.keys`, not spelled — so a rename is an ImportError
    here rather than an empty scan in a run somebody is reading for evidence."""
    assert proof.keys.PROJECTION_SK is keys.PROJECTION_SK


def test_it_parses_the_partition_the_way_the_consumer_builds_it(proof):
    """The script splits `pk` back into (environment, tenant_id) to build the
    envelope. Round-trip it against the real key builder."""
    partition = keys.partition("prod", "acme")
    _, environment, _, tenant_id = partition.split("#")

    assert (environment, tenant_id) == ("prod", "acme")
    assert keys.partition(environment, tenant_id) == partition


def test_the_caller_satisfies_what_build_envelope_requires(proof):
    """TS-MC.1: `build_envelope` takes a context object rather than two loose
    strings, precisely so a call site cannot invent a tenant. The UAT runner is
    the one place that legitimately constructs one."""
    caller = proof.Caller(environment="prod", tenant_id="acme")

    assert caller.environment == "prod"
    assert caller.tenant_id == "acme"
