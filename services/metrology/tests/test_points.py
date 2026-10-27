"""Point-prompted feature measurement on synthetic renders (the point segmenter is the deterministic region-grow mock)."""

import math

import numpy as np
import pytest

from services.metrology import testing as T
from services.metrology.mats import get_mat
from services.metrology.measure import MeasureOutput, measure_photo
from services.metrology.points import (
    POINT_NOTE,
    FeatureKind,
    FeatureMeasurement,
    FeaturePoint,
    measure_features_from_points,
    merge_holes,
    outline_hole_quality,
    region_grow_points,
)
from services.metrology.segment import ThresholdSegmenter

TOL_MM = 0.15


def _centre(mat_id: str, dx: float = 0.0, dy: float = 0.0) -> tuple[float, float]:
    st = get_mat(mat_id).stage
    return st.x_mm + st.w_mm / 2 + dx, st.y_mm + st.h_mm / 2 + dy


def _run(
    part: T.PrismPart, holes: list[tuple[float, float]], cam: T.Camera, mat_id: str, kind: FeatureKind = "hole"
) -> tuple[MeasureOutput, list[FeatureMeasurement]]:
    sc = T.render_part_scene(mat_id, cam, part)
    out = measure_photo(sc.image, "top", segmenter=ThresholdSegmenter(), thickness_mm=part.thickness_mm, K=cam.K)
    h = part.thickness_mm
    pts = []
    for i, (x, y) in enumerate(holes):
        u, v = cam.project(np.array([[x, y, -h]]))[0]
        pts.append(FeaturePoint(f"f{i}", kind, (float(u), float(v))))
    assert out.detection is not None
    fms = measure_features_from_points(
        sc.image,
        out.detection,
        out.pose,
        pts,
        region_grow_points(),
        thickness_mm=h,
        mask_source="mock-points",
        part_mask=out.photo_mask,
    )
    return out, fms


def test_points_find_hidden_holes_the_outline_missed() -> None:
    """Ø2.5 bores through a 10 mm plate, far from the camera: no mat shows through, so the outline pass sees no hole.
    Pointing at them, the top-opening rim (bore wall vs top face) gives the diameter on the top-face plane."""
    cx, cy = _centre("screen-l", 60, 0)
    holes = [(cx - 15, cy), (cx + 15, cy)]
    part = T.PrismPart(T.rounded_rect_poly(cx, cy, 50, 24, 4), [T.circle_poly(x, y, 2.5) for x, y in holes], 10.0)
    cam = T.camera_above(_centre("screen-l"), height_mm=300, tilt_deg=18, azimuth_deg=0)
    out, fms = _run(part, holes, cam, "screen-l")
    m = out.result.measurements
    assert m is not None and not m.holes
    for fm, (x, y) in zip(fms, holes, strict=True):
        assert fm.ok, fm.reason
        assert abs(fm.values["diameter"].value - 2.5) < TOL_MM
        assert fm.center_mm is not None
        assert math.hypot(fm.center_mm[0] - x, fm.center_mm[1] - y) < TOL_MM
        ev = fm.values["diameter"].evidence
        assert (
            ev is not None
            and ev.note is not None
            and ev.note.startswith(POINT_NOTE)
            and ev.pixels == [list(map(lambda v: round(v, 2), fm.point_px))]
        )
    merged, notes = merge_holes(m, outline_hole_quality(out), fms)
    assert len(merged) == 2 and all("did not see it" in n for n in notes)


def test_points_match_outline_accuracy_on_see_through_holes() -> None:
    cx, cy = _centre("screen-l", 20, 0)
    holes = [(cx + dx, cy + dy) for dx in (-17, 17) for dy in (-17, 17)]
    part = T.PrismPart(T.rounded_rect_poly(cx, cy, 50, 50, 5), [T.circle_poly(x, y, 5.0) for x, y in holes], 10.0)
    cam = T.camera_above(_centre("screen-l"), height_mm=330, tilt_deg=18, azimuth_deg=160)
    out, fms = _run(part, holes, cam, "screen-l")
    m = out.result.measurements
    assert m is not None and len(m.holes) == 4
    outline_err = max(abs(h.diameter.value - 5.0) for h in m.holes)
    point_err = max(abs(fm.values["diameter"].value - 5.0) for fm in fms)
    assert all(fm.ok for fm in fms)
    assert point_err < TOL_MM and point_err <= outline_err + 0.05
    merged, notes = merge_holes(m, outline_hole_quality(out), fms)
    assert len(merged) == 4 and len(notes) == 4  # every point matched an outline hole


