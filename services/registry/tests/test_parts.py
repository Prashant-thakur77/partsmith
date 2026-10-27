from __future__ import annotations

import io

import numpy as np
import pytest
from partsmith_schemas.verification import ParamSpec
from PIL import Image

from services.agent.templates import get_template
from services.common import blobs
from services.geom_worker.program import UnknownParamError
from services.registry import parts as P
from services.registry.store import get_registry
from services.registry.tests.fixtures import add_part


@pytest.mark.parametrize(
    ("template", "want", "expected"),
    [
        ("clip", "M4 hole, 2 mm taller, 3 ribs", {"hole_d": 4.5, "arm_height": 10.0, "rib_count": 3}),
        ("l_bracket", "M3 screws and 2 mm taller and no gussets", {"hole_d": 3.4, "height": 32.0, "gusset_count": 0}),
        ("cable_clip", "for an 8 mm cable, 3 channels", {"cable_d": 8.0, "channel_count": 3}),
        ("hook", "for a 25 mm rail", {"reach": 25.0}),
        ("knob", "6.35 mm shaft, 40 mm diameter", {"bore_d": 6.35, "diameter": 40.0}),
        ("hinge_leaf", "4 holes and 0.5 mm thicker", {"hole_count": 4, "thickness": 3.0}),
    ],
)
def test_mock_variant_mapper_understands_plain_english(template: str, want: str, expected: dict[str, float]) -> None:
    t = get_template(template)
    edits, missed, conf = P.map_variant(want, t.params, t.defaults)
    got = {e["param"]: e["to"] for e in edits}
    assert got == pytest.approx(expected)
    assert not missed and conf >= 0.7


def test_mock_variant_refuses_rescale_and_reports_unknowns() -> None:
    t = get_template("caster_wheel")
    edits, missed, conf = P.map_variant("scale it up 2x", t.params, t.defaults)
    assert edits == [] and "rescal" in missed[0] and conf == 0.0


def test_guard_maps_closest_clamps_and_refuses_uniform_rescale() -> None:
    t = get_template("clip")
    vals = t.defaults
    params, applied, rejected = P.guard_edits(
        [
            {"param": "hole_dia", "to": 99, "reason": "x"},
            {"param": "wingspan", "to": 3, "reason": "?"},
            {"param": "rib_count", "to": 2.6, "reason": "ribs"},
        ],
        t.params,
        vals,
    )
    assert params["hole_d"] == 6.0  # mapped to the closest knob and clamped to max
    assert params["rib_count"] == 3
    assert any("asked for 'hole_dia'" in a and "clamped" in a for a in applied)
    assert any("wingspan" in r for r in rejected)
    # every mm dimension x1.5 = a rescale → refused
    scaled = [{"param": n, "to": vals[n] * 1.5, "reason": ""} for n in ("length", "width", "thickness")]
    params, applied, rejected = P.guard_edits(scaled, t.params, vals)
    assert not applied and any("rescale" in r for r in rejected)
    assert params["length"] == vals["length"]
    # a rescale word as a parameter name is refused too
    _, applied, rejected = P.guard_edits([{"param": "scale", "to": 2, "reason": ""}], t.params, vals)
    assert not applied and "rescal" in rejected[0]


def test_variant_through_provider_stage_is_mock_labelled() -> None:
    add_part("clip", "shelf-clip")
    v = P.variant("shelf-clip", "M4 hole and 3 ribs")
    assert v.mode == "mock"
    assert v.params["hole_d"] == 4.5 and v.params["rib_count"] == 3
    assert len(v.applied) == 2 and v.confidence > 0.5
    with pytest.raises(P.PartNotFound) as e:
        P.variant("shelf-clp", "M4")
    assert "shelf-clip" in e.value.closest


def test_bake_part_clamps_and_hits_cache() -> None:
    add_part("spacer", "m3-spacer")
    a = P.bake_part("m3-spacer", {"height": 12.0, "bore_d": 99.0}, ["stl", "view"])
    assert not a.cache_hit and a.clamped == {"bore_d": 20.0}
    assert set(a.artifacts) == {"stl", "view"} and a.artifacts["stl"].startswith("/api/v1/bakes/")
    key, name = a.artifacts["stl"].split("/")[-2:]
    assert P.bake_file(key, name) is not None and P.bake_file("../../etc", "passwd") is None
    b = P.bake_part("m3-spacer", {"height": 12.0, "bore_d": 99.0}, ["view", "stl"])
    assert b.cache_hit and b.cache_key == a.cache_key
    assert a.facts is not None and a.facts.bbox_mm[2] == pytest.approx(12.0, abs=0.01)
    with pytest.raises(UnknownParamError) as e:
        P.bake_part("m3-spacer", {"heigth": 3})
    assert "height" in e.value.closest["heigth"]


