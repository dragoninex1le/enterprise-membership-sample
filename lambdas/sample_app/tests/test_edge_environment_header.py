"""Every API path through CloudFront names its environment.

Unpinned (PORTH-627), Porth's authorizer resolves the ADR-Z8 environment from
the BFF session or the `x-porth-environment` header, and RAISES
`UnboundEnvironmentError` when it has neither. It does not derive it from the
host.

Neither of the other two sources exists here. The session resolver sees only the
ID token's claims — it cannot know the host, so it writes `environment: ""` and
says so in a comment — and the admin SPA does not send the header (checked
against the deployed bundle, not the source). The edge is the only place left
that knows, and it does: one distribution serves exactly one environment.

So this is not a style assertion. A behaviour reaching an API without the
function attached fails EVERY authenticated request through it, with an error
naming an unbound environment rather than the missing association.
"""
from __future__ import annotations

import pathlib
import re

import pytest
import yaml


class _Loader(yaml.SafeLoader):
    pass


_Loader.add_multi_constructor("!", lambda loader, suffix, node: getattr(node, "value", None))

_TEMPLATE = pathlib.Path(__file__).resolve().parents[3] / "template.yml"

#: The behaviours that reach an API rather than the SPA bucket. Every one of
#: them is authorized by Porth.
API_PATHS = {"/auth/*", "/porth/*", "/sample/*"}


@pytest.fixture(scope="module")
def distribution() -> dict:
    doc = yaml.load(_TEMPLATE.read_text(), Loader=_Loader)
    dists = [
        r["Properties"]["DistributionConfig"]
        for r in doc["Resources"].values()
        if r.get("Type") == "AWS::CloudFront::Distribution"
    ]
    assert len(dists) == 1, "expected exactly one distribution"
    return dists[0]


def test_every_api_behaviour_carries_the_function(distribution):
    behaviours = distribution.get("CacheBehaviors") or []
    by_path = {b.get("PathPattern"): b for b in behaviours}

    assert API_PATHS <= set(by_path), (
        f"the API behaviours changed: {sorted(by_path)}. If one was added, it "
        f"needs the function too; if one was removed, update API_PATHS."
    )

    missing = [p for p in sorted(API_PATHS) if not by_path[p].get("FunctionAssociations")]
    assert not missing, (
        f"{missing} reach an API with no viewer-request function, so requests "
        f"through them carry no x-porth-environment. Porth's authorizer raises "
        f"UnboundEnvironmentError on every one — an error that names the "
        f"environment, not the missing association."
    )


def test_the_function_sets_the_environment_from_the_stack_parameter(distribution):
    """Not a literal. Two environments deploy this template, and a hardcoded
    value would send one of them the other's rows."""
    doc = yaml.load(_TEMPLATE.read_text(), Loader=_Loader)
    code = doc["Resources"]["PorthApiPathStripFunction"]["Properties"]["FunctionCode"]

    assert "x-porth-environment" in code
    assert "${EnvironmentSlot}" in code, (
        "the header value is not substituted from EnvironmentSlot, so both "
        "environments would claim the same one"
    )


def test_the_strip_is_guarded_so_other_paths_pass_through(distribution):
    """The function is attached to three behaviours and rewrites one path.

    It was `uri.replace(/^\\/porth/, '')` — unanchored to a segment boundary, so
    it also rewrote anything merely STARTING with those characters, turning
    /porthology into /ology. Harmless while it was attached to /porth/* alone;
    not harmless now.
    """
    doc = yaml.load(_TEMPLATE.read_text(), Loader=_Loader)
    code = doc["Resources"]["PorthApiPathStripFunction"]["Properties"]["FunctionCode"]

    assert "replace(/^\\/porth/" not in code, "the unanchored strip is back"
    assert re.search(r"startsWith\(['\"]/porth/['\"]\)", code), (
        "the strip must test for the /porth/ SEGMENT, or paths on the other two "
        "behaviours are rewritten as well"
    )
