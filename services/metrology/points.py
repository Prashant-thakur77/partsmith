"""Feature measurement from points: a model (or the user) points at a feature, a point-prompted segmenter cuts it out,
code measures it.

Each `FeaturePoint` becomes one point-prompted segmentation of a crop around it (with a negative point on the nearest
mat marker so the segmenter does not return the board). The feature's edge is traced sub-pixel on the mask and then
made sub-pixel against the photo (colour unmixing across the edge); the result is fitted in millimetres:

- hole, mat visible through it, thickness known → vertical-cylinder fit to the see-through lens (`fit_see_through_hole`);
- hole whose bore hides the mat (only wall visible) → circle fit to the top opening on the top-face plane;
- hole otherwise → circle fit on the mat plane; slot → obround fit; tab → min-area rectangle; broken edge → region.

Everything is `source=measured` with the prompt point as evidence. `merge_holes` combines these with the holes the outline
pass found: a point-derived hole replaces an outline hole only when its fit is strictly better (lower rms radial residual
relative to the radius); holes the outline pass missed are added.
"""

from __future__ import annotations

import io
import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Literal

import cv2
import numpy as np
from numpy.typing import NDArray
from partsmith_schemas.common import Evidence, Measured, Source
from partsmith_schemas.measurement import Hole, Measurements
from scipy.ndimage import distance_transform_edt
from shapely.geometry import Polygon

from services.common.images import decode_bgr

from .calibrate import MatDetection, PoseEstimate, apply_h, plane_homography
from .features import fit_circle, fit_see_through_hole, fit_see_through_slot, fit_slot, min_area_rect
from .measure import MeasureOutput
from .segment import mask_contour_subpx

F64 = NDArray[np.float64]
U8 = NDArray[np.uint8]
BoolMask = NDArray[np.bool_]
FeatureKind = Literal["hole", "slot", "tab", "broken_edge"]
PointPx = tuple[float, float]
Box = tuple[float, float, float, float]
SegPointsCall = Callable[[bytes, list[PointPx], list[PointPx], Box | None], list[tuple[NDArray[np.bool_], float]]]

CROP_HALF_MM = 18.0  # crop around the point (holes and slots are well inside this)
MARKER_REACH_MM = 60.0  # include the nearest marker in the crop (for the negative point) if it is this close
SEE_THROUGH_FRACTION = 0.8  # share of mask pixels with the stage's colour for "the mat shows through"
STAGE_COLOUR_TOL = 25.0
POINT_NOTE = "SAM point prompt"


@dataclass(frozen=True)
class FeaturePoint:
    id: str
    kind: FeatureKind
    px: PointPx  # full-frame image pixel
    source: Literal["model", "user"] = "model"


@dataclass
class FeatureMeasurement:
    id: str
    kind: FeatureKind
    point_px: PointPx
    ok: bool
    method: str = ""
    center_mm: tuple[float, float] | None = None  # mat frame
    values: dict[str, Measured] = field(default_factory=dict)
    rms_mm: float | None = None
    quality: float | None = None  # rms / radius (holes) or rms / width (slots); lower is better
    outline_mm: list[tuple[float, float]] = field(default_factory=list)  # mat frame
    mask_score: float = 0.0
    mask_source: str = ""
    point_source: str = "model"
    reason: str | None = None


def _png(img: U8) -> bytes:
    ok, buf = cv2.imencode(".png", img)
    if not ok:
        raise RuntimeError("PNG encode failed")
    return bytes(io.BytesIO(buf.tobytes()).getvalue())


def stage_colour(img: U8, det: MatDetection) -> F64:
    """Median colour of the stage's border band (where no part lies)."""
    st = det.mat.stage
    outer = np.round(det.to_px(st.corners()) * 16).astype(np.int32)
    inner = np.round(det.to_px(st.inset(4.0).corners()) * 16).astype(np.int32)
    m = np.zeros(img.shape[:2], np.uint8)
    cv2.fillPoly(m, [outer], 1, cv2.LINE_8, shift=4)
    cv2.fillPoly(m, [inner], 0, cv2.LINE_8, shift=4)
    return np.asarray(np.median(img[m > 0].reshape(-1, 3), axis=0), dtype=np.float64)


