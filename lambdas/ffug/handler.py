"""ffug — the ADR-Z11 UAT compute target (PORTH-555 Phase A, PORTH-587 Phase B).

**Phase B landed here.** The module docstring used to say that
``resolve_tenant_context`` was "the single seam that changes"; this is that
change. Tenant and environment no longer ride the payload. They come from a
KMS-signed context envelope that :class:`porth_common.director.Director`
verifies before returning anything, and the data access underneath runs on an
STS session narrowed to that one tenant.

What that buys, stated precisely because the fixture exists to demonstrate it:

* **A caller cannot name its own tenant.** ``tenant_id`` is not a field ffug
  reads. It is a signed claim, and forging one requires ``kms:Sign`` on the
  install's context key — which ffug's own role deliberately does not hold
  (HoS condition H1; the denial is what UAT-4 witnesses).
* **Reaching another tenant's partition is refused by DynamoDB, not by ffug.**
  The narrowed session carries a ``dynamodb:LeadingKeys`` condition pinned to
  ``ENV#{env}#TENANT#{tenant}``. There is no branch in this file that could be
  wrong about it, and no ambient DynamoDB grant on the function role to fall
  back to — a narrowing failure is ``AccessDenied``, never silent wide access.
* **The tenant's salt was minted by something else entirely.** ``lifecycle.py``
  seeds it off the bus on ``tenant.created``. This path can read it and cannot
  create it: a caller arriving before the event is refused rather than served
  under an invented salt.

Operations: ``echo`` (store a payload under the caller's tenant, hand it back),
``get`` (read it back), ``hash`` (return ``SHA256(salt : payload)``). Named in
the ``operation`` field, which is what
:class:`porth_common.internal_plane.client.ServiceClient` sends. ``hash`` is the
addition, and it is the reason PORTH-587 amends the "no business logic" rule —
see README.md. It writes nothing, so ``echo`` remains the only writer and the
residue sweep stays a one-prefix question.

Public-repo note (PORTH-533): this repo's Actions logs are world-readable. Log
identifiers only — never a salt, never a payload body, never a token.
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any

from porth_common.context import PersistedContext
from porth_common.context.envelope import EnvelopeError
from porth_common.director import Director
from porth_common.internal_plane.config import (
    ServiceNotActiveError,
    ServicesConfigError,
    UnknownServiceError,
)
from porth_common.protocols.cloud_clients import DOCUMENT_STORE, IDENTITY_BROKER
from porth_common.internal_plane import log_plane_identity

from . import keys, salt

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


TABLE_NAME = os.environ.get("FFUG_TABLE_NAME", "")

#: ffug's own work queue. Not a Porth capability and not reached through the
#: Director: a queue between two services is not a supported integration shape,
#: and this one is not between anybody — it is inside ffug, no different from a
#: row in its own table. Porth owns the crossings; services own their insides.
WORK_QUEUE_URL = os.environ.get("FFUG_WORK_QUEUE_URL", "")

_sqs = None


def _queue():
    global _sqs
    if _sqs is None:
        import boto3

        _sqs = boto3.client("sqs")
    return _sqs


class FfugError(Exception):
    """Typed rejection. Carries a stable code so callers can assert on it."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message

    def to_response(self) -> dict[str, Any]:
        return {"ok": False, "error": {"code": self.code, "message": self.message}}


class FfugDirector(Director):
    """The shared Director, plus ffug's one table.

    ``RESOURCES`` makes the narrowing eager: the STS exchange happens while the
    Director is being built, so a narrowing failure is raised at the boundary
    naming the capability, rather than several frames inside an op wearing
    whatever exception the first DynamoDB call happened to produce.
    """

    #: Declared, not read from the environment (PORTH-623). ffug is one
    #: service whichever of its Lambdas is running — the request ingress, the
    #: worker and the lifecycle consumer all share this identity because they
    #: are components of it, not separate services.
    SERVICE_ID = "ffug"

    RESOURCES = ((DOCUMENT_STORE, "resource"),)

    @property
    def table(self):
        """ffug's table, reached through THIS request's narrowed credentials.

        The argument is a CAPABILITY, not an AWS service name. ``DOCUMENT_STORE``
        maps to DynamoDB on AWS and to Firestore or Cosmos DB elsewhere; passing
        the string ``"dynamodb"`` raises ``UnknownCapabilityError`` at runtime,
        which cost the sample app every one of its pages in PORTH-615. Imported
        rather than spelled, so the same mistake is an ImportError next time.
        """
        if getattr(self, "_ffug_table", None) is None:
            self._ffug_table = self.resource(DOCUMENT_STORE).Table(TABLE_NAME)
        return self._ffug_table


