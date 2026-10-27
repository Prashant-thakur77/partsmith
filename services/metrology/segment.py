"""Part segmentation: a `Segmenter` protocol, a deterministic threshold segmenter for the plain mat stage, a provider
segmenter (SAM 3.1 through the providers package) with a prompt ladder, and mask post-processing with sub-pixel contours.

All masks are full-frame booleans in image pixels.
"""

from __future__ import annotations

import io
import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

import cv2
import numpy as np
from numpy.typing import NDArray

from .calibrate import MatDetection

F64 = NDArray[np.float64]
F32 = NDArray[np.float32]
U8 = NDArray[np.uint8]
BoolMask = NDArray[np.bool_]

# Provider ladder (PLAN §5.4): stop early on a confident mask, ignore anything below the floor.
EARLY_EXIT_SCORE = 0.85
SCORE_FLOOR = 0.4
DUPLICATE_IOU = 0.72
CROP_MARGIN = 0.15
CROP_ACCEPT_IOU = 0.8
PROVIDER_MAX_SIDE_PX = 2016  # ≈ 2× SAM's 1008 px input; keeps request bodies small
DEFAULT_LADDER = ("plastic part", "broken plastic piece")

THRESHOLD_SOURCE = "threshold"
MIN_PART_AREA_MM2 = 4.0  # Measurements.mask_source literal for the deterministic segmenter


@dataclass
class SegContext:
    """What a segmenter may know about the photo: the detected mat (stage location) and colours to treat as background."""

    det: MatDetection
    ignore_hue_deg: tuple[float, float] | None = None  # e.g. the fit-check outline colour drawn on the screen
    ignore_min_saturation: float = 0.35


@dataclass
class SegResult:
    mask: BoolMask
    score: float
    source: str
    prob: F32 | None = None  # soft coverage map (0..1) when available; gives sub-pixel edges
    prompt: str | None = None
    attempts: list[dict[str, Any]] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    largest_fraction: float | None = None  # share of the raw foreground in the kept component (fragmentation)
    background: Callable[[NDArray[np.float64]], NDArray[np.float64]] | None = None  # stage colour model at image px


class Segmenter(Protocol):
    def segment(self, img: U8, prompt: str, *, context: SegContext | None = None) -> SegResult: ...


# ---------------------------------------------------------------- mask post-processing


def _disk(d_px: float) -> U8:
    k = max(1, round(d_px))
    if k % 2 == 0:
        k += 1
    return np.asarray(cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k)), dtype=np.uint8)


def fill_holes(mask: BoolMask, max_area_px: float | None = None) -> BoolMask:
    """Fill background regions not connected to the image border (all of them, or only those ≤ `max_area_px`)."""
    m = mask.astype(np.uint8)
    inv = (1 - m).astype(np.uint8)
    n, lab, stats, _ = cv2.connectedComponentsWithStats(inv, connectivity=4)
    h, w = m.shape
    out = mask.copy()
    for i in range(1, n):
        x, y, bw, bh, area = stats[i]
        touches = x == 0 or y == 0 or x + bw == w or y + bh == h
        if touches:
            continue
        if max_area_px is None or area <= max_area_px:
            out[lab == i] = True
    return out


def _largest_fraction(mask: BoolMask, px_per_mm2: float, min_mm2: float = 1.0) -> float:
    """Share of the foreground (pieces ≥ `min_mm2`) that lies in the largest piece; 1.0 = one solid part."""
    _, _, stats, _ = cv2.connectedComponentsWithStats(mask.astype(np.uint8), connectivity=8)
    areas = stats[1:, cv2.CC_STAT_AREA].astype(np.float64)
    areas = areas[areas >= min_mm2 * px_per_mm2]
    return float(areas.max() / areas.sum()) if len(areas) else 0.0


def largest_component(mask: BoolMask) -> BoolMask:
    n, lab, stats, _ = cv2.connectedComponentsWithStats(mask.astype(np.uint8), connectivity=8)
    if n <= 1:
        return np.zeros_like(mask, dtype=bool)
    return np.asarray(lab == 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA])), dtype=bool)


