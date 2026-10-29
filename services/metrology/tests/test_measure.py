"""Accuracy on synthetic photos with exact ground truth (rendered from known K, R, t; labelled synthetic)."""

import math

import cv2
import numpy as np
import pytest
from partsmith_schemas.common import DataOrigin, Source
from partsmith_schemas.measurement import Hole, ViewKind
from shapely.geometry import Polygon

from services.metrology import testing as T
from services.metrology.calibrate import detect_mat
from services.metrology.mats import STAGE_COLOURS, get_mat
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
    assert mc.height_correction_scale == pytest.approx((corr.pose.camera_height_mm - 8) / corr.pose.camera_height_mm)
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


def _caster_plate(dx: float, hole_d: float, h: float) -> tuple[T.PrismPart, list[tuple[float, float]]]:
    cx, cy = _centre("screen-l", dx, 0)
    hs = [(cx + ox, cy + oy) for ox in (-17, 17) for oy in (-17, 17)] if hole_d >= 4 else [(cx - 15, cy), (cx + 15, cy)]
    body = T.rounded_rect_poly(cx, cy, 50, 50 if hole_d >= 4 else 24, 5)
    return T.PrismPart(body, [T.circle_poly(x, y, hole_d) for x, y in hs], thickness_mm=h), hs


def test_see_through_holes_of_a_thick_plate() -> None:
    """10 mm plate, camera tilted 18°: each Ø5 hole shows the mat only through a narrow lens. Fitting the hole as a
    vertical cylinder (bottom disc ∩ projected top disc) recovers diameter and position."""
    part, hs = _caster_plate(20, 5.0, 10.0)
    cam = T.camera_above(_centre("screen-l"), height_mm=330, tilt_deg=18, azimuth_deg=160)
    sc = T.render_part_scene("screen-l", cam, part)
    out = measure_photo(sc.image, "top", segmenter=ThresholdSegmenter(), thickness_mm=10.0, K=cam.K)
    m = out.result.measurements
    assert m is not None and len(m.holes) == 4
    for hole in m.holes:
        c = _hole_mat(out, hole)
        assert min(np.hypot(c[0] - x, c[1] - y) for x, y in hs) < TOL_MM
        assert abs(hole.diameter.value - 5.0) < TOL_MM
        assert hole.diameter.evidence is not None and "see-through fit, h=10.0 mm" in (
            hole.diameter.evidence.note or ""
        )
        assert 0 < hole.diameter.sigma_mm < 0.3
    # Without the thickness the same photo cannot give the bores: the old behaviour is kept and said so.
    raw = measure_photo(sc.image, "top", segmenter=ThresholdSegmenter(), thickness_mm=None, K=cam.K)
    assert raw.result.measurements is not None
    assert any("through-holes read small" in n for n in raw.result.measurements.notes)


def test_hidden_hole_is_noted() -> None:
    part, hs = _caster_plate(60, 2.5, 10.0)
    cam = T.camera_above(_centre("screen-l"), height_mm=300, tilt_deg=18, azimuth_deg=0)
    sc = T.render_part_scene("screen-l", cam, part)
    out = measure_photo(sc.image, "top", segmenter=ThresholdSegmenter(), thickness_mm=10.0, K=cam.K)
    m = out.result.measurements
    assert m is not None and not m.holes
    hidden = [n for n in m.notes if n.startswith("possible hidden hole")]
    assert len(hidden) == 2
    for (x, y), note in zip(sorted(hs), sorted(hidden), strict=True):
        assert f"({x:.1f}, {y:.1f})" in note or f"({x:.1f}," in note