def _active_projection(director: FfugDirector) -> dict[str, Any]:
    """The tenant's projection row, or a typed refusal.

    Three refusals, deliberately distinguishable — from a caller's point of view
    they all mean "no", but they mean very different things to whoever is
    holding the pager:

    * ``tenant_not_provisioned`` — the bus event has not arrived (or never will,
      because ffug was deployed after the tenant existed and no lifecycle event
      has been emitted since).
    * ``tenant_not_active`` — suspended. TS-MC.8: refusal happens on receipt of
      the suspension, so the contamination window is event-delivery latency.
    * ``tenant_not_active`` with no salt — the stripped marker left by
      ``tenant.deleted``. Reached only by a caller holding a still-valid envelope
      for a tenant deleted moments ago.
    """
    environment, tenant_id = director.environment, director.tenant_id
    row = director.table.get_item(
        Key=keys.projection_key(environment, tenant_id)
    ).get("Item")

    log.debug(
        "ffug.projection tenant_id=%s found=%s status=%s has_salt=%s",
        tenant_id,
        row is not None,
        (row or {}).get("status", "-"),
        # PRESENCE, never the value. This repo's logs are world-readable
        # (PORTH-533) and the standing rule is identifiers only — the salt is
        # returned to the approver on purpose, and that is a different audience
        # from a log line that outlives the request.
        bool((row or {}).get("prime")),
    )

    if row is None:
        raise FfugError(
            "tenant_not_provisioned",
            "no projection for this tenant — ffug has seen no lifecycle event for it",
        )
    status = row.get("status")
    if status != "active":
        raise FfugError("tenant_not_active", f"tenant is {status!r}, not active")
    if not row.get("prime"):
        raise FfugError("tenant_not_active", "tenant has no salt")
    return row


def _op_echo(args: dict[str, Any], director: FfugDirector) -> dict[str, Any]:
    item_id = (args.get("item_id") or "").strip()
    if not item_id:
        raise FfugError("missing_item_id", "item_id is required for echo")
    payload = args.get("payload")
    if payload is None:
        raise FfugError("missing_payload", "payload is required for echo")

    _active_projection(director)
    item = {
        **keys.item_key(director.environment, director.tenant_id, item_id),
        "payload": payload,
    }
    director.table.put_item(Item=item)
    return {"ok": True, "operation": "echo", "item_id": item_id, "payload": payload}


def _op_get(args: dict[str, Any], director: FfugDirector) -> dict[str, Any]:
    item_id = (args.get("item_id") or "").strip()
    if not item_id:
        raise FfugError("missing_item_id", "item_id is required for get")

    _active_projection(director)
    result = director.table.get_item(
        Key=keys.item_key(director.environment, director.tenant_id, item_id)
    )
    item = result.get("Item")
    if item is None:
        raise FfugError("not_found", f"no item {item_id} for this tenant")
    return {"ok": True, "operation": "get", "item_id": item_id, "payload": item.get("payload")}


