"""Narrated walk-around points: every proposed (time, pixel) is checked on its decoded frame before it is measured."""

from __future__ import annotations

from pathlib import Path

import pytest
from shapely.geometry import Polygon

from services.common.paths import REPO_ROOT
from services.metrology import narration as N
from services.metrology.points import region_grow_points

CLIP = REPO_ROOT / "data" / "synthetic" / "samples" / "demo-caster-wheel" / "orbit.mp4"  # SYNTHETIC, silent


@pytest.fixture(scope="module")
def clip() -> bytes:
    if not CLIP.exists():
        pytest.skip("synthetic demo clip missing")
    return Path(CLIP).read_bytes()


def test_audio_track_detection(clip: bytes) -> None:
    assert not N.has_audio_track(clip)
    mp4_with_sound = b"\x00\x00\x00\x21hdlr" + b"\x00" * 8 + b"soun" + b"\x00" * 13
    assert N.has_audio_track(mp4_with_sound)
    assert N.has_audio_track(b"\x1aE\xdf\xa3....A_OPUS....")
    assert not N.has_audio_track(b"\x00\x00\x00\x21hdlr" + b"\x00" * 8 + b"vide")


def test_read_frame(clip: bytes) -> None:
    got = N.read_frame(clip, 2.0)
    assert got is not None
    idx, t, img = got
    assert idx == 30 and t == pytest.approx(2.0) and img.shape == (1080, 1920, 3)


def test_every_point_is_checked_and_kept_points_are_measured(clip: bytes) -> None:
    pts = [
        N.NarratedPoint("window", "hole", 0.53, 973.4, 455.3, "this hole"),  # an opening of the wheel (frame 8)
        N.NarratedPoint("hub", "tab", 0.53, 956.7, 528.0, "the hub"),
        N.NarratedPoint("stage", "tab", 0.53, 40.0, 40.0, "?"),
        N.NarratedPoint("outside", "hole", 0.53, 2500.0, 40.0, "?"),
        N.NarratedPoint("odd", "bore", 0.53, 956.7, 528.0, "?"),  # type: ignore[arg-type]
    ]
    checks, frames = N.locate_points(clip, pts, footprint_mat=None, thickness_mm=15.0)
    by = {c.point.name: c for c in checks}
    assert by["window"].ok and by["hub"].ok and by["window"].frame_index == 8
    assert by["stage"].reason == "the point is not on the part in that frame"
    assert "outside the 1920 x 1080 frame" in by["outside"].reason
    assert "unknown feature kind" in by["odd"].reason
    assert list(frames) == [8] and len(frames[8].checks) == 2
    feats = {f.id: f for f in N.measure_located(frames, region_grow_points(), thickness_mm=15.0)}
    assert feats["window"].ok and "diameter" in feats["window"].values
    assert all(
        N.NARRATION_NOTE in (v.evidence.note or "") for f in feats.values() for v in f.values.values() if v.evidence
    )
    assert all(v.source == "measured" for f in feats.values() for v in f.values.values())


def test_point_off_the_top_photos_footprint_is_dropped(clip: bytes) -> None:
    far = Polygon([(0, 0), (5, 0), (5, 5), (0, 5)])  # the measured footprint is elsewhere on the mat
    checks, frames = N.locate_points(clip, [N.NarratedPoint("hub", "tab", 0.53, 956.7, 528.0)], footprint_mat=far,
                                     thickness_mm=15.0)  # fmt: skip
    assert not checks[0].ok and "measured footprint" in checks[0].reason and frames == {}
    square = Polygon([(0, 0), (10, 0), (10, 10), (0, 10)])
    assert N.same_placement(square, square) and not N.same_placement(square, far)
