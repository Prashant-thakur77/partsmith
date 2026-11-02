from __future__ import annotations

import io
from pathlib import Path

import numpy as np
import pytest
import trimesh

from services.geom_worker.bake import FACTS_RULE, BakeError, bake, cache_key
from services.geom_worker.export import glb_bytes, vertex_normals
from services.geom_worker.program import defaults
from services.geom_worker.sandbox import WarmPool


def _box() -> tuple[np.ndarray, np.ndarray]:
    m = trimesh.creation.box(extents=(10.0, 20.0, 30.0))
    m.apply_translation((0, 0, 15.0))
    return np.asarray(m.vertices), np.asarray(m.faces)


def test_glb_is_metres_and_y_up() -> None:
    v, f = _box()
    scene = trimesh.load(io.BytesIO(glb_bytes(v, f)), file_type="glb")
    mesh = scene.to_geometry() if isinstance(scene, trimesh.Scene) else scene
    ext = mesh.bounds[1] - mesh.bounds[0]
    assert ext == pytest.approx([0.010, 0.030, 0.020], abs=1e-6)  # Z (30 mm) became Y (0.030 m)
    assert mesh.bounds[0][1] == pytest.approx(0.0, abs=1e-9)  # the mounting face sits on y = 0


def test_vertex_normals_unit_length() -> None:
    v, f = _box()
    n = vertex_normals(v, f)
    assert np.allclose(np.linalg.norm(n, axis=1), 1.0)


def test_bake_caches_and_reports_facts(tmp_path: Path, pool: WarmPool, plate_code: str) -> None:
    out = bake(plate_code, {"length": 50.0, "hole_count": 9}, ("stl", "py", "view"), pool=pool, root=tmp_path)
    assert not out.cache_hit
    assert out.clamped == {"hole_count": 4}
    assert set(out.files) == {"stl", "py", "view"} and all(p.exists() for p in out.files.values())
    assert defaults(out.files["py"].read_text())["length"] == 50.0
    facts = out.facts
    assert facts is not None
    assert facts.bbox_mm == pytest.approx((50.0, 20.0, 3.0), abs=1e-3)
    assert facts.mass_g_pla == pytest.approx(facts.volume_mm3 / 1000 * 1.24, abs=0.01)
    assert facts.mass_g_petg > facts.mass_g_pla
    assert facts.orientation.startswith("-Z") and not facts.supports_needed
    assert "solid-volume" in out.facts_notes["mass"]

    again = bake(plate_code, {"length": 50.0, "hole_count": 4}, ("view", "py", "stl"), pool=pool, root=tmp_path)
    assert again.cache_hit and again.cache_key == out.cache_key
    assert again.files == out.files


def test_cache_key_depends_on_everything(plate_code: str) -> None:
    p = defaults(plate_code)
    k = cache_key(plate_code, 1, p, ["stl"])
    assert k == cache_key(plate_code, 1, dict(reversed(list(p.items()))), ["stl"])
    assert k != cache_key(plate_code, 2, p, ["stl"])
    assert k != cache_key(plate_code, 1, {**p, "length": 41.0}, ["stl"])
    assert k != cache_key(plate_code, 1, p, ["stl", "step"])
    assert k != cache_key(plate_code + "\n", 1, p, ["stl"])


def test_bake_failure_raises(tmp_path: Path, pool: WarmPool) -> None:
    code = "import cadquery as cq\nPARAMS = {'a': (1.0, 0.5, 2.0, 0.1, 'mm', True, 'A')}\ndef build(p):\n    return 1 / 0\n"
    with pytest.raises(BakeError) as ei:
        bake(code, {}, ("stl",), pool=pool, root=tmp_path)
    assert ei.value.error.kind == "runtime" and ei.value.error.line == 4


def test_bake_rejects_unknown_format(plate_code: str, tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="unknown format"):
        bake(plate_code, {}, ("obj",), root=tmp_path)


def test_overhang_detects_supports(tmp_path: Path, pool: WarmPool) -> None:
    # A T standing on its stem overhangs under the bar; bar-down or lying flat it does not.
    code = (
        "import cadquery as cq\n"
        "PARAMS = {'w': (30.0, 10.0, 50.0, 0.1, 'mm', True, 'Bar')}\n"
        "def build(p):\n"
        "    stem = cq.Workplane('XY').box(6, 6, 20, centered=(True, True, False))\n"
        "    bar = cq.Workplane('XY').box(p['w'], 6, 4, centered=(True, True, False)).translate((0, 0, 20))\n"
        "    return stem.union(bar)\n"
        "result = build({k: v[0] for k, v in PARAMS.items()})\n"
    )
    out = bake(code, {}, ("stl",), pool=pool, root=tmp_path)
    assert out.facts is not None
    assert out.overhang_mm2["-Z"] > 100  # the bar's underside overhangs when printed as modelled
    assert out.overhang_mm2["+Z"] == pytest.approx(0.0)  # bar face down: nothing overhangs
    assert out.facts.orientation[:2] in ("+Z", "-Y", "+Y")  # lying flat on its side also needs no support
    assert not out.facts.supports_needed


CHAMFERED_TUBE = (
    "import cadquery as cq\n"
    "PARAMS = {'d': (7.0, 4.0, 30.0, 0.05, 'mm', True, 'Outer'), 'h': (12.0, 2.0, 60.0, 0.1, 'mm', True, 'Height')}\n"
    "def build(p):\n"
    "    t = cq.Workplane('XY').circle(p['d'] / 2).extrude(p['h'])\n"
    "    t = t.cut(cq.Workplane('XY').workplane(offset=-1).circle(1.7).extrude(p['h'] + 2))\n"
    "    return t.faces('>Z or <Z').edges().chamfer(0.4)\n"
    "result = build({k: v[0] for k, v in PARAMS.items()})\n"
)


