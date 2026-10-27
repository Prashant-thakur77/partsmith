"""Fixed failure taxonomy: every failed bench run gets exactly ONE category, by the first rule that matches.

Order (most specific cause first): refused → timeout → scale_fail → seg_fail → capture_reject → codegen_error →
topology_wrong → judge_veto → dim_off. The rules read only the run's own events and the scorer's comparison.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

CATEGORIES: tuple[str, ...] = (
    "seg_fail",  # no usable part mask (nothing found, or a mask the gate flags as not the part)
    "scale_fail",  # the mat could not give a scale (markers, reprojection, marker size)
    "capture_reject",  # any other capture-gate rejection (blur, glare, moiré, tilt, exposure, …)
    "codegen_error",  # no runnable / valid final part program
    "topology_wrong",  # holes or other features missing or extra in the final model
    "dim_off",  # the model exists and has the right features but a named dimension is off
    "timeout",  # wall-clock or cost cap stopped the run
    "refused",  # the job refused the part class
    "judge_veto",  # the judge's blocking veto stands on the final model
)
DESCRIPTIONS = {
    "seg_fail": "no usable part mask",
    "scale_fail": "no scale from the mat (markers / reprojection / marker size)",
    "capture_reject": "capture gate rejected the photo (blur, glare, moiré, tilt, exposure, contrast)",
    "codegen_error": "no runnable or valid final part program",
    "topology_wrong": "features missing or extra in the final model",
    "dim_off": "a named dimension is outside tolerance",
    "timeout": "wall-clock or cost cap reached",
    "refused": "the part class was refused",
    "judge_veto": "a blocking judge veto on the final model",
}
SCALE_CHECKS = {"markers", "reprojection", "scale"}


def failed_checks(summary: Mapping[str, Any]) -> list[str]:
    """Names of failed capture checks from a done-event summary (`capture` report), if any."""
    cap = summary.get("capture") or {}
    return [str(c.get("name")) for c in cap.get("checks") or [] if c.get("severity") == "fail"]


def classify(score: Mapping[str, Any], events: Sequence[Mapping[str, Any]] = ()) -> str | None:
    """Category of a failed run, or None when the run passed (pass@0.5)."""
    if score.get("pass_0_5"):
        return None
    status = str(score.get("status") or "")
    if status == "refused":
        return "refused"
    logs = " ".join(str(e.get("msg", "")) for e in events if e.get("t") == "log").lower()
    if status == "crashed" and "timeout" in str(score.get("failure", "")).lower():
        return "timeout"
    if "wall-clock cap" in logs or "cost cap" in logs:
        return "timeout"
    checks = set(score.get("failed_checks") or [])
    retake = str(score.get("retake_reason") or "").lower()
    if status == "failed":
        if checks & SCALE_CHECKS:
            return "scale_fail"
        if "contrast" in checks or "no part found" in retake:
            return "seg_fail"  # the mask is not the part (nothing found, or it blends into the stage)
        if not checks and ("markers" in retake or "the mat" in retake):
            return "scale_fail"
        if checks or retake:
            return "capture_reject"
    if not score.get("valid"):
        return "codegen_error"
    if score.get("missed") or score.get("extra_holes"):
        return "topology_wrong"
    if any(
        e.get("t") == "stage" and e.get("stage") == "judge" and "blocking" in str(e.get("label", "")) for e in events
    ) and not score.get("verified"):
        return "judge_veto"
    return "dim_off"


def counts(categories: Iterable[str | None]) -> dict[str, int]:
    """Count per category, every category listed (zeros included) in the fixed order."""
    c = Counter(x for x in categories if x is not None)
    return {k: int(c.get(k, 0)) for k in CATEGORIES}