def test_template_pdf_is_a_pdf() -> None:
    add_part("clip", "shelf-clip")
    pdf = P.template_pdf("shelf-clip", {"length": 40.0})
    assert pdf[:5] == b"%PDF-" and len(pdf) > 1000
    outline, holes, (length, width) = P.outline_and_holes(get_template("clip").code)
    assert len(outline) > 4 and width == pytest.approx(16.0, abs=0.2)
    assert len(holes) == 1 and holes[0]["diameter_mm"] == pytest.approx(4.2, abs=0.1)
    assert length == pytest.approx(36.0, abs=0.2)


def test_matching_shared_interface_then_family() -> None:
    add_part("clip", "clip-a", params={"hole_d": 4.5})
    add_part("l_bracket", "bracket-m4")  # hole_d 4.5 by default
    add_part("clip", "clip-b", params={"hole_d": 3.4})
    add_part("knob", "knob-6")
    found = P.matching("clip-a")
    slugs = [p.slug for p, _ in found]
    assert slugs[0] == "bracket-m4" and "4.5 mm interface" in found[0][1]
    assert "clip-b" in slugs and "knob-6" not in slugs


def test_cards_detail_thumbnails_and_lineage() -> None:
    parent = add_part("hook", "wall-hook")
    child = add_part("hook", "wall-hook-long", params={"length": 80.0}, forked_from="wall-hook")
    reg = get_registry()
    card = P.part_card(parent, reg)
    assert card["thumbnail_url"] == "/api/v1/parts/wall-hook/thumbnail.png"  # lazy until rendered
    assert card["topology_knobs"] == ["hole_count"] and card["verified"] and card["origin"] == "synthetic"
    u1, u2 = P.ensure_thumbnail(parent)
    assert P.part_card(parent, reg)["thumbnail_url"] == u1
    img = Image.open(io.BytesIO(blobs.get(u1.rsplit("/", 1)[-1])))
    assert img.size == (640, 480) and img.mode == "RGBA"
    assert Image.open(io.BytesIO(blobs.get(u2.rsplit("/", 1)[-1]))).size == (1280, 960)
    alpha = np.asarray(img)[..., 3]
    assert alpha[0, 0] == 0 and (alpha == 255).mean() > 0.05
    assert P.ensure_thumbnail(parent) == (u1, u2)  # cached
    d = P.part_detail(child, reg)
    assert set(d["artifacts"]) == {"stl", "step", "3mf", "glb", "view", "py"}
    assert d["artifacts"]["stl"] == "/api/v1/parts/wall-hook-long/bake?format=stl&download=1"
    assert d["lineage"] == [{"slug": "wall-hook", "version": 1, "relation": "forked_from", "title": "Wall hook"}]
    assert P.part_detail(parent, reg)["lineage"][0]["relation"] == "variant_of"


def test_after_publish_fills_facts() -> None:
    part = add_part("spacer", "spacer-x")
    assert part.facts is None
    P.after_publish(part)
    stored = get_registry().get_part("spacer-x")
    assert stored is not None and stored.facts is not None and stored.facts.mass_g_pla > 0
    assert get_registry().thumbnail("spacer-x") is not None


FREE_CODE = [  # the knobs of a free-code (extruded outline) program
    ParamSpec(name="thickness", default=15.0, min=0.8, max=40.0, step=0.05, label="Plate thickness"),
    ParamSpec(name="outline_offset", default=0.0, min=-1.0, max=1.0, step=0.02, label="Outline offset"),
    ParamSpec(name="hole_1_d", default=12.5, min=9.5, max=15.5, step=0.05, label="hole_1 diameter"),
]


@pytest.mark.parametrize(
    ("template", "text", "expected"),
    [
        ("knob", "make it 2 mm taller", {"height": 18.0}),
        ("knob", "thoda ooncha karo", {"height": 16.5}),
        ("knob", "hole bada karo", {"bore_d": 6.2}),
        ("spacer", "2 mm lamba karo", {"height": 12.0}),  # a cylinder's length is its height
        ("l_bracket", "mota karo", {"thickness": 3.5}),
        ("clip", "chauda karo", {"width": 16.5}),
        ("clip", "make it wider", {"width": 16.5}),
        ("hook", "thoda chauda karo", {"width": 22.5}),
        (None, "make it 2 mm taller", {"thickness": 17.0}),  # flat extruded part: height = thickness
        (None, "thoda ooncha karo", {"thickness": 15.5}),
        (None, "1 mm mota karo", {"thickness": 16.0}),
        (None, "hole bada karo", {"hole_1_d": 12.7}),
    ],
)
def test_voice_edit_and_variant_share_dimension_synonyms(
    template: str | None, text: str, expected: dict[str, float]
) -> None:
    from services.media.voice import map_utterance

    specs = list(get_template(template).params) if template else FREE_CODE
    values = {p.name: p.default for p in specs}
    voice_edits, missed, _ = map_utterance(text, specs, values)
    assert {e["param"]: e["to"] for e in voice_edits} == pytest.approx(expected), missed
    variant_edits, missed, _ = P.map_variant(text, specs, values)
    assert {e["param"]: e["to"] for e in variant_edits} == pytest.approx(expected), missed
