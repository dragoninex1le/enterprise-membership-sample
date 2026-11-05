"""`porth` - the install's baseline as a snapshot (contract 1.1, PRF-20).

**What the adapter knows.** A fixed list of Porth's tables, and that every row of a slot sits under a
partition key starting `ENV#{env_scope}#`. Nothing about what an install should contain: which
tenants, roles, permissions or claim mappings exist is whatever the install left, version to version.
Checking that it is right is the job of post-deploy test scripts, never this module (Richard,
2026-11-05).

* **bootstrap** copies every row of the slot from each table, verbatim, with the table's key schema,
  into the adapter's own audit table under `BASELINE#{installed_version}#{content_digest}`. prawf
  supplies `installed_version` (opaque here, a storage key) and keeps the record of which baseline is
  current; the adapter never chooses one.
* **reset** removes every row of the slot from those tables and writes the named baseline back. What
  is live is not consulted: reset returns to the known state whatever happened since (Richard,
  2026-11-05). Rows that would be deleted and then written back unchanged are simply overwritten, so
  there is no moment when the platform tenant is missing. The result is checked by hashing the slot
  again; a mismatch is `snapshot_invalid`.
* **prune** deletes the baselines prawf names, and nothing else.

**Sessions are not in it.** Their keys carry no environment, so a slot's sessions cannot be told from
another's; `porth-session` clears them on its own.

**Where a snapshot lives.** Inline in the audit item, gzipped, when it fits; otherwise in the
adapter's S3 bucket under `{env_scope}/porth/...`, with the object's hash on the item. Every load
re-hashes both. Snapshots never travel on the wire.

**Hash.** sha256 over a canonical JSON form: tables by logical name, key schema, rows sorted by key,
attribute maps sorted, set members sorted. The rows are hashed as stored, so an untouched slot hashes
the same every time.
"""
from __future__ import annotations

import base64
import gzip
import hashlib
import json
import os
import re
from datetime import datetime, timezone

import aws
import ledger
import slots
from envelope import ContractError

ENTITY = "porth"
KIND = "snapshot"

#: Logical name -> the environment variable holding the physical table name. The logical name is what
#: the snapshot and its hash use, so a redeployed Porth with renamed tables restores the same content.
TABLES: dict[str, str] = {
    "tenants": "PORTH_TENANTS_TABLE",
    "roles": "PORTH_ROLES_TABLE",
    "permissions": "PORTH_PERMISSIONS_TABLE",
    "claim-mapping-configs": "PORTH_CLAIM_MAPPING_CONFIGS_TABLE",
    "users": "PORTH_USERS_TABLE",
    "org-units": "PORTH_ORG_UNITS_TABLE",
}

#: An item may be 400 KB. Inline payloads stay well under it, leaving room for the other attributes.
INLINE_LIMIT = 300_000
#: installed_version is opaque, but it is part of a sort key and an S3 key: it may not hold `#` or `/`.
_LABEL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,127}$")
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")


# ---------------------------------------------------------------- reading the slot

def physical(name: str) -> str:
    return os.environ[TABLES[name]]


def key_schema(db, table: str) -> list[str]:
    """[partition key, sort key?] by attribute name, as the table declares them."""
    keys = db.describe_table(TableName=table)["Table"]["KeySchema"]
    return [k["AttributeName"] for k in sorted(keys, key=lambda k: k["KeyType"] != "HASH")]


def scan_slot(db, table: str, partition_key: str, env_scope: str) -> list[dict]:
    """Every row of the slot in one table. IAM cannot hold a Scan to one slot, so the filter does:
    DynamoDB applies it before anything is returned, and no other slot's row reaches this code."""
    kwargs = {"TableName": table, "ConsistentRead": True,
              "FilterExpression": "begins_with(#pk, :p)",
              "ExpressionAttributeNames": {"#pk": partition_key},
              "ExpressionAttributeValues": {":p": {"S": f"ENV#{env_scope}#"}}}
    items, start = [], None
    while True:
        if start:
            kwargs["ExclusiveStartKey"] = start
        page = db.scan(**kwargs)
        items += page.get("Items", [])
        start = page.get("LastEvaluatedKey")
        if not start:
            return items