def test_upright_tube_with_45_deg_chamfers_needs_no_supports(tmp_path: Path, pool: WarmPool) -> None:
    # A plain 7 x 12 mm spacer stands on its flat end; its 45 deg chamfers print without supports.
    out = bake(CHAMFERED_TUBE, {}, ("stl",), pool=pool, root=tmp_path)
    assert out.facts is not None and not out.facts.supports_needed
    assert out.facts.orientation.startswith(("-Z", "+Z"))
    assert out.overhang_mm2["-Z"] == pytest.approx(0.0, abs=0.5)


def test_cached_facts_from_older_rules_are_recomputed(tmp_path: Path, pool: WarmPool) -> None:
    import json

    out = bake(CHAMFERED_TUBE, {}, ("stl",), pool=pool, root=tmp_path)
    man = out.files["stl"].parent / "manifest.json"
    m = json.loads(man.read_text())
    m.pop("facts_rule")
    m["facts"]["supports_needed"] = True  # what the old 45 deg cut-off said
    man.write_text(json.dumps(m))
    again = bake(CHAMFERED_TUBE, {}, ("stl",), pool=pool, root=tmp_path)
    assert again.cache_hit and again.facts is not None and not again.facts.supports_needed
    assert json.loads(man.read_text())["facts_rule"] == FACTS_RULE


# Supports verdicts for the family templates at their defaults, and why. A small sloped edge (fillet or chamfer) that
# tops out within 2 mm of the bed prints as first layers stepping outwards; real overhangs higher up still count.
TEMPLATE_SUPPORTS = {
    "caster_wheel": (False, "-Z"),  # a solid disc printed flat: its 2 mm bottom tread fillet is a bed edge
    "spacer": (False, "-Z"),  # stands on its end; 45 deg chamfers and a vertical bore
    "knob": (False, "+Z"),  # upside down: the top fillet becomes a bed edge (as modelled, the blind bore's ceiling
    # is a flat bridge 12 mm up)
    "l_bracket": (False, "-Z"),  # the upright leg's two horizontal 4.5 mm screw holes: their top arcs bridge
    "hook": (True, "-Y"),  # the J arm's bend overhangs well above the plate in every orientation; on its side the
    # two screw holes are horizontal and bridge, which leaves a little less overhang than flat on its plate
}


@pytest.mark.parametrize("name", sorted(TEMPLATE_SUPPORTS))
def test_template_supports_verdicts(name: str, tmp_path: Path, pool: WarmPool) -> None:
    from services.agent.templates import get_template

    needed, orient = TEMPLATE_SUPPORTS[name]
    out = bake(get_template(name).code, {}, ("stl",), pool=pool, root=tmp_path)
    assert out.facts is not None
    assert out.facts.supports_needed is needed, (name, out.overhang_mm2)
    assert out.facts.orientation.startswith(orient)
    if name == "caster_wheel":
        assert out.overhang_mm2["-Z"] == pytest.approx(0.0, abs=0.5)  # was ~148 mm^2 of fillet facets


LOW_CEILING = (
    "import cadquery as cq\n"
    "PARAMS = {'d': (40.0, 20.0, 60.0, 0.1, 'mm', True, 'Disc')}\n"
    "def build(p):\n"
    "    stem = cq.Workplane('XY').circle(15).extrude(1.5)\n"
    "    return stem.union(cq.Workplane('XY').workplane(offset=1.5).circle(p['d'] / 2).extrude(3))\n"
    "result = build({k: v[0] for k, v in PARAMS.items()})\n"
)


def test_a_flat_ceiling_near_the_bed_still_counts(tmp_path: Path, pool: WarmPool) -> None:
    # a 40 mm disc on a 30 mm stem 1.5 mm tall: the ring under the disc faces straight down (a ledge, not a sloped
    # edge), so the bed-edge allowance does not hide it as modelled
    out = bake(LOW_CEILING, {}, ("stl",), pool=pool, root=tmp_path)
    assert out.overhang_mm2["-Z"] == pytest.approx(3.14159 * (20**2 - 15**2), rel=0.02)


SIDE_HOLE = (
    "import cadquery as cq\n"
    "PARAMS = {'d': (5.0, 2.0, 12.0, 0.1, 'mm', True, 'Hole')}\n"
    "def build(p):\n"
    "    block = cq.Workplane('XY').box(30, 20, 20, centered=(True, True, False))\n"
    "    return block.cut(cq.Workplane('YZ').workplane(offset=-20).center(0, 10).circle(p['d'] / 2).extrude(40))\n"
    "result = build({k: v[0] for k, v in PARAMS.items()})\n"
)


@pytest.mark.parametrize(("d", "counted"), [(4.0, False), (6.0, False), (10.0, True)])
def test_top_arc_of_a_small_horizontal_hole_is_not_an_overhang(
    d: float, counted: bool, tmp_path: Path, pool: WarmPool
) -> None:
    # a block lying flat with a hole along X, 10 mm up: up to 6 mm across the hole's top arc bridges; a 10 mm hole's
    # top arc (about 30 mm x 2 x 0.8 rad x r of facets steeper than 45 deg) still needs support as modelled
    out = bake(SIDE_HOLE, {"d": d}, ("stl",), pool=pool, root=tmp_path)
    if counted:
        assert out.overhang_mm2["-Z"] > 100
    else:
        assert out.overhang_mm2["-Z"] == pytest.approx(0.0, abs=0.5)
