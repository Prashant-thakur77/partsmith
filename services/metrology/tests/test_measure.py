"""Accuracy on synthetic photos with exact ground truth (rendered from known K, R, t; labelled synthetic)."""

import math

import cv2
import numpy as np
import pytest
from partsmith_schemas.common import DataOrigin, Source
from partsmith_schemas.measurement import Hole, ViewKind
from shapely.geometry import Polygon

from services.metrology import testing as T
from services.metrology.mats import get_mat
from services.metrology.measure import MeasureOutput, measure_photo
from services.metrology.segment import ThresholdSegmenter

TOL_MM = 0.15


def _centre(mat_id: str, dx: float = 0.0, dy: float = 0.0) -> tuple[float, float]:
    st = get_mat(mat_id).stage
    return st.x_mm + st.w_mm / 2 + dx, st.y_mm + st.h_mm / 2 + dy


def _plate(mat_id: str, thickness: float, angle: float = 25.0) -> tuple[T.PrismPart, tuple[float, float]]:
    cx, cy = _centre(mat_id, 8, -4)
    a = math.radians(angle)
    hole_c = (cx + 8 * math.cos(a), cy + 8 * math.sin(a))
    return T.PrismPart(
        T.rect_poly(cx, cy, 40, 20, angle), [T.circle_poly(*hole_c, 6.0)], thickness_mm=thickness
    ), hole_c


def _hole_mat(out: MeasureOutput, hole: Hole) -> np.ndarray:
    assert out.result.measurements is not None
    M = np.array(out.result.measurements.part_to_mat)
    return np.asarray(M[:2, :2] @ np.array(hole.center_mm) + M[:2, 2], dtype=np.float64)


@pytest.mark.parametrize("known_K", [True, False], ids=["calibrated-K", "estimated-K"])
def test_thin_plate_with_hole(known_K: bool) -> None:
    part, hole_c = _plate("screen-m", 1.0)
    cam = T.camera_above(_centre("screen-m"), height_mm=260, tilt_deg=10, azimuth_deg=30)
    sc = T.render_part_scene("screen-m", cam, part)
    out = measure_photo(
        T.encode_png(sc.image),
        ViewKind.top,
        segmenter=ThresholdSegmenter(),
        thickness_mm=1.0,
        K=cam.K if known_K else None,
        origin=DataOrigin.synthetic,
    )
    r = out.result
    assert r.capture.passed, r.capture.retake_reason
    m = r.measurements
    assert m is not None and m.origin == DataOrigin.synthetic
    assert abs(m.length.value - 40.0) < TOL_MM
    assert abs(m.width.value - 20.0) < TOL_MM
    assert len(m.holes) == 1
    assert abs(m.holes[0].diameter.value - 6.0) < TOL_MM
    assert np.linalg.norm(_hole_mat(out, m.holes[0]) - hole_c) < TOL_MM
    assert m.length.source == Source.measured and 0 < m.length.sigma_mm < 0.5
    assert m.thickness is not None and m.thickness.source == Source.user_stated
    assert r.calibration is not None and r.calibration.pose is not None
    assert r.calibration.pose.intrinsics_source == ("calibrated" if known_K else "estimated")
    assert any("height-corrected" in n for n in m.notes)
    # rectified footprint mask agrees with the true footprint
    gt = Polygon(part.outline_mm, part.holes_mm)
    assert out.footprint_mat is not None
    assert out.footprint_mat.symmetric_difference(gt).area / gt.area < 0.01
    assert out.rectified_mask is not None and out.rectified_png and out.mask_png
    assert out.rectified_mask.shape == (
        round(get_mat("screen-m").stage.h_mm * 10),
        round(get_mat("screen-m").stage.w_mm * 10),
    )
    yy, xx = np.nonzero(out.rectified_mask)
    c_mm = np.array([xx.mean(), yy.mean()]) + 0.5
    c_mm = c_mm / out.px_per_mm + np.array(out.origin_mm)
    assert np.linalg.norm(c_mm - np.array(gt.centroid.coords[0])) < 0.1
    png = cv2.imdecode(np.frombuffer(out.overlay_png, np.uint8), cv2.IMREAD_COLOR)
    assert png is not None and png.shape[1] <= 1600


