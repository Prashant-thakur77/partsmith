"""The one-line "why best effort" reason, built only from a verification record (hand-built TEST DATA records)."""

from __future__ import annotations

from partsmith_schemas.verification import FeatureResidual, JudgeVeto, PartTest, Verification, ViewMetrics

from services.verifier.ship import failing_checks, failing_view_gates, short_reason, worst_problem

REFINED = "top: refined in the photo frame by +0.32 deg, (+0.00, -0.01) mm on the mat"
SIDE_FAILS = (
    "side view (photo frame): IoU 0.969 (not gated), mean contour distance 0.20 mm (needs <= 0.15 mm), "
    "Hausdorff 0.50 mm (needs <= 0.5 mm) (worst at x=-14.1, y=5.1 mm) - fails"
)


def _view(view: str, hd: float) -> ViewMetrics:
    return ViewMetrics(view=view, iou=0.98, hausdorff_mm=hd, hd95_mm=hd, mean_mm=hd / 2)


def _best_effort(**kw: object) -> Verification:
    return Verification(verified=False, status="best_effort", **kw)


def test_none_unless_best_effort() -> None:
    assert short_reason(None) is None
    assert short_reason(Verification(verified=True, status="verified")) is None
    assert short_reason(Verification(verified=False, status="failed", reasons=["policy error"])) is None


def test_failed_residual_names_the_dimension_and_tolerance() -> None:
    r = FeatureResidual(
        feature_id="outline",
        quantity="length",
        measured_mm=46.37,
        model_mm=46.75,
        delta_mm=0.38,
        tol_mm=0.3,
        passed=False,
    )
    v = _best_effort(residuals=[r], views=[_view("top", 0.43)])
    assert short_reason(v) == "the outline length is 0.38 mm too long (allowed ±0.30 mm)"


def test_failed_part_test_is_cut_to_its_name() -> None:
    p0 = {"value": 1.0, "expected": 0.0, "tol": 0.3, "passed": False}
    tests = [
        PartTest(id="bbox.x.height", description="length without a side view: the top photo reads 49.93 mm", **p0),
        PartTest(id="bbox.y.height", description="width without a side view: …", **p0),
        PartTest(id="fit.mate.x", description="informational", priority="P1", **p0),
    ]
    assert short_reason(_best_effort(tests=tests)) == "part test failed: length without a side view (+1 more)"


def test_view_over_the_hausdorff_limit() -> None:
    v = _best_effort(views=[_view("top", 0.2), _view("side", 0.63)])
    assert short_reason(v) == "the side outline is off by up to 0.63 mm (limit 0.50 mm)"


def test_view_gate_from_the_verifier_line_not_the_first_reason() -> None:
    v = _best_effort(views=[_view("side", 0.498)], reasons=[REFINED, SIDE_FAILS])
    assert failing_view_gates(v) == ["the side view's average edge gap is 0.20 mm (needs ≤ 0.15 mm)"]
    assert short_reason(v) == "the side view's average edge gap is 0.20 mm (needs ≤ 0.15 mm)"
    assert worst_problem(v) == short_reason(v)  # the export gate no longer quotes the "refined by" line


def test_blocking_judge_veto_comes_first() -> None:
    v = _best_effort(vetoes=[JudgeVeto(feature="hole_1", issue="missing in the model", severity="blocking")])
    assert short_reason(v) == "the judge flagged hole_1: missing in the model"


def _res(feature: str, qty: str, measured: float, model: float, tol: float = 0.3) -> FeatureResidual:
    d = model - measured
    return FeatureResidual(feature_id=feature, quantity=qty, measured_mm=measured, model_mm=model, delta_mm=d,
                           tol_mm=tol, passed=abs(d) <= tol)  # fmt: skip


