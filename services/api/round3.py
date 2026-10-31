"""Round-3 routes: the buy-or-print card for jobs and published parts, and a job's "fits where it goes" record.
Mounted by `services/api/main.py` with `app.include_router(round3.router)` under `/api/v1` (docs/API.md "Buy or
print", "Fits where it goes")."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Query
from partsmith_schemas import BuyOrPrint, MateFitResult
from pydantic import BaseModel, Field

from services.agent import buy_or_print as bop
from services.agent import mating
from services.api.common import API, _job
from services.api.errors import ApiError
from services.registry import fit_learning, presets
from services.registry import parts as P
from services.registry.store import get_registry
from services.verifier.mate_fit import PrinterFit, reprint

router = APIRouter(prefix=API)


class BuyOrPrintRequest(BaseModel):
    city: str | None = Field(None, max_length=80, description="optional: also look for print shops near this city")


def _card_json(card: BuyOrPrint) -> dict[str, Any]:
    return card.model_dump(mode="json")


def _provenance(job: Any, card: BuyOrPrint) -> dict[str, bool]:
    """How a stored card reached this answer. `recorded`: its lookup was played back (the job is a recorded run, or the
    lookup's own mode is "replay"); `stored`: it was read from storage, not searched for this request. Neither depends
    on the server's own provider mode, so a live job's stored card is never called a recorded run."""
    lk = card.lookup
    replay_job = bool(getattr(job.summary, "is_replay", False))
    return {"recorded": lk is not None and (replay_job or lk.mode == "replay"), "stored": lk is not None}


@router.get("/jobs/{job_id}/buy-or-print", tags=["jobs"])
def job_buy_or_print(job_id: str) -> dict[str, Any]:
    """The job's buy-or-print card. A job without a stored card gets the print side now (no lookup: a GET never
    starts a paid search); POST runs the lookup."""
    job = _job(job_id)
    card = bop.stored_card(job)
    if card is not None:
        return _card_json(card.model_copy(update=_provenance(job, card)))
    if not job.read_text("part.py"):
        raise ApiError(409, "no_program", "the job has no part program yet, so there is nothing to price")
    ver = job.read_json("verification.json") or {}
    title, _ = bop.job_title(job)
    return _card_json(
        bop.build_card(
            title=title, status=str(ver.get("status", "")), facts=bop.job_facts(job), lookup=None, job_id=job.id,
            notes=["no lookup ran for this card yet: POST this route to look up the original part"],
        )
    )  # fmt: skip


@router.post("/jobs/{job_id}/buy-or-print", tags=["jobs"])
def job_buy_or_print_lookup(job_id: str, body: BuyOrPrintRequest | None = None) -> dict[str, Any]:
    """Run the lookup (search grounding, cited items only) and store the card. The verification is never touched."""
    job = _job(job_id)
    if not job.finished:
        raise ApiError(409, "not_finished", "the job is still running; ask again when it is done")
    if not job.read_text("part.py"):
        raise ApiError(409, "no_program", "the job has no part program, so there is nothing to price")
    city = (body.city or "").strip() or None if body is not None else None
    return _card_json(bop.job_card(job, city=city))


@router.get("/parts/{slug}/buy-or-print", tags=["registry"])
def part_buy_or_print(slug: str) -> dict[str, Any]:
    """A published part's card: the print side from its facts, plus the lookup stored on the job it came from (if
    any). Never starts a search."""
    part = P.require_part(slug)
    st = part.verification.status if part.verification is not None else "unknown"
    lookup = None
    flags = {"recorded": False, "stored": False}
    notes: list[str] = []
    jid = part.provenance.job_id
    if jid:
        try:
            src = _job(jid)
        except ApiError:
            src = None
        stored = bop.stored_card(src) if src is not None else None
        lookup = stored.lookup if stored is not None else None
        if stored is not None and src is not None:
            flags = _provenance(src, stored)
    if lookup is None:
        notes.append("no stored lookup for this part: open its job's card to look up the original")
    facts = P.facts(part) if part.facts is not None else None
    card = bop.build_card(title=part.title, status=st, facts=facts, lookup=lookup, slug=part.slug, notes=notes)
    return _card_json(card.model_copy(update=flags))


@router.get("/jobs/{job_id}/mate-fit", tags=["jobs"])
def job_mate_fit(
    job_id: str,
    preset: Annotated[str | None, Query(description="Fit preset id (GET /presets); default: the job's own")] = None,
    fit_session: Annotated[
        str | None,
        Query(pattern=fit_learning.SESSION_PATTERN, description="Device id: the clearance its coupon reports taught"),
    ] = None,
) -> dict[str, Any]:
    """The job's mate_fit.json: the mates measured on its "where it fits" photo and how the model fits them. With
    `preset` and/or `fit_session` the "after printing on …" note is recomputed for that printer and device (the CAD
    and the measured mate never change). 404 when the job had no mating photo."""
    job = _job(job_id)
    data = job.read_json("mate_fit.json")
    if not data:
        raise ApiError(404, "no_mate_fit", "this job has no mating photo, so there is no fit to check")
    res = MateFitResult.model_validate(data)
    if (preset or fit_session) and res.fits:
        pid = preset or res.preset or mating.DEFAULT_PRESET
        if pid not in presets.BY_ID:
            raise ApiError(422, "unknown_preset", f"no fit preset {pid!r}", sorted(presets.BY_ID))
        lc = fit_learning.learned(get_registry(), pid, fit_session)
        printer = PrinterFit(pid, lc.title, lc.clearance_mm, lc.source, lc.label)
        fits = reprint(res.fits, printer, mating.has_fit_knobs(job.read_text("part.py") or ""))
        res = res.model_copy(update={"fits": fits, "preset": pid})
    return res.model_dump(mode="json")