def refine_mask(
    mask: BoolMask,
    px_per_mm: float,
    *,
    close_mm: float = 0.3,
    open_mm: float = 0.3,
    min_speck_mm2: float = 2.0,
    min_hole_mm2: float = 0.5,
    keep: str = "largest",
) -> BoolMask:
    """Clean a part mask: close/open, drop specks < `min_speck_mm2`, fill holes < `min_hole_mm2` (real holes stay).

    `keep="largest"` returns only the largest component; `keep="all"` keeps every component above the speck size.
    """
    m = mask.astype(np.uint8)
    if close_mm > 0:
        m = np.asarray(cv2.morphologyEx(m, cv2.MORPH_CLOSE, _disk(close_mm * px_per_mm)), dtype=np.uint8)
    if open_mm > 0:
        m = np.asarray(cv2.morphologyEx(m, cv2.MORPH_OPEN, _disk(open_mm * px_per_mm)), dtype=np.uint8)
    px2 = px_per_mm**2
    n, lab, stats, _ = cv2.connectedComponentsWithStats(m, connectivity=8)
    out = np.zeros(m.shape, dtype=bool)
    if n > 1:
        areas = stats[1:, cv2.CC_STAT_AREA]
        if keep == "largest":
            i = 1 + int(np.argmax(areas))
            if areas[i - 1] >= min_speck_mm2 * px2:
                out = lab == i
        else:
            for i in range(1, n):
                if areas[i - 1] >= min_speck_mm2 * px2:
                    out |= lab == i
    return fill_holes(out, max_area_px=min_hole_mm2 * px2)


@dataclass
class Contour:
    points_px: F64  # (N, 2) sub-pixel image coordinates
    is_hole: bool
    parent: int  # index of the enclosing outer contour, -1 for outer contours
    area_px: float


def _refine_along_normals(field_up: F32, pts: F64, reach: float = 2.5, step: float = 0.25) -> F64:
    """Move contour points (upsampled grid) to the nearest 0.5 crossing of `field_up` along the local normal."""
    n = len(pts)
    if n < 5:
        return pts
    k = 2
    tang = np.roll(pts, -k, axis=0) - np.roll(pts, k, axis=0)
    norm = np.linalg.norm(tang, axis=1, keepdims=True)
    tang = tang / np.maximum(norm, 1e-9)
    nrm = np.c_[-tang[:, 1], tang[:, 0]]
    offs = np.arange(-reach, reach + 1e-9, step)
    samp = pts[:, None, :] + offs[None, :, None] * nrm[:, None, :]
    vals = (
        cv2.remap(
            field_up,
            samp[..., 0].astype(np.float32),
            samp[..., 1].astype(np.float32),
            cv2.INTER_LINEAR,
            borderMode=cv2.BORDER_REPLICATE,
        ).astype(np.float64)
        - 0.5
    )
    sign_change = vals[:, :-1] * vals[:, 1:] <= 0
    mid = (offs[:-1] + offs[1:]) / 2
    score = np.where(sign_change, np.abs(mid)[None, :], np.inf)
    j = np.argmin(score, axis=1)
    has = np.isfinite(score[np.arange(n), j])
    v0, v1 = vals[np.arange(n), j], vals[np.arange(n), j + 1]
    frac = np.where(np.abs(v1 - v0) > 1e-9, -v0 / np.where(np.abs(v1 - v0) > 1e-9, v1 - v0, 1.0), 0.5)
    t = offs[j] + np.clip(frac, 0, 1) * step
    out = pts.copy()
    out[has] = pts[has] + t[has, None] * nrm[has]
    return out


def mask_contour_subpx(
    mask_or_prob: BoolMask | F32,
    *,
    upsample: int = 4,
    blur_px: float | None = None,
    min_area_px: float = 4.0,
) -> list[Contour]:
    """Sub-pixel contours (outer + holes) of a mask or soft coverage map.

    The field is upsampled `upsample`× (bilinear) — binary masks are first blurred (`blur_px`, default 0.6 px) to remove
    the pixel staircase — traced at 0.5, and each point is then moved to the interpolated 0.5 crossing along its normal.
    Coordinates are image pixels (integer = pixel centre).
    """
    f = np.asarray(mask_or_prob)
    is_binary = f.dtype == bool or (f.dtype == np.uint8)
    field0 = f.astype(np.float32)
    if f.dtype == np.uint8 and field0.max() > 1:
        field0 /= 255.0
    ys, xs = np.nonzero(field0 >= 0.5)
    if len(xs) == 0:
        return []
    pad = 4
    h, w = field0.shape
    x0, y0 = max(int(xs.min()) - pad, 0), max(int(ys.min()) - pad, 0)
    x1, y1 = min(int(xs.max()) + pad + 1, w), min(int(ys.max()) + pad + 1, h)
    roi = field0[y0:y1, x0:x1]
    if is_binary:
        sigma = 0.6 if blur_px is None else blur_px
        if sigma > 0:
            roi = np.asarray(cv2.GaussianBlur(roi, (0, 0), sigma), dtype=np.float32)
    elif blur_px:
        roi = np.asarray(cv2.GaussianBlur(roi, (0, 0), blur_px), dtype=np.float32)
    up = np.asarray(
        cv2.resize(roi, ((x1 - x0) * upsample, (y1 - y0) * upsample), interpolation=cv2.INTER_LINEAR), dtype=np.float32
    )
    binary = (up >= 0.5).astype(np.uint8)
    cs, hier = cv2.findContours(binary, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_NONE)
    if hier is None:
        return []
    out: list[Contour] = []
    index_map: dict[int, int] = {}
    order = sorted(range(len(cs)), key=lambda i: hier[0][i][3] >= 0)  # outers first
    for i in order:
        c = cs[i]
        area = cv2.contourArea(c) / upsample**2
        if area < min_area_px:
            continue
        parent_raw = int(hier[0][i][3])
        if parent_raw >= 0 and parent_raw not in index_map:
            continue
        pts = c.reshape(-1, 2).astype(np.float64)
        pts = _refine_along_normals(up, pts)
        img_pts = (pts + 0.5) / upsample - 0.5 + np.array([x0, y0], dtype=np.float64)
        index_map[i] = len(out)
        out.append(
            Contour(
                points_px=img_pts,
                is_hole=parent_raw >= 0,
                parent=index_map.get(parent_raw, -1) if parent_raw >= 0 else -1,
                area_px=float(area),
            )
        )
    return out