def _canon_value(v: dict) -> object:
    """One typed DynamoDB value in a canonical, JSON-safe form."""
    (t, x), = v.items()
    if t == "B":
        return {"B": base64.b64encode(x if isinstance(x, (bytes, bytearray)) else bytes(x)).decode()}
    if t == "BS":
        return {"BS": sorted(base64.b64encode(b).decode() for b in x)}
    if t in ("SS", "NS"):
        return {t: sorted(x)}
    if t == "M":
        return {"M": {k: _canon_value(x[k]) for k in sorted(x)}}
    if t == "L":
        return {"L": [_canon_value(i) for i in x]}
    return {t: x}


def _canon_row(row: dict) -> dict:
    return {k: _canon_value(row[k]) for k in sorted(row)}


def _row_key(row: dict, schema: list[str]) -> tuple:
    return tuple(json.dumps(row.get(k), sort_keys=True) for k in schema)


def capture(db, env_scope: str) -> dict:
    """The slot's rows in every table, canonical. Pure data: what restore writes back."""
    content = {}
    for name in TABLES:
        table = physical(name)
        schema = key_schema(db, table)
        rows = [_canon_row(r) for r in scan_slot(db, table, schema[0], env_scope)]
        rows.sort(key=lambda r: _row_key(r, schema))
        content[name] = {"key_schema": schema, "rows": rows}
    return {"entity": ENTITY, "tables": content}


