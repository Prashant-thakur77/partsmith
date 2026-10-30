"""The two images a reviewer pins on: the job's rectified top photo and the same photo with the model drawn over it.

Both have the same pixel size, so a pin's normalised (u, v) is the same point on either. A committed replay keeps its
rectified photo only as a smaller JPEG; the model is drawn on that JPEG at its own scale (the original grid size comes
from the original blob when it exists, else from the mat's stage at the recorded px/mm).
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any

import cv2
import numpy as np

from services.agent.jobs import Job
from services.agent.orchestrator import image_size
from services.common import blobs
from services.common.images import decode_bgr

FILL_BGR = (230, 140, 70)
FILL_ALPHA = 0.35
JPEG_QUALITY = 88
FOCUS_MARGIN_MM = 12.0  # room around the part when the review page zooms to it

_cache: dict[tuple[str, str], str] = {}
_lock = threading.Lock()


def top_rectified_key(job: Job) -> str | None:
    """The blob of the job's rectified top photo: the latest `rectified` artifact for the top view (a replay's points
    at its re-encoded JPEG), else the key in rectified.json."""
    for e in reversed(job.events):
        if e.t == "artifact" and e.kind == "rectified" and str(e.label or "").startswith("top") and blobs.exists(e.sha):
            return str(e.sha)
    rect = job.read_json("rectified.json") or {}
    key = rect.get("sha")
    return str(key) if isinstance(key, str) and blobs.exists(key) else None


def _grid_size(job: Job, rect: dict[str, Any]) -> tuple[int, int] | None:
    """(width, height) of the rectified grid the job measured on (px_per_mm × the mat stage)."""
    key = rect.get("sha")
    if isinstance(key, str) and blobs.exists(key):
        return image_size(blobs.get(key))
    mat_id = ((job.read_json("state.json") or {}).get("calibration") or {}).get("mat_id")
    if not mat_id:
        return None
    try:
        from services.metrology.mats import get_mat

        st = get_mat(str(mat_id)).stage
    except Exception:
        return None
    ppm = float(rect["px_per_mm"])
    return max(1, round(st.w_mm * ppm)), max(1, round(st.h_mm * ppm))


Projection = tuple[np.ndarray[Any, Any], dict[str, Any], float, Callable[[Any], np.ndarray[Any, Any]]]


def _projection(job: Job, key: str) -> Projection | None:
    """The decoded photo `key`, the job's model outline, px/mm on that photo, and part-frame mm → photo px (×16, for
    cv2's sub-pixel `shift=4`). None without a rectified grid, an outline or a part pose."""
    rect = job.read_json("rectified.json")
    outline = job.read_json("outline.json")
    top = (job.read_json("measurements.json") or {}).get("top") or {}
    if not rect or not outline or not top.get("part_to_mat"):
        return None
    try:
        img = decode_bgr(blobs.get(key))
    except ValueError:
        return None
    h, w = img.shape[:2]
    grid = _grid_size(job, rect) or (w, h)
    ppm = float(rect["px_per_mm"]) * w / grid[0]
    origin = np.asarray(rect["origin_mm"], dtype=np.float64)
    M = np.asarray(top["part_to_mat"], dtype=np.float64)

    def to_px(pts: Any) -> np.ndarray[Any, Any]:
        p = np.asarray(pts, dtype=np.float64).reshape(-1, 2)
        mat = p @ M[:2, :2].T + M[:2, 2]
        return np.asarray(np.round(((mat - origin) * ppm - 0.5) * 16), dtype=np.int32)

    return img, outline, ppm, to_px


def part_box(job: Job, key: str, margin_mm: float = FOCUS_MARGIN_MM) -> list[float] | None:
    """[u0, v0, u1, v1]: the model outline's box on photo `key` plus `margin_mm` each side, as fractions of the image
    (clamped to 0–1), so the review page can zoom to the part. None when there is no outline."""
    proj = _projection(job, key)
    if proj is None:
        return None
    img, outline, ppm, to_px = proj
    h, w = img.shape[:2]
    pts = to_px(outline["outline_mm"]).astype(np.float64) / 16
    if not len(pts):
        return None
    m = margin_mm * ppm
    x0, y0 = pts.min(axis=0) - m
    x1, y1 = pts.max(axis=0) + m
    return [
        round(float(max(0.0, x0 / w)), 4),
        round(float(max(0.0, y0 / h)), 4),
        round(float(min(1.0, x1 / w)), 4),
        round(float(min(1.0, y1 / h)), 4),
    ]


def model_overlay(job: Job, key: str) -> bytes | None:
    """The rectified photo `key` with the model's top outline (holes cleared) filled and stroked on it, or None when
    the job has no model outline."""
    proj = _projection(job, key)
    if proj is None:
        return None
    img, outline, ppm, to_px = proj
    h, w = img.shape[:2]
    fill = np.zeros((h, w), np.uint8)
    poly = to_px(outline["outline_mm"])
    cv2.fillPoly(fill, [poly], 255, cv2.LINE_AA, shift=4)
    for hole in outline.get("holes", []):
        c = to_px([hole["center_mm"]])[0]
        r = round(float(hole["diameter_mm"]) / 2 * ppm * 16)
        cv2.circle(fill, (int(c[0]), int(c[1])), r, 0, -1, cv2.LINE_AA, shift=4)
    a = (fill.astype(np.float32) / 255.0 * FILL_ALPHA)[:, :, None]
    out = (img.astype(np.float32) * (1 - a) + np.asarray(FILL_BGR, np.float32) * a).astype(np.uint8)
    cv2.polylines(out, [poly], True, FILL_BGR, 2, cv2.LINE_AA, shift=4)
    ok, buf = cv2.imencode(".jpg", out, [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])
    return bytes(buf.tobytes()) if ok else None


def review_images(job: Job) -> dict[str, Any]:
    """{"rectified": url, "overlay": url, "focus": [u0, v0, u1, v1]} for the review page (None when the job has no
    rectified top photo, no model outline or no part box)."""
    key = top_rectified_key(job)
    if key is None:
        return {"rectified": None, "overlay": None, "focus": None}
    with _lock:
        cached = _cache.get((job.id, key))
    if cached is None:
        png = model_overlay(job, key)
        if png is not None:
            cached = blobs.put(png, ".jpg")
            with _lock:
                _cache[(job.id, key)] = cached
    return {"rectified": blobs.url(key), "overlay": blobs.url(cached) if cached else None, "focus": part_box(job, key)}