def _op_hash(args: dict[str, Any], director: FfugDirector) -> dict[str, Any]:
    """Return this tenant's digest of *payload*. Stores nothing.

    The same payload under two tenants yields two digests because the salts
    differ. The interesting half is not that they differ — it is that neither
    invocation *could* have produced the other's, because the read one line
    below is bounded by this request's narrowed credentials to this request's
    tenant partition.

    ``prime`` is returned alongside the digest on purpose. It is not a secret
    (see salt.py), and handing it back makes the demo reproducible by hand:
    anyone can confirm the digest is what it claims to be.
    """
    # `hash` takes ONE argument, so the arguments ARE the document. Unchanged
    # and deliberately so: this is the shape scripts/ffug_proof.py sends and
    # the shape the witnessed synchronous round trip uses.
    #
    # Empty is absent, not "hash nothing". `ServiceClient._body` writes `{}` when
    # a caller passes no payload at all, so an empty dict IS how "I sent you
    # nothing" arrives — and digesting it would return a confident, meaningless
    # number that recomputes correctly and describes no document.
    payload = args if args or args == 0 else None
    if payload is None:
        raise FfugError("missing_payload", "payload is required for hash")

    prime = str(_active_projection(director)["prime"])
    digest = salt.digest(prime, payload)
    # Enough to correlate a screen against a log, and not enough to reconstruct
    # anything: the digest PREFIX, and the canonical form's LENGTH rather than
    # the canonical form. The payload is the caller's data and does not belong
    # in a log that outlives the request.
    log.debug(
        "ffug.hashed tenant_id=%s canonical_bytes=%d digest=%s",
        director.tenant_id,
        len(salt.canonical(payload)),
        digest[:12],
    )
    return {
        "ok": True,
        "operation": "hash",
        "prime": prime,
        "digest": digest,
    }


#: A tenant and an environment that belong to nobody. Nothing needs to exist at
#: these names — IAM refuses on the KEY, before any data is consulted, so a
#: denial is returned identically whether the partition is empty or full.
FOREIGN = "__isolation_probe__"

_DENIED = ("AccessDenied", "AccessDeniedException", "not authorized")
_ASSUMED_ROLE = re.compile(r"assumed-role/([^/\s]+)")


def _attempt(description: str, expect: str, call) -> dict[str, Any]:
    """Run one read under this request's narrowed credentials, report the outcome.

    A refusal is a RESULT here, not a fault, so everything is caught. The
    interesting field is ``partitions_seen``: on any read that succeeds it says
    how many DISTINCT tenants came back. One is this tenant. More than one is
    the breach, stated as a number rather than left for a reader to infer from
    a row dump.
    """
    outcome: dict[str, Any] = {"attempt": description, "expect": expect}
    try:
        result = call()
    except Exception as exc:  # noqa: BLE001 — being refused is the point
        message = str(exc)
        outcome["allowed"] = False
        outcome["detail"] = (
            "refused by IAM"
            if any(marker in message for marker in _DENIED)
            else message[:200]
        )
        outcome["partitions_seen"] = 0
    else:
        items = result.get("Items")
        if items is None:
            # BatchGetItem answers under Responses/{table}, not Items. Normalised
            # here so partitions_seen means the same thing on every attempt —
            # a probe whose headline number is only populated for some of its
            # rows reports "0 partitions" for a read that returned plenty.
            items = [
                row
                for rows in (result.get("Responses") or {}).values()
                for row in rows
            ]
        outcome["allowed"] = True
        outcome["partitions_seen"] = len({str(item.get("pk", "")) for item in items})
        outcome["detail"] = f"{result.get('Count', len(items))} row(s)"
    outcome["pass"] = outcome["allowed"] == (expect == "allow")
    return outcome


