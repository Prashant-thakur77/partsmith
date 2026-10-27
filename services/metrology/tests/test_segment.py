from collections.abc import Callable

import cv2
import numpy as np
import pytest

from services.metrology import testing as T
from services.metrology.calibrate import detect_mat
from services.metrology.segment import (
    ProviderSegmenter,
    SegContext,
    ThresholdSegmenter,
    fill_holes,
    mask_contour_subpx,
    mask_iou,
    merge_duplicates,
    refine_mask,
)


def _scene(part: T.PrismPart, **kw: object) -> T.Scene:
    cam = T.camera_above((105, 65), height_mm=260, tilt_deg=8, azimuth_deg=20)
    return T.render_scene("screen-m", cam.K, cam.R, cam.t, cam.size, part, **kw)  # type: ignore[arg-type]


PART = T.PrismPart(T.rect_poly(100, 60, 40, 20, 15), [T.circle_poly(105, 60, 6.0)], thickness_mm=2.0)


def test_threshold_segmenter_matches_ground_truth() -> None:
    sc = _scene(PART)
    det = detect_mat(sc.image)
    res = ThresholdSegmenter().segment(sc.image, "plastic part", context=SegContext(det))
    assert res.source == "threshold" and res.prob is not None
    assert mask_iou(res.mask, sc.mask) > 0.98
    assert res.score > 0.5
    with pytest.raises(ValueError):
        ThresholdSegmenter().segment(sc.image, "x")


def test_threshold_segmenter_light_part_and_thin_lines() -> None:
    light = T.PrismPart(PART.outline_mm, PART.holes_mm, 2.0, top_bgr=(200, 202, 206), side_bgr=(175, 176, 180))

    def lines(img: np.ndarray, cam: T.Camera) -> np.ndarray:
        img = T.draw_outline_on_mat(img, cam, T.rect_poly(150, 95, 25, 15), (40, 40, 40), 0.6)  # dark 0.6 mm box
        return T.draw_outline_on_mat(img, cam, np.array([[40.0, 40.0], [70.0, 40.0]]), (40, 40, 40), 0.5)

    sc = _scene(light, under=lines)
    det = detect_mat(sc.image)
    res = ThresholdSegmenter().segment(sc.image, "plastic part", context=SegContext(det))
    assert mask_iou(res.mask, sc.mask) > 0.97  # the drawn lines are not part


def test_ignore_hue_removes_outline_touching_the_part() -> None:
    ring = T.rect_poly(100, 60, 40, 20, 15)
    sc = _scene(PART, under=lambda img, cam: T.draw_outline_on_mat(img, cam, ring, (138, 33, 224), 0.4))
    det = detect_mat(sc.image)
    plain = ThresholdSegmenter().segment(sc.image, "p", context=SegContext(det))
    ign = ThresholdSegmenter().segment(sc.image, "p", context=SegContext(det, ignore_hue_deg=(285.0, 350.0)))
    assert mask_iou(ign.mask, sc.mask) >= mask_iou(plain.mask, sc.mask)
    assert mask_iou(ign.mask, sc.mask) > 0.97


def test_refine_mask_cleans_and_keeps_real_holes() -> None:
    ppm = 10.0
    m = np.zeros((300, 400), bool)
    cv2.rectangle(m.view(np.uint8), (50, 50), (300, 200), 1, -1)
    m = m.view(bool)
    m[100:104, 100:104] = False  # 0.16 mm² pinhole: filled
    cv2.circle(m.view(np.uint8), (220, 120), 20, 0, -1)  # Ø4 mm real hole: kept
    m[10:13, 350:353] = True  # speck: dropped
    out = refine_mask(m, ppm)
    assert out[101, 101] and not out[120, 220] and not out[11, 351]
    assert fill_holes(out)[120, 220]


def test_subpixel_contour_of_a_disc() -> None:
    r, c = 37.3, (80.4, 71.7)
    yy, xx = np.mgrid[0:160, 0:160].astype(np.float64)
    # analytic coverage via 8x supersampling
    ss = 8
    sub = (np.arange(ss) + 0.5) / ss - 0.5
    cov = np.zeros_like(xx)
    for dy in sub:
        for dx in sub:
            cov += np.hypot(xx + dx - c[0], yy + dy - c[1]) <= r
    cov /= ss * ss
    for field in (cov.astype(np.float32), cov >= 0.5):
        cs = mask_contour_subpx(field)
        outer = next(k for k in cs if not k.is_hole)
        d = np.hypot(outer.points_px[:, 0] - c[0], outer.points_px[:, 1] - c[1])
        tol = 0.03 if field.dtype != bool else 0.15
        assert abs(d.mean() - r) < tol


