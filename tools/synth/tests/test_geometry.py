"""Ground-truth geometry: rectangles, poses, see-through holes (SYNTHETIC meshes)."""

import math

import numpy as np
import pytest

from tools.synth import geometry as G

PLATE_WITH_HOLES = """import cadquery as cq

plate = cq.Workplane("XY").rect(40.0, 20.0).extrude(3.0)
plate = plate.faces(">Z").workplane().pushPoints([(-10.0, 0.0), (10.0, 0.0)]).hole(5.0)
blind = cq.Workplane("XY").workplane(offset=-0.01).center(0.0, 6.0).circle(1.5).extrude(1.5)
result = plate.cut(blind)
"""


def _rect(L: float, W: float, a_deg: float, c=(5.0, -3.0)) -> np.ndarray:
    a = math.radians(a_deg)
    R = np.array([[math.cos(a), -math.sin(a)], [math.sin(a), math.cos(a)]])
    p = np.array([[-L / 2, -W / 2], [L / 2, -W / 2], [L / 2, W / 2], [-L / 2, W / 2]])
    return np.asarray(p @ R.T + np.array(c), dtype=np.float64)


@pytest.mark.parametrize("angle", [0.0, 17.0, 63.5, 90.0, 141.0])
def test_min_area_rect_of_rotated_rectangle(angle: float) -> None:
    pts = np.vstack([_rect(40, 12.5, angle), _rect(30, 5, angle)])  # inner points do not matter
    length, width, a = G.min_area_rect(pts)
    assert length == pytest.approx(40.0, abs=1e-9) and width == pytest.approx(12.5, abs=1e-9)
    assert min(abs(a - angle % 180), 180 - abs(a - angle % 180)) < 1e-6


def test_placement_is_a_proper_rotation_and_flips_up_to_into_table() -> None:
    pl = G.Placement((100.0, 50.0), 30.0)
    M = pl.matrix()
    assert np.linalg.det(M[:3, :3]) == pytest.approx(1.0)
    top = pl.apply(np.array([[0.0, 0.0, 5.0]]))[0]
    assert top[2] == pytest.approx(-5.0)  # 5 mm up = 5 mm towards the camera
    assert top[:2] == pytest.approx([100.0, 50.0])
    # distances are preserved
    a, b = pl.apply_xy(np.array([[0.0, 0.0], [10.0, 0.0]]))
    assert np.linalg.norm(a - b) == pytest.approx(10.0)


def test_lay_on_side_turns_thickness_into_footprint() -> None:
    box = np.array([[x, y, z] for x in (-20, 20) for y in (-5, 5) for z in (0, 3)], dtype=float)
    v = G.lay_on_side(box)
    assert v[:, 2].min() == pytest.approx(0.0) and v[:, 2].max() == pytest.approx(10.0)
    length, width, _ = G.min_area_rect(v[:, :2])
    assert length == pytest.approx(40.0) and width == pytest.approx(3.0)


def test_build_mesh_dims_and_visible_holes() -> None:
    pm = G.build_mesh(PLATE_WITH_HOLES)
    assert G.top_dims(pm) == pytest.approx({"length": 40.0, "width": 20.0}, abs=1e-6)
    holes = G.visible_holes(pm)
    assert [h.name for h in holes] == ["hole_1", "hole_2"]  # the blind pocket is not see-through
    assert [h.diameter_mm for h in holes] == pytest.approx([5.0, 5.0], abs=1e-6)
    assert holes[0].center_cad_mm == pytest.approx((-10.0, 0.0), abs=1e-6)
    sd = G.side_dims(pm)
    assert sd["thickness"] == pytest.approx(3.0, abs=1e-6) and sd["side_height"] == pytest.approx(20.0, abs=1e-6)