def _op_isolation_probe(args: dict[str, Any], director: FfugDirector) -> dict[str, Any]:
    """What can ffug's own narrowed session actually reach in ffug's own table?

    The question this exists to settle is "if we just scan the table, what do we
    get?" — and the answer is worth stating before reading the code, because it
    is not the one the design invites you to expect.

    **A scan cannot be bounded to a tenant.** ``dynamodb:LeadingKeys`` binds to
    the partition key of the item being accessed, and a Scan names no key, so
    the condition key is absent from the request context and
    ``ForAllValues:StringLike`` passes VACUOUSLY against it. Granting Scan under
    that condition does not return this tenant's rows; it returns every tenant's.
    It is the one action no key condition can constrain — the same trap Porth
    carries on its platform session policy, which PORTH-580 exists to retire.

    So ffug is granted no Scan at all, and the first attempt below is expected to
    be REFUSED. That is the stronger result: not "you asked for everything and
    were handed your own share", but "you cannot ask the question".

    **What the scan does NOT settle, stated plainly.** It says nothing about the
    Director. Denied, it is denied by the role's action list whether the Director
    narrowed well, badly, or not at all; granted, it would return every tenant
    either way. A scan is blind to narrowing in both directions.

    What isolates the Director's contribution is attempt 3. FfugTenantRole's
    ceiling permits ENV#*#TENANT#* — EVERY tenant — so a session that was not
    narrowed, or narrowed to the wrong tenant, would be ALLOWED to read a
    foreign partition. The denial there is attributable to the session policy
    and to nothing else, which makes it the Director test.

    Attempt 5 is that same test at its sharpest: one BatchGetItem carrying this
    tenant's key AND a foreign one. Two separate queries differ in their whole
    request; these differ in one key. DynamoDB evaluates LeadingKeys over every
    key in the batch (ForAllValues), so the presence of the foreign key alone
    decides it, and a partial answer is not a possible outcome.

    ``_active_projection`` is deliberately NOT called first. This probe reports
    on IAM, and a tenant whose bus event has not arrived should see its own
    partition allowed and empty rather than a provisioning error standing in for
    an isolation answer.
    """
    table = director.table
    environment, tenant_id = director.environment, director.tenant_id

    def query(partition: str):
        return lambda: table.query(
            KeyConditionExpression="pk = :pk",
            ExpressionAttributeValues={":pk": partition},
            Limit=25,
        )

    own = keys.partition(environment, tenant_id)
    foreign_tenant = keys.partition(environment, FOREIGN)
    foreign_env = keys.partition(FOREIGN, tenant_id)
    # The prefix-extension hole, specifically. A LeadingKeys pattern written
    # TENANT#$tenant* rather than the exact key plus TENANT#$tenant#* admits
    # this, and 'acme' reaches 'acme-staging'. Not hypothetical: PORTH-593
    # found exactly that in Porth's own policy. Denied here means the pattern
    # is the strict pair rather than a prefix.
    sibling = f"{own}-probe"
    # The same hole on the ENVIRONMENT axis (PORTH-627). Prefix extension was
    # only ever tested on the tenant half of the key, and the two halves are
    # written by different substitutions — $env and $tenant — so one being
    # strict says nothing about the other. Denied here means 'porth-sample'
    # does not reach 'porth-sample-probe', and by extension not 'porth-dau'
    # either had the environments been named that way.
    env_sibling = keys.partition(f"{environment}-probe", tenant_id)

    store = director.resource(DOCUMENT_STORE)

    def batch_own_plus_foreign():
        return store.batch_get_item(
            RequestItems={
                TABLE_NAME: {
                    "Keys": [
                        keys.projection_key(environment, tenant_id),
                        keys.projection_key(environment, FOREIGN),
                    ]
                }
            }
        )

    attempts = [
        _attempt("scan the whole table, no filter", "deny", lambda: table.scan(Limit=25)),
        # The POSITIVE control, and it is load-bearing. Every other row here
        # passes by being refused, so a fault that denied everything — a wrong
        # table name, a broken role, no narrowing at all — would render as a
        # clean sweep. This row is what stops the suite passing vacuously.
        _attempt(f"query {own}", "allow", query(own)),
        _attempt(f"query {foreign_tenant}", "deny", query(foreign_tenant)),
        _attempt(f"query {sibling}", "deny", query(sibling)),
        _attempt(f"query {env_sibling}", "deny", query(env_sibling)),
        _attempt(f"query {foreign_env}", "deny", query(foreign_env)),
        _attempt(
            "batch-get this tenant AND a foreign one in ONE request",
            "deny",
            batch_own_plus_foreign,
        ),
    ]

    # A partition that REALLY EXISTS, named by the caller (PORTH-598).
    #
    # Every probe above aims at a tenant invented for the purpose, so a refusal
    # is honest but answers a slightly weaker question — IAM refuses on the key
    # before consulting data, so an empty partition and a full one deny
    # identically. That is the correct mechanism and it is also why the rows
    # above cannot distinguish "refused" from "there was nothing there anyway"
    # to someone reading the screen.
    #
    # Naming a real tenant closes that. It is safe to let the caller choose:
    # the value scopes NOTHING — the Director's tenant still comes from the
    # signed envelope, and this string only builds a partition we assert must
    # be refused. Nor does a broken install turn this into a reader: the result
    # carries counts, never rows.
    probe_tenant = (args.get("probe_tenant") or "").strip()
    if probe_tenant and probe_tenant != tenant_id:
        named = keys.partition(environment, probe_tenant)
        attempts.append(_attempt(f"query {named} (a real tenant)", "deny", query(named)))

    # The same, on the ENVIRONMENT axis (PORTH-627), and the one EMS could not
    # ask until it ran two environments.
    #
    # `foreign_env` above aims at a sentinel that exists nowhere, so it is
    # vacuous in exactly the way PORTH-598 objected to for tenants. Naming a
    # REAL environment — one with its own stack, its own table and this same
    # tenant's rows in it — is what makes the refusal evidence.
    #
    # Note where the query goes: THIS environment's table, since that is the
    # only table these credentials can reach at all. The foreign part is the
    # KEY. So a denial here is attributable to the session policy's $env
    # narrowing and not to the resource layer, which is the whole point —
    # FfugTenantRole's ceiling is ENV#*#TENANT#*, so an un-narrowed session
    # would be ALLOWED to read this partition.
    #
    # Safe to let the caller name it for the same reason probe_tenant is: the
    # value scopes nothing. The Director's environment still comes from the
    # signed envelope, and this string only builds a partition asserted to be
    # refused. The result carries counts, never rows.
    probe_environment = (args.get("probe_environment") or "").strip()
    if probe_environment and probe_environment != environment:
        named_env = keys.partition(probe_environment, tenant_id)
        attempts.append(
            _attempt(f"query {named_env} (a real environment)", "deny", query(named_env))
        )

    # The role STS actually issued, asked through the same narrowed credentials
    # everything else here uses. A client built from the ambient identity would
    # answer confidently about the wrong principal. GetCallerIdentity needs no
    # permission — it is answerable even to a session that is denied everything.
    try:
        arn = director.client(IDENTITY_BROKER).get_caller_identity()["Arn"]
        match = _ASSUMED_ROLE.search(arn)
        role = match.group(1) if match else arn
    except Exception as exc:  # noqa: BLE001
        role = None
        log.warning("ffug.probe could not resolve its own identity: %s", exc)

    log.info(
        "ffug.probe tenant_id=%s isolated=%s outcome=%s",
        tenant_id,
        all(a["pass"] for a in attempts),
        # One token per attempt, in order, so a regression is visible in the log
        # stream without opening the response body. A '!' is a probe that did
        # not do what the boundary says it must.
        " ".join(
            f"{'ok' if a['pass'] else '!'}:{a['expect']}" for a in attempts
        ),
    )

    return {
        "ok": True,
        "operation": "isolation_probe",
        "table": TABLE_NAME,
        "environment": environment,
        "tenant_id": tenant_id,
        "probe_tenant": probe_tenant or None,
        "probe_environment": probe_environment or None,
        "role": role,
        "attempts": attempts,
        # Every attempt, not the readable one. A successful read of your own
        # partition proves the credentials work and says nothing about what is
        # kept out, which is the entire property under test.
        "isolated": all(attempt["pass"] for attempt in attempts),
    }


