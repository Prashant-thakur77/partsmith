"""Product routes: the parametric playground (`/templates`), "Describe it" (`/describe`), saving a registry variant
(`POST /parts/{slug}/variants`), the "Print it" settings (`/jobs/{id}/print-plan`, `/parts/{slug}/print-plan`) and the
cited print-shop lookup (`POST /print-shops`). Mounted by `services/api/main.py` under `/api/v1` (docs/API.md).
"""

from __future__ import annotations

import hashlib
import json
import time
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import FileResponse
from partsmith_schemas.registry import BakeResult
from pydantic import BaseModel, Field

from services.admin import audit
from services.agent import buy_or_print as bop
from services.agent import providers
from services.agent.templates import get_template, list_templates
from services.api.auth import require_admin
from services.api.common import API, EXTENSIONS, RESERVED_QUERY, _file, _float, _formats, _job, job_decision
from services.api.errors import ApiError
from services.common import blobs
from services.common.paths import sub
from services.geom_worker import bake as geom_bake
from services.geom_worker.program import clamp
from services.registry import describe, examples, gate, variants
from services.registry import parts as P
from services.registry.filenames import download_name

router = APIRouter(prefix=API)

TEMPLATE_SOURCE = "registry.gate (template bake)"


def template_decision() -> gate.ShipDecision:
    """Template bakes (playground, Describe it) are not checked against a real part: best effort, with the reason."""
    return gate.ShipDecision("best_effort", examples.TEMPLATE_SHIP_REASON, TEMPLATE_SOURCE)


def _template(name: str) -> Any:
    try:
        return get_template(name)
    except KeyError as exc:
        import difflib

        names = [t.name for t in list_templates()]
        raise ApiError(
            404, "template_not_found", f"no template {name!r}", difflib.get_close_matches(name, names, n=3, cutoff=0.3)
        ) from exc


def _knobs(request: Request) -> dict[str, float]:
    return {k: _float(k, v) for k, v in request.query_params.multi_items() if k not in RESERVED_QUERY}


# ------------------------------------------------------------------------------------------------- playground


@router.get("/templates", summary="Every family template as a playground example (knobs, presets, thumbnail)",
            tags=["templates"])  # fmt: skip
def templates_list() -> list[dict[str, Any]]:
    return examples.all_cards()


@router.get("/templates/{name}", summary="One template: knobs, presets and its program (part.py)", tags=["templates"])
def template_get(name: str) -> dict[str, Any]:
    return examples.template_detail(_template(name))


@router.get("/templates/{name}/thumbnail.png", summary="Isometric thumbnail at the defaults (cached)",
            tags=["templates"], response_class=FileResponse)  # fmt: skip
def template_thumbnail(name: str, scale: Annotated[int, Query(ge=1, le=2)] = 1) -> FileResponse:
    _template(name)
    path = examples.thumbnail_path(name, scale)
    return FileResponse(path, media_type="image/png", headers={"Cache-Control": "public, max-age=3600"})


@router.get(
    "/templates/{name}/bake",
    summary="Bake a template at params (cached); `&download=1&ack=1` returns the file",
    tags=["templates"],
    responses={200: {"model": BakeResult}},
)
def template_bake(name: str, request: Request, download: bool = False, ack: bool = False) -> Any:
    """Query: `<param>=<value>` knobs plus `format=` (default stl,step,view). Out-of-range values are clamped and
    listed in `clamped`; unknown knobs are a 422 with `closest_matches`. Identical requests are cache hits. The JSON
    adds `print_plan` (orientation, supports, suggested settings, grams and minutes from the mesh), `downloads` and
    `ship`. `download=1`: `view`/`glb` are previews; printable files are not checked against a real part, so they
    answer `409 needs_ack` until `ack=1`."""
    t = _template(name)
    fmts = _formats(request)
    params = _knobs(request)
    decision = template_decision()
    if download and fmts[0] not in ("view", "glb"):
        gate.require(decision, ack)
    out = examples.bake_template(t.name, params, fmts)
    blobs.claim(out.cache_key, f"template:{t.name}")  # its /bakes/... file links go through the same decision
    if download:
        fmt = fmts[0]
        path = out.files.get(fmt)
        if path is None:
            raise ApiError(404, "artifact_not_found", f"no {fmt} file in this bake", sorted(out.files))
        defaults = {sp.name: sp.default for sp in t.params}
        name = download_name(t.name, EXTENSIONS[fmt], out.params, defaults, [sp.name for sp in t.params])
        return _file(path, fmt, name)
    res = out.to_bake_result(t.name, lambda fmt, p: P.bake_url(out.cache_key, p.name)).model_dump(mode="json")
    res["facts_notes"] = out.facts_notes
    res["print_plan"] = bop.print_plan(out.facts) if out.facts else None
    res["downloads"] = examples.template_urls(t.name, out.params)
    res["ship"] = decision.to_dict()
    return res


