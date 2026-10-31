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

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from partsmith_schemas.common import HAUSDORFF_PASS_MM, IOU_PASS
from partsmith_schemas.verification import FeatureResidual, Verification
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
    """The single most important reason a part is best effort, in plain words. When the check that sets the headline
    max error failed, that check is named (so the number and the reason agree); otherwise the biggest failing residual,
    the first failed required test, the worst view, in that order."""
    head = _headline_failure(v, digits=1)
    if head is not None:
        return head
    bad = [r for r in v.residuals if not r.passed]
    if bad:
        return _residual_phrase(max(bad, key=lambda r: abs(r.delta_mm) - r.tol_mm), "the outline", 1)
    for t in v.tests:
        if t.priority == "P0" and not t.passed:
            return f"test failed: {t.description}"
    off = [vm for vm in v.views if vm.hausdorff_mm > v.thresholds.hausdorff_mm]
    if off:
        vm = max(off, key=lambda m: m.hausdorff_mm)
        where = f" near ({vm.worst_point_mm[0]:.0f}, {vm.worst_point_mm[1]:.0f}) mm" if vm.worst_point_mm else ""
        return f"the {vm.view} outline differs from the photo by up to {vm.hausdorff_mm:.1f} mm{where}"
    gates = failing_view_gates(v)
    if gates:
        return gates[0]
    if v.reasons:
        return str(v.reasons[0])
    return "the model does not match the measurements within tolerance"


# Two numbers "are" the headline when they agree to this many mm (max_error_mm is copied from one of them).
_HEADLINE_EPS_MM = 1e-6


def _view_phrase(view: str, hausdorff_mm: float, limit_mm: float, digits: int = 2) -> str:
    return f"the {view} outline is off by up to {hausdorff_mm:.{digits}f} mm (limit {limit_mm:.2f} mm)"


def _headline_failure(v: Verification, digits: int = 2) -> str | None:
    """The failing check whose value IS the record's max error (the number shown as the headline), in plain words;
    None when the max error comes from a check that passed (or there is none). `max_error_mm` is the worst of the
    views' outline gaps (Hausdorff) and the measured-size residuals (verify.py), so one of those set it."""
    top = v.max_error_mm
    if top is None:
        return None
    for vm in v.views:
        if abs(vm.hausdorff_mm - top) <= _HEADLINE_EPS_MM and vm.hausdorff_mm > v.thresholds.hausdorff_mm:
            return _view_phrase(vm.view, vm.hausdorff_mm, v.thresholds.hausdorff_mm, digits)
    for r in v.residuals:
        if abs(abs(r.delta_mm) - top) <= _HEADLINE_EPS_MM and not r.passed:
            return f"{_residual_phrase(r, 'the outline', digits)} (allowed ±{r.tol_mm:.2f} mm)"
    return None


def _residual_phrase(r: FeatureResidual, outline: str, digits: int) -> str:
    """ "the outline length is 0.4 mm too long" for a failed residual (model minus measured = `delta_mm`)."""
    d = r.delta_mm
    name = outline if r.feature_id == "outline" else r.feature_id.replace("_", " ")
    if r.quantity in ("center_x", "center_y"):
        return f"{r.feature_id} is {abs(d):.{digits}f} mm off its measured position"
    words = {
        "diameter": ("too large", "too small"),
        "length": ("too long", "too short"),
        "width": ("too wide", "too narrow"),
        "thickness": ("too thick", "too thin"),
        "depth": ("too deep", "too shallow"),
    }.get(r.quantity, ("too big", "too small"))
    what = r.feature_id if r.quantity in ("diameter", "depth") else f"{name} {r.quantity}"
    return f"{what} is {abs(d):.{digits}f} mm {words[0] if d > 0 else words[1]}"


# One gated number in a verifier view line: "mean contour distance 0.20 mm (needs <= 0.15 mm)", "IoU 0.965 (needs >= 0.97)".
_VIEW_GATE = re.compile(
    r"(?P<name>IoU|mean contour distance|Hausdorff|HD95)\s+(?P<val>\d+(?:\.\d+)?)(?P<unit> mm)?\s+"
    r"\(needs (?P<op><=|>=) (?P<lim>\d+(?:\.\d+)?)(?: mm)?\)"
)


