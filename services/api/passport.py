"""Repair passport routes: resolve a printed id, serve its QR code, and decide the passport mark on bakes.
Mounted by `services/api/main.py` under `/api/v1` (docs/API.md "Repair passport")."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Annotated, Any

from fastapi import APIRouter, Path, Request
from fastapi.responses import Response
from partsmith_schemas import PartRecord, Passport, Verification
from partsmith_schemas.verification import ParamSpec

from services.agent import jobs
from services.api.common import API, _job, _svc, public_base
from services.api.errors import ApiError
from services.geom_worker.program import clamp
from services.registry import gate
from services.registry import passport as PP
from services.registry.publish import values_of
from services.registry.store import get_registry

router = APIRouter(prefix=API)
PassportId = Annotated[str, Path(min_length=1, max_length=24, description="Passport id, e.g. 7KQ3MZ (any case)")]
QR_CACHE = "public, max-age=3600"  # the code encodes this server's public URL, so it is not immutable


def job_ids() -> list[str]:
    """Every job on this server (runs and bundled replays), from the directory names only (nothing is loaded)."""
    roots = [_svc().manager().root, jobs.REPLAYS_DIR]
    out: list[str] = []
    for root in roots:
        if root.exists():
            out += [d.name for d in root.iterdir() if (d / "summary.json").exists() or (d / "run.jsonl").exists()]
    return out


def _job_or_none(jid: str | None) -> Any:
    if not jid:
        return None
    try:
        return _job(jid)
    except ApiError:
        return None


def resolve(raw: str) -> Passport:
    """The passport behind a typed or scanned id; 404 `passport_not_found` with the closest ids otherwise."""
    reg = get_registry()
    ids = job_ids()
    pid = PP.normalize(raw)
    match = PP.find(pid, reg, ids) if pid else None
    if match is None or pid is None:
        msg = f"no passport {raw!r}" + ("" if pid else f" (an id is {PP.ID_LEN} letters or digits)")
        raise ApiError(404, "passport_not_found", msg, PP.closest(raw, reg, ids))
    if match.kind == "part":
        assert match.part is not None
        src = _job_or_none(match.part.provenance.job_id)
        spec = src.read_json("partspec.json") if src is not None else None
        out = PP.for_part(match.part, pid=pid, version=match.version, spec=spec)
    else:
        assert match.job is not None
        job = _job(match.job)
        spec = job.read_json("partspec.json") or {}
        part = get_registry().get_part(job.summary.part_slug) if job.summary.part_slug else None
        if part is not None:
            out = PP.for_part(part, pid=pid, spec=spec, job=job.id, job_status=job.summary.status)
        else:
            data = job.read_json("verification.json")
            ver = Verification.model_validate(data) if data else None
            values = {k: float(v) for k, v in (job.read_json("values.json") or {}).items()}
            title = str(spec.get("title") or job.summary.title or "").split(" (")[0]
            out = PP.for_job(
                pid=pid, job=job.id, title=title, family=str(spec.get("family", "custom")), values=values, spec=spec,
                verification=ver, decision=gate.decide(verification=ver, job=job), origin=job.input.origin,
                job_status=job.summary.status,
            )  # fmt: skip
    if match.others:
        out.notes.append("the same id also matches: " + ", ".join(match.others[:3]) + " (shown: the first match)")
    return out


@router.get("/passport/{passport_id}", summary="Resolve a repair passport id", tags=["registry"])
def passport_get(passport_id: PassportId) -> dict[str, Any]:
    """The part (or unpublished job) a printed passport id points at: knob values, fit preset, verification status
    and the gated bake route to reprint it. Unknown ids → 404 `passport_not_found` with the closest ids."""
    out: dict[str, Any] = resolve(passport_id).model_dump(mode="json")
    return out


def _qr_text(request: Request, pid: str) -> str:
    return f"{public_base(request)}/p/{pid}"


@router.get("/passport/{passport_id}/qr.svg", summary="QR code to /p/{id} (SVG)", tags=["registry"])
def passport_qr_svg(passport_id: PassportId, request: Request) -> Response:
    from services.media import passport_qr

    p = resolve(passport_id)
    body = passport_qr.svg(_qr_text(request, p.id), title=f"PartSmith passport {p.id}: {p.title}")
    return Response(body, media_type="image/svg+xml", headers={"Cache-Control": QR_CACHE,
                    "Content-Disposition": f'inline; filename="passport-{p.id}.svg"'})  # fmt: skip


@router.get("/passport/{passport_id}/qr.png", summary="QR code to /p/{id} (PNG)", tags=["registry"])
def passport_qr_png(passport_id: PassportId, request: Request) -> Response:
    from services.media import passport_qr

    p = resolve(passport_id)
    return Response(passport_qr.png(_qr_text(request, p.id)), media_type="image/png", headers={
        "Cache-Control": QR_CACHE, "Content-Disposition": f'inline; filename="passport-{p.id}.png"'})  # fmt: skip


# ------------------------------------------------------------------------------------------- the mark on bakes


def _differs(specs: Sequence[ParamSpec], base: Mapping[str, float], raw: Mapping[str, float]) -> list[str]:
    """Knobs where the request moves away from the values the passport stands for."""
    if not raw:
        return []
    want, _ = clamp({**base, **raw}, list(specs))
    have, _ = clamp(dict(base), list(specs))
    return sorted(k for k in raw if k in want and abs(float(want[k]) - float(have.get(k, want[k]))) > 1e-6)


def refused(pid: str, why: str) -> dict[str, Any]:
    return {"text": pid, "applied": False, "reason": why, "checks": []}


def part_mark(part: PartRecord, raw: Mapping[str, float]) -> tuple[str | None, dict[str, Any] | None]:
    """(id to deboss, refusal report). A variant at other knob values gets no mark: the id would bring back the
    published values, not the ones printed."""
    pid = PP.part_id(part)
    moved = _differs(part.params, values_of(part), raw)
    if moved:
        return None, refused(pid, "not marked: the knobs differ from the published part (" + ", ".join(moved[:4])
                             + "), so its passport would not bring this variant back")  # fmt: skip
    return pid, None


def job_mark(job_id: str, specs: Sequence[ParamSpec], base: Mapping[str, float],
             raw: Mapping[str, float]) -> tuple[str | None, dict[str, Any] | None]:  # fmt: skip
    pid = PP.job_id(job_id)
    moved = _differs(specs, base, raw)
    if moved:
        return None, refused(pid, "not marked: the knobs differ from the job's values (" + ", ".join(moved[:4])
                             + "), so its passport would not bring this variant back")  # fmt: skip
    return pid, None


def mark_header(report: Mapping[str, Any] | None) -> dict[str, str]:
    """`X-PartSmith-Passport: applied <id>` or `skipped <id>` on a marked download (ASCII only)."""
    if not report:
        return {}
    word = "applied" if report.get("applied") else "skipped"
    return {"X-PartSmith-Passport": f"{word} {report.get('text', '')}".encode("ascii", "replace").decode()}
