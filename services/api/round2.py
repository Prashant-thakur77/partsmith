"""Product routes: bundle.zip, embed viewer, fit presets, share cards, lessons, repair-shop batches and the
open-weights evidence pack. Mounted by `services/api/main.py` under `/api/v1` (the embed page lives at `/embed/{slug}`)."""

from __future__ import annotations

import difflib
import json
import os
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, Response
from partsmith_schemas import PartFacts, PartRecord
from pydantic import BaseModel, Field

from services.agent import providers
from services.api.auth import require_admin
from services.api.common import API, _query_params, _svc
from services.api.errors import ApiError
from services.common import blobs
from services.common.paths import REPO_ROOT
from services.registry import batches, bundle, gate, presets, share_card
from services.registry import parts as P
from services.registry.store import get_registry

router = APIRouter(prefix=API)
embed_router = APIRouter()
OPEN_WEIGHTS_REPORT = REPO_ROOT / "eval" / "reports" / "latest" / "open_weights.json"


def _web(path: str) -> str:
    return os.environ.get("PARTSMITH_WEB_URL", "http://localhost:3000").rstrip("/") + path


# ------------------------------------------------------------------------------------------------- presets


def apply_preset(part: PartRecord, params: dict[str, float], preset: str | None) -> tuple[dict[str, float], Any]:
    """(params with the preset applied on top, preset info or None). 422 `unknown_preset` with the closest ids."""
    if not preset:
        return params, None
    if preset not in presets.BY_ID:
        ids = list(presets.BY_ID)
        raise ApiError(
            422, "unknown_preset", f"no fit preset {preset!r}", difflib.get_close_matches(preset, ids) or ids
        )
    unknown = [k for k in params if k not in part.defaults]
    if unknown:  # let the bake report unknown knobs with closest matches
        return params, None
    base = {**part.defaults, **params}
    values, changes = presets.apply(preset, part.params, base)
    p = presets.BY_ID[preset]
    return values, {"id": p.id, "title": p.title, "delta_mm": p.delta_mm, "changes": changes}


@router.get("/presets", summary="All fit presets (material × process clearances)", tags=["registry"])
def presets_all() -> list[dict[str, Any]]:
    return [{"id": p.id, "title": p.title, "material": p.material, "process": p.process, "nozzle_mm": p.nozzle_mm,
             "delta_mm": p.delta_mm, "note": p.note} for p in presets.PRESETS]  # fmt: skip


@router.get("/parts/{slug}/presets", summary="Fit presets and what each changes on this part", tags=["registry"])
def part_presets(slug: str) -> dict[str, Any]:
    part = P.require_part(slug)
    return {
        "slug": slug,
        "fit_knobs": [p.name for p in presets.fit_knobs(part.params)],
        "presets": presets.for_part(part.params, part.defaults),
        "note": "Clearances are documented starting points, not measurements; print the fit-test coupon to tune.",
    }


# ------------------------------------------------------------------------------------------------- bundle, embed, card


@router.get(
    "/parts/{slug}/bundle.zip",
    summary="Zip: part.py, STEP, STL, 3MF, verification.json, README, LICENSE, offline viewer",
    tags=["registry"],
    response_class=Response,
    responses={200: {"content": {"application/zip": {}}}},
)
def part_bundle(slug: str, request: Request, preset: str | None = None, ack: bool = False) -> Response:
    """Export gate: verified parts download directly; best effort needs `ack=1` (the 409 says why); failed parts are
    refused. Knob values in the query (and `preset=`) are baked into `part.py` and every file."""
    part = P.require_part(slug)
    decision = gate.decide_part(part)
    gate.require(decision, ack)
    params, info = apply_preset(part, _query_params(request), preset)
    data = bundle.build_bundle(part, params, decision, preset=info)
    return Response(data, media_type="application/zip",
                    headers={"Content-Disposition": f'attachment; filename="{slug}.zip"'})  # fmt: skip


@embed_router.get("/embed/{slug}", response_class=HTMLResponse, include_in_schema=False)
def embed(slug: str, request: Request) -> HTMLResponse:
    """Minimal viewer page for iframes: `<iframe src="…/embed/{slug}">`. Knob values in the query are applied."""
    part = P.require_part(slug)
    params = _query_params(request)
    from urllib.parse import urlencode

    src = f"{API}/parts/{slug}/bake?" + urlencode({**params, "format": "view", "download": 1})
    status, _ = share_card.status_text(part)
    page = bundle.viewer_html(part.title, src=src, caption=f"{status} · {share_card.origin_text(part)}",
                              link=_web(f"/parts/{slug}"))  # fmt: skip
    return HTMLResponse(page, headers={"Content-Security-Policy": "frame-ancestors *",
                                       "Cache-Control": "public, max-age=300"})  # fmt: skip