def test_slot_and_tab_from_points() -> None:
    cx, cy = _centre("screen-m", 0, 0)
    slot = T.slot_poly(cx - 8, cy, 12.0, 4.0, 0.0)
    part = T.PrismPart(T.rect_poly(cx, cy, 44, 20), [slot], 2.0)
    cam = T.camera_above((cx, cy), height_mm=260, tilt_deg=8, azimuth_deg=40)
    _, fms = _run(part, [(cx - 8, cy)], cam, "screen-m", kind="slot")
    fm = fms[0]
    assert fm.ok and "obround" in fm.method
    assert abs(fm.values["length"].value - 12.0) < TOL_MM and abs(fm.values["width"].value - 4.0) < TOL_MM


def test_merge_rule_prefers_better_fit_only() -> None:
    from partsmith_schemas.common import Measured
    from partsmith_schemas.measurement import Hole, Measurements, ViewKind

    from services.metrology.points import FeatureMeasurement

    meas = Measurements(
        view=ViewKind.top,
        origin="synthetic",
        outline_mm=[(0, 0), (1, 0), (1, 1)],
        holes=[Hole(id="hole_1", center_mm=(0.0, 0.0), diameter=Measured(value=4.0))],
        length=Measured(value=1),
        width=Measured(value=1),
        area_mm2=1.0,
        part_to_mat=np.eye(3).tolist(),
    )
    worse = FeatureMeasurement(
        "p", "hole", (0, 0), ok=True, center_mm=(0.1, 0.0), quality=0.05, values={"diameter": Measured(value=4.3)}
    )
    better = FeatureMeasurement(
        "p", "hole", (0, 0), ok=True, center_mm=(0.1, 0.0), quality=0.001, values={"diameter": Measured(value=4.1)}
    )
    holes, _ = merge_holes(meas, [0.01], [worse])
    assert holes[0].diameter.value == 4.0
    holes, notes = merge_holes(meas, [0.01], [better])
    assert holes[0].diameter.value == 4.1 and "point measurement used" in notes[0]


def test_failed_call_is_one_failed_feature() -> None:
    cx, cy = _centre("screen-m")
    part = T.PrismPart(T.rect_poly(cx, cy, 40, 20), [T.circle_poly(cx, cy, 5)], 2.0)
    cam = T.camera_above((cx, cy), height_mm=260, tilt_deg=5)
    sc = T.render_part_scene("screen-m", cam, part)
    out = measure_photo(sc.image, "top", segmenter=ThresholdSegmenter(), thickness_mm=2.0, K=cam.K)

    def boom(*_: object) -> list[tuple[np.ndarray, float]]:
        raise RuntimeError("down")

    assert out.detection is not None
    fms = measure_features_from_points(
        sc.image, out.detection, out.pose, [FeaturePoint("a", "hole", (10.0, 10.0))], boom
    )
    assert not fms[0].ok and fms[0].reason is not None and "segmentation failed" in fms[0].reason


@pytest.mark.parametrize("tol", [14.0])
def test_mock_is_deterministic(tol: float) -> None:
    img = np.full((60, 80, 3), 200, np.uint8)
    img[20:40, 30:50] = 40
    import cv2

    png = cv2.imencode(".png", img)[1].tobytes()
    call = region_grow_points(tol)
    a = call(png, [(40.0, 30.0)], [], None)
    b = call(png, [(40.0, 30.0)], [], None)
    assert len(a) == 1 and 300 <= a[0][0].sum() <= 400 and np.array_equal(a[0][0], b[0][0])
    assert call(png, [(40.0, 30.0)], [(45.0, 35.0)], None) == []
