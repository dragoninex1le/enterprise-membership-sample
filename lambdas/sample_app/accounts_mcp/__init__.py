"""The accounts MCP service — EMS's books, for an AI assistant acting as a signed-in user.

An assistant connected to ``https://{tenant}.api.{slot}.{zone}/mcp`` can read the
tenant's position, chase overdue receivables, raise and send invoices, record bills
and work the approval queue — each only as far as the signed-in user's EMS role allows.

How the pieces fit:

* **Who.** The user signs in through Porth's MCP door on the tenant's API host
  (OAuth, discovered from the 401 this surface answers without a token). Porth's
  bearer authorizer resolves the token to the user, tenant, roles and permissions,
  and ``DirectorMiddleware`` turns that into the request's Director.
* **What.** Each tool states the ``sample-app`` permission it needs and checks it
  against the Director before doing anything. A refusal is an MCP tool error naming
  the permission — the expected answer for a clerk asking to approve.
* **How.** A tool does its work by calling the same route function the web app uses,
  so the rules (draft before submit, decided records stay decided) live in one place.

``tools`` holds the server and its tools; ``http`` is the ``/mcp`` route.
"""
