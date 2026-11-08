"""``/mcp`` on the sample app.

Reached through the app's bearer API (template.yml ``SampleAppBearerApi``), mapped
under ``mcp`` on the tenant API hosts: API Gateway routes on the path without the
key, but the event still carries it, so this route sees ``/mcp``.

The SDK's streamable-HTTP transport normally runs inside a long-lived task group
started by the application's lifespan. Lambda (Mangum, lifespan off) has no such
thing, and the server is stateless with JSON responses, so a transport is started
for each request, handed the request, and stopped. The response is collected and
returned as an ordinary one.
"""

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import Response
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager

from sample_app.accounts_mcp.tools import build_server

router = APIRouter(tags=["MCP"])
SERVER = build_server()


async def _one_request(request: Request) -> Response:
    transport = StreamableHTTPSessionManager(app=SERVER._mcp_server, json_response=True, stateless=True)  # noqa: SLF001
    status = 500
    headers: list[tuple[bytes, bytes]] = []
    chunks: list[bytes] = []

    async def collect(message: dict[str, Any]) -> None:
        nonlocal status, headers
        if message["type"] == "http.response.start":
            status = int(message["status"])
            headers = list(message.get("headers") or [])
        elif message["type"] == "http.response.body":
            chunks.append(message.get("body", b""))

    async with transport.run():
        await transport.handle_request(request.scope, request.receive, collect)

    kept = {k.decode(): v.decode() for k, v in headers if k.lower() != b"content-length"}
    return Response(content=b"".join(chunks), status_code=status, headers=kept)


@router.api_route("/mcp", methods=["GET", "POST", "DELETE"], include_in_schema=False)
async def mcp(request: Request) -> Response:
    return await _one_request(request)
