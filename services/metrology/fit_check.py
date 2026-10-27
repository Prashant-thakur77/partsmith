"""Screen fit check: the model's 1:1 outline is drawn on the calibrated screen mat, the real part is laid on it and
photographed, and code compares the part's footprint with the outline.

Pass thresholds (named below) follow from what a screen can show and a phone can see:

* Screen pixel pitch. Laptop and tablet panels have 0.10–0.25 mm pixels (13" 2560×1600 ≈ 0.11 mm, 15.6" 1920×1080 ≈
  0.18 mm, 14" 1366×768 ≈ 0.23 mm). An anti-aliased line is placed to about half a device pixel, ≤ 0.12 mm.
* Card scale. Matching an ID-1 card by eye sets the scale to ≈ 0.2 % (0.1 mm over 50 mm, 0.2 mm over 100 mm).
* Photo measurement. Mat fit + mask edges + residual parallax of the part's top edge: ≈ 0.1–0.2 mm.

Root-sum-square of those is ≈ 0.3 mm, so edges within `FIT_AGREE_MM` (0.35 mm) are shown green: they agree as well as
this setup can tell. Up to `FIT_WARN_MM` (0.8 mm) is amber: worth a look, often a burr or a slightly lifted part. Beyond
that is red. The check passes when 95 % of the outline is within `FIT_PASS_HD95_MM` (0.5 mm — the same bound the verifier
uses), no point is off by more than `FIT_PASS_MAX_MM`, IoU ≥ `FIT_PASS_IOU`, and every hole is within `FIT_HOLE_TOL_MM`.
Placement: nobody lays a part down to 0.1 mm, so the part is first aligned to the outline by a small rigid move (up to
`MAX_PLACEMENT_SHIFT_MM` / `MAX_PLACEMENT_ROT_DEG`), which is reported, then compared.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np
from numpy.typing import NDArray
from partsmith_schemas import FitCheckResult
from partsmith_schemas.measurement import ViewKind
from scipy.optimize import minimize
from scipy.spatial import cKDTree
from shapely import affinity
from shapely.geometry import Point, Polygon
from shapely.prepared import prep

from . import overlay as ov
from .features import fit_circle, largest_polygon
from .mats import get_mat
from .measure import decode_image, measure_photo
from .segment import Segmenter, ThresholdSegmenter

F64 = NDArray[np.float64]
U8 = NDArray[np.uint8]

FIT_AGREE_MM = 0.35
FIT_WARN_MM = 0.8
FIT_PASS_HD95_MM = 0.5
FIT_PASS_MAX_MM = 1.0
FIT_PASS_IOU = 0.95
FIT_HOLE_TOL_MM = 0.5
MAX_PLACEMENT_SHIFT_MM = 6.0
MAX_PLACEMENT_ROT_DEG = 8.0
SAMPLE_STEP_MM = 0.05
DIM_OFFSET_MM = 5.0

# The web fit-check page draws the outline, holes and dimension lines in this colour; the segmenter treats it as background.
FIT_OUTLINE_RGB = (224, 33, 138)  # #E0218A
FIT_OUTLINE_HUE_DEG = (285.0, 350.0)


@dataclass
class FitHole:
    center_mm: tuple[float, float]  # outline hole centre, mat frame
    outline_diameter_mm: float
    measured_diameter_mm: float | None
    center_offset_mm: float | None


@dataclass
class FitCheckOutput:
    result: FitCheckResult
    overlay_png: bytes
    hd95_mm: float = float("nan")
    worst_point_mm: tuple[float, float] | None = None  # on the outline, mat frame
    worst_signed_mm: float = 0.0  # + part larger than the outline there, − smaller
    placement_shift_mm: tuple[float, float] = (0.0, 0.0)
    placement_rot_deg: float = 0.0
    holes: list[FitHole] = field(default_factory=list)
    part_mat: Polygon | None = None


# ---------------------------------------------------------------- outline for the screen


def _circle(cx: float, cy: float, d: float, n: int = 180) -> F64:
    a = np.linspace(0, 2 * math.pi, n, endpoint=False)
    return np.asarray(np.c_[cx + d / 2 * np.cos(a), cy + d / 2 * np.sin(a)], dtype=np.float64)


def fit_outline_for(
    outline_part: list[list[float]] | F64,
    holes: list[dict[str, Any]] | None,
    mat_id: str,
) -> dict[str, Any]:
    """Centre a part-frame outline (Y up) on the mat's stage and return it in MAT coordinates (`/jobs/{id}/fit-outline`).

    The part's long side follows the stage's long side. `holes` are `{"center_mm": [x, y], "diameter_mm": d}` in the
    part frame. Raises `ValueError` if the part does not fit on the stage.
    """
    mat = get_mat(mat_id)
    st = mat.stage
    P = np.asarray(outline_part, dtype=np.float64).reshape(-1, 2)
    lo, hi = P.min(axis=0), P.max(axis=0)
    bw, bh = hi - lo
    theta = 0.0 if (bw >= bh) == (st.w_mm >= st.h_mm) else math.pi / 2
    c, s = math.cos(theta), math.sin(theta)
    Rf = np.array([[c, s], [s, -c]])  # Rot(θ)·diag(1, −1): part (Y up) → mat (y down)
    rot = P @ Rf.T
    rlo, rhi = rot.min(axis=0), rot.max(axis=0)
    size = rhi - rlo
    if size[0] > st.w_mm - 2 or size[1] > st.h_mm - 2:
        raise ValueError(
            f"A {size[0]:.0f} × {size[1]:.0f} mm part does not fit the {st.w_mm:.0f} × {st.h_mm:.0f} mm stage of "
            f"{mat_id}; use a larger mat."
        )
    centre = np.array([st.x_mm + st.w_mm / 2, st.y_mm + st.h_mm / 2])
    t = centre - (rlo + rhi) / 2

    def to_mat(q: F64) -> F64:
        return np.asarray(np.asarray(q, dtype=np.float64).reshape(-1, 2) @ Rf.T + t, dtype=np.float64)

    out_holes = []
    dims: list[dict[str, Any]] = []
    for hd in holes or []:
        cm = to_mat(np.array([hd["center_mm"]]))[0]
        d = float(hd["diameter_mm"])
        out_holes.append({"center_mm": [round(float(cm[0]), 3), round(float(cm[1]), 3)], "diameter_mm": round(d, 3)})
        dims.append(
            {
                "label": f"Ø{d:.2f}",
                "from_mm": [round(float(cm[0] - d / 2), 3), round(float(cm[1]), 3)],
                "to_mm": [round(float(cm[0] + d / 2), 3), round(float(cm[1]), 3)],
                "value_mm": round(d, 3),
            }
        )
    mlo, mhi = rlo + t, rhi + t
    y_dim = mhi[1] + DIM_OFFSET_MM if mhi[1] + DIM_OFFSET_MM < st.y2_mm else mlo[1] - DIM_OFFSET_MM
    x_dim = mhi[0] + DIM_OFFSET_MM if mhi[0] + DIM_OFFSET_MM < st.x2_mm else mlo[0] - DIM_OFFSET_MM
    dims.insert(
        0,
        {
            "label": f"{size[0]:.2f} mm",
            "from_mm": [round(float(mlo[0]), 3), round(float(y_dim), 3)],
            "to_mm": [round(float(mhi[0]), 3), round(float(y_dim), 3)],
            "value_mm": round(float(size[0]), 3),
        },
    )
    dims.insert(
        1,
        {
            "label": f"{size[1]:.2f} mm",
            "from_mm": [round(float(x_dim), 3), round(float(mlo[1]), 3)],
            "to_mm": [round(float(x_dim), 3), round(float(mhi[1]), 3)],
            "value_mm": round(float(size[1]), 3),
        },
    )
    return {
        "mat_id": mat_id,
        "outline_mm": [[round(float(x), 3), round(float(y), 3)] for x, y in to_mat(P)],
        "holes": out_holes,
        "dims": dims,
        "placement": {
            "cx_mm": round(float(t[0]), 3),
            "cy_mm": round(float(t[1]), 3),
            "theta_deg": round(math.degrees(theta), 3),
        },
    }


# ---------------------------------------------------------------- comparison


def _sample_rings(poly: Polygon, step: float = SAMPLE_STEP_MM) -> F64:
    pts = []
    for ring in [poly.exterior, *poly.interiors]:
        n = max(8, math.ceil(ring.length / step))
        d = np.linspace(0, ring.length, n, endpoint=False)
        pts.append(np.array([ring.interpolate(x).coords[0] for x in d]))
    return np.concatenate(pts)


def _where(pt: F64, centre: F64) -> str:
    dx, dy = pt - centre
    h = "right" if dx > 0 else "left"
    v = "bottom" if dy > 0 else "top"
    if abs(dx) > 2.5 * abs(dy):
        return f"{h} end"
    if abs(dy) > 2.5 * abs(dx):
        return f"{v} edge"
    return f"{v}-{h}"


def _transform(pts: F64, p: F64, pivot: F64) -> F64:
    c, s = math.cos(p[2]), math.sin(p[2])
    R = np.array([[c, -s], [s, c]])
    return np.asarray((pts - pivot) @ R.T + pivot + p[:2], dtype=np.float64)


def compare_to_outline(part: Polygon, target: Polygon, *, register: bool = True) -> dict[str, Any]:
    """Align `part` to `target` with a small rigid move, then boundary distances (mm), IoU and the worst point."""
    tgt_pts = _sample_rings(target)
    part_pts = _sample_rings(part)
    tree_t = cKDTree(tgt_pts)
    pivot = np.array(target.centroid.coords[0])
    p0 = np.array([target.centroid.x - part.centroid.x, target.centroid.y - part.centroid.y, 0.0])

    def cost(p: F64) -> float:
        q = _transform(part_pts, p, pivot)
        d1, _ = tree_t.query(q)
        d2, _ = cKDTree(q).query(tgt_pts)
        # Squared distances: with a uniformly larger/smaller part, a spurious rotation then costs second-order.
        return float(np.mean(d1**2) + np.mean(d2**2))

    p = p0
    if register:
        r = minimize(
            cost,
            p0,
            method="Nelder-Mead",
            options={
                "xatol": 1e-3,
                "fatol": 1e-5,
                "maxiter": 400,
                "initial_simplex": p0 + np.array([[0, 0, 0], [0.3, 0, 0], [0, 0.3, 0], [0, 0, 0.01]]),
            },
        )
        p = np.asarray(r.x, dtype=np.float64)
    shift = p[:2]  # how far the part had to move to sit on the outline (rotation is about the outline centroid)
    moved_part = affinity.translate(affinity.rotate(part, math.degrees(p[2]), origin=(pivot[0], pivot[1])), p[0], p[1])
    q = _transform(part_pts, p, pivot)
    d_part, _ = tree_t.query(q)
    d_tgt, _ = cKDTree(q).query(tgt_pts)
    inside = prep(moved_part)
    sign = np.array([1.0 if inside.contains(Point(x, y)) else -1.0 for x, y in tgt_pts])
    signed = d_tgt * sign
    k = int(np.argmax(d_tgt))
    inter = moved_part.intersection(target).area
    union = moved_part.union(target).area
    return {
        "hausdorff_mm": float(max(d_part.max(), d_tgt.max())),
        "hd95_mm": float(max(np.percentile(d_part, 95), np.percentile(d_tgt, 95))),
        "mean_mm": float((d_part.mean() + d_tgt.mean()) / 2),
        "iou": float(inter / union) if union > 0 else 0.0,
        "target_pts": tgt_pts,
        "signed_mm": signed,
        "worst_idx": k,
        "shift_mm": (float(shift[0]), float(shift[1])),
        "rot_deg": float(math.degrees(p[2])),
        "moved_part": moved_part,
        "params": p,
        "pivot": pivot,
    }


def fit_check(
    photo: bytes | U8,
    mat_id: str,
    outline_mm: list[list[float]] | F64,
    holes: list[dict[str, Any]] | None = None,
    *,
    segmenter: Segmenter | None = None,
    thickness_mm: float | None = None,
    K: F64 | None = None,
) -> FitCheckOutput:
    """Compare a photo of the real part lying on its drawn outline with that outline (mat frame, as served by
    `/jobs/{id}/fit-outline`). `thickness_mm` (the model's thickness) enables the height correction."""
    img = decode_image(photo) if isinstance(photo, bytes | bytearray) else np.asarray(photo, dtype=np.uint8)
    seg = segmenter or ThresholdSegmenter()
    mo = measure_photo(
        img,
        ViewKind.fit_check,
        segmenter=seg,
        thickness_mm=thickness_mm,
        K=K,
        mat_id=mat_id,
        prompt="plastic part",
        seg_context_kwargs={"ignore_hue_deg": FIT_OUTLINE_HUE_DEG},
    )
    capture = mo.result.capture
    target = largest_polygon(
        Polygon(
            np.asarray(outline_mm, dtype=np.float64),
            [_circle(h["center_mm"][0], h["center_mm"][1], float(h["diameter_mm"])) for h in holes or []],
        ).buffer(0)
    )
    if mo.footprint_mat is None or mo.detection is None or target is None:
        reason = capture.retake_reason or "No part found on the outline — lay the part on the drawn shape and retake."
        res = FitCheckResult(
            passed=False, iou=0.0, hausdorff_mm=float("nan"), mean_mm=float("nan"), reasons=[reason], capture=capture
        )
        return FitCheckOutput(res, mo.overlay_png)

    cmp = compare_to_outline(mo.footprint_mat, target)
    reasons: list[str] = []
    shift = math.hypot(*cmp["shift_mm"])
    placed_ok = shift <= MAX_PLACEMENT_SHIFT_MM and abs(cmp["rot_deg"]) <= MAX_PLACEMENT_ROT_DEG
    if not placed_ok:
        reasons.append(
            f"The part sits {shift:.1f} mm / {abs(cmp['rot_deg']):.1f}° away from the outline — line it up with the drawn "
            "shape and retake."
        )
    elif shift > 1.0 or abs(cmp["rot_deg"]) > 1.0:
        reasons.append(f"Aligned the part to the outline first (moved {shift:.1f} mm, turned {cmp['rot_deg']:+.1f}°).")

    fit_holes: list[FitHole] = []
    holes_ok = True
    moved: Polygon = cmp["moved_part"]
    for i, h in enumerate(holes or [], start=1):
        hc = np.array(h["center_mm"], dtype=np.float64)
        d = float(h["diameter_mm"])
        best = None
        for ring in moved.interiors:
            pts = np.asarray(ring.coords)[:-1]
            if len(pts) < 8:
                continue
            cf = fit_circle(pts)
            off = math.hypot(cf.cx - hc[0], cf.cy - hc[1])
            if off < d / 2 and (best is None or off < best[1]):
                best = (cf, off)
        if best is None:
            holes_ok = False
            fit_holes.append(FitHole((float(hc[0]), float(hc[1])), d, None, None))
            reasons.append(
                f"Hole {i} (Ø{d:.2f} mm) is not visible in the photo — is it covered or missing on the part?"
            )
            continue
        cf, off = best
        md = 2 * cf.r
        fit_holes.append(FitHole((float(hc[0]), float(hc[1])), d, md, off))
        if abs(md - d) > FIT_HOLE_TOL_MM or off > FIT_HOLE_TOL_MM:
            holes_ok = False
            reasons.append(
                f"Hole {i}: the part's hole is Ø{md:.2f} mm, {off:.2f} mm off centre; the model has Ø{d:.2f} mm."
            )

    hd95, hmax, iou = cmp["hd95_mm"], cmp["hausdorff_mm"], cmp["iou"]
    k = cmp["worst_idx"]
    worst = cmp["target_pts"][k]
    wsign = float(cmp["signed_mm"][k])
    centre = np.array(target.centroid.coords[0])
    passed = bool(
        capture.passed
        and placed_ok
        and holes_ok
        and hd95 <= FIT_PASS_HD95_MM
        and hmax <= FIT_PASS_MAX_MM
        and iou >= FIT_PASS_IOU
    )
    if hd95 <= FIT_PASS_HD95_MM:
        reasons.insert(0, f"Edges agree within {hd95:.2f} mm along 95 % of the outline (IoU {iou:.3f}).")
    else:
        reasons.insert(0, f"Edges differ by up to {hd95:.2f} mm along 5 % of the outline (IoU {iou:.3f}).")
    bigger = "larger" if wsign > 0 else "smaller"
    if hmax > FIT_AGREE_MM:
        reasons.append(
            f"Largest difference {hmax:.2f} mm at the {_where(worst, centre)} — the part is {bigger} than "
            "the model there."
        )
    if not capture.passed and capture.retake_reason:
        reasons.append(capture.retake_reason)

    res = FitCheckResult(
        passed=passed,
        iou=round(iou, 4),
        hausdorff_mm=round(hmax, 3),
        mean_mm=round(cmp["mean_mm"], 3),
        reasons=reasons,
        capture=capture,
    )
    overlay_png = _overlay(img, mo, target, cmp, passed)
    return FitCheckOutput(
        result=res,
        overlay_png=overlay_png,
        hd95_mm=hd95,
        worst_point_mm=(float(worst[0]), float(worst[1])),
        worst_signed_mm=wsign,
        placement_shift_mm=cmp["shift_mm"],
        placement_rot_deg=cmp["rot_deg"],
        holes=fit_holes,
        part_mat=mo.footprint_mat,
    )


def _overlay(img: U8, mo: Any, target: Polygon, cmp: dict[str, Any], passed: bool) -> bytes:
    det = mo.detection
    b = target.bounds
    pad = 25.0
    box = det.to_px(
        np.array(
            [[b[0] - pad, b[1] - pad], [b[2] + pad, b[1] - pad], [b[2] + pad, b[3] + pad], [b[0] - pad, b[3] + pad]]
        )
    )
    c = ov.Canvas.from_image(img, crop=(*box.min(axis=0), *box.max(axis=0)))
    if mo.footprint_mat is not None:
        c.poly(det.to_px(np.asarray(mo.footprint_mat.exterior.coords)), ov.INK, width=1)
    pts = cmp["target_pts"]
    dev = np.abs(cmp["signed_mm"])
    px = det.to_px(pts)
    # Colour bands along the outline, drawn where the outline really is on the screen.
    for i in range(len(px) - 1):
        if np.linalg.norm(pts[i + 1] - pts[i]) > 3 * SAMPLE_STEP_MM:
            continue  # ring boundary
        col = ov.AGREE if dev[i] <= FIT_AGREE_MM else ov.AMBER if dev[i] <= FIT_WARN_MM else ov.RED
        c.line(px[i], px[i + 1], col, width=c.lw + 2)
    k = cmp["worst_idx"]
    wp = px[k]
    c.dot(wp, ov.RED if dev[k] > FIT_WARN_MM else ov.AMBER if dev[k] > FIT_AGREE_MM else ov.AGREE, 4.0 * c.lw)
    c.label(
        f"{dev[k]:.2f} mm",
        wp
        + (
            det.to_px(
                pts[k]
                + 4.0
                * (pts[k] - np.array(target.centroid.coords[0]))
                / max(np.linalg.norm(pts[k] - np.array(target.centroid.coords[0])), 1e-9)
            )[0]
            - wp
        ),
    )
    verdict = "fits" if passed else "does not fit"
    c.top_label(
        f"Fit check: {verdict} · 95 % within {cmp['hd95_mm']:.2f} mm · max {cmp['hausdorff_mm']:.2f} mm · "
        f"IoU {cmp['iou']:.3f}",
        ov.AGREE if passed else ov.RED,
    )
    return c.png()
