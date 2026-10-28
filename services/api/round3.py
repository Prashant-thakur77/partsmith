"""Round-3 routes: the buy-or-print card for jobs and published parts. Mounted by `services/api/main.py` with
`app.include_router(round3.router)` under `/api/v1` (docs/API.md "Buy or print")."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from partsmith_schemas import BuyOrPrint
from pydantic import BaseModel, Field

from services.agent import buy_or_print as bop
from services.api.common import API, _job
from services.api.errors import ApiError
from services.registry import parts as P

router = APIRouter(prefix=API)


class BuyOrPrintRequest(BaseModel):
    city: str | None = Field(None, max_length=80, description="optional: also look for print shops near this city")


def _card_json(card: BuyOrPrint) -> dict[str, Any]:
    return card.model_dump(mode="json")


@router.get("/jobs/{job_id}/buy-or-print", tags=["jobs"])
def job_buy_or_print(job_id: str) -> dict[str, Any]:
    """The job's buy-or-print card. A job without a stored card gets the print side now (no lookup: a GET never
    starts a paid search); POST runs the lookup."""
    job = _job(job_id)
    card = bop.stored_card(job)
    if card is not None:
        return _card_json(card)
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
    notes: list[str] = []
    jid = part.provenance.job_id
    if jid:
        try:
            src = _job(jid)
        except ApiError:
            src = None
        stored = bop.stored_card(src) if src is not None else None
        lookup = stored.lookup if stored is not None else None
    if lookup is None:
        notes.append("no stored lookup for this part: open its job's card to look up the original")
    card = bop.build_card(title=part.title, status=st, facts=part.facts, lookup=lookup, slug=part.slug, notes=notes)
    return _card_json(card)