def mask_iou(a: BoolMask, b: BoolMask) -> float:
    u = int(np.count_nonzero(a | b))
    return float(np.count_nonzero(a & b) / u) if u else 0.0


# ---------------------------------------------------------------- threshold segmenter


def _otsu(values: F64, bins: int = 256) -> tuple[float, float]:
    """Otsu threshold and separability η = σ_between² / σ_total² of a 1-D sample."""
    v = values[np.isfinite(values)]
    if len(v) < 2:
        return float("nan"), 0.0
    lo, hi = float(v.min()), float(v.max())
    if hi - lo < 1e-9:
        return lo, 0.0
    hist, edges = np.histogram(v, bins=bins, range=(lo, hi))
    p = hist.astype(np.float64) / hist.sum()
    centers = (edges[:-1] + edges[1:]) / 2
    w0 = np.cumsum(p)
    mu = np.cumsum(p * centers)
    mu_t = mu[-1]
    w1 = 1 - w0
    with np.errstate(divide="ignore", invalid="ignore"):
        sb = (mu_t * w0 - mu) ** 2 / (w0 * w1)
    sb[~np.isfinite(sb)] = 0
    k = int(np.argmax(sb))
    var_t = float(np.sum(p * (centers - mu_t) ** 2))
    return float(edges[k + 1]), float(sb[k] / var_t) if var_t > 0 else 0.0


# A cast shadow keeps at least this share of the stage's brightness: with ordinary room light filling in, a desk-lamp
# shadow is rarely darker than half the lit surface. One bound for pixels, for the part's own colour and for the gate.
SHADOW_MIN_RATIO = 0.50
SHADOW_CHROMA_TOL = 8.0  # max colour distance (8-bit) from the darkened stage colour
SHADOW_MAX_GRADIENT = 60.0  # grey levels per mm at 0.25 mm blur: penumbras stay below, part edges far above
SHADOW_KEEP_FRACTION = 0.5
# A part whose own colour is within this of the darkened stage colour is treated as shadow-coloured (no suppression).
PART_SHADOW_CHROMA_TOL = 16.0
PART_SHADOW_MIN_RATIO = SHADOW_MIN_RATIO  # white, off-white and light/mid-grey parts on a white stage


def _shadow_cone_distance(
    roi: NDArray[np.float32], bg: NDArray[np.float32], k_min: float = SHADOW_MIN_RATIO, k_max: float = 1.0
) -> NDArray[np.float32]:
    """Distance of each pixel from the 'shadow cone' {k·B : k ∈ [k_min, k_max]} of the local stage colour B."""
    bb = np.maximum(np.sum(bg * bg, axis=2), 1e-6)
    k = np.clip(np.sum(roi * bg, axis=2) / bb, k_min, k_max)
    return np.asarray(np.linalg.norm(roi - k[..., None] * bg, axis=2), dtype=np.float32)


SHADOW_CUT_MIN_EDGE = 0.3


