"""The one-line "why best effort" reason, built only from a verification record (hand-built TEST DATA records)."""

from __future__ import annotations

from partsmith_schemas.verification import FeatureResidual, JudgeVeto, PartTest, Verification, ViewMetrics

from services.verifier.ship import failing_view_gates, short_reason, worst_problem

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
    assert failing_view_gates(v) == ["the side view's mean contour distance is 0.20 mm (needs ≤ 0.15 mm)"]
    assert short_reason(v) == "the side view's mean contour distance is 0.20 mm (needs ≤ 0.15 mm)"
    assert worst_problem(v) == short_reason(v)  # the export gate no longer quotes the "refined by" line


def test_blocking_judge_veto_comes_first() -> None:
    v = _best_effort(vetoes=[JudgeVeto(feature="hole_1", issue="missing in the model", severity="blocking")])
    assert short_reason(v) == "the judge flagged hole_1: missing in the model"
