"""Admin token for writes that change what others see: publishing, Steer, lesson promotion, request status, batches.

`PARTSMITH_ADMIN_TOKEN` set → those routes need `Authorization: Bearer <token>` (401 `admin_required` otherwise).
Not set → development mode: they are open and `/status` says `admin: "open (dev)"`. Public reads stay anonymous.
"""

from __future__ import annotations

import hmac
import os

from fastapi import Request

from services.api.errors import ApiError


def token() -> str | None:
    t = os.environ.get("PARTSMITH_ADMIN_TOKEN", "").strip()
    return t or None


def mode() -> str:
    return "token" if token() else "open (dev)"


def is_admin(request: Request) -> bool:
    expected = token()
    if expected is None:
        return True
    header = request.headers.get("authorization", "")
    scheme, _, given = header.partition(" ")
    return scheme.lower() == "bearer" and hmac.compare_digest(given.strip().encode(), expected.encode())


def require_admin(request: Request) -> None:
    """FastAPI dependency."""
    if not is_admin(request):
        raise ApiError(401, "admin_required", "this action needs the admin token (Authorization: Bearer …)")