# Plain words for the verifier's metric names (the record keeps the technical line in `reasons`).
_PLAIN_GATE = {
    "IoU": "overlap (IoU)",
    "mean contour distance": "average edge gap",
    "Hausdorff": "largest outline gap",
    "HD95": "95th-percentile outline gap",
}


def failing_view_gates(v: Verification) -> list[str]:
    """The gated view numbers that missed their limit, read from the verifier's own view lines (those ending
    "- fails"), in plain words, e.g. "the side view's average edge gap is 0.20 mm (needs ≤ 0.15 mm)"."""
    out: list[str] = []
    for line in v.reasons:
        if not line.rstrip().endswith("- fails") or " view" not in line:
            continue
        view = line.split(" view", 1)[0].strip()
        for m in _VIEW_GATE.finditer(line):
            val, lim = float(m["val"]), float(m["lim"])
            if (val > lim) if m["op"] == "<=" else (val < lim):
                unit = " mm" if m["unit"] else ""
                op = "≤" if m["op"] == "<=" else "≥"
                name = _PLAIN_GATE.get(m["name"], m["name"])
                out.append(f"the {view} view's {name} is {m['val']}{unit} (needs {op} {m['lim']}{unit})")
    return out


# Test ids whose failure is the same problem as a failed residual (verify.py writes both for one dimension).
_TEST_RESIDUAL = {"bbox.x": ("outline", "length"), "bbox.y": ("outline", "width"), "thickness": ("plate", "thickness")}


def _test_is_residual(test_id: str, bad: list[FeatureResidual]) -> bool:
    feat, _, qty = test_id.partition(".")
    target = _TEST_RESIDUAL.get(test_id) or (feat, qty)
    for r in bad:
        if r.feature_id != target[0]:
            continue
        if r.quantity == target[1] or (target[1] == "center" and r.quantity.startswith("center")):
            return True
    return False


def failing_checks(v: Verification) -> list[str]:
    """Every check that kept a best-effort record from passing, one plain line each, headline first: the failing check
    whose value is the record's max error (so the reason explains the number next to it), then judge vetoes, failed
    residuals (biggest overshoot first; a hole's x and y count once), failed required tests that are not already a
    residual, views over the outline-gap limit, then views failing only their overlap / average-edge-gap limit."""
    out: list[str] = []
    head = _headline_failure(v)
    if head is not None:
        out.append(head)

    def add(line: str) -> None:
        if line not in out:
            out.append(line)

    for x in v.vetoes:
        if x.severity == "blocking":
            add(f"the judge flagged {x.feature}: {x.issue}"[:140])
    bad = sorted((r for r in v.residuals if not r.passed), key=lambda r: abs(r.delta_mm) - r.tol_mm, reverse=True)
    seen_centres: set[str] = set()
    for r in bad:
        if r.quantity in ("center_x", "center_y"):
            if r.feature_id in seen_centres:
                continue
            seen_centres.add(r.feature_id)
        add(f"{_residual_phrase(r, 'the outline', 2)} (allowed ±{r.tol_mm:.2f} mm)")
    for t in v.tests:
        if t.priority == "P0" and not t.passed and not _test_is_residual(t.id, bad):
            name = re.split(r":| ==| \(", t.description, maxsplit=1)[0].strip() or t.id
            add(f"part test failed: {name}")
    off = sorted((vm for vm in v.views if vm.hausdorff_mm > v.thresholds.hausdorff_mm),
                 key=lambda m: m.hausdorff_mm, reverse=True)  # fmt: skip
    for vm in off:
        add(_view_phrase(vm.view, vm.hausdorff_mm, v.thresholds.hausdorff_mm))
    off_views = {vm.view for vm in off}
    for g in failing_view_gates(v):
        if not any(g.startswith(f"the {name} view") for name in off_views):
            add(g)
    return out


def short_reason(v: Verification | None) -> str | None:
    """One short line saying which check kept a best-effort part from passing, built only from its verification
    record. The first check named is the one that sets the headline max error when that check failed (a 4.70 mm
    outline gap is never explained by a 0.89 mm hole offset), then "(+N more)" for the other failing checks.
    None unless the record is best effort."""
    if v is None or v.verified or v.status != "best_effort":
        return None
    checks = failing_checks(v)
    if not checks:
        return worst_problem(v)
    more = f" (+{len(checks) - 1} more)" if len(checks) > 1 else ""
    return checks[0] + more


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
