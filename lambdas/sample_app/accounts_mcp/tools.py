"""The accounts tools.

Every tool takes the MCP ``Context`` and reads the caller from the HTTP request it
arrived on (``request.state.director``, set by ``DirectorMiddleware``). Nothing about
the caller comes from the tool's arguments.

``PERMISSION`` maps each tool to the ``sample-app`` key it needs; ``None`` means any
signed-in caller. It is the single statement of what a tool requires, read by the
check below and by the tests that hold it to the web routes.
"""

# No `from __future__ import annotations`: the SDK builds each tool's input schema
# from these annotations at registration, and postponed (string) annotations would
# have to be resolved again in another module's namespace.
import datetime as _dt
import logging
import time
from typing import Any, Literal, Optional

from fastapi import HTTPException
from mcp.server.fastmcp import Context, FastMCP
from mcp.server.fastmcp.exceptions import ToolError

from sample_app.dependencies import author
from sample_app.repository import TransitionNotAllowedError, UnknownRecordTypeError
from sample_app.routers import ap, approvals, ar, dashboard

log = logging.getLogger("sample_app.accounts_mcp")

GUIDE = (
    "EMS accounts for one tenant: receivables (invoices to customers), payables (bills "
    "from vendors) and the approval queue between them. You act as the signed-in user; "
    "who_am_i shows their roles and what they may do. Invoices start as drafts and are "
    "sent for approval with send_invoice_for_approval; bills are recorded and sent with "
    "send_bill_for_approval. Someone holding approvals.write decides them. A tool the "
    "user's role does not allow says which permission it needs — report that, do not "
    "retry. Amounts are in the tenant's currency."
)

PERMISSION: dict[str, Optional[str]] = {
    "who_am_i": None,
    "accounts_summary": "dashboard.read",
    "list_invoices": "ar.invoices.read",
    "overdue_receivables": "ar.invoices.read",
    "raise_invoice": "ar.invoices.write",
    "send_invoice_for_approval": "ar.invoices.write",
    "list_bills": "ap.bills.read",
    "record_bill": "ap.bills.write",
    "send_bill_for_approval": "ap.bills.write",
    "approval_queue": "approvals.read",
    "decide": "approvals.write",
}

#: Tools that change the books, for the audit line.
CHANGES_BOOKS = {"raise_invoice", "send_invoice_for_approval", "record_bill",
                 "send_bill_for_approval", "decide"}


def caller(ctx: Context) -> Any:
    request = ctx.request_context.request
    director = getattr(getattr(request, "state", None), "director", None)
    if director is None:
        raise ToolError("No Porth identity on this request.")
    return director


def act(ctx: Context, tool: str, work) -> Any:
    """Check the tool's permission, do the work, translate the app's refusals, and
    write one audit line — whatever the outcome."""
    director = caller(ctx)
    started, outcome = time.monotonic(), "ok"
    try:
        needed = PERMISSION[tool]
        if needed and not director.can_perform(needed):
            outcome = "denied"
            raise ToolError(f"Your EMS role does not allow this: it needs the '{needed}' permission.")
        try:
            return work(director)
        except HTTPException as exc:
            outcome = "refused"
            raise ToolError(_reason(exc)) from None
        except (TransitionNotAllowedError, UnknownRecordTypeError) as exc:
            outcome = "refused"
            raise ToolError(str(exc)) from None
    except ToolError:
        if outcome == "ok":
            outcome = "refused"
        raise
    except Exception as exc:
        outcome = "failed"
        log.warning("accounts_mcp.failure tool=%s error=%s", tool, type(exc).__name__)
        raise ToolError("EMS could not complete that just now; try again shortly.") from None
    finally:
        log.info(
            "accounts_mcp.call tool=%s changes_books=%s tenant=%s environment=%s actor=%s outcome=%s ms=%d",
            tool, tool in CHANGES_BOOKS, director.tenant_id, director.environment, author(director),
            outcome, round((time.monotonic() - started) * 1000),
        )


def _reason(exc: HTTPException) -> str:
    detail = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
    return {
        404: f"Not found: {detail}",
        409: f"Not possible in its current state: {detail}",
    }.get(exc.status_code, detail)


def _today() -> str:
    return _dt.date.today().isoformat()


