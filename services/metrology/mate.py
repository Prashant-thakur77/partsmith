"""The "where it fits" photo: measure the mating feature (socket, shaft, slot or panel edge) in millimetres.

The mating photo is taken on the same mat as the part, so the same metrology applies: the markers give the mat plane,
the capture gate decides whether the photo is usable, and a point prompt (the user's tap, or a model pointing at the
photo) cuts the feature out. Code measures it; a model never says a size.

- ``mate_hole`` (a socket or bore the part goes into): circle fit to the opening's edge on the mat plane.
- ``mate_peg`` (a shaft or pin the part goes onto): a shaft lying on its side (a region at least ``SHAFT_ASPECT`` times
  longer than wide) is read from its two edges. Those edges are where the camera's rays graze the round section, not
  its diameter on the mat, so the diameter is solved from the camera position (pose) and the two edges exactly. A
  round region (a pin standing up) gets a circle fit on the mat plane.
- ``mate_slot`` (a slot the part's tab goes into, or a panel edge the part clips onto): the width between the region's
  two long sides (parallel-line fit), and its length.

The photo cannot tell how high a socket plate or a panel edge stands above the mat, so every reading except the lying
shaft carries a parallax allowance in its ±σ for an edge up to ``MATE_PLATE_MM`` above the mat (a stated choice: a
socket plate, a panel or a strip lying flat). σ also widens with the segmenter's confidence, and below
``confidence.RETAKE_BELOW`` the mate is not used and the job asks for a retake, exactly like the top view's features.

``propose_mates`` is the deterministic, labelled stand-in for a model pointing at the mating feature (mock mode): the
most prominent object on the stage, its opening if it has one. It never reads ground truth.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

import cv2
import numpy as np
from numpy.typing import NDArray
from partsmith_schemas.common import Evidence, Measured, Source
from partsmith_schemas.measurement import MateKind, MateMeasurement
from scipy.ndimage import distance_transform_edt
from scipy.optimize import least_squares

from .calibrate import MatDetection, PoseEstimate, apply_h
from .confidence import retake_reason, widen
from .features import SeeThroughFit, _fit_lens, _lens_residuals, fit_circle, fit_see_through_hole, min_area_rect
from .points import (
    POINT_NOTE,
    SEE_THROUGH_FRACTION,
    STAGE_COLOUR_TOL,
    SegPointsCall,
    _circle_sigma,
    _confidence_of,
    _crop_for,
    _outer_contour,
    _pick_mask,
    _png,
    stage_colour,
)

F64 = NDArray[np.float64]
U8 = NDArray[np.uint8]
BoolMask = NDArray[np.bool_]
PointPx = tuple[float, float]

MATE_KINDS: tuple[MateKind, ...] = ("mate_hole", "mate_peg", "mate_slot")
MATE_WORDS: dict[MateKind, str] = {"mate_hole": "socket", "mate_peg": "shaft", "mate_slot": "slot or panel edge"}
MATE_PLATE_MM = 3.0  # parallax allowance: an edge up to this high above the mat (stated choice, not fitted)
SHAFT_ASPECT = 2.0  # a peg region this elongated is a shaft lying on its side
MATE_CROP_HALF_MM = 40.0  # crop around a mate point (a shaft or a panel edge is longer than a hole)
DEFAULT_CAMERA_MM = 300.0  # only when the pose could not be solved (parallax allowance)
MOCK_POINT_LABEL = "MOCK: the most prominent object on the stage, picked by code; no model looked at the photo"


@dataclass(frozen=True)
class MatePoint:
    id: str
    kind: MateKind
    px: PointPx  # full-frame image pixel
    source: Literal["user", "model", "mock"] = "user"


@dataclass(frozen=True)
class StripFit:
    cx: float
    cy: float
    length: float
    width: float  # mean distance between the two long sides
    angle_rad: float  # direction of the long side
    rms: float
    n: int  # edge points used for the width
    edges: tuple[float, float]  # signed offsets of the two long sides from the centre, across the strip


def fit_strip(pts: F64) -> StripFit | None:
    """Two parallel long sides: the min-area rectangle gives the axis, then each side's offset is the mean of its edge
    points away from the ends (least squares for two parallel lines). None when the region is not elongated."""
    p = np.asarray(pts, dtype=np.float64)
    (cx, cy), L, W, th = min_area_rect(p)
    if L < 1.5 * W or W <= 0:
        return None
    u = np.array([math.cos(th), math.sin(th)])
    v = np.array([-u[1], u[0]])
    a = (p - [cx, cy]) @ u
    b = (p - [cx, cy]) @ v
    mid = np.abs(a) <= L / 2 - max(W, 0.1 * L)
    hi, lo = mid & (b > 0), mid & (b < 0)
    if hi.sum() < 6 or lo.sum() < 6:
        return None
    e_hi, e_lo = float(np.mean(b[hi])), float(np.mean(b[lo]))
    res = np.r_[b[hi] - e_hi, b[lo] - e_lo]
    return StripFit(
        float(cx), float(cy), float(L), e_hi - e_lo, float(th), float(np.sqrt(np.mean(res**2))), int(hi.sum() + lo.sum()),
        (e_hi, e_lo),
    )  # fmt: skip


def _grazing_edges(s_cam: float, h_cam: float, s0: float, r: float) -> tuple[float, float] | None:
    """Where the two rays from a camera at (s_cam, h_cam) that graze a circle (centre (s0, r), radius r, resting on
    the mat) meet the mat, in the cross-section plane (s across the shaft, height up)."""
    dx, dz = s0 - s_cam, r - h_cam
    d = math.hypot(dx, dz)
    if d <= r or dz >= 0:
        return None
    phi, alpha = math.atan2(dz, dx), math.asin(r / d)
    out = []
    for ang in (phi + alpha, phi - alpha):
        sz = math.sin(ang)
        if sz >= -1e-9:
            return None
        out.append(s_cam + (-h_cam / sz) * math.cos(ang))
    return min(out), max(out)


def shaft_diameter(edges_s: tuple[float, float], s_cam: float, h_cam: float) -> float | None:
    """Diameter of a round shaft lying on the mat from its two silhouette edges on the mat plane (cross-section
    coordinates), solved exactly for the camera position."""
    lo, hi = min(edges_s), max(edges_s)
    w = hi - lo
    if w <= 0 or h_cam <= w:
        return None

    def res(x: F64) -> F64:
        e = _grazing_edges(s_cam, h_cam, float(x[0]), float(x[1]))
        if e is None:
            return np.array([1e3, 1e3])
        return np.array([e[0] - lo, e[1] - hi])

    sol = least_squares(res, np.array([(lo + hi) / 2, w / 2]), method="lm")
    if not sol.success or float(np.max(np.abs(sol.fun))) > 1e-4:
        return None
    return 2 * float(sol.x[1])


LENS_MAX_PLATE_MM = 12.0  # plate thicknesses tried when the socket's own lens tells the plate height
LENS_STEP_MM = 0.25


def fit_socket_lens(q_ground: F64, pose: PoseEstimate) -> SeeThroughFit | None:
    """A socket in a plate of unknown thickness: the mat seen through it is the lens between the bottom opening (true
    size, on the mat) and the top opening projected from the camera. Scan the plate height, keep the one whose lens
    fits the boundary best, and fit the hole there (σ includes ±0.5 mm on that height). None when the lens tells
    nothing (no better than a plain circle)."""
    q = np.asarray(q_ground, dtype=np.float64).reshape(-1, 2)
    n = np.asarray(pose.nadir_mm, dtype=np.float64)
    h_cam = pose.camera_height_mm
    best: tuple[float, float] | None = None
    for h in np.arange(0.0, LENS_MAX_PLATE_MM + 1e-9, LENS_STEP_MM):
        sc = (h_cam - float(h)) / h_cam
        out = _fit_lens(q, n, sc)
        if out is None:
            continue
        x, _ = out
        rms = float(np.sqrt(np.mean(_lens_residuals(q, x[:2], float(x[2]), n, sc) ** 2)))
        if best is None or rms < best[1] - 1e-6:
            best = (float(h), rms)
    if best is None or best[0] <= 0.0:
        return None
    return fit_see_through_hole(q, pose.nadir_mm, h_cam, best[0], height_sigma_mm=0.5)


def _parallax(
    size_mm: float,
    centre_mm: tuple[float, float],
    pose: PoseEstimate | None,
    material: str | None,
    across: tuple[float, float] | None = None,
) -> tuple[float, float]:
    """(correction to add, σ) for an edge somewhere between the mat and MATE_PLATE_MM above it. At height h a
    material edge reads larger by up to (size + nadir offset)·h/(H − h) (its top is magnified; one wall may show) and
    the mat seen through an opening reads smaller by up to the same amount (the lens); for a strip only the offset
    across it (`across`: unit normal) counts. The reading is moved by half that range and σ is the other half, so
    any height in the range lands within ±σ."""
    h_cam = pose.camera_height_mm if pose is not None else DEFAULT_CAMERA_MM
    off = 0.0
    if pose is not None:
        d = (centre_mm[0] - pose.nadir_mm[0], centre_mm[1] - pose.nadir_mm[1])
        off = abs(d[0] * across[0] + d[1] * across[1]) if across is not None else math.hypot(*d)
    half = 0.5 * MATE_PLATE_MM * (size_mm + off) / max(h_cam - MATE_PLATE_MM, 1.0)
    return (half if material == "opening" else -half), half


PARALLAX_NOTE = f"moved by half the parallax of an edge 0–{MATE_PLATE_MM:g} mm above the mat; ±σ covers the rest"


def measure_mates(
    img: U8,
    det: MatDetection,
    pose: PoseEstimate | None,
    points: Sequence[MatePoint],
    segment_points_call: SegPointsCall,
    *,
    mask_source: str = "sam-3.1",
    negatives_px: Sequence[PointPx] = (),
) -> list[MateMeasurement]:
    """Measure each mate point. Never raises for one bad point: it comes back with ``ok=False`` and a reason."""
    img3 = img if img.ndim == 3 else np.asarray(cv2.cvtColor(img, cv2.COLOR_GRAY2BGR), dtype=np.uint8)
    stage_bgr = stage_colour(img3, det)
    out: list[MateMeasurement] = []
    for mp in points:
        mm = MateMeasurement(id=mp.id, kind=mp.kind, point_px=mp.px, point_source=mp.source, ok=False,
                             mask_source=mask_source)  # fmt: skip
        out.append(mm)
        x0, y0, x1, y1, negs_full = _mate_crop(det, mp.px, img3.shape[:2], negatives_px)
        if x1 - x0 < 8 or y1 - y0 < 8:
            mm.reason = "the point is outside the photo"
            continue
        crop = np.ascontiguousarray(img3[y0:y1, x0:x1])
        pos = (mp.px[0] - x0, mp.px[1] - y0)
        try:
            masks = segment_points_call(_png(crop), [pos], [(q[0] - x0, q[1] - y0) for q in negs_full], None)
        except Exception as e:  # one failed call is one failed mate, not a failed job
            mm.reason = f"segmentation failed: {type(e).__name__}: {e}"
            continue
        picked = _pick_mask(masks, pos)
        if picked is None:
            mm.reason = "the segmenter returned no mask for this point"
            continue
        m, score = picked
        full = np.zeros(img3.shape[:2], dtype=bool)
        sub = np.asarray(m[: y1 - y0, : x1 - x0], dtype=bool)
        full[y0:y1, x0:x1] = sub
        clipped = bool(sub[0, :].any() or sub[-1, :].any() or sub[:, 0].any() or sub[:, -1].any())
        _measure_one(mm, full, img3, stage_bgr, det, pose, clipped)
        conf, label = _confidence_of(mask_source, score)
        mm.confidence = None if conf is None else round(conf, 4)
        if mm.ok and conf is not None:
            mm.size = widen(mm.size, conf, label) if mm.size is not None else None
            mm.length = widen(mm.length, conf, label) if mm.length is not None else None
            what = f"the {MATE_WORDS[mp.kind]} at pixel ({mp.px[0]:.0f}, {mp.px[1]:.0f}) on the mating photo"
            mm.retake = retake_reason(what, conf)
            if mm.retake is not None:
                mm.ok = False
                mm.reason = mm.retake + (f" [{label}]" if label else "")
    return out


def unmix_wide(img: U8, mask: BoolMask, inside_px: int = 2, outside_px: int = 4) -> NDArray[np.float32]:
    """Soft coverage like `points.unmix_edges`, with the outside colour taken `outside_px` beyond the mask: a
    point-prompt or flood-fill mask often stops a pixel or two inside a blurred edge, and a colour sampled right next
    to it is still a mix, which pulls the 0.5 crossing inwards (−0.1 mm on a 6 mm shaft at 1 px of blur)."""
    m = np.asarray(mask, dtype=bool)
    if not m.any():
        return np.zeros(m.shape, np.float32)
    ys, xs = np.nonzero(m)
    pad = outside_px + 6
    y0, y1 = max(int(ys.min()) - pad, 0), min(int(ys.max()) + pad + 1, m.shape[0])
    x0, x1 = max(int(xs.min()) - pad, 0), min(int(xs.max()) + pad + 1, m.shape[1])
    sub = img[y0:y1, x0:x1].astype(np.float32)
    mm = m[y0:y1, x0:x1].astype(np.uint8)

    def k(r: int) -> NDArray[np.uint8]:
        return np.asarray(cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * r + 1, 2 * r + 1)), dtype=np.uint8)

    inner = cv2.erode(mm, k(inside_px)) > 0
    outer = ~(cv2.dilate(mm, k(outside_px)) > 0)
    if not inner.any() or not outer.any():
        return m.astype(np.float32)
    _, ii = distance_transform_edt(~inner, return_indices=True)
    _, oi = distance_transform_edt(~outer, return_indices=True)
    I_, O_ = sub[ii[0], ii[1]], sub[oi[0], oi[1]]
    v = I_ - O_
    alpha = np.clip(np.sum((sub - O_) * v, axis=2) / np.maximum(np.sum(v * v, axis=2), 1e-6), 0.0, 1.0)
    alpha = np.where(np.sum(v * v, axis=2) < 64.0, mm.astype(np.float32), alpha)  # alike on both sides: raster edge
    band = (cv2.dilate(mm, k(outside_px)) > 0) & ~inner
    soft = np.where(inner, 1.0, np.where(band, alpha, 0.0)).astype(np.float32)
    out = np.zeros(m.shape, np.float32)
    out[y0:y1, x0:x1] = soft
    return out


def _mate_crop(
    det: MatDetection, pt: PointPx, shape: tuple[int, int], negatives_px: Sequence[PointPx]
) -> tuple[int, int, int, int, list[PointPx]]:
    """The feature crop (with its negative points), widened to MATE_CROP_HALF_MM: a shaft or a panel edge is longer
    than a hole."""
    x0, y0, x1, y1, negs = _crop_for(det, pt, shape, negatives_px)
    mm = det.to_mm(np.array([pt], dtype=np.float64))[0]
    half = MATE_CROP_HALF_MM * det.px_per_mm_at((float(mm[0]), float(mm[1])))
    h, w = shape
    x0, y0 = max(min(x0, int(pt[0] - half)), 0), max(min(y0, int(pt[1] - half)), 0)
    x1, y1 = min(max(x1, math.ceil(pt[0] + half)), w), min(max(y1, math.ceil(pt[1] + half)), h)
    return x0, y0, x1, y1, negs


def _measure_one(
    mm: MateMeasurement,
    mask: BoolMask,
    img: U8,
    stage_bgr: F64,
    det: MatDetection,
    pose: PoseEstimate | None,
    clipped: bool = False,
) -> None:
    """Fit the mate's shape. `clipped`: the region reaches the crop's edge (a long shaft or panel), so only its width
    is measured, not its length; a round mate that is clipped is not measured at all."""
    ring_px = _outer_contour(unmix_wide(img, mask), mm.point_px)
    if ring_px is None or len(ring_px) < 12:
        mm.reason = "the mask is too small to measure"
        return
    see = float(np.mean(np.linalg.norm(img[mask].astype(np.float64) - stage_bgr, axis=1) < STAGE_COLOUR_TOL))
    mm.material = "opening" if see >= SEE_THROUGH_FRACTION else "material"
    ring = apply_h(det.H, det.undistort(ring_px))
    mm.outline_mm = [(round(float(a), 3), round(float(b), 3)) for a, b in ring[:: max(1, len(ring) // 180)]]
    reproj = det.reproj_mm_rms
    ev = [[round(mm.point_px[0], 2), round(mm.point_px[1], 2)]]

    def measured(v: float, sig: float, note: str) -> Measured:
        return Measured(value=round(v, 3), source=Source.measured, sigma_mm=round(sig, 3),
                        evidence=Evidence(view="mating", pixels=ev, note=f"{POINT_NOTE} ({mm.mask_source}); {note}"))  # fmt: skip

    (rcx, rcy), L, W, _ = min_area_rect(ring)
    strip = fit_strip(ring) if L >= SHAFT_ASPECT * W or mm.kind == "mate_slot" else None
    if mm.kind == "mate_peg" and strip is not None and L >= SHAFT_ASPECT * W:
        h_cam = pose.camera_height_mm if pose is not None else None
        d = None
        if pose is not None and h_cam is not None:
            n = np.array([-math.sin(strip.angle_rad), math.cos(strip.angle_rad)])
            c = np.array([strip.cx, strip.cy])
            s_cam = float((np.asarray(pose.nadir_mm) - c) @ n)
            d = shaft_diameter((strip.edges[1], strip.edges[0]), s_cam, h_cam)
        mm.shape, mm.center_mm = "strip", (round(strip.cx, 3), round(strip.cy, 3))
        sig = math.hypot(2 * strip.rms / math.sqrt(max(strip.n / 8.0, 1.0)), reproj)
        if d is None:
            corr, par = _parallax(strip.width, (strip.cx, strip.cy), pose, "material")
            mm.method = f"shaft on its side: edge-to-edge width on the mat plane (no camera pose), {PARALLAX_NOTE}"
            d, sig = strip.width + corr, math.hypot(sig, par)
        else:
            mm.method = f"shaft on its side: round section solved from both edges, camera {h_cam:.0f} mm up"
            sig = math.hypot(sig, 0.25 * abs(strip.width - d))  # the camera is not exactly in the cross-section plane
        mm.size = measured(d, sig, f"{mm.method}; edges {strip.width:.3f} mm apart, rms {strip.rms:.3f} mm")
        if not clipped:
            mm.length = measured(strip.length, math.hypot(0.1, reproj), "shaft length, min-area rectangle")
        mm.ok = True
        return
    if mm.kind in ("mate_hole", "mate_peg"):
        if clipped:
            mm.reason = f"the {MATE_WORDS[mm.kind]} region runs past the {2 * MATE_CROP_HALF_MM:g} mm crop: not a " \
                        "round feature; tap inside the socket or on the shaft"  # fmt: skip
            return
        cf = fit_circle(ring)
        lens = fit_socket_lens(ring, pose) if mm.kind == "mate_hole" and mm.material == "opening" and pose else None
        if lens is not None and lens.rms < cf.rms:
            mm.method = f"see-through socket: lens fit, plate {lens.height_mm:.2f} mm high (solved from the lens)"
            mm.shape, mm.center_mm = "round", (round(lens.cx, 3), round(lens.cy, 3))
            sig = math.hypot(lens.sigma_d, reproj)
            mm.size = measured(2 * lens.r, sig, f"{mm.method}, rms {lens.rms:.3f} mm")
            mm.ok = True
            return
        corr, par = _parallax(2 * cf.r, (cf.cx, cf.cy), pose, mm.material)
        sig = math.hypot(_circle_sigma(cf.rms, cf.n, reproj), par)
        what = "opening" if mm.material == "opening" else "outline"
        mm.method = f"circle fit to the {what} on the mat plane"
        if mm.kind == "mate_peg":
            mm.method += " (a standing pin reads its top edge; lay a shaft on its side for the exact reading)"
        mm.shape, mm.center_mm = "round", (round(cf.cx, 3), round(cf.cy, 3))
        note = f"{mm.method}, rms {cf.rms:.3f} mm; {PARALLAX_NOTE}"
        mm.size = measured(2 * cf.r + corr, sig, note)
        mm.ok = True
        if L > 1.3 * W:
            mm.reason = f"not round ({L:.2f} × {W:.2f} mm): the circle fit is an average"
        return
    if strip is None:
        mm.shape, mm.center_mm = "region", (round(float(rcx), 3), round(float(rcy), 3))
        mm.reason = f"the region is not slot-shaped ({L:.2f} × {W:.2f} mm); tap the slot or the panel's edge"
        return
    normal = (-math.sin(strip.angle_rad), math.cos(strip.angle_rad))
    corr, par = _parallax(strip.width, (strip.cx, strip.cy), pose, mm.material, normal)
    sig = math.hypot(2 * strip.rms / math.sqrt(max(strip.n / 8.0, 1.0)), reproj, par)
    mm.shape, mm.center_mm = "strip", (round(strip.cx, 3), round(strip.cy, 3))
    mm.method = "width between the two long sides (parallel-line fit) on the mat plane"
    note = f"{mm.method}, rms {strip.rms:.3f} mm; {PARALLAX_NOTE}"
    mm.size = measured(strip.width + corr, sig, note)
    if not clipped:
        mm.length = measured(strip.length, math.hypot(0.1, reproj), "length, min-area rectangle")
    mm.ok = True


# ---------------------------------------------------------------- deterministic stand-in for a model pointing


def propose_mates(img: U8, det: MatDetection, kind_hint: MateKind | None = None) -> list[MatePoint]:
    """MOCK pointer (labelled): the largest object on the stage that is not the stage colour; if it encloses an
    opening and the hint allows a socket or slot, point inside the opening, otherwise at the object's deepest point.
    The kind is the hint, else guessed from the shape (opening → socket, elongated → shaft, else slot)."""
    img3 = img if img.ndim == 3 else np.asarray(cv2.cvtColor(img, cv2.COLOR_GRAY2BGR), dtype=np.uint8)
    st = det.mat.stage.inset(3.0)
    poly = np.round(det.to_px(st.corners()) * 16).astype(np.int32)
    stage = np.zeros(img3.shape[:2], np.uint8)
    cv2.fillPoly(stage, [poly], 1, cv2.LINE_8, shift=4)
    bg = stage_colour(img3, det)
    diff = np.linalg.norm(img3.astype(np.float64) - bg, axis=2) > 2 * STAGE_COLOUR_TOL
    obj = (diff & (stage > 0)).astype(np.uint8)
    obj = np.asarray(cv2.morphologyEx(obj, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8)), dtype=np.uint8)
    n, lab, stats, _ = cv2.connectedComponentsWithStats(obj, connectivity=8)
    if n <= 1:
        return []
    i = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    blob = (lab == i).astype(np.uint8)
    filled = blob.copy()
    cs, _ = cv2.findContours(blob, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    cv2.drawContours(filled, cs, -1, 1, thickness=cv2.FILLED)
    holes = (filled > 0) & (blob == 0) & (stage > 0)
    hn, hlab, hstats, _ = cv2.connectedComponentsWithStats(holes.astype(np.uint8), connectivity=8)
    if hn > 1 and kind_hint in (None, "mate_hole", "mate_slot"):
        j = 1 + int(np.argmax(hstats[1:, cv2.CC_STAT_AREA]))
        if hstats[j, cv2.CC_STAT_AREA] >= 30:
            dist = cv2.distanceTransform((hlab == j).astype(np.uint8), cv2.DIST_L2, 5)
            y, x = np.unravel_index(int(np.argmax(dist)), dist.shape)
            ring = apply_h(det.H, det.undistort(np.argwhere(hlab == j)[:, ::-1].astype(np.float64)))
            _, L, W, _ = min_area_rect(ring)
            kind: MateKind = kind_hint or ("mate_slot" if L >= 2.0 * W else "mate_hole")
            return [MatePoint("mate_1", kind, (float(x), float(y)), "mock")]
    dist = cv2.distanceTransform(blob, cv2.DIST_L2, 5)
    y, x = np.unravel_index(int(np.argmax(dist)), dist.shape)
    pts = apply_h(det.H, det.undistort(np.argwhere(blob > 0)[::7, ::-1].astype(np.float64)))
    _, L, W, _ = min_area_rect(pts)
    guess: MateKind = kind_hint or ("mate_peg" if L >= SHAFT_ASPECT * W else "mate_slot")
    return [MatePoint("mate_1", guess, (float(x), float(y)), "mock")]


# ---------------------------------------------------------------- overlay


def mate_overlay(img: U8, det: MatDetection, mates: Sequence[MateMeasurement], max_side: int = 1400) -> bytes:
    """The mating photo (cropped around the mates) with each measured outline and its size drawn on."""
    pts_px: list[F64] = []
    for m in mates:
        if m.outline_mm:
            pts_px.append(det.to_px(np.asarray(m.outline_mm, dtype=np.float64)))
        pts_px.append(np.asarray([m.point_px], dtype=np.float64))
    allp = np.concatenate(pts_px) if pts_px else np.zeros((0, 2))
    h, w = img.shape[:2]
    if len(allp):
        pad = 0.15 * max(float(np.ptp(allp[:, 0])), float(np.ptp(allp[:, 1])), 200.0)
        x0, y0 = max(int(allp[:, 0].min() - pad), 0), max(int(allp[:, 1].min() - pad), 0)
        x1, y1 = min(int(allp[:, 0].max() + pad), w), min(int(allp[:, 1].max() + pad), h)
    else:
        x0, y0, x1, y1 = 0, 0, w, h
    out = np.ascontiguousarray(img[y0:y1, x0:x1].copy())
    s = min(1.0, max_side / max(out.shape[:2]))
    if s < 1.0:
        out = np.asarray(
            cv2.resize(out, (round(out.shape[1] * s), round(out.shape[0] * s)), interpolation=cv2.INTER_AREA),
            dtype=np.uint8,
        )
    lw = max(2, round(out.shape[1] / 500))
    for m, ring_px in zip(
        mates, [det.to_px(np.asarray(m.outline_mm)) if m.outline_mm else None for m in mates], strict=True
    ):
        col = (60, 200, 60) if m.ok else (40, 40, 230)
        if ring_px is not None:
            q = np.round((ring_px - [x0, y0]) * s * 4).astype(np.int32).reshape(-1, 1, 2)
            cv2.polylines(out, [q], True, col, lw, cv2.LINE_AA, shift=2)
        px = (round((m.point_px[0] - x0) * s), round((m.point_px[1] - y0) * s))
        cv2.drawMarker(out, px, col, cv2.MARKER_CROSS, 6 * lw, lw, cv2.LINE_AA)
        text = (f"{m.id}: {'Ø' if m.shape == 'round' or m.kind == 'mate_peg' else 'w '}{m.size.value:.2f} ± "
                f"{m.size.sigma_mm:.2f} mm") if m.ok and m.size is not None else f"{m.id}: not measured"  # fmt: skip
        text = text.replace("Ø", "D ")  # Hershey fonts have no Ø
        org = (min(px[0] + 4 * lw, out.shape[1] - 10), max(px[1] - 4 * lw, 14))
        fs = 0.45 * lw
        cv2.putText(out, text, org, cv2.FONT_HERSHEY_SIMPLEX, fs, (0, 0, 0), 3 * lw, cv2.LINE_AA)
        cv2.putText(out, text, org, cv2.FONT_HERSHEY_SIMPLEX, fs, (255, 255, 255), lw, cv2.LINE_AA)
    return _png(out)
