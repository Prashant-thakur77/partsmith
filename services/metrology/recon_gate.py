"""Gate for image-model reconstructions of a broken part (the model proposes, code decides).

An image model may complete the broken region on the rectified photo. The completion is accepted only when the
image is still the same photo everywhere else: every mat marker re-detects within `MARKER_MAX_SHIFT_PX` of where it was,
and the intact part is unchanged (IoU ≥ `INTACT_MIN_IOU` against its own mask, mean colour change ≤
`INTACT_MAX_COLOUR_DELTA`). What it adds outside the intact part is returned as the completion, measured in mm and
labelled `inferred` — never `measured`.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
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
# Plausibility of the completion itself.
JOIN_MIN_MM = 1.0  # it must meet the part along the break, not at a point
COLOUR_MATCH_MIN = 25.0  # RGB distance to the part's median colour, at least this much slack…
COLOUR_MATCH_REL = 0.35  # …or this share of the part/stage contrast
TEXTURE_MAX_RATIO = 2.0  # grey-level σ of the completion vs the part (+ slack below)
TEXTURE_SLACK = 8.0
MAX_COMPLETION_REL = 0.6  # without an expected region: a broken-off piece rarely exceeds 60 % of what is left
EXPECTED_MAX_RATIO = 1.5  # with an expected region (e.g. the mirror completion): at most 1.5× its area…
EXPECTED_MIN_INSIDE = 0.6  # …and mostly inside it
MAX_RAGGEDNESS = 8.0
JOIN_ARM_MM = 1.0  # outline direction measured over ±2 arms around each join
JOIN_MAX_ANGLE_DEG = 40.0
BACKGROUND_CHANGE_DELTA = 30.0
BACKGROUND_MAX_CHANGED = 0.01
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


def _plausibility(
    orig: U8,
    rec: U8,
    keep: BoolMask,
    completion: BoolMask,
    stage_bgr: NDArray[np.float32] | None,
    ppm: float,
    origin: tuple[float, float],
    expected_mm: Sequence[Sequence[float]] | None,
) -> list[str]:
    reasons: list[str] = []
    rf = rec.astype(np.float32)
    k3 = np.ones((3, 3), np.uint8)
    # Joined along the break, not touching at a point.
    join_px = int(np.count_nonzero(completion & (cv2.dilate(keep.astype(np.uint8), k3) > 0)))
    join_mm = join_px / ppm
    if join_mm < JOIN_MIN_MM:
        reasons.append(
            f"the completion touches the part along only {join_mm:.1f} mm (< {JOIN_MIN_MM:.0f} mm): not a repair"
        )
    # The part's colour and texture.
    core_k = cv2.erode(keep.astype(np.uint8), np.ones((5, 5), np.uint8)) > 0
    core_c = cv2.erode(completion.astype(np.uint8), k3) > 0
    if core_k.any() and core_c.any():
        ck = np.median(rf[core_k], axis=0)
        cc = np.median(rf[core_c], axis=0)
        d_part = float(np.linalg.norm(cc - ck))
        sep = float(np.linalg.norm(ck - stage_bgr)) if stage_bgr is not None else 255.0
        d_stage = float(np.linalg.norm(cc - stage_bgr)) if stage_bgr is not None else 255.0
        if d_part > max(COLOUR_MATCH_MIN, COLOUR_MATCH_REL * sep) or d_part > d_stage:
            reasons.append(f"the completion's colour does not match the part (Δ {d_part:.0f} from the part)")
        g = cv2.cvtColor(np.clip(rf, 0, 255).astype(np.uint8), cv2.COLOR_BGR2GRAY).astype(np.float32)
        sk, sc = float(np.std(g[core_k])), float(np.std(g[core_c]))
        if sc > TEXTURE_MAX_RATIO * sk + TEXTURE_SLACK:
            reasons.append(f"the completion is far more textured than the part (grey σ {sc:.0f} vs {sk:.0f})")
        dark, light = float(np.mean(g[core_c] < 70)), float(np.mean(g[core_c] > 190))
        if dark > 0.05 and light > 0.05 and not (np.mean(g[core_k] < 70) > 0.05 and np.mean(g[core_k] > 190) > 0.05):
            reasons.append("the completion contains black-and-white patches like a marker")
    # A solid piece, not a scatter of cells: perimeter² / (4π·area) is 1 for a disc, ≈ 4 for a 1 × 10 strip and > 10
    # for a checkerboard fragment.
    cs, _ = cv2.findContours(completion.astype(np.uint8), cv2.RETR_CCOMP, cv2.CHAIN_APPROX_NONE)
    perim = sum(cv2.arcLength(c, True) for c in cs) / ppm
    a_mm2 = float(np.count_nonzero(completion)) / ppm**2
    if a_mm2 > 0 and perim**2 / (4 * math.pi * a_mm2) > MAX_RAGGEDNESS:
        reasons.append("the completion is ragged (scattered cells, not a solid piece of part)")
    # Marker-like squares inside it.
    gray = cv2.cvtColor(rec, cv2.COLOR_BGR2GRAY)
    corners, _, rejected = _detector().detectMarkers(gray)
    zone = cv2.dilate(completion.astype(np.uint8), np.ones((7, 7), np.uint8)) > 0
    for q in list(corners) + list(rejected or []):
        c = np.asarray(q, np.float64).reshape(-1, 2).mean(axis=0)
        x, y = round(c[0]), round(c[1])
        side = float(np.linalg.norm(np.asarray(q).reshape(-1, 2)[0] - np.asarray(q).reshape(-1, 2)[1]))
        if 0 <= y < zone.shape[0] and 0 <= x < zone.shape[1] and zone[y, x] and side > 2 * ppm:
            reasons.append("a marker-like square appears inside the completion")
            break
    # Bounded size.
    area = float(np.count_nonzero(completion)) / ppm**2
    keep_area = float(np.count_nonzero(keep)) / ppm**2
    if expected_mm is not None and len(expected_mm) >= 3:
        exp = np.zeros(keep.shape, np.uint8)
        pts = (np.asarray(expected_mm, dtype=np.float64) - np.asarray(origin)) * ppm - 0.5
        cv2.fillPoly(exp, [np.round(pts * 16).astype(np.int32)], 1, cv2.LINE_8, shift=4)
        expected = (exp > 0) & ~keep
        e_area = float(np.count_nonzero(expected)) / ppm**2
        inside = float(np.count_nonzero(completion & (cv2.dilate(exp, np.ones((7, 7), np.uint8)) > 0))) / ppm**2
        if e_area > 0 and area > EXPECTED_MAX_RATIO * e_area:
            reasons.append(f"the completion ({area:.0f} mm²) is much larger than the broken region ({e_area:.0f} mm²)")
        if area > 0 and inside < EXPECTED_MIN_INSIDE * area:
            reasons.append("most of the completion lies outside the broken region")
    elif keep_area > 0 and area > MAX_COMPLETION_REL * keep_area:
        reasons.append(f"the completion ({area:.0f} mm²) is too large for a broken-off piece of this part")
    # Smooth continuation of the outline at the joins.
    worst = _worst_join_angle(keep, completion, ppm)
    if worst is not None and worst > JOIN_MAX_ANGLE_DEG:
        reasons.append(
            f"the completion's outline meets the part's at {worst:.0f}° (> {JOIN_MAX_ANGLE_DEG:.0f}°): it does "
            "not continue the part"
        )
    return reasons


def _changed_around(orig: U8, rec: U8, keep: BoolMask, completion: BoolMask, ppm: float) -> float:
    """Share of the mat within 15 mm of the part (outside the part and the completion) that the model changed."""
    r = max(3, int(2 * 15.0 * ppm) | 1)
    around = (cv2.dilate(keep.astype(np.uint8), cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (r, r))) > 0) & ~keep
    around &= ~(cv2.dilate(completion.astype(np.uint8), np.ones((5, 5), np.uint8)) > 0)
    if not around.any():
        return 0.0
    d = np.linalg.norm(rec.astype(np.float32)[around] - orig.astype(np.float32)[around], axis=1)
    return float(np.mean(d > BACKGROUND_CHANGE_DELTA))


def _worst_join_angle(keep: BoolMask, completion: BoolMask, ppm: float) -> float | None:
    """Largest direction change of the joined outline where the completion meets the intact part (deg)."""
    union = (keep | completion).astype(np.uint8)
    cs, _ = cv2.findContours(union, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    if not cs:
        return None
    u = max(cs, key=cv2.contourArea).reshape(-1, 2).astype(np.float64)
    n = len(u)
    if n < 20:
        return None
    new = cv2.erode(completion.astype(np.uint8), np.ones((3, 3), np.uint8)) > 0
    new = cv2.dilate(new.astype(np.uint8), np.ones((5, 5), np.uint8)) > 0
    is_new = new[u[:, 1].astype(int), u[:, 0].astype(int)] & ~keep[u[:, 1].astype(int), u[:, 0].astype(int)]
    m = max(3, round(JOIN_ARM_MM * ppm))
    worst = None
    for j in np.flatnonzero(is_new != np.roll(is_new, 1)):
        a, b, c = u[(j - 2 * m) % n], u[j % n], u[(j + 2 * m) % n]
        d1, d2 = b - a, c - b
        if np.linalg.norm(d1) < 1 or np.linalg.norm(d2) < 1:
            continue
        ang = math.degrees(math.acos(float(np.clip(d1 @ d2 / (np.linalg.norm(d1) * np.linalg.norm(d2)), -1, 1))))
        worst = ang if worst is None else max(worst, ang)
    return worst


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
    expected_mm: Sequence[Sequence[float]] | None = None,
) -> ReconGate:
    """Check a reconstruction against the original rectified mat image (which must include the marker ring).

    `keep_mask` marks the intact original part on the rectified grid. A plain array needs `px_per_mm` (default: the
    image width over the mat width) and `origin_mm` (mat mm of the top-left corner). `expected_mm` (mat frame, e.g. the
    mirror completion of the broken region) bounds where and how much may be added.

    Besides markers and the intact part, the completion itself must be plausible: joined to the part along the break
    (not touching at a point), the part's colour and texture (not the stage's, not marker black-and-white), free of
    marker-like squares, of a bounded size, continuing the part's outline smoothly where it joins, and nothing else
    around the part may have changed."""
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
    if completion.any():
        reasons += _plausibility(o3, rec, keep, completion, bg, ppm, origin, expected_mm)
    else:
        reasons.append("the reconstruction adds no part material at the break")
    changed = _changed_around(o3, rec, keep, completion, ppm)
    if changed > BACKGROUND_MAX_CHANGED:
        reasons.append(f"{changed * 100:.0f} % of the mat around the part changed outside the completion")
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