def test_camera_frame_outputs() -> None:
    part, _ = _plate("screen-m", 6.0)
    cam = T.camera_above(_centre("screen-m"), height_mm=260, tilt_deg=10, azimuth_deg=30)
    sc = T.render_part_scene("screen-m", cam, part)
    out = measure_photo(sc.image, "top", segmenter=ThresholdSegmenter(), thickness_mm=6.0, K=cam.K)
    assert out.K is not None and out.R is not None and out.t_mm is not None and out.part_to_mat is not None
    np.testing.assert_allclose(out.R, cam.R, atol=2e-3)
    np.testing.assert_allclose(out.t_mm, cam.t, atol=1.0)
    assert out.photo_mask is not None and out.photo_mask.shape == sc.image.shape[:2]
    assert out.H_top is not None and out.top_px_per_mm is not None
    # the top face is closer to the camera, so it is imaged larger than the mat plane at the same spot
    assert out.top_px_per_mm > out.detection.px_per_mm_at(_centre("screen-m", 8, -4))


def _hex_bgr(h: str) -> tuple[int, int, int]:
    r, g, b = (int(h[i : i + 2], 16) for i in (1, 3, 5))
    return b, g, r


WHITE_PART = {"top_bgr": (212, 214, 214), "side_bgr": (186, 188, 188)}


def test_white_part_white_stage_fails_contrast_dark_stage_measures() -> None:
    body = T.rounded_rect_poly(105, 65, 42, 12, 2, 20)
    part = T.PrismPart(body, [T.circle_poly(118, 70, 3.5)], thickness_mm=2.0)
    part.top_bgr, part.side_bgr = WHITE_PART["top_bgr"], WHITE_PART["side_bgr"]
    cam = T.camera_above((105, 65), height_mm=260, tilt_deg=6, azimuth_deg=30)
    on_white = T.render_scene("screen-m", cam.K, cam.R, cam.t, cam.size, part)
    out = measure_photo(T.add_noise(on_white.image, 2.0), "top", segmenter=ThresholdSegmenter(), thickness_mm=2.0)
    c = next(x for x in out.result.capture.checks if str(x.name) == "contrast")
    assert c.severity == "fail" and not out.result.capture.passed
    assert "switch the screen mat to the dark stage" in c.reason
    dark = _hex_bgr(STAGE_COLOURS["dark"])
    on_dark = T.render_scene("screen-m", cam.K, cam.R, cam.t, cam.size, part, stage_bgr=dark)
    out2 = measure_photo(T.add_noise(on_dark.image, 2.0), "top", segmenter=ThresholdSegmenter(), thickness_mm=2.0)
    m = out2.result.measurements
    assert out2.result.capture.passed, out2.result.capture.retake_reason
    assert m is not None and abs(m.length.value - 42) < TOL_MM and abs(m.width.value - 12) < TOL_MM
    assert len(m.holes) == 1 and abs(m.holes[0].diameter.value - 3.5) < TOL_MM


def test_fragmented_mask_fails_contrast() -> None:
    from services.metrology.capture_gate import check_contrast

    part, _ = _plate("screen-m", 1.0)
    cam = T.camera_above(_centre("screen-m"), height_mm=260, tilt_deg=6)
    sc = T.render_part_scene("screen-m", cam, part)
    det = detect_mat(sc.image)
    c = check_contrast(sc.image, det, sc.mask, largest_fraction=0.4)
    assert c.severity == "fail"
    assert check_contrast(sc.image, det, sc.mask, largest_fraction=1.0).severity == "ok"


@pytest.mark.parametrize("colour", [(40, 46, 52), (150, 150, 150)], ids=["dark", "mid-grey"])
def test_cast_shadow_on_paper_is_not_part(colour: tuple[int, int, int]) -> None:
    cx, cy = _centre("paper-a4")
    disc = T.circle_poly(cx, cy, 16.0)
    part = T.PrismPart(disc, [], thickness_mm=10.0, top_bgr=colour, side_bgr=tuple(int(v * 0.8) for v in colour))  # type: ignore[arg-type]
    cam = T.camera_above((cx, cy), height_mm=320, tilt_deg=4, azimuth_deg=60)
    shadow = T.cast_shadow(disc, 130.0, 7.0, 0.25, 2.5)
    sc = T.render_scene("paper-a4", cam.K, cam.R, cam.t, cam.size, part, under=shadow, white_bgr=(214, 222, 226))
    img = T.add_noise(sc.image, 2.5)
    out = measure_photo(img, "top", segmenter=ThresholdSegmenter(), thickness_mm=10.0, K=cam.K)
    m = out.result.measurements
    assert m is not None
    if colour[0] < 100:
        assert abs(m.length.value - 16.0) < TOL_MM and abs(m.width.value - 16.0) < TOL_MM
    if colour[0] > 100:
        # A mid-grey part has its own shadow's colour (same chroma, ~2/3 of the paper's brightness): it cannot be
        # told from its shadow, so the gate sends it to a darker surface instead of trusting the outline.
        c = next(x for x in out.result.capture.checks if str(x.name) == "contrast")
        assert c.severity == "fail" and "darker surface" in c.reason
        return


