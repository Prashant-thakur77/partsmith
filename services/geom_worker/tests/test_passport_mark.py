"""The passport mark: debossed by trusted code after the program ran, never changing a measured dimension, skipped on
parts with no safe face, and absent unless asked for (CAD in the sandbox pool, no network)."""

from __future__ import annotations

import math
from pathlib import Path

import pytest

from services.geom_worker.bake import bake, cache_key, passport_report
from services.geom_worker.sandbox import WarmPool, run_program
from services.verifier.solid_features import SolidFeatures

BIG = """
import cadquery as cq

PARAMS = {  # name: (default, min, max, step, unit, affects_fit, label)
    "length": (64.0, 20.0, 120.0, 0.1, "mm", True, "Length"),
    "width": (32.0, 8.0, 60.0, 0.1, "mm", True, "Width"),
    "thickness": (3.0, 1.0, 8.0, 0.1, "mm", True, "Plate thickness"),
    "hole_d": (4.2, 2.0, 8.0, 0.05, "mm", True, "Screw hole"),
}


def build(p):
    plate = cq.Workplane("XY").rect(p["length"], p["width"]).extrude(p["thickness"]).edges("|Z").fillet(2.0)
    pts = [(-p["length"] / 3, 0), (p["length"] / 3, 0)]
    return plate.faces(">Z").workplane().pushPoints(pts).hole(p["hole_d"])


def interfaces(p):
    return [{"id": "screw", "label": "screw hole", "at": [p["length"] / 3, 0, p["thickness"] / 2],
             "axis": [1, 0, 0], "mates": [4.0], "mate_label": "M4 screw"}]
"""

PID = "7KQ3MZ"


def _features(res: object) -> SolidFeatures:
    feats = getattr(res, "features", None)
    assert feats is not None
    return SolidFeatures.from_dict(feats)


@pytest.mark.parametrize("pid", [PID, "44KKAT"])  # "AT": kerned glyphs that touch must still cut as one tool
def test_mark_changes_no_measured_dimension_and_stays_one_watertight_solid(pool: WarmPool, pid: str) -> None:
    with run_program(BIG, {}, outputs=(), pool=pool) as plain, \
         run_program(BIG, {}, outputs=(), pool=pool, passport=pid) as marked:  # fmt: skip
        assert plain.ok and marked.ok, (plain.error, marked.error)
        rep = marked.passport
        assert rep is not None and rep["applied"], rep
        assert plain.passport is None  # nothing is marked unless asked for
        assert rep["text"] == pid and rep["depth_mm"] == 0.4 and rep["text_height_mm"] >= 4.0
        assert {c["name"] for c in rep["checks"]} >= {"bounding box unchanged", "holes unchanged",
                                                      "mating interfaces unchanged", "watertight mesh"}  # fmt: skip
        assert all(c["passed"] for c in rep["checks"])
        a, b = _features(plain), _features(marked)
        assert b.bbox_mm == pytest.approx(a.bbox_mm, abs=1e-3)
        assert len(a.holes) == len(b.holes) == 2
        for ha, hb in zip(a.holes, b.holes, strict=True):
            assert hb.diameter_mm == pytest.approx(ha.diameter_mm, abs=1e-3)
            assert hb.center_mm == pytest.approx(ha.center_mm, abs=1e-3)
        assert b.plate_thickness_mm == pytest.approx(a.plate_thickness_mm, abs=1e-3)
        assert marked.solid_info is not None and plain.solid_info is not None
        assert marked.solid_info.valid and marked.solid_info.n_solids == 1
        removed = plain.solid_info.volume_mm3 - marked.solid_info.volume_mm3
        assert 0 < removed == pytest.approx(rep["removed_mm3"], abs=1e-2)
        assert marked.mesh is not None and marked.mesh.trimesh().is_watertight
        box = rep["box_mm"]
        assert box["w"] >= 25 and box["h"] >= 8
        # the free rectangle keeps 3 mm away from the declared interface at (length / 3, 0)
        hw, hh = (box["w"] / 2, box["h"] / 2) if box["angle_deg"] == 0 else (box["h"] / 2, box["w"] / 2)
        dx, dy = max(abs(64 / 3 - box["cx"]) - hw, 0.0), max(abs(box["cy"]) - hh, 0.0)
        assert math.hypot(dx, dy) >= 3.0 - 1e-6


def test_small_or_thin_part_is_left_unmarked_and_says_so(pool: WarmPool) -> None:
    for params, why in (({"length": 40.0, "width": 20.0}, "free 25 x 8 mm"), ({"thickness": 1.0}, "material under")):
        with run_program(BIG, params, outputs=(), features=False, pool=pool) as plain, \
             run_program(BIG, params, outputs=(), features=False, pool=pool, passport=PID) as marked:  # fmt: skip
            rep = marked.passport
            assert rep is not None and not rep["applied"] and why in rep["reason"], rep
            assert "no safe place" in rep["reason"]
            assert plain.solid_info is not None and marked.solid_info is not None
            assert marked.solid_info.volume_mm3 == pytest.approx(plain.solid_info.volume_mm3, abs=1e-6)


def test_bake_keys_and_stores_the_mark_only_when_asked(tmp_path: Path, pool: WarmPool) -> None:
    assert cache_key(BIG, 1, {"a": 1.0}, ["stl"]) == cache_key(BIG, 1, {"a": 1.0}, ["stl"], None)
    assert cache_key(BIG, 1, {"a": 1.0}, ["stl"], PID) != cache_key(BIG, 1, {"a": 1.0}, ["stl"])
    plain = bake(BIG, {}, ("stl",), pool=pool, root=tmp_path)
    marked = bake(BIG, {}, ("stl",), pool=pool, root=tmp_path, passport=PID)
    assert plain.passport is None and passport_report(plain.cache_key, tmp_path) is None
    assert marked.passport is not None and marked.passport["applied"]
    assert passport_report(marked.cache_key, tmp_path) == marked.passport
    assert marked.facts is not None and plain.facts is not None
    assert marked.facts.bbox_mm == pytest.approx(plain.facts.bbox_mm, abs=1e-3)
    assert marked.facts.volume_mm3 < plain.facts.volume_mm3
    again = bake(BIG, {}, ("stl",), pool=pool, root=tmp_path, passport=PID)
    assert again.cache_hit and again.passport == marked.passport
