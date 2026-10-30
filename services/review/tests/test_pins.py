"""Pin maths: normalised photo point → mat mm → part mm, the local mismatch at a pin, and the numbered pin crops."""

from __future__ import annotations

import math

import cv2
import numpy as np
import pytest
from partsmith_schemas import Pin, ViewMetrics
from pydantic import ValidationError

from services.metrology.calibrate import Rectified
from services.review import pins as P
from services.verifier.align import Rigid2D
from services.verifier.render import Frame, rasterize_polygon
from services.verifier.verify import PhotoMask, ViewResult

PPM = 20.0


def _square(frame: Frame, x0: float, y0: float, size: float) -> np.ndarray:
    sq = np.array([[x0, y0], [x0 + size, y0], [x0 + size, y0 + size], [x0, y0 + size]], dtype=np.float64)
    return rasterize_polygon(sq, [], frame)


def _view(photo_x0: float = 0.0, model_x0: float = 0.0, excluded: np.ndarray | None = None) -> ViewResult:
    frame = Frame.around(np.array([[-15.0, -15.0], [15.0, 15.0]]), PPM, margin_mm=2.0)
    photo = _square(frame, -10.0 + photo_x0, -10.0, 20.0)
    model = _square(frame, -10.0 + model_x0, -10.0, 20.0)
    metrics = ViewMetrics(view="top", iou=0.9, hausdorff_mm=1.0, hd95_mm=1.0, mean_mm=0.5)
    return ViewResult("top", "top", Rigid2D(), metrics, model, PhotoMask(photo, frame), excluded_mask=excluded)


def test_pin_validates_its_range() -> None:
    assert Pin(id=1, u=0.0, v=1.0, note="ok").v == 1.0
    for bad in ({"u": 1.2, "v": 0.5}, {"u": 0.5, "v": -0.01}):
        with pytest.raises(ValidationError):
            Pin(id=1, note="x", **bad)
    with pytest.raises(ValidationError):
        Pin(id=1, u=0.5, v=0.5, note="x" * 301)


def test_uv_to_mat_matches_the_rectified_grid() -> None:
    rect = {"sha": "x", "px_per_mm": 8.0, "origin_mm": [12.5, -3.0]}
    size = (800, 600)
    r = Rectified(np.zeros((600, 800, 3), np.uint8), 8.0, (12.5, -3.0))
    for col, row in ((0.0, 0.0), (399.0, 299.0), (799.0, 599.0), (123.4, 456.7)):
        # the centre of pixel (col, row) sits at u = (col + 0.5) / width on the normalised image
        u, v = (col + 0.5) / size[0], (row + 0.5) / size[1]
        x, y = P.uv_to_mat_mm(u, v, rect, size)
        ex, ey = r.px_to_mm(np.array([[col, row]]))[0]
        assert (x, y) == pytest.approx((ex, ey), abs=1e-9)
    assert P.uv_to_mat_mm(0.0, 0.0, rect, size) == pytest.approx((12.5, -3.0))
    assert P.uv_to_mat_mm(1.0, 1.0, rect, size) == pytest.approx((12.5 + 100.0, -3.0 + 75.0))


def test_mat_to_part_inverts_part_to_mat() -> None:
    th = math.radians(30.0)
    M = [[math.cos(th), -math.sin(th), 50.0], [math.sin(th), math.cos(th), 20.0], [0.0, 0.0, 1.0]]
    part = (3.0, -4.0)
    mat = np.asarray(M) @ np.array([*part, 1.0])
    assert P.mat_to_part_mm((float(mat[0]), float(mat[1])), M) == pytest.approx(part, abs=1e-9)


def test_local_mismatch_at_an_offset_edge() -> None:
    vr = _view(photo_x0=0.0, model_x0=1.0)  # the model is 1.0 mm right of the photo
    assert P.local_mismatch_mm(vr, (-10.0, 0.0)) == pytest.approx(1.0, abs=0.1)
    assert P.local_mismatch_mm(vr, (10.5, 0.0)) == pytest.approx(1.0, abs=0.1)
    assert P.local_mismatch_mm(vr, (0.0, 0.0)) is None  # 10 mm from every edge: nothing to compare there


def test_local_mismatch_identical_masks_and_excluded_pixels() -> None:
    assert P.local_mismatch_mm(_view(), (-10.0, 0.0)) == pytest.approx(0.0, abs=0.1)
    vr = _view(photo_x0=0.0, model_x0=1.0)
    excluded = np.zeros_like(vr.model_mask)
    excluded[:, : vr.model_mask.shape[1] // 2] = True  # the left half is a broken region, left out
    vr.excluded_mask = excluded
    assert P.local_mismatch_mm(vr, (-10.0, 0.0)) is None


def test_pin_crops_draw_a_numbered_red_ring_on_both_panes() -> None:
    vr = _view(photo_x0=0.0, model_x0=1.0)
    out = P.pin_crops(vr, [(1, (-10.0, 0.0)), (2, (14.5, 14.5))])  # the second pin sits near the frame corner
    assert len(out) == 2
    for png in out:
        img = cv2.imdecode(np.frombuffer(png, np.uint8), cv2.IMREAD_COLOR)
        assert img is not None
        red = (img[:, :, 2] > 200) & (img[:, :, 1] < 60) & (img[:, :, 0] < 60)
        half = img.shape[1] // 2
        assert red[:, :half].any() and red[:, half:].any()