def _op_hash_async(args: dict[str, Any], director: FfugDirector) -> dict[str, Any]:
    """Accept the work, persist who it is for, and answer immediately.

    The crossing ends here. What is queued is a `PersistedContext` and a body —
    **never the envelope**. A queued message is persisted state inside this
    service, not something in transport, and re-verifying a token minted for a
    crossing that already finished would be verifying the wrong thing. Holding
    one open long enough to still verify would mean moving H2's 300-second
    ceiling for no gain.

    The projection is read here as well as in the worker, deliberately. It costs
    one GetItem and it turns "this tenant has no salt" into a refusal at the
    door, with the caller still on the line, instead of a message that queues
    successfully and dies out of sight.

    The callback carries an OPERATION and the caller's OWN ADDRESS (PORTH-624,
    2026-08-27). ffug holds no callback addresses and Porth's registry holds
    none either: the party receiving an answer is the one that knows where it
    listens, so it says so when it asks.

    ffug still cannot be turned into a way to reach an arbitrary target. What
    it is pointed at only receives a token minted for the VERIFIED
    `source_service` of this crossing, so an answer delivered anywhere other
    than that service's ingress is refused on `aud` before its payload is read.
    Misdirection fails at the receiver, which is what lets this path stay free
    of a per-call validation.
    """
    payload = args.get("document")
    if payload is None:
        raise FfugError(
            "missing_payload",
            "hash_async requires a document to hash, under `document`",
        )

    callback = args.get("callback") or {}
    operation = str(callback.get("operation") or "").strip()
    endpoint = callback.get("endpoint") or None
    if not operation or not endpoint:
        raise FfugError(
            "missing_callback",
            "hash_async requires callback.operation and callback.endpoint — "
            "asynchronous work with nothing to report to is work nobody learns "
            "the result of. The endpoint is the CALLER's own address: ffug does "
            "not hold one and there is no registry entry to fall back on",
        )

    if not WORK_QUEUE_URL:
        raise FfugError(
            "queue_unavailable",
            "FFUG_WORK_QUEUE_URL is not set — refusing to accept work that "
            "cannot be queued rather than acknowledging and dropping it",
        )

    _active_projection(director)

    record = PersistedContext.from_director(director)
    body = json.dumps(
        {
            "context": record.to_json(),
            "payload": payload,
            # Operation and the caller's own address. Stored as given —
            # ffug does not resolve it, does not check it against a registered
            # one, and gains nothing by doing either: the completion is minted
            # for the VERIFIED source_service, so an answer sent anywhere else
            # is refused on `aud` at whatever ingress receives it (PORTH-624).
            "callback": {"operation": operation, "endpoint": endpoint},
        },
        separators=(",", ":"),
    )
    _queue().send_message(QueueUrl=WORK_QUEUE_URL, MessageBody=body)

    log.info(
        "ffug.queued operation=hash_async tenant_id=%s answering=%s callback_op=%s "
        "trace_id=%s",
        director.tenant_id, director.source_service or "-", operation,
        director.async_trace_id,
    )
    return {
        "ok": True,
        "operation": "hash_async",
        "status": "queued",
        "trace_id": director.async_trace_id,
    }