def _cut_follows_edge(roi: NDArray[np.float32], core: BoolMask, kept: BoolMask) -> bool:
    """True when the line between the kept part and the removed 'shadow' is a real edge.

    A part meets its own shadow at a sharp step (its outline); a shadow-coloured patch inside a uniformly grey part
    has no step there. Compare the image gradient along the cut with the gradient along the part's edge against the
    bare stage: the cut must carry at least `SHADOW_CUT_MIN_EDGE` of it.
    """
    # Colour gradient (all three channels): a yellow part against grey shadowed paper differs in hue, not brightness.
    g = np.asarray(cv2.GaussianBlur(roi, (0, 0), 1.0), dtype=np.float32)
    gx, gy = cv2.Sobel(g, cv2.CV_32F, 1, 0), cv2.Sobel(g, cv2.CV_32F, 0, 1)
    mag = np.sqrt(np.sum(gx * gx + gy * gy, axis=2))
    k3 = np.ones((3, 3), np.uint8)
    rim = kept & ~(cv2.erode(kept.astype(np.uint8), k3) > 0)
    removed = core & ~kept
    near_removed = cv2.dilate(removed.astype(np.uint8), np.ones((5, 5), np.uint8)) > 0
    near_stage = cv2.dilate((~core).astype(np.uint8), np.ones((5, 5), np.uint8)) > 0
    cut = rim & near_removed & ~near_stage
    edge = rim & near_stage & ~near_removed
    if cut.sum() < 10 or edge.sum() < 10:
        return True
    # The edge may lie a pixel either side of the rim: take the local maximum of the gradient.
    mag_max = cv2.dilate(mag, np.ones((5, 5), np.uint8))
    return bool(np.median(mag_max[cut]) >= SHADOW_CUT_MIN_EDGE * np.median(mag_max[edge]))


def _smooth(roi: NDArray[np.float32], px_per_mm: float) -> NDArray[np.bool_]:
    """Pixels without sharp structure at ~0.5 mm scale (shadow interiors and penumbras)."""
    g = cv2.cvtColor(np.clip(roi, 0, 255).astype(np.uint8), cv2.COLOR_BGR2GRAY).astype(np.float32)
    sig = max(0.5 * px_per_mm / 2.0, 0.8)
    gb = cv2.GaussianBlur(g, (0, 0), sig)
    gx = cv2.Sobel(gb, cv2.CV_32F, 1, 0, ksize=3) / 8.0
    gy = cv2.Sobel(gb, cv2.CV_32F, 0, 1, ksize=3) / 8.0
    grad_mm = np.hypot(gx, gy) * px_per_mm
    return np.asarray(grad_mm < SHADOW_MAX_GRADIENT, dtype=bool)


def _bg_model(coef: F64, x0: int, y0: int, sx: float, sy: float) -> Callable[[F64], F64]:
    """The fitted stage colour (BGR) at full-frame image points."""

    def at(pts_px: F64) -> F64:
        p = np.asarray(pts_px, dtype=np.float64).reshape(-1, 2)
        A = _poly_design((p[:, 0] - x0 - sx) / sx, (p[:, 1] - y0 - sy) / sy)
        return np.asarray(A @ coef, dtype=np.float64)

    return at


def _poly_design(x: F64, y: F64) -> F64:
    return np.asarray(np.c_[np.ones_like(x), x, y, x * x, y * y, x * y], dtype=np.float64)


