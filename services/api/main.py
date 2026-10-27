"""PartSmith REST + SSE API under `/api/v1` (contract: docs/API.md), plus `/llms.txt`, `/prompt.txt` and the MCP
server over streamable HTTP at `/mcp`.

    uv run uvicorn services.api.main:app --port 8000

Jobs go through the agent service facade only (`services/agent/service.py`); the registry through
`services/registry`. Blocking work (CAD bakes, model calls) runs in FastAPI's thread pool.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import threading
import time
from collections import defaultdict, deque
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from typing import Annotated, Any, Literal
from urllib.parse import urlencode

from fastapi import APIRouter, Body, Depends, FastAPI, File, Form, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, Response, StreamingResponse
from partsmith_schemas import ArtifactEvent, JobInput, Measurements, MetricEvent, Need, PartRecord
from partsmith_schemas.partspec import Family
from partsmith_schemas.registry import BakeResult, VariantResult
from partsmith_schemas.verification import ParamSpec, Verification
from pydantic import BaseModel, Field
from starlette.routing import Route
from starlette.types import Receive, Scope, Send

from services.agent import providers
from services.api import agentdocs, auth, usage
from services.api.auth import require_admin
from services.api.common import (
    API,
    EXTENSIONS,
    IMMUTABLE,
    _file,
    _formats,
    _job,
    _mat_or_404,
    _query_params,
    _resolve_artifact,
    _service_call,
    _svc,
    public_base,
)
from services.api.errors import ApiError, install
from services.api.round2 import apply_preset, embed_router
from services.api.round2 import router as round2_router
from services.api.uploads import check_audio, check_video, clean_image, parse_points
from services.common import blobs
from services.common.paths import REPO_ROOT
from services.geom_worker import bake as geom_bake
from services.registry import gate, steer
from services.registry import parts as P
from services.registry.publish import dedupe_published, publish_part
from services.registry.store import get_registry

VERSION = "0.1.0"
FOLLOW_MAX_S = 1800.0
FOLLOW_POLL_S = 0.5
HEARTBEAT_S = float(os.environ.get("PARTSMITH_SSE_HEARTBEAT_S", "15"))
BENCH_REPORT = REPO_ROOT / "eval" / "reports" / "latest" / "report.json"

log = logging.getLogger("partsmith.api")


# ------------------------------------------------------------------------------------------------- app plumbing


class RateLimiter:
    """Fixed-window per-IP limit on write requests (POST/PUT/PATCH/DELETE). PARTSMITH_RATE_LIMIT per minute."""

    def __init__(self, per_minute: int) -> None:
        self.per_minute = per_minute
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, key: str) -> tuple[bool, int]:
        now = time.monotonic()
        with self._lock:
            q = self._hits[key]
            while q and now - q[0] > 60.0:
                q.popleft()
            if len(q) >= self.per_minute:
                return False, int(60 - (now - q[0])) + 1
            q.append(now)
            return True, 0


class McpMount:
    """ASGI endpoint for `/mcp`. The MCP session manager is created in the app lifespan (it can run only once per
    instance), so this indirection lets every lifespan (tests start several) get a fresh one."""

    def __init__(self) -> None:
        self.inner: Any = None

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if self.inner is None:
            resp = JSONResponse(
                {"error": {"code": "mcp_unavailable", "message": "MCP starts with the app lifespan"}}, status_code=503
            )
            await resp(scope, receive, send)
            return
        await self.inner(scope, receive, send)


mcp_mount = McpMount()


def _mcp_security() -> Any:
    from mcp.server.transport_security import TransportSecuritySettings

    hosts = os.environ.get("PARTSMITH_MCP_ALLOWED_HOSTS", "")
    if hosts == "*":
        return TransportSecuritySettings(enable_dns_rebinding_protection=False)
    extra = [h.strip() for h in hosts.split(",") if h.strip()]
    return TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=["127.0.0.1:*", "localhost:*", "[::1]:*", "testserver", *extra],
        allowed_origins=[
            "http://127.0.0.1:*",
            "http://localhost:*",
            "http://[::1]:*",
            *[f"https://{h}" for h in extra],
        ],
    )


def _warm_cad_pool() -> None:
    try:
        from services.geom_worker.sandbox import default_pool

        default_pool().warm()
    except Exception:  # warm-up is an optimisation only
        log.warning("CAD worker warm-up failed; workers start on first use")


@contextlib.asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    if os.environ.get("PARTSMITH_WARM_CAD", "1") == "1":
        threading.Thread(target=_warm_cad_pool, name="cad-warm", daemon=True).start()  # never blocks startup
    from services.mcp.server import build_server

    server = build_server(allow_paths=False)
    inner = server.streamable_http_app(
        streamable_http_path="/mcp", stateless_http=True, json_response=True, transport_security=_mcp_security()
    )
    async with server.session_manager.run():
        mcp_mount.inner = inner
        try:
            yield
        finally:
            mcp_mount.inner = None


app = FastAPI(
    title="PartSmith API",
    version=VERSION,
    summary="Photos of a broken part → measured millimetres → a verified parametric CadQuery part, and an open "
    "registry of parts that are programs.",
    description="All lengths are millimetres. Errors use one envelope: "
    '`{"error": {"code", "message", "closest_matches"?}}`. Anonymous read is allowed; writes are rate limited per IP.',
    openapi_url=f"{API}/openapi.json",
    docs_url=f"{API}/docs",
    redoc_url=None,
    lifespan=lifespan,
)
install(app)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        o.strip()
        for o in os.environ.get("PARTSMITH_CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000").split(",")
        if o.strip()
    ],
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition", "Retry-After"],
)
limiter = RateLimiter(int(os.environ.get("PARTSMITH_RATE_LIMIT", "120")))


@app.middleware("http")
async def rate_limit(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
    if request.method in ("POST", "PUT", "PATCH", "DELETE") and request.url.path.startswith(API):
        ip = request.client.host if request.client else "unknown"
        ok, retry = limiter.allow(ip)
        if not ok:
            return JSONResponse(
                {"error": {"code": "rate_limited", "message": f"too many writes; retry in {retry} s"}},
                status_code=429,
                headers={"Retry-After": str(retry)},
            )
    response = await call_next(request)
    path = request.url.path
    if path.startswith((API, "/mcp", "/embed", "/llms.txt", "/prompt.txt")):
        route = getattr(request.scope.get("route"), "path", None) or ("/mcp" if path.startswith("/mcp") else path)
        try:
            usage.record(
                str(route), request.client.host if request.client else "", request.headers.get("user-agent", "")
            )
        except Exception:  # counting must never break a request
            log.warning("usage counter failed")
    return response


router = APIRouter(prefix=API)


# ------------------------------------------------------------------------------------------------- system


class Health(BaseModel):
    ok: bool
    version: str


@router.get("/health", summary="Liveness", tags=["system"])
def health() -> Health:
    return Health(ok=True, version=VERSION)


_call_cache: dict[str, list[dict[str, Any]]] = {}


def _model_calls(job: Any) -> list[dict[str, Any]]:
    """model_call events of a job (cached once the job is finished)."""
    if job.id in _call_cache:
        return _call_cache[job.id]
    calls = [e.model_dump() for e in job.events if e.t == "model_call"]
    if job.finished:
        _call_cache[job.id] = calls
    return calls


@router.get("/status", summary="Which model runs where, provider health, job and cost aggregates", tags=["system"])
def status() -> dict[str, Any]:
    """Live proof for the provider table: per-stage provider/model/mode, warnings (missing keys → mock), and
    aggregates computed from the `model_call` events of every job on this server."""
    from services.agent.providers.routing import ENDPOINTS

    rows = providers.status()
    jobs_total = jobs_verified = 0
    costs: list[float] = []
    agg: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    last_live: dict[str, float] = {}
    try:
        summaries = _svc().manager().list(100_000)
        mgr = _svc().manager()
    except ApiError:
        summaries, mgr = [], None
    for s in summaries:
        if s.is_replay:
            continue
        jobs_total += 1
        jobs_verified += int(s.verified)
        costs.append(float(s.cost_usd))
        job = mgr.get(s.id) if mgr is not None else None
        for c in _model_calls(job) if job is not None else []:
            key = (c["stage"], c["provider"], c["model"], c["mode"])
            a = agg.setdefault(
                key,
                {
                    "stage": c["stage"],
                    "provider": c["provider"],
                    "model": c["model"],
                    "mode": c["mode"],
                    "calls": 0,
                    "failed": 0,
                    "tokens_in": 0,
                    "tokens_out": 0,
                    "usd": 0.0,
                    "ms_total": 0,
                },
            )
            a["calls"] += 1
            a["failed"] += int(not c.get("ok", True))
            a["tokens_in"] += c.get("tokens_in", 0)
            a["tokens_out"] += c.get("tokens_out", 0)
            a["usd"] = round(a["usd"] + c.get("usd", 0.0), 6)
            a["ms_total"] += c.get("ms", 0)
            if c["mode"] == "live":
                last_live[c["provider"]] = max(last_live.get(c["provider"], 0.0), c.get("ts", 0.0))
    calls = sorted(agg.values(), key=lambda a: (a["stage"], -a["calls"]))
    for a in calls:
        a["ms_mean"] = round(a.pop("ms_total") / a["calls"]) if a["calls"] else None
        ep = ENDPOINTS.get(a["provider"])
        a["open_weights"] = bool(ep and ep.open_weights)
    live_open = sorted({r["stage"] for r in rows if r["open_weights"] and r["mode"] == "live"})
    return {
        "mode": providers.overall_mode(),
        "admin": auth.mode(),
        "providers": rows,
        "warnings": providers.warnings(),
        "jobs": {"total": jobs_total, "verified": jobs_verified},
        "cost": {
            "usd_total": round(sum(costs), 6),
            "usd_per_job_mean": round(sum(costs) / len(costs), 6) if costs else None,
            "n_jobs": len(costs),
        },
        "model_calls": calls,
        "open_weights": {
            "open_weights_only": os.environ.get("OPEN_WEIGHTS_ONLY", "0") == "1",
            "stages_live_on_open_weights": live_open,
            "calls_on_open_weights": sum(a["calls"] for a in calls if a["open_weights"] and a["mode"] == "live"),
            "last_live_call_ts": last_live,
        },
    }


# ------------------------------------------------------------------------------------------------- mats, blobs, bakes


@router.get("/mats", summary="All calibration mats (marker layouts at 1:1)", tags=["mats"])
def mats() -> list[dict[str, Any]]:
    from services.metrology.mats import all_mats, layout_json

    return [layout_json(m.mat_id) for m in all_mats()]


@router.get("/mats/{mat_id}", summary="One mat layout", tags=["mats"])
def mat(mat_id: str) -> dict[str, Any]:
    from services.metrology.mats import layout_json

    _mat_or_404(mat_id)
    return layout_json(mat_id)


@router.get(
    "/mats/{mat_id}/pdf",
    summary="Plain-paper mat PDF (A4, print at 100 %)",
    tags=["mats"],
    response_class=Response,
    responses={200: {"content": {"application/pdf": {}}}},
)
def mat_pdf(mat_id: str) -> Response:
    from tools.mat.make_mat import mat_pdf as render

    _mat_or_404(mat_id)
    try:
        pdf = render(mat_id)
    except ValueError as exc:
        raise ApiError(422, "not_printable", str(exc), ["paper-a4"]) from exc
    return Response(
        pdf,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'inline; filename="partsmith-mat-{mat_id}.pdf"',
            "Cache-Control": "public, max-age=3600",
        },
    )


@router.get(
    "/blobs/{key}",
    summary="Content-addressed blob (images, overlays, code)",
    tags=["files"],
    response_class=FileResponse,
)
def blob(key: str, request: Request) -> Response:
    try:
        path = blobs.locate(key)
    except ValueError as exc:
        raise ApiError(400, "bad_key", "blob keys are sha256 hex plus an optional extension") from exc
    if not path.exists():
        raise ApiError(404, "blob_not_found", f"no blob {key!r}")
    etag = f'"{key.split(".")[0]}"'
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers={"ETag": etag, "Cache-Control": IMMUTABLE})
    return FileResponse(path, media_type=blobs.content_type(key), headers={"Cache-Control": IMMUTABLE, "ETag": etag})


@router.get(
    "/bakes/{cache_key}/{name}",
    summary="A baked file (content-addressed by the bake cache key)",
    tags=["files"],
    response_class=FileResponse,
)
def baked_file(cache_key: str, name: str) -> FileResponse:
    path = P.bake_file(cache_key, name)
    if path is None:
        raise ApiError(
            404,
            "bake_not_found",
            f"no baked file {name!r} for {cache_key[:12]}…",
            sorted(geom_bake.FILE_NAMES.values()),
        )
    fmt = next((f for f, n in geom_bake.FILE_NAMES.items() if n == name), "")
    return _file(path, fmt, name)


# ------------------------------------------------------------------------------------------------- jobs


@router.post("/jobs/fix", summary="Start a fix job from photos on a mat", tags=["jobs"])
def jobs_fix(
    top: Annotated[UploadFile, File(description="Top view on the mat (JPEG/PNG/WebP, ≤ 25 MB)")],
    side: Annotated[UploadFile | None, File(description="Optional side view against the mat")] = None,
    mating: Annotated[UploadFile | None, File(description="Optional photo of where the part fits")] = None,
    intent: Annotated[str, Form(max_length=500)] = "",
    mat_kind: Annotated[Literal["screen", "paper"], Form()] = "screen",
    thickness_mm: Annotated[float | None, Form(gt=0, lt=500)] = None,
    family_hint: Annotated[Family | None, Form()] = None,
    screen_px_per_mm: Annotated[float | None, Form(gt=0, lt=100)] = None,
    orbit: Annotated[
        UploadFile | None, File(description="Optional 5–10 s walk-around clip (MP4/MOV/WebM, ≤ 60 MB)")
    ] = None,
    points: Annotated[
        str | None,
        Form(description='Feature taps in top-photo pixels: {"top": [{"x", "y", "kind"?, "id"?}]}', max_length=8000),
    ] = None,
) -> dict[str, Any]:
    """Photos are validated (decode, size, type) and GPS metadata is removed before anything is stored."""
    photos: dict[str, bytes] = {}
    for view, up in (("top", top), ("side", side), ("mating", mating)):
        if up is not None:
            photos[view], _ = clean_image(up.file.read(), view)
    if orbit is not None:
        clip = orbit.file.read()
        check_video(clip, "orbit")
        photos["orbit"] = clip
    taps = parse_points(points)
    job_input = JobInput(
        intent=intent,
        mat_kind=mat_kind,
        thickness_mm=thickness_mm,
        family_hint=family_hint,
        screen_px_per_mm=screen_px_per_mm,
    )
    extra = {"points": taps} if taps else {}
    job = _service_call(_svc().start_fix_job, photos, job_input, conflict="invalid_request", **extra)
    return dict(job.summary.model_dump(mode="json"))


class DemoRequest(BaseModel):
    sample: str = Field(description="Synthetic sample id from GET /jobs/demo/samples", examples=["clip-easy-001"])


@router.get("/jobs/demo/samples", summary="Bundled synthetic samples for demo jobs", tags=["jobs"])
def demo_samples() -> list[dict[str, Any]]:
    return list(_svc().list_demo_samples())


@router.post("/jobs/demo", summary="Run a bundled SYNTHETIC sample through the full pipeline", tags=["jobs"])
def jobs_demo(body: DemoRequest) -> dict[str, Any]:
    ids = [s["id"] for s in _svc().list_demo_samples()]
    if body.sample not in ids:
        import difflib

        raise ApiError(
            404,
            "sample_not_found",
            f"no sample {body.sample!r}",
            difflib.get_close_matches(body.sample, ids, n=3) or ids[:5],
        )
    job = _service_call(_svc().start_demo_job, body.sample, conflict="sample_not_found")
    return dict(job.summary.model_dump(mode="json"))


@router.get("/jobs", summary="Recent jobs", tags=["jobs"])
def jobs_list(
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
    include_replays: bool = False,
    kind: str | None = None,
) -> list[dict[str, Any]]:
    out = _svc().manager().list(limit if kind is None else 500, include_replays=include_replays)
    items = [s.model_dump(mode="json") for s in out if kind is None or s.kind == kind]
    return items[:limit]


@router.get(
    "/jobs/{job_id}", summary="Job detail (summary, events, spec, measurements, verification, code)", tags=["jobs"]
)
def job_detail(job_id: str) -> dict[str, Any]:
    try:
        return dict(_svc().job_detail(job_id))
    except KeyError:
        _job(job_id)
        raise


def _sse(ev: Any) -> str:
    return f"id: {ev.seq}\ndata: {ev.model_dump_json(exclude_none=True)}\n\n"


@router.get(
    "/jobs/{job_id}/events",
    summary="Server-sent events: past events first, then live, ends after done",
    tags=["jobs"],
    response_class=StreamingResponse,
    responses={200: {"content": {"text/event-stream": {}}}},
)
async def job_events(
    job_id: str,
    request: Request,
    from_seq: Annotated[int, Query(ge=0, description="Resume from this event seq")] = 0,
    follow: Annotated[bool, Query(description="Keep streaming after `done` (fit-check updates)")] = False,
) -> StreamingResponse:
    """One `data: <Event JSON>` per event, `id:` = seq, original `ts` kept (replays pace on ts gaps). A `: keep-alive`
    comment is sent when nothing happens for a while. `Last-Event-ID` resumes like `from_seq`. The stream ends after
    `done`, unless `follow=1`: then it stays open (up to 30 min) and delivers events added later, e.g. a phone's
    fit check, so a laptop page turns green without reloading."""
    job = await asyncio.to_thread(_job, job_id)
    start = from_seq
    last = request.headers.get("last-event-id")
    if last and last.isdigit():
        start = max(start, int(last) + 1)

    async def stream() -> AsyncIterator[str]:
        seq = start
        yield "retry: 3000\n\n"
        quiet_since = time.monotonic()
        deadline = time.monotonic() + FOLLOW_MAX_S
        while True:
            if await request.is_disconnected():
                return
            if follow and job.finished:  # events_since would not wait on a finished job: poll instead
                events = list(job.events[seq:])
                if not events:
                    await asyncio.sleep(FOLLOW_POLL_S)
            else:
                events = await asyncio.to_thread(job.events_since, seq, HEARTBEAT_S)
            if events:
                quiet_since = time.monotonic()
                for ev in events:
                    yield _sse(ev)
                    seq = ev.seq + 1
                    if ev.t == "done" and not follow:
                        return
                continue
            if job.finished and not follow:
                return
            if follow and time.monotonic() > deadline:
                return
            if not follow or time.monotonic() - quiet_since >= HEARTBEAT_S:
                quiet_since = time.monotonic()
                yield ": keep-alive\n\n"

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"},
    )


class AnswerRequest(BaseModel):
    id: str = Field(description="Question id from the question event", examples=["q1"])
    value: str | float = Field(examples=[12.5])
    via: Literal["text", "voice"] = "text"


@router.post("/jobs/{job_id}/answer", summary="Answer the job's pending question (resumes it)", tags=["jobs"])
def job_answer(job_id: str, body: AnswerRequest) -> dict[str, Any]:
    _job(job_id)
    try:
        out = _svc().answer(job_id, body.id, body.value, body.via)
    except KeyError as exc:
        raise ApiError(409, "no_pending_question", str(exc).strip("'\"")) from exc
    return out.model_dump(mode="json") if hasattr(out, "model_dump") else dict(out)


@router.post(
    "/jobs/{job_id}/edit",
    summary="Voice or text edit of the part's knobs (clamped to PARAMS)",
    tags=["jobs"],
    openapi_extra={
        "requestBody": {
            "content": {
                "application/json": {
                    "schema": {"type": "object", "properties": {"text": {"type": "string"}}},
                    "example": {"text": "hole 0.2 mm bigger"},
                },
                "multipart/form-data": {
                    "schema": {
                        "type": "object",
                        "properties": {"audio": {"type": "string", "format": "binary"}, "text": {"type": "string"}},
                    }
                },
            }
        }
    },
)
async def job_edit(job_id: str, request: Request) -> dict[str, Any]:
    await asyncio.to_thread(_job, job_id)
    ctype = request.headers.get("content-type", "")
    text: str | None = None
    audio: bytes | None = None
    mime = "audio/wav"
    if ctype.startswith("multipart/form-data"):
        form = await request.form()
        up = form.get("audio")
        if up is not None and not isinstance(up, str):
            audio = await up.read()
            mime = check_audio(audio, up.content_type)
        t = form.get("text")
        text = t if isinstance(t, str) and t.strip() else None
    else:
        try:
            body = await request.json()
        except json.JSONDecodeError as exc:
            raise ApiError(422, "validation_error", 'send JSON {"text": ...} or multipart audio') from exc
        text = str(body.get("text", "")) if isinstance(body, dict) else None
    if not text and audio is None:
        raise ApiError(422, "validation_error", 'send {"text": "..."} or a multipart `audio` file')
    out = await asyncio.to_thread(
        _service_call,
        _svc().edit,
        job_id,
        text=text[:500] if text else None,
        audio=audio,
        mime=mime,
        conflict="no_program",
    )
    return dict(out)


@router.post("/jobs/{job_id}/preview", summary="Muse Image 'see the fix' preview (labelled AI preview)", tags=["jobs"])
def job_preview(job_id: str) -> dict[str, Any]:
    _job(job_id)
    return dict(_service_call(_svc().preview, job_id, conflict="no_preview_source"))


@router.get(
    "/jobs/{job_id}/fit-outline", summary="1:1 outline + holes + dims of the model in the mat frame", tags=["jobs"]
)
def job_fit_outline(job_id: str, mat_id: Annotated[str, Query(examples=["screen-m"])] = "screen-m") -> dict[str, Any]:
    _job(job_id)
    _mat_or_404(mat_id)
    return dict(_service_call(_svc().fit_outline, job_id, mat_id, conflict="no_model_outline"))


@router.post(
    "/jobs/{job_id}/fit-check", summary="Screen fit check: photo of the real part on the outline", tags=["jobs"]
)
def job_fit_check(
    job_id: str, photo: Annotated[UploadFile, File()], mat_id: Annotated[str, Form()] = "screen-m"
) -> dict[str, Any]:
    _job(job_id)
    _mat_or_404(mat_id)
    data, _ = clean_image(photo.file.read(), "photo")
    out = _service_call(_svc().fit_check, job_id, data, mat_id, conflict="no_model_outline")
    res: dict[str, Any] = out.model_dump(mode="json") if hasattr(out, "model_dump") else dict(out)
    _emit_fit_check(_job(job_id), res, mat_id)
    return res


def _emit_fit_check(job: Any, res: dict[str, Any], mat_id: str) -> None:
    """Live update for pages following the job's SSE: metric events (fit_check_passed 1/0, IoU, Hausdorff) and the
    overlay as a `measure_overlay` artifact labelled "fit check …"."""
    it = int(job.summary.iterations)
    passed = bool(res.get("passed"))
    job.emit(MetricEvent(job=job.id, iter=it, name="fit_check_passed", value=1.0 if passed else 0.0, unit=""))
    if isinstance(res.get("iou"), (int, float)):
        job.emit(MetricEvent(job=job.id, iter=it, name="fit_check_iou", value=float(res["iou"]), unit=""))
    if isinstance(res.get("hausdorff_mm"), (int, float)):
        job.emit(MetricEvent(job=job.id, iter=it, name="fit_check_hausdorff_mm", value=float(res["hausdorff_mm"])))
    url = res.get("overlay_url")
    if isinstance(url, str) and url.startswith(f"{API}/blobs/"):
        key = url.rsplit("/", 1)[-1]
        job.emit(ArtifactEvent(job=job.id, kind="measure_overlay", sha=key.split(".")[0], url=url, iter=it,
                               label=f"fit check on {mat_id}: {'PASS' if passed else 'FAIL'}"))  # fmt: skip


@router.get(
    "/jobs/{job_id}/run.jsonl", summary="Raw run log (one event per line)", tags=["jobs"], response_class=FileResponse
)
def job_runlog(job_id: str) -> FileResponse:
    job = _job(job_id)
    path = job.dir / "run.jsonl"
    if not path.exists():
        raise ApiError(404, "no_run_log", f"job {job_id} has no run log yet")
    return FileResponse(
        path, media_type="application/x-ndjson", filename=f"{job_id}.run.jsonl", headers={"Cache-Control": "no-cache"}
    )


@router.get("/jobs/{job_id}/bake", summary="Re-bake the job's current part program (before publishing)", tags=["jobs"])
def job_bake(job_id: str, request: Request, download: bool = False, ack: bool = False) -> Any:
    """Query: `<param>=<value>` knobs plus `format=` (repeat or comma-separate). Same BakeResult as part bakes.
    `download=1` goes through the export gate: verified ships, best effort needs `ack=1`, failed is refused."""
    job = _job(job_id)
    params, fmts = _query_params(request), _formats(request)
    svc = _svc()
    if not hasattr(svc, "bake_job"):
        raise ApiError(501, "not_implemented", "this build's agent service has no bake_job")
    res = _service_call(svc.bake_job, job_id, params, fmts, conflict="no_program")
    data = res.model_dump(mode="json") if hasattr(res, "model_dump") else dict(res)
    if download:
        fmt = fmts[0]
        if fmt != "view":  # the viewer mesh is a preview, not a printable export
            gate.require(_job_decision(job), ack)
        path = _resolve_artifact(data["artifacts"].get(fmt, ""))
        if path is None:
            raise ApiError(404, "artifact_not_found", f"no {fmt} file for this bake", sorted(data["artifacts"]))
        return _file(path, fmt, f"{job_id}{EXTENSIONS[fmt]}")
    return data


class PublishRequest(BaseModel):
    slug: str | None = Field(None, pattern=r"^[a-z0-9][a-z0-9-]{1,79}$", description="Optional slug for the new part")
    ack: bool = Field(False, description="Acknowledge a best-effort part (required to publish one)")


def _job_decision(job: Any) -> gate.ShipDecision:
    data = job.read_json("verification.json")
    ver = Verification.model_validate(data) if data else None
    return gate.decide(verification=ver, job=job)


@router.post(
    "/jobs/{job_id}/publish", summary="Publish a finished job to the registry (origin preserved)", tags=["jobs"]
)
def job_publish(
    job_id: str,
    body: Annotated[PublishRequest | None, Body()] = None,
    ack: bool = False,
    _admin: None = Depends(require_admin),
) -> dict[str, Any]:
    """Admin. Export gate: verified publishes; best effort needs `ack` (body or `?ack=1`); failed is refused."""
    job = _job(job_id)
    if not job.finished or job.summary.status != "done":
        raise ApiError(
            409, "not_finished", f"job {job_id} is {job.summary.status}; only finished jobs can be published"
        )
    decision = _job_decision(job)
    gate.require(decision, ack or bool(body and body.ack))
    slug = body.slug if body else None
    if slug and get_registry().get_part(slug) is not None:
        raise ApiError(409, "slug_taken", f"slug {slug!r} is taken", P.closest_slugs(slug))
    part = _service_call(_svc().publish, job_id, slug=slug, conflict="no_program")
    # an identical part (same program + params) already published is reused instead of a second card
    outcome = dedupe_published(part.slug) if get_registry().get_part(part.slug) else publish_part(part)
    if outcome.part.slug != part.slug:
        job.summary.part_slug = outcome.part.slug
        job.save_summary()
    detail = P.part_detail(outcome.part)
    detail["publish"] = outcome.to_dict()
    detail["ship"] = decision.to_dict()
    return detail


CANCEL_WAIT_S = 3.0


@router.post("/jobs/{job_id}/cancel", summary="Cancel a running job", tags=["jobs"])
def job_cancel(job_id: str) -> dict[str, Any]:
    """Returns the summary after the cancel took effect (`cancelled`), or `status: "cancelling"` when the job has not
    stopped within a few seconds (it stops at its next check). Finished jobs are returned unchanged."""
    job = _job(job_id)
    if not job.finished:
        svc = _svc()
        if hasattr(svc, "cancel"):
            _service_call(svc.cancel, job_id, conflict="job_not_found")
        else:
            job.cancel()
        deadline = time.monotonic() + CANCEL_WAIT_S
        while not job.finished and time.monotonic() < deadline:
            time.sleep(0.05)
    out = dict(job.summary.model_dump(mode="json"))
    if not job.finished:
        out["status"] = "cancelling"
    return out


@router.post(
    "/transcribe", summary="Speech to text (Muse Voice Transcribe; labelled mock without a key)", tags=["jobs"]
)
def transcribe(
    audio: Annotated[UploadFile, File(description="wav/webm/ogg/mp3/m4a, ≤ 15 MB")],
    language_hint: Annotated[str | None, Form(examples=["hinglish"])] = None,
) -> dict[str, Any]:
    data = audio.file.read()
    mime = check_audio(data, audio.content_type)
    t = providers.transcribe(data, mime, language_hint)
    return {"text": t.text, "mode": t.mode, "language": t.language_hint, "model": t.model, "note": t.note}


@router.get("/replays", summary="Bundled, labelled replays of earlier runs", tags=["jobs"])
def replays() -> list[dict[str, Any]]:
    return list(_svc().replays())


# ------------------------------------------------------------------------------------------------- measure / verify


@router.post("/measure", summary="Stateless: photo on a mat → measurements in mm + overlay", tags=["measure"])
def measure(
    photo: Annotated[UploadFile, File()],
    view: Annotated[Literal["top", "side"], Form()] = "top",
    mat_kind: Annotated[Literal["screen", "paper"], Form()] = "screen",
    thickness_mm: Annotated[float | None, Form(gt=0, lt=500)] = None,
    mat_id: Annotated[str | None, Form()] = None,
) -> dict[str, Any]:
    if mat_id:
        _mat_or_404(mat_id)
    data, _ = clean_image(photo.file.read(), "photo")
    out = _service_call(_svc().measure, data, view, thickness_mm=thickness_mm, mat_id=mat_id, conflict="measure_failed")
    return out.model_dump(mode="json") if hasattr(out, "model_dump") else dict(out)


class VerifyRequest(BaseModel):
    part: str = Field(description="Registry slug")
    params: dict[str, float] = Field(default_factory=dict)
    measurements: Measurements | dict[str, Measurements] | None = Field(
        None, description="One view or {view: Measurements}"
    )
    job_id: str | None = Field(None, description="Use this job's measured photos instead of `measurements`")


@router.post("/verify", summary="Stateless: verify a registry part at params against measurements", tags=["measure"])
def verify_part(body: VerifyRequest) -> dict[str, Any]:
    """Deterministic: runs the part program in the sandbox and applies the pass rule. Code decides `verified`."""
    P.require_part(body.part)
    meas: dict[str, Any]
    if body.job_id:
        _job(body.job_id)
        meas = dict(_service_call(_svc().job_detail, body.job_id, conflict="job_not_found").get("measurements") or {})
        if not meas:
            raise ApiError(409, "no_measurements", f"job {body.job_id} has no measurements yet")
    elif body.measurements is None:
        raise ApiError(422, "validation_error", "send `measurements` or `job_id`")
    elif isinstance(body.measurements, dict):
        meas = dict(body.measurements)
    else:
        meas = {body.measurements.view.value: body.measurements}
    verification, functional = P.verify_part(body.part, body.params, meas)
    out: dict[str, Any] = verification.model_dump(mode="json")
    out["functional"] = functional
    return out


# ------------------------------------------------------------------------------------------------- registry

SortKey = Literal["relevance", "newest", "error", "title"]


@router.get("/parts", summary="Search the registry", tags=["registry"])
def parts_search(
    q: str = "",
    family: str | None = None,
    verified: bool | None = None,
    origin: str | None = None,
    sort: SortKey = "relevance",
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 24,
    role: Annotated[
        Literal["part", "reference", "all"], Query(description="reference = bench reference objects")
    ] = "part",
) -> dict[str, Any]:
    """`sort`: relevance (default) | newest | error (smallest max error first) | title. `cursor` is opaque.
    Reference objects (ID-1 card, LEGO brick …) are bench-only and hidden unless `role=reference` or `role=all`."""
    reg = get_registry()
    start = int(cursor) if cursor and cursor.isdigit() else 0
    items, total = reg.search(q, family=family, verified=verified, origin=origin, sort=sort, cursor=start, limit=limit,
                              role=None if role == "all" else role)  # fmt: skip
    thumbs = reg.thumbnails()
    nxt = start + len(items)
    return {
        "items": [P.part_card(p, reg, thumbs) for p in items],
        "next_cursor": str(nxt) if nxt < total else None,
        "total": total,
    }


@router.get("/parts/{slug}", summary="Part record + artifact URLs + lineage", tags=["registry"])
def part_get(slug: str) -> dict[str, Any]:
    return P.part_detail(P.require_part(slug))


@router.get("/parts/{slug}/params", summary="Typed knobs", tags=["registry"])
def part_params(slug: str) -> list[ParamSpec]:
    return list(P.require_part(slug).params)


@router.get(
    "/parts/{slug}/bake",
    summary="Bake at params (cached); `&download=1` returns the file",
    tags=["registry"],
    responses={200: {"model": BakeResult}},
)
def part_bake(slug: str, request: Request, download: bool = False, preset: str | None = None) -> Any:
    """Query: `<param>=<value>` for any knob plus `format=stl|3mf|step|glb|view|py` (repeat or comma-separate;
    default stl,step,view). Out-of-range values are clamped and listed in `clamped`; unknown knobs are a 422 with
    `closest_matches`. `preset=` applies a fit preset (GET /parts/{slug}/presets) after the knob values. Identical
    requests are content-addressed cache hits."""
    part = P.require_part(slug)
    params, fmts = _query_params(request), _formats(request)
    params, preset_info = apply_preset(part, params, preset)
    out = P.bake_output(part, params, fmts)
    if download:
        fmt = fmts[0]
        path = out.files.get(fmt)
        if path is None:
            raise ApiError(404, "artifact_not_found", f"no {fmt} file in this bake", sorted(out.files))
        return _file(path, fmt, f"{slug}{EXTENSIONS[fmt]}")
    res = out.to_bake_result(slug, lambda fmt, p: P.bake_url(out.cache_key, p.name)).model_dump(mode="json")
    res["facts_notes"] = out.facts_notes
    if preset_info is not None:
        res["preset"] = preset_info
    return res


@router.get(
    "/parts/{slug}/variant",
    summary="Plain words → params (code clamps, never rescales)",
    tags=["registry"],
    responses={200: {"model": VariantResult}},
)
def part_variant(
    slug: str, want: Annotated[str, Query(min_length=1, max_length=500, examples=["M4 hole, 2 mm taller"])]
) -> dict[str, Any]:
    res: dict[str, Any] = P.variant(slug, want).model_dump(mode="json")

    res["bake_url"] = f"{API}/parts/{slug}/bake?" + urlencode({**res["params"], "format": "stl,step,view"})
    return res


@router.get("/parts/{slug}/matching", summary="Parts that share an interface or family", tags=["registry"])
def part_matching(slug: str) -> list[dict[str, Any]]:
    reg = get_registry()
    thumbs = reg.thumbnails()
    return [dict(P.part_card(p, reg, thumbs), reason=why) for p, why in P.matching(slug, reg=reg)]


@router.get(
    "/parts/{slug}/template.pdf",
    summary="1:1 paper template (outline, holes, dimensions)",
    tags=["registry"],
    response_class=Response,
    responses={200: {"content": {"application/pdf": {}}}},
)
def part_template(slug: str, request: Request) -> Response:
    pdf = P.template_pdf(slug, _query_params(request))
    return Response(
        pdf, media_type="application/pdf", headers={"Content-Disposition": f'inline; filename="{slug}-template.pdf"'}
    )


@router.get(
    "/parts/{slug}/thumbnail.png",
    summary="Isometric thumbnail (rendered on first request)",
    tags=["registry"],
    response_class=FileResponse,
)
def part_thumbnail(slug: str, scale: Annotated[int, Query(ge=1, le=2)] = 1) -> FileResponse:
    part = P.require_part(slug)
    u1, u2 = P.ensure_thumbnail(part)
    path = blobs.locate((u2 if scale == 2 else u1).rsplit("/", 1)[-1])
    return FileResponse(path, media_type="image/png", headers={"Cache-Control": "public, max-age=300"})


class FeedbackRequest(BaseModel):
    result: Literal["fits", "tight", "loose", "pass", "fail"]
    kind: Literal["print", "screen_fit"] = "print"
    note: str = Field("", max_length=500)


@router.post("/parts/{slug}/feedback", summary="Did it fit? (lessons evidence)", tags=["registry"])
def part_feedback(slug: str, body: FeedbackRequest) -> dict[str, Any]:
    P.require_part(slug)
    fid = get_registry().add_fit_report(slug, body.kind, body.result, {"note": body.note})
    return {"id": fid, "slug": slug, "result": body.result, "kind": body.kind}


@router.get("/families", summary="Families with counts", tags=["registry"])
def families() -> list[dict[str, Any]]:
    from services.agent.templates import list_templates

    counts = {f["family"]: f for f in get_registry().families(include_reference=False)}
    names = list(dict.fromkeys([*counts, *(t.family.value for t in list_templates())]))
    return [
        {
            "family": n,
            "title": P.FAMILY_TITLES.get(n, n),
            "count": counts.get(n, {}).get("count", 0),
            "verified": counts.get(n, {}).get("verified", 0),
        }
        for n in names
    ]


class NeedRequest(BaseModel):
    query: str = Field(min_length=3, max_length=300, examples=["dishwasher rack wheel 22 mm"])


def _need_out(need: Need, photos: dict[str, str] | None = None) -> dict[str, Any]:
    d: dict[str, Any] = need.model_dump(mode="json")
    key = (photos if photos is not None else get_registry().need_photos()).get(need.id)
    d["photo_url"] = blobs.url(key) if key else None
    return d


def _client(request: Request) -> str:
    return usage.fingerprint(request.client.host if request.client else "", request.headers.get("user-agent", ""))


@router.post(
    "/needs",
    summary="Request a part that does not exist yet (JSON, or multipart with an optional photo)",
    tags=["requests"],
    openapi_extra={"requestBody": {"content": {
        "application/json": {"schema": {"type": "object", "properties": {"query": {"type": "string"}}},
                             "example": {"query": "dishwasher rack wheel 22 mm"}},
        "multipart/form-data": {"schema": {"type": "object", "properties": {
            "query": {"type": "string"}, "photo": {"type": "string", "format": "binary"}}}}}}},
)  # fmt: skip
async def needs_add(request: Request) -> dict[str, Any]:
    """A repeat of an existing request adds a vote (once per client). Photos are validated and GPS-stripped."""
    photo: bytes | None = None
    if request.headers.get("content-type", "").startswith("multipart/form-data"):
        form = await request.form()
        q = form.get("query")
        up = form.get("photo")
        if up is not None and not isinstance(up, str):
            photo = await up.read()
        query = q if isinstance(q, str) else ""
    else:
        try:
            body = await request.json()
        except json.JSONDecodeError as exc:
            raise ApiError(422, "validation_error", 'send JSON {"query": ...} or multipart query + photo') from exc
        query = str(body.get("query", "")) if isinstance(body, dict) else ""
    try:
        query = NeedRequest(query=query.strip()).query
    except ValueError as exc:
        raise ApiError(422, "validation_error", "query: 3 to 300 characters") from exc
    reg = get_registry()
    need, counted = reg.request_need(query, _client(request))
    if photo is not None:
        data, mime = clean_image(photo, "photo")
        reg.set_need_photo(need.id, blobs.put(data, ".jpg" if mime == "image/jpeg" else ".png"))
    return {**_need_out(need), "counted": counted}


@router.get("/needs", summary="Requested parts, most votes first", tags=["requests"])
def needs_list(
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    status: Literal["open", "in_progress", "fulfilled"] | None = None,
) -> list[dict[str, Any]]:
    reg = get_registry()
    photos = reg.need_photos()
    return [_need_out(n, photos) for n in reg.needs(500) if status is None or n.status == status][:limit]


@router.post("/needs/{need_id}/vote", summary="Vote for a request (one vote per client)", tags=["requests"])
def needs_vote(need_id: str, request: Request) -> dict[str, Any]:
    try:
        need, counted = get_registry().vote_need(need_id, _client(request))
    except KeyError as exc:
        raise ApiError(404, "need_not_found", f"no request {need_id!r}") from exc
    return {**_need_out(need), "counted": counted}


class NeedStatusRequest(BaseModel):
    status: Literal["open", "in_progress", "fulfilled"]


@router.patch("/needs/{need_id}", summary="Set a request's status (admin)", tags=["requests"])
def needs_status(need_id: str, body: NeedStatusRequest, _admin: None = Depends(require_admin)) -> dict[str, Any]:
    try:
        return _need_out(get_registry().set_need_status(need_id, body.status))
    except KeyError as exc:
        raise ApiError(404, "need_not_found", f"no request {need_id!r}") from exc


@router.get("/stats", summary="Counters computed from the database", tags=["registry"])
def stats() -> dict[str, Any]:
    s = get_registry().stats()
    try:
        s["jobs"] = sum(1 for j in _svc().manager().list(100_000) if not j.is_replay)
    except ApiError:
        s["jobs"] = 0
    s["usage"] = usage.summary()
    s.update({k: s["usage"][k] for k in ("calls_total", "mcp_calls", "distinct_clients", "last_7d")})
    return s


# ------------------------------------------------------------------------------------------------- steer


class SteerRequest(BaseModel):
    brief: str = Field(min_length=3, max_length=300, examples=["cupboard hardware kit, M4 screws, 5 mm grid"])
    count: int = Field(6, ge=1, le=steer.MAX_COUNT)


class ReviewRequest(BaseModel):
    slug: str
    action: Literal["approve", "send_back", "reject"]
    note: str = Field("", max_length=500, description="For send_back: a plain-words change, e.g. '2 mm taller'")


@router.post(
    "/steer", summary="Start a Steer factory run (Muse Wonder plans, lanes build + self-check)", tags=["steer"]
)
def steer_start(body: SteerRequest, _admin: None = Depends(require_admin)) -> dict[str, str]:
    return {"id": steer.start(body.brief, body.count)}


@router.get("/steer", summary="Recent Steer runs", tags=["steer"])
def steer_list(limit: Annotated[int, Query(ge=1, le=100)] = 20) -> list[dict[str, Any]]:
    return steer.list_runs(limit)


@router.get("/steer/{run_id}", summary="Steer state: plan, lanes, approval queue", tags=["steer"])
def steer_get(run_id: str) -> dict[str, Any]:
    try:
        return steer.get(run_id)
    except KeyError as exc:
        raise ApiError(
            404, "steer_not_found", f"no steer run {run_id!r}", [r["id"] for r in steer.list_runs(3)]
        ) from exc


@router.post(
    "/steer/{run_id}/review", summary="approve | send_back | reject one queued part; returns the state", tags=["steer"]
)
def steer_review(run_id: str, body: ReviewRequest, _admin: None = Depends(require_admin)) -> dict[str, Any]:
    state = steer_get(run_id)
    try:
        return steer.review(run_id, body.slug, body.action, body.note)
    except KeyError as exc:
        raise ApiError(
            404, "slug_not_in_queue", f"{body.slug!r} is not in this run's queue", [q["slug"] for q in state["queue"]]
        ) from exc
    except ValueError as exc:
        raise ApiError(409, "bad_review", str(exc)) from exc


# ------------------------------------------------------------------------------------------------- bench + agent docs


def _pending_table(name: str, gt: str) -> dict[str, Any]:
    return {
        "n": 0,
        "ground_truth": gt,
        "ci": None,
        "columns": [],
        "rows": [],
        "headline": {"median_abs_err_mm": None},
        "status": "pending",
        "note": "not run yet: `make bench` writes eval/reports/latest/report.json",
    }


BENCH_FILE_TYPES = {".png", ".jpg", ".jpeg", ".svg", ".json", ".md", ".csv", ".txt"}


def _reports_root() -> Any:
    return BENCH_REPORT.parent.parent.resolve()


def _report_file(rel: str) -> Any:
    """A file under eval/reports, or None. No traversal outside, no hidden files, only report media types."""
    root = _reports_root()
    if not rel or "\x00" in rel or any(part.startswith(".") for part in rel.split("/")):
        return None
    path = (root / rel).resolve()
    if not path.is_relative_to(root) or not path.is_file() or path.suffix.lower() not in BENCH_FILE_TYPES:
        return None
    return path


def _overlay_url(failure: dict[str, Any]) -> str | None:
    """The failure's overlay: its blob when present, else the report file served by /bench/files, else None."""
    url = failure.get("overlay_url")
    if isinstance(url, str) and url and _resolve_artifact(url) is not None:
        return url
    name = failure.get("overlay_file")
    if not isinstance(name, str) or not name:
        return None
    root = _reports_root()
    dirs = [BENCH_REPORT.parent, *sorted((d for d in root.iterdir() if d.is_dir()), reverse=True)]
    for d in dirs:
        rel = f"{d.resolve().relative_to(root).as_posix()}/{name}"
        if _report_file(rel) is not None:
            return f"{API}/bench/files/{rel}"
    return None


