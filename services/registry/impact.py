"""Impact numbers for one job, computed only from what the job already has (docs/API.md `GET /jobs/{id}/impact`):

- minutes from upload to the first downloadable print file: the job's creation time to the first `stl` / `threemf` /
  `step` artifact event (event timestamps; a replay keeps its original run's timestamps);
- filament grams: the bake's own `mass_g_pla` (solid mesh volume × PLA density), else the verified mesh volume ×
  the same density. Solid volume at 100 % infill is an upper bound — a real print weighs less;
- filament cost: grams × an assumed spool price per kg. Every constant is listed in `assumptions`; every number
  here is labelled an estimate.
"""

from __future__ import annotations

import os
from collections.abc import Iterable, Mapping
from typing import Any

from services.geom_worker.bake import DENSITY_G_CM3

FILE_KINDS = ("stl", "threemf", "step")
# Assumed price of a 1 kg PLA spool (an assumption, not a quote). Override with the environment variables below.
SPOOL_PRICE_PER_KG = {"INR": 1200.0, "USD": 20.0}
SPOOL_ENV = {"INR": "PARTSMITH_PLA_INR_PER_KG", "USD": "PARTSMITH_PLA_USD_PER_KG"}


def spool_prices() -> dict[str, float]:
    out = {}
    for cur, default in SPOOL_PRICE_PER_KG.items():
        try:
            out[cur] = float(os.environ.get(SPOOL_ENV[cur], default))
        except ValueError:
            out[cur] = default
    return out


def minutes_to_file(created_at: float, events: Iterable[Any]) -> dict[str, Any] | None:
    """{"minutes","started_at","file_at","kind","waited_for_answer"} or None when no print file was produced."""
    answered = False
    first_ts: float | None = None
    for e in events:
        ts = float(getattr(e, "ts", 0.0) or 0.0)
        if first_ts is None and ts > 0:
            first_ts = ts
        if getattr(e, "t", "") == "answer":
            answered = True
        if getattr(e, "t", "") == "artifact" and getattr(e, "kind", "") in FILE_KINDS and ts > 0:
            start = created_at if 0 < created_at <= ts else (first_ts or ts)
            return {
                "minutes": round((ts - start) / 60.0, 2),
                "started_at": start,
                "file_at": ts,
                "kind": str(e.kind),
                "waited_for_answer": answered,
            }
    return None


def filament(facts: Mapping[str, Any] | None, volume_mm3: float | None) -> dict[str, Any] | None:
    """PLA grams from the bake facts (preferred) or the verified mesh volume; None when neither exists."""
    density = DENSITY_G_CM3["PLA"]
    if facts and isinstance(facts.get("mass_g_pla"), (int, float)) and facts["mass_g_pla"] > 0:
        vol = facts.get("volume_mm3")
        return {
            "material": "PLA",
            "grams": round(float(facts["mass_g_pla"]), 2),
            "volume_mm3": float(vol) if isinstance(vol, (int, float)) else None,
            "density_g_cm3": density,
            "source": "bake facts (mesh volume × density)",
        }
    if volume_mm3 is not None and volume_mm3 > 0:
        return {
            "material": "PLA",
            "grams": round(volume_mm3 / 1000.0 * density, 2),
            "volume_mm3": float(volume_mm3),
            "density_g_cm3": density,
            "source": "verified mesh volume × density",
        }
    return None


def job_impact(
    *,
    job_id: str,
    created_at: float,
    events: Iterable[Any],
    facts: Mapping[str, Any] | None,
    volume_mm3: float | None,
    replay: bool = False,
) -> dict[str, Any]:
    """The `/jobs/{id}/impact` payload. Fields are null when the job has no data for them — never a placeholder."""
    timing = minutes_to_file(created_at, events)
    fil = filament(facts, volume_mm3)
    prices = spool_prices()
    cost = (
        [
            {"currency": cur, "amount": round(fil["grams"] / 1000.0 * per_kg, 2), "price_per_kg": per_kg}
            for cur, per_kg in prices.items()
        ]
        if fil
        else []
    )
    print_min = facts.get("print_minutes_est") if facts else None
    assumptions = [
        f"PLA density {DENSITY_G_CM3['PLA']} g/cm³; solid volume at 100 % infill (an upper bound)",
        *(f"spool price {v:g} {c}/kg (assumed, set {SPOOL_ENV[c]})" for c, v in prices.items()),
    ]
    notes = []
    if timing and timing["waited_for_answer"]:
        notes.append("includes the time the job waited for your answer")
    if replay:
        notes.append("replay: times are from the original recorded run")
    return {
        "job_id": job_id,
        "label": "estimate",
        "minutes_to_file": timing,
        "filament": fil,
        "cost": cost,
        "print_minutes_est": float(print_min) if isinstance(print_min, (int, float)) else None,
        "assumptions": assumptions,
        "notes": notes,
        "replay": replay,
    }
