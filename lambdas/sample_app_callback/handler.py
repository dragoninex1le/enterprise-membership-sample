"""The sample app's callback ingress — where ffug's answer comes back (PORTH-621).

A separate Lambda, and the two reasons are structural rather than stylistic:

* ``SampleAppFunction`` is a Mangum/FastAPI handler. It expects an API Gateway
  event and cannot read ``{operation, payload, porth_context}``, which is what
  :class:`ServiceClient` sends.
* It holds **no** DynamoDB grant at all — deliberately, since PORTH-586 — so
  even if it could parse the event it could not write the answer.

This is ffug's shape, mirrored: an invoke ingress that builds a Director from a
verified envelope and reaches data only through the narrowing that envelope
justifies.

**The direction wall.** This Director is built with ``expects=RESPONSE``, so a
token signed with a *request* key is refused here before anything else happens.
That is the second half of PORTH-623 and it is what stops this route being a way
to originate work: ffug holds a response key and no request key, and this door
accepts nothing else. ``verify_callback`` refuses to run at all against a
Director that did not declare it.

**The order is verify → recompute → compare, and it cannot be got wrong here.**
The signature is checked as a precondition of the Director existing, so there is
no path that reaches the correlation check with an unverified envelope. A
mismatch on a badly-signed callback therefore reports as a signature failure and
never as a hash mismatch — different events, different alarms, and conflating
them would mean a forgery being logged as a bookkeeping error.

Public-repo note (PORTH-533): identifiers only. Never a digest in full, never a
document body, never a token.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from porth_common.context.envelope import EnvelopeError
from porth_common.director import Director
from porth_common.internal_plane.callback import (
    CallbackCorrelationMismatchError,
    CallbackError,
    verify_callback,
)
from porth_common.internal_plane.config import (
    ServiceNotActiveError,
    ServicesConfigError,
    UnknownServiceError,
)
from porth_common.protocols.cloud_clients import DOCUMENT_STORE
from porth_common.protocols.signing import Direction

from sample_app.repository import APPROVABLE, SampleAppRepository

log = logging.getLogger(__name__)
log.setLevel(os.environ.get("SAMPLE_APP_LOG_LEVEL", "INFO"))


class CallbackRefused(Exception):
    """Typed rejection, returned as data so a caller can assert on the code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message

    def to_response(self) -> dict[str, Any]:
        return {"ok": False, "error": {"code": self.code, "message": self.message}}


class CallbackDirector(Director):
    """The shared Director, narrowed, plus this app's repository.

    ``RESOURCES`` makes the narrowing eager, for the same reason ffug's does: a
    narrowing failure should be raised at the boundary naming the capability,
    not several frames later wearing whatever exception the first DynamoDB call
    produced.

    Note what this does NOT do — fall back to the execution role. There is
    nothing to fall back to: the role below holds no standing table access, so a
    narrowing that failed cannot quietly succeed against every tenant.
    ``SampleAppEventConsumerFunction`` keeps a standing grant because no
    authorizer and no envelope ever run for an EventBridge delivery and it has
    no other identity available. This function has a verified envelope, so it
    has a choice, and this is the one worth making.
    """

    RESOURCES = ((DOCUMENT_STORE, "resource"),)

    @property
    def repository(self) -> SampleAppRepository:
        if getattr(self, "_repository", None) is None:
            self._repository = SampleAppRepository(
                self.resource(DOCUMENT_STORE),
                environment=self.environment,
                tenant_id=self.tenant_id,
            )
        return self._repository


def _build_director(event: dict[str, Any], context: Any) -> CallbackDirector:
    """Construct the Director, translating the library's refusals into codes.

    Every branch is a refusal returned as data. Absent, deliberately, is a
    branch for narrowing failure — that is a deployment fault rather than a
    caller fault, so it propagates and the invocation errors: an operator should
    see it, and a caller should not be told anything useful about it.
    """
    try:
        return CallbackDirector(event, context, expects=Direction.RESPONSE)
    except EnvelopeError as exc:
        raise CallbackRefused(
            getattr(exc, "reason_code", "envelope_error"), str(exc)
        ) from exc
    except (UnknownServiceError, ServiceNotActiveError) as exc:
        # Verified, and from a service this install will not accept completions
        # from. A different fault from a bad signature and worth its own code:
        # one is forgery, the other is configuration.
        raise CallbackRefused("source_service_refused", str(exc)) from exc
    except ServicesConfigError as exc:
        raise CallbackRefused("services_config_unreadable", str(exc)) from exc


