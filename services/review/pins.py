"""Reviewer pins: a point the person clicked on the rectified top photo, in millimetres, and what code measures there.

The web sends (u, v) normalised to the rectified image (0–1, independent of zoom and of the JPEG a replay shows). The
job that uses the pins turns them into mat mm with its own `rectified.json` (same photo → same rectification), then
into its part frame with `part_to_mat`. The local mismatch at a pin is code's number for that note: within a disc
around the pin, the largest distance between the photo's edge and the model's edge, from the verifier's own masks.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import cv2
import numpy as np

from services.verifier.verify import ViewResult

PIN_RADIUS_MM = 3.0  # the disc a pin's local mismatch is measured in
RING_RADIUS_MM = 2.0  # the ring drawn on the evidence crops
RED = (0, 0, 255)  # BGR

BoolMask = np.ndarray[Any, np.dtype[np.bool_]]


def uv_to_mat_mm(u: float, v: float, rect: Mapping[str, Any], size_px: tuple[int, int]) -> tuple[float, float]:
    """Mat mm of a normalised point on the rectified image `size_px` = (width, height). Pixel (col, row) has its
    centre at mat (x0 + (col + 0.5) / ppm, y0 + (row + 0.5) / ppm) (`metrology.calibrate.Rectified.px_to_mm`); the
    continuous position u · width is that pixel's col + 0.5."""
    ppm = float(rect["px_per_mm"])
    x0, y0 = (float(c) for c in rect["origin_mm"])
    w, h = size_px
    col, row = u * w - 0.5, v * h - 0.5
    return x0 + (col + 0.5) / ppm, y0 + (row + 0.5) / ppm


def mat_to_part_mm(pt_mat: tuple[float, float], part_to_mat: Sequence[Sequence[float]]) -> tuple[float, float]:
    """Part-frame mm of a mat point (the inverse of the view's 3×3 `part_to_mat`)."""
    Mi = np.linalg.inv(np.asarray(part_to_mat, dtype=np.float64))
    q = Mi @ np.array([pt_mat[0], pt_mat[1], 1.0])
    return float(q[0]), float(q[1])


def _edges(mask: BoolMask) -> BoolMask:
    """Boundary pixels of a mask (inside pixels with a 4-neighbour outside)."""
    m8 = np.ascontiguousarray(mask.astype(np.uint8))
    kernel = cv2.getStructuringElement(cv2.MORPH_CROSS, (3, 3))
    inner = cv2.erode(m8, kernel, borderType=cv2.BORDER_CONSTANT, borderValue=0)
    return np.asarray((m8 > 0) & (inner == 0), dtype=np.bool_)


def _dist_to(edges: BoolMask) -> np.ndarray[Any, np.dtype[np.float32]]:
    """Per-pixel distance (px) to the nearest edge pixel."""
    src = np.ascontiguousarray(np.where(edges, 0, 255).astype(np.uint8))
    return np.asarray(cv2.distanceTransform(src, cv2.DIST_L2, cv2.DIST_MASK_PRECISE), dtype=np.float32)


def local_mismatch_mm(
    vr: ViewResult, pt_part_mm: tuple[float, float], radius_mm: float = PIN_RADIUS_MM
) -> float | None:
    """Within `radius_mm` of the pin (part frame), the larger of: photo-edge pixels' distance to the model edge, and
    model-edge pixels' distance to the photo edge. Pixels the verifier left out (`excluded_mask`, a broken region)
    are ignored. None when neither edge passes through the disc, or a mask is empty."""
    frame = vr.photo.frame
    photo = np.asarray(vr.photo.mask, dtype=np.bool_)
    model = np.asarray(vr.model_mask, dtype=np.bool_)
    if photo.shape != model.shape or not photo.any() or not model.any():
        return None
    pe, me = _edges(photo), _edges(model)
    h, w = photo.shape
    cx, cy = (float(c) for c in frame.to_px(np.asarray(pt_part_mm, dtype=np.float64)))
    rp = radius_mm * frame.px_per_mm
    x0, x1 = max(int(np.floor(cx - rp)), 0), min(int(np.ceil(cx + rp)) + 1, w)
    y0, y1 = max(int(np.floor(cy - rp)), 0), min(int(np.ceil(cy + rp)) + 1, h)
    if x1 <= x0 or y1 <= y0:
        return None  # the pin is off this view's frame
    ys, xs = np.mgrid[y0:y1, x0:x1]
    disc = np.zeros((h, w), dtype=np.bool_)
    disc[y0:y1, x0:x1] = (xs - cx) ** 2 + (ys - cy) ** 2 <= rp**2
    if vr.excluded_mask is not None and vr.excluded_mask.shape == disc.shape:
        disc &= ~np.asarray(vr.excluded_mask, dtype=np.bool_)
    near_p, near_m = pe & disc, me & disc
    if not near_p.any() and not near_m.any():
        return None
    worst = 0.0
    if near_p.any():
        worst = max(worst, float(_dist_to(me)[near_p].max()))
    if near_m.any():
        worst = max(worst, float(_dist_to(pe)[near_m].max()))
    return round(worst / frame.px_per_mm, 3)


def _crop(mask: BoolMask, x0: int, y0: int, size: int) -> BoolMask:
    """`size`² window of `mask` at (x0, y0); the part outside the mask is empty (a pin near the frame edge)."""
    out = np.zeros((size, size), dtype=np.bool_)
    h, w = mask.shape
    sx0, sy0, sx1, sy1 = max(x0, 0), max(y0, 0), min(x0 + size, w), min(y0 + size, h)
    if sx1 > sx0 and sy1 > sy0:
        out[sy0 - y0 : sy1 - y0, sx0 - x0 : sx1 - x0] = mask[sy0:sy1, sx0:sx1]
    return out


def pin_crops(vr: ViewResult, pins: Sequence[tuple[int, tuple[float, float]]], half_mm: float = 6.0) -> list[bytes]:
    """One PNG per pin (id, part-frame mm): photo | model side by side around the pin, like the judge's hotspot crops,
    with a numbered red ring at the same spot on both panes so the model knows which note is which."""
    fr = vr.photo.frame
    r = max(int(half_mm * fr.px_per_mm), 8)
    ring = max(round(RING_RADIUS_MM * fr.px_per_mm), 3)
    out: list[bytes] = []
    for pid, pt in pins:
        c = fr.to_px(np.asarray(pt, dtype=np.float64))
        x0, y0 = round(float(c[0])) - r, round(float(c[1])) - r
        p = _crop(vr.photo.mask, x0, y0, 2 * r)
        m = _crop(vr.model_mask, x0, y0, 2 * r)
        gap = 4
        pane = np.full((2 * r, 4 * r + gap, 3), 255, np.uint8)
        pane[:, : 2 * r][p] = (60, 60, 60)
        pane[:, 2 * r + gap :][m] = (200, 120, 40)
        for off in (0, 2 * r + gap):
            centre = (off + r, r)
            cv2.circle(pane, centre, ring, RED, 2, cv2.LINE_AA)
            cv2.putText(
                pane, str(pid), (off + r + ring + 3, r - ring), cv2.FONT_HERSHEY_SIMPLEX, 0.6, RED, 2, cv2.LINE_AA
            )
        ok, buf = cv2.imencode(".png", pane)
        if ok:
            out.append(bytes(buf.tobytes()))
    return out


__all__ = ["PIN_RADIUS_MM", "local_mismatch_mm", "mat_to_part_mm", "pin_crops", "uv_to_mat_mm"]
