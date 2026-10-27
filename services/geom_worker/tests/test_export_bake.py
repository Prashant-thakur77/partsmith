from __future__ import annotations

import io
from pathlib import Path

import numpy as np
import pytest
import trimesh

from services.geom_worker.bake import BakeError, bake, cache_key
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
