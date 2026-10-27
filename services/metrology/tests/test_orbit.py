"""Walk-around clips rendered from known cameras (synthetic): heights and footprints from silhouette carving."""

from dataclasses import dataclass

import numpy as np

from services.metrology import testing as T
from services.metrology.mats import get_mat
from services.metrology.measure import measure_photo
from services.metrology.orbit import measure_orbit
from services.metrology.segment import ThresholdSegmenter

ST = get_mat("screen-l").stage
C = (ST.x_mm + ST.w_mm / 2, ST.y_mm + ST.h_mm / 2)


@dataclass
class _FM:
    frame_idx: int
    t_s: float
    mask: np.ndarray
    score: float


def _clip(part: list[T.PrismPart], n: int = 12) -> tuple[list[np.ndarray], list[np.ndarray]]:
    frames, masks = [], []
    for az in np.arange(0, 360, 360 / n):
        cam = T.camera_above(C, height_mm=320, tilt_deg=28, azimuth_deg=float(az), f_px=1100, size=(1200, 900))
        sc = T.render_scene("screen-l", cam.K, cam.R, cam.t, cam.size, part)
        frames.append(sc.image)
        masks.append(sc.mask)
    return frames, masks


def test_orbit_resolves_height_of_a_tall_flange() -> None:
    cx, cy = C
    l_bracket = [
        T.PrismPart(T.rect_poly(cx, cy, 40, 20), [], 3.0),
        T.PrismPart(T.rect_poly(cx, cy - 8.5, 40, 3), [], 25.0),
    ]
    frames, masks = _clip(l_bracket)
    calls: list[tuple[str, float]] = []

    def video_call(vb: bytes, mime: str, prompt: str, fps: float) -> list[_FM]:
        calls.append((mime, fps))
        assert len(vb) > 1000  # frames were encoded into a clip for the segmenter
        return [_FM(i, i / fps, m, 0.95) for i, m in enumerate(masks)]

    out = measure_orbit(frames, video_call, fps=5)
    assert calls and out.n_sampled == 12 and out.azimuth_bins == 12 and not out.rejected
    assert out.max_height is not None and out.length is not None and out.width is not None
    assert abs(out.max_height.value - 25.0) < 0.5 and out.max_height.sigma_mm > 0
    assert out.max_height.source.value == "measured" and "orbit, 12 frames" in (out.max_height.evidence.note or "")
    assert abs(out.length.value - 40.0) < 0.3 and abs(out.width.value - 20.0) < 0.3
    assert out.hull_upper_bound_mm is not None and out.hull_upper_bound_mm >= out.max_height.value
    f = out.frames[0]
    assert out.part_to_mat is not None
    kw = f.camera_view_kwargs(out.part_to_mat)
    assert set(kw) >= {"K", "R", "t_mm", "image_mask", "image_field", "part_to_mat", "px_per_mm_local"}
    assert f.image_mask.shape == frames[0].shape[:2] and f.image_field.dtype == np.float32


def test_orbit_beats_a_single_side_photo_on_a_partial_height_ridge() -> None:
    """A part on its side: a 2 mm plate standing 20 mm tall with a 4 mm ridge only 8 mm tall on the far side. The single
    side photo has to assume the full 20 mm everywhere and trims the ridge; the orbit's footprint does not assume."""
    cx, cy = C
    part = [T.PrismPart(T.rect_poly(cx, cy, 40, 2), [], 20.0), T.PrismPart(T.rect_poly(cx, cy + 3, 40, 4), [], 8.0)]
    cam = T.camera_above(C, height_mm=330, tilt_deg=14, azimuth_deg=90)
    single = measure_photo(
        T.render_scene("screen-l", cam.K, cam.R, cam.t, cam.size, part).image,
        "side",
        segmenter=ThresholdSegmenter(),
        thickness_mm=20.0,
        K=cam.K,
    )
    assert single.result.measurements is not None and single.result.measurements.thickness is not None
    err_single = abs(single.result.measurements.thickness.value - 6.0)
    frames, _ = _clip(part)
    out = measure_orbit(frames, None, fps=5)  # per-frame threshold masks
    assert out.width is not None and out.max_height is not None
    err_orbit = abs(out.width.value - 6.0)
    assert err_orbit < 0.3 and err_single > 2.0
    assert abs(out.max_height.value - 20.0) < 0.5


def test_orbit_rejects_bad_frames_and_reports_coverage() -> None:
    cx, cy = C
    frames, _ = _clip([T.PrismPart(T.rect_poly(cx, cy, 30, 20), [], 5.0)], n=4)
    frames.append(np.full_like(frames[0], 128))
    out = measure_orbit(frames, None, fps=5)
    assert out.rejected.get("no mat") == 1 and out.n_usable == 4
    assert out.azimuth_bins == 4 and any("walk further around" in n for n in out.notes)