@router.get(
    "/parts/{slug}/card.png",
    summary="1200×630 share card (og:image)",
    tags=["registry"],
    response_class=FileResponse,
)
def part_card_png(slug: str) -> FileResponse:
    part = P.require_part(slug)
    P.ensure_thumbnail(part)
    t = get_registry().thumbnail(slug)
    key = share_card.card_key(part, t["key_2x"] if t else None, _web(f"/parts/{slug}").split("://", 1)[-1])
    return FileResponse(blobs.locate(key), media_type="image/png", headers={"Cache-Control": "public, max-age=300"})


# ------------------------------------------------------------------------------------------------- lessons


def _lesson_links(evidence: dict[str, Any]) -> list[dict[str, str]]:
    links: list[dict[str, str]] = []
    jobs = [evidence.get("job_id"), *list(evidence.get("job_ids") or [])]
    for jid in [j for j in jobs if isinstance(j, str) and j]:
        links.append({"kind": "job", "id": jid, "url": f"{API}/jobs/{jid}", "page": f"/jobs/{jid}"})
    for key in ("slug", "part_slug"):
        if isinstance(evidence.get(key), str):
            s = evidence[key]
            links.append({"kind": "part", "id": s, "url": f"{API}/parts/{s}", "page": f"/parts/{s}"})
    for fid in evidence.get("fit_report_ids") or []:
        links.append({"kind": "fit_report", "id": str(fid), "url": "", "page": ""})
    return links


def lessons_out(scope: str | None = None, status: str | None = None) -> list[dict[str, Any]]:
    return [dict(x, links=_lesson_links(x["evidence"])) for x in get_registry().lessons(scope, status)]


@router.get(
    "/lessons", summary="Lessons: candidates, promoted and rejected rules with evidence links", tags=["lessons"]
)
def lessons_list(
    status: Annotated[str | None, Query(pattern="^(candidate|promoted|rejected)$")] = None,
    scope: str | None = None,
) -> list[dict[str, Any]]:
    """Only promoted lessons are fed to future builds; promotion is a human decision (admin)."""
    return lessons_out(scope, status)


class LessonDecision(BaseModel):
    by: str = Field("admin", max_length=64)


def _decide_lesson(lid: str, status: str, by: str) -> dict[str, Any]:
    reg = get_registry()
    try:
        reg.set_lesson_status(lid, status, by)
    except KeyError as exc:
        ids = [x["id"] for x in reg.lessons()]
        raise ApiError(404, "lesson_not_found", f"no lesson {lid!r}", difflib.get_close_matches(lid, ids)) from exc
    lesson = reg.lesson(lid) or {}
    return dict(lesson, links=_lesson_links(lesson.get("evidence") or {}))


@router.post("/lessons/{lesson_id}/promote", summary="Promote a lesson (admin)", tags=["lessons"])
def lesson_promote(
    lesson_id: str, body: LessonDecision | None = None, _admin: None = Depends(require_admin)
) -> dict[str, Any]:
    return _decide_lesson(lesson_id, "promoted", body.by if body else "admin")


@router.post("/lessons/{lesson_id}/reject", summary="Reject a lesson (admin)", tags=["lessons"])
def lesson_reject(
    lesson_id: str, body: LessonDecision | None = None, _admin: None = Depends(require_admin)
) -> dict[str, Any]:
    return _decide_lesson(lesson_id, "rejected", body.by if body else "admin")


# ------------------------------------------------------------------------------------------------- batches


def _job_info(job_id: str) -> dict[str, Any] | None:
    try:
        job = _svc().manager().get(job_id)
    except ApiError:
        return None
    if job is None:
        return None
    s = job.summary
    facts = job.read_json("facts.json")
    if not facts and s.part_slug:
        part = get_registry().get_part(s.part_slug)
        facts = part.facts.model_dump(mode="json") if part and part.facts else None
    if facts:
        facts = PartFacts.model_validate(facts).model_dump(mode="json")
    return {"title": s.title, "status": s.status, "verified": s.verified, "max_error_mm": s.max_error_mm,
            "origin": s.origin.value, "part_slug": s.part_slug, "facts": facts}  # fmt: skip


