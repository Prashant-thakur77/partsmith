"""Segmentation confidence → measurement uncertainty, and when to ask for a retake.

SAM 3.1 reports a confidence ``c`` in [0, 1] per mask (``include_confidence``). A mask the model is unsure of has edges
we trust less, so every value measured from it gets a wider ±σ:

    σ_eff = σ × (1 + K × (1 − c)),   K = 2

monotone in ``c``: a sure mask (c = 1) keeps σ, c = 0.5 doubles it, c = 0 triples it. Below ``RETAKE_BELOW`` the
value is not used at all and the job asks for a retake of that feature or view, in plain words. Both constants are
stated choices (not fitted to any ground truth): K makes an even-odds mask carry twice the error, and 0.5 is where the
model says it is as likely wrong as right. The segmenter's own floor (masks under 0.4 are dropped) stays below it.

Only a model's confidence counts: a deterministic stand-in (threshold, flood fill) reports a score that is not a
probability, so callers pass ``None`` for those and nothing changes. Mock point masks carry a labelled proxy (edge
contrast, see ``services/agent/providers/mocks.py``) so the same path runs without keys.

This widens the reported uncertainty only. The verifier's pass thresholds never read σ, so a low confidence can
never loosen a test.
"""

from __future__ import annotations

from collections.abc import Callable

from partsmith_schemas.common import Evidence, Measured
from partsmith_schemas.measurement import Measurements

CONFIDENCE_K = 2.0
RETAKE_BELOW = 0.5
MODEL_MASK_SOURCES = ("sam-3.1", "sam3-open")


def sigma_for_confidence(sigma_mm: float, confidence: float | None) -> float:
    """σ widened for a mask of the given confidence (unchanged for None)."""
    if confidence is None:
        return sigma_mm
    c = min(max(float(confidence), 0.0), 1.0)
    return sigma_mm * (1.0 + CONFIDENCE_K * (1.0 - c))


def widen(m: Measured, confidence: float | None, label: str = "") -> Measured:
    """A copy of ``m`` with σ widened for the mask confidence and the confidence noted in its evidence."""
    if confidence is None:
        return m
    note = f"mask confidence {confidence:.2f}{f' ({label})' if label else ''}: ±σ × {1 + CONFIDENCE_K * (1 - confidence):.2f}"
    ev = m.evidence or Evidence()
    ev = ev.model_copy(update={"note": f"{ev.note}; {note}" if ev.note else note})
    return m.model_copy(update={"sigma_mm": round(sigma_for_confidence(m.sigma_mm, confidence), 3), "evidence": ev})


def widen_measurements(meas: Measurements, confidence: float | None, label: str = "") -> Measurements:
    """Every measured value of one view widened for its outline mask's confidence (length, width, a measured
    thickness, holes, slots). A user-stated thickness is not from the mask and keeps its σ."""
    if confidence is None:
        return meas
    w: Callable[[Measured], Measured] = lambda m: widen(m, confidence, label)  # noqa: E731
    upd: dict[str, object] = {"length": w(meas.length), "width": w(meas.width)}
    if meas.thickness is not None and meas.thickness.source.value == "measured":
        upd["thickness"] = w(meas.thickness)
    upd["holes"] = [h.model_copy(update={"diameter": w(h.diameter)}) for h in meas.holes]
    upd["slots"] = [s.model_copy(update={"length": w(s.length), "width": w(s.width)}) for s in meas.slots]
    return meas.model_copy(update=upd)


def retake_reason(what: str, confidence: float | None) -> str | None:
    """Plain words asking for a retake of ``what`` when the mask confidence is below ``RETAKE_BELOW``, else None."""
    if confidence is None or confidence >= RETAKE_BELOW:
        return None
    return (
        f"The segmenter is only {confidence:.0%} sure of {what} (glare, a shadow, a finger or a busy background "
        f"nearby?). Retake it closer, with even light and nothing else touching the part."
    )
