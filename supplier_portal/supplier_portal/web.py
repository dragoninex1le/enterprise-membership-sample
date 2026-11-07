"""The supplier portal function's routes.

``POST /suppliers/session`` — the supplier's client trades a SupplierLink assertion
for a Porth session in the buyer's tenant. On the sample app's SUPPLIERS API (mapped
under ``suppliers`` on the tenant API hosts) with no Porth authorizer: the caller has
no Porth credential yet. Body: ``{"assertion": "<compact JWS>"}``.

    200 {token, session_id, expires_at, api_base_url}
    401 {"error": "assertion_rejected"}    any verification failure, all alike
    403 {"error": "buyer_not_linked"}      the buyer account is not linked to EMS
    403 {"error": "other_tenants_host"}    linked, but to another tenant than this host's
    4xx {"error": <Porth's code>}          Porth refused (porth_session.ANSWER_STATUS)
    503 {"error": "porth_unavailable"}

``GET | PUT /sample/suppliers/link`` and ``DELETE /sample/suppliers/link/{buyer}`` —
the buyer's tenant admin links their SupplierLink buyer account. On the browser API
with the admin's session. Needs ``suppliers.manage``; not available to a delegated
caller, nor to the platform operator (a link belongs to one tenant).
"""

from __future__ import annotations

import logging
import os
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from supplier_portal import assertion, porth_session
from supplier_portal.links import ClaimedByAnotherTenant, Links
from supplier_portal.hosts import OwnUiCors, tenant_on

log = logging.getLogger("supplier_portal")
log.setLevel(os.environ.get("SUPPLIER_PORTAL_LOG_LEVEL", "INFO"))

MANAGE = "suppliers.manage"


class SessionRequest(BaseModel):
    assertion: str = Field(min_length=1, max_length=4096)


class LinkRequest(BaseModel):
    buyer: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")


_KEY = None


def supplierlink_key():
    """SupplierLink's public key (PEM, SSM String), read once per container."""
    global _KEY
    if _KEY is None:
        import boto3

        pem = boto3.client("ssm").get_parameter(Name=os.environ["SUPPLIERLINK_PUBLIC_KEY_PARAMETER"])["Parameter"]["Value"]
        _KEY = assertion.load_public_key(pem)
    return _KEY


def links() -> Links:
    return Links()


def mint_transport():
    """The call to Porth. A dependency so tests can stand in for Porth."""
    return None


def tenant_admin(request: Request) -> Any:
    who = getattr(request.state, "director", None)
    if who is None or not who.tenant_id:
        raise HTTPException(401, "No Porth context on this request.")
    if (getattr(who, "_raw_context", None) or {}).get("auth_source") == "exchange":
        raise HTTPException(403, "delegated_principal_refused")
    if who.is_platform_admin:
        raise HTTPException(403, "A buyer link belongs to one tenant. Sign in to that tenant to link it.")
    if not who.can_perform(MANAGE):
        raise HTTPException(403, f"Missing permission: {MANAGE}")
    return who


def build() -> FastAPI:
    from porth_common.director import DirectorMiddleware

    api = FastAPI(title="EMS supplier portal")
    api.add_middleware(DirectorMiddleware)
    api.add_middleware(OwnUiCors)

    @api.post("/suppliers/session")
    def session(body: SessionRequest, request: Request, store: Links = Depends(links),
                transport=Depends(mint_transport)) -> Any:
        try:
            contact = assertion.check(body.assertion, public_key=supplierlink_key())
        except assertion.Unverified as why:
            log.info("supplier_session.rejected why=%s", why.why)
            return JSONResponse({"error": "assertion_rejected"}, status_code=401)

        link = store.find(contact.buyer)
        if link is None:
            log.info("supplier_session.unlinked buyer=%s", contact.buyer)
            return JSONResponse({"error": "buyer_not_linked"}, status_code=403)
        if tenant_on(request.headers.get("host", "")) != link.tenant:
            log.info("supplier_session.wrong_host buyer=%s", contact.buyer)
            return JSONResponse({"error": "other_tenants_host"}, status_code=403)

        from porth_common.context.persisted import PersistedContext, PersistedContextError

        try:
            record = PersistedContext.restore(link.porth_context)
        except PersistedContextError:
            log.error("supplier_session.link_context_unreadable buyer=%s", contact.buyer)
            return JSONResponse({"error": "porth_unavailable"}, status_code=503)
        if record.tenant_id != link.tenant:
            log.error("supplier_session.link_context_mismatch buyer=%s", contact.buyer)
            return JSONResponse({"error": "porth_unavailable"}, status_code=503)

        outcome = porth_session.request_session(record, contact, call=transport)
        if not outcome.granted:
            return JSONResponse({"error": outcome.code}, status_code=outcome.status)
        return {"token": outcome.token, "session_id": outcome.session_id,
                "expires_at": outcome.expires_at, "api_base_url": outcome.api_base_url or None}

    @api.get("/sample/suppliers/link")
    def show(who: Any = Depends(tenant_admin), store: Links = Depends(links)) -> Any:
        return [l.shown() for l in store.of_tenant(who.tenant_id)]

    @api.put("/sample/suppliers/link")
    def link(body: LinkRequest, who: Any = Depends(tenant_admin), store: Links = Depends(links)) -> Any:
        from porth_common.context.persisted import PersistedContext

        context = PersistedContext.from_director(who).to_json()
        try:
            made = store.link(buyer=body.buyer, tenant=who.tenant_id, porth_context=context,
                              by=who.porth_user_id or who.user_id)
        except ClaimedByAnotherTenant:
            raise HTTPException(409, "That SupplierLink buyer account is linked to another tenant.") from None
        log.info("supplier_link.linked tenant=%s buyer=%s", who.tenant_id, body.buyer)
        return made.shown()

    @api.delete("/sample/suppliers/link/{buyer}")
    def unlink(buyer: str, who: Any = Depends(tenant_admin), store: Links = Depends(links)) -> Any:
        if not store.unlink(buyer=buyer, tenant=who.tenant_id):
            raise HTTPException(404, f"{buyer} is not linked to this tenant.")
        log.info("supplier_link.unlinked tenant=%s buyer=%s", who.tenant_id, buyer)
        return {"buyer": buyer, "linked": False}

    return api