def _nearest_marker_px(det: MatDetection, pt: PointPx) -> PointPx | None:
    if det.n_markers == 0:
        return None
    c = det.corners_px.mean(axis=1)
    i = int(np.argmin(np.hypot(c[:, 0] - pt[0], c[:, 1] - pt[1])))
    return float(c[i, 0]), float(c[i, 1])


def _crop_for(det: MatDetection, pt: PointPx, shape: tuple[int, int]) -> tuple[int, int, int, int, PointPx | None]:
    h, w = shape
    mm = det.to_mm(np.array([pt], dtype=np.float64))[0]
    ppm = det.px_per_mm_at((float(mm[0]), float(mm[1])))
    half = CROP_HALF_MM * ppm
    x0, y0, x1, y1 = pt[0] - half, pt[1] - half, pt[0] + half, pt[1] + half
    neg = _nearest_marker_px(det, pt)
    if neg is not None and math.hypot(neg[0] - pt[0], neg[1] - pt[1]) <= MARKER_REACH_MM * ppm:
        x0, y0 = min(x0, neg[0] - 5), min(y0, neg[1] - 5)
        x1, y1 = max(x1, neg[0] + 5), max(y1, neg[1] + 5)
    else:
        neg = None
    return max(int(x0), 0), max(int(y0), 0), min(math.ceil(x1), w), min(math.ceil(y1), h), neg


def _pick_mask(masks: list[tuple[NDArray[np.bool_], float]], pt: PointPx) -> tuple[BoolMask, float] | None:
    best = None
    for m, s in masks:
        mm = np.asarray(m, dtype=bool)
        x, y = round(pt[0]), round(pt[1])
        inside = 0 <= y < mm.shape[0] and 0 <= x < mm.shape[1] and bool(mm[y, x])
        key = (inside, float(s))
        if mm.any() and (best is None or key > best[0]):
            best = (key, mm, float(s))
    return None if best is None else (best[1], best[2])


def measure_features_from_points(
    img: U8,
    det: MatDetection,
    pose: PoseEstimate | None,
    points: Sequence[FeaturePoint],
    segment_points_call: SegPointsCall,
    *,
    thickness_mm: float | None = None,
    mask_source: str = "sam-3.1",
    part_mask: BoolMask | None = None,
) -> list[FeatureMeasurement]:
    """Measure each pointed-at feature. Never raises for one bad point: that point comes back with `ok=False`.

    `part_mask` (the outline pass's full-frame mask) gives the top face's colour around each feature; without it the
    colour is sampled from a ring around the returned mask."""
    img3 = img if img.ndim == 3 else np.asarray(cv2.cvtColor(img, cv2.COLOR_GRAY2BGR), dtype=np.uint8)
    stage_bgr = stage_colour(img3, det)
    thick = thickness_mm is not None and thickness_mm > 0 and pose is not None and pose.camera_height_mm > thickness_mm
    H_top = (
        plane_homography(pose, float(thickness_mm), det.H)
        if thick and pose is not None and thickness_mm is not None
        else None
    )
    out: list[FeatureMeasurement] = []
    for fp in points:
        fm = FeatureMeasurement(fp.id, fp.kind, fp.px, ok=False, mask_source=mask_source, point_source=fp.source)
        out.append(fm)
        x0, y0, x1, y1, neg = _crop_for(det, fp.px, img3.shape[:2])
        if x1 - x0 < 8 or y1 - y0 < 8:
            fm.reason = "the point is outside the photo"
            continue
        crop = np.ascontiguousarray(img3[y0:y1, x0:x1])
        pos_c = (fp.px[0] - x0, fp.px[1] - y0)
        negs = [] if neg is None else [(neg[0] - x0, neg[1] - y0)]
        try:
            masks = segment_points_call(_png(crop), [pos_c], negs, None)
        except Exception as e:  # a failed call is one failed feature, not a failed job
            fm.reason = f"segmentation failed: {type(e).__name__}: {e}"
            continue
        picked = _pick_mask(masks, pos_c)
        if picked is None:
            fm.reason = "the segmenter returned no mask for this point"
            continue
        m, score = picked
        fm.mask_score = score
        full = np.zeros(img3.shape[:2], dtype=bool)
        full[y0:y1, x0:x1] = m[: y1 - y0, : x1 - x0]
        _measure_one(fm, full, img3, stage_bgr, det, pose, H_top, thickness_mm, part_mask)
    return out


