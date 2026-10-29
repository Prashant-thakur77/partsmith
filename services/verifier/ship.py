"""The single export gate: may this part's files leave the building?

`can_ship` is what the web app, the REST API and the MCP server all call before handing out STL/3MF/STEP files.
It trusts nothing but the numbers in the verification record and re-checks that they are consistent, so a record
that was edited (or a model that merely *says* "verified") cannot open the gate:

- verified, and its own numbers agree (every P0 test passed, every view within the stated thresholds, thresholds not
  loosened, a valid single watertight solid, hashes present) -> ok
- best effort -> requires an explicit acknowledgement; the reason names the worst problem in plain words and points
  at the fit-test coupon
- failed, invalid, inconsistent, or the job not finished -> blocked

When the mating photo's "fits where it goes" check says the part does not fit, the reason carries a warning; the
decision itself is unchanged (that check is informational, `verified` is about matching the broken part).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from partsmith_schemas.common import HAUSDORFF_PASS_MM, IOU_PASS
from partsmith_schemas.verification import Verification
from pydantic import ValidationError

COUPON_HINT = "Print the fit-test coupon first: it checks the critical holes and edges in a few minutes of printing."
REQUIRED_HASHES = ("code_sha256", "mesh_sha256")


@dataclass(frozen=True)
class ShipDecision:
    ok: bool
    reason: str
    requires_ack: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {"ok": self.ok, "reason": self.reason, "requires_ack": self.requires_ack}


def _inconsistencies(v: Verification) -> list[str]:
    """Ways in which a record claiming `verified` contradicts its own numbers."""
    out: list[str] = []
    if v.status != "verified":
        out.append(f"status is {v.status!r}")
    th = v.thresholds
    if th.hausdorff_mm > HAUSDORFF_PASS_MM + 1e-9 or th.iou < IOU_PASS - 1e-9:
        out.append("the pass thresholds were loosened")
    if not v.views:
        out.append("no measured view was compared")
    for vm in v.views:
        if vm.hausdorff_mm > min(th.hausdorff_mm, HAUSDORFF_PASS_MM) + 1e-9:
            out.append(f"the {vm.view} view is off by {vm.hausdorff_mm:.2f} mm")
    failed = [t.id for t in v.tests if t.priority == "P0" and not t.passed]
    if failed:
        out.append(f"P0 tests failed: {', '.join(failed[:4])}")
    if any(x.severity == "blocking" for x in v.vetoes):
        out.append("a blocking judge veto is present")
    val = v.validity
    if val is None or not (val.is_valid and val.single_solid and val.watertight and val.volume_mm3 > 0):
        out.append("the solid is not a valid single watertight body")
    missing = [h for h in REQUIRED_HASHES if not v.hashes.get(h)]
    if missing:
        out.append(f"provenance hashes missing ({', '.join(missing)})")
    return out


def worst_problem(v: Verification) -> str:
    """The single most important reason a part is best effort, in plain words."""
    bad = [r for r in v.residuals if not r.passed]
    if bad:
        r = max(bad, key=lambda r: abs(r.delta_mm) - r.tol_mm)
        d = r.delta_mm
        name = "the outline" if r.feature_id == "outline" else r.feature_id.replace("_", " ")
        if r.quantity in ("center_x", "center_y"):
            return f"{r.feature_id} is {abs(d):.1f} mm off its measured position"
        words = {
            "diameter": ("too large", "too small"),
            "length": ("too long", "too short"),
            "width": ("too wide", "too narrow"),
            "thickness": ("too thick", "too thin"),
            "depth": ("too deep", "too shallow"),
        }.get(r.quantity, ("too big", "too small"))
        what = r.feature_id if r.quantity in ("diameter", "depth") else f"{name} {r.quantity}"
        return f"{what} is {abs(d):.1f} mm {words[0] if d > 0 else words[1]}"
    for t in v.tests:
        if t.priority == "P0" and not t.passed:
            return f"test failed: {t.description}"
    off = [vm for vm in v.views if vm.hausdorff_mm > v.thresholds.hausdorff_mm]
    if off:
        vm = max(off, key=lambda m: m.hausdorff_mm)
        where = f" near ({vm.worst_point_mm[0]:.0f}, {vm.worst_point_mm[1]:.0f}) mm" if vm.worst_point_mm else ""
        return f"the {vm.view} outline differs from the photo by up to {vm.hausdorff_mm:.1f} mm{where}"
    if v.reasons:
        return str(v.reasons[0])
    return "the model does not match the measurements within tolerance"


FIT_TEST_PREFIX = "fit.mate."  # services/verifier/mate_fit.py: "fits where it goes" (P1, informational)


def fit_warning(v: Verification) -> str:
    """The " Warning: …" suffix when the mating photo says the part does not fit where it goes, else "". It never changes the
    decision (that check is informational); it makes the reason say so before anyone prints."""
    bad = [t for t in v.tests if t.id.startswith(FIT_TEST_PREFIX) and not t.passed and t.value is not None]
    if not bad:
        return ""
    what = bad[0].description.removeprefix("fits where it goes: ").removeprefix("does not fit: ")
    what = what.split("; after printing")[0]
    more = f" (and {len(bad) - 1} more)" if len(bad) > 1 else ""
    return f" Warning: it does not fit where it goes — {what}{more}."


def can_ship(
    verification: Verification | Mapping[str, Any] | None,
    *,
    job_status: str,
    acknowledged_best_effort: bool = False,
) -> ShipDecision:
    """Decide whether a job's files may be exported (see module docstring)."""
    if job_status in ("failed", "cancelled"):
        return ShipDecision(False, f"blocked: the job {job_status}; there is no part to export")
    if job_status != "done":
        return ShipDecision(False, "blocked: the job has not finished yet")
    if verification is None:
        return ShipDecision(False, "blocked: the part has not been verified")
    try:
        v = verification if isinstance(verification, Verification) else Verification.model_validate(verification)
    except ValidationError:
        return ShipDecision(False, "blocked: the verification record is malformed")

    if v.verified:
        problems = _inconsistencies(v)
        if problems:
            return ShipDecision(
                False, "blocked: the record says verified but its own numbers disagree — " + "; ".join(problems)
            )
        warn = fit_warning(v)
        ok = "verified: every measured dimension and view is within tolerance"
        return ShipDecision(True, ok + ("." + warn if warn else ""))
    if v.status == "verified":
        return ShipDecision(False, "blocked: the record is inconsistent (status verified, verified = false)")
    if v.status == "failed" or (v.validity is not None and not v.validity.is_valid):
        why = v.reasons[0] if v.reasons else "the program did not produce a valid solid"
        return ShipDecision(False, f"blocked: {why}")
    problem = worst_problem(v)
    warn = fit_warning(v)
    if acknowledged_best_effort:
        return ShipDecision(True, f"best effort, acknowledged: {problem}. {COUPON_HINT}{warn}", requires_ack=True)
    return ShipDecision(False, f"best effort: {problem}. {COUPON_HINT}{warn}", requires_ack=True)
