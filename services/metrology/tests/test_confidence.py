"""Mask confidence → ±σ, low-confidence retakes, and the negative points sent with every point prompt."""

from __future__ import annotations

import itertools
from typing import Any

import numpy as np
import pytest
from partsmith_schemas.common import Measured, Source
from partsmith_schemas.measurement import CaptureReport, Hole, Measurements

from services.metrology import testing as T
from services.metrology.confidence import (
    CONFIDENCE_K,
    RETAKE_BELOW,
    retake_reason,
    sigma_for_confidence,
    widen_measurements,
)
from services.metrology.mats import get_mat
from services.metrology.measure import measure_photo, with_confidence_check
from services.metrology.points import (
    MOCK_MASK_SOURCE,
    NEG_MIN_MM,
    FeaturePoint,
    glare_point_px,
    measure_features_from_points,
    region_grow_points,
)
from services.metrology.segment import ThresholdSegmenter


def test_sigma_widens_monotonically_as_confidence_drops() -> None:
    confs = np.linspace(0.0, 1.0, 21)
    sig = [sigma_for_confidence(0.1, float(c)) for c in confs]
    assert all(a >= b for a, b in itertools.pairwise(sig))  # never narrower for a less sure mask
    assert sig[-1] == pytest.approx(0.1)  # a sure mask keeps sigma
    assert sigma_for_confidence(0.1, 0.5) == pytest.approx(0.1 * (1 + CONFIDENCE_K * 0.5))
    assert sigma_for_confidence(0.1, None) == 0.1  # a stand-in's score is not a confidence: unchanged
    assert sigma_for_confidence(0.1, 1.7) == pytest.approx(0.1)  # clipped to [0, 1]


def test_widen_measurements_touches_mask_values_only() -> None:
    m = Measurements(
        view="top", origin="synthetic", outline_mm=[(0, 0), (40, 0), (40, 20)], area_mm2=800.0,
        length=Measured(value=40.0, sigma_mm=0.1), width=Measured(value=20.0, sigma_mm=0.1),
        thickness=Measured(value=3.0, source=Source.user_stated, sigma_mm=0.3),
        holes=[Hole(id="hole_1", center_mm=(0, 0), diameter=Measured(value=5.0, sigma_mm=0.05))],
    )  # fmt: skip
    w = widen_measurements(m, 0.5, "sam-3.1")
    assert w.length.sigma_mm == pytest.approx(0.2) and w.width.sigma_mm == pytest.approx(0.2)
    assert w.holes[0].diameter.sigma_mm == pytest.approx(0.1)
    assert w.thickness is not None and w.thickness.sigma_mm == 0.3  # the user said it; the mask did not
    assert w.length.value == 40.0  # values never move, only their uncertainty
    assert w.length.evidence is not None and "mask confidence 0.50" in (w.length.evidence.note or "")
    assert widen_measurements(m, None) is m


def test_retake_below_the_stated_threshold_in_plain_words() -> None:
    assert retake_reason("the hole", RETAKE_BELOW) is None
    msg = retake_reason("the hole", 0.3)
    assert msg is not None and "30% sure of the hole" in msg and "Retake" in msg
    cap = CaptureReport(passed=True, checks=[])
    low = with_confidence_check(cap, 0.3, "the part's outline in the top photo")
    c = low.checks[-1]
    assert c.name == "mask_confidence" and c.severity == "warn" and c.passed and low.passed  # asks, never stops
    assert with_confidence_check(cap, 0.9, "x").checks[-1].severity == "ok"


@pytest.fixture(scope="module")
def scene() -> dict[str, Any]:
    st = get_mat("screen-l").stage
    cx, cy = st.x_mm + st.w_mm / 2 + 60, st.y_mm + st.h_mm / 2
    hole = (cx - 15, cy)
    part = T.PrismPart(T.rounded_rect_poly(cx, cy, 50, 24, 4), [T.circle_poly(*hole, 4.0)], 3.0)
    cam = T.camera_above((st.x_mm + st.w_mm / 2, st.y_mm + st.h_mm / 2), height_mm=300, tilt_deg=10, azimuth_deg=0)
    sc = T.render_part_scene("screen-l", cam, part)
    out = measure_photo(sc.image, "top", segmenter=ThresholdSegmenter(), thickness_mm=3.0, K=cam.K)
    u, v = cam.project(np.array([[hole[0], hole[1], -3.0]]))[0]
    return {"img": sc.image, "out": out, "pt": (float(u), float(v))}


