"""2-D comparison metrics between a photo mask and a model silhouette on the same mm frame (PLAN Appendix D).

- ``iou``: |A and B| / |A or B|.
- ``contour_distances_mm``: symmetric distances between the two boundaries; each boundary is resampled to <= 0.05 mm
  spacing first. Hausdorff = max of both directed maxima, HD95 = max of both 95th percentiles, mean = average of both
  directed means. Boundaries come from pixel masks, so expect a quantisation floor of about one pixel diagonal.
- over / under areas: *over* = model material the photo lacks, *under* = photo material the model lacks.
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np
import numpy.typing as npt
from scipy.spatial import cKDTree

from services.verifier.render import BoolMask, FloatArray, Frame

RESAMPLE_MM = 0.05

# Okabe-Ito colour-blind-safe palette (BGR for OpenCV).
COLOR_MATCH = (205, 205, 205)
COLOR_OVER = (0, 94, 213)  # vermillion
COLOR_UNDER = (178, 114, 0)  # blue
COLOR_EDGE = (40, 40, 40)
COLOR_WORST = (0, 0, 0)


@dataclass(frozen=True)
class ContourDistances:
    hausdorff_mm: float
    hd95_mm: float
    mean_mm: float
    worst_point_mm: tuple[float, float] | None
    worst_on: str  # "model" (a model edge far from the photo edge) or "photo"


def iou(a: BoolMask, b: BoolMask) -> float:
    a = np.asarray(a, dtype=bool)
    b = np.asarray(b, dtype=bool)
    union = int(np.count_nonzero(a | b))
    return float(np.count_nonzero(a & b) / union) if union else 0.0


def resample_closed(poly: FloatArray, spacing: float) -> FloatArray:
    """Points along a closed polyline, no two consecutive ones further apart than `spacing`."""
    if len(poly) < 2:
        return poly
    closed = np.vstack([poly, poly[:1]])
    seg = np.diff(closed, axis=0)
    seg_len = np.linalg.norm(seg, axis=1)
    out = [poly[:1]]
    for p, d, n in zip(closed[:-1], seg, seg_len, strict=True):
        k = max(int(np.ceil(n / spacing)), 1)
        ts = np.arange(1, k + 1)[:, None] / k
        out.append(p + ts * d)
    return np.vstack(out)[:-1]


def contour_points_mm(mask: BoolMask, frame: Frame, spacing_mm: float = RESAMPLE_MM) -> FloatArray:
    """All boundary curves of a mask (outer and holes) as mm points, resampled to <= spacing_mm."""
    m = np.ascontiguousarray(np.asarray(mask, dtype=np.uint8))
    contours, _ = cv2.findContours(m, cv2.RETR_LIST, cv2.CHAIN_APPROX_NONE)
    pts = [resample_closed(frame.to_mm(c.reshape(-1, 2).astype(np.float64)), spacing_mm) for c in contours if len(c)]
    if not pts:
        return np.zeros((0, 2))
    return np.vstack(pts)


def contour_distances_mm(model_pts: FloatArray, photo_pts: FloatArray) -> ContourDistances:
    """Symmetric boundary distances (mm) between two point sets that sample closed curves densely."""
    if len(model_pts) == 0 or len(photo_pts) == 0:
        return ContourDistances(float("inf"), float("inf"), float("inf"), None, "model")
    d_mp, _ = cKDTree(photo_pts).query(model_pts)
    d_pm, _ = cKDTree(model_pts).query(photo_pts)
    if d_mp.max() >= d_pm.max():
        worst, on = model_pts[int(np.argmax(d_mp))], "model"
    else:
        worst, on = photo_pts[int(np.argmax(d_pm))], "photo"
    return ContourDistances(
        hausdorff_mm=float(max(d_mp.max(), d_pm.max())),
        hd95_mm=float(max(np.percentile(d_mp, 95), np.percentile(d_pm, 95))),
        mean_mm=float((d_mp.mean() + d_pm.mean()) / 2),
        worst_point_mm=(float(worst[0]), float(worst[1])),
        worst_on=on,
    )


def mask_contour_distances(model_mask: BoolMask, photo_mask: BoolMask, frame: Frame) -> ContourDistances:
    return contour_distances_mm(contour_points_mm(model_mask, frame), contour_points_mm(photo_mask, frame))


def points_outside(pts_mm: FloatArray, frame: Frame, excluded: BoolMask | None) -> FloatArray:
    """Contour points (mm on `frame`) that do not fall on an excluded pixel."""
    if excluded is None or len(pts_mm) == 0:
        return pts_mm
    px = np.round(frame.to_px(pts_mm)).astype(int)
    h, w = excluded.shape
    inside = (px[:, 0] >= 0) & (px[:, 0] < w) & (px[:, 1] >= 0) & (px[:, 1] < h)
    hit = np.zeros(len(pts_mm), dtype=bool)
    hit[inside] = excluded[px[inside, 1], px[inside, 0]]
    out: FloatArray = pts_mm[~hit]
    return out


def over_under_mm2(photo_mask: BoolMask, model_mask: BoolMask, frame: Frame) -> tuple[float, float]:
    """(over, under) areas in mm^2: over = model & ~photo, under = photo & ~model."""
    px_area = 1.0 / frame.px_per_mm**2
    over = int(np.count_nonzero(model_mask & ~photo_mask)) * px_area
    under = int(np.count_nonzero(photo_mask & ~model_mask)) * px_area
    return float(over), float(under)


def _put(
    img: npt.NDArray[np.uint8], text: str, org: tuple[int, int], scale: float, color: tuple[int, int, int]
) -> None:
    cv2.putText(img, text, org, cv2.FONT_HERSHEY_SIMPLEX, scale, (255, 255, 255), 4, cv2.LINE_AA)
    cv2.putText(img, text, org, cv2.FONT_HERSHEY_SIMPLEX, scale, color, 1, cv2.LINE_AA)


def residual_heatmap(
    photo_mask: BoolMask,
    model_mask: BoolMask,
    frame: Frame,
    *,
    distances: ContourDistances | None = None,
    title: str = "",
    label_point_mm: tuple[float, float] | None = None,
    excluded: BoolMask | None = None,
    max_side_px: int = 1400,
    min_side_px: int = 640,
) -> bytes:
    """PNG overlay: grey = both agree, vermillion = over (model material the photo lacks), blue = under (photo
    material the model lacks). The worst boundary point is circled and labelled in mm. Colour-blind-safe palette.
    ``label_point_mm`` overrides the coordinates printed next to the worst point (e.g. part-frame mm for a photo
    crop whose `frame` is only a pixel scale)."""
    photo = np.asarray(photo_mask, dtype=bool)
    model = np.asarray(model_mask, dtype=bool)
    h, w = photo.shape
    img = np.full((h, w, 3), 255, np.uint8)
    img[photo & model] = COLOR_MATCH
    img[model & ~photo] = COLOR_OVER
    img[photo & ~model] = COLOR_UNDER
    if excluded is not None:  # hatched: left out of the comparison (broken region), not judged
        ex = np.asarray(excluded, dtype=bool)
        yy, xx = np.mgrid[0:h, 0:w]
        stripes = ((xx + yy) // 4) % 2 == 0
        img[ex] = (235, 235, 235)
        img[ex & stripes] = (150, 150, 150)
    scale = 1.0
    long_side = max(h, w)
    if long_side > max_side_px:
        scale = max_side_px / long_side
    elif long_side < min_side_px:
        scale = min_side_px / long_side
    if scale != 1.0:
        interp = cv2.INTER_AREA if scale < 1 else cv2.INTER_NEAREST
        img = np.asarray(
            cv2.resize(img, (max(1, round(w * scale)), max(1, round(h * scale))), interpolation=interp), np.uint8
        )
    for m in (photo, model):
        cs, _ = cv2.findContours(m.astype(np.uint8), cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
        cs = [np.round((c.astype(np.float64) + 0.5) * scale - 0.5).astype(np.int32) for c in cs]
        cv2.drawContours(img, cs, -1, COLOR_EDGE, 1, cv2.LINE_AA)

    H, W = img.shape[:2]
    if distances is not None and distances.worst_point_mm is not None:
        p = frame.to_px(np.array(distances.worst_point_mm))
        c = (round((p[0] + 0.5) * scale - 0.5), round((p[1] + 0.5) * scale - 0.5))
        cv2.circle(img, c, 14, COLOR_WORST, 2, cv2.LINE_AA)
        lp = label_point_mm or distances.worst_point_mm
        label = f"worst {distances.hausdorff_mm:.2f} mm at ({lp[0]:.1f}, {lp[1]:.1f})"
        org = (min(max(c[0] + 18, 4), max(W - 9 * len(label), 4)), min(max(c[1] - 18, 18), H - 6))
        _put(img, label, org, 0.5, COLOR_WORST)

    # Legend.
    rows = [(COLOR_MATCH, "model and photo agree"), (COLOR_OVER, "over: model has material the photo lacks"),
            (COLOR_UNDER, "under: photo has material the model lacks")]  # fmt: skip
    if excluded is not None and np.any(excluded):
        rows.append(((150, 150, 150), "hatched: broken region, not compared (inferred)"))
    y = 10
    if title:
        _put(img, title, (10, y + 14), 0.55, (0, 0, 0))
        y += 24
    for color, text in rows:
        cv2.rectangle(img, (10, y), (28, y + 14), color, -1)
        cv2.rectangle(img, (10, y), (28, y + 14), COLOR_EDGE, 1)
        _put(img, text, (34, y + 12), 0.45, (0, 0, 0))
        y += 20
    # 10 mm scale bar.
    bar = round(10 * frame.px_per_mm * scale)
    if bar < W - 20:
        cv2.line(img, (10, H - 12), (10 + bar, H - 12), (0, 0, 0), 2)
        _put(img, "10 mm", (10, H - 18), 0.45, (0, 0, 0))
    ok, buf = cv2.imencode(".png", img)
    if not ok:
        raise RuntimeError("PNG encoding failed")
    return bytes(buf.tobytes())
