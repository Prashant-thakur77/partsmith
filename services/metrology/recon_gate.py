"""Gate for image-model reconstructions of a broken part (the model proposes, code decides).

An image model may complete the broken region on the rectified photo. The completion is accepted only when the
image is still the same photo everywhere else: every mat marker re-detects within `MARKER_MAX_SHIFT_PX` of where it was,
and the intact part is unchanged (IoU ≥ `INTACT_MIN_IOU` against its own mask, mean colour change ≤
`INTACT_MAX_COLOUR_DELTA`). What it adds outside the intact part is returned as the completion, measured in mm and
labelled `inferred` — never `measured`.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import cv2
import numpy as np
from numpy.typing import NDArray
from partsmith_schemas.common import Evidence, Measured, Source

from .calibrate import Rectified, _detector, _refine_corners
from .mats import MatSpec, get_mat

U8 = NDArray[np.uint8]
BoolMask = NDArray[np.bool_]

MARKER_MAX_SHIFT_PX = 1.0
MIN_MARKERS_COMPARED = 2
INTACT_MIN_IOU = 0.98
INTACT_MAX_COLOUR_DELTA = 12.0  # mean RGB distance (8-bit) over the intact part; re-encoding noise stays well below
INTACT_BAND_MM = 0.5  # how far around the intact part a changed edge still counts against it
MIN_COMPLETION_MM2 = 2.0
COMPLETION_NOTE = "image-model completion of the broken region (inferred, not measured)"


@dataclass
class ReconGate:
    ok: bool
    marker_shift_px: float | None
    intact_iou: float
    colour_delta: float
    reason: str
    completion_mask: BoolMask
    completion_area: Measured | None = None
    completion_outline_mm: list[list[tuple[float, float]]] = field(default_factory=list)  # mat frame
    markers_compared: int = 0


def _markers(img: U8) -> dict[int, NDArray[np.float64]]:
    gray = img if img.ndim == 2 else cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    corners, ids, _ = _detector().detectMarkers(gray)
    if ids is None:
        return {}
    c = _refine_corners(
        np.asarray(gray, dtype=np.uint8), np.stack([np.asarray(x, np.float64).reshape(4, 2) for x in corners])
    )
    return {int(i): c[k] for k, i in enumerate(ids.ravel())}


def _stage_mask(
    shape: tuple[int, int], mat: MatSpec, ppm: float, origin: tuple[float, float], inset_mm: float
) -> BoolMask:
    st = mat.stage.inset(inset_mm)
    x0 = round((st.x_mm - origin[0]) * ppm)
    y0 = round((st.y_mm - origin[1]) * ppm)
    x1 = round((st.x2_mm - origin[0]) * ppm)
    y1 = round((st.y2_mm - origin[1]) * ppm)
    m = np.zeros(shape, dtype=bool)
    m[max(y0, 0) : max(y1, 0), max(x0, 0) : max(x1, 0)] = True
    return m


def gate_reconstruction(
    original_rectified: Rectified | U8,
    reconstructed: U8,
    keep_mask: BoolMask,
    mat: MatSpec | str,
    *,
    px_per_mm: float | None = None,
    origin_mm: tuple[float, float] = (0.0, 0.0),
) -> ReconGate:
    """Check a reconstruction against the original rectified mat image (which must include the marker ring).

    `keep_mask` marks the intact original part on the rectified grid. A plain array needs `px_per_mm` (default: the
    image width over the mat width) and `origin_mm` (mat mm of the top-left corner)."""
    spec = get_mat(mat) if isinstance(mat, str) else mat
    if isinstance(original_rectified, Rectified):
        orig, ppm, origin = original_rectified.image, original_rectified.px_per_mm, original_rectified.origin_mm
    else:
        orig = np.asarray(original_rectified, dtype=np.uint8)
        ppm = px_per_mm if px_per_mm is not None else orig.shape[1] / spec.width_mm
        origin = origin_mm
    h, w = orig.shape[:2]
    keep = np.asarray(keep_mask, dtype=bool)
    empty = np.zeros((h, w), dtype=bool)
    rec = np.asarray(reconstructed, dtype=np.uint8)
    if rec.shape[:2] != (h, w):
        if abs(rec.shape[1] / rec.shape[0] - w / h) > 0.01:
            return ReconGate(False, None, 0.0, float("nan"), "the reconstruction has a different aspect ratio", empty)
        rec = np.asarray(cv2.resize(rec, (w, h), interpolation=cv2.INTER_AREA), dtype=np.uint8)
    if rec.ndim == 2:
        rec = np.asarray(cv2.cvtColor(rec, cv2.COLOR_GRAY2BGR), dtype=np.uint8)
    o3 = orig if orig.ndim == 3 else np.asarray(cv2.cvtColor(orig, cv2.COLOR_GRAY2BGR), dtype=np.uint8)

    # 1. Markers re-detect where they were.
    mo, mr = _markers(o3), _markers(rec)
    common = sorted(set(mo) & set(mr) & set(spec.ids))
    shift = max((float(np.max(np.linalg.norm(mo[i] - mr[i], axis=1))) for i in common), default=float("nan"))

    # 2. The intact part is unchanged.
    stage = _stage_mask((h, w), spec, ppm, origin, 0.0)
    band = stage & ~_stage_mask((h, w), spec, ppm, origin, 3.0)
    bg = np.median(o3[band & ~keep].reshape(-1, 3), axis=0).astype(np.float32) if (band & ~keep).any() else None
    of, rf = o3.astype(np.float32), rec.astype(np.float32)
    if bg is not None and keep.any():
        d_keep = np.linalg.norm(of[keep] - bg, axis=1)
        thr = 0.5 * float(np.median(d_keep))
        rec_part = (np.linalg.norm(rf - bg, axis=2) > thr) & stage
    else:
        rec_part = empty
    k = max(3, int(2 * INTACT_BAND_MM * ppm) | 1)
    disk_k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))

    # 3 (first): what is new — part material outside the intact part and attached to it. One-pixel slivers along the
    # intact edge are anti-aliasing, not material.
    new = cv2.morphologyEx((rec_part & ~keep).astype(np.uint8), cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    touch = cv2.dilate(keep.astype(np.uint8), np.ones((5, 5), np.uint8)) > 0
    n, lab, stats, _ = cv2.connectedComponentsWithStats(new, connectivity=8)
    completion = np.zeros((h, w), dtype=bool)
    for i in range(1, n):
        comp = lab == i
        if stats[i, cv2.CC_STAT_AREA] >= MIN_COMPLETION_MM2 * ppm**2 and np.any(comp & touch):
            completion |= comp

    # 2. The intact part is unchanged: compare masks near the intact part, away from where the completion joins it.
    near = (cv2.dilate(keep.astype(np.uint8), disk_k) > 0) & ~(cv2.dilate(completion.astype(np.uint8), disk_k) > 0)
    inter = int(np.count_nonzero(keep & rec_part & near))
    union = int(np.count_nonzero((keep | rec_part) & near))
    iou = inter / union if union else 0.0
    core = cv2.erode(keep.astype(np.uint8), disk_k) > 0
    colour_delta = float(np.mean(np.linalg.norm(rf[core] - of[core], axis=1))) if core.any() else float("nan")

    reasons: list[str] = []
    if len(common) < MIN_MARKERS_COMPARED:
        reasons.append(f"only {len(common)} markers re-detected in the reconstruction (need {MIN_MARKERS_COMPARED})")
    elif shift > MARKER_MAX_SHIFT_PX:
        reasons.append(f"the markers moved by {shift:.1f} px (> {MARKER_MAX_SHIFT_PX:.0f} px): the image was warped")
    if iou < INTACT_MIN_IOU:
        reasons.append(f"the intact part changed shape (IoU {iou:.3f} < {INTACT_MIN_IOU})")
    if not math.isnan(colour_delta) and colour_delta > INTACT_MAX_COLOUR_DELTA:
        reasons.append(f"the intact part changed colour (mean Δ {colour_delta:.1f} > {INTACT_MAX_COLOUR_DELTA:.0f})")
    ok = not reasons
    area_mm2 = float(np.count_nonzero(completion)) / ppm**2
    outlines: list[list[tuple[float, float]]] = []
    cs, _ = cv2.findContours(completion.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    for c in cs:
        p = (c.reshape(-1, 2).astype(np.float64) + 0.5) / ppm + np.asarray(origin)
        outlines.append([(round(float(x), 3), round(float(y), 3)) for x, y in p])
    note = COMPLETION_NOTE + ("; passed the reconstruction gate" if ok else "; REJECTED by the reconstruction gate")
    area = Measured(value=round(area_mm2, 2), source=Source.inferred, sigma_mm=0.0, evidence=Evidence(note=note))
    reason = (
        "; ".join(reasons)
        if reasons
        else f"accepted: markers within {shift:.2f} px, intact IoU {iou:.3f}, completion {area_mm2:.1f} mm²"
    )
    return ReconGate(
        ok, None if math.isnan(shift) else shift, iou, colour_delta, reason, completion, area, outlines, len(common)
    )
