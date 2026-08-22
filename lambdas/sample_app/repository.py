"""The sample app's data access — one tenant, one environment, per instance.

PORTH-594. This table predates ADR-Z8. Porth gained the environment dimension
and every Porth row moved to ``ENV#{slot}#…``; this one never followed, so its
rows sat at ``TENANT#{tenant}`` with the environment carried by the table NAME.
That is why the session policy could not fence the environment in
``dynamodb:LeadingKeys``: there was no environment in the key to fence.

Two things changed together, because half a migration on an empty table is
invisible until the first row is written:

**The key carries the environment.** ``ENV#{slot}#TENANT#{tenant}``, the same
shape as Porth's own rows and the shape ``SampleAppSessionPolicy`` now matches.

**The scope is a property of the repository, not an argument to its methods.**
Every method used to take ``tenant_id``, which made the tenant a free string at
each call site — the shape TS-MC.1 exists to prevent, and the one the Director
was adopted to remove. A repository is now built FOR a scope and cannot be asked
about another one. There is no parameter to get wrong.

Both values come from the Director, which got them from the authorizer's own
resolution. Neither is read from the environment: ``PORTH_ENVIRONMENT`` suffixes
the table name and is a DIFFERENT VALUE from the ADR-Z8 slot — ``dev`` versus
``prod`` on this install. Composing the key from the wrong one produces rows
nothing can read and a policy that matches nothing, and each looks like the
other's fault.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone

from dataclasses import dataclass

from boto3.dynamodb.conditions import Key

#: The one status that means "waiting for a human". Named once: a second
#: spelling of it is a record that can never be found again.
PENDING_APPROVAL = "pending_approval"


@dataclass(frozen=True)
class _RecordSpec:
    record_type: str
    prefix: str
    label: str
    id_field: str
    party_field: str
    #: The states a record may be submitted FROM. Invoices are created `draft`
    #: and bills `pending`; both are working states, and neither is a decision.
    submittable_from: frozenset


#: The record types that can be approved. Adding one is a line here, not a
#: branch in three places.
APPROVABLE: dict[str, _RecordSpec] = {
    "invoice": _RecordSpec(
        record_type="invoice", prefix="INVOICE#", label="Invoice",
        id_field="invoice_id", party_field="customer_name",
        submittable_from=frozenset({"draft"}),
    ),
    "bill": _RecordSpec(
        record_type="bill", prefix="BILL#", label="Bill",
        id_field="bill_id", party_field="vendor_name",
        submittable_from=frozenset({"pending"}),
    ),
}


class UnknownRecordTypeError(ValueError):
    """A record type that cannot be approved, refused rather than guessed at."""


class TransitionNotAllowedError(Exception):
    """The record does not exist, or is not in a state this transition allows."""


def _spec(record_type: str) -> _RecordSpec:
    spec = APPROVABLE.get(record_type)
    if spec is None:
        raise UnknownRecordTypeError(
            f"{record_type!r} is not approvable; expected one of "
            f"{', '.join(sorted(APPROVABLE))}"
        )
    return spec


def _conditional_check_failed(exc: Exception) -> bool:
    """True when DynamoDB refused the write because our guard said so."""
    code = getattr(exc, "response", {}).get("Error", {}).get("Code")
    return code == "ConditionalCheckFailedException"


#: Exactly what the fingerprint covers (PORTH-599). Named once and kept small
#: on purpose: the point of showing a digest to a human is that they can see
#: what went into it, and a document nobody can reproduce by hand proves nothing
#: to the person looking at it.
FINGERPRINT_FIELDS = ("record_type", "record_id", "counterparty", "amount")


def fingerprint_document(approval: dict) -> dict:
    """The substance of a record, in a fixed field order."""
    return {field: approval.get(field, "") for field in FINGERPRINT_FIELDS}


def _as_approval(record_type: str, spec: _RecordSpec, item: dict) -> dict:
    """One record, in the shape the approvals screen reads.

    The screen has always expected `record_type`, `amount`, `submitted_by` and
    `submitted_at`. Nothing produced them, so even a row that had somehow
    reached the list would have rendered blank columns.
    """
    return {
        "record_id": item.get(spec.id_field, ""),
        "record_type": record_type,
        "counterparty": item.get(spec.party_field, ""),
        "amount": item.get("amount", "0"),
        "status": item.get("status", ""),
        "submitted_by": item.get("submitted_by", ""),
        "submitted_at": item.get("submitted_at", ""),
        # Present once ffug has fingerprinted the decision. Empty is a real
        # state — the record was approved before the fingerprint existed, or
        # ffug was unreachable — so the screen shows the difference rather than
        # rendering a blank that reads as "no fingerprint was ever wanted".
        "fingerprint_prime": item.get("fingerprint_prime", ""),
        "fingerprint_digest": item.get("fingerprint_digest", ""),
    }

#: The table NAME's environment — the deployment axis. Not the data axis; see
#: the module docstring. These are different values and conflating them is the
#: specific mistake this module is arranged to prevent.
TABLE_NAME = f"porth-sample-app-{os.environ.get('PORTH_ENVIRONMENT', 'dev')}"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ScopeMissingError(ValueError):
    """The repository was built without a full scope, so it refuses to exist.

    Raised rather than defaulted. An empty environment yields
    ``ENV##TENANT#acme`` — a key that is written successfully, matches no
    session policy, and is never read back. The failure would surface as "the
    invoice I just created is not in the list", several layers from its cause.
    """


class SampleAppRepository:
    """This app's table, bound to one tenant in one environment."""

    def __init__(self, dynamodb_resource, *, environment: str, tenant_id: str) -> None:
        if not environment or not tenant_id:
            raise ScopeMissingError(
                f"repository needs both an environment and a tenant; got "
                f"environment={environment!r} tenant_id={tenant_id!r}"
            )
        self.table = dynamodb_resource.Table(TABLE_NAME)
        self.environment = environment
        self.tenant_id = tenant_id
        #: Every row this instance can address. Composed once: a second place
        #: that builds this string is a second place it can be built wrong.
        self.partition = f"ENV#{environment}#TENANT#{tenant_id}"

    # -- reads ---------------------------------------------------------------

    def _list(self, sk_prefix: str) -> list[dict]:
        resp = self.table.query(
            KeyConditionExpression=Key("pk").eq(self.partition)
            & Key("sk").begins_with(sk_prefix)
        )
        return resp.get("Items", [])

    def list_invoices(self) -> list[dict]:
        return self._list("INVOICE#")

    def list_bills(self) -> list[dict]:
        return self._list("BILL#")

    def list_pending_approvals(self) -> list[dict]:
        """Everything awaiting a decision, across both record types.

        Derived from the records themselves — there is no APPROVAL# row and
        never was. The previous version queried that prefix, which nothing has
        ever written, so this list was structurally always empty (PORTH-597).
        """
        pending: list[dict] = []
        for record_type, spec in APPROVABLE.items():
            for item in self._list(spec.prefix):
                if item.get("status") == PENDING_APPROVAL:
                    pending.append(_as_approval(record_type, spec, item))
        return sorted(pending, key=lambda a: a["submitted_at"])

    # -- writes --------------------------------------------------------------

    def create_invoice(self, data: dict) -> dict:
        invoice_id = str(uuid.uuid4())
        item = {
            "pk": self.partition, "sk": f"INVOICE#{invoice_id}",
            "invoice_id": invoice_id, "tenant_id": self.tenant_id,
            "environment": self.environment,
            "customer_name": data["customer_name"], "amount": str(data["amount"]),
            "status": "draft", "due_date": data.get("due_date", ""),
            "created_by": data.get("created_by", ""), "created_at": _now(),
        }
        self.table.put_item(Item=item)
        return item

    def create_bill(self, data: dict) -> dict:
        bill_id = str(uuid.uuid4())
        item = {
            "pk": self.partition, "sk": f"BILL#{bill_id}",
            "bill_id": bill_id, "tenant_id": self.tenant_id,
            "environment": self.environment,
            "vendor_name": data["vendor_name"], "amount": str(data["amount"]),
            "status": "pending", "due_date": data.get("due_date", ""),
            "created_by": data.get("created_by", ""), "created_at": _now(),
        }
        self.table.put_item(Item=item)
        return item

    def submit_for_approval(self, record_type: str, record_id: str, *, by: str) -> dict:
        """Move a record from its own working state into the approval queue.

        This is the step that did not exist. Invoices were created `draft` and
        bills `pending`, the approvals list queried a prefix nothing wrote, and
        there was no action anywhere that moved a record from one to the other —
        so nothing could ever appear for a decision.
        """
        spec = _spec(record_type)
        return self._transition(
            spec,
            record_id,
            to=PENDING_APPROVAL,
            allowed_from=spec.submittable_from,
            extra={"submitted_by": by, "submitted_at": _now()},
        )

    def approve(self, record_type: str, record_id: str) -> dict:
        spec = _spec(record_type)
        return self._transition(
            spec, record_id, to="approved", allowed_from={PENDING_APPROVAL}
        )

    def reject(self, record_type: str, record_id: str) -> dict:
        spec = _spec(record_type)
        return self._transition(
            spec, record_id, to="rejected", allowed_from={PENDING_APPROVAL}
        )

    def _transition(
        self, spec: "_RecordSpec", record_id: str, *,
        to: str, allowed_from: set[str], extra: dict | None = None,
    ) -> dict:
        """One status change, guarded by DynamoDB rather than by a prior read.

        The condition does two jobs at once, and both were broken before:

        * **the record must exist.** ``UpdateItem`` is an UPSERT — the previous
          approve() wrote to ``APPROVAL#{id}`` with no condition, so approving an
          id that did not exist silently CREATED a row holding a pk, an sk and a
          status, and nothing else. The only code path that could write to that
          prefix wrote junk, and the list filtered it out again, so it was
          invisible junk.
        * **it must be in a state this transition is legal from.** Read-then-write
          would race with a second approver; the condition cannot.
        """
        names = {"#s": "status"}
        values = {f":from{i}": v for i, v in enumerate(sorted(allowed_from))}
        values[":to"] = to
        sets = ["#s = :to"]
        for index, (key, value) in enumerate(sorted((extra or {}).items())):
            names[f"#x{index}"] = key
            values[f":x{index}"] = value
            sets.append(f"#x{index} = :x{index}")

        try:
            resp = self.table.update_item(
                Key={"pk": self.partition, "sk": f"{spec.prefix}{record_id}"},
                UpdateExpression="SET " + ", ".join(sets),
                ExpressionAttributeNames=names,
                ExpressionAttributeValues=values,
                ConditionExpression=(
                    "attribute_exists(pk) AND #s IN ("
                    + ", ".join(k for k in values if k.startswith(":from"))
                    + ")"
                ),
                ReturnValues="ALL_NEW",
            )
        except Exception as exc:  # noqa: BLE001 — a refusal is a result
            if _conditional_check_failed(exc):
                raise TransitionNotAllowedError(
                    f"{spec.label} {record_id} is not in "
                    f"{' or '.join(sorted(allowed_from))}, or does not exist"
                ) from exc
            raise
        return _as_approval(spec.record_type, spec, resp.get("Attributes", {}))

    def attach_fingerprint(self, record_type: str, record_id: str, *, prime: str, digest: str) -> dict:
        """Record ffug's answer against the decision it describes.

        Written after the transition rather than as part of it, deliberately.
        The approval is the business outcome and must not fail because a fixture
        service was unreachable; the fingerprint is evidence about that outcome
        and can arrive late or not at all. Conditioned on the record existing so
        this cannot conjure one — the same upsert trap PORTH-597 removed.
        """
        spec = _spec(record_type)
        resp = self.table.update_item(
            Key={"pk": self.partition, "sk": f"{spec.prefix}{record_id}"},
            UpdateExpression="SET #p = :p, #d = :d",
            ExpressionAttributeNames={"#p": "fingerprint_prime", "#d": "fingerprint_digest"},
            ExpressionAttributeValues={":p": prime, ":d": digest},
            ConditionExpression="attribute_exists(pk)",
            ReturnValues="ALL_NEW",
        )
        return _as_approval(record_type, spec, resp.get("Attributes", {}))

    # -- derived -------------------------------------------------------------

    def dashboard_summary(self) -> dict:
        invoices = self.list_invoices()
        bills = self.list_bills()
        approvals = self.list_pending_approvals()
        outstanding = sum(1 for i in invoices if i.get("status") != "paid")
        total_ar = sum(float(i.get("amount", 0)) for i in invoices if i.get("status") != "paid")
        bills_due = sum(1 for b in bills if b.get("status") == "pending")
        total_ap = sum(float(b.get("amount", 0)) for b in bills if b.get("status") == "pending")
        return {
            "outstanding_invoices": outstanding, "total_ar": total_ar,
            "bills_due": bills_due, "total_ap": total_ap,
            "pending_approvals": len(approvals), "cash_position": total_ar - total_ap,
        }