def _measure(scene: dict[str, Any], score: float | None, source: str, negatives: Any = ()) -> tuple[Any, list[Any]]:
    seen: list[Any] = []
    base = region_grow_points()

    def call(png: bytes, pos: Any, neg: Any, box: Any) -> Any:
        seen.append(list(neg))
        return [(m, s if score is None else score) for m, s in base(png, pos, neg, box)]

    out = scene["out"]
    fms = measure_features_from_points(
        scene["img"], out.detection, out.pose, [FeaturePoint("h", "hole", scene["pt"])], call,
        thickness_mm=3.0, mask_source=source, part_mask=out.photo_mask, negatives_px=negatives,
    )  # fmt: skip
    return fms[0], seen


def test_confidence_widens_the_feature_sigma_and_low_confidence_asks_for_a_retake(scene: dict[str, Any]) -> None:
    plain, _ = _measure(scene, None, "mock-points")  # a stand-in without a confidence
    assert plain.ok and plain.confidence is None
    sure, _ = _measure(scene, 0.95, "sam-3.1")
    unsure, _ = _measure(scene, 0.6, "sam-3.1")
    d0, d1, d2 = (f.values["diameter"] for f in (plain, sure, unsure))
    assert d0.value == d1.value == d2.value  # the value is the code's fit; confidence only widens its sigma
    assert d0.sigma_mm < d1.sigma_mm < d2.sigma_mm
    assert d2.sigma_mm == pytest.approx(d0.sigma_mm * (1 + CONFIDENCE_K * 0.4), abs=2e-3)
    low, _ = _measure(scene, 0.3, "sam-3.1")
    assert not low.ok and low.retake is not None and "30% sure of the hole" in low.retake
    assert low.confidence == pytest.approx(0.3)


def test_mock_confidence_is_labelled(scene: dict[str, Any]) -> None:
    fm, _ = _measure(scene, 0.8, MOCK_MASK_SOURCE)
    ev = fm.values["diameter"].evidence
    assert fm.ok and ev is not None and "MOCK: edge-contrast proxy, not SAM" in (ev.note or "")
    low, _ = _measure(scene, 0.2, MOCK_MASK_SOURCE)
    assert not low.ok and "[MOCK" in (low.reason or "")


def test_negative_points_markers_and_extras_in_the_crop(scene: dict[str, Any]) -> None:
    from services.metrology.points import _crop_for

    out = scene["out"]
    det = out.detection
    x, y = scene["pt"]
    ppm = det.px_per_mm_at(tuple(det.to_mm(np.array([[x, y]]))[0]))
    far = (x + 6 * ppm, y + 3 * ppm)  # inside the crop: an exclude tap or a glare blob
    near = (x + 0.5 * NEG_MIN_MM * ppm, y)  # on the feature itself: would contradict the positive point
    fm, seen = _measure(scene, None, "mock-points", negatives=[far, near])
    assert seen[0] and len(seen[0]) == len(fm.negatives_px)  # what was sent = what is reported (crop offsets aside)
    assert any(np.hypot(q[0] - far[0], q[1] - far[1]) < 1e-6 for q in fm.negatives_px)
    assert not any(np.hypot(q[0] - near[0], q[1] - near[1]) < 1e-6 for q in fm.negatives_px)
    # A feature 20 mm from a mat marker: the crop reaches the marker and its centre goes first as a negative.
    c = det.corners_px.mean(axis=1)[0]
    centre = np.asarray(
        det.to_px(np.array([[get_mat("screen-l").stage.x_mm + 60, get_mat("screen-l").stage.y_mm + 60]]))
    )[0]
    d = (centre - c) / np.linalg.norm(centre - c)
    pt = (float(c[0] + d[0] * 20 * ppm), float(c[1] + d[1] * 20 * ppm))
    *_, negs = _crop_for(det, pt, scene["img"].shape[:2], [far])
    assert negs and np.hypot(negs[0][0] - c[0], negs[0][1] - c[1]) < 1e-6
    assert len(negs) <= 8


def test_glare_point_is_on_the_blown_out_blob() -> None:
    img = np.full((120, 160, 3), 90, np.uint8)
    mask = np.zeros((120, 160), bool)
    mask[30:90, 40:130] = True
    assert glare_point_px(img, mask) is None
    img[50:60, 70:85] = 255  # a blown-out highlight on the part
    pt = glare_point_px(img, mask)
    assert pt is not None and 70 <= pt[0] < 85 and 50 <= pt[1] < 60
    assert glare_point_px(img, None) is None