@dataclass
class ThresholdSegmenter:
    """Deterministic segmentation against the plain mat stage.

    The background colour is modelled per channel as a quadratic over the image (screens and lamps are not uniform),
    fitted robustly to a band just inside the stage border. Pixels are scored by colour distance to that model, split
    with Otsu, cleaned, and thin structures up to `min_line_mm` wide (e.g. a 1:1 outline drawn on the screen) are removed
    by an opening. The returned `prob` map is the colour distance normalised by the part's typical distance, which for
    anti-aliased edges equals pixel coverage — so contours of `prob` are sub-pixel.
    """

    band_mm: float = 4.0
    min_line_mm: float = 1.0
    min_contrast: float = 18.0  # minimum colour distance (8-bit units) for anything to count as part
    source: str = THRESHOLD_SOURCE
    suppress_shadows: bool = True

    def segment(self, img: U8, prompt: str = "plastic part", *, context: SegContext | None = None) -> SegResult:
        if context is None:
            raise ValueError("ThresholdSegmenter needs the detected mat (SegContext) to know where the stage is")
        det = context.det
        stage = det.mat.stage
        h_img, w_img = img.shape[:2]
        img3 = img if img.ndim == 3 else cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
        stage_px = det.to_px(stage.corners())
        inner_px = det.to_px(stage.inset(self.band_mm).corners())
        x0 = max(math.floor(stage_px[:, 0].min()) - 2, 0)
        y0 = max(math.floor(stage_px[:, 1].min()) - 2, 0)
        x1 = min(math.ceil(stage_px[:, 0].max()) + 3, w_img)
        y1 = min(math.ceil(stage_px[:, 1].max()) + 3, h_img)
        empty = np.zeros((h_img, w_img), dtype=bool)
        if x1 - x0 < 8 or y1 - y0 < 8:
            return SegResult(empty, 0.0, self.source, notes=["The stage is outside the photo."])
        off = np.array([x0, y0], dtype=np.float64)
        rw, rh = x1 - x0, y1 - y0
        stage_m = np.zeros((rh, rw), np.uint8)
        cv2.fillPoly(stage_m, [np.round((stage_px - off) * 16).astype(np.int32)], 1, cv2.LINE_8, shift=4)
        inner_m = np.zeros((rh, rw), np.uint8)
        cv2.fillPoly(inner_m, [np.round((inner_px - off) * 16).astype(np.int32)], 1, cv2.LINE_8, shift=4)
        band = (stage_m > 0) & (inner_m == 0)
        roi = img3[y0:y1, x0:x1].astype(np.float32)

        # Robust quadratic background model per channel, fitted on the border band.
        by, bx = np.nonzero(band)
        if len(bx) < 50:
            return SegResult(empty, 0.0, self.source, notes=["The stage border is not visible."])
        rng = np.random.default_rng(0)
        if len(bx) > 30000:
            sel = rng.choice(len(bx), 30000, replace=False)
            bx, by = bx[sel], by[sel]
        sx, sy = rw / 2.0, rh / 2.0
        A = _poly_design((bx - sx) / sx, (by - sy) / sy)
        vals = roi[by, bx].astype(np.float64)
        keep = np.ones(len(bx), dtype=bool)
        coef = np.zeros((6, 3))
        for _ in range(4):
            coef, *_ = np.linalg.lstsq(A[keep], vals[keep], rcond=None)
            res = np.linalg.norm(vals - A @ coef, axis=1)
            mad = float(np.median(res[keep])) + 1e-6
            keep = res < max(4.0 * 1.4826 * mad, 6.0)
        noise = float(np.median(np.linalg.norm(vals[keep] - A[keep] @ coef, axis=1))) * 1.4826
        yy, xx = np.mgrid[0:rh, 0:rw].astype(np.float64)
        D = _poly_design(((xx - sx) / sx).ravel(), ((yy - sy) / sy).ravel())
        bg = (D @ coef).reshape(rh, rw, 3).astype(np.float32)
        dist = np.linalg.norm(roi - bg, axis=2)

        inside_stage = stage_m > 0
        if context.ignore_hue_deg is not None:
            # Lines drawn on the screen (fit-check outline) are background too. Their anti-aliased edges blend the
            # line colour with the stage colour, so score pixels by their distance to the stage→line colour segment.
            hsv = cv2.cvtColor(img3[y0:y1, x0:x1], cv2.COLOR_BGR2HSV_FULL).astype(np.float32)
            hue = hsv[..., 0] * 360.0 / 256.0
            sat = hsv[..., 1] / 255.0
            lo, hi = context.ignore_hue_deg
            in_hue = (hue >= lo) & (hue <= hi) if lo <= hi else (hue >= lo) | (hue <= hi)
            line_px = in_hue & (sat >= context.ignore_min_saturation) & inside_stage
            if np.count_nonzero(line_px) >= 20:
                C = np.median(roi[line_px], axis=0).astype(np.float32)
                v = C[None, None, :] - bg
                t = np.clip(np.sum((roi - bg) * v, axis=2) / np.maximum(np.sum(v * v, axis=2), 1e-6), 0.0, 1.0)
                dist = np.linalg.norm(roi - (bg + t[..., None] * v), axis=2).astype(np.float32)

        inside = inside_stage
        floor = max(self.min_contrast, 5.0 * noise)
        px_mm = det.px_per_mm_at((stage.x_mm + stage.w_mm / 2, stage.y_mm + stage.h_mm / 2))
        k = _disk(self.min_line_mm * 1.25 * px_mm)
        min_area_px = MIN_PART_AREA_MM2 * px_mm**2
        # Otsu separates the part from the stage; when it splits off something else instead (dark lines drawn on the
        # screen next to a light part), the class above the threshold vanishes after thin-line removal and Otsu is
        # re-run on the values below it.
        vals_in = dist[inside].astype(np.float64)
        upper = float("inf")
        core = np.zeros_like(inside)
        thr, eta = floor, 0.0
        for _ in range(3):
            t, e = _otsu(vals_in[vals_in <= upper])
            thr = max(t if np.isfinite(t) else floor, floor)
            cand = ((dist > thr) & inside).astype(np.uint8)
            if self.min_line_mm > 0:
                opened = cv2.morphologyEx(cand, cv2.MORPH_OPEN, k)
                cand_b = (cand > 0) & (cv2.dilate(opened, k) > 0)
            else:
                cand_b = cand > 0
            core = largest_component(cand_b)
            eta = e
            if np.count_nonzero(core) >= min_area_px or thr <= floor:
                break
            upper = thr
        if np.count_nonzero(core) < min_area_px:
            return SegResult(empty, 0.0, self.source, notes=["No part found on the stage."])
        largest_fraction = _largest_fraction(cand_b, px_mm**2)
        notes: list[str] = []

        # Cast shadows: the stage colour scaled down (same chroma, darker) and smooth. Remove them unless the part
        # itself looks like that (a light-grey or white part on a white stage), which the contrast check reports.
        shadow_zone: BoolMask = np.zeros(core.shape, dtype=bool)
        cone_d = _shadow_cone_distance(roi, bg)
        # Judge colour on a lightly smoothed image (sensor noise would otherwise blur the shadow/part boundary).
        roi_s = np.asarray(cv2.GaussianBlur(roi, (0, 0), 1.5), dtype=np.float32)
        shadow_like = (_shadow_cone_distance(roi_s, bg) < max(SHADOW_CHROMA_TOL, noise)) & _smooth(roi, px_mm)

        # Hysteresis: Otsu can split a part into its lit faces and its shaded walls (a light part on the dark stage:
        # the walls are dimmer than the top but still brighter than the stage). Everything connected to the core that
        # differs from the stage by more than the noise floor and is not shadow-coloured belongs to the part.
        if thr > floor:
            grow = ((dist > floor) & inside & ~shadow_like).astype(np.uint8)
            if self.min_line_mm > 0:
                opened = cv2.morphologyEx(grow, cv2.MORPH_OPEN, k)
                grow = ((grow > 0) & (cv2.dilate(opened, k) > 0)).astype(np.uint8)
            grow |= core.astype(np.uint8)
            largest_fraction = _largest_fraction(grow > 0, px_mm**2)  # pieces after joining walls to faces
            _, lab_g = cv2.connectedComponents(grow, connectivity=8)
            ids = np.unique(lab_g[core])
            grown = np.isin(lab_g, ids[ids > 0])
            if grown.sum() > 1.02 * core.sum():
                notes.append(f"mask grown from the brightest faces to {grown.sum() / px_mm**2:.0f} mm² (shaded walls)")
            core = grown
        part_like_shadow = False
        if self.suppress_shadows:
            er = cv2.erode(core.astype(np.uint8), _disk(3)) > 0
            core_sel = er if er.any() else core.astype(bool)
            P = np.median(roi[core_sel], axis=0)[None, None, :].astype(np.float32)
            Bm = np.median(bg[core_sel], axis=0)[None, None, :].astype(np.float32)
            cone_part = _shadow_cone_distance(P, Bm, PART_SHADOW_MIN_RATIO, 1.05)
            part_like_shadow = float(cone_part[0, 0]) < max(PART_SHADOW_CHROMA_TOL, noise)
            if part_like_shadow:
                notes.append("the part's colour looks like a shadow on this stage; shadows were not removed")
        if self.suppress_shadows and not part_like_shadow:
            kept = core & ~shadow_like
            if self.min_line_mm > 0:
                kept_u8 = kept.astype(np.uint8)
                opened = cv2.morphologyEx(kept_u8, cv2.MORPH_OPEN, k)
                kept = (kept_u8 > 0) & (cv2.dilate(opened, k) > 0)
            kept = largest_component(kept)
            removed = int(np.count_nonzero(core)) - int(np.count_nonzero(kept))
            cut_ok = removed <= 0.02 * np.count_nonzero(core) or _cut_follows_edge(roi, core, kept)
            if not cut_ok:
                notes.append("shadow-coloured areas inside the part were kept (no edge separates them from the part)")
            elif np.count_nonzero(kept) >= SHADOW_KEEP_FRACTION * np.count_nonzero(core):
                if removed > 0.02 * np.count_nonzero(core):
                    notes.append(f"cast shadow removed ({removed / px_mm**2:.0f} mm²)")
                    shadow_zone = cv2.dilate((core & ~kept).astype(np.uint8), _disk(5)) > 0
                core = kept
            elif removed > 0.02 * np.count_nonzero(core):
                notes.append("the part's colour looks like a shadow on this stage; shadows were not removed")
            # Shadow touching the part's edge (whether or not it crossed the threshold): score that edge against
            # the shadow, not the bare stage.
            near = cv2.dilate(core.astype(np.uint8), _disk(max(3.0, 1.0 * px_mm))) > 0
            touching = near & ~core & shadow_like & (dist > max(SHADOW_CHROMA_TOL, 2.0 * noise))
            if np.count_nonzero(touching) > 0.01 * np.count_nonzero(core):
                shadow_zone |= cv2.dilate(touching.astype(np.uint8), _disk(5)) > 0

        eroded = cv2.erode(core.astype(np.uint8), _disk(3)) > 0
        d_part = float(np.median(dist[eroded])) if eroded.any() else float(np.median(dist[core]))
        d_part = max(d_part, thr * 1.05)
        prob = np.clip(dist / d_part, 0.0, 1.0).astype(np.float32)
        # Edge level from the nearby inside, not the part's median: a dim wall next to a bright top still has its
        # 50 % crossing where it meets the stage.
        d_s = np.asarray(cv2.GaussianBlur(dist, (0, 0), 1.0), dtype=np.float32)
        level = np.asarray(cv2.dilate(np.where(core, d_s, 0.0).astype(np.float32), _disk(5)), dtype=np.float32)
        near_edge = (level > 0) & ~eroded
        prob = np.where(near_edge, np.clip(dist / np.maximum(level, floor), 0.0, 1.0), prob).astype(np.float32)
        if shadow_zone.any():
            # Next to a removed shadow the local background is the shadow, so score by distance to the shadow cone.
            dc = float(np.median(cone_d[eroded])) if eroded.any() else d_part
            prob_c = np.clip(cone_d / max(dc, 1e-3), 0.0, 1.0).astype(np.float32)
            prob = np.where(shadow_zone & ~eroded, prob_c, prob).astype(np.float32)
        prob[~inside] = 0.0

        full_mask = empty.copy()
        full_mask[y0:y1, x0:x1] = core
        full_prob = np.zeros((h_img, w_img), np.float32)
        full_prob[y0:y1, x0:x1] = prob
        score = float(np.clip(eta, 0.0, 1.0))
        return SegResult(
            full_mask,
            score,
            self.source,
            prob=full_prob,
            prompt=prompt,
            notes=[
                f"threshold segmentation: background model from the stage border, contrast {d_part:.0f}/255",
                *notes,
            ],
            largest_fraction=largest_fraction,
            background=_bg_model(coef, x0, y0, sx, sy),
        )