def _decode(png: bytes) -> np.ndarray:
    img = cv2.imdecode(np.frombuffer(png, np.uint8), cv2.IMREAD_COLOR)
    assert img is not None
    return np.asarray(img, dtype=np.uint8)


def _fake_call(
    table: dict[str, list[tuple[np.ndarray, float]]], log: list[str]
) -> Callable[[bytes, str], list[tuple[np.ndarray, float]]]:
    def call(png: bytes, prompt: str) -> list[tuple[np.ndarray, float]]:
        img = _decode(png)
        log.append(f"{prompt}:{img.shape[1]}x{img.shape[0]}")
        if prompt == "boom":
            raise RuntimeError("provider down")
        out = []
        for m, s in table.get(prompt, []):
            out.append(
                (cv2.resize(m.astype(np.uint8), (img.shape[1], img.shape[0])) > 0 if m.shape != img.shape[:2] else m, s)
            )
        return out

    return call


def test_provider_ladder_early_exit_merge_and_floor() -> None:
    h, w = 120, 160
    a = np.zeros((h, w), bool)
    a[30:80, 40:100] = True
    b = np.zeros((h, w), bool)
    b[32:82, 40:100] = True  # duplicate of a
    log: list[str] = []
    table = {"plastic part": [(a, 0.6), (b, 0.62)], "broken plastic piece": [(a, 0.9)], "clip": [(a, 0.95)]}
    seg = ProviderSegmenter(_fake_call(table, log), family_word="clip", fallback=None, crop_refine=False)
    res = seg.segment(np.zeros((h, w, 3), np.uint8))
    assert res.prompt == "broken plastic piece" and res.score == 0.9  # early exit before "clip"
    assert [a["prompt"] for a in res.attempts] == ["plastic part", "broken plastic piece"]
    assert res.attempts[0]["best_score"] == 0.62
    assert len(merge_duplicates([(a, 0.6), (b, 0.62)])) == 1
    low = ProviderSegmenter(_fake_call({"plastic part": [(a, 0.3)]}, []), fallback=None, crop_refine=False)
    r2 = low.segment(np.zeros((h, w, 3), np.uint8))
    assert not r2.mask.any() and r2.score == 0.0


def test_provider_falls_back_to_threshold_and_survives_errors() -> None:
    sc = _scene(PART)
    det = detect_mat(sc.image)
    seg = ProviderSegmenter(_fake_call({}, []), family_word="boom")
    res = seg.segment(sc.image, context=SegContext(det))
    assert res.source == "threshold"
    assert any("error" in a for a in res.attempts)
    assert mask_iou(res.mask, sc.mask) > 0.98


def test_provider_downscales_and_refines_on_crop() -> None:
    sc = _scene(PART)
    gt = sc.mask
    log: list[str] = []

    def call(png: bytes, prompt: str) -> list[tuple[np.ndarray, float]]:
        img = _decode(png)
        log.append(f"{img.shape[1]}x{img.shape[0]}")
        if img.shape[:2] == gt.shape:  # full frame: a coarse mask
            coarse = cv2.resize(
                cv2.resize(gt.astype(np.uint8), (400, 300), interpolation=cv2.INTER_AREA), gt.shape[::-1]
            )
            return [(coarse > 0, 0.9)]
        # crop: find where it came from by template matching against the photo
        res = cv2.matchTemplate(sc.image, img, cv2.TM_SQDIFF)
        _, _, (x, y), _ = cv2.minMaxLoc(res)
        x, y = int(x), int(y)
        return [(gt[y : y + img.shape[0], x : x + img.shape[1]], 0.93)]

    seg = ProviderSegmenter(call, max_side_px=4000)
    res = seg.segment(sc.image)
    assert len(log) == 2 and log[1] != log[0]
    assert res.score == pytest.approx(0.93)
    assert mask_iou(res.mask, gt) > 0.999
    log2: list[str] = []
    small = ProviderSegmenter(_fake_call({"plastic part": [(gt, 0.9)]}, log2), max_side_px=800, crop_refine=False)
    small.segment(sc.image)
    assert log2[0].endswith(":800x600")
