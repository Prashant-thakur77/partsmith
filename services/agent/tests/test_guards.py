import pytest
from partsmith_schemas.verification import FeatureResidual, ParamSpec

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
    assert "a run that passed verification" in c[0].rule


def test_lesson_wording_follows_the_job_status():
    its = [{"iter": 2, "edits": [{"param": "corner_radius", "from": 3.0, "to": 4.2}]}]
    c = lessons.extract_candidates(
        job_id="j",
        family="cover",
        template="battery_cover",
        first_values={"corner_radius": 3.0},
        final_values={"corner_radius": 4.2},
        iterations=its,
        verified=False,
        strategy_switches=[],
        max_error_mm=4.8,
        origin="synthetic",
    )
    knob = next(x for x in c if x.evidence.get("param") == "corner_radius")
    assert "verified" not in knob.rule and "best effort (max gap 4.80 mm)" in knob.rule
    assert "not confirmed" in knob.rule


def test_rescale_backed_by_each_measured_residual_is_allowed():
    edits = [{"param": "length", "to": 41.0}, {"param": "width", "to": 20.5}]
    deltas = {"length": -1.0, "width": -0.5}  # model smaller than measured on both, by exactly these amounts
    g = guards.guard_edits(edits, SPECS, VALUES, outline_params=["length", "width"], residual_deltas=deltas)
    assert len(g.applied) == 2
    g = guards.guard_edits(edits, SPECS, VALUES, outline_params=["length", "width"], residual_deltas={"length": -1.0})
    assert not g.applied


def test_flexible_and_organic_objects_are_refused_with_plain_reasons():
    assert guards.refused_class("Replace this soft silicone rubber gasket ring.") == guards.FLEXIBLE
    assert guards.refused_class("the O-ring of my pressure cooker lid") == guards.FLEXIBLE
    assert guards.refused_class("Make a copy of this little clay figurine.") == guards.ORGANIC
    assert "TPU" in guards.refusal_message(guards.FLEXIBLE)
    assert "free-form" in guards.refusal_message(guards.ORGANIC)
    # rigid parts that merely mention nearby things are not refused
    for ok in ("battery cover of my kid's toy car", "the knob is sealed"):
        assert guards.refused_class(ok) is None, ok


# ---- pinned knobs: a passing measured size is not traded away unless the round's evidence points at it ------------
HOOK_MAP = {"length": "length", "width": "width", "hole_1.diameter": "hole_d", "side.thickness": "reach"}


def _res(fid: str, q: str, measured: float, model: float, tol: float = 0.3) -> FeatureResidual:
    d = model - measured
    return FeatureResidual(feature_id=fid, quantity=q, measured_mm=measured, model_mm=model, delta_mm=d, tol_mm=tol,
                           passed=abs(d) <= tol)  # fmt: skip


# the recorded wall hook's round-5 residuals (j_261029_5e9d54d1): length passes, hole_2's position does not
HOOK_RESIDUALS = [
    _res("outline", "length", 49.829, 49.809),
    _res("outline", "width", 22.272, 22.459),
    _res("hole_1", "diameter", 3.91, 3.854, 0.15),
    _res("hole_2", "center_x", -8.957, -9.848),
    _res("side", "thickness", 39.751, 39.931),
]


def test_knobs_whose_measured_size_passes_are_pinned_unless_evidence_points_at_them():
    pins = guards.pinned_knobs(HOOK_RESIDUALS, HOOK_MAP)
    assert set(pins) == {"length", "width", "hole_d", "reach"}
    assert pins["length"] == guards.Pin("length", 49.829, 49.809, 0.3)
    assert pins["hole_d"].quantity == "hole 1 diameter"
    # the worst spot of a failing view inside a knob's template region is evidence for that knob
    assert "reach" not in guards.pinned_knobs(HOOK_RESIDUALS, HOOK_MAP, pointed=["reach"])
    # a failing size is evidence too: that knob is not pinned at all
    failing = [_res("outline", "length", 49.829, 53.01), *HOOK_RESIDUALS[1:]]
    assert "length" not in guards.pinned_knobs(failing, HOOK_MAP)
    # every size a knob controls must pass (a wheel's diameter sets both length and width)
    wheel = {"length": "diameter", "width": "diameter"}
    assert "diameter" not in guards.pinned_knobs(
        [_res("outline", "length", 62, 62.1), _res("outline", "width", 62, 62.5)], wheel
    )


def test_a_pinned_length_is_not_shortened_out_of_its_tolerance():
    specs = [_spec("length", 60.0, 36.0, 120.0), _spec("tip_length", 14.0, 3.0, 40.0)]
    values = {"length": 44.8, "tip_length": 14.0}
    pins = guards.pinned_knobs(HOOK_RESIDUALS, HOOK_MAP)
    g = guards.guard_edits(
        [{"param": "length", "to": 42.8}, {"param": "tip_length", "to": 13.0}], specs, values, pinned=pins
    )
    assert [e.param for e in g.applied] == ["tip_length"]  # only the pinned knob's edit is refused
    assert g.rejected[0].startswith("length: pinned — its size test passes (model 49.81 mm vs measured length 49.83")
    assert "nothing in this round's evidence points at it" in g.rejected[0]
    # a move that keeps the size inside its tolerance is harmless and allowed
    g2 = guards.guard_edits([{"param": "length", "to": 45.0}], specs, values, pinned=pins)
    assert [(e.param, e.to) for e in g2.applied] == [("length", 45.0)]
    # without pins (a reviewer round, or a failing size) the same edit goes through, step-capped as before
    g3 = guards.guard_edits([{"param": "length", "to": 42.8}], specs, values)
    assert [(e.param, e.to) for e in g3.applied] == [("length", 42.8)]
