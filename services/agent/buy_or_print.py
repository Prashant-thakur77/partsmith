"""Buy-or-print card: printing costs computed by code from the part's mesh, next to cited offers for the original.

Print side (code only): solid volume x density -> grams (PLA 1.24, PETG 1.27 g/cm^3, the same densities as the part
facts; 100 % infill, so an upper bound), the part facts' print-time estimate, and filament cost at assumed spool
prices (below; labelled assumptions, not quotes). Buy side: `providers.buy_lookup` (search grounding, code keeps only
cited items). The card is stored as `buy_or_print.json` in the job folder; building it never reads or changes the
verification beyond copying its status.
"""

from __future__ import annotations

import os
import time
from collections.abc import Mapping
from typing import Any

from partsmith_schemas import BuyLookup, BuyOrPrint, PartFacts, PrintEstimate
from partsmith_schemas.commerce import Material

from services.agent import providers
from services.agent.jobs import Job
from services.geom_worker.bake import DENSITY_G_CM3, FACT_NOTES

CARD_FILE = "buy_or_print.json"
# Assumed retail price of a 1 kg filament spool (assumptions for the estimate, not quotes; change them here).
SPOOL_PRICE_PER_KG: dict[Material, dict[str, float]] = {
    "PLA": {"INR": 1200.0, "USD": 20.0},
    "PETG": {"INR": 1400.0, "USD": 22.0},
}
MATERIALS: tuple[Material, ...] = ("PLA", "PETG")


def print_estimates(facts: PartFacts) -> list[PrintEstimate]:
    """Grams, minutes and filament cost per material from the part facts (pure)."""
    out: list[PrintEstimate] = []
    for mat in MATERIALS:
        grams = facts.volume_mm3 / 1000.0 * DENSITY_G_CM3[mat]
        prices = SPOOL_PRICE_PER_KG[mat]
        out.append(
            PrintEstimate(
                material=mat,
                volume_mm3=round(facts.volume_mm3, 1),
                grams=round(grams, 2),
                print_minutes=round(facts.print_minutes_est, 1),
                filament_cost={cur: round(grams / 1000.0 * p, 2) for cur, p in prices.items()},
                price_per_kg=dict(prices),
                assumptions=[
                    f"grams: {FACT_NOTES['mass']}",
                    f"minutes: {FACT_NOTES['print_minutes_est']}",
                    "filament cost: grams x an assumed 1 kg spool price ("
                    + ", ".join(f"{cur} {p:g}/kg" for cur, p in prices.items())
                    + "); not a quote, and no shop margin or electricity",
                ],
            )
        )
    return out


def lookup_query(title: str, family: str | None, intent: str) -> str:
    """What to search for: the part's title and family, plus the user's own words when they name a product."""
    parts = [title.strip() or "replacement plastic part"]
    if family and family not in ("custom", "reference") and family.replace("_", " ") not in parts[0].lower():
        parts.append(f"({family.replace('_', ' ')})")
    if intent.strip():
        parts.append(f"— user: {intent.strip()[:200]}")
    return " ".join(parts)


def to_lookup(r: providers.BuyResult) -> BuyLookup:
    return BuyLookup.model_validate(
        {
            "query": r.query, "city": r.city, "oem": r.oem, "offers": r.offers, "places": r.places,
            "dropped": r.dropped, "searched": r.searched, "queries": r.queries, "mode": r.mode,
            "provider": r.provider, "model": r.model, "usd": r.usd, "label": r.label,
        }
    )  # fmt: skip


def build_card(
    *,
    title: str,
    status: str,
    facts: PartFacts | None,
    lookup: BuyLookup | None,
    job_id: str | None = None,
    slug: str | None = None,
    notes: list[str] | None = None,
) -> BuyOrPrint:
    notes = list(notes or [])
    if facts is None:
        notes.append("no mesh facts yet (the part was not exported), so no print estimate")
    if lookup is not None and lookup.mode == "mock":
        notes.append(f"{lookup.label}: no seller or price on this card came from the web")
    return BuyOrPrint(
        job_id=job_id,
        slug=slug,
        title=title,
        status=status if status in ("verified", "best_effort", "failed") else "unknown",
        prints=print_estimates(facts) if facts is not None else [],
        lookup=lookup,
        mode=lookup.mode if lookup is not None else "mock",
        created_at=time.time(),
        notes=notes,
    )


# ------------------------------------------------------------------------------------------------- jobs


def job_facts(job: Job) -> PartFacts | None:
    raw = job.read_json("facts.json")
    if raw:
        return PartFacts.model_validate(raw)
    code = job.read_text("part.py")
    if not code:
        return None
    from services.geom_worker.bake import BakeError, bake

    try:
        bo = bake(code, {k: float(v) for k, v in (job.read_json("values.json") or {}).items()}, ("stl",))
    except (BakeError, ValueError):
        return None
    if bo.facts is not None:
        job.write_json("facts.json", bo.facts)
    return bo.facts


def job_title(job: Job) -> tuple[str, str | None]:
    spec = job.read_json("partspec.json") or {}
    title = str(spec.get("title") or job.summary.title or "")
    return title, spec.get("family")


def lookup_enabled() -> bool:
    """`PARTSMITH_BUY_LOOKUP=0` skips the search-grounded lookup (benches set it: the card is not scored)."""
    return os.environ.get("PARTSMITH_BUY_LOOKUP", "1").strip() != "0"


def job_card(
    job: Job, *, city: str | None = None, lookup: bool = True, fixture: Mapping[str, Any] | None = None
) -> BuyOrPrint:
    """Build (and store) the job's card. The lookup's model_call event lands on the job; its cost counts there."""
    ver = job.read_json("verification.json") or {}
    title, family = job_title(job)
    city = city if city is not None else job.input.city
    found: BuyLookup | None = None
    notes: list[str] = []
    if lookup:
        query = lookup_query(title, family, job.input.intent)
        with providers.job_context(job.id, job.emit, ctx=job.ctx):
            found = to_lookup(providers.buy_lookup(query, city=city, fixture=fixture))
    else:
        notes.append("no lookup ran for this card yet")
    card = build_card(title=title, status=str(ver.get("status", "")), facts=job_facts(job), lookup=found,
                      job_id=job.id, notes=notes)  # fmt: skip
    job.write_json(CARD_FILE, card)
    return card


def stored_card(job: Job) -> BuyOrPrint | None:
    raw = job.read_json(CARD_FILE)
    return BuyOrPrint.model_validate(raw) if raw else None