def _op_fingerprint_complete(
    payload: dict[str, Any], director: CallbackDirector
) -> dict[str, Any]:
    """Attach ffug's answer to the record that asked for it.

    The lookup comes first and the correlation check second, because the check
    needs the hash the record stored. Both happen after the envelope has already
    been verified — that is a precondition of `director` existing at all.
    """
    found = director.repository.find_by_fingerprint_trace(director.trace_id)
    if found is None:
        # No record in this tenant is waiting on this trace. Authentic and
        # unattributable — which is a real thing to be told, and is what a
        # replayed completion looks like after the first one landed.
        raise CallbackRefused(
            "no_pending_work",
            f"no record in this tenant is awaiting trace {director.trace_id!r}",
        )

    record_type, item = found

    try:
        # Porth computes and compares; the application only ever stored. The
        # recomputation takes environment and tenant from the VERIFIED claims and
        # the originating party from the callback's verified `aud`, so three of
        # the four components are ones this app could not have influenced.
        verify_callback(
            director, expected_hash=item.get("fingerprint_correlation_hash", "")
        )
    except CallbackCorrelationMismatchError as exc:
        # Its own code, because an AUTHENTIC callback carrying the wrong context
        # is a different event from a forged one: a registered service completing
        # work against a context the initiator did not start. Worth alarming on
        # separately, and not to be reported as a signature failure.
        raise CallbackRefused("correlation_mismatch", str(exc)) from exc
    except CallbackError as exc:
        raise CallbackRefused(getattr(exc, "reason_code", "callback_error"), str(exc)) from exc

    # Said out loud, because a match was previously only inferable from the
    # absence of a refusal (PORTH-622 AC3). Silence-as-success is the shape that
    # kept this app's entire log stream muted for four stories — an empty log
    # group reads as "quiet" rather than "nothing was permitted to speak".
    #
    # Identifiers only (PORTH-533). The hash is not a secret, but a reader
    # greps the trace, and the line does not need it.
    log.info(
        "sample_app.callback.correlated tenant_id=%s record_type=%s trace_id=%s "
        "outcome=stored_hash_matched",
        director.tenant_id, record_type, director.trace_id,
    )

    prime, digest = str(payload.get("prime", "")), str(payload.get("digest", ""))
    if not prime or not digest:
        raise CallbackRefused(
            "incomplete_result", "the completion carried no prime or no digest"
        )

    # The id field is a property of the record type and is named in ONE place.
    # Spelling it here again is how the two drift when a third type is added.
    record_id = item[APPROVABLE[record_type].id_field]
    stored = director.repository.attach_fingerprint(
        record_type, record_id, prime=prime, digest=digest
    )
    log.info(
        "sample_app.fingerprint_completed tenant_id=%s record_type=%s digest=%s trace_id=%s",
        director.tenant_id, record_type, digest[:12], director.trace_id,
    )
    return {"ok": True, "operation": "fingerprint-complete", "record": stored}


_OPS = {"fingerprint-complete": _op_fingerprint_complete}


def handler(event: dict[str, Any], context: Any = None) -> dict[str, Any]:
    event = event or {}
    try:
        # Before verification, so nothing here is claimed — only the shape of
        # what arrived, which is the first thing wanted when a completion is
        # being refused as unauthenticated.
        log.debug(
            "sample_app.callback.received operation=%s context_present=%s",
            (event.get("operation") or "").strip(),
            "porth_context" in event,
        )

        director = _build_director(event, context)

        log.debug(
            "sample_app.callback.verified environment=%s tenant_id=%s "
            "source_service=%s internal=%s trace_id=%s",
            director.environment,
            director.tenant_id,
            director.source_service or "-",
            getattr(director, "is_internal_call", "?"),
            director.trace_id or "-",
        )

        if not director.is_authenticated:
            raise CallbackRefused(
                "missing_context", "no verified tenant context on this invocation"
            )

        op = (event.get("operation") or "").strip()
        fn = _OPS.get(op)
        if fn is None:
            raise CallbackRefused("unknown_op", f"unknown op {op!r}")

        result = fn(event.get("payload") or {}, director)
        log.info(
            "sample_app.callback.served operation=%s tenant_id=%s "
            "source_service=%s trace_id=%s",
            op, director.tenant_id, director.source_service or "-", director.trace_id or "-",
        )
        return result
    except CallbackRefused as exc:
        log.warning(
            "sample_app.callback.refused code=%s: %s", exc.code, exc.message
        )
        return exc.to_response()
