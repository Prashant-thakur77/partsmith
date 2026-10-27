import pytest
from partsmith_schemas.verification import ParamSpec

from services.agent import guards, lessons


def _spec(
    name: str, default: float, lo: float, hi: float, step: float = 0.1, unit: str = "mm", topology: bool = False
) -> ParamSpec:
    return ParamSpec(name=name, default=default, min=lo, max=hi, step=step, unit=unit, topology=topology)


SPECS = [
    _spec("length", 40.0, 10.0, 120.0),
    _spec("width", 20.0, 5.0, 60.0),
    _spec("hole_d", 4.2, 2.0, 8.0, 0.05),
    _spec("hole_count", 2, 1, 4, 1, "", True),
    _spec("angle", 30.0, 0.0, 90.0, 1.0, "deg"),
]
VALUES = {"length": 40.0, "width": 20.0, "hole_d": 4.2, "hole_count": 2, "angle": 30.0}


def test_unknown_param_rejected_with_closest_names():
    g = guards.guard_edits([{"param": "hole_dia", "to": 5.0}], SPECS, VALUES)
    assert not g.applied
    assert "unknown parameter 'hole_dia'" in g.rejected[0] and "hole_d" in g.rejected[0]


def test_clamp_and_snap_to_range():
    g = guards.guard_edits([{"param": "hole_d", "to": 1.0}], SPECS, {**VALUES, "hole_d": 2.3})
    assert [e.param for e in g.applied] == ["hole_d"]
    assert g.applied[0].to == pytest.approx(2.0)
    assert "clamped" in g.applied[0].reason and g.applied[0].limited


def test_delta_cap_per_round():
    # 20 % of 40 mm is 8 mm, capped at 2 mm per round
    g = guards.guard_edits([{"param": "length", "to": 55.0, "reason": "residual"}], SPECS, VALUES)
    assert g.applied[0].to == pytest.approx(42.0)
    assert "capped" in g.applied[0].reason
    # small values: 20 % or at least 0.5 mm
    g = guards.guard_edits([{"param": "hole_d", "to": 6.0}], SPECS, VALUES)
    assert g.applied[0].to == pytest.approx(4.2 + 0.84, abs=0.03)
    # topology knobs move by one per round
    g = guards.guard_edits([{"param": "hole_count", "to": 4}], SPECS, VALUES)
    assert g.applied[0].to == 3.0
    # degrees: at most 10 per round
    g = guards.guard_edits([{"param": "angle", "to": 80}], SPECS, VALUES)
    assert g.applied[0].to == pytest.approx(40.0)


def test_whole_outline_rescale_is_refused():
    edits = [{"param": "length", "to": 41.0}, {"param": "width", "to": 20.5}]
    g = guards.guard_edits(edits, SPECS, VALUES, outline_params=["length", "width"])
    assert not g.applied and "never rescale" in g.rejected[0]
    # changing one outline knob (or both by different factors) is fine
    g = guards.guard_edits(
        [{"param": "length", "to": 41.0}, {"param": "width", "to": 20.2}],
        SPECS,
        VALUES,
        outline_params=["length", "width"],
    )
    assert len(g.applied) == 2


def test_no_op_and_non_numeric_edits_rejected():
    g = guards.guard_edits([{"param": "length", "to": 40.0}, {"param": "width", "to": "wide"}], SPECS, VALUES)
    assert not g.applied and len(g.rejected) == 2


def test_extract_code_and_refusals():
    assert guards.extract_code("here:\n```python\nimport math\nx = 1\n```\nbye") == "import math\nx = 1\n"
    assert guards.extract_code("x = 2") == "x = 2\n"
    assert guards.refused_class("a trigger for my airsoft gun") == "firearm or weapon component"
    assert guards.refused_class("seat belt buckle clip") == "vehicle safety system"
    assert guards.refused_class("cupboard turn button latch") is None


def test_lesson_candidates_only_from_measured_changes():
    its = [{"iter": 2, "edits": [{"param": "corner_radius", "from": 3.0, "to": 4.2}]}]
    c = lessons.extract_candidates(
        job_id="j",
        family="cover",
        template="battery_cover",
        first_values={"corner_radius": 3.0, "length": 56.0},
        final_values={"corner_radius": 4.2, "length": 56.0},
        iterations=its,
        verified=True,
        strategy_switches=[],
        max_error_mm=0.3,
        origin="synthetic",
    )
    assert len(c) == 1 and c[0].scope == "cover" and "corner_radius" in c[0].rule
    assert c[0].evidence["origin"] == "synthetic"


def test_rescale_backed_by_each_measured_residual_is_allowed():
    edits = [{"param": "length", "to": 41.0}, {"param": "width", "to": 20.5}]
    deltas = {"length": -1.0, "width": -0.5}  # model smaller than measured on both, by exactly these amounts
    g = guards.guard_edits(edits, SPECS, VALUES, outline_params=["length", "width"], residual_deltas=deltas)
    assert len(g.applied) == 2
    g = guards.guard_edits(edits, SPECS, VALUES, outline_params=["length", "width"], residual_deltas={"length": -1.0})
    assert not g.applied
