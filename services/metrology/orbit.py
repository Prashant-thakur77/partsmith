"""Walk-around measurement: frames of a short phone clip orbiting the part on the mat.

Each sampled frame gets its own mat detection and camera pose; frames with too few markers or a poor fit are dropped
(and counted). The part mask per frame comes from a video segmenter call (SAM 3.1 tracking via providers) or, frame by
frame, from the deterministic threshold segmenter. Frames are kept spread around the part: the best frame per 15°
azimuth bin, 6 to 24 views.

Height comes from silhouette carving (visual hull) on a grid in mat millimetres: a column of the grid is solid up to the
highest point whose projection lies inside the part's silhouette in every kept view. At the part's outline that bound is
tight — the views from the opposite side see the top edge against the mat — so the maximum height is read along the
outline. Inside the outline the hull is only an upper bound (a top face is never a silhouette edge from above). The
footprint is the hull's bottom slice, which no longer depends on an assumed height: this is what resolves the
side-photo thickness and tall-feature ambiguity.
"""

from __future__ import annotations

import math
import os
import tempfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

import cv2
import numpy as np
from numpy.typing import NDArray
from partsmith_schemas.common import Evidence, Measured, Source
from shapely.geometry import Polygon

from .calibrate import (
    MatDetection,
    MatNotFoundError,
    PoseEstimate,
    apply_h,
    detect_mat,
    estimate_focal_px,
    estimate_pose,
)
from .features import largest_polygon, min_area_rect, part_frame_from
from .segment import SegContext, Segmenter, ThresholdSegmenter, mask_contour_subpx, refine_mask

F64 = NDArray[np.float64]
F32 = NDArray[np.float32]
U8 = NDArray[np.uint8]
BoolMask = NDArray[np.bool_]

MIN_MARKERS = 4
MAX_REPROJ_PX = 1.5
MIN_VIEWS = 6
MAX_VIEWS = 24
AZIMUTH_BIN_DEG = 15.0
GRID_MM = 0.5
Z_MAX_MM = 80.0
RIM_INSET_MM = 0.05  # sample the outline this far inside (the hull rises by inset / tan(tilt) inwards)
RIM_STEP_MM = 0.25
EDGE_SIGMA_PX = 0.3  # 1σ of a silhouette edge in a frame (sub-pixel contour on a clean mask)


class FrameMaskLike(Protocol):
    frame_idx: int
    t_s: float
    mask: Any
    score: float


SegVideoCall = Callable[[bytes, str, str, float], Sequence[FrameMaskLike]]


@dataclass
class OrbitFrame:
    """One kept frame, in the shape the camera-frame verifier takes (`verifier.camera.CameraView`)."""

    frame_idx: int
    t_s: float
    K: F64
    R: F64
    t_mm: F64
    dist: F64
    image_mask: BoolMask
    image_field: F32
    image_size: tuple[int, int]
    px_per_mm_local: float
    H_ground: F64
    azimuth_deg: float
    tilt_deg: float
    reproj_px: float
    n_markers: int
    mask_source: str
    mask_score: float
    top_height_mm: float | None = None

    def camera_view_kwargs(self, part_to_mat: F64) -> dict[str, Any]:
        return {
            "K": self.K,
            "R": self.R,
            "t_mm": self.t_mm,
            "image_mask": self.image_mask,
            "image_field": self.image_field,
            "part_to_mat": part_to_mat,
            "px_per_mm_local": self.px_per_mm_local,
            "image_size": self.image_size,
            "dist": self.dist,
            "top_height_mm": self.top_height_mm,
            "H_ground": self.H_ground,
        }


@dataclass
class OrbitOutput:
    frames: list[OrbitFrame]
    n_sampled: int
    n_usable: int
    rejected: dict[str, int]
    azimuth_bins: int
    mat_id: str | None = None
    footprint_mat: Polygon | None = None
    length: Measured | None = None
    width: Measured | None = None
    max_height: Measured | None = None
    hull_upper_bound_mm: float | None = None
    height_map: F32 | None = None  # (ny, nx) hull height per grid cell, NaN outside the footprint
    grid_origin_mm: tuple[float, float] = (0.0, 0.0)  # mat mm of cell (0, 0)'s centre
    grid_step_mm: float = GRID_MM
    part_to_mat: F64 | None = None
    notes: list[str] = field(default_factory=list)


