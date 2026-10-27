"""The API error envelope: `{"error": {"code", "message", "closest_matches"?}}` for every 4xx/5xx."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from services.geom_worker.bake import BakeError
from services.geom_worker.program import ProgramError, UnknownParamError
from services.registry.parts import PartNotFound

log = logging.getLogger("partsmith.api")


class ApiError(Exception):
    """Raise anywhere in a route to answer with the error envelope."""

    def __init__(self, status: int, code: str, message: str, closest: list[str] | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.closest = closest


def envelope(code: str, message: str, closest: list[str] | None = None) -> dict[str, Any]:
    err: dict[str, Any] = {"code": code, "message": message}
    if closest is not None:
        err["closest_matches"] = closest
    return {"error": err}


def _resp(status: int, code: str, message: str, closest: list[str] | None = None) -> JSONResponse:
    return JSONResponse(envelope(code, message, closest), status_code=status)


_HTTP_CODES = {
    400: "bad_request",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    413: "too_large",
    415: "unsupported_media_type",
    429: "rate_limited",
}


def install(app: FastAPI) -> None:
    """Register the envelope handlers on `app`."""

    @app.exception_handler(ApiError)
    async def _api(_: Request, exc: ApiError) -> JSONResponse:
        return _resp(exc.status, exc.code, exc.message, exc.closest)

    @app.exception_handler(PartNotFound)
    async def _part(_: Request, exc: PartNotFound) -> JSONResponse:
        return _resp(404, "part_not_found", f"no part {exc.slug!r}", exc.closest)

    @app.exception_handler(UnknownParamError)
    async def _param(_: Request, exc: UnknownParamError) -> JSONResponse:
        closest = sorted({c for names in exc.closest.values() for c in names})
        return _resp(422, "unknown_param", str(exc), closest)

    @app.exception_handler(ProgramError)
    async def _program(_: Request, exc: ProgramError) -> JSONResponse:
        return _resp(422, "bad_param", exc.message)

    @app.exception_handler(BakeError)
    async def _bake(_: Request, exc: BakeError) -> JSONResponse:
        return _resp(422, "bake_failed", f"the part program failed to build: {exc}")

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = _HTTP_CODES.get(exc.status_code, f"http_{exc.status_code}")
        resp = _resp(exc.status_code, code, str(exc.detail))
        for k, v in (exc.headers or {}).items():
            resp.headers[k] = v
        return resp

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        errs = exc.errors()
        first = errs[0] if errs else {}
        where = ".".join(str(x) for x in first.get("loc", ()) if x != "body")
        msg = f"{where}: {first.get('msg', 'invalid request')}" if where else str(first.get("msg", "invalid request"))
        return _resp(422, "validation_error", msg)

    @app.exception_handler(Exception)
    async def _crash(_: Request, exc: Exception) -> JSONResponse:
        log.exception("unhandled error")  # message only; requests and env never logged
        return _resp(500, "internal_error", f"internal error ({type(exc).__name__})")
