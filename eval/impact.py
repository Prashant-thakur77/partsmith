"""Impact log totals from data/impact/sessions.yaml (real repair sessions, entered by hand, never invented).

Each session: who/where/what was repaired, the replacement's market price with its source URL (or "not stocked"),
the PartSmith run id (time to verified is read from that run's events), the fit result and the printed grams.
Money is in rupees; grams → ₹ uses the `rupees_per_gram` stated in the YAML. Empty log → "pending".

    uv run python -m eval.impact
"""

from __future__ import annotations

import datetime as dt
import gzip
import json
import math
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

REPO = Path(__file__).resolve().parents[1]
SESSIONS = REPO / "data" / "impact" / "sessions.yaml"
REPORTS = REPO / "eval" / "reports"
FitResult = Literal["fits", "tight", "loose", "failed", "not_tested"]


class Session(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session: str
    date: dt.date
    place: str
    part: str
    appliance: str
    replacement_price_inr: float | None = None  # None when the part is not sold separately
    price_source: str  # URL of the listing, or "not stocked"
    run_id: str | None = None  # PartSmith job id
    fit_result: FitResult = "not_tested"
    print_grams: float | None = None
    notes: str = ""


class ImpactLog(BaseModel):
    model_config = ConfigDict(extra="forbid")

    currency: Literal["INR"] = "INR"
    rupees_per_gram: float | None = None  # filament cost stated by the person keeping the log (₹/g)
    rupees_per_gram_source: str = ""
    sessions: list[Session] = Field(default_factory=list)


def load(path: Path = SESSIONS) -> ImpactLog:
    if not path.exists():
        return ImpactLog()
    return ImpactLog.model_validate(yaml.safe_load(path.read_text()) or {})


def _run_events(run_id: str) -> list[dict[str, Any]] | None:
    from services.common.paths import runs_dir

    for base in (runs_dir(), REPO / "data" / "replays"):
        p = base / run_id / "run.jsonl"
        if p.exists():
            return [json.loads(line) for line in p.read_text().splitlines() if line.strip()]
    for p in (REPO / "eval" / "runs").glob("*/*/*/*/run.jsonl.gz"):
        with gzip.open(p, "rt", encoding="utf-8") as fh:
            evs = [json.loads(line) for line in fh]
        if evs and evs[0].get("job") == run_id:
            return evs
    return None


def time_to_verified_s(events: Sequence[dict[str, Any]]) -> float | None:
    """Seconds from the first event to a verified `done` event (None when the run never verified)."""
    if not events:
        return None
    done = next((e for e in events if e.get("t") == "done" and e.get("verified")), None)
    if done is None:
        return None
    return float(done["ts"]) - float(events[0]["ts"])


def totals(log: ImpactLog) -> dict[str, Any]:
    if not log.sessions:
        return {"status": "pending", "note": "no sessions logged yet (data/impact/sessions.yaml)", "n_sessions": 0}
    rows: list[dict[str, Any]] = []
    for s in log.sessions:
        ev = _run_events(s.run_id) if s.run_id else None
        ttv = time_to_verified_s(ev) if ev else None
        cost = s.print_grams * log.rupees_per_gram if (s.print_grams is not None and log.rupees_per_gram) else None
        saved = s.replacement_price_inr - cost if (s.replacement_price_inr is not None and cost is not None) else None
        rows.append(
            {
                "session": s.session,
                "date": s.date.isoformat(),
                "place": s.place,
                "part": s.part,
                "appliance": s.appliance,
                "replacement_price_inr": s.replacement_price_inr,
                "price_source": s.price_source,
                "run_id": s.run_id,
                "run_found": ev is not None,
                "time_to_verified_s": ttv,
                "fit_result": s.fit_result,
                "print_grams": s.print_grams,
                "print_cost_inr": cost,
                "saved_inr": saved,
            }
        )
    priced = [r for r in rows if r["replacement_price_inr"] is not None]
    ttvs = [r["time_to_verified_s"] for r in rows if r["time_to_verified_s"] is not None]
    costs = [r["print_cost_inr"] for r in rows if r["print_cost_inr"] is not None]
    saved_list = [float(r["saved_inr"]) for r in rows if r["saved_inr"] is not None]
    return {
        "status": "ok",
        "currency": log.currency,
        "rupees_per_gram": log.rupees_per_gram,
        "rupees_per_gram_source": log.rupees_per_gram_source,
        "n_sessions": len(rows),
        "n_fits": sum(r["fit_result"] == "fits" for r in rows),
        "n_not_stocked": sum(r["price_source"].strip().lower() == "not stocked" for r in rows),
        "replacement_value_inr": sum(r["replacement_price_inr"] for r in priced),
        "print_cost_inr": sum(costs) if costs else None,
        "saved_inr": sum(saved_list) if saved_list else None,
        "median_time_to_verified_s": sorted(ttvs)[len(ttvs) // 2] if ttvs else None,
        "sessions": rows,
    }


def fmt(v: float | None) -> str:
    return "–" if v is None or (isinstance(v, float) and math.isnan(v)) else f"{v:,.0f}"


def to_markdown(t: dict[str, Any]) -> str:
    L = ["# Impact log", ""]
    if t["status"] != "ok":
        return "\n".join([*L, f"**pending** — {t['note']}.", ""])
    L.append(
        f"{t['n_sessions']} sessions · {t['n_fits']} fit · {t['n_not_stocked']} parts not stocked · replacement value "
        f"₹{fmt(t['replacement_value_inr'])} · print cost ₹{fmt(t['print_cost_inr'])} at ₹{t['rupees_per_gram']}/g "
        f"({t['rupees_per_gram_source'] or 'source not given'}) · saved ₹{fmt(t['saved_inr'])}"
    )
    L += [
        "",
        "| session | date | part | appliance | price ₹ | source | time to verified | fit |",
        "|---|---|---|---|---:|---|---:|---|",
    ]
    for r in t["sessions"]:
        ttv = "–" if r["time_to_verified_s"] is None else f"{r['time_to_verified_s'] / 60:.1f} min"
        L.append(
            f"| {r['session']} | {r['date']} | {r['part']} | {r['appliance']} | {fmt(r['replacement_price_inr'])} | "
            f"{r['price_source']} | {ttv} | {r['fit_result']} |"
        )
    return "\n".join([*L, ""])


def main(argv: Sequence[str] | None = None) -> int:
    t = totals(load())
    out = REPORTS / dt.date.today().isoformat()
    out.mkdir(parents=True, exist_ok=True)
    (out / "impact.json").write_text(json.dumps(t, indent=1, default=str) + "\n")
    (out / "impact.md").write_text(to_markdown(t))
    (REPORTS / "latest").mkdir(parents=True, exist_ok=True)
    (REPORTS / "latest" / "impact.json").write_text(json.dumps(t, indent=1, default=str) + "\n")
    print("impact:", t["status"], f"({t['n_sessions']} sessions)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