@router.get("/templates/{name}/coupon.stl", summary="Fit-test coupon for the template's holes at params (STL)",
            tags=["templates"], response_class=FileResponse)  # fmt: skip
def template_coupon(name: str, request: Request) -> FileResponse:
    """A small test print with the template's screw hole / bore at −0.2, 0 and +0.2 mm. 404 `no_coupon` when the
    template has no hole knob (or zero holes at these values). The coupon is the recommended first print, so it is
    not held back by the export gate."""
    t = _template(name)
    params = _knobs(request)
    values, _ = clamp(params, list(t.params))  # unknown knobs: 422 unknown_param + closest
    code = examples.coupon_code(t.name, values)
    if code is None:
        raise ApiError(404, "no_coupon", f"{t.title} has no screw hole or bore to test at these values")
    out = geom_bake.bake(code, {}, ("stl",))
    return _file(out.files["stl"], "stl", download_name(f"{t.name}-coupon", ".stl"))


# ------------------------------------------------------------------------------------------------- describe it


class DescribeRequest(BaseModel):
    text: str = Field(min_length=3, max_length=describe.MAX_TEXT,
                      examples=["a cable clip for a 6 mm cable, screws down with one M3 screw, 20 mm wide"])  # fmt: skip


class AnswersRequest(BaseModel):
    answers: dict[str, float | None] = Field(
        default_factory=dict, description="knob -> number, or null to keep the template default"
    )


def _describe(rid: str) -> dict[str, Any]:
    try:
        return describe.get(rid)
    except KeyError as exc:
        raise ApiError(404, "describe_not_found", f"no description {rid!r}", describe.recent(3)) from exc


@router.post("/describe", summary="Words with numbers → one template part, every number checked by code",
             tags=["describe"])  # fmt: skip
def describe_start(body: DescribeRequest) -> dict[str, Any]:
    """The `describe_plan` stage (Muse Spark 1.3; labelled mock without a key) proposes a template + values with
    their sources; code checks the plan, asks for missing fit-critical numbers (`status: needs_answers`) or bakes
    the part and compares every number you gave with the baked model (`checks`). Anonymous; rate limited."""
    try:
        return describe.public(describe.start(body.text))
    except ValueError as exc:
        raise ApiError(422, "validation_error", str(exc)) from exc


@router.get("/describe/{rid}", summary="A stored description: plan, values with sources, checks, files",
            tags=["describe"])  # fmt: skip
def describe_get(rid: str) -> dict[str, Any]:
    return describe.public(_describe(rid))


@router.post("/describe/{rid}/answers", summary="Answer the missing numbers (no second model call), then bake",
             tags=["describe"])  # fmt: skip
def describe_answer(rid: str, body: AnswersRequest) -> dict[str, Any]:
    _describe(rid)
    try:
        return describe.public(describe.answer(rid, body.answers))
    except ValueError as exc:
        raise ApiError(409, "no_pending_question", str(exc)) from exc


# ------------------------------------------------------------------------------------------------- variants


