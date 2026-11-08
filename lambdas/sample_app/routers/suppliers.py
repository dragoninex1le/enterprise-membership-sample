"""/suppliers/* — what a supplier's contact can do in the buyer's books.

Reached on the sample app's SUPPLIERS API (mapped under ``suppliers`` on the tenant
API hosts) behind Porth's bearer authorizer, with the delegated session the supplier
portal obtained for a SupplierLink contact (``auth_source == "exchange"``,
``connector_type == "supplierlink"``). Porth's context names the tenant (the buyer),
the contact (``external_id``), the supplier (``store_external_id``) and the EMS role
the buyer mapped SupplierLink's role to.

A supplier submits invoices to the buyer and follows them through the buyer's
approval — only their own. The supplier id used for that is Porth's, so no request
can widen it. Nothing here approves, and no other route in the app serves a supplier
(handler.SupplierBoundary).
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from ..dependencies import porth, require_permission
from ..director import SampleAppDirector
from .. import trace

NETWORK = "supplierlink"


def delegated(director) -> dict:
    """Porth's context for a delegated caller, or {} for anyone else."""
    ctx = getattr(director, "_raw_context", None) or {}
    return ctx if ctx.get("auth_source") == "exchange" else {}


def supplier_contact(request: Request) -> None:
    director = getattr(request.state, "director", None)
    if director is None or not director.tenant_id:
        trace.event("suppliers.refused", logging.INFO, reason="no_porth_context", director=director is not None)
        raise HTTPException(401, "No Porth context on this request.")
    ctx = delegated(director)
    trace.event("suppliers.who", tenant=director.tenant_id, delegated=bool(ctx),
                connector=ctx.get("connector_type"), supplier=ctx.get("store_external_id"),
                user=director.porth_user_id or director.user_id)
    if ctx.get("connector_type") != NETWORK or not ctx.get("store_external_id"):
        trace.event("suppliers.refused", logging.INFO, reason="suppliers_only", connector=ctx.get("connector_type"),
                    has_supplier=bool(ctx.get("store_external_id")))
        raise HTTPException(403, "suppliers_only")


router = APIRouter(prefix="/suppliers", tags=["suppliers"], dependencies=[Depends(supplier_contact)])


class SupplierInvoice(BaseModel):
    vendor_name: str = Field(min_length=1, max_length=200, description="The supplier's trading name, as invoiced")
    amount: float = Field(gt=0)
    due_date: str = ""
    supplier_reference: str = Field("", max_length=64, description="The supplier's own invoice number")


def _supplier(director) -> str:
    return delegated(director)["store_external_id"]


@router.get("/me")
def me(director: SampleAppDirector = Depends(porth)) -> dict:
    ctx = delegated(director)
    return {
        "buyer_tenant": director.tenant_id,
        "supplier": ctx.get("store_external_id"),
        "contact": ctx.get("external_id"),
        "session_id": ctx.get("delegated_session_id"),
        "permissions": sorted(director.permissions),
    }


@router.get("/invoices", dependencies=[Depends(require_permission("supplier.invoices.read"))])
def my_invoices(director: SampleAppDirector = Depends(porth)) -> list[dict]:
    return director.repository.supplier_invoices(_supplier(director))


@router.get("/invoices/{bill_id}", dependencies=[Depends(require_permission("supplier.invoices.read"))])
def my_invoice(bill_id: str, director: SampleAppDirector = Depends(porth)) -> dict:
    found = director.repository.supplier_invoice(_supplier(director), bill_id)
    if found is None:
        raise HTTPException(404, f"No invoice {bill_id} from you.")
    return found


@router.post("/invoices", dependencies=[Depends(require_permission("supplier.invoices.submit"))])
def submit_invoice(body: SupplierInvoice, director: SampleAppDirector = Depends(porth)) -> dict:
    return director.repository.create_supplier_invoice(
        supplier_id=_supplier(director),
        submitted_by=delegated(director).get("external_id", ""),
        data=body.model_dump(),
    )
