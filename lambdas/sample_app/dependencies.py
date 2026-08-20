from __future__ import annotations

from fastapi import Depends, HTTPException, Request

from porth_common.director import get_director

from .director import SampleAppDirector


def require_permission(permission_key: str):
    """Refuse the request unless the caller holds *permission_key*.

    PORTH-613 — this asks the Director rather than a hand-rolled context object.
    The check itself is one line either way; what changes is what happens when it
    fails. ``can_perform`` logs WHICH of two very different faults occurred:

        DENIED ar.invoices.read — not held by this caller
        DENIED ar.invoices.read — not held, and not a Porth permission

    the second meaning the permission may never have been seeded, in which case
    nobody holds it and granting is not the fix. From a 403 alone those are
    indistinguishable, and this app spent an evening on exactly that ambiguity.
    """

    def dependency(request: Request) -> None:
        director = getattr(request.state, "director", None)
        if director is None:
            # No Director attached: the request never carried an authorizer
            # context. That is an integration fault, not a permission one, and
            # calling it 403 sent us looking for missing grants for hours
            # (PORTH-612). 401 says "you are not authenticated here", which is
            # what actually happened.
            raise HTTPException(
                status_code=401,
                detail="No Porth context on this request — the API is not behind "
                       "the Porth authorizer, or the call did not reach it.",
            )
        if not director.can_perform(permission_key):
            raise HTTPException(
                status_code=403, detail=f"Missing permission: {permission_key}"
            )

    return dependency


def porth(director: SampleAppDirector = Depends(get_director)) -> SampleAppDirector:
    """The request's Director, typed for this app. Use as a route dependency."""
    return director
