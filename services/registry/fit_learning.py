"""Coupon fit learning: tight / ok / loose on a printed fit-test coupon tunes one number per printer + material preset
and device — the clearance the fit preset adds to internal-fit knobs. Measured dimensions are never touched; only the
preset's `delta_mm` is replaced (see `presets.apply(..., delta_mm=)`).

Update rule (pure, bounded, deterministic):
- every feature report proposes `base + STEP_MM × direction × weight`, where `base` is the clearance in effect when it
  was reported (computed here, never sent by the client), direction tight = +1 / ok = 0 / loose = −1 (tight means the
  hole is too small, so it needs more clearance) and weight barely = 0.5 / unspecified = 1 / very = 2;
- every proposal is clamped to the preset's documented range (`presets.clearance_range`: delta ± 0.25 mm, ≥ 0);
- the learned clearance is the median of the newest `WINDOW` proposals, clamped again and rounded to 0.001 mm.
With no reports the preset's documented delta applies, labelled as such.
"""

from __future__ import annotations

import hashlib
import secrets
import statistics
import threading
from collections.abc import Sequence
from typing import Literal

from pydantic import BaseModel, Field

from services.registry import presets
from services.registry.store import Registry

STEP_MM = 0.05
WINDOW = 15
WEIGHTS = {"barely": 0.5, "": 1.0, "very": 2.0}
DIRECTIONS = {"tight": 1.0, "ok": 0.0, "loose": -1.0}
RULE = (
    f"each feature report proposes the clearance in effect ± {STEP_MM:g} mm (tight: more, loose: less; barely ×0.5, "
    f"very ×2, ok: no change), clamped to the preset's range; the learned clearance is the median of the newest "
    f"{WINDOW} proposals. Only the clearance knob changes, never a measured dimension."
)

Fit = Literal["tight", "ok", "loose"]
Amount = Literal["barely", "very"]
SESSION_PATTERN = r"^[A-Za-z0-9_-]{8,64}$"

_lock = threading.Lock()


class CouponFeatureReport(BaseModel):
    feature: str = Field(min_length=1, max_length=64, description="Mating feature id, e.g. hole_1 or slot")
    fit: Fit
    amount: Amount | None = Field(None, description="Optional: how tight / loose (barely or very)")


class CouponReportRequest(BaseModel):
    preset: str = Field(description="Fit preset id (GET /presets), e.g. pla-fdm-0.4")
    session: str = Field(pattern=SESSION_PATTERN, description="Random device id kept in the browser; no account")
    features: list[CouponFeatureReport] = Field(min_length=1, max_length=8)
    job_id: str | None = Field(None, max_length=64)
    slug: str | None = Field(None, max_length=120)


class CouponReportOut(BaseModel):
    feature: str
    fit: Fit
    amount: str
    base_mm: float
    proposal_mm: float
    created_at: float


class LearnedClearance(BaseModel):
    """The clearance a preset applies on one device: learned from coupon reports, or the documented starting point."""

    preset: str
    title: str
    material: str
    process: str
    preset_clearance_mm: float
    clearance_mm: float
    range_mm: tuple[float, float]
    source: Literal["learned", "preset"]
    reports: int = Field(description="Coupon submissions in the window")
    feature_reports: int = Field(description="Feature reports in the window (the median is over these)")
    label: str
    rule: str = RULE
    recent: list[CouponReportOut] = Field(default_factory=list)


# ------------------------------------------------------------------------------------------------- pure core


def _clamp(value_mm: float, preset: presets.Preset) -> float:
    lo, hi = presets.clearance_range(preset)
    return round(min(hi, max(lo, value_mm)), 3)


def proposal(base_mm: float, fit: str, amount: str | None, preset: presets.Preset) -> float:
    """What one feature report asks the clearance to become (clamped to the preset's range)."""
    step = STEP_MM * DIRECTIONS[fit] * WEIGHTS[amount or ""]
    return _clamp(base_mm + step, preset)


def learned_value(proposals_newest_first: Sequence[float], preset: presets.Preset) -> float:
    """Median of the newest WINDOW proposals, clamped; the preset's delta when there are none."""
    window = list(proposals_newest_first)[:WINDOW]
    if not window:
        return preset.delta_mm
    return _clamp(float(statistics.median(window)), preset)


def device_key(session: str) -> str:
    """Stored instead of the raw device id."""
    return hashlib.sha256(f"partsmith-coupon:{session}".encode()).hexdigest()[:32]


def label(source: str, reports: int) -> str:
    if source == "preset":
        return "documented starting point (no coupon reports yet)"
    return f"learned from {reports} coupon report{'s' if reports != 1 else ''}"


# ------------------------------------------------------------------------------------------------- registry IO


def learned(reg: Registry, preset_id: str, session: str | None) -> LearnedClearance:
    """KeyError for an unknown preset id. Without a session: the preset's documented clearance."""
    preset = presets.BY_ID[preset_id]
    rows = reg.coupon_reports(preset_id, device_key(session))[:WINDOW] if session else []
    value = learned_value([r["proposal_mm"] for r in rows], preset)
    source: Literal["learned", "preset"] = "learned" if rows else "preset"
    submissions = len({r["report_id"] for r in rows})
    return LearnedClearance(
        preset=preset.id,
        title=preset.title,
        material=preset.material,
        process=preset.process,
        preset_clearance_mm=preset.delta_mm,
        clearance_mm=value,
        range_mm=presets.clearance_range(preset),
        source=source,
        reports=submissions,
        feature_reports=len(rows),
        label=label(source, submissions),
        recent=[
            CouponReportOut(
                feature=r["feature"],
                fit=r["fit"],
                amount=r["amount"],
                base_mm=r["base_mm"],
                proposal_mm=r["proposal_mm"],
                created_at=r["created_at"],
            )
            for r in rows[:10]
        ],
    )


def record(reg: Registry, req: CouponReportRequest) -> tuple[str, LearnedClearance]:
    """Store one coupon submission and return (report id, the new learned clearance). KeyError for an unknown preset."""
    preset = presets.BY_ID[req.preset]
    rid = "cr_" + secrets.token_hex(5)
    with _lock:  # base = the clearance in effect right now; read and insert together
        base = learned(reg, req.preset, req.session).clearance_mm
        rows = [
            {
                "report_id": rid,
                "preset": preset.id,
                "device": device_key(req.session),
                "feature": f.feature,
                "fit": f.fit,
                "amount": f.amount or "",
                "base_mm": base,
                "proposal_mm": proposal(base, f.fit, f.amount, preset),
                "job_id": req.job_id,
                "slug": req.slug,
            }
            for f in req.features
        ]
        reg.add_coupon_reports(rows)
    return rid, learned(reg, req.preset, req.session)


def learned_all(reg: Registry, session: str | None) -> list[LearnedClearance]:
    return [learned(reg, p.id, session) for p in presets.PRESETS]