def test_thin_disc_on_paper() -> None:
    cx, cy = _centre("paper-a4", -5, 10)
    part = T.PrismPart(T.circle_poly(cx, cy, 30.0), [], thickness_mm=0.8, top_bgr=(40, 60, 170), side_bgr=(30, 45, 130))
    cam = T.camera_above(_centre("paper-a4"), height_mm=340, tilt_deg=9, azimuth_deg=-60)
    sc = T.render_part_scene("paper-a4", cam, part, white_bgr=(225, 228, 230), surround_bgr=(90, 110, 130))
    out = measure_photo(sc.image, "top", segmenter=ThresholdSegmenter(), thickness_mm=0.8)
    m = out.result.measurements
    assert m is not None
    assert abs(m.length.value - 30.0) < TOL_MM and abs(m.width.value - 30.0) < TOL_MM
    assert m.area_mm2 == pytest.approx(math.pi * 15**2, rel=0.01)
    assert not m.holes and m.symmetry_score is not None and m.symmetry_score > 0.99


@pytest.mark.parametrize("known_K", [True, False], ids=["calibrated-K", "estimated-K"])
def test_height_correction_on_a_thick_part(known_K: bool) -> None:
    """An 8 mm plate seen from 330 mm at 12° tilt: uncorrected top edges read ~2 % large; the plane-at-height
    correction brings length, width and the through-hole back within tolerance."""
    part, hole_c = _plate("screen-l", 8.0, angle=-15.0)
    cam = T.camera_above(_centre("screen-l"), height_mm=330, tilt_deg=12, azimuth_deg=200)
    sc = T.render_part_scene("screen-l", cam, part)
    K = cam.K if known_K else None
    corr = measure_photo(sc.image, "top", segmenter=ThresholdSegmenter(), thickness_mm=8.0, K=K)
    raw = measure_photo(sc.image, "top", segmenter=ThresholdSegmenter(), thickness_mm=None, K=K)
    mc, mr = corr.result.measurements, raw.result.measurements
    assert mc is not None and mr is not None
    err_c = max(abs(mc.length.value - 40), abs(mc.width.value - 20))
    err_r = max(abs(mr.length.value - 40), abs(mr.width.value - 20))
    assert err_c < TOL_MM
    assert err_r > 0.5 and err_r > 4 * err_c
    assert len(mc.holes) == 1 and abs(mc.holes[0].diameter.value - 6.0) < TOL_MM
    assert np.linalg.norm(_hole_mat(corr, mc.holes[0]) - hole_c) < TOL_MM
    assert mc.height_correction_scale == pytest.approx((corr.pose.camera_height_mm - 8) / corr.pose.camera_height_mm)  # type: ignore[union-attr]
    assert mr.height_correction_scale == 1.0 and any("thickness unknown" in n for n in mr.notes)


def test_side_view_gives_thickness() -> None:
    cx, cy = _centre("screen-m")
    part = T.PrismPart(T.rect_poly(cx, cy, 40, 6, 0), [], thickness_mm=20.0)  # lying on its side: 6 mm thick plate
    cam = T.camera_above((cx, cy), height_mm=280, tilt_deg=8, azimuth_deg=90)
    sc = T.render_part_scene("screen-m", cam, part)
    out = measure_photo(sc.image, "side", segmenter=ThresholdSegmenter(), thickness_mm=20.0, K=cam.K)
    m = out.result.measurements
    assert m is not None and m.view == ViewKind.side
    assert m.thickness is not None and m.thickness.source == Source.measured
    assert abs(m.thickness.value - 6.0) < TOL_MM and abs(m.length.value - 40.0) < TOL_MM


def test_no_mat_reports_capture_failure() -> None:
    img = np.full((600, 800, 3), 180, np.uint8)
    out = measure_photo(img, "top", segmenter=ThresholdSegmenter())
    assert not out.result.capture.passed
    assert out.result.measurements is None and out.result.calibration is None
    assert out.result.capture.retake_reason and "markers" in out.result.capture.retake_reason.lower()
    assert out.overlay_png[:8] == b"\x89PNG\r\n\x1a\n"


def test_empty_stage() -> None:
    cam = T.camera_above(_centre("screen-m"), height_mm=260, tilt_deg=6)
    sc = T.render_part_scene("screen-m", cam, None)
    out = measure_photo(sc.image, "top", segmenter=ThresholdSegmenter())
    assert out.result.measurements is None and out.result.calibration is not None
    assert not out.result.capture.passed