def test_side_view_of_a_thin_tall_card() -> None:
    """An SD card (32 × 24 × 2.1 mm) standing on its long edge: its top edge shifts by more than its own thickness, so
    the height-corrected outline keeps only a small share of the photo outline — that is correct, not a failure."""
    cx, cy = _centre("screen-m", 30, 0)
    part = T.PrismPart(T.rect_poly(cx, cy, 32.0, 2.1, 5.0), [], thickness_mm=24.0)
    cam = T.camera_above(_centre("screen-m"), height_mm=330, tilt_deg=14, azimuth_deg=0)
    sc = T.render_part_scene("screen-m", cam, part)
    out = measure_photo(
        sc.image, "side", segmenter=ThresholdSegmenter(), thickness_mm=24.0, K=cam.K, stated_thickness_mm=24.0
    )
    m = out.result.measurements
    assert m is not None and m.thickness is not None
    assert abs(m.thickness.value - 2.1) < TOL_MM and abs(m.length.value - 32.0) < TOL_MM
    assert not any("taller than the plate" in n for n in m.notes)


def test_side_view_flags_tall_features() -> None:
    cx, cy = _centre("screen-m")
    part = T.PrismPart(T.rect_poly(cx, cy, 40, 12, 0), [], thickness_mm=20.0)
    cam = T.camera_above((cx, cy), height_mm=280, tilt_deg=6, azimuth_deg=90)
    sc = T.render_part_scene("screen-m", cam, part)
    out = measure_photo(
        sc.image, "side", segmenter=ThresholdSegmenter(), thickness_mm=20.0, K=cam.K, stated_thickness_mm=3.0
    )
    assert out.result.measurements is not None
    assert any("taller than the plate" in n for n in out.result.measurements.notes)


def _cylinder(cx: float, cy: float, length: float, d: float, ang: float, n: int = 96) -> tuple[np.ndarray, np.ndarray]:
    """Triangle mesh (mat frame, z into the table) of a cylinder lying on the mat with its axis at `ang` degrees."""
    r = d / 2
    a = np.linspace(0, 2 * np.pi, n, endpoint=False)
    ring = np.c_[np.zeros(n), r * np.cos(a), -(r + r * np.sin(a))]
    ca, sa = math.cos(math.radians(ang)), math.sin(math.radians(ang))
    rot = np.array([[ca, -sa, 0], [sa, ca, 0], [0, 0, 1]])
    ends = [ring + np.array([-length / 2, 0.0, 0.0]), ring + np.array([length / 2, 0.0, 0.0])]
    verts = np.concatenate(ends) @ rot.T + np.array([cx, cy, 0.0])
    faces = []
    for i in range(n):
        j = (i + 1) % n
        faces += [[i, j, n + j], [i, n + j, n + i]]
    c0 = len(verts)
    verts = np.r_[
        verts, [[cx - ca * length / 2, cy - sa * length / 2, -r], [cx + ca * length / 2, cy + sa * length / 2, -r]]
    ]
    for i in range(n):
        j = (i + 1) % n
        faces += [[c0, i, j], [c0 + 1, n + i, n + j]]
    return verts, np.array(faces)


