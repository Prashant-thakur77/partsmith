"""EXIF orientation: every photo decode sees the pixels the browser shows, so a tap point lands on the same feature.

Phones store most photos sideways with an EXIF Orientation tag; the web app draws them rotated and sends tap points in
those (oriented) pixels. These tests build real JPEGs with Pillow and decode them the way the pipeline does.
"""

from __future__ import annotations

import io
import math
from collections.abc import Callable

import cv2
import numpy as np
import pytest
from PIL import Image, ImageOps

from services.agent.orchestrator import fit_png
from services.agent.providers import media
from services.common.images import decode_bgr, exif_orientation, orient, oriented_size
from services.metrology import testing as T
from services.metrology.mats import get_mat
from services.metrology.measure import decode_image, measure_photo
from services.metrology.points import FeaturePoint, measure_features_from_points, region_grow_points
from services.metrology.segment import ThresholdSegmenter

# The stored pixels for each orientation, given the upright (displayed) image: the inverse of what a viewer applies.
TO_STORED: dict[int, Callable[[np.ndarray], np.ndarray]] = {
    1: lambda a: a,
    2: lambda a: a[:, ::-1],
    3: lambda a: a[::-1, ::-1],
    4: lambda a: a[::-1],
    5: lambda a: np.swapaxes(a, 0, 1),
    6: lambda a: cv2.rotate(a, cv2.ROTATE_90_COUNTERCLOCKWISE),
    7: lambda a: np.swapaxes(a[::-1, ::-1], 0, 1),
    8: lambda a: cv2.rotate(a, cv2.ROTATE_90_CLOCKWISE),
}


def _encode(bgr: np.ndarray, orientation: int, fmt: str = "JPEG") -> bytes:
    """`bgr` is what the user sees; the file stores it as a phone would for `orientation` and tags it."""
    stored = np.ascontiguousarray(TO_STORED[orientation](bgr))
    exif = Image.Exif()
    exif[0x0112] = orientation
    buf = io.BytesIO()
    kw = {"quality": 95} if fmt == "JPEG" else {}
    Image.fromarray(stored[:, :, ::-1]).save(buf, format=fmt, exif=exif.tobytes(), **kw)
    return buf.getvalue()


def _pattern(h: int = 60, w: int = 100) -> np.ndarray:
    """Asymmetric test card (every orientation looks different)."""
    img = np.zeros((h, w, 3), np.uint8)
    img[: h // 3, : w // 4] = (0, 0, 255)
    img[h // 2 :, w // 2 :] = (255, 0, 0)
    img[:, w - 5 :] = (0, 255, 0)
    return img


@pytest.mark.parametrize("orientation", range(1, 9))
def test_decode_matches_the_displayed_image_for_every_orientation(orientation: int) -> None:
    upright = _pattern()
    data = _encode(upright, orientation, fmt="PNG")  # lossless, so the comparison is exact
    assert exif_orientation(data) == orientation
    got = decode_bgr(data)
    assert np.array_equal(got, upright)
    with Image.open(io.BytesIO(data)) as im:  # the same transform as Pillow's exif_transpose
        assert np.array_equal(got, np.asarray(ImageOps.exif_transpose(im).convert("RGB"))[:, :, ::-1])
    assert oriented_size(data) == (upright.shape[1], upright.shape[0])
    assert np.array_equal(orient(TO_STORED[orientation](upright), orientation), upright)


def test_jpeg_orientation_6_is_transposed_by_every_decode_path() -> None:
    """A real JPEG with Orientation=6: displayed 100 wide x 60 tall, stored sideways (60 wide x 100 tall)."""
    upright = _pattern(60, 100)
    data = _encode(upright, 6)
    raw = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_UNCHANGED)  # a decode that ignores the tag
    assert raw.shape[:2] == (100, 60)  # stored sideways: this is the frame a tap must NOT be read in
    for got in (decode_image(data), decode_bgr(data), media.decode_image_rgb(data)[:, :, ::-1]):
        assert got.shape[:2] == (60, 100)
        assert float(np.mean(np.abs(got.astype(int) - upright.astype(int)))) < 6.0  # JPEG noise only
    assert media.image_size(data) == (100, 60)
    small, scale = fit_png(data, 4096)  # what a model is shown
    assert scale == 1.0 and exif_orientation(small) == 1 and decode_bgr(small).shape[:2] == (60, 100)
    fitted = media.fit_image(data, 4096)
    assert exif_orientation(fitted) == 1 and decode_bgr(fitted).shape[:2] == (60, 100)


def test_a_tap_on_a_rotated_exif_photo_lands_on_the_same_hole() -> None:
    """The browser taps a hole on the photo as displayed. Upright file and sideways file + Orientation=6 must give the
    same point measurement: same hole, same centre, same diameter."""
    st = get_mat("screen-m").stage
    cx, cy = st.x_mm + st.w_mm / 2, st.y_mm + st.h_mm / 2
    hole = (cx + 8.0, cy)
    part = T.PrismPart(T.rounded_rect_poly(cx, cy, 44, 24, 3), [T.circle_poly(*hole, 5.0)], 3.0)
    cam = T.camera_above((cx, cy), height_mm=260, tilt_deg=10, azimuth_deg=0)
    scene = T.render_part_scene("screen-m", cam, part).image
    u, v = cam.project(np.array([[hole[0], hole[1], -part.thickness_mm]]))[0]
    tap = FeaturePoint("tap", "hole", (float(u), float(v)))  # browser coordinates (displayed photo)

    results = []
    for orientation in (1, 6):
        img = decode_image(_encode(scene, orientation))
        assert img.shape == scene.shape
        out = measure_photo(img, "top", segmenter=ThresholdSegmenter(), thickness_mm=part.thickness_mm, K=cam.K)
        assert out.detection is not None
        (fm,) = measure_features_from_points(
            img, out.detection, out.pose, [tap], region_grow_points(), thickness_mm=part.thickness_mm,
            mask_source="mock-points", part_mask=out.photo_mask,
        )  # fmt: skip
        assert fm.ok, fm.reason
        assert fm.center_mm is not None
        assert math.hypot(fm.center_mm[0] - hole[0], fm.center_mm[1] - hole[1]) < 0.2
        assert abs(fm.values["diameter"].value - 5.0) < 0.2
        results.append(fm)
    a, b = results
    assert a.center_mm is not None and b.center_mm is not None
    assert math.hypot(a.center_mm[0] - b.center_mm[0], a.center_mm[1] - b.center_mm[1]) < 0.05
    assert abs(a.values["diameter"].value - b.values["diameter"].value) < 0.05
