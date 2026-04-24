from __future__ import annotations
import logging
import os

import boto3
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from .auth_context import parse_auth_context
from .context import PorthContext

logger = logging.getLogger(__name__)


class PorthContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        event = getattr(request.state, "aws_event", None) or {}
        try:
            auth = parse_auth_context(event)
        except Exception:
            logger.exception("Failed to parse auth context")
            return JSONResponse({"detail": "Unauthorized"}, status_code=401)

        if not auth.get("tenant_id"):
            return JSONResponse({"detail": "Unauthorized"}, status_code=401)

        region = os.environ.get("AWS_REGION", "us-east-1")
        sts_key = auth.get("sts_access_key_id")
        if sts_key:
            dynamodb = boto3.resource(
                "dynamodb",
                aws_access_key_id=sts_key,
                aws_secret_access_key=auth["sts_secret_access_key"],
                aws_session_token=auth["sts_session_token"],
                region_name=region,
            )
        else:
            dynamodb = boto3.resource("dynamodb", region_name=region)

        request.state.porth = PorthContext(
            tenant_id=auth["tenant_id"],
            user_id=auth.get("user_id", ""),
            organization_id=auth.get("organization_id", ""),
            external_id=auth.get("external_id", ""),
            roles=auth["roles"],
            permissions=auth["permissions"],
            _dynamodb=dynamodb,
        )
        return await call_next(request)
