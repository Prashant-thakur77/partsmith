"""Narrated walk-around points: code checks every (time, pixel) a model proposes before it becomes a SAM point prompt.

A model that watched (and heard) the walk-around clip names features and points at each one in one frame. Here code
decodes that frame, finds the mat in it (the frame's own camera pose), and keeps a point only when

- it lies inside the frame,
- it lies on the part in that frame (the part's silhouette with its holes filled, so a hole's centre counts), and
- it lands on the part's footprint on the mat (the walk-around's own footprint, or the top photo's when the clip
  measured none).

Kept points are measured like user taps: one point-prompted segmentation each, fitted in millimetres by
`points.measure_features_from_points` on that frame. Every value is `source=measured`; the evidence note says the point
came from the narration. The narration itself never sets a number.
"""

from __future__ import annotations

import os
import re
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass, field

import cv2
import numpy as np
from numpy.typing import NDArray
from shapely.geometry import Point, Polygon

from .calibrate import MatDetection, MatNotFoundError, PoseEstimate, detect_mat, estimate_pose, plane_homography
from .points import FeatureKind, FeatureMeasurement, FeaturePoint, SegPointsCall, measure_features_from_points
from .segment import SegContext, Segmenter, ThresholdSegmenter, fill_holes

U8 = NDArray[np.uint8]
BoolMask = NDArray[np.bool_]
NARRATION_NOTE = "pointed by Spark (narration)"
PLACEMENT_TOL_MM = 2.0  # how far off the top photo's footprint a narrated point may land (edge features)
KINDS: tuple[FeatureKind, ...] = ("hole", "slot", "tab", "broken_edge")


def has_audio_track(video: bytes) -> bool:
    """True when the clip carries sound: an MP4/MOV `hdlr` box of type `soun`, or a WebM/Matroska audio codec id."""
    for m in re.finditer(rb"hdlr", video):
        if video[m.start() + 12 : m.start() + 16] == b"soun":
            return True
    return any(tag in video for tag in (b"A_OPUS", b"A_VORBIS", b"A_AAC", b"A_MPEG"))


def read_frame(video: bytes, t_s: float, suffix: str = ".mp4") -> tuple[int, float, U8] | None:
    """(frame index, its time, BGR image) of the frame at `t_s` seconds, or None when the clip has no such frame."""
    fd, path = tempfile.mkstemp(suffix=suffix)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(video)
        cap = cv2.VideoCapture(path)
        try:
            fps = float(cap.get(cv2.CAP_PROP_FPS)) or 30.0
            n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            idx = max(0, round(t_s * fps))
            if n > 0:
                idx = min(idx, n - 1)
            cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
            ok, img = cap.read()
            if not ok:
                return None
            return idx, idx / fps, np.asarray(img, dtype=np.uint8)
        finally:
            cap.release()
    finally:
        os.unlink(path)


@dataclass(frozen=True)
class NarratedPoint:
    name: str
    kind: FeatureKind
    t_s: float
    x_px: float
    y_px: float
    said: str = ""


@dataclass
class PointCheck:
    """What code made of one narrated point."""

    point: NarratedPoint
    ok: bool
    reason: str = ""
    frame_index: int | None = None
    mat_mm: tuple[float, float] | None = None  # where the point lands on the mat (top-face plane)

    def to_dict(self) -> dict[str, object]:
        p = self.point
        return {"name": p.name, "kind": p.kind, "t_s": p.t_s, "x_px": p.x_px, "y_px": p.y_px, "said": p.said,
                "ok": self.ok, "reason": self.reason, "frame_index": self.frame_index,
                "mat_mm": list(self.mat_mm) if self.mat_mm else None}  # fmt: skip


@dataclass
class LocatedFrame:
    index: int
    img: U8
    det: MatDetection
    pose: PoseEstimate | None
    part_mask: BoolMask
    checks: list[PointCheck] = field(default_factory=list)


def _on_mat(det: MatDetection, pose: PoseEstimate | None, x: float, y: float, height_mm: float | None) -> list[Point]:
    """The pixel on the mat plane and (when the height and pose are known) on the top-face plane, in mat mm."""
    px = np.array([[x, y]], dtype=np.float64)
    out = [Point(*det.to_mm(px)[0])]
    if pose is not None and height_mm and pose.camera_height_mm > height_mm:
        out.append(Point(*det.to_mm(px, plane_homography(pose, height_mm, det.H))[0]))
    return out


