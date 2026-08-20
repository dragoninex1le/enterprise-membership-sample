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
        """This app's table, reached through the request's own credentials.

        ``self.resource(...)`` is the seam: the connection is cached and scoped
        to this tenant's credentials, so a handler cannot reach another tenant's
        partition even by asking. The old middleware built this from raw STS keys
        per request, which worked and cached nothing and renewed nothing.

        The argument is a CAPABILITY, not an AWS service name — DOCUMENT_STORE,
        which on AWS maps to DynamoDB and elsewhere would be Firestore or Cosmos
        DB. Passing ``"dynamodb"`` raised UnknownCapabilityError at runtime and
        the app 500'd on every page (PORTH-615). The constant is imported rather
        than spelled, so the same mistake is an ImportError next time.
        """
        if getattr(self, "_repository", None) is None:
            self._repository = SampleAppRepository(self.resource(DOCUMENT_STORE))
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