# ---------------------------------------------------------------- frames in


def _read_video(video: bytes, fps: float) -> tuple[list[tuple[int, float, U8]], float]:
    fd, path = tempfile.mkstemp(suffix=".mp4")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(video)
        cap = cv2.VideoCapture(path)
        src_fps = float(cap.get(cv2.CAP_PROP_FPS)) or 30.0
        step = max(1, round(src_fps / fps))
        out: list[tuple[int, float, U8]] = []
        i = 0
        while True:
            ok, fr = cap.read()
            if not ok:
                break
            if i % step == 0:
                out.append((i, i / src_fps, np.asarray(fr, dtype=np.uint8)))
            i += 1
        cap.release()
        return out, src_fps
    finally:
        os.unlink(path)


def _encode_video(frames: Sequence[U8], fps: float) -> bytes:
    h, w = frames[0].shape[:2]
    fd, path = tempfile.mkstemp(suffix=".mp4")
    os.close(fd)
    try:
        vw = cv2.VideoWriter(path, cv2.VideoWriter.fourcc(*"mp4v"), fps, (w, h))
        for fr in frames:
            vw.write(fr)
        vw.release()
        with open(path, "rb") as f:
            return f.read()
    finally:
        os.unlink(path)


# ---------------------------------------------------------------- per-frame geometry


@dataclass
class _Cand:
    idx: int
    t_s: float
    img: U8
    det: MatDetection
    pose: PoseEstimate | None = None


def _project(K: F64, R: F64, t: F64, X: F64) -> F64:
    Xc = X @ R.T + t
    uv = Xc @ K.T
    return np.asarray(uv[:, :2] / uv[:, 2:3], dtype=np.float64)


def _field_of(mask: BoolMask, prob: F32 | None) -> F32:
    if prob is not None:
        inner = cv2.erode(mask.astype(np.uint8), np.ones((9, 9), np.uint8)) > 0
        outer = cv2.dilate(mask.astype(np.uint8), np.ones((9, 9), np.uint8)) > 0
        return np.where(inner, 1.0, np.where(outer, prob, 0.0)).astype(np.float32)
    return np.asarray(cv2.GaussianBlur(mask.astype(np.float32), (0, 0), 0.6), dtype=np.float32)