@pytest.mark.parametrize(("length", "d"), [(50.5, 14.5), (16.0, 40.0)], ids=["aa-cell", "wheel-on-tread"])
def test_round_profile(length: float, d: float) -> None:
    mesh = _cylinder(120, 70, length, d, 20)
    cam = T.camera_above((105, 65), height_mm=300, tilt_deg=12, azimuth_deg=30, f_px=2000, size=(2000, 1500))
    sc = T.render_scene("screen-m", cam.K, cam.R, cam.t, cam.size, mesh)
    prism = measure_photo(sc.image, "top", segmenter=ThresholdSegmenter(), thickness_mm=d, K=cam.K)
    rnd = measure_photo(sc.image, "top", segmenter=ThresholdSegmenter(), thickness_mm=d, K=cam.K, profile="round")
    mp, mr = prism.result.measurements, rnd.result.measurements
    assert mp is not None and mr is not None
    big, small = max(length, d), min(length, d)
    err_r = max(abs(mr.length.value - big), abs(mr.width.value - small))
    err_p = max(abs(mp.length.value - big), abs(mp.width.value - small))
    assert err_r < TOL_MM and err_p > 0.3
    assert any("round profile" in n for n in mr.notes)


@pytest.mark.parametrize("thickness", [12.0, 1.0])
def test_top_view_of_a_thick_part_records_what_the_photo_allows(thickness: float) -> None:
    """A top photo reads every edge at the stated height; an end that sat lower would read short. The reading is
    the low end of `bound_mm` and the mat-plane reading the high end; the spread grows with the part's height."""
    cx, cy = _centre("screen-m", 10, 0)
    part = T.PrismPart(T.rect_poly(cx, cy, 50.0, 14.0, 20.0), [], thickness_mm=thickness)
    cam = T.camera_above(_centre("screen-m"), height_mm=330, tilt_deg=4, azimuth_deg=30)
    sc = T.render_part_scene("screen-m", cam, part)
    out = measure_photo(sc.image, "top", segmenter=ThresholdSegmenter(), thickness_mm=thickness, K=cam.K)
    m = out.result.measurements
    assert m is not None and m.length.bound_mm is not None
    lo, hi = m.length.bound_mm
    assert lo == m.length.value and abs(lo - 50.0) < TOL_MM
    if thickness > 5:
        assert hi - lo > 1.0 and any("a side photo settles it" in n for n in m.notes)
    else:
        assert hi - lo < 0.3


def test_see_through_holes_a_model_mask_closed_come_back_from_the_threshold() -> None:
    """Live, 2026-10-29: SAM 3.1 closed a countersunk pivot the threshold mask still saw through. A model mask without
    the openings gets them back from the colour threshold and measures exactly like the same mask with them open (a
    model mask has no soft edge map, so both read about 0.2 mm small here; that is the binary edge, not this rule)."""
    from services.metrology.segment import SegContext, SegResult, fill_holes

    class Model:
        def __init__(self, closed: bool) -> None:
            self.closed = closed

        def segment(self, img: np.ndarray, prompt: str, *, context: SegContext | None = None) -> SegResult:
            thr = ThresholdSegmenter().segment(img, prompt, context=context).mask
            return SegResult(fill_holes(thr) if self.closed else thr, 0.95, "sam-3.1", prompt=prompt)

    part, _ = _caster_plate(20, 5.0, 10.0)
    cam = T.camera_above(_centre("screen-l"), height_mm=330, tilt_deg=18, azimuth_deg=160)
    sc = T.render_part_scene("screen-l", cam, part)
    closed = measure_photo(sc.image, "top", segmenter=Model(True), thickness_mm=10.0, K=cam.K).result.measurements
    opened = measure_photo(sc.image, "top", segmenter=Model(False), thickness_mm=10.0, K=cam.K).result.measurements
    assert closed is not None and opened is not None and len(closed.holes) == 4
    assert any("taken from the colour threshold" in n for n in closed.notes)
    assert [h.diameter.value for h in closed.holes] == [h.diameter.value for h in opened.holes]
    assert all(abs(h.diameter.value - 5.0) < 0.3 for h in closed.holes)
    # a thin part keeps the model mask as it is: there is no cylinder fit to decide what an opening would be
    thin = measure_photo(sc.image, "top", segmenter=Model(True), thickness_mm=None, K=cam.K).result.measurements
    assert thin is not None and not thin.holes