# ---------------------------------------------------------------- provider segmenter (SAM 3.1 via providers)

SegCall = Callable[[bytes, str], list[tuple[NDArray[np.bool_], float]]]


def _png(img: U8) -> bytes:
    ok, buf = cv2.imencode(".png", img)
    if not ok:
        raise RuntimeError("PNG encode failed")
    return bytes(io.BytesIO(buf.tobytes()).getvalue())


def _bbox(mask: BoolMask) -> tuple[int, int, int, int] | None:
    ys, xs = np.nonzero(mask)
    if len(xs) == 0:
        return None
    return int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1


def merge_duplicates(
    cands: Sequence[tuple[BoolMask, float]], iou_thr: float = DUPLICATE_IOU
) -> list[tuple[BoolMask, float]]:
    """OR-merge masks that overlap with IoU ≥ `iou_thr` (the merged score is the max)."""
    out: list[tuple[BoolMask, float]] = []
    for m, s in sorted(cands, key=lambda c: -c[1]):
        for i, (om, os_) in enumerate(out):
            if mask_iou(m, om) >= iou_thr:
                out[i] = (om | m, max(os_, s))
                break
        else:
            out.append((m.copy(), s))
    return out


@dataclass
class ProviderSegmenter:
    """Text-prompted segmentation through a provider call (SAM 3.1 via `services/agent/providers`).

    `call(image_png, prompt)` returns `[(mask, score)]` with masks full-frame for the image it was given. The ladder
    tries `prompt`, "broken plastic piece", then `family_word`; it stops at the first mask scoring ≥ 0.85 and ignores
    masks below 0.4. Duplicate masks (IoU ≥ 0.72) are OR-merged. The chosen mask is then re-segmented on a crop
    (+15 % margin) at full resolution for sharper edges. If nothing clears the floor, `fallback` (threshold) is used.
    """

    call: SegCall
    family_word: str | None = None
    fallback: Segmenter | None = field(default_factory=ThresholdSegmenter)
    source: str = "sam-3.1"
    max_side_px: int = PROVIDER_MAX_SIDE_PX
    crop_refine: bool = True

    def _run(self, img: U8, prompt: str) -> list[tuple[BoolMask, float]]:
        h, w = img.shape[:2]
        scale = min(1.0, self.max_side_px / max(h, w))
        send = (
            img if scale >= 1.0 else cv2.resize(img, (round(w * scale), round(h * scale)), interpolation=cv2.INTER_AREA)
        )
        out = []
        for m, s in self.call(_png(np.asarray(send, dtype=np.uint8)), prompt):
            m = np.asarray(m, dtype=bool)
            if m.shape != (h, w):
                m = cv2.resize(m.astype(np.float32), (w, h), interpolation=cv2.INTER_LINEAR) >= 0.5
            out.append((m, float(s)))
        return out

    def _plausible(self, m: BoolMask, context: SegContext | None) -> bool:
        if not m.any():
            return False
        if context is None:
            return True
        st = context.det.mat.stage
        poly = context.det.to_px(st.corners())
        stage_m = np.zeros(m.shape, np.uint8)
        cv2.fillPoly(stage_m, [np.round(poly).astype(np.int32)], 1)
        area = int(np.count_nonzero(m))
        inside = int(np.count_nonzero(m & (stage_m > 0)))
        return inside >= 0.8 * area and area <= 0.85 * int(np.count_nonzero(stage_m))

    def segment(self, img: U8, prompt: str = "plastic part", *, context: SegContext | None = None) -> SegResult:
        ladder: list[str] = []
        for p in (prompt, *DEFAULT_LADDER, self.family_word):
            if p and p not in ladder:
                ladder.append(p)
        attempts: list[dict[str, Any]] = []
        best: tuple[BoolMask, float, str] | None = None
        for p in ladder:
            try:
                cands = self._run(img, p)
            except Exception as e:  # provider failures fall through the ladder
                attempts.append({"prompt": p, "error": f"{type(e).__name__}: {e}"})
                continue
            good = [
                (m, s)
                for m, s in merge_duplicates([c for c in cands if c[1] >= SCORE_FLOOR])
                if self._plausible(m, context)
            ]
            top = max(good, key=lambda c: c[1]) if good else None
            attempts.append(
                {"prompt": p, "n_masks": len(cands), "best_score": None if top is None else round(top[1], 4)}
            )
            if top is not None and (best is None or top[1] > best[1]):
                best = (top[0], top[1], p)
            if best is not None and best[1] >= EARLY_EXIT_SCORE:
                break
        if best is None:
            if self.fallback is None:
                return SegResult(
                    np.zeros(img.shape[:2], bool),
                    0.0,
                    self.source,
                    attempts=attempts,
                    notes=["The segmenter found no part above the confidence floor."],
                )
            res = self.fallback.segment(img, prompt, context=context)
            res.attempts = attempts + res.attempts
            res.notes.insert(0, f"{self.source} found no part with score ≥ {SCORE_FLOOR}; deterministic fallback used.")
            return res
        mask, score, used = best
        notes: list[str] = []
        if self.crop_refine:
            refined = self._crop_refine(img, mask, used)
            if refined is not None:
                mask, crop_score = refined
                score = max(score, crop_score)
                notes.append("mask re-segmented on a full-resolution crop")
        return SegResult(mask, score, self.source, prompt=used, attempts=attempts, notes=notes)

    def _crop_refine(self, img: U8, mask: BoolMask, prompt: str) -> tuple[BoolMask, float] | None:
        bb = _bbox(mask)
        if bb is None:
            return None
        h, w = img.shape[:2]
        x0, y0, x1, y1 = bb
        mx, my = CROP_MARGIN * (x1 - x0), CROP_MARGIN * (y1 - y0)
        cx0, cy0 = max(int(x0 - mx), 0), max(int(y0 - my), 0)
        cx1, cy1 = min(math.ceil(x1 + mx), w), min(math.ceil(y1 + my), h)
        if (cx1 - cx0) * (cy1 - cy0) >= 0.8 * w * h:
            return None  # the crop would not add resolution
        crop = np.ascontiguousarray(img[cy0:cy1, cx0:cx1])
        try:
            cands = self._run(crop, prompt)
        except Exception:
            return None
        ref = mask[cy0:cy1, cx0:cx1]
        scored = [(m, s, mask_iou(m, ref)) for m, s in cands if s >= SCORE_FLOOR]
        if not scored:
            return None
        m, s, iou = max(scored, key=lambda c: c[2])
        if iou < CROP_ACCEPT_IOU:
            return None
        full = np.zeros_like(mask)
        full[cy0:cy1, cx0:cx1] = m
        return full, s