EVIDENCE_FILES = ("bypass", "program_vs_mesh", "impact", "open_weights")


def _bench_evidence() -> dict[str, Any]:
    """Side reports next to report.json (lying-brain bypass suite, program vs mesh, impact log, open weights): each
    is the file's JSON, or null when that script has not run yet."""
    out: dict[str, Any] = {}
    for name in EVIDENCE_FILES:
        path = BENCH_REPORT.parent / f"{name}.json"
        try:
            out[name] = json.loads(path.read_text()) if path.exists() else None
        except json.JSONDecodeError:
            out[name] = None
    return out


@router.get("/bench", summary="Latest PartSmith-Bench report (or a 'pending' payload)", tags=["bench"])
def bench() -> dict[str, Any]:
    """`failures[].overlay_url` always resolves (a blob or `/bench/files/...`) or is null."""
    if BENCH_REPORT.exists():
        try:
            report: dict[str, Any] = json.loads(BENCH_REPORT.read_text())
        except json.JSONDecodeError as exc:
            raise ApiError(500, "bad_report", "eval/reports/latest/report.json is not valid JSON") from exc
        report.setdefault("status", "ok")
        for f in report.get("failures") or []:
            if isinstance(f, dict):
                f["overlay_url"] = _overlay_url(f)
        report["evidence"] = _bench_evidence()
        return report
    return {
        "status": "pending",
        "generated_at": None,
        "git_sha": None,
        "tables": {
            "synthetic": _pending_table("synthetic", "synthetic_exact"),
            "reference_objects": _pending_table("reference_objects", "reference_spec"),
            "real_ruler": _pending_table("real_ruler", "ruler"),
        },
        "runs": [],
        "failures": [],
        "evidence": _bench_evidence(),
    }


