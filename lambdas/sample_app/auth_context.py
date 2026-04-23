from __future__ import annotations


def parse_auth_context(event: dict) -> dict:
    """Extract Porth auth context from API Gateway Lambda authorizer output."""
    ctx = (
        event.get("requestContext", {})
        .get("authorizer", {})
        .get("lambda", {})
    )
    return {
        "tenant_id": ctx.get("tenant_id"),
        "user_id": ctx.get("user_id"),
        "organization_id": ctx.get("organization_id"),
        "external_id": ctx.get("external_id"),
        "roles": [r for r in ctx.get("roles", "").split(",") if r],
        "permissions": {p for p in ctx.get("permissions", "").split(",") if p},
        "sts_access_key_id": ctx.get("sts_access_key_id"),
        "sts_secret_access_key": ctx.get("sts_secret_access_key"),
        "sts_session_token": ctx.get("sts_session_token"),
    }