class VariantSaveRequest(BaseModel):
    params: dict[str, float] = Field(description="knob values (others keep the part's own)")
    title: str | None = Field(None, max_length=120)


@router.post("/parts/{slug}/variants", summary="Save a registry variant at new knob values (admin)",
             tags=["registry"])  # fmt: skip
def part_variant_save(slug: str, body: VariantSaveRequest, _admin: None = Depends(require_admin)) -> dict[str, Any]:
    """Admin. Builds the part's program at the values in the sandbox and publishes it (dedupe, descriptive slug,
    `forked_from`). The variant's record is best effort: "a variant of a verified part, not itself checked against a
    photo"; the changed knobs are listed in `verification.unchecked`."""
    try:
        outcome, diff = variants.save_variant(slug, body.params, title=body.title)
    except variants.NoChange as exc:
        raise ApiError(409, "no_change", str(exc)) from exc
    audit.record("part.variant", slug, after=outcome.to_dict(), numbers={"changed": len(diff)})
    return variants.outcome_json(outcome, diff)


# ------------------------------------------------------------------------------------------------- print it


@router.get("/jobs/{job_id}/print-plan", summary="Print it: orientation, supports, settings, grams, minutes",
            tags=["jobs"])  # fmt: skip
def job_print_plan(job_id: str) -> dict[str, Any]:
    job = _job(job_id)
    if not job.read_text("part.py"):
        raise ApiError(409, "no_program", "the job has no part program yet, so there is nothing to print")
    facts = bop.job_facts(job)
    if facts is None:
        raise ApiError(409, "no_program", "the job's program could not be baked, so there are no print facts")
    return {"print_plan": bop.print_plan(facts), "ship": job_decision(job).to_dict()}


@router.get("/parts/{slug}/print-plan", summary="Print it for a registry part at params", tags=["registry"])
def part_print_plan(slug: str, request: Request) -> dict[str, Any]:
    part = P.require_part(slug)
    out = P.bake_output(part, _knobs(request), ("stl",))
    if out.facts is None:
        raise ApiError(409, "no_program", "no print facts for this bake")
    return {"print_plan": bop.print_plan(out.facts), "ship": gate.decide_part(part).to_dict()}


class PrintShopsRequest(BaseModel):
    city: str = Field(min_length=2, max_length=80, examples=["Pune"])
    title: str = Field(min_length=3, max_length=120, description="what is being printed", examples=["Cable clip"])


SHOPS_TTL_S = 24 * 3600


@router.post("/print-shops", summary="Print shops near a city (search-grounded, cited items only)", tags=["describe"])
def print_shops(body: PrintShopsRequest) -> dict[str, Any]:
    """The buy-or-print lookup (`buy_lookup` stage) with a city: only places and offers with a cited page and quote
    are kept; a labelled mock without a key. The same (title, city) within 24 h returns the stored answer, so a
    reload never pays for a second search. The model call is recorded as a `model_call` event on the stored lookup."""
    city = " ".join(body.city.split())
    title = " ".join(body.title.split())
    key = hashlib.sha256(f"{title.lower()}|{city.lower()}".encode()).hexdigest()[:20]
    path = sub("print_shops") / f"{key}.json"
    if path.exists():
        rec: dict[str, Any] = json.loads(path.read_text())
        if time.time() - float(rec.get("created_at", 0)) < SHOPS_TTL_S:
            return {**rec["lookup"], "cached": True}
    events: list[dict[str, Any]] = []

    def emit(ev: Any) -> None:
        events.append(ev.model_dump(mode="json") if hasattr(ev, "model_dump") else dict(ev))

    query = bop.lookup_query(f"{title} — 3D printing service", None, "")
    with providers.job_context(f"ps_{key}", emit):
        found = bop.to_lookup(providers.buy_lookup(query, city=city))
    lookup = found.model_dump(mode="json")
    path.write_text(json.dumps({"created_at": time.time(), "lookup": lookup, "events": events}, indent=1))
    return {**lookup, "cached": False}


__all__ = ["router", "template_decision"]