def build_server() -> FastMCP:
    server = FastMCP("ems-accounts", instructions=GUIDE, stateless_http=True, json_response=True)

    @server.tool()
    def who_am_i(ctx: Context) -> dict[str, Any]:
        """The signed-in user here: tenant, environment, roles and EMS permissions."""
        def work(d):
            return {
                "tenant": d.tenant_id, "environment": d.environment,
                "user": author(d), "email": d.user_email or None,
                "roles": list(d.roles), "permissions": sorted(d.permissions),
            }
        return act(ctx, "who_am_i", work)

    @server.tool()
    def accounts_summary(ctx: Context) -> dict[str, Any]:
        """Receivables and payables outstanding, approvals waiting, and the net position."""
        return act(ctx, "accounts_summary", lambda d: dashboard.get_dashboard(director=d))

    @server.tool()
    def list_invoices(ctx: Context, status: Optional[str] = None) -> list[dict[str, Any]]:
        """Invoices to customers, optionally only those with a given status
        (draft, pending_approval, approved, rejected, paid)."""
        def work(d):
            rows = ar.list_invoices(director=d)
            return [r for r in rows if status is None or r.get("status") == status]
        return act(ctx, "list_invoices", work)

    @server.tool()
    def overdue_receivables(ctx: Context, as_of: Optional[str] = None) -> dict[str, Any]:
        """Unpaid invoices whose due date is before `as_of` (YYYY-MM-DD, default today),
        oldest first, with the total owed."""
        cutoff = as_of or _today()

        def work(d):
            overdue = sorted(
                (r for r in ar.list_invoices(director=d)
                 if r.get("status") not in ("paid", "rejected") and r.get("due_date") and r["due_date"] < cutoff),
                key=lambda r: r["due_date"],
            )
            return {"as_of": cutoff, "count": len(overdue),
                    "total": round(sum(float(r.get("amount", 0)) for r in overdue), 2), "invoices": overdue}
        return act(ctx, "overdue_receivables", work)

    @server.tool()
    def raise_invoice(ctx: Context, customer_name: str, amount: float, due_date: str = "") -> dict[str, Any]:
        """Raise a draft invoice to a customer. Send it with send_invoice_for_approval."""
        body = ar.CreateInvoiceRequest(customer_name=customer_name, amount=amount, due_date=due_date)
        return act(ctx, "raise_invoice", lambda d: ar.create_invoice(body, director=d))

    @server.tool()
    def send_invoice_for_approval(ctx: Context, invoice_id: str) -> dict[str, Any]:
        """Send a draft invoice to the approval queue."""
        return act(ctx, "send_invoice_for_approval", lambda d: ar.submit_invoice(invoice_id, director=d))

    @server.tool()
    def list_bills(ctx: Context, status: Optional[str] = None) -> list[dict[str, Any]]:
        """Bills from vendors, optionally only those with a given status."""
        def work(d):
            rows = ap.list_bills(director=d)
            return [r for r in rows if status is None or r.get("status") == status]
        return act(ctx, "list_bills", work)

    @server.tool()
    def record_bill(ctx: Context, vendor_name: str, amount: float, due_date: str = "") -> dict[str, Any]:
        """Record a bill from a vendor. Send it with send_bill_for_approval."""
        body = ap.CreateBillRequest(vendor_name=vendor_name, amount=amount, due_date=due_date)
        return act(ctx, "record_bill", lambda d: ap.create_bill(body, director=d))

    @server.tool()
    def send_bill_for_approval(ctx: Context, bill_id: str) -> dict[str, Any]:
        """Send a recorded bill to the approval queue."""
        return act(ctx, "send_bill_for_approval", lambda d: ap.submit_bill(bill_id, director=d))

    @server.tool()
    def approval_queue(ctx: Context) -> list[dict[str, Any]]:
        """Invoices and bills waiting for a decision, oldest first."""
        return act(ctx, "approval_queue", lambda d: approvals.list_approvals(director=d))

    @server.tool()
    def decide(ctx: Context, record_type: Literal["invoice", "bill"], record_id: str,
               decision: Literal["approve", "reject"]) -> dict[str, Any]:
        """Approve or reject an invoice or bill waiting in the approval queue."""
        def work(d):
            if decision == "approve":
                return approvals.approve(record_type, record_id, director=d)
            return approvals.reject(record_type, record_id, director=d)
        return act(ctx, "decide", work)

    return server
