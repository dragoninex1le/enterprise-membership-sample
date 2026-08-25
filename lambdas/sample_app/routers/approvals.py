"""Approvals — derived from the records themselves (PORTH-597).

There is no APPROVAL# row and there never was. This router used to query that
prefix, which nothing in the application has ever written, so the list was
structurally always empty. A record awaiting a decision is now just an invoice
or a bill whose own status says so.

Approve and reject therefore act on the SOURCE record. One record, one
lifecycle, nothing to keep consistent between two of them.
"""
from fastapi import APIRouter, Depends, HTTPException

from ..dependencies import porth, require_permission
from ..director import SampleAppDirector
from porth_common.context.correlation import context_hash

from ..ffug_client import FingerprintUnavailable, fingerprint_async
from ..repository import (
    TransitionNotAllowedError,
    UnknownRecordTypeError,
    fingerprint_document,
)

#: This app's own registered identity. The callback's `aud` will be this, and
#: `verify_callback` recomputes the correlation hash from its own verified
#: audience — so what is hashed HERE has to be the same string, or nothing ever
#: correlates. Read from the environment in the ingress; spelled once here.
SOURCE_SERVICE = "sample-app"

router = APIRouter(prefix="/sample/approvals", tags=["approvals"])


def _decide(director: SampleAppDirector, record_type: str, record_id: str, approve: bool) -> dict:
    try:
        decide = director.repository.approve if approve else director.repository.reject
        return decide(record_type, record_id)
    except UnknownRecordTypeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except TransitionNotAllowedError as exc:
        # 409, not 404. The record may well exist — it has already been decided,
        # or was never submitted. "Not found" would send someone looking for a
        # missing record instead of at the status it actually has.
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("", dependencies=[Depends(require_permission("approvals.read"))])
def list_approvals(director: SampleAppDirector = Depends(porth)) -> list[dict]:
    return director.repository.list_pending_approvals()


@router.get(
    "/{record_type}/{record_id}",
    dependencies=[Depends(require_permission("approvals.read"))],
)
def read_approval(
    record_type: str, record_id: str, director: SampleAppDirector = Depends(porth)
) -> dict:
    """One record's current state, for a screen watching a queued fingerprint.

    The list endpoint returns only what awaits a decision, so an approved record
    leaves it immediately — which was invisible while the fingerprint arrived
    inside the approve call. Reading `approvals.read`, not `write`: watching a
    decision is not making one.
    """
    try:
        approval = director.repository.get_approval(record_type, record_id)
    except UnknownRecordTypeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if approval is None:
        raise HTTPException(status_code=404, detail=f"no {record_type} {record_id}")
    return approval


@router.post(
    "/{record_type}/{record_id}/approve",
    dependencies=[Depends(require_permission("approvals.write"))],
)
def approve(record_type: str, record_id: str, director: SampleAppDirector = Depends(porth)) -> dict:
    """Approve a record, then have ffug fingerprint the decision — later (PORTH-621).

    The order matters and so does the error handling. The approval is the
    business outcome: it is committed first, and it does not fail because a
    fixture service on the internal plane was unreachable. The fingerprint is
    evidence ABOUT that outcome, so a failure to obtain it is reported on the
    response rather than raised — visible, and not mistaken for "no fingerprint
    was wanted here".

    PORTH-621 changed only *when* the evidence arrives. The endpoint now returns
    with the fingerprint `queued`, and ffug's completion lands minutes or a
    redelivery later on a separate ingress. That the endpoint already tolerated
    "approved, no fingerprint" is why this is a smaller change than it sounds:
    the state that had to be added is `queued`, not the absence.
    """
    approval = _decide(director, record_type, record_id, approve=True)
    document = fingerprint_document(approval)

    # Read once. `async_trace_id` resolves on first read and holds thereafter,
    # so the value hashed below, the value stored on the record and the value
    # sent to ffug are the same string by construction rather than by three
    # call sites agreeing.
    trace_id = director.async_trace_id

    # Stored BEFORE the work is requested, and that order is not incidental. The
    # callback can in principle arrive before this call returns; a record that
    # has no correlation hash yet would refuse an answer that was perfectly
    # correct. Committing the expectation first costs one write and removes the
    # race entirely.
    stored = director.repository.begin_fingerprint(
        record_type,
        record_id,
        trace_id=trace_id,
        correlation_hash=context_hash(
            environment=director.environment,
            tenant_id=director.tenant_id,
            # OUR id, not ffug's. The hash is anchored to the initiator, which
            # is what the callback's verified `aud` will name.
            source_service=SOURCE_SERVICE,
            trace_id=trace_id,
        ),
    )

    try:
        fingerprint_async(director, document, trace_id=trace_id)
    except FingerprintUnavailable as exc:
        # The approval stands. What is reported is that no fingerprint is coming
        # — and the record is put back to having no fingerprint lifecycle at all,
        # rather than left `queued` forever waiting for work nobody accepted.
        cleared = director.repository.abandon_fingerprint(record_type, record_id)
        return {**cleared, "fingerprint_document": document, "fingerprint_error": str(exc)}

    return {**stored, "fingerprint_document": document}


@router.post(
    "/{record_type}/{record_id}/reject",
    dependencies=[Depends(require_permission("approvals.write"))],
)
def reject(record_type: str, record_id: str, director: SampleAppDirector = Depends(porth)) -> dict:
    return _decide(director, record_type, record_id, approve=False)
