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
from ..ffug_client import FingerprintUnavailable, fingerprint
from ..repository import (
    TransitionNotAllowedError,
    UnknownRecordTypeError,
    fingerprint_document,
)

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


@router.post(
    "/{record_type}/{record_id}/approve",
    dependencies=[Depends(require_permission("approvals.write"))],
)
def approve(record_type: str, record_id: str, director: SampleAppDirector = Depends(porth)) -> dict:
    """Approve a record, then have ffug fingerprint the decision (PORTH-599).

    The order matters and so does the error handling. The approval is the
    business outcome: it is committed first, and it does not fail because a
    fixture service on the internal plane was unreachable. The fingerprint is
    evidence ABOUT that outcome, so a failure to obtain it is reported on the
    response rather than raised — visible, and not mistaken for "no fingerprint
    was wanted here".
    """
    approval = _decide(director, record_type, record_id, approve=True)
    document = fingerprint_document(approval)

    try:
        result = fingerprint(director, document)
    except FingerprintUnavailable as exc:
        return {**approval, "fingerprint_document": document, "fingerprint_error": str(exc)}

    stored = director.repository.attach_fingerprint(
        record_type, record_id, prime=result["prime"], digest=result["digest"]
    )
    return {**stored, "fingerprint_document": document}


@router.post(
    "/{record_type}/{record_id}/reject",
    dependencies=[Depends(require_permission("approvals.write"))],
)
def reject(record_type: str, record_id: str, director: SampleAppDirector = Depends(porth)) -> dict:
    return _decide(director, record_type, record_id, approve=False)