_OPS = {
    "echo": _op_echo,
    "get": _op_get,
    "hash": _op_hash,
    "hash_async": _op_hash_async,
    "isolation_probe": _op_isolation_probe,
}


def _build_director(event: dict[str, Any], context: Any) -> FfugDirector:
    """Construct the Director, translating its refusals into typed rejections.

    Every branch here is a REFUSAL, returned as data so UAT-4 can assert on the
    rejection class rather than parse a stack trace. Note what is deliberately
    absent: a branch for narrowing failure. That is a deployment fault, not a
    caller fault, so it propagates and the invocation errors — an operator
    should see it, and a caller should not be told anything useful about it.

    ``reason_code`` comes off the library's own exceptions, so ffug's codes and
    Porth's audit-log codes are the same vocabulary. The Director has already
    written the H4 rejection line by the time we get here; this only shapes the
    reply.
    """
    try:
        return FfugDirector(event, context)
    except EnvelopeError as exc:
        raise FfugError(getattr(exc, "reason_code", "envelope_error"), str(exc)) from exc
    except (UnknownServiceError, ServiceNotActiveError) as exc:
        # The signature verified; the service it names is not one this install
        # will accept calls from. A different fault from a bad signature, and
        # worth its own code — one is forgery, the other is configuration.
        raise FfugError("source_service_refused", str(exc)) from exc
    except ServicesConfigError as exc:
        raise FfugError("services_config_unreadable", str(exc)) from exc


