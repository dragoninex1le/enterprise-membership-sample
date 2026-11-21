"""Print `connector roles,comma,separated` per line from deploy/porth/delegated/connectors.json."""
import json
import re
import sys

NAME = re.compile(r"^[a-z0-9][a-z0-9-]*$")

with open(sys.argv[1], encoding="utf-8") as f:
    connectors = json.load(f)["connectors"]
for connector, spec in sorted(connectors.items()):
    roles = spec.get("allowed_roles") or []
    if not NAME.match(connector) or not roles or not all(NAME.match(r) for r in roles):
        sys.exit(f"connectors.json: {connector!r} needs a lower-case name and at least one allowed role")
    print(connector, ",".join(roles))
