import math

import numpy as np
import pytest
from partsmith_schemas.common import DataOrigin, Source
from partsmith_schemas.measurement import ViewKind
from shapely.geometry import Polygon

from services.metrology import testing as T
from services.metrology.features import (
    PartFrame,
    SigmaModel,
    analyse_footprint,
    build_measurements,
    fit_circle,
    fit_circle_algebraic,
    fit_slot,
    min_area_rect,
    symmetry_axis,
)


def test_circle_fits() -> None:
    rng = np.random.default_rng(1)
    a = rng.uniform(0, 2 * np.pi, 400)
    pts = np.c_[3.0 + 2.5 * np.cos(a), -1.0 + 2.5 * np.sin(a)] + rng.normal(0, 0.01, (400, 2))
    cx, cy, r = fit_circle_algebraic(pts)
    assert (cx, cy, r) == pytest.approx((3.0, -1.0, 2.5), abs=0.005)
    # geometric refinement fixes the algebraic bias on a short arc
    arc = a[(a > 0.2) & (a < 1.6)]
    p_arc = np.c_[3.0 + 2.5 * np.cos(arc), -1.0 + 2.5 * np.sin(arc)] + rng.normal(0, 0.02, (len(arc), 2))
    cf = fit_circle(p_arc)
    assert cf.r == pytest.approx(2.5, abs=0.05)
    assert cf.rms < 0.03 and cf.roundness > 0


def test_slot_fit() -> None:
    sf = fit_slot(T.slot_poly(5.0, 2.0, 12.0, 4.0, 30.0))
    assert sf is not None
    assert sf.length == pytest.approx(12.0, abs=0.01)
    assert sf.width == pytest.approx(4.0, abs=0.01)
    assert (sf.cx, sf.cy) == pytest.approx((5.0, 2.0), abs=0.01)
    assert math.degrees(sf.angle_rad) % 180 == pytest.approx(30.0, abs=0.2)
    assert fit_slot(T.circle_poly(0, 0, 5)) is None


def test_part_frame_round_trip() -> None:
    fr = PartFrame(100.0, 60.0, math.radians(25.0), scale=1.002)
    p = np.array([[110.0, 65.0], [90.0, 50.0]])
    np.testing.assert_allclose(fr.to_mat(fr.to_part(p)), p, atol=1e-9)
    # +X of the part frame points along theta in the mat; +Y (up) points to mat −y rotated
    ex = fr.to_mat(np.array([[1.0, 0.0]]))[0] - fr.to_mat(np.array([[0.0, 0.0]]))[0]
    assert math.degrees(math.atan2(ex[1], ex[0])) == pytest.approx(25.0)
    _, L, W, th = min_area_rect(T.rect_poly(0, 0, 30, 10, 100))
    assert pytest.approx((30, 10), abs=1e-3) == (L, W) and math.degrees(th) == pytest.approx(-80, abs=1e-3)


def test_symmetry_axis() -> None:
    tri = Polygon([(-10, 0), (10, 0), (0, 15)])  # isosceles: axis is vertical
    ang, score = symmetry_axis(tri)
    assert ang == pytest.approx(90.0, abs=0.5) and score > 0.995
    L_shape = Polygon([(0, 0), (20, 0), (20, 5), (5, 5), (5, 30), (0, 30)])
    _, s2 = symmetry_axis(L_shape)
    assert s2 < 0.9


def test_build_measurements_rect_with_hole_and_slot() -> None:
    outer = T.rect_poly(100, 60, 40, 20, 20)
    hole = T.circle_poly(100 + 10 * math.cos(math.radians(20)), 60 + 10 * math.sin(math.radians(20)), 5.0, 360)
    slot = T.slot_poly(100 - 10 * math.cos(math.radians(20)), 60 - 10 * math.sin(math.radians(20)), 10, 4, 20)
    poly = Polygon(outer, [hole, slot])
    sigma = SigmaModel(reproj_mm=0.02, edge_mm=0.03, height_rel=0.001)
    m, ff = build_measurements(
        poly, view=ViewKind.top, origin=DataOrigin.synthetic, sigma=sigma, to_px=lambda p: p * 5.0
    )
    assert m.length.value == pytest.approx(40, abs=1e-3) and m.width.value == pytest.approx(20, abs=1e-3)
    assert m.length.source == Source.measured and m.length.sigma_mm > 0 and m.length.evidence is not None
    assert m.length.evidence.pixels is not None and len(m.length.evidence.pixels) == 2
    assert len(m.holes) == 1 and len(m.slots) == 1
    h = m.holes[0]
    assert h.diameter.value == pytest.approx(5.0, abs=0.01)
    assert abs(h.center_mm[0]) == pytest.approx(10.0, abs=0.01) and h.center_mm[1] == pytest.approx(0.0, abs=0.01)
    s = m.slots[0]
    assert s.length.value == pytest.approx(10, abs=0.02) and s.width.value == pytest.approx(4, abs=0.02)
    assert s.angle_deg % 180 == pytest.approx(0.0, abs=0.5) or s.angle_deg % 180 == pytest.approx(180.0, abs=0.5)
    assert m.area_mm2 == pytest.approx(poly.area, rel=1e-3)
    assert m.symmetry_score is not None and m.symmetry_score > 0.9
    # part_to_mat maps the part-frame hole centre back onto the true mat position
    M = np.array(m.part_to_mat)
    back = M[:2, :2] @ np.array(h.center_mm) + M[:2, 2]
    assert back == pytest.approx(np.array(Polygon(hole).centroid.coords[0]), abs=0.01)
    assert ff.length_mm == pytest.approx(40, abs=1e-3)


def test_irregular_opening_is_noted() -> None:
    poly = Polygon(T.rect_poly(0, 0, 40, 20), [np.array([[-5, -3], [5, -3], [0, 6.0]])])
    ff = analyse_footprint(poly)
    assert not ff.holes and not ff.slots and len(ff.other_openings_mm2) == 1


def test_sigma_model() -> None:
    s = SigmaModel(reproj_mm=0.02, edge_mm=0.05, height_rel=0.01, scale_rel=0.002)
    assert s.length(40) > s.length(10) > 0
    assert s.diameter(5.0, 400) < s.length(5.0)
