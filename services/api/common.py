"""Helpers shared by the API route modules: service access, job lookup, query parsing, file responses, URLs."""

from __future__ import annotations

import math
import os
import re
from collections.abc import Callable
from typing import Any

from fastapi import Request
from fastapi.responses import FileResponse

from services.api import deps
from services.api.errors import ApiError
from services.common import blobs
from services.geom_worker.program import ProgramError, UnknownParamError
from services.registry import parts as P

API = "/api/v1"
IMMUTABLE = "public, max-age=31536000, immutable"
MEDIA_TYPES = {
    "stl": "model/stl",
    "step": "model/step",
    "3mf": "model/3mf",
    "glb": "model/gltf-binary",
    "view": "application/json",
    "py": "text/x-python; charset=utf-8",
}
EXTENSIONS = {"stl": ".stl", "step": ".step", "3mf": ".3mf", "glb": ".glb", "view": ".view.json", "py": ".py"}
RESERVED_QUERY = {"format", "formats", "download", "preset", "ack", "passport"}


def _svc() -> Any:
    return deps.service()


def _job(job_id: str) -> Any:
    job = _svc().manager().get(job_id)
    if job is None:
        ids = [s.id for s in _svc().manager().list(200, include_replays=True)]
        import difflib

        raise ApiError(404, "job_not_found", f"no job {job_id!r}", difflib.get_close_matches(job_id, ids, n=3))
    return job


_HINTS = {
    "no_model_outline": "fit-outline and fit-check need a finished fix job with a model outline "
    "(Steer lanes and failed runs have none)",
    "no_program": "the job has no part program yet (it is still running, failed early or was refused)",
    "no_preview_source": "the preview needs a verified outline and a rectified photo from a fix job",
}


def _service_call(fn: Callable[..., Any], *args: Any, conflict: str, **kw: Any) -> Any:
    """Call the agent service; its KeyError (missing state) → 409 `conflict`, ValueError → 422. Errors that already
    map to the envelope (unknown part/param, bad PARAMS) pass through."""
    try:
        return fn(*args, **kw)
    except (P.PartNotFound, UnknownParamError, ProgramError, ApiError):
        raise
    except KeyError as exc:
        msg = str(exc.args[0]) if exc.args else conflict
        hint = _HINTS.get(conflict)
        raise ApiError(409, conflict, f"{msg}; {hint}" if hint else msg) from exc
    except ValueError as exc:
        raise ApiError(422, "invalid_request", str(exc)) from exc


def _float(name: str, raw: str) -> float:
    try:
        v = float(raw)
    except ValueError:
        raise ApiError(422, "bad_param", f"{name}={raw!r} is not a number") from None
    if not math.isfinite(v):
        raise ApiError(422, "bad_param", f"{name} must be finite")
    return v


def _query_params(request: Request) -> dict[str, float]:
    return {k: _float(k, v) for k, v in request.query_params.multi_items() if k not in RESERVED_QUERY}


def _formats(request: Request) -> list[str]:
    raw = request.query_params.getlist("format") + request.query_params.getlist("formats")
    try:
        return P.parse_formats(raw or None)
    except ValueError as exc:
        raise ApiError(422, "bad_format", str(exc), list(P.ALL_FORMATS)) from exc


def _file(path: Any, fmt: str, filename: str, *, cache: str = IMMUTABLE) -> FileResponse:
    return FileResponse(
        path,
        media_type=MEDIA_TYPES.get(fmt, "application/octet-stream"),
        filename=filename,
        headers={"Cache-Control": cache},
    )


def _resolve_artifact(url: str) -> Any:
    """Local file behind an artifact URL (bake route or blob)."""
    if url.startswith(f"{API}/bakes/"):
        key, _, name = url[len(f"{API}/bakes/") :].partition("/")
        return P.bake_file(key, name)
    if url.startswith(f"{API}/blobs/"):
        try:
            p = blobs.locate(url[len(f"{API}/blobs/") :])
        except ValueError:
            return None
        return p if p.exists() else None
    return None


def _mat_or_404(mat_id: str) -> None:
    from services.metrology.mats import all_mats

    ids = [m.mat_id for m in all_mats()]
    if mat_id not in ids:
        import difflib

        raise ApiError(404, "mat_not_found", f"no mat {mat_id!r}", difflib.get_close_matches(mat_id, ids, n=3) or ids)


_HOST_RE = re.compile(r"^[A-Za-z0-9.\-]+(:\d{1,5})?$|^\[[0-9a-fA-F:]+\](:\d{1,5})?$")


def public_base(request: Request) -> str:
    """Absolute base for links: X-Forwarded-Host/-Proto (the web app proxies), else PARTSMITH_PUBLIC_URL, else this
    request's own origin. Header values are validated so they cannot inject text into the documents."""
    host = request.headers.get("x-forwarded-host", "").split(",")[0].strip()
    proto = request.headers.get("x-forwarded-proto", "").split(",")[0].strip().lower()
    if host and _HOST_RE.match(host):
        scheme = proto if proto in ("http", "https") else request.url.scheme
        return f"{scheme}://{host}"
    env = os.environ.get("PARTSMITH_PUBLIC_URL", "").strip()
    if env:
        return env.rstrip("/")
    return str(request.base_url).rstrip("/")