SAME_PLACE_IOU = 0.8


def same_placement(a: Polygon, b: Polygon) -> bool:
    """True when two footprints on the mat (mm) are the same placement of the part (IoU >= SAME_PLACE_IOU)."""
    try:
        union = float(a.union(b).area)
        return union > 0 and float(a.intersection(b).area) / union >= SAME_PLACE_IOU
    except Exception:  # invalid geometry: treat as moved
        return False


def locate_points(
    video: bytes,
    points: Sequence[NarratedPoint],
    *,
    footprint_mat: Polygon | None,
    thickness_mm: float | None,
    segmenter: Segmenter | None = None,
    suffix: str = ".mp4",
) -> tuple[list[PointCheck], dict[int, LocatedFrame]]:
    """Check every narrated point against its decoded frame (see module docstring). Never raises for one bad point."""
    seg = segmenter or ThresholdSegmenter()
    frames: dict[int, LocatedFrame | None] = {}
    checks: list[PointCheck] = []
    for p in points:
        c = PointCheck(p, ok=False)
        checks.append(c)
        if p.kind not in KINDS:
            c.reason = f"unknown feature kind {p.kind!r}"
            continue
        got = read_frame(video, p.t_s, suffix)
        if got is None:
            c.reason = f"the clip has no frame at {p.t_s:.2f} s"
            continue
        idx, _, img = got
        c.frame_index = idx
        h, w = img.shape[:2]
        if not (0 <= p.x_px < w and 0 <= p.y_px < h):
            c.reason = f"pixel ({p.x_px:.0f}, {p.y_px:.0f}) is outside the {w} x {h} frame"
            continue
        if idx not in frames:
            frames[idx] = _locate_frame(idx, img, seg)
        fr = frames[idx]
        if fr is None:
            c.reason = "the mat (or the part) is not visible in that frame"
            continue
        if not fr.part_mask[int(p.y_px), int(p.x_px)]:
            c.reason = "the point is not on the part in that frame"
            continue
        landing = _on_mat(fr.det, fr.pose, p.x_px, p.y_px, thickness_mm)
        c.mat_mm = (round(landing[-1].x, 3), round(landing[-1].y, 3))
        if footprint_mat is not None and not any(footprint_mat.buffer(PLACEMENT_TOL_MM).contains(q) for q in landing):
            c.reason = "the point does not land on the part's measured footprint on the mat"
            continue
        c.ok = True
        fr.checks.append(c)
    return checks, {i: f for i, f in frames.items() if f is not None and f.checks}


def _locate_frame(idx: int, img: U8, seg: Segmenter) -> LocatedFrame | None:
    try:
        det = detect_mat(img)
    except MatNotFoundError:
        return None
    try:
        pose: PoseEstimate | None = estimate_pose(det, None)
    except MatNotFoundError:
        pose = None
    r = seg.segment(img, "plastic part", context=SegContext(det))
    if not r.mask.any():
        return None
    return LocatedFrame(idx, img, det, pose, fill_holes(np.asarray(r.mask, dtype=bool)))


def measure_located(
    frames: dict[int, LocatedFrame], call: SegPointsCall, *, thickness_mm: float | None
) -> list[FeatureMeasurement]:
    """Measure every kept point on its own frame; values carry the narration provenance in their evidence note."""
    out: list[FeatureMeasurement] = []
    for fr in frames.values():
        pts = [FeaturePoint(c.point.name, c.point.kind, (c.point.x_px, c.point.y_px), "narration") for c in fr.checks]
        feats = measure_features_from_points(fr.img, fr.det, fr.pose, pts, call, thickness_mm=thickness_mm,
                                             part_mask=fr.part_mask)  # fmt: skip
        for fm in feats:
            for k, v in list(fm.values.items()):
                ev = v.evidence
                note = f"{ev.note}; {NARRATION_NOTE}" if ev is not None and ev.note else NARRATION_NOTE
                new_ev = ev.model_copy(update={"note": note}) if ev is not None else None
                fm.values[k] = v.model_copy(update={"evidence": new_ev}) if new_ev is not None else v
        out += feats
    return out
