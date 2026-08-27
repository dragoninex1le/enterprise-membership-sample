"""ffug's queue drainer: one Director per record, then a fresh crossing back.

The asynchronous half of PORTH-620. The request path ended at `hash_async`,
which persisted who the work was for and queued it. Nothing signed travels on
that queue — a `PersistedContext` does, which needs no signature for the same
reason a row in ffug's own table needs none: only ffug's verified ingress writes
where it lives.

Two properties this file exists to hold, both of which are easy to lose while
still appearing to work:

**One Director per record.** A batch can carry several tenants, and the Director
for record B must be unreachable from record A's — not merely a different
object, but narrowed to a different partition, so DynamoDB refuses the crossing
rather than this code remembering not to make it. `PerRecordDirectors` does the
building and the checking; what would break the property is looping with one
Director hoisted out, which reads as an optimisation.

**A refusal is a batch item failure, never a silent delete.** Returning normally
from an SQS handler deletes the whole batch — including records the iterator
refused. `ReportBatchItemFailures` on the event source plus the identifiers
returned here is what stops a poisoned record taking its neighbours with it.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

from porth_common.director.per_record import PerRecordDirectors
from porth_common.internal_plane.callback import CallbackDeclaration, send_callback
from porth_common.internal_plane import log_plane_identity

from . import keys, salt
from .handler import FfugDirector

log = logging.getLogger(__name__)
log.setLevel(os.environ.get("FFUG_LOG_LEVEL", "INFO"))

# PORTH-623 — the LIBRARY's logger, separately.
#
# Setting this module's own level does nothing for porth_common: loggers are
# per-package, so the lines that say which key signed and which key verified
# stay silent at Lambda's WARNING default no matter how loud this service is.
#
# That is the same trap that muted this whole app for four stories — an empty
# log group reading as quiet rather than silenced — one package over, and it
# would have been found the same way: by needing a line and not having it.
#
# Own variable, because library detail and application detail are different
# questions. Turning up porth_common brings key resolution, trust-document cache
# ages and per-candidate verification; you want that while diagnosing a
# signature, and not otherwise.
logging.getLogger("porth_common").setLevel(
    os.environ.get("PORTH_COMMON_LOG_LEVEL", "INFO")
)



def _context_of(record: dict[str, Any]) -> Any:
    """The persisted context out of one SQS record.

    Raising here is fine and is the point: `PerRecordDirectors` turns anything
    this throws into a typed refusal for that record alone, so a malformed
    message is one batch item failure rather than an exception that abandons
    the records after it.
    """
    return json.loads(record["body"])["context"]


def _complete(scoped: Any) -> None:
    """Hash under this record's own credential, then call the initiator back."""
    director = scoped.director
    message = json.loads(scoped.item["body"])

    row = director.table.get_item(
        Key=keys.projection_key(director.environment, director.tenant_id)
    ).get("Item")
    if row is None or row.get("status") != "active" or not row.get("prime"):
        # Refused rather than raised. A tenant suspended or deleted between the
        # request being accepted and the work being drained is a real outcome,
        # not a transient fault — redelivering would produce the same answer
        # every time until the queue gave up.
        log.warning(
            "ffug.worker.refused tenant_id=%s reason=tenant_not_active trace_id=%s",
            director.tenant_id, director.async_trace_id,
        )
        return

    prime = str(row["prime"])
    payload = message["payload"]
    digest = salt.digest(prime, payload)

    log.debug(
        "ffug.worker.hashed tenant_id=%s canonical_bytes=%d digest=%s trace_id=%s",
        director.tenant_id, len(salt.canonical(payload)), digest[:12],
        director.async_trace_id,
    )

    declared = message["callback"]
    send_callback(
        director,
        CallbackDeclaration(
            service_id=declared["service_id"], operation=declared["operation"]
        ),
        {"prime": prime, "digest": digest},
    )
    log.info(
        "ffug.worker.completed tenant_id=%s callback=%s/%s digest=%s trace_id=%s",
        director.tenant_id, declared["service_id"], declared["operation"],
        digest[:12], director.async_trace_id,
    )


def handler(event: dict[str, Any], context: Any = None) -> dict[str, Any]:
    # PORTH-623 — who this deployable is and where it will read, once per
    # process, at INFO. The post-deploy check: a wrong PORTH_BRANCH shows up
    # here as a wrong path rather than three layers down as a refusal.
    log_plane_identity(FfugDirector.SERVICE_ID)
    records = (event or {}).get("Records") or []
    batch = PerRecordDirectors(
        records, context_of=_context_of, director_cls=FfugDirector, runtime_context=context
    )

    failures: list[dict[str, str]] = []

    for scoped in batch:
        try:
            _complete(scoped)
        except Exception as exc:  # noqa: BLE001 — one bad record must not take the batch
            # Raised, not swallowed: a throttle, a lapsed credential or a callee
            # that was briefly unreachable are all worth another delivery. The
            # DLQ's maxReceiveCount is what stops "another delivery" being
            # forever, which is a bound this file should not also be inventing.
            log.exception(
                "ffug.worker.failed tenant_id=%s trace_id=%s: %s",
                getattr(scoped.director, "tenant_id", "-"),
                getattr(scoped.director, "async_trace_id", "-"),
                exc,
            )
            failures.append({"itemIdentifier": scoped.item["messageId"]})

    for refusal in batch.refusals:
        # A record whose context would not restore, or whose Director would not
        # narrow. Never deleted quietly — it goes back and, after
        # maxReceiveCount, to the dead-letter queue where someone can look at it.
        log.warning(
            "ffug.worker.refused index=%d reason=%s tenant_id=%s: %s",
            refusal.index, refusal.reason_code, refusal.tenant_id or "-", refusal.detail,
        )
        failures.append({"itemIdentifier": refusal.item["messageId"]})

    log.info(
        "ffug.worker.batch received=%d failed=%d refused=%d",
        len(records), len(failures) - batch.refused_count, batch.refused_count,
    )
    return {"batchItemFailures": failures}
