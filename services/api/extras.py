"""Open data routes: search demand (`GET /demand`) and a part's verification record and knobs as plain JSON documents
(`/parts/{slug}/verification.json`, `/parts/{slug}/params.json`). Every number comes from the stored record."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from services.api.common import API
from services.api.errors import ApiError
from services.common import blobs
from services.registry import demand
from services.registry import parts as P
from services.registry.store import get_registry

router = APIRouter(prefix=API)

JSON_SCHEMA = "https://json-schema.org/draft/2020-12/schema"


def _iso(ts: float) -> str | None:
    return datetime.fromtimestamp(ts, UTC).isoformat(timespec="seconds") if ts else None


@router.get("/demand", summary="Open requests by votes and searches that found no close part", tags=["requests"])
def demand_get(
    needs: Annotated[int, Query(ge=0, le=200, description="How many open requests")] = 20,
    missed: Annotated[int, Query(ge=0, le=200, description="How many missed searches")] = 50,
) -> dict[str, Any]:
    """`needs`: open requests, most votes first. `missed_searches`: registry searches (web and MCP) grouped by
    normalised query whose best coverage stayed below 0.5, most asked first — {q, count, best_coverage, last_at}.
    The search log keeps the query text, result count, best coverage and time only (no IP, no user agent)."""
    reg = get_registry()
    photos = reg.need_photos()
    open_needs = [n for n in reg.needs(500) if n.status == "open"][:needs]
    out_needs = []
    for n in open_needs:
        d: dict[str, Any] = n.model_dump(mode="json")
        key = photos.get(n.id)
        d["photo_url"] = blobs.url(key) if key else None
        out_needs.append(d)
    return {
        "needs": out_needs,
        "missed_searches": demand.missed_searches(missed) if missed else [],
        "miss_below": demand.MISS_BELOW,
    }


@router.get(
    "/parts/{slug}/verification.json",
    summary="The part's stored verification record as a JSON document",
    tags=["registry"],
)
def part_verification_json(slug: str) -> JSONResponse:
    """Max error and its limit, per-view silhouette metrics, per-feature residuals, part tests, unchecked knobs, the
    verifier version and when the part was published — exactly as stored with the part (404 `no_verification` when
    the part has none)."""
    part = P.require_part(slug)
    v = part.verification
    if v is None:
        raise ApiError(404, "no_verification", f"part {slug!r} has no stored verification record")
    record = v.model_dump(mode="json")
    body = {
        "slug": part.slug,
        "title": part.title,
        "version": part.version,
        "code_sha": part.code_sha,
        "verified": v.verified,
        "status": v.status,
        "max_error_mm": v.max_error_mm,
        "limit_mm": v.thresholds.hausdorff_mm,
        "iou_limit": v.thresholds.iou,
        "views": record["views"],
        "residuals": record["residuals"],
        "tests": record["tests"],
        "unchecked": record["unchecked"],
        "reasons": record["reasons"],
        "origin": record["origin"],
        "verifier_version": v.versions.get("verifier"),
        "versions": record["versions"],
        "published_at": _iso(part.created_at),
        "verification": record,
    }
    return JSONResponse(
        body, headers={"Content-Disposition": f'inline; filename="partsmith-{part.slug}-verification.json"'}
    )


@router.get("/parts/{slug}/params.json", summary="The part's knobs as a JSON-Schema document", tags=["registry"])
def part_params_json(slug: str) -> JSONResponse:
    """One property per knob: type (integer for knobs that change topology, else number), unit (mm, deg or none),
    default, minimum, maximum, step and a description. An object that validates against it is a valid set of
    `/parts/{slug}/bake` query values."""
    part = P.require_part(slug)
    props: dict[str, Any] = {}
    for p in part.params:
        props[p.name] = {
            "type": "integer" if p.topology else "number",
            "unit": p.unit or None,
            "default": part.defaults.get(p.name, p.default),
            "minimum": p.min,
            "maximum": p.max,
            "step": p.step,
            "description": p.label or p.name.replace("_", " "),
            "affects_fit": p.affects_fit,
            "topology": p.topology,
        }
    body = {
        "$schema": JSON_SCHEMA,
        "$id": f"{API}/parts/{part.slug}/params.json",
        "title": f"{part.title} — knobs",
        "type": "object",
        "slug": part.slug,
        "version": part.version,
        "code_sha": part.code_sha,
        "units": "millimetres for lengths, degrees for angles",
        "properties": props,
        "additionalProperties": False,
        "bake": f"{API}/parts/{part.slug}/bake",
    }
    return JSONResponse(body, headers={"Content-Disposition": f'inline; filename="partsmith-{part.slug}-params.json"'})
