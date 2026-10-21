"""The slot map, and the one-slot data session (R8: one adapter per target, slot chosen per call).

The map is the target's own list of its slots, held in the target's own configuration. prawf names
a slot; the target resolves it. Adding a slot is a map entry — no IAM change, no redeploy of prawf.

**Isolation between slots is IAM, not routing.** This Lambda's own role holds no DynamoDB access at
all. Every data call runs on credentials from `data_session`, which assumes the data role with an
inline session policy that admits only partition keys under `ENV#{env_scope}#`. A bug that routed a
write to the wrong slot would be denied by AWS, not by this code getting the routing right.

Two things this module refuses to get wrong:

* **Slot names are checked before they become a glob.** The session policy is `StringLike`, so a
  slot named `*` would admit every slot. Names must match PORTH-627's EnvironmentSlot pattern, and a
  caller's slot must equal a map key exactly — it is looked up, never interpolated.
* **The delimiter is part of the pattern.** `ENV#porth-dau#*` does not match `ENV#porth-dau-probe#…`,
  which is the prefix-extension row PORTH-627's Stage C probes for.
"""
from __future__ import annotations

import json
import os
import re

import aws
from envelope import ContractError

#: PORTH-627's EnvironmentSlot AllowedPattern. It is also what keeps a name glob-free.
_SLOT_NAME = re.compile(r"^[a-z][a-z0-9-]*$")
#: common.schema.json `identifier`.
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
ENVIRONMENT_CLASSES = ("disposable", "protected")

#: Read-only in PRF-9. Writes arrive with the first write verb, reviewed in that slice.
READ_ACTIONS = ("dynamodb:GetItem", "dynamodb:BatchGetItem", "dynamodb:Query", "dynamodb:DescribeTable")

#: `ForAllValues` over an absent key evaluates TRUE, and a Scan carries no LeadingKeys — so a Scan
#: would pass a LeadingKeys-conditioned Allow and read every slot. Denied outright, as is PartiQL.
NEVER = ("dynamodb:Scan", "dynamodb:PartiQLSelect", "dynamodb:ExecuteStatement",
         "dynamodb:BatchExecuteStatement", "dynamodb:ExecuteTransaction")


class SlotMapError(Exception):
    """The target's own configuration is wrong. Loud, never a default."""


def parse(raw: str) -> dict[str, dict]:
    try:
        doc = json.loads(raw)
    except json.JSONDecodeError as e:
        raise SlotMapError(f"slot map is not JSON: {e}") from e
    slots = doc.get("slots") if isinstance(doc, dict) else None
    if not isinstance(slots, dict) or not slots:
        raise SlotMapError('slot map must be {"slots": {"<slot>": {...}}} with at least one slot')

    out: dict[str, dict] = {}
    for name, cfg in slots.items():
        if not isinstance(name, str) or not _SLOT_NAME.fullmatch(name):
            raise SlotMapError(f"slot name {name!r} must match {_SLOT_NAME.pattern}")
        if not isinstance(cfg, dict):
            raise SlotMapError(f"slot {name!r}: configuration must be an object")
        env_id = cfg.get("environment_id")
        if not isinstance(env_id, str) or not _IDENTIFIER.fullmatch(env_id):
            raise SlotMapError(f"slot {name!r}: environment_id must be an identifier")
        klass = cfg.get("environment_class")
        if klass not in ENVIRONMENT_CLASSES:
            raise SlotMapError(f"slot {name!r}: environment_class must be one of {ENVIRONMENT_CLASSES}")
        # Under PORTH-627 the slot IS the env_scope. The override exists for the one case where it
        # is not — a residue scope such as `prod` — and it goes into a glob, so it is checked too.
        scope = cfg.get("env_scope", name)
        if not isinstance(scope, str) or not _SLOT_NAME.fullmatch(scope):
            raise SlotMapError(f"slot {name!r}: env_scope must match {_SLOT_NAME.pattern}")
        out[name] = {"environment_id": env_id, "environment_class": klass, "env_scope": scope}
    return out


def load() -> dict[str, dict]:
    """Read the map from the target's own configuration, every call. It is one GetParameter, and
    a map that changes takes effect at once rather than whenever a container happens to recycle."""
    name = os.environ["SLOT_MAP_PARAMETER"]
    raw = aws.client("ssm").get_parameter(Name=name)["Parameter"]["Value"]
    return parse(raw)


def resolve(slot_map: dict[str, dict], requested: object) -> tuple[str, dict]:
    """Turn the caller's slot into one of the target's. There is no default slot.

    Omission resolves only when the target serves exactly one slot. Otherwise a silent default is
    precisely the failure TAM §2.2 exists to catch: tests passing against a different environment
    from the one intended.

    Reason code: `scope_violation` until PRF-19 publishes its own code for an unknown slot.
    """
    if requested is None:
        if len(slot_map) == 1:
            name = next(iter(slot_map))
            return name, slot_map[name]
        raise ContractError(
            "refused", "scope_violation",
            f"this target serves {len(slot_map)} slots ({', '.join(sorted(slot_map))}); "
            "the call must name one. There is no default slot.",
        )
    if not isinstance(requested, str) or requested not in slot_map:
        raise ContractError(
            "refused", "scope_violation",
            f"slot {requested!r} is not one this target serves ({', '.join(sorted(slot_map))})",
        )
    return requested, slot_map[requested]


def session_policy(env_scope: str) -> str:
    """The inline policy that narrows the data role to one slot for one call."""
    if not _SLOT_NAME.fullmatch(env_scope):
        # Unreachable through `parse`, and kept anyway: this string becomes an IAM glob.
        raise ValueError(f"refusing to build a key pattern from {env_scope!r}")
    return json.dumps({
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "OneSlotOnly",
                "Effect": "Allow",
                "Action": list(READ_ACTIONS),
                "Resource": "*",
                "Condition": {
                    "ForAllValues:StringLike": {"dynamodb:LeadingKeys": [f"ENV#{env_scope}#*"]},
                },
            },
            {"Sid": "NeverScan", "Effect": "Deny", "Action": list(NEVER), "Resource": "*"},
        ],
    }, separators=(",", ":"))


def data_session(env_scope: str):
    """A DynamoDB client whose credentials reach one slot's rows and nothing else."""
    creds = aws.client("sts").assume_role(
        RoleArn=os.environ["DATA_ROLE_ARN"],
        RoleSessionName=f"prawf-{env_scope}"[:64],
        Policy=session_policy(env_scope),
        DurationSeconds=900,
    )["Credentials"]
    return aws.client(
        "dynamodb",
        aws_access_key_id=creds["AccessKeyId"],
        aws_secret_access_key=creds["SecretAccessKey"],
        aws_session_token=creds["SessionToken"],
    )