def _canonical_bytes(content: dict) -> bytes:
    return json.dumps(content, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def digest(content: dict) -> str:
    return "sha256:" + hashlib.sha256(_canonical_bytes(content)).hexdigest()


def _typed(value: object) -> dict:
    """Back from the canonical form to what DynamoDB takes."""
    (t, x), = value.items()
    if t == "B":
        return {"B": base64.b64decode(x)}
    if t == "BS":
        return {"BS": [base64.b64decode(b) for b in x]}
    if t == "M":
        return {"M": {k: _typed(v) for k, v in x.items()}}
    if t == "L":
        return {"L": [_typed(i) for i in x]}
    return {t: x}


def _item(row: dict) -> dict:
    return {k: _typed(v) for k, v in row.items()}


# ---------------------------------------------------------------- storage

def _bucket() -> str:
    return os.environ["PRAWF_SNAPSHOT_BUCKET"]


def _pk(env_scope: str) -> dict:
    return {"S": f"ENV#{env_scope}#ENTITY#{ENTITY}"}


def _sk(installed_version: str, content_digest: str | None = None) -> str:
    return f"BASELINE#{installed_version}#" + (content_digest or "")


def _object_key(env_scope: str, installed_version: str, content_digest: str) -> str:
    return f"{env_scope}/{ENTITY}/{installed_version}/{content_digest.removeprefix('sha256:')}.json.gz"


def installed_version_of(payload: object, verb: str) -> str:
    value = payload.get("installed_version") if isinstance(payload, dict) else None
    if value is None:
        raise ContractError("refused", "installed_version_required",
                            f"{verb} on {ENTITY} needs payload.installed_version: the version deployed in this slot")
    if not isinstance(value, str) or not _LABEL.fullmatch(value):
        raise ContractError("refused", "installed_version_required",
                            f"installed_version must match {_LABEL.pattern}: it is used as a storage key")
    return value


class Store:
    """The slot's stored baselines, on the one-slot session's credentials."""

    def __init__(self, env_scope: str):
        creds = slots.data_credentials(env_scope)
        self.env_scope = env_scope
        self.db = aws.client("dynamodb", **creds)
        self._creds = creds
        self._s3 = None

    @property
    def s3(self):
        if self._s3 is None:
            self._s3 = aws.client("s3", **self._creds)
        return self._s3

    def get(self, installed_version: str, content_digest: str) -> dict | None:
        return self.db.get_item(TableName=ledger.table(), ConsistentRead=True, Key={
            "PK": _pk(self.env_scope), "SK": {"S": _sk(installed_version, content_digest)}}).get("Item")

    def under(self, installed_version: str) -> list[dict]:
        kwargs = {"TableName": ledger.table(), "ConsistentRead": True,
                  "KeyConditionExpression": "PK = :pk AND begins_with(SK, :sk)",
                  "ExpressionAttributeValues": {":pk": _pk(self.env_scope), ":sk": {"S": _sk(installed_version)}}}
        items, start = [], None
        while True:
            if start:
                kwargs["ExclusiveStartKey"] = start
            page = self.db.query(**kwargs)
            items += page.get("Items", [])
            start = page.get("LastEvaluatedKey")
            if not start:
                return items

    def put(self, installed_version: str, content: dict, run_id: str) -> tuple[str, bool]:
        """Store a baseline. The same content under the same version is already stored: unchanged."""
        content_digest = digest(content)
        if self.get(installed_version, content_digest):
            return content_digest, False
        body = gzip.compress(_canonical_bytes(content), mtime=0)
        item = {
            "PK": _pk(self.env_scope), "SK": {"S": _sk(installed_version, content_digest)},
            "installed_version": {"S": installed_version}, "content_digest": {"S": content_digest},
            "captured_at": {"S": datetime.now(timezone.utc).isoformat()}, "run_id": {"S": run_id},
        }
        if len(body) <= INLINE_LIMIT:
            item["payload"] = {"B": body}
        else:
            key = _object_key(self.env_scope, installed_version, content_digest)
            self.s3.put_object(Bucket=_bucket(), Key=key, Body=body, ServerSideEncryption="AES256")
            item["payload_ref"] = {"S": key}
            item["payload_sha256"] = {"S": hashlib.sha256(body).hexdigest()}
        self.db.put_item(TableName=ledger.table(), Item=item)
        return content_digest, True

    def load(self, installed_version: str, content_digest: str) -> dict:
        """The named baseline, re-hashed. Anything wrong with it is `snapshot_invalid`."""
        item = self.get(installed_version, content_digest)
        if not item:
            raise ContractError("failed", "snapshot_invalid",
                                f"no {ENTITY} baseline {content_digest} is stored for installed version "
                                f"{installed_version} in this slot")
        if "payload" in item:
            body = bytes(item["payload"]["B"])
        else:
            body = self.s3.get_object(Bucket=_bucket(), Key=item["payload_ref"]["S"])["Body"].read()
            if hashlib.sha256(body).hexdigest() != item["payload_sha256"]["S"]:
                raise ContractError("failed", "snapshot_invalid",
                                    f"the stored {ENTITY} baseline {content_digest} does not match its recorded hash")
        try:
            content = json.loads(gzip.decompress(body))
        except (OSError, ValueError) as e:
            raise ContractError("failed", "snapshot_invalid",
                                f"the stored {ENTITY} baseline {content_digest} cannot be read") from e
        if digest(content) != content_digest:
            raise ContractError("failed", "snapshot_invalid",
                                f"the stored {ENTITY} baseline does not hash to {content_digest}")
        return content

    def delete(self, item: dict) -> None:
        if "payload_ref" in item:
            self.s3.delete_object(Bucket=_bucket(), Key=item["payload_ref"]["S"])
        self.db.delete_item(TableName=ledger.table(), Key={"PK": item["PK"], "SK": item["SK"]})


# ---------------------------------------------------------------- verbs

def _result(installed_version: str, content_digest: str, **extra) -> dict:
    return {"entity": ENTITY, "baseline_kind": KIND, "installed_version": installed_version,
            "content_digest": content_digest, **extra}


def bootstrap(env_scope: str, run_id: str, dry_run: bool, payload: object) -> tuple[list[dict], list[str]]:
    installed_version = installed_version_of(payload, "bootstrap")
    store = Store(env_scope)
    content = capture(store.db, env_scope)
    counts = ", ".join(f"{n} {len(t['rows'])}" for n, t in content["tables"].items())
    if dry_run:
        return [_result(installed_version, digest(content))], [f"dry run: would capture {counts}; nothing stored"]
    content_digest, stored = store.put(installed_version, content, run_id)
    note = f"captured {counts}" if stored else "this content is already stored under this installed version"
    return [_result(installed_version, content_digest)], [note]


def _baseline(payload: object) -> tuple[str, str]:
    named = payload.get("baseline") if isinstance(payload, dict) else None
    if not isinstance(named, dict):
        raise ContractError("refused", "installed_version_required",
                            f"reset of {ENTITY} needs payload.baseline {{installed_version, content_digest}}: "
                            "prawf names the baseline, the adapter never chooses one")
    installed_version = installed_version_of(named, "reset")
    content_digest = named.get("content_digest")
    if not isinstance(content_digest, str) or not _DIGEST.fullmatch(content_digest):
        raise ContractError("failed", "snapshot_invalid",
                            f"baseline.content_digest {content_digest!r} names no baseline this adapter could store")
    return installed_version, content_digest


def restore(env_scope: str, run_id: str, dry_run: bool, payload: object, publish) -> tuple[list[dict], list[str]]:
    """Every row of the slot goes; the baseline comes back. `publish(table, row)` is called for each
    row removed and not written back, so Porth's consumers hear about what went."""
    installed_version, content_digest = _baseline(payload)
    store = Store(env_scope)
    content = store.load(installed_version, content_digest)
    notes = []
    if isinstance(payload, dict) and "expected_current_digest" in payload:
        notes.append("expected_current_digest is not checked: reset returns to the baseline whatever is live")

    plan = []
    for name, stored in content["tables"].items():
        table = physical(name)
        schema = key_schema(store.db, table)
        if schema != stored["key_schema"]:
            raise ContractError("failed", "snapshot_invalid",
                                f"table {name} is keyed {schema} now, but the baseline was captured keyed "
                                f"{stored['key_schema']}; this baseline cannot be restored to this install")
        keep = {_row_key(r, schema) for r in stored["rows"]}
        gone = [r for r in scan_slot(store.db, table, schema[0], env_scope)
                if _row_key(_canon_row(r), schema) not in keep]
        plan.append((name, table, schema, gone, stored["rows"]))

    summary = ", ".join(f"{n}: remove {len(g)}, write {len(w)}" for n, _, _, g, w in plan)
    if dry_run:
        return [_result(installed_version, content_digest)], ["dry run: nothing changed", summary, *notes]

    for name, table, schema, gone, rows in plan:
        for row in gone:
            store.db.delete_item(TableName=table, Key={k: row[k] for k in schema})
            publish(name, row)
        for row in rows:
            store.db.put_item(TableName=table, Item=_item(row))

    after = digest(capture(store.db, env_scope))
    if after != content_digest:
        raise ContractError("failed", "snapshot_invalid",
                            f"after restoring, the slot hashes to {after}, not {content_digest}: something wrote "
                            "to it during the reset. Reset again")
    return [_result(installed_version, content_digest)], [summary, *notes]


def prune(env_scope: str, run_id: str, dry_run: bool, payload: object) -> tuple[list[dict], list[str]]:
    named = payload.get("baselines") if isinstance(payload, dict) else None
    if not isinstance(named, list) or not named:
        raise ContractError("refused", "installed_version_required",
                            f"prune on {ENTITY} needs payload.baselines: [{{installed_version, content_digest?}}]")
    store = Store(env_scope)
    results = []
    for entry in named:
        installed_version = installed_version_of(entry, "prune")
        content_digest = entry.get("content_digest") if isinstance(entry, dict) else None
        if content_digest is not None and (not isinstance(content_digest, str) or not _DIGEST.fullmatch(content_digest)):
            raise ContractError("refused", "installed_version_required",
                                f"content_digest {content_digest!r} is not sha256:<64 hex>")
        found = [store.get(installed_version, content_digest)] if content_digest else store.under(installed_version)
        found = [f for f in found if f]
        if not dry_run:
            for item in found:
                store.delete(item)
        result = {"entity": ENTITY, "installed_version": installed_version,
                  "outcome": "removed" if found else "unchanged", "removed": len(found)}
        if content_digest:
            result["content_digest"] = content_digest
        results.append(result)
    return results, ["dry run: nothing removed"] if dry_run else []
