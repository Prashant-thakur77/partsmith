"""Describe it (plan checks, mock planner, number checks) and the playground presets. Mock providers, no network."""

from __future__ import annotations

from typing import Any

import pytest

from services.agent.templates import get_template, list_templates
from services.registry import describe as D
from services.registry import examples as E


def test_mock_plan_quotes_the_words_it_used() -> None:
    plan = D.mock_plan("a cable clip for a 6 mm cable, screws down with one M3 screw, 20 mm wide")
    assert plan["template"] == "cable_clip"
    by = {v["param"]: v for v in plan["values"]}
    assert by["cable_d"] == {**by["cable_d"], "value": 6.0, "source": "user", "quote": "for a 6 mm cable"}
    assert by["hole_d"]["value"] == 3.4 and "M3" in by["hole_d"]["note"] and by["hole_count"]["value"] == 1
    assert by["width"]["quote"] == "20 mm wide"
    assert D.mock_plan("a spacer 12 mm tall for an M3 screw")["values"][1]["param"] == "bore_d"
    assert D.mock_plan("something for my bicycle")["template"] == "none"


def test_pick_template_prefers_longer_phrases() -> None:
    assert D.pick_template("cable clip for my desk").name == "cable_clip"
    assert D.pick_template("a retaining clip for a 3 mm panel").name == "clip"
    assert D.pick_template("standoff for a pcb").name == "spacer"
    assert D.pick_template("a thing") is None


def test_check_plan_maps_names_clamps_and_downgrades_made_up_quotes() -> None:
    raw: dict[str, Any] = {
        "template": "cable_clips",
        "values": [
            {"param": "cable_dia", "value": 6, "source": "user", "quote": "6 mm cable", "note": ""},
            {"param": "width", "value": 99, "source": "user", "quote": "very wide", "note": ""},
            {"param": "length", "value": 50, "source": "user", "quote": "50 mm long", "note": ""},
            {"param": "colour", "value": 3, "source": "user", "quote": "", "note": ""},
            {"param": "wall", "value": "thick", "source": "inferred", "quote": "", "note": ""},
        ],
    }
    t, rows, notes = D.check_plan(raw, "A cable clip for a 6 mm  cable, very wide")
    assert t is not None and t.name == "cable_clip"
    by = {r["param"]: r for r in rows}
    assert by["cable_d"]["source"] == "user" and by["cable_d"]["value"] == 6.0  # "cable_dia" → cable_d
    assert by["width"]["value"] == 30.0 and by["width"]["asked"] == 99.0  # clamped, remembered
    assert by["length"]["source"] == "inferred" and "not in your description" in by["length"]["note"]
    assert by["wall"]["source"] == "default" and len(rows) == len(t.params)
    assert any("colour" in n for n in notes) and any("cable_clips" in n for n in notes)
    assert D.check_plan({"template": "none"}, "x")[0] is None
    assert D.check_plan({"template": "gearbox"}, "x")[0] is None


def test_questions_skip_given_numbers_and_hole_size_without_holes() -> None:
    t = get_template("cable_clip")
    _, rows, _ = D.check_plan({"template": "cable_clip", "values": []}, "")
    assert [q["param"] for q in D.questions_for(t, rows)] == ["length", "cable_d", "hole_d"]
    for r in rows:
        if r["param"] == "hole_count":
            r["value"] = 0.0
    assert [q["param"] for q in D.questions_for(t, rows)] == ["length", "cable_d"]


def _rows(template: str, **said: float) -> list[dict[str, Any]]:
    vals = [{"param": k, "value": v, "source": "user", "quote": f"{v} mm", "note": ""} for k, v in said.items()]
    text = " ".join(f"{v} mm" for v in said.values())
    return D.check_plan({"template": template, "values": vals}, text)[1]


def test_number_checks_measure_the_model_not_the_knob() -> None:
    t = get_template("cable_clip")
    rows = _rows("cable_clip", cable_d=6.0, length=40.0, hole_d=3.4)
    feats = {"size_mm": [40.0, 10.0, 7.7], "holes": [{"diameter_mm": 3.4}, {"diameter_mm": 3.4}],
             "plate_thickness_mm": 2.0, "interfaces": [{"id": "cable_channel", "gap_mm": 5.2}]}  # fmt: skip
    c = D.number_checks(t, rows, feats)
    by = {i["param"]: i for i in c["items"]}
    assert by["length"]["status"] == "met" and by["hole_d"]["status"] == "met"
    assert by["cable_d"]["status"] == "not_met" and by["cable_d"]["measured"] == 5.2
    assert c["status"] == "partial" and c["measured"] == 3 and "verif" not in c["label"].lower()
    rows = _rows("cable_clip", opening=0.8)
    assert D.number_checks(t, rows, feats)["items"][0]["status"] == "knob_only"
    assert D.number_checks(t, _rows("cable_clip"), feats)["status"] == "none"


def test_build_reports_a_number_the_template_cannot_reach() -> None:
    """The cable clip's program shrinks the channel to fit a short base: the check must say so."""
    rec: dict[str, Any] = {"template": "cable_clip", "values": _rows("cable_clip", cable_d=16.0, length=30.0)}
    D.build(rec)
    by = {i["param"]: i for i in rec["checks"]["items"]}
    assert by["length"]["status"] == "met"
    assert by["cable_d"]["status"] == "not_met" and by["cable_d"]["measured"] < 16.0
    assert rec["checks"]["status"] == "partial" and rec["print_plan"]["layer_mm"] == 0.2


@pytest.mark.parametrize("name", [t.name for t in list_templates()])
def test_presets_name_real_knobs_inside_their_ranges(name: str) -> None:
    t = get_template(name)
    presets = E.presets_for(name)
    assert 2 <= len(presets) <= 3 and len({p.id for p in presets}) == len(presets)
    specs = {p.name: p for p in t.params}
    for preset in presets:
        assert preset.values, preset.id
        for k, v in preset.values.items():
            assert k in specs, f"{name}/{preset.id}: unknown knob {k}"
            s = specs[k]
            assert s.min <= v <= s.max, f"{name}/{preset.id}: {k}={v} outside {s.min}..{s.max}"
            if s.topology:
                assert float(v).is_integer()


def test_template_cards_and_coupon_features() -> None:
    cards = E.all_cards()
    assert len(cards) == len(list_templates()) and all(c["presets"] for c in cards)
    feats = E.coupon_features(get_template("knob"), {})
    assert [(f.kind, f.diameter_mm, f.flat_depth_mm) for f in feats] == [("d_bore", 6.0, 1.5)]
    assert [f.kind for f in E.coupon_features(get_template("spacer"), {"flat_count": 2})] == ["hole"]
    assert E.coupon_features(get_template("cable_clip"), {"hole_count": 0}) == []
    assert E.coupon_code("battery_cover", {}) is None
    assert "PARAMS" in (E.coupon_code("cable_clip", {"hole_d": 3.4}) or "")


@pytest.mark.slow
@pytest.mark.parametrize("name", [t.name for t in list_templates()])
def test_every_preset_builds_in_the_sandbox(name: str) -> None:
    t = get_template(name)
    for preset in E.presets_for(name):
        out = E.bake_template(name, {**t.defaults, **preset.values}, ("view",))
        assert out.clamped == {} and out.files["view"].exists(), preset.id
