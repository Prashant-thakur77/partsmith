"""The "where it fits" photo: mates measured on SYNTHETIC renders with exact ground truth (mock point segmenter)."""

from __future__ import annotations

import math
from typing import Any, cast

import numpy as np
import pytest
from numpy.typing import NDArray
from partsmith_schemas.measurement import MateKind, MateMeasurement

from services.metrology.calibrate import detect_mat, estimate_pose
from services.metrology.mate import (
    MOCK_POINT_LABEL,
    MatePoint,
    _grazing_edges,
    fit_strip,
    mate_overlay,
    measure_mates,
    propose_mates,
    shaft_diameter,
)
from services.metrology.points import Box, region_grow_points
from tools.synth.mating import MateScene, MatingGT, render_mating

Px = tuple[float, float]

CASES: list[tuple[MateScene, float]] = [
    ("socket", 8.0),
    ("socket", 5.0),
    ("shaft", 6.0),
    ("shaft", 3.0),
    ("slot", 3.0),
    ("panel", 3.0),
]


def _measure(scene: MateScene, size: float, **kw: Any) -> tuple[MateMeasurement, MatingGT]:
    img, gt, _ = render_mating(scene, size, **kw)
    det = detect_mat(img)
    pose = estimate_pose(det)  # no K: the job estimates the intrinsics from the markers too
    kind = cast("MateKind", gt.kind)
    (m,) = measure_mates(img, det, pose, [MatePoint("m1", kind, gt.tap_px)], region_grow_points(),
                         mask_source="mock-points")  # fmt: skip
    return m, gt


@pytest.mark.parametrize(("scene", "size"), CASES)
def test_mate_is_measured_within_its_sigma_of_ground_truth(scene: MateScene, size: float) -> None:
    m, gt = _measure(scene, size)
    assert m.ok, m.reason
    assert m.size is not None
    err = m.size.value - gt.size_mm
    assert abs(err) <= max(m.size.sigma_mm, 0.02), (scene, size, m.size, m.method)
    assert abs(err) < 0.1
    assert m.material == gt.material
    ev = m.size.evidence
    assert ev is not None and ev.view == "mating" and ev.note is not None and ev.note.startswith("SAM point prompt")


def test_tilted_far_camera_still_within_sigma() -> None:
    tilted: list[tuple[MateScene, float]] = [("socket", 8.0), ("shaft", 6.0), ("panel", 3.0)]
    for scene, size in tilted:
        m, gt = _measure(scene, size, height_mm=400.0, tilt_deg=20.0, azimuth_deg=200.0, offset_mm=(-25.0, 10.0))
        assert m.ok and m.size is not None, m.reason
        assert abs(m.size.value - gt.size_mm) <= max(m.size.sigma_mm, 0.02), (scene, m.size)


def test_shaft_section_inverts_the_grazing_rays_exactly() -> None:
    for s_cam, h_cam, s0, d in ((0.0, 300.0, 0.0, 6.0), (-40.0, 350.0, 2.0, 3.0), (25.0, 280.0, -5.0, 10.0)):
        edges = _grazing_edges(s_cam, h_cam, s0, d / 2)
        assert edges is not None and edges[1] - edges[0] > d  # the shadow edges sit outside the shaft
        got = shaft_diameter(edges, s_cam, h_cam)
        assert got == pytest.approx(d, abs=1e-6)


def test_strip_fit_width_is_the_side_to_side_distance() -> None:
    a = np.linspace(0, 1, 400)
    top = np.c_[-20 + 40 * a, np.full_like(a, 1.5)]
    bot = np.c_[20 - 40 * a, np.full_like(a, -1.5)]
    th = math.radians(30)
    R = np.array([[math.cos(th), -math.sin(th)], [math.sin(th), math.cos(th)]])
    pts = np.r_[top, bot] @ R.T + [5, 7]
    sf = fit_strip(pts)
    assert sf is not None and sf.width == pytest.approx(3.0, abs=1e-9) and sf.length == pytest.approx(40.0, abs=1e-6)
    assert fit_strip(np.c_[np.cos(np.linspace(0, 6.28, 100)), np.sin(np.linspace(0, 6.28, 100))]) is None


def test_mock_pointer_finds_the_socket_opening_and_says_it_is_mock() -> None:
    img, gt, _ = render_mating("socket", 8.0)
    det = detect_mat(img)
    (p,) = propose_mates(img, det)
    assert p.kind == "mate_hole" and p.source == "mock"
    assert math.hypot(p.px[0] - gt.tap_px[0], p.px[1] - gt.tap_px[1]) < 8.0
    (q,) = propose_mates(img, det, "mate_peg")  # a hint the user's words gave wins over the shape guess
    assert q.kind == "mate_peg"
    assert "MOCK" in MOCK_POINT_LABEL


def test_unsure_mask_asks_for_a_retake() -> None:
    img, gt, _ = render_mating("shaft", 6.0)
    det = detect_mat(img)
    base = region_grow_points()

    def unsure(png: bytes, pos: list[Px], neg: list[Px], box: Box | None) -> list[tuple[NDArray[np.bool_], float]]:
        return [(m, 0.3) for m, _ in base(png, pos, neg, None)]

    (m,) = measure_mates(img, det, estimate_pose(det), [MatePoint("m1", "mate_peg", gt.tap_px)], unsure,
                         mask_source="sam-3.1")  # fmt: skip
    assert not m.ok and m.retake is not None and "30% sure" in m.retake and m.confidence == 0.3


def test_bad_points_fail_softly_and_the_overlay_draws() -> None:
    img, gt, _ = render_mating("socket", 8.0)
    det = detect_mat(img)
    pts = [MatePoint("m1", "mate_hole", gt.tap_px), MatePoint("off", "mate_hole", (-500.0, -500.0))]
    a, b = measure_mates(img, det, estimate_pose(det), pts, region_grow_points(), mask_source="mock-points")
    assert a.ok and not b.ok and b.reason
    png = mate_overlay(img, det, [a, b])
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