OPENING_SEARCH_MM = 15.0
OPENING_MIN_DIFF = 12.0  # colour distance (8-bit) that separates a hole's inside from the top face, at least


def _opening(
    img: U8, mask: BoolMask, pt: PointPx, ppm: float, part_mask: BoolMask | None
) -> tuple[BoolMask, NDArray[np.float32]] | None:
    """Everything inside a hole's top rim: the connected region around the point whose colour differs from the
    surrounding top face by more than the face's own variation (bore wall and/or the mat seen through), plus a soft
    field whose 0.5 crossing is the rim (colour distance / the nearby inside level). None when not enclosed."""
    h, w = mask.shape
    r = OPENING_SEARCH_MM * ppm
    x0, y0 = max(int(pt[0] - r), 0), max(int(pt[1] - r), 0)
    x1, y1 = min(int(pt[0] + r) + 1, w), min(int(pt[1] + r) + 1, h)
    sub = img[y0:y1, x0:x1].astype(np.float32)
    m = mask[y0:y1, x0:x1]
    if not m.any():
        return None

    def grow(mm_: float) -> BoolMask:
        k = max(3, int(2 * mm_ * ppm) | 1)
        el = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))
        return np.asarray(cv2.dilate(m.astype(np.uint8), el) > 0, dtype=bool)

    if part_mask is not None:
        pm = cv2.erode(part_mask[y0:y1, x0:x1].astype(np.uint8), np.ones((5, 5), np.uint8)) > 0
        around = pm & ~grow(0.3)
    else:
        around = grow(2.5) & ~grow(1.0)
    if around.sum() < 20:
        return None
    top = np.median(sub[around], axis=0)
    d = np.linalg.norm(sub - top, axis=2).astype(np.float32)
    spread = float(np.median(d[around])) * 1.4826
    thr = max(OPENING_MIN_DIFF, 4.0 * spread)
    if float(np.median(d[m])) < 1.5 * thr:
        return None  # the pointed-at region looks like the top face itself
    cand = (d > thr).astype(np.uint8)
    cand = cv2.morphologyEx(cand, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    _, lab = cv2.connectedComponents(cand, connectivity=8)
    ids = np.unique(lab[m & (cand > 0)])
    ids = ids[ids > 0]
    if len(ids) == 0:
        return None
    reg = np.isin(lab, ids)
    if reg[0, :].any() or reg[-1, :].any() or reg[:, 0].any() or reg[:, -1].any():
        return None  # not enclosed by top face: an open notch or the stage
    out = np.zeros_like(mask)
    out[y0:y1, x0:x1] = reg
    # Sub-pixel rim: an edge pixel mixes the top colour T with the colour X just inside, P = T + α(X − T). Take X from
    # the nearest pixel one step inside the region and solve for α; the rim is the α = 0.5 crossing.
    reg_in = cv2.erode(reg.astype(np.uint8), np.ones((3, 3), np.uint8)) > 0
    if not reg_in.any():
        reg_in = reg
    _, idx = distance_transform_edt(~reg_in, return_indices=True)
    X = sub[idx[0], idx[1]]
    v = X - top
    alpha = np.sum((sub - top) * v, axis=2) / np.maximum(np.sum(v * v, axis=2), 1e-6)
    soft = np.where(reg_in, 1.0, np.clip(alpha, 0.0, 1.0)).astype(np.float32)
    band = cv2.dilate(reg.astype(np.uint8), np.ones((5, 5), np.uint8)) > 0
    soft = np.where(band, soft, 0.0).astype(np.float32)
    field = np.zeros(mask.shape, np.float32)
    field[y0:y1, x0:x1] = soft
    return out, field


def _outer_contour(mask: BoolMask | NDArray[np.float32], pt: PointPx) -> F64 | None:
    cs = [c for c in mask_contour_subpx(mask, min_area_px=2.0) if not c.is_hole]
    if not cs:
        return None
    for c in cs:
        poly = c.points_px.astype(np.float32).reshape(-1, 1, 2)
        if cv2.pointPolygonTest(poly, (float(pt[0]), float(pt[1])), False) >= 0:
            return c.points_px
    return max(cs, key=lambda c: c.area_px).points_px


def unmix_edges(img: U8, mask: BoolMask, band_px: int = 3) -> NDArray[np.float32]:
    """Soft coverage of a mask from the photo: each pixel near the mask edge is taken as a mix of the colour one step
    inside and the colour one step outside, P = O + α(I − O); the edge is the α = 0.5 crossing. A segmenter's raster
    edge is only pixel-true; this makes it sub-pixel without assuming which side is darker."""
    m = np.asarray(mask, dtype=bool)
    if not m.any():
        return np.zeros(m.shape, np.float32)
    ys, xs = np.nonzero(m)
    pad = band_px + 4
    y0, y1 = max(int(ys.min()) - pad, 0), min(int(ys.max()) + pad + 1, m.shape[0])
    x0, x1 = max(int(xs.min()) - pad, 0), min(int(xs.max()) + pad + 1, m.shape[1])
    sub = img[y0:y1, x0:x1].astype(np.float32)
    mm = m[y0:y1, x0:x1]
    k3 = np.ones((3, 3), np.uint8)
    inner = cv2.erode(mm.astype(np.uint8), k3) > 0
    outer = ~(cv2.dilate(mm.astype(np.uint8), k3) > 0)
    if not inner.any() or not outer.any():
        return m.astype(np.float32)
    _, ii = distance_transform_edt(~inner, return_indices=True)
    _, oi = distance_transform_edt(~outer, return_indices=True)
    I_ = sub[ii[0], ii[1]]
    O_ = sub[oi[0], oi[1]]
    v = I_ - O_
    alpha = np.clip(np.sum((sub - O_) * v, axis=2) / np.maximum(np.sum(v * v, axis=2), 1e-6), 0.0, 1.0)
    weak = np.sum(v * v, axis=2) < 64.0  # inside and outside look alike: keep the raster edge there
    alpha = np.where(weak, mm.astype(np.float32), alpha)
    near = cv2.dilate(mm.astype(np.uint8), np.ones((2 * band_px + 1,) * 2, np.uint8)) > 0
    deep = cv2.erode(mm.astype(np.uint8), np.ones((2 * band_px + 1,) * 2, np.uint8)) > 0
    soft = np.where(deep, 1.0, np.where(near, alpha, 0.0)).astype(np.float32)
    out = np.zeros(m.shape, np.float32)
    out[y0:y1, x0:x1] = soft
    return out


def _circle_sigma(rms: float, n: int, reproj_mm: float) -> float:
    """1σ of a fitted diameter: neighbouring traced edge points are correlated, so count one in eight as independent."""
    return math.hypot(2 * rms / math.sqrt(max(n / 8.0, 1.0)), reproj_mm)


def _measure_one(
    fm: FeatureMeasurement,
    mask: BoolMask,
    img: U8,
    stage_bgr: F64,
    det: MatDetection,
    pose: PoseEstimate | None,
    H_top: F64 | None,
    thickness_mm: float | None,
    part_mask: BoolMask | None = None,
) -> None:
    ev_px = [[round(fm.point_px[0], 2), round(fm.point_px[1], 2)]]
    reproj = det.reproj_mm_rms

    def measured(v: float, sig: float, note: str) -> Measured:
        return Measured(
            value=round(v, 3),
            source=Source.measured,
            sigma_mm=round(sig, 3),
            evidence=Evidence(view="top", pixels=ev_px, note=f"{POINT_NOTE} ({fm.mask_source}); {note}"),
        )

    opening = None
    if fm.kind in ("hole", "slot"):
        mm = det.to_mm(np.array([fm.point_px], dtype=np.float64))[0]
        opening = _opening(img, mask, fm.point_px, det.px_per_mm_at((float(mm[0]), float(mm[1]))), part_mask)
    ring_px = _outer_contour(unmix_edges(img, mask), fm.point_px)
    rim_px = _outer_contour(opening[1], fm.point_px) if opening is not None else None
    if (ring_px is None or len(ring_px) < 8) and (rim_px is None or len(rim_px) < 8):
        fm.reason = "the mask is too small to measure"
        return

    if fm.kind == "hole":
        # Candidates: (method, cx, cy, r, rms, σ_d, ring). The best fit (lowest rms/r) is reported.
        cands: list[tuple[str, float, float, float, float, float, F64]] = []
        if rim_px is not None and len(rim_px) >= 8:
            # The rim of the top opening bounds everything that is not top face inside it (bore wall and the mat
            # seen through): an exact circle on the top-face plane, whether or not the mat shows through.
            H = H_top if H_top is not None else det.H
            rm = apply_h(H, det.undistort(rim_px))
            cf = fit_circle(rm)
            name = "top-opening rim" + (f", h={thickness_mm:.1f} mm" if H_top is not None else " on the mat plane")
            cands.append((name, cf.cx, cf.cy, cf.r, cf.rms, _circle_sigma(cf.rms, cf.n, reproj), rm))
        if ring_px is not None and len(ring_px) >= 8:
            see = float(np.mean(np.linalg.norm(img[mask].astype(np.float64) - stage_bgr, axis=1) < STAGE_COLOUR_TOL))
            see_through = see >= SEE_THROUGH_FRACTION
            if see_through and H_top is not None and pose is not None and thickness_mm is not None:
                q = det.to_mm(ring_px)
                f = fit_see_through_hole(q, pose.nadir_mm, pose.camera_height_mm, thickness_mm)
                if f is not None:
                    cands.append(
                        (
                            f"see-through cylinder, h={thickness_mm:.1f} mm",
                            f.cx,
                            f.cy,
                            f.r,
                            f.rms,
                            math.hypot(f.sigma_d, reproj),
                            q,
                        )
                    )
            else:
                H = H_top if (H_top is not None and not see_through) else det.H
                rm = apply_h(H, det.undistort(ring_px))
                cf = fit_circle(rm)
                name = "circle on the top-face plane" if H is H_top else "circle on the mat plane"
                cands.append((name, cf.cx, cf.cy, cf.r, cf.rms, _circle_sigma(cf.rms, cf.n, reproj), rm))
        if not cands:
            fm.reason = "no circle could be fitted"
            return
        fm.method, cx, cy, r, rms, sig_d, ring_mm = min(cands, key=lambda c: c[4] / max(c[3], 1e-6))
        fm.center_mm = (round(cx, 3), round(cy, 3))
        fm.rms_mm, fm.quality = rms, rms / max(r, 1e-6)
        fm.values["diameter"] = measured(2 * r, sig_d, f"{fm.method}, rms {rms:.3f} mm")
        fm.outline_mm = [(round(float(a), 3), round(float(b), 3)) for a, b in ring_mm[:: max(1, len(ring_mm) // 180)]]
        fm.ok = True
        return
    if fm.kind == "slot":
        # Same two candidates as a hole: the top-opening rim on the top-face plane, and the segmenter's own edge
        # (sub-pixel against the photo; the see-through model when the mat shows through the slot). The better obround fit wins.
        slot_cands = []
        H = H_top if H_top is not None else det.H
        if rim_px is not None and len(rim_px) >= 8:
            rm = apply_h(H, det.undistort(rim_px))
            slot_cands.append(("obround fit, top-opening rim", fit_slot(rm), rm))
        if ring_px is not None and len(ring_px) >= 8:
            see = float(np.mean(np.linalg.norm(img[mask].astype(np.float64) - stage_bgr, axis=1) < STAGE_COLOUR_TOL))
            if see >= SEE_THROUGH_FRACTION and H_top is not None and pose is not None and thickness_mm is not None:
                rm = det.to_mm(ring_px)
                slot_cands.append(
                    (
                        f"see-through obround, h={thickness_mm:.1f} mm",
                        fit_see_through_slot(rm, pose.nadir_mm, pose.camera_height_mm, thickness_mm),
                        rm,
                    )
                )
            else:
                rm = apply_h(det.H if see >= SEE_THROUGH_FRACTION else H, det.undistort(ring_px))
                slot_cands.append(("obround fit, segmented edge", fit_slot(rm), rm))
        ok_c = [(n, f, r) for n, f, r in slot_cands if f is not None]
        if not ok_c:
            fm.reason = "the region is not slot-shaped"
            return
        fm.method, sf, ring_mm = min(ok_c, key=lambda c: c[1].rms / max(c[1].width, 1e-6) if c[1] else math.inf)
        assert sf is not None
        fm.outline_mm = [(round(float(a), 3), round(float(b), 3)) for a, b in ring_mm[:: max(1, len(ring_mm) // 180)]]
        fm.center_mm = (round(sf.cx, 3), round(sf.cy, 3))
        fm.rms_mm, fm.quality = sf.rms, sf.rms / max(sf.width, 1e-6)
        sig = math.hypot(sf.rms, reproj)
        fm.values["length"] = measured(sf.length, sig, f"{fm.method}, rms {sf.rms:.3f} mm")
        fm.values["width"] = measured(sf.width, sig, f"{fm.method}, rms {sf.rms:.3f} mm")
        fm.values["angle_deg"] = Measured(value=round(math.degrees(sf.angle_rad) % 180.0, 2), source=Source.measured)
        fm.ok = True
        return
    if ring_px is None:
        ring_px = rim_px
    assert ring_px is not None
    H = H_top if H_top is not None else det.H
    ring_mm = apply_h(H, det.undistort(ring_px))
    fm.outline_mm = [(round(float(a), 3), round(float(b), 3)) for a, b in ring_mm[:: max(1, len(ring_mm) // 180)]]
    (cx, cy), L, W, _ = min_area_rect(ring_mm)
    fm.center_mm = (round(cx, 3), round(cy, 3))
    sig = math.hypot(0.1, reproj)
    if fm.kind == "tab":
        fm.method = "min-area rectangle"
        fm.values["length"] = measured(L, sig, "tab, min-area rectangle")
        fm.values["width"] = measured(W, sig, "tab, min-area rectangle")
    else:
        fm.method = "region"
        fm.values["extent"] = measured(L, sig, "broken region, longest extent")
        fm.values["area_mm2"] = Measured(value=round(abs(Polygon(ring_mm).area), 2), source=Source.measured)
    fm.ok = True


# ---------------------------------------------------------------- merging with the outline pass


def outline_hole_quality(out: MeasureOutput) -> list[float]:
    """rms/r of each hole the outline pass reported (same order as `Measurements.holes`)."""
    if out.features is None or out.result.measurements is None:
        return []
    fr = out.features.frame
    q: list[float] = []
    for cf, _ in out.features.holes:
        match = None
        for f in out.hole_fits:
            c = fr.to_part(np.array([[f.cx, f.cy]]))[0]
            if math.hypot(c[0] - cf.cx, c[1] - cf.cy) < max(cf.r, 0.5):
                match = f
        q.append((match.rms / match.r) if match is not None else cf.rms / max(cf.r, 1e-6))
    return q


def merge_holes(
    meas: Measurements, outline_quality: Sequence[float], features: Sequence[FeatureMeasurement]
) -> tuple[list[Hole], list[str]]:
    """Holes after combining the outline pass with point-derived holes.

    Rule: a point-derived hole matches an outline hole when their centres are within max(r, 1 mm). It replaces it only
    when its fit is strictly better (rms/r lower than the outline hole's `outline_quality`); otherwise the outline value
    stays and the point result is noted. Unmatched point holes are added — those are holes the outline pass missed.
    """
    M = np.asarray(meas.part_to_mat, dtype=np.float64)
    inv = np.linalg.inv(M) if M.shape == (3, 3) else np.eye(3)
    holes = list(meas.holes)
    q = list(outline_quality) + [math.inf] * max(0, len(holes) - len(outline_quality))
    notes: list[str] = []
    for fm in features:
        if fm.kind != "hole" or not fm.ok or fm.center_mm is None or "diameter" not in fm.values:
            continue
        c = (inv @ np.array([fm.center_mm[0], fm.center_mm[1], 1.0]))[:2]
        d = fm.values["diameter"]
        best_i, best_dist = -1, math.inf
        for i, h in enumerate(holes):
            dist = math.hypot(h.center_mm[0] - c[0], h.center_mm[1] - c[1])
            if dist < max(h.diameter.value / 2, 1.0) and dist < best_dist:
                best_i, best_dist = i, dist
        if best_i >= 0:
            h = holes[best_i]
            fq = fm.quality if fm.quality is not None else math.inf
            if fq < q[best_i]:
                holes[best_i] = Hole(
                    id=h.id,
                    center_mm=(round(float(c[0]), 3), round(float(c[1]), 3)),
                    diameter=d,
                    roundness_mm=h.roundness_mm,
                )
                q[best_i] = fq
                notes.append(f"{h.id}: point measurement used (fit rms/r {fq:.3f} better than the outline's)")
            else:
                notes.append(f"{h.id}: outline measurement kept (point fit rms/r {fq:.3f} not better)")
            continue
        new_id = f"hole_{len(holes) + 1}"
        holes.append(Hole(id=new_id, center_mm=(round(float(c[0]), 3), round(float(c[1]), 3)), diameter=d))
        q.append(fm.quality if fm.quality is not None else math.inf)
        notes.append(f"{new_id}: found from a {fm.point_source} point; the outline pass did not see it")
    return holes, notes


# ---------------------------------------------------------------- deterministic stand-in for the point segmenter


def region_grow_points(tolerance: float = 14.0) -> SegPointsCall:
    """Deterministic point segmenter (labelled mock): flood fill from the positive point on the image it is given,
    every pixel within `tolerance` (per channel) of the seed colour, never reaching a negative point."""

    def call(image_png: bytes, pos: list[PointPx], neg: list[PointPx], box: Box | None) -> list[tuple[BoolMask, float]]:
        try:
            img = decode_bgr(image_png)
        except ValueError:
            return []
        if not pos:
            return []
        h, w = img.shape[:2]
        sm = cv2.GaussianBlur(img, (0, 0), 0.8)
        out: list[tuple[BoolMask, float]] = []
        for p in pos:
            ff = np.zeros((h + 2, w + 2), np.uint8)
            seed = (int(np.clip(round(p[0]), 0, w - 1)), int(np.clip(round(p[1]), 0, h - 1)))
            tol = (tolerance,) * 3
            flags = 4 | cv2.FLOODFILL_MASK_ONLY | cv2.FLOODFILL_FIXED_RANGE | (1 << 8)
            cv2.floodFill(sm.copy(), ff, seed, (0, 0, 0), tol, tol, flags)
            m = ff[1:-1, 1:-1] > 0
            for q_ in neg:
                x, y = round(q_[0]), round(q_[1])
                if 0 <= y < h and 0 <= x < w and m[y, x]:
                    return []  # leaked into the board: no usable mask
            out.append((m, 0.9))
        return out

    return call