def measure_orbit(
    video: bytes | Sequence[U8],
    segment_video_call: SegVideoCall | None = None,
    *,
    fps: float = 5.0,
    K: F64 | None = None,
    dist: F64 | None = None,
    mime: str = "video/mp4",
    prompt: str = "plastic part",
    segmenter: Segmenter | None = None,
    min_markers: int = MIN_MARKERS,
    max_reproj_px: float = MAX_REPROJ_PX,
    min_views: int = MIN_VIEWS,
    max_views: int = MAX_VIEWS,
    grid_mm: float = GRID_MM,
    z_max_mm: float = Z_MAX_MM,
) -> OrbitOutput:
    """Calibrated views, footprint and height of a part from a walk-around clip (bytes) or already-sampled frames."""
    if isinstance(video, bytes | bytearray):
        sampled, _ = _read_video(bytes(video), fps)
        video_bytes: bytes | None = bytes(video)
    else:
        sampled = [(i, i / fps, np.asarray(f, dtype=np.uint8)) for i, f in enumerate(video)]
        video_bytes = None
    rejected: dict[str, int] = {}
    notes: list[str] = []

    def reject(why: str) -> None:
        rejected[why] = rejected.get(why, 0) + 1

    cands: list[_Cand] = []
    mat_id: str | None = None
    for idx, t_s, img in sampled:
        try:
            det = detect_mat(img, K=K, dist=dist, mat_id=mat_id)
        except MatNotFoundError:
            reject("no mat")
            continue
        if det.n_markers < min_markers:
            reject(f"fewer than {min_markers} markers")
            continue
        if det.reproj_px_rms > max_reproj_px:
            reject("poor marker fit")
            continue
        mat_id = mat_id or det.mat.mat_id
        cands.append(_Cand(idx, t_s, img, det))
    out = OrbitOutput(
        frames=[],
        n_sampled=len(sampled),
        n_usable=len(cands),
        rejected=rejected,
        azimuth_bins=0,
        mat_id=mat_id,
        notes=notes,
    )
    if not cands:
        notes.append("no usable frame: keep the whole mat in view while walking around the part")
        return out

    # One camera for the whole clip: a calibration if given, else the median single-view focal estimate.
    K_use = None if K is None else np.asarray(K, dtype=np.float64)
    if K_use is None:
        fs = [f for c in cands if (f := estimate_focal_px(c.det.H, c.det.image_size)) is not None]
        if fs:
            w, h = cands[0].det.image_size
            f = float(np.median(fs))
            K_use = np.array([[f, 0, (w - 1) / 2.0], [0, f, (h - 1) / 2.0], [0, 0, 1.0]])
            notes.append(f"camera focal length estimated from {len(fs)} frames ({f:.0f} px)")
    for c in cands:
        try:
            c.pose = estimate_pose(c.det, K_use)
        except MatNotFoundError:
            c.pose = None
    cands = [c for c in cands if c.pose is not None]

    # Masks: the video segmenter for the whole clip, else per frame.
    vmasks: dict[int, tuple[BoolMask, float]] = {}
    if segment_video_call is not None:
        try:
            vb = video_bytes if video_bytes is not None else _encode_video([s[2] for s in sampled], fps)
            for fm in segment_video_call(vb, mime, prompt, fps):
                vmasks[int(fm.frame_idx)] = (np.asarray(fm.mask, dtype=bool), float(fm.score))
        except Exception as e:  # the clip still measures with the per-frame fallback
            notes.append(f"video segmentation failed ({type(e).__name__}); per-frame threshold masks used")
    seg = segmenter or ThresholdSegmenter()

    st = cands[0].det.mat.stage
    centre = np.array([st.x_mm + st.w_mm / 2, st.y_mm + st.h_mm / 2])
    frames: list[OrbitFrame] = []
    for c in cands:
        assert c.pose is not None
        h_img, w_img = c.img.shape[:2]
        prob: F32 | None = None
        if c.idx in vmasks:
            m, score = vmasks[c.idx]
            if m.shape != (h_img, w_img):
                m = cv2.resize(m.astype(np.float32), (w_img, h_img), interpolation=cv2.INTER_LINEAR) >= 0.5
            source = "sam-3.1"
        else:
            r = seg.segment(c.img, prompt, context=SegContext(c.det))
            m, score, prob, source = r.mask, r.score, r.prob, r.source
        if not m.any():
            reject("no part mask")
            continue
        ppm = c.det.px_per_mm_at((float(centre[0]), float(centre[1])))
        m = refine_mask(m, ppm)
        if m[0].any() or m[-1].any() or m[:, 0].any() or m[:, -1].any():
            reject("part cut off by the frame edge")
            continue
        C = c.pose.camera_center_mm
        az = math.degrees(math.atan2(C[1] - centre[1], C[0] - centre[0])) % 360.0
        frames.append(
            OrbitFrame(
                frame_idx=c.idx,
                t_s=c.t_s,
                K=c.pose.K,
                R=c.pose.R,
                t_mm=c.pose.t,
                dist=c.pose.dist,
                image_mask=m,
                image_field=_field_of(m, prob),
                image_size=(w_img, h_img),
                px_per_mm_local=ppm,
                H_ground=c.det.H,
                azimuth_deg=az,
                tilt_deg=c.pose.tilt_deg,
                reproj_px=c.det.reproj_px_rms,
                n_markers=c.det.n_markers,
                mask_source=source,
                mask_score=score,
            )
        )
    if not frames:
        notes.append("no frame had a usable part mask")
        return out

    # Spread over azimuth: the best frame per bin (more markers, lower residual), at most `max_views` bins.
    bins: dict[int, OrbitFrame] = {}
    for fr in frames:
        b = int(fr.azimuth_deg // AZIMUTH_BIN_DEG)
        cur = bins.get(b)
        key = (fr.n_markers, -fr.reproj_px, fr.mask_score)
        if cur is None or key > (cur.n_markers, -cur.reproj_px, cur.mask_score):
            bins[b] = fr
    kept = sorted(bins.values(), key=lambda fr: fr.azimuth_deg)
    if len(kept) > max_views:
        sel = np.linspace(0, len(kept) - 1, max_views).round().astype(int)
        kept = [kept[i] for i in sorted(set(sel.tolist()))]
    out.frames = kept
    out.azimuth_bins = len(kept)
    if len(kept) < min_views:
        notes.append(f"only {len(kept)} directions around the part (need {min_views}): walk further around it")
    _carve(out, kept, grid_mm, z_max_mm)
    return out


# ---------------------------------------------------------------- carving


def _inside_all(views: Sequence[OrbitFrame], X: F64) -> NDArray[np.bool_]:
    ok = np.ones(len(X), dtype=bool)
    for v in views:
        if not ok.any():
            break
        idx = np.flatnonzero(ok)
        uv = _project(v.K, v.R, v.t_mm, X[idx])
        if v.dist is not None and np.any(v.dist):
            rv = np.asarray(cv2.Rodrigues(v.R)[0], dtype=np.float64)
            uv = np.asarray(
                cv2.projectPoints(X[idx].reshape(-1, 1, 3), rv, v.t_mm, v.K, v.dist)[0].reshape(-1, 2), dtype=np.float64
            )
        val = cv2.remap(
            v.image_field,
            uv[:, 0:1].astype(np.float32),
            uv[:, 1:2].astype(np.float32),
            cv2.INTER_LINEAR,
            borderMode=cv2.BORDER_CONSTANT,
            borderValue=0.0,
        ).ravel()
        ok[idx] = val >= 0.5
    return ok


def _hull_heights(
    views: Sequence[OrbitFrame], cols: F64, alive: NDArray[np.bool_], z_max_mm: float
) -> tuple[F64, NDArray[np.bool_]]:
    """Hull height of each (x, y) column (bisection on z; mat z points into the table, so height h is z = −h).
    Returns (height, capped) where capped marks columns still inside at `z_max_mm`."""
    lo = np.zeros(len(cols))
    hi = np.full(len(cols), z_max_mm)
    capped = np.zeros(len(cols), dtype=bool)
    idx0 = np.flatnonzero(alive)
    if len(idx0):
        capped[idx0[_inside_all(views, np.c_[cols[idx0], np.full(len(idx0), -z_max_mm)])]] = True
    for _ in range(math.ceil(math.log2(z_max_mm / 0.02))):
        idx = np.flatnonzero(alive & ~capped)
        if len(idx) == 0:
            break
        mid = (lo[idx] + hi[idx]) / 2
        ins = _inside_all(views, np.c_[cols[idx], -mid])
        lo[idx[ins]] = mid[ins]
        hi[idx[~ins]] = mid[~ins]
    return np.where(capped, z_max_mm, lo), capped


def _carve(out: OrbitOutput, views: Sequence[OrbitFrame], grid_mm: float, z_max_mm: float) -> None:
    # Bounding box: intersection of the ground silhouettes (the hull's bottom can only be smaller).
    polys = []
    for v in views:
        cs = [c for c in mask_contour_subpx(v.image_mask) if not c.is_hole]
        if not cs:
            continue
        ring = max(cs, key=lambda c: c.area_px).points_px
        p = largest_polygon(Polygon(apply_h(v.H_ground, ring)).buffer(0))
        if p is not None:
            polys.append(p)
    if not polys:
        out.notes.append("no silhouettes to carve")
        return
    box = polys[0]
    for p in polys[1:]:
        box = box.intersection(p)
    if box.is_empty:
        out.notes.append("the silhouettes do not overlap on the mat: poses disagree")
        return
    x0, y0, x1, y1 = box.bounds
    x0, y0, x1, y1 = x0 - 2, y0 - 2, x1 + 2, y1 + 2
    xs = np.arange(x0, x1 + 1e-9, grid_mm)
    ys = np.arange(y0, y1 + 1e-9, grid_mm)
    gx, gy = np.meshgrid(xs, ys)
    cols = np.c_[gx.ravel(), gy.ravel()]
    ground = _inside_all(views, np.c_[cols, np.zeros(len(cols))])
    lo, capped = _hull_heights(views, cols, ground, z_max_mm)
    height = np.where(ground, np.where(capped, z_max_mm, lo), np.nan).reshape(gy.shape).astype(np.float32)
    out.height_map = height
    out.grid_origin_mm = (float(x0), float(y0))
    out.grid_step_mm = grid_mm
    fp_mask = np.isfinite(height)
    if not fp_mask.any():
        out.notes.append("the carved footprint is empty")
        return
    # Footprint polygon from the bottom slice (cell centres → mm).
    slices, _ = cv2.findContours(fp_mask.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    big = max(slices, key=cv2.contourArea).reshape(-1, 2).astype(np.float64)
    # The bottom slice of the hull is the intersection of the ground silhouettes: use it exactly (sub-pixel contours)
    # rather than its rasterised copy on the grid.
    fp = largest_polygon(box)
    if fp is None:
        fp = largest_polygon(Polygon(big * grid_mm + [x0, y0]).buffer(grid_mm / 2, join_style="mitre"))
    out.footprint_mat = fp
    n = len(views)
    tilt = float(np.median([v.tilt_deg for v in views]))
    ppm = float(np.median([v.px_per_mm_local for v in views]))
    ev = Evidence(view="orbit", note=f"orbit, {n} frames: visual hull")
    sig_xy = EDGE_SIGMA_PX / ppm
    if fp is not None:
        _, L, W, _ = min_area_rect(np.asarray(fp.exterior.coords))
        out.length = Measured(
            value=round(L, 3), source=Source.measured, sigma_mm=round(math.sqrt(2) * sig_xy, 3), evidence=ev
        )
        out.width = Measured(
            value=round(W, 3), source=Source.measured, sigma_mm=round(math.sqrt(2) * sig_xy, 3), evidence=ev
        )
        out.part_to_mat = part_frame_from(fp).matrix()
    # Height read ON the outline, where the hull is tight: just inside it the bound already rises by d / tan(tilt).
    if fp is None:
        return
    ring = fp.buffer(-RIM_INSET_MM).exterior if fp.buffer(-RIM_INSET_MM).geom_type == "Polygon" else fp.exterior
    n_s = max(16, int(ring.length / RIM_STEP_MM))
    pts = np.array([ring.interpolate(t).coords[0] for t in np.linspace(0, ring.length, n_s, endpoint=False)])
    rim_h, rim_cap = _hull_heights(views, pts, np.ones(len(pts), dtype=bool), z_max_mm)
    rim_h = rim_h[~rim_cap]
    if len(rim_h) == 0:
        return
    # Corners are bounded by fewer views and read high; the 90th percentile of the outline is the tallest edge.
    hmax = float(np.percentile(rim_h, 90))
    spread = float(np.percentile(rim_h, 95) - np.percentile(rim_h, 80))
    tan_t = max(math.tan(math.radians(tilt)), 0.05)
    sig_h = math.hypot(EDGE_SIGMA_PX / ppm / tan_t, RIM_INSET_MM / tan_t, spread / 2)
    out.max_height = Measured(
        value=round(hmax, 3),
        source=Source.measured,
        sigma_mm=round(sig_h, 3),
        evidence=Evidence(view="orbit", note=f"orbit, {n} frames: visual hull along the outline"),
    )
    upper = float(np.nanmax(height))
    out.hull_upper_bound_mm = round(upper, 3)
    if upper >= z_max_mm - 1e-6:
        out.notes.append("the hull reaches the carving ceiling inside the outline: views from higher up would bound it")
    elif upper > hmax + max(1.0, 3 * sig_h):
        out.notes.append(
            f"inside the outline the views only bound the height at {upper:.1f} mm (a top face is never a silhouette "
            "edge); taller interior features would need a side photo"
        )
