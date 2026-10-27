"""Photo → millimetres: detect the mat, segment the part, extract its footprint in mat mm, measure it in the part frame.

Height handling. A part of thickness h has its top edges h closer to the camera, so the mat-plane homography sees
them enlarged and pushed away from the camera's nadir. When the thickness is known and the pose is solved, every
contour is mapped twice — onto the mat plane and onto the plane at height h (exact projective model, see
`calibrate.plane_homography`) — and the footprint is the intersection of the two. For a prism with vertical walls this
recovers the true outline whether an edge seen in the photo is a top edge (far side from the nadir) or a bottom edge
(near side), and through-holes come out round. Without a thickness the mat-plane footprint is reported with a note.

`measure_photo` stores nothing; the caller stores the PNG blobs and fills the `*_sha` fields.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import cv2
import numpy as np
from numpy.typing import ArrayLike, NDArray
from partsmith_schemas.common import DataOrigin, Measured, Source
from partsmith_schemas.measurement import MeasureResult, ViewKind
from scipy.ndimage import gaussian_filter1d
from shapely.geometry import Polygon

from . import overlay as ov
from .calibrate import (
    MatDetection,
    MatNotFoundError,
    PoseEstimate,
    calibration_from,
    detect_mat,
    estimate_pose,
    exif_focal35_mm,
    height_scale,
    plane_homography,
    rectify,
)
from .capture_gate import run_gate
from .features import FootprintFeatures, SigmaModel, build_measurements, largest_polygon
from .segment import Contour, SegContext, Segmenter, SegResult, mask_contour_subpx, refine_mask

F64 = NDArray[np.float64]
U8 = NDArray[np.uint8]
BoolMask = NDArray[np.bool_]

RECTIFIED_PX_PER_MM = 10.0
ASSUMED_UNKNOWN_HEIGHT_MM = 3.0  # σ of the unknown top-face height when no thickness is given
USER_THICKNESS_SIGMA_MM = 0.3
CONTOUR_SMOOTH_MM = 0.1


@dataclass
class MeasureOutput:
    result: MeasureResult
    overlay_png: bytes
    rectified_png: bytes | None = None
    mask_png: bytes | None = None  # rectified footprint mask, white = part, same grid as the rectified image
    rectified_mask: BoolMask | None = None
    px_per_mm: float = RECTIFIED_PX_PER_MM
    origin_mm: tuple[float, float] = (0.0, 0.0)  # mat mm of the rectified grid's top-left corner
    photo_mask: BoolMask | None = None  # full-frame part mask after clean-up
    footprint_mat: Polygon | None = None  # footprint in mat mm (nominal mat scale)
    features: FootprintFeatures | None = None
    detection: MatDetection | None = None
    pose: PoseEstimate | None = None
    segmentation: SegResult | None = None
    notes: list[str] = field(default_factory=list)


def decode_image(data: bytes) -> U8:
    arr = np.frombuffer(data, np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("could not decode the image")
    return np.asarray(img, dtype=np.uint8)


def _png(img: U8) -> bytes:
    ok, buf = cv2.imencode(".png", img)
    if not ok:
        raise RuntimeError("PNG encode failed")
    return bytes(buf.tobytes())


def edge_rise_px(gray: U8, pts_px: F64, max_points: int = 240, reach: float = 4.0) -> float | None:
    """Median 10–90 % rise distance (px) of the image intensity across contour points — an edge-sharpness measure."""
    n = len(pts_px)
    if n < 10:
        return None
    idx = np.linspace(0, n - 1, min(max_points, n)).astype(int)
    k = 3
    tang = np.roll(pts_px, -k, axis=0) - np.roll(pts_px, k, axis=0)
    tang = tang[idx] / np.maximum(np.linalg.norm(tang[idx], axis=1, keepdims=True), 1e-9)
    nrm = np.c_[-tang[:, 1], tang[:, 0]]
    offs = np.arange(-reach, reach + 1e-9, 0.25)
    samp = pts_px[idx][:, None, :] + offs[None, :, None] * nrm[:, None, :]
    prof = cv2.remap(
        gray.astype(np.float32),
        samp[..., 0].astype(np.float32),
        samp[..., 1].astype(np.float32),
        cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_REPLICATE,
    ).astype(np.float64)
    lo, hi = prof[:, :3].mean(axis=1), prof[:, -3:].mean(axis=1)
    ok = np.abs(hi - lo) > 15
    if ok.sum() < 5:
        return None
    q = (prof[ok] - lo[ok, None]) / (hi - lo)[ok, None]
    rises = []
    for row in q:
        a = np.flatnonzero(row >= 0.1)
        b = np.flatnonzero(row >= 0.9)
        if len(a) and len(b):
            rises.append(abs(offs[b[0]] - offs[a[0]]))
    return float(np.median(rises)) if rises else None


def smooth_ring(pts: F64, sigma_mm: float = CONTOUR_SMOOTH_MM) -> F64:
    """Gaussian smoothing along a closed contour. Removes edge noise that would otherwise inflate extreme-point
    measurements (min-area rectangle) without moving straight edges; a circle of radius r shrinks by only ≈ σ²/2r."""
    p = np.asarray(pts, dtype=np.float64)
    if len(p) < 8 or sigma_mm <= 0:
        return p
    step = float(np.mean(np.linalg.norm(np.diff(p, axis=0, append=p[:1]), axis=1)))
    s = sigma_mm / max(step, 1e-9)
    if s < 0.3:
        return p
    return np.asarray(
        np.c_[gaussian_filter1d(p[:, 0], s, mode="wrap"), gaussian_filter1d(p[:, 1], s, mode="wrap")], dtype=np.float64
    )


def _footprint_from_contours(contours: list[Contour], det: MatDetection, H: F64) -> Polygon | None:
    outers = [i for i, c in enumerate(contours) if not c.is_hole]
    if not outers:
        return None
    oi = max(outers, key=lambda i: contours[i].area_px)
    ext = smooth_ring(det.to_mm(contours[oi].points_px, H))
    holes = [
        smooth_ring(det.to_mm(c.points_px, H))
        for c in contours
        if c.is_hole and c.parent == oi and len(c.points_px) >= 8
    ]
    return largest_polygon(Polygon(ext, holes).buffer(0))


def _rasterize(poly: Polygon, origin_mm: tuple[float, float], ppm: float, shape: tuple[int, int]) -> BoolMask:
    rings = [np.asarray(poly.exterior.coords)] + [np.asarray(r.coords) for r in poly.interiors]
    px = [np.round(((r - np.asarray(origin_mm)) * ppm - 0.5) * 16).astype(np.int32) for r in rings]
    m = np.zeros(shape, np.uint8)
    cv2.fillPoly(m, px, 255, cv2.LINE_8, shift=4)
    return m > 0


def measure_photo(
    img_bytes: bytes | U8,
    view: ViewKind | str,
    *,
    segmenter: Segmenter,
    thickness_mm: float | None = None,
    K: F64 | None = None,
    dist: F64 | None = None,
    origin: DataOrigin = DataOrigin.real,
    prompt: str = "plastic part",
    mat_id: str | None = None,
    scale_correction: float = 1.0,
    scale_sigma_rel: float = 0.0,
    focal35_mm: float | None = None,
    px_per_mm: float = RECTIFIED_PX_PER_MM,
    seg_context_kwargs: dict[str, object] | None = None,
) -> MeasureOutput:
    """Measure one photo of a part on a mat.

    `thickness_mm` is the height of the part's top face above the mat in THIS view (for a side view: the part's width
    as seen from the top). `K`/`dist` come from a camera calibration; otherwise EXIF or a single-view estimate is used.
    `scale_correction` (true mm per nominal mat mm) comes from the screen card match or the paper 50 mm ruler.
    """
    view = ViewKind(view)
    if isinstance(img_bytes, bytes | bytearray):
        img = decode_image(bytes(img_bytes))
        f35 = focal35_mm if focal35_mm is not None else exif_focal35_mm(bytes(img_bytes))
    else:
        img = np.asarray(img_bytes, dtype=np.uint8)
        f35 = focal35_mm
    if img.ndim == 2:
        img = np.asarray(cv2.cvtColor(img, cv2.COLOR_GRAY2BGR), dtype=np.uint8)
    notes: list[str] = []

    try:
        det = detect_mat(img, K=K, dist=dist, mat_id=mat_id)
    except MatNotFoundError as e:
        rep = run_gate(img, None)
        notes.append(str(e))
        return MeasureOutput(
            result=MeasureResult(capture=rep),
            overlay_png=ov.banner(img, rep.retake_reason or str(e)),
            notes=notes,
        )

    pose: PoseEstimate | None
    try:
        pose = estimate_pose(det, K, focal35_mm=f35)
        notes.append(
            f"camera intrinsics: {pose.intrinsics_source}; camera {pose.camera_height_mm:.0f} mm above the mat, "
            f"tilt {pose.tilt_deg:.1f}°"
        )
    except MatNotFoundError:
        pose = None
        notes.append("camera pose could not be solved; no height correction")

    ctx = SegContext(det, **(seg_context_kwargs or {}))  # type: ignore[arg-type]
    seg = segmenter.segment(img, prompt, context=ctx)
    notes.extend(seg.notes)
    st = det.mat.stage
    ppm_img = det.px_per_mm_at((st.x_mm + st.w_mm / 2, st.y_mm + st.h_mm / 2))
    mask = refine_mask(seg.mask, ppm_img) if seg.mask.any() else seg.mask
    field_: BoolMask | NDArray[np.float32] = mask
    if seg.prob is not None and mask.any():
        inner = cv2.erode(mask.astype(np.uint8), np.ones((5, 5), np.uint8)) > 0
        outer = cv2.dilate(mask.astype(np.uint8), np.ones((5, 5), np.uint8)) > 0
        field_ = np.where(inner, 1.0, np.where(outer, seg.prob, 0.0)).astype(np.float32)

    capture = run_gate(img, det, mask if mask.any() else np.zeros_like(mask), pose=pose)
    rect = rectify(img, det.H, px_per_mm, st, K=det.K, dist=det.dist)
    calib = calibration_from(det, pose, px_per_mm, scale_correction)

    contours = mask_contour_subpx(field_) if mask.any() else []
    ground = _footprint_from_contours(contours, det, det.H) if contours else None
    if ground is None:
        return MeasureOutput(
            result=MeasureResult(capture=capture, calibration=calib),
            overlay_png=_overlay(
                img, det, mask, None, None, det.H, capture.retake_reason or "No part found on the stage."
            ),
            rectified_png=_png(rect.image),
            px_per_mm=px_per_mm,
            origin_mm=rect.origin_mm,
            photo_mask=mask,
            detection=det,
            pose=pose,
            segmentation=seg,
            notes=notes,
        )

    footprint = ground
    H_display = det.H
    hscale = 1.0
    zc = pose.camera_height_mm if pose is not None else None
    if thickness_mm is not None and thickness_mm > 0 and pose is not None and zc is not None and zc > thickness_mm:
        H_top = plane_homography(pose, thickness_mm, det.H)
        top = _footprint_from_contours(contours, det, H_top)
        inter = largest_polygon(ground.intersection(top)) if top is not None else None
        if inter is not None and inter.area > 0.5 * ground.area:
            footprint = inter
            H_display = H_top
            hscale = height_scale(zc, thickness_mm)
            notes.append(
                f"height-corrected for a {thickness_mm:.2f} mm top face: contours mapped onto the mat plane and the "
                f"top-face plane (scale {hscale:.4f} about the camera nadir) and intersected"
            )
    elif thickness_mm is None:
        notes.append(
            "thickness unknown: footprint measured on the mat plane; top edges of a thick part read slightly large"
        )

    ppm_part = det.px_per_mm_at((footprint.centroid.x, footprint.centroid.y))
    rise = edge_rise_px(np.asarray(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), dtype=np.uint8), contours[0].points_px)
    quant = 0.1 if seg.prob is not None else 0.35
    edge_px = math.hypot(0.15 * (rise if rise is not None else 2.0), quant)
    if zc is not None:
        h_sig = USER_THICKNESS_SIGMA_MM if thickness_mm is not None else ASSUMED_UNKNOWN_HEIGHT_MM
        height_rel = h_sig / zc
    else:
        height_rel = ASSUMED_UNKNOWN_HEIGHT_MM / 300.0
    sigma = SigmaModel(
        reproj_mm=det.reproj_mm_rms, edge_mm=edge_px / ppm_part, height_rel=height_rel, scale_rel=scale_sigma_rel
    )

    if view == ViewKind.side:
        thickness: Measured | None = None
    elif thickness_mm is not None:
        thickness = Measured(value=round(thickness_mm, 3), source=Source.user_stated, sigma_mm=USER_THICKNESS_SIGMA_MM)
    else:
        thickness = None

    def to_px(pts_mm: F64) -> F64:
        return det.to_px(pts_mm, H_display)

    meas, ff = build_measurements(
        footprint,
        view=view,
        origin=origin,
        sigma=sigma,
        scale=scale_correction,
        to_px=to_px,
        thickness=thickness,
        height_correction_scale=hscale,
        mask_source=seg.source,
        mask_confidence=seg.score,
        notes=notes,
    )
    if view == ViewKind.side:
        meas.thickness = Measured(
            value=meas.width.value, source=Source.measured, sigma_mm=meas.width.sigma_mm, evidence=meas.width.evidence
        )
        meas.notes.append("side view: thickness = short side of the profile")

    rmask = _rasterize(footprint, rect.origin_mm, px_per_mm, rect.image.shape[:2])
    return MeasureOutput(
        result=MeasureResult(capture=capture, calibration=calib, measurements=meas),
        overlay_png=_overlay(img, det, mask, footprint, ff, H_display, capture.retake_reason),
        rectified_png=_png(rect.image),
        mask_png=_png((rmask * 255).astype(np.uint8)),
        rectified_mask=rmask,
        px_per_mm=px_per_mm,
        origin_mm=rect.origin_mm,
        photo_mask=mask,
        footprint_mat=footprint,
        features=ff,
        detection=det,
        pose=pose,
        segmentation=seg,
        notes=meas.notes,
    )


def _overlay(
    img: U8,
    det: MatDetection,
    mask: BoolMask,
    footprint: Polygon | None,
    ff: FootprintFeatures | None,
    H: F64,
    warning: str | None,
) -> bytes:
    ring = det.to_px(det.mat.bounds.inset(-4.0).corners())
    c = ov.Canvas.from_image(img, crop=(*ring.min(axis=0), *ring.max(axis=0)))
    for q in det.corners_px:
        c.poly(q, ov.MARKER, width=max(1, c.lw - 1))
    if mask.any():
        c.tint(mask)
    if footprint is not None and ff is not None:

        def px(p_part: ArrayLike) -> F64:
            return det.to_px(ff.frame.to_mat(np.asarray(p_part, dtype=np.float64).reshape(-1, 2)), H)

        c.poly(det.to_px(np.asarray(footprint.exterior.coords), H), ov.TEAL)
        L, W = ff.length_mm, ff.width_mm
        a, b = px([[-L / 2, -W / 2]])[0], px([[L / 2, -W / 2]])[0]
        d = px([[0, -W / 2 - 5]])[0] - px([[0, -W / 2]])[0]
        c.dimension(a, b, f"{L:.2f} mm", d, 30)
        a, b = px([[L / 2, -W / 2]])[0], px([[L / 2, W / 2]])[0]
        d = px([[L / 2 + 5, 0]])[0] - px([[L / 2, 0]])[0]
        c.dimension(a, b, f"{W:.2f} mm", d, 30)
        for cf, _ in ff.holes:
            ring = px(ov.circle_pts(cf.cx, cf.cy, cf.r))
            c.poly(ring, ov.INK)
            ctr = px([[cf.cx, cf.cy]])[0]
            arm = np.linalg.norm(ring[0] - ctr) * 0.35
            c.line(ctr - np.array([arm, 0.0]), ctr + np.array([arm, 0.0]), ov.INK, 1)
            c.line(ctr - np.array([0.0, arm]), ctr + np.array([0.0, arm]), ov.INK, 1)
            c.label(f"Ø{2 * cf.r:.2f}", px([[cf.cx, cf.cy + cf.r + 3.0]])[0])
        for sf, ring_part in ff.slots:
            c.poly(px(ring_part), ov.INK)
            c.label(f"{sf.length:.2f} × {sf.width:.2f}", px([[sf.cx, sf.cy]])[0])
    if warning:
        c.top_label(warning, ov.RED)
    return c.png()