@router.get(
    "/bench/files/{path:path}",
    summary="A file of a bench report (overlays, charts) under eval/reports",
    tags=["bench"],
    response_class=FileResponse,
)
def bench_file(path: str) -> FileResponse:
    found = _report_file(path)
    if found is None:
        raise ApiError(404, "report_file_not_found", f"no report file {path!r}")
    return FileResponse(found, headers={"Cache-Control": "public, max-age=300"})


@router.get(
    "/llms.txt",
    summary="Reference for LLMs (generated from the registry)",
    tags=["agents"],
    response_class=PlainTextResponse,
)
def llms_txt(request: Request) -> PlainTextResponse:
    return PlainTextResponse(
        agentdocs.llms_txt(base=public_base(request)), headers={"Cache-Control": "public, max-age=60"}
    )


@router.get(
    "/prompt.txt", summary="Working instructions for coding agents", tags=["agents"], response_class=PlainTextResponse
)
def prompt_txt(request: Request) -> PlainTextResponse:
    return PlainTextResponse(
        agentdocs.prompt_txt(base=public_base(request)), headers={"Cache-Control": "public, max-age=60"}
    )


app.include_router(router)
app.include_router(round2_router)
app.include_router(embed_router)
app.add_api_route("/llms.txt", llms_txt, methods=["GET"], include_in_schema=False)
app.add_api_route("/prompt.txt", prompt_txt, methods=["GET"], include_in_schema=False)
app.router.routes.append(Route("/mcp", endpoint=mcp_mount, methods=["GET", "POST", "DELETE"]))


def iter_routes() -> Iterator[tuple[str, str]]:
    """(method, path) of every route: the OpenAPI paths plus the plain routes (openapi.json, llms.txt, /mcp)."""
    for path, ops in app.openapi()["paths"].items():
        for method in ops:
            yield method.upper(), path
    for r in app.routes:
        methods = getattr(r, "methods", None) or set()
        for m in sorted(methods - {"HEAD", "OPTIONS"}):
            yield m, getattr(r, "path", "")


# keep these names referenced for OpenAPI response models
__all__ = ["PartRecord", "app"]