class Customer(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    contact: str = Field("", max_length=80)
    jobs: list[str] = Field(default_factory=list)


class BatchRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120, examples=["Saturday walk-ins"])
    customers: list[Customer] = Field(default_factory=list)


class BatchJob(BaseModel):
    customer: str = Field(min_length=1, max_length=80)
    job_id: str
    contact: str = Field("", max_length=80)


def _batch_out(batch: dict[str, Any]) -> dict[str, Any]:
    rate, base = batches.price_rate()
    return dict(batch, rows=batches.rows(batch, _job_info), price={"inr_per_g_pla": rate, "inr_base_per_part": base})


def _batch(bid: str) -> dict[str, Any]:
    try:
        return batches.get(bid)
    except KeyError as exc:
        raise ApiError(404, "batch_not_found", f"no batch {bid!r}") from exc


@router.post("/batches", summary="Create a repair-shop batch (customers → jobs) (admin)", tags=["batches"])
def batch_create(body: BatchRequest, _admin: None = Depends(require_admin)) -> dict[str, Any]:
    try:
        return _batch_out(batches.create(body.name, [c.model_dump() for c in body.customers]))
    except ValueError as exc:
        raise ApiError(422, "validation_error", str(exc)) from exc


@router.get("/batches", summary="Batches (admin)", tags=["batches"])
def batch_list(_admin: None = Depends(require_admin)) -> list[dict[str, Any]]:
    return batches.list_batches()


@router.get("/batches/{batch_id}", summary="A batch with per-job rows and price estimates (admin)", tags=["batches"])
def batch_get(batch_id: str, _admin: None = Depends(require_admin)) -> dict[str, Any]:
    return _batch_out(_batch(batch_id))


@router.post("/batches/{batch_id}/jobs", summary="Add a job to a customer in a batch (admin)", tags=["batches"])
def batch_add_job(batch_id: str, body: BatchJob, _admin: None = Depends(require_admin)) -> dict[str, Any]:
    _batch(batch_id)
    try:
        return _batch_out(batches.add_job(batch_id, body.customer, body.job_id, body.contact))
    except ValueError as exc:
        raise ApiError(422, "validation_error", str(exc)) from exc


@router.get(
    "/batches/{batch_id}/sheet.pdf",
    summary="Per-customer job sheet PDF (admin)",
    tags=["batches"],
    response_class=Response,
    responses={200: {"content": {"application/pdf": {}}}},
)
def batch_sheet(batch_id: str, _admin: None = Depends(require_admin)) -> Response:
    pdf = batches.sheet_pdf(_batch(batch_id), _job_info)
    return Response(pdf, media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="{batch_id}-job-sheet.pdf"'})  # fmt: skip


# ------------------------------------------------------------------------------------------------- open weights


def _recorded_model_calls() -> list[Any]:
    """`model_call` events of every job on this server and every bundled replay (live and replayed calls)."""
    try:
        mgr = _svc().manager()
        summaries = mgr.list(100_000, include_replays=True)
    except ApiError:
        return []
    out: list[Any] = []
    for s in summaries:
        job = mgr.get(s.id)
        if job is not None:
            out += [e for e in job.events if e.t == "model_call"]
    return out


@router.get("/status/open-weights", summary="Open-weights evidence: live summary + bench report", tags=["system"])
def open_weights() -> dict[str, Any]:
    """`summary` from the providers layer (which stages run on open weights, where, with what calls), `report` from
    eval/reports/latest/open_weights.json. Either is null with a note when not available yet."""
    fn = getattr(providers, "open_weights_summary", None)
    summary: Any = None
    note: list[str] = []
    if callable(fn):
        try:
            events = _recorded_model_calls()
            try:
                summary = fn(events)  # every recorded run, not just this process
            except TypeError:
                summary = fn()
        except Exception as exc:  # evidence endpoint must not fail the page
            note.append(f"open_weights_summary failed: {type(exc).__name__}")
    else:
        note.append("providers.open_weights_summary is not available in this build")
    report: Any = None
    if OPEN_WEIGHTS_REPORT.exists():
        try:
            report = json.loads(OPEN_WEIGHTS_REPORT.read_text())
        except json.JSONDecodeError:
            note.append("open_weights.json is not valid JSON")
    else:
        note.append("eval/reports/latest/open_weights.json not generated yet")
    rows = [r for r in providers.status() if r.get("open_weights")]
    return {"status": "ok" if summary is not None and report is not None else "partial" if summary or report else
            "pending", "summary": summary, "report": report, "stages": rows, "notes": note}  # fmt: skip
