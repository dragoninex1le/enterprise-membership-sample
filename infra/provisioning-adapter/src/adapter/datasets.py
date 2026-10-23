"""A seed's dataset - PROVISIONING-CONTRACT §4.3, §8 (PRF-12).

A dataset arrives either by reference (`{id, version, digest}`) or inline (the same identity plus a
`form` and its content). Both are valid in the contract; this adapter implements one of them:

* **Inline, enumerated** - the content travels with the call, so the adapter needs no route back to
  prawf's storage. Implemented.
* **By reference** - would need this account to resolve a dataset held in prawf's. `unsupported`,
  which prawf reads as "skip", not "fail".
* **Inline, generated** - no generator is implemented. `unsupported`.

**The digest is checked, not trusted.** Inline, the content is right here, so the adapter recomputes
the hash and refuses a mismatch: a dataset whose content does not match its declared identity is not
the fixture its id and version name, and seeding it would make the run record lie.

The digest rule (prawf-dataset-digest/1), which prawf applies when it stores a dataset: SHA-256 over
the dataset with its `digest` member removed, serialised as JSON with keys sorted, no insignificant
whitespace (`,` and `:` separators), and non-ASCII characters left as UTF-8.
"""
from __future__ import annotations

import hashlib
import json

from envelope import ContractError

FORMS = ("enumerated",)


def digest_of(dataset: dict) -> str:
    body = {k: v for k, v in dataset.items() if k != "digest"}
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def accept(payload: object) -> dict:
    """The dataset to apply, or the contract's answer for why it cannot be."""
    dataset = payload.get("dataset") if isinstance(payload, dict) else None
    if not isinstance(dataset, dict):
        raise ContractError("refused", "dataset_conflict", "seed needs payload.dataset (§4.3)")
    if "form" not in dataset:
        raise ContractError(
            "unsupported", "not_implemented",
            "this adapter does not resolve datasets by reference; send the dataset inline",
        )
    if dataset["form"] not in FORMS:
        raise ContractError(
            "unsupported", "not_implemented",
            f"dataset form {dataset['form']!r} is not implemented; this adapter accepts {', '.join(FORMS)}",
        )
    for field in ("id", "version", "digest"):
        if not isinstance(dataset.get(field), str) or not dataset[field]:
            raise ContractError("refused", "dataset_conflict", f"the dataset has no {field}")
    actual = digest_of(dataset)
    if actual != dataset["digest"]:
        raise ContractError(
            "refused", "dataset_conflict",
            f"dataset {dataset['id']} {dataset['version']} declares digest {dataset['digest']} "
            f"but its content hashes to {actual}: it is not the fixture it names",
        )
    resources = dataset.get("resources")
    if not isinstance(resources, list) or not resources:
        raise ContractError("refused", "dataset_conflict", "an enumerated dataset needs at least one resource")
    return dataset