def test_reason_names_the_check_that_sets_the_headline_max_error() -> None:
    """Wall hook (numbers from j_261029_5e9d54d1): the headline 4.70 mm is the side outline gap, so the reason leads
    with it, not with the 0.89 mm hole offset; the top view and the hole are the "+2 more"."""
    side = ViewMetrics(view="side", iou=0.875, hausdorff_mm=4.696413340954089, hd95_mm=4.0, mean_mm=1.0)
    top = ViewMetrics(view="top", iou=0.947, hausdorff_mm=1.8341119415365426, hd95_mm=1.5, mean_mm=0.5)
    hole_x = _res("hole_2", "center_x", -8.957, -9.847558672451182)
    hole_y = _res("hole_2", "center_y", 0.983, 1.0818506517274893)
    v = _best_effort(views=[top, side], residuals=[hole_x, hole_y], max_error_mm=4.696413340954089,
                     tests=[PartTest(id="hole_2.center", priority="P1", description="hole_2 centre", value=0.9,
                                    expected=0.0, tol=0.3, passed=False)])  # fmt: skip
    assert short_reason(v) == "the side outline is off by up to 4.70 mm (limit 0.50 mm) (+2 more)"
    assert failing_checks(v)[1:] == [
        "hole_2 is 0.89 mm off its measured position (allowed ±0.30 mm)",
        "the top outline is off by up to 1.83 mm (limit 0.50 mm)",
    ]
    assert worst_problem(v) == "the side outline is off by up to 4.7 mm (limit 0.50 mm)"


def test_cable_clip_outline_gap_leads_and_the_width_test_counts_once() -> None:
    """Cable clip (numbers from j_261029_1c3ea2b9): 1.76 mm side outline gap is the headline; the 0.32 mm narrow width
    is one more problem even though both a residual and the bbox.y test report it."""
    side = ViewMetrics(view="side", iou=0.901, hausdorff_mm=1.7612338122604754, hd95_mm=1.2, mean_mm=0.21)
    top = ViewMetrics(view="top", iou=0.959, hausdorff_mm=0.3173011833495405, hd95_mm=0.3, mean_mm=0.14)
    width = _res("outline", "width", 11.907, 11.583)
    bbox_y = PartTest(id="bbox.y", description="width (short side of the footprint) == 11.91 +/- 0.3 mm",
                      value=11.583, expected=11.907, tol=0.3, passed=False)  # fmt: skip
    v = _best_effort(views=[top, side], residuals=[width], tests=[bbox_y], max_error_mm=1.7612338122604754)
    assert short_reason(v) == "the side outline is off by up to 1.76 mm (limit 0.50 mm) (+1 more)"
    assert failing_checks(v)[1] == "the outline width is 0.32 mm too narrow (allowed ±0.30 mm)"


def test_a_failed_residual_that_is_the_max_error_leads() -> None:
    r = _res("hole_1", "diameter", 5.0, 5.6, tol=0.15)
    v = _best_effort(views=[_view("top", 0.3)], residuals=[r], max_error_mm=0.6)
    assert short_reason(v) == "hole_1 is 0.60 mm too large (allowed ±0.15 mm)"


def test_headline_from_a_passing_check_falls_back_to_the_failing_ones() -> None:
    """Max error 0.45 mm from a view within its limit: the reason is the check that actually failed."""
    v = _best_effort(views=[_view("side", 0.45)], reasons=[SIDE_FAILS], max_error_mm=0.45)
    assert short_reason(v) == "the side view's average edge gap is 0.20 mm (needs ≤ 0.15 mm)"


def test_judge_veto_follows_the_headline_failure() -> None:
    veto = JudgeVeto(feature="hole_1", issue="missing in the model", severity="blocking")
    v = _best_effort(views=[_view("side", 0.9)], vetoes=[veto], max_error_mm=0.9)
    assert short_reason(v) == "the side outline is off by up to 0.90 mm (limit 0.50 mm) (+1 more)"
    assert failing_checks(v)[1] == "the judge flagged hole_1: missing in the model"
