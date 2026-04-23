from __future__ import annotations
from fastapi import Request, HTTPException


def require_permission(permission_key: str):
    def dependency(request: Request) -> None:
        porth = getattr(request.state, "porth", None)
        if porth is None or not porth.has_permission(permission_key):
            raise HTTPException(status_code=403, detail=f"Missing permission: {permission_key}")
    return dependency
