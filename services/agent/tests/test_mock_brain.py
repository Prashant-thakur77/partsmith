from typing import Any

import pytest
from partsmith_schemas.verification import ParamSpec

from services.agent import mock_brain
from services.agent.providers import ModelRequest
from services.agent.templates import get_template


def _top(L: float, W: float, holes: Any = (), area: float | None = None) -> dict[str, Any]:
    return {
        "length": {"value": L, "source": "measured", "sigma_mm": 0.05},
        "width": {"value": W, "source": "measured", "sigma_mm": 0.05},
        "area_mm2": area if area is not None else L * W,
        "outline_mm": [[-L / 2, -W / 2], [L / 2, -W / 2], [L / 2, W / 2], [-L / 2, W / 2]],
        "holes": [
            {
                "id": f"hole_{i + 1}",
                "center_mm": list(c),
                "diameter": {"value": d, "source": "measured", "sigma_mm": 0.03},
            }
            for i, (c, d) in enumerate(holes)
        ],
        "slots": [],
        "symmetry_score": 0.99,
    }


def test_template_choice_from_hint_words_and_shape():
    assert mock_brain.choose_template("", "latch", None)[0] == "cupboard_latch"
    assert mock_brain.choose_template("the knob of my cooker broke", None, None)[0] == "knob"
    round_top = _top(20.0, 20.0, [((0.0, 0.0), 8.0)], area=3.1416 * 100 - 3.1416 * 16)
    assert mock_brain.choose_template("", None, mock_brain.shape_cues(round_top))[0] == "spacer"
    plate = _top(56.0, 32.0)
    assert mock_brain.choose_template("", None, mock_brain.shape_cues(plate))[0] == "battery_cover"


def test_understand_marks_guesses_and_asks_for_thickness():
    top = _top(52.3, 16.3, [((10.0, 0.0), 4.6)])
    req = ModelRequest(messages=[], mock_context={"measurements": {"top": top}, "intent": "", "family_hint": "latch"})
    spec = mock_brain.understand(req)
    assert spec["template_hint"] == "cupboard_latch"
    assert spec["thickness"]["source"] == "inferred"
    assert [u["id"] for u in spec["unknowns"]] == ["thickness"]
    assert spec["features"][0]["diameter"]["value"] == 4.6 and spec["features"][0]["diameter"]["source"] == "measured"


def test_build_rounds_measured_values_and_leaves_the_rest_naive():
    t = get_template("cupboard_latch")
    spec = {"thickness": {"value": 6.0}}
    vals = mock_brain.template_values(t, spec, _top(52.32, 16.31, [((10.0, 0.0), 4.62)]), {})
    assert vals["length"] == 52.0 and vals["width"] == 16.0 and vals["pivot_d"] == 4.5 and vals["thickness"] == 6.0
    assert vals["pivot_offset"] == t.defaults["pivot_offset"]  # unmeasured → default; the loop has to find it


def _fix_ctx(residuals: Any, views: Any, values: Any, history: Any = ()) -> ModelRequest:
    t = get_template("battery_cover")
    return ModelRequest(
        messages=[],
        mock_context={
            "params": [p.model_dump() for p in t.params],
            "values": values,
            "measure_map": t.measure_map,
            "verification": {"residuals": residuals, "views": views, "tests": []},
            "history": list(history),
        },
    )


def _view(hd: float, iou: float = 0.99, over: float = 0.0, under: float = 0.0) -> dict[str, Any]:
    return {"view": "top", "hausdorff_mm": hd, "iou": iou, "over_area_mm2": over, "under_area_mm2": under}


def test_fix_moves_mapped_knob_against_residual_damped():
    t = get_template("battery_cover")
    vals = {**t.defaults, "width": 32.0}
    res = [
        {
            "feature_id": "outline",
            "quantity": "width",
            "measured_mm": 32.4,
            "model_mm": 32.0,
            "delta_mm": -0.4,
            "tol_mm": 0.3,
            "passed": False,
        }
    ]
    out = mock_brain.fix(_fix_ctx(res, [_view(0.6)], vals))
    assert out["edits"] == [
        {"param": "width", "from": 32.0, "to": pytest.approx(32.36), "reason": "residual -0.40 mm (damped)"}
    ]


def test_fix_probes_an_unmapped_knob_then_reverses():
    t = get_template("battery_cover")
    vals = dict(t.defaults)
    out = mock_brain.fix(_fix_ctx([], [_view(0.64, over=5.6, under=2.7)], vals))
    (e,) = out["edits"]
    assert e["param"] == "corner_radius" and e["to"] > vals["corner_radius"] and e["reason"].startswith("probe+")
    hist = [{"iter": 2, "edits": [e], "hd_before": 0.64, "hd_after": 0.80, "improved": False}]
    out2 = mock_brain.fix(_fix_ctx([], [_view(0.64, over=5.6, under=2.7)], vals, hist))
    (e2,) = out2["edits"]
    assert e2["param"] == "corner_radius" and e2["to"] < vals["corner_radius"] and e2["reason"].startswith("probe-")


def test_variant_mock_uses_phrase_mapper():
    params = [ParamSpec(name="hole_d", default=4.0, min=2.0, max=8.0, step=0.05, label="Screw hole")]
    req = ModelRequest(
        messages=[],
        mock_context={"want": "hole thoda bada", "params": [p.model_dump() for p in params], "values": {"hole_d": 4.0}},
    )
    out = mock_brain.variant(req)
    assert out["edits"] and out["edits"][0]["param"] == "hole_d"
