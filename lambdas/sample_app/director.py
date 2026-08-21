"""The sample app's Director — its half of the Porth contract (PORTH-613).

Porth's authorizer resolves the caller and serialises identity, roles,
permissions and a set of tenant-narrowed credentials into the request's
authorizer context. The Director is the shared spine that reads it. Two services
already inherit it — the Porth API and the Elegans backend — and this is the
third.

Before this, the app parsed that context itself: its own ``parse_auth_context``,
its own ``PorthContext`` dataclass, its own middleware building its own boto3
resource from the raw STS keys. It worked, and it was a second implementation of
something the library owns. Everything Porth learned about that parse —
env-scoping, credential renewal at the end of a request, the DENIED-because-never
-seeded diagnostic — landed in the library and not here.

What binding to the Director actually buys, beyond deleting code:

* **permission denials say which of two things went wrong.** A 403 cannot
  distinguish "this caller lacks the grant" from "the permission was never
  seeded and NOBODY holds it". :meth:`Director.can_perform` logs the difference,
  and this app has now been on both sides of it in one evening.
* **credentials are the library's problem.** The old middleware read
  ``sts_access_key_id`` and friends out of the context and built a resource per
  request. The Director hands back a cached, tenant-scoped connection and
  settles renewal after the response — the PORTH-565 checkpoint the app had no
  equivalent of.
* **the tenant is never passed by hand.** ``director.tenant_id`` comes from the
  authorizer's own resolution, so a handler cannot accidentally read one
  tenant's rows while claiming another's.
"""
from __future__ import annotations

import os

from porth_common.director import Director as PorthDirector
from porth_common.director import DirectorMiddleware as _BaseDirectorMiddleware
from porth_common.protocols.cloud_clients import DOCUMENT_STORE

from .repository import SampleAppRepository

#: This app's own table. Named from the same environment variable the repository
#: has always used, so the two cannot disagree about which table is "ours".
TABLE_NAME = f"porth-sample-app-{os.environ.get('PORTH_ENVIRONMENT', 'dev')}"


class SampleAppDirector(PorthDirector):
    """The shared Director, plus this app's own data access.

    Deliberately thin. Everything about identity, roles, permissions and
    credentials is inherited; the only thing this app adds is a repository bound
    to the request's narrowed connection.
    """

    @property
    def repository(self) -> SampleAppRepository:
        """This app's table, reached with the credentials this request arrived on.

        ``self.resource(...)`` does not mean "Porth's credentials". It means
        *whatever the authorizer minted for this request*, and PORTH-586 changed
        what that is.

        PORTH-616 was right about the mechanics and its premise has since gone.
        Before PORTH-586 every request resolved a catch-all binding in the
        session-policy index, so the credentials arriving here were
        ``porth-tenant-{env}`` — Porth's own role, scoped to Porth's tables, and
        correctly refusing this one:

            AccessDeniedException: assumed-role/porth-tenant-dev/porth-tenant is
            not authorized to perform: dynamodb:Query on table/porth-sample-app-dev

        Falling back to the ambient execution role was the right answer to that.
        The index now binds this app's host to this app's own role, so the same
        call returns ``porth-sample-app-tenant-{env}``: a role this app owns,
        granted this table and nothing of Porth's, and narrowed to one tenant by
        the ``porth-tenant`` / ``porth-env`` session tags Porth attaches to every
        assume. The call site did not change meaning; what arrives did.

        What that buys, and it is the whole point of PORTH-585: tenant isolation
        on this app's data becomes an IAM boundary rather than a convention. It
        was the key shape — every row written under ``pk = TENANT#{tenant_id}``
        — which is sound while every write goes through this repository and is
        worth nothing the first time one does not. PORTH-594 then put the
        environment into that key as well, so the pattern the session policy
        matches fences both axes rather than fencing the tenant in the key
        and the environment on a session tag.

        A query for another tenant's partition is now refused by DynamoDB
        before this code is consulted.

        The ambient identity is gone rather than merely unused: SampleAppFunction
        no longer holds DynamoDBCrudPolicy on this table, so there is nothing to
        fall back TO. That is deliberate, and it is what Porth did to its own API
        function in PORTH-550 — while a broad execution role exists underneath,
        narrowing is advisory, and any path that loses it succeeds quietly
        against every tenant.

        SampleAppEventConsumerFunction keeps its own grant. No authorizer runs
        for an EventBridge delivery, so there are no request credentials to use
        and its execution role is the only identity it can have.
        """
        if getattr(self, "_repository", None) is None:
            # PORTH-594 — the repository is built FOR this request's scope, and
            # both halves come from the authorizer's own resolution rather than
            # from the environment. `environment` here is the ADR-Z8 slot; the
            # PORTH_ENVIRONMENT that names the table is a different value.
            #
            # A missing scope raises in the repository's constructor rather than
            # producing ENV##TENANT#… — a key that writes fine, matches no
            # session policy, and is never read back.
            self._repository = SampleAppRepository(
                self.resource(DOCUMENT_STORE),
                environment=self.environment,
                tenant_id=self.tenant_id,
            )
        return self._repository


class DirectorMiddleware(_BaseDirectorMiddleware):
    """Bind the shared middleware to this app's Director subclass.

    A shell for the same reason the Porth API's is: ``app.add_middleware`` names
    a class, and which class this deployment attaches is a deployment fact. The
    parse, the attach and the credential-renewal checkpoint all live in
    :class:`porth_common.director.DirectorMiddleware`.
    """

    def __init__(self, app) -> None:
        super().__init__(app, director_cls=SampleAppDirector)


__all__ = ["TABLE_NAME", "DirectorMiddleware", "SampleAppDirector"]
