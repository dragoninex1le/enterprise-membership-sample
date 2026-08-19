#!/usr/bin/env python3
"""Substitute {{PLACEHOLDER}} tokens in a JSON artefact and print the result.

    render.py session-policy/index.template.json ENV=dev

Placeholders are deliberately {{UPPER}} rather than $VAR: the session-policy
documents contain `$env` and `$tenant` markers that the AUTHORIZER substitutes
at request time, and those must survive this step untouched. Two substitution
syntaxes in one file, with different owners and different timing, is how one
gets eaten by the other.

Validates that the output is still JSON and that no placeholder survived, so an
unrendered token fails here rather than being written to SSM and failing at
request time as something unrecognisable.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

PLACEHOLDER = re.compile(r"\{\{([A-Z0-9_]+)\}\}")


def render(text: str, values: dict[str, str]) -> str:
    def _sub(match: re.Match) -> str:
        name = match.group(1)
        if name not in values:
            raise SystemExit(f"::error::no value supplied for placeholder {{{{{name}}}}}")
        return values[name]

    return PLACEHOLDER.sub(_sub, text)


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        raise SystemExit("usage: render.py <file.template.json> [KEY=value ...]")

    path = Path(argv[1])
    values = dict(pair.split("=", 1) for pair in argv[2:])

    rendered = render(path.read_text(), values)

    leftover = PLACEHOLDER.findall(rendered)
    if leftover:
        raise SystemExit(f"::error::unrendered placeholders remain: {sorted(set(leftover))}")

    try:
        json.loads(rendered)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"::error::{path} did not render to valid JSON: {exc}") from exc

    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
