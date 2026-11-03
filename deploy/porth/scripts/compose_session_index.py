#!/usr/bin/env python3
"""Expand the session-policy index template once per ADR-Z8 environment.

    compose_session_index.py index.template.json ENV=dev ENVIRONMENTS=a,b

The authorizer picks a binding by matching the request host to a `context_rule`
and then looking the rule's `context_hint` up in `bindings`. It substitutes
``${role_type}``, ``{account}`` and ``{region}`` into the chosen ARNs — and
NOTHING else. There is no `$env`, so one binding cannot serve two environments:
each needs its own rule, its own hint and its own role ARN.

Rather than write those out per environment and cap the number at however many
were typed, the template describes ONE environment using ``{{ENV_SLOT}}``, and
every rule and binding mentioning it is repeated once per environment here.
Anything without it — the catch-all rule, Porth's own binding — is emitted once.

Rule ORDER is preserved, and it matters: `_resolve_context_hint` returns the
first pattern that matches, so a catch-all placed above a specific host would
swallow it. Expanding in place keeps the template's order the output's order.

Placeholders are {{UPPER}} for the same reason as render.py: the session-policy
documents these bindings point AT contain `$env` and `$tenant` markers that the
authorizer substitutes at request time, and those must survive untouched.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

PLACEHOLDER = re.compile(r"\{\{([A-Z0-9_]+)\}\}")
SLOT = "{{ENV_SLOT}}"


def _render(node, values: dict[str, str]):
    """Substitute placeholders through a parsed JSON tree."""
    if isinstance(node, str):
        def _sub(m: re.Match) -> str:
            name = m.group(1)
            if name not in values:
                raise SystemExit(f"::error::no value supplied for placeholder {{{{{name}}}}}")
            return values[name]
        return PLACEHOLDER.sub(_sub, node)
    if isinstance(node, list):
        return [_render(v, values) for v in node]
    if isinstance(node, dict):
        return {_render(k, values): _render(v, values) for k, v in node.items()}
    return node


def _mentions_slot(node) -> bool:
    return SLOT in json.dumps(node)


def compose(template: dict, env: str, environments: list[str]) -> dict:
    rules: list = []
    for rule in template.get("context_rules", []):
        if _mentions_slot(rule):
            rules.extend(_render(rule, {"ENV": env, "ENV_SLOT": e}) for e in environments)
        else:
            rules.append(_render(rule, {"ENV": env}))

    bindings: dict = {}
    for key, entry in (template.get("bindings") or {}).items():
        pair = {key: entry}
        if _mentions_slot(pair):
            for e in environments:
                bindings.update(_render(pair, {"ENV": env, "ENV_SLOT": e}))
        else:
            bindings.update(_render(pair, {"ENV": env}))

    return {"context_rules": rules, "bindings": bindings}


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        raise SystemExit("usage: compose_session_index.py <file.template.json> [KEY=value ...]")

    values = dict(pair.split("=", 1) for pair in argv[2:])
    env = values.get("ENV", "")
    environments = [e.strip() for e in values.get("ENVIRONMENTS", "").split(",") if e.strip()]

    if not env:
        raise SystemExit("::error::ENV is required — it names the /porth/{branch}/… tree")
    if not environments:
        raise SystemExit(
            "::error::ENVIRONMENTS is required and must list at least one ADR-Z8 "
            "environment. An empty list renders an index with no binding for the "
            "app at all, and the authorizer would fall back to the tenant role's "
            "full ceiling — every tenant readable — rather than fail."
        )

    composed = compose(json.loads(Path(argv[1]).read_text()), env, environments)

    out = json.dumps(composed, indent=2)
    leftover = PLACEHOLDER.findall(out)
    if leftover:
        raise SystemExit(f"::error::unrendered placeholders remain: {sorted(set(leftover))}")
    print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