def _debug_identity(director: FfugDirector) -> None:
    """At DEBUG only: who STS actually issued this request's session to.

    The single most useful line when asking "is the narrowing real?" — it is
    the assumed-role name, from the service that issued it, rather than
    anything this code believes about itself. Behind a level check because it
    costs a GetCallerIdentity per invocation, which a hot path should not pay
    to reassure a reader.
    """
    if not log.isEnabledFor(logging.DEBUG):
        return
    try:
        arn = director.client(IDENTITY_BROKER).get_caller_identity()["Arn"]
        match = _ASSUMED_ROLE.search(arn)
        log.debug("ffug.narrowed role=%s", match.group(1) if match else arn)
    except Exception as exc:  # noqa: BLE001 — a diagnostic must not fail a request
        log.debug("ffug.narrowed role=? (%s)", exc)


def handler(event: dict[str, Any], context: Any = None) -> dict[str, Any]:
    # PORTH-623 — who this deployable is and where it will read, once per
    # process, at INFO. The post-deploy check: a wrong PORTH_BRANCH shows up
    # here as a wrong path rather than three layers down as a refusal.
    log_plane_identity(FfugDirector.SERVICE_ID)
    event = event or {}
    try:
        # Before verification, so nothing here can be trusted and nothing here
        # is claimed. Only the SHAPE of what arrived: which operation was asked
        # for, and whether an envelope was present at all — which is the first
        # thing you want when a call is being refused as unauthenticated.
        log.debug(
            "ffug.received operation=%s context_present=%s",
            (event.get("operation") or "echo").strip(),
            "porth_context" in event,
        )

        director = _build_director(event, context)

        # After verification, so every field here is a signed claim rather than
        # something the caller asserted. The pairing with the line above is the
        # point: what was sent, then what survived being checked.
        log.debug(
            "ffug.verified environment=%s tenant_id=%s source_service=%s "
            "authenticated=%s internal=%s trace_id=%s",
            director.environment,
            director.tenant_id,
            director.source_service or "-",
            director.is_authenticated,
            getattr(director, "is_internal_call", "?"),
            director.trace_id or "-",
        )
        _debug_identity(director)

        if not director.is_authenticated:
            # No envelope at all, or one carrying no tenant. Refused rather than
            # served under a default — the fail-closed posture ffug has had
            # since Phase A, now applied to a boundary that can be forged.
            raise FfugError(
                "missing_context",
                "no verified tenant context on this invocation",
            )

        # `operation`, the D7.4 wire field. ServiceClient sends
        # {"operation", "payload", "porth_context"}, so a service that reads
        # `op` can be called by hand and not by the sanctioned client — which is
        # the wrong way round, since the client is the supported route and the
        # hand-rolled invoke is the one being designed out (PORTH-599).
        op = (event.get("operation") or "echo").strip()
        fn = _OPS.get(op)
        if fn is None:
            raise FfugError("unknown_op", f"unknown op {op!r}")

        # THE unwrap, and the only one. `ServiceClient` puts what a caller
        # passes under `payload` and adds `operation` and `porth_context`
        # alongside it, so an op reading a field off the raw event reads a level
        # that nothing populates.
        #
        # This was three separate defects before it was one rule (PORTH-622):
        # `hash_async` read `callback` off the top and refused every call, which
        # was loud; `isolation_probe` read `probe_tenant` off the top and
        # silently saw "" on every call since PORTH-598 — so the probe has been
        # aiming its refusal at no partition at all, which is the weak version
        # its own docstring warns against. `echo` and `get` had it latent,
        # working only because nothing reaches them through the client yet.
        #
        # Unwrapping HERE rather than in each op is what makes that
        # unrepeatable: there is no longer a per-op choice to get wrong.
        result = fn(event.get("payload") or {}, director)
        log.info(
            "ffug.served operation=%s environment=%s tenant_id=%s source_service=%s trace_id=%s",
            op,
            director.environment,
            director.tenant_id,
            director.source_service or "-",
            director.trace_id or "-",
        )
        return result
    except FfugError as exc:
        return exc.to_response()
