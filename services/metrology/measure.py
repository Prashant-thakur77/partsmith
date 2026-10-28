"""Photo → millimetres: detect the mat, segment the part, extract its footprint in mat mm, measure it in the part frame.

Height handling. A part of thickness h has its top edges h closer to the camera, so the mat-plane homography sees
them enlarged and pushed away from the camera's nadir. When the thickness is known and the pose is solved, every
contour is mapped twice — onto the mat plane and onto the plane at height h (exact projective model, see
`calibrate.plane_homography`) — and the footprint is the intersection of the two. For a prism with vertical walls this
recovers the true outline whether an edge seen in the photo is a top edge (far side from the nadir) or a bottom edge
(near side). Through-holes are fitted as vertical cylinders to the region where the mat shows through (see
`features.fit_see_through_hole`). Without a thickness the mat-plane footprint is reported with a note.

`measure_photo` stores nothing; the caller stores the PNG blobs and fills the `*_sha` fields.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Literal, Protocol

import cv2
import numpy as np
from numpy.typing import ArrayLike, NDArray
from partsmith_schemas.common import DataOrigin, Measured, Source
from partsmith_schemas.measurement import CaptureCheck, CaptureReport, Measurements, MeasureResult, ViewKind
from scipy.ndimage import gaussian_filter1d
from shapely.geometry import Polygon
from shapely.ops import unary_union

from services.common.images import decode_bgr

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
from .confidence import MODEL_MASK_SOURCES, RETAKE_BELOW, retake_reason, widen_measurements
from .features import (
    FootprintFeatures,
    SeeThroughFit,
    SigmaModel,
    build_measurements,
    fit_see_through_hole,
    largest_polygon,
    min_area_rect,
)
from .segment import Contour, SegContext, Segmenter, SegResult, mask_contour_subpx, refine_mask

F64 = NDArray[np.float64]
U8 = NDArray[np.uint8]
BoolMask = NDArray[np.bool_]

RECTIFIED_PX_PER_MM = 10.0
ASSUMED_UNKNOWN_HEIGHT_MM = 3.0  # σ of the unknown top-face height when no thickness is given
USER_THICKNESS_SIGMA_MM = 0.3
TALL_MARGIN_MM = 1.0  # side view taller than the stated thickness by more than this (or 15 %) is reported
TALL_MARGIN_REL = 0.15
MIN_KEEP_TOP = 0.25  # share of the mat-plane outline the height-corrected outline must keep (top views)
MIN_KEEP_SIDE = 0.05  # side views: the known height is the part's own width, so trust it much further
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
    photo_field: NDArray[np.float32] | None = None  # soft coverage the sub-pixel contours were traced on
    footprint_mat: Polygon | None = None  # footprint in mat mm (nominal mat scale)
    features: FootprintFeatures | None = None
    detection: MatDetection | None = None
    pose: PoseEstimate | None = None
    segmentation: SegResult | None = None
    notes: list[str] = field(default_factory=list)
    H_top: F64 | None = None  # image px → mat mm on the top-face plane (None without a thickness)
    hole_fits: list[SeeThroughFit] = field(default_factory=list)  # see-through cylinder fits behind `holes`
    top_px_per_mm: float | None = None  # local image px per mm at the part centre, on the plane used for measuring

    # Camera-frame comparison (verifier): the camera, the full-frame mask and the part placement.
    @property
    def K(self) -> F64 | None:
        return None if self.pose is None else self.pose.K

    @property
    def R(self) -> F64 | None:
        return None if self.pose is None else self.pose.R

    @property
    def t_mm(self) -> F64 | None:
        return None if self.pose is None else self.pose.t

    @property
    def part_to_mat(self) -> F64 | None:
        m = self.result.measurements
        return None if m is None else np.asarray(m.part_to_mat, dtype=np.float64)


def decode_image(data: bytes) -> U8:
    """Photo bytes → BGR pixels as the browser shows them (EXIF orientation applied; tap points use this frame)."""
    return decode_bgr(data)


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


class PlaneMapper(Protocol):
    """What the footprint functions need from a mat detection: the ground homography and pixel -> mm mapping.
    `MatDetection` satisfies it; the verifier passes a stand-in built from the model's camera."""

    @property
    def H(self) -> F64: ...

    def to_mm(self, pts_px: F64, H: F64 | None = None) -> F64: ...


def footprint_from_contours(contours: list[Contour], det: PlaneMapper, H: F64) -> Polygon | None:
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


SEE_THROUGH_MIN_PX = 3  # smallest see-through region kept when parallax can make the visible lens arbitrarily thin
SEE_THROUGH_MAX_RMS_REL = 0.08
SEE_THROUGH_MIN_MM2 = 0.25
SEE_THROUGH_MIN_FILL = 0.2  # area / disc on its longest side: a lens is at least this full, a crease is not
MIN_CUTOUT_MM2 = 1.0  # irregular see-through openings smaller than this are not subtracted from the outline


def expected_shift_mm(pose: PoseEstimate, height_mm: float, at_mm: tuple[float, float]) -> float:
    """How far the top opening of a through-hole at `at_mm` projects from its bottom opening (mat plane, mm)."""
    nx, ny = pose.nadir_mm
    zc = pose.camera_height_mm
    return float(math.hypot(at_mm[0] - nx, at_mm[1] - ny) * height_mm / max(zc - height_mm, 1e-6))


def _restore_see_through(
    mask: BoolMask, raw: BoolMask, det: MatDetection, pose: PoseEstimate | None, h: float, ppm: float
) -> BoolMask:
    """Re-open small see-through regions that mask clean-up filled.

    For a part of thickness h, a through-hole shows the mat only where its top and bottom openings overlap in the photo.
    When the parallax shift (h·distance-to-nadir/(Zc − h)) approaches the hole's diameter that lens becomes arbitrarily
    thin, so with a shift ≥ 0.1 mm enclosed background regions in the raw segmentation are kept as candidate openings
    (the hole fit decides what they are) when they are at least `SEE_THROUGH_MIN_MM2` (a lens narrower than ~0.5 mm
    cannot be fitted anyway) and compact like a lens, not specks along a dark crease or seam.
    """
    if pose is None:
        return mask
    ys, xs = np.nonzero(mask)
    centre = det.to_mm(np.array([[xs.mean(), ys.mean()]]))[0]
    if expected_shift_mm(pose, h, (float(centre[0]), float(centre[1]))) < 0.1:
        return mask
    inv = (~raw & mask).astype(np.uint8)  # background inside the cleaned part
    n, lab, stats, _ = cv2.connectedComponentsWithStats(inv, connectivity=4)
    out = mask.copy()
    min_px = max(SEE_THROUGH_MIN_PX, SEE_THROUGH_MIN_MM2 * ppm**2)
    for i in range(1, n):
        area = float(stats[i, cv2.CC_STAT_AREA])
        if area < min_px:
            continue
        span = float(max(stats[i, cv2.CC_STAT_WIDTH], stats[i, cv2.CC_STAT_HEIGHT]))
        if area / (math.pi * (span / 2) ** 2) < SEE_THROUGH_MIN_FILL:
            continue
        out[lab == i] = False
    return out


def thick_footprint(
    contours: list[Contour],
    det: PlaneMapper,
    pose: PoseEstimate,
    h: float,
    H_top: F64,
    notes: list[str],
    *,
    min_keep: float = MIN_KEEP_TOP,
) -> tuple[Polygon, list[SeeThroughFit]] | None:
    """Outline = mat-plane ∩ top-plane mapping of the outer contour; holes = see-through cylinder fits.

    A tall, thin object (an SD card on its edge) legitimately keeps a small share of its photo outline: its top edge
    is shifted by more than its own thickness. `min_keep` only guards against a grossly wrong stated height."""
    outers = [i for i, c in enumerate(contours) if not c.is_hole]
    if not outers:
        return None
    oi = max(outers, key=lambda i: contours[i].area_px)
    g = largest_polygon(Polygon(smooth_ring(det.to_mm(contours[oi].points_px))).buffer(0))
    t = largest_polygon(Polygon(smooth_ring(det.to_mm(contours[oi].points_px, H_top))).buffer(0))
    if g is None or t is None:
        return None
    ext = largest_polygon(g.intersection(t))
    if ext is None or ext.area < min_keep * g.area:
        notes.append(
            f"height correction skipped: the corrected outline would keep only "
            f"{0 if ext is None else 100 * ext.area / g.area:.0f} % of the photo's outline — check the stated height"
        )
        return None
    ext = Polygon(ext.exterior)
    fits: list[SeeThroughFit] = []
    cutouts: list[Polygon] = []
    nadir = pose.nadir_mm
    for c in contours:
        if not c.is_hole or c.parent != oi or len(c.points_px) < 8:
            continue
        q = smooth_ring(det.to_mm(c.points_px), 0.05)
        f = fit_see_through_hole(q, nadir, pose.camera_height_mm, h, USER_THICKNESS_SIGMA_MM)
        if f is not None and f.rms <= max(0.03, SEE_THROUGH_MAX_RMS_REL * f.r) and f.r > 0.2:
            disc = Polygon(_circle(f.cx, f.cy, f.r))
            if ext.buffer(-0.05).contains(disc.centroid) and disc.area < 0.9 * ext.area:
                fits.append(f)
                cutouts.append(disc)
                continue
        # Not a round vertical hole: subtract what is seen through, mapped on both planes.
        gq = Polygon(q).buffer(0)
        tq = Polygon(smooth_ring(det.to_mm(c.points_px, H_top), 0.05)).buffer(0)
        cut = gq.union(tq)
        if cut.area < MIN_CUTOUT_MM2 or not ext.buffer(-0.2).contains(cut):
            continue  # specks and slits along creases, or openings at the rim: not holes in the outline
        trial = ext.difference(cut)
        if trial.geom_type != "Polygon":
            continue  # would split the outline in two: a gap, not a hole
        cutouts.append(cut)
        notes.append(
            f"through-opening near mat ({cut.centroid.x:.1f}, {cut.centroid.y:.1f}) mm is not a round vertical hole; "
            "outline only"
        )
    fp = largest_polygon(ext.difference(unary_union(cutouts))) if cutouts else ext
    if fp is None:
        return None
    return fp, fits


def round_footprint(
    contours: list[Contour], det: PlaneMapper, pose: PoseEstimate, diameter: float, prism: Polygon
) -> Polygon | None:
    """Footprint of a cylinder (diameter = `diameter`) lying on the mat, from its photo silhouette.

    A silhouette ray of a cylinder is tangent to it, so it meets the mid-height plane at r/cos θ from the axis, θ being
    the ray's tilt from vertical across the axis. Curved sides are mapped onto that plane and pulled in by
    r(1/cos θ − 1). The round direction is the rectangle side whose extent is closer to the diameter (an AA cell
    across its width, a wheel on its tread along its length). The flat ends are vertical faces, so their extent comes
    from the prism outline (`prism`, mat plane ∩ top plane).
    """
    outers = [i for i, c in enumerate(contours) if not c.is_hole]
    if not outers:
        return None
    oi = max(outers, key=lambda i: contours[i].area_px)
    r = diameter / 2
    H_mid = plane_homography(pose, r, det.H)
    q = smooth_ring(det.to_mm(contours[oi].points_px, H_mid))
    (cx, cy), L, W, th = min_area_rect(q)
    u = np.array([math.cos(th), math.sin(th)])
    v = np.array([-u[1], u[0]])
    across = v if abs(W - diameter) <= abs(L - diameter) else u  # direction in which the profile is round
    along = np.array([-across[1], across[0]])
    k = 3
    tang = np.roll(q, -k, axis=0) - np.roll(q, k, axis=0)
    tang /= np.maximum(np.linalg.norm(tang, axis=1, keepdims=True), 1e-9)
    nrm = np.c_[tang[:, 1], -tang[:, 0]]
    centre = np.array([cx, cy])
    nrm[np.sum((q - centre) * nrm, axis=1) < 0] *= -1  # outwards
    side = np.abs(nrm @ across) > 0.7
    C = pose.camera_center_mm
    zc = pose.camera_height_mm
    s_n = np.sign((q - centre) @ across)[:, None] * across[None, :]  # outward across-axis direction per point
    a = np.sum((q - C[:2]) * s_n, axis=1)
    cos_t = (zc - r) / np.hypot(a, zc - r)
    pull = r * (1.0 / cos_t - 1.0)
    q2 = q.copy()
    q2[side] -= (pull[side])[:, None] * s_n[side]
    R = largest_polygon(Polygon(q2).buffer(0))
    if R is None:
        return None
    t = np.asarray(prism.exterior.coords)[:, :2] @ along
    t_lo, t_hi = float(t.min()), float(t.max())
    big = 10 * (L + W + diameter)
    slab = Polygon(
        [
            centre + along * (t_lo - centre @ along) + across * big,
            centre + along * (t_hi - centre @ along) + across * big,
            centre + along * (t_hi - centre @ along) - across * big,
            centre + along * (t_lo - centre @ along) - across * big,
        ]
    )
    return largest_polygon(R.intersection(slab))


def _circle(cx: float, cy: float, r: float, n: int = 360) -> F64:
    a = np.linspace(0, 2 * math.pi, n, endpoint=False)
    return np.asarray(np.c_[cx + r * np.cos(a), cy + r * np.sin(a)], dtype=np.float64)


HIDDEN_HOLE_MIN_MM2 = 1.0


def _hidden_holes(
    img: U8, mask: BoolMask, det: MatDetection, H_top: F64, fits: list[SeeThroughFit], contours: list[Contour]
) -> list[str]:
    """Notes for possible through-holes whose bore hides the mat completely from this angle.

    Inside the part, a hidden bore still shows as a compact patch whose colour differs from the top face (the bore
    wall). Patches that touch the part's outer edge (visible side walls) or sit around a see-through hole are ignored.
    This is a hint only: printing, labels or dirt can look the same.
    """
    if not mask.any():
        return []
    ppm = det.px_per_mm_at(tuple(det.to_mm(np.argwhere(mask)[:, ::-1].mean(axis=0, keepdims=True).astype(float))[0]))
    k = max(3, int(0.8 * ppm) | 1)
    core = cv2.erode(mask.astype(np.uint8), cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))) > 0
    if core.sum() < 50:
        return []
    lab_img = cv2.cvtColor(img, cv2.COLOR_BGR2LAB).astype(np.float32)
    ref = np.median(lab_img[core], axis=0)
    d = np.linalg.norm(lab_img - ref, axis=2)
    mad = float(np.median(d[core])) * 1.4826 + 1.0
    odd = core & (d > max(15.0, 4.0 * mad))
    # exclude the neighbourhood of see-through openings (their bore walls)
    excl = np.zeros(mask.shape, np.uint8)
    for c in contours:
        if c.is_hole:
            cv2.fillPoly(excl, [np.round(c.points_px).astype(np.int32)], 1)
    if excl.any():
        grow = max(3, int(ppm * (2.0 + max((f.shift_mm for f in fits), default=0.0))) | 1)
        excl = np.asarray(cv2.dilate(excl, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (grow, grow))), dtype=np.uint8)
    odd &= excl == 0
    n, lab, _, _ = cv2.connectedComponentsWithStats(odd.astype(np.uint8), connectivity=8)
    edge = cv2.dilate((~core).astype(np.uint8), np.ones((3, 3), np.uint8)) > 0
    out = []
    for i in range(1, n):
        comp = lab == i
        if np.any(comp & edge):
            continue
        cs, _ = cv2.findContours(comp.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
        big = max(cs, key=cv2.contourArea).reshape(-1, 2).astype(np.float64)
        if len(big) < 4:
            continue
        poly = Polygon(det.to_mm(big, H_top)).buffer(0)
        if poly.area < HIDDEN_HOLE_MIN_MM2 or poly.length <= 0:
            continue
        compact = 4 * math.pi * poly.area / poly.length**2
        if compact < 0.5:
            continue
        dia = 2 * math.sqrt(poly.area / math.pi)
        out.append(
            f"possible hidden hole near mat ({poly.centroid.x:.1f}, {poly.centroid.y:.1f}) mm, about Ø{dia:.1f} mm: "
            "the bore is not seen through from this angle — retake from straight above it or state its diameter"
        )
    return out


def _top_px_per_mm(det: MatDetection, footprint: Polygon, H: F64) -> float:
    """Image px per mm at the footprint centre on the plane of `H` (top face when height-corrected)."""
    from .calibrate import local_scale

    c = (footprint.centroid.x, footprint.centroid.y)
    return local_scale(np.linalg.inv(H), c)


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
    profile: Literal["prism", "round"] = "prism",
    stated_thickness_mm: float | None = None,
) -> MeasureOutput:
    """Measure one photo of a part on a mat.

    `profile="round"`: the object is a cylinder lying on its curved side (an AA cell, a wheel on its tread), so its
    widest silhouette is at mid-height; `thickness_mm` is then its diameter. `stated_thickness_mm` (side views): the
    plate thickness the user stated for the top view, to flag features that stand taller than it.

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
    thick = bool(
        thickness_mm is not None and thickness_mm > 0 and pose is not None and pose.camera_height_mm > thickness_mm
    )
    if thick and mask.any():
        mask = _restore_see_through(mask, seg.mask, det, pose, float(thickness_mm or 0.0), ppm_img)
    field_: BoolMask | NDArray[np.float32] = mask
    if seg.prob is not None and mask.any():
        # The soft map decides the edge across a band of ±4 px around the mask boundary (the mask itself may include
        # a pixel or two of blur halo); only deeper inside is the field forced to 1 (textured faces, bore walls).
        inner = cv2.erode(mask.astype(np.uint8), np.ones((9, 9), np.uint8)) > 0
        outer = cv2.dilate(mask.astype(np.uint8), np.ones((9, 9), np.uint8)) > 0
        field_ = np.where(inner, 1.0, np.where(outer, seg.prob, 0.0)).astype(np.float32)

    soft_field = field_.astype(np.float32) if field_.dtype == np.float32 else None
    capture = run_gate(
        img,
        det,
        mask if mask.any() else np.zeros_like(mask),
        pose=pose,
        largest_fraction=seg.largest_fraction,
        components_mm2=seg.components_mm2,
    )
    rect = rectify(img, det.H, px_per_mm, st, K=det.K, dist=det.dist)
    calib = calibration_from(det, pose, px_per_mm, scale_correction)

    contours = mask_contour_subpx(field_, min_area_px=2.0) if mask.any() else []
    ground = footprint_from_contours(contours, det, det.H) if contours else None
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
            photo_field=soft_field,
            detection=det,
            pose=pose,
            segmentation=seg,
            notes=notes,
        )

    footprint = ground
    H_display = det.H
    H_top: F64 | None = None
    hscale = 1.0
    hole_fits: list[SeeThroughFit] = []
    zc = pose.camera_height_mm if pose is not None else None
    if thick and pose is not None and zc is not None and thickness_mm is not None:
        min_keep = MIN_KEEP_SIDE if view == ViewKind.side else MIN_KEEP_TOP
        H_top = plane_homography(pose, thickness_mm, det.H)
        corrected = thick_footprint(contours, det, pose, thickness_mm, H_top, notes, min_keep=min_keep)
        if corrected is not None and profile == "round":
            rounded = round_footprint(contours, det, pose, thickness_mm, corrected[0])
            if rounded is not None:
                footprint = rounded
                H_display = plane_homography(pose, thickness_mm / 2, det.H)
                hscale = height_scale(zc, thickness_mm / 2)
                notes.append(
                    f"round profile (Ø{thickness_mm:.2f} mm cylinder lying down): curved sides from silhouette rays "
                    "tangent to the cylinder (mid-height plane, corrected for the ray angle); flat ends from the "
                    "mat-plane ∩ top-plane outline"
                )
                corrected = None
        if corrected is not None:
            footprint, hole_fits = corrected
            H_display = H_top
            hscale = height_scale(zc, thickness_mm)
            notes.append(
                f"height-corrected for a {thickness_mm:.2f} mm top face: outline mapped onto the mat plane and the "
                f"top-face plane (scale {hscale:.4f} about the camera nadir) and intersected; through-holes fitted as "
                "vertical cylinders to the region where the mat shows through"
            )
        hidden = _hidden_holes(img, mask, det, H_top, hole_fits, contours)
        notes.extend(hidden)
    elif thickness_mm is None:
        notes.append(
            "thickness unknown: footprint measured on the mat plane; top edges of a thick part read slightly large, "
            "and its through-holes read small (only the see-through part is measured) or are missed"
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
        hole_fits=hole_fits,
    )
    if view == ViewKind.side:
        sig = meas.width.sigma_mm
        if footprint is not ground:
            # The correction assumes the part stands the full stated height everywhere along this profile. A lower
            # feature on the side away from the camera is trimmed with it, so the photo only bounds the thickness:
            # between the corrected profile and the uncorrected one (which also counts the far walls' parallax).
            upper = min_area_rect(np.asarray(ground.exterior.coords))[2]
            lower = meas.width.value
            if upper - lower > 0.3:
                sig = math.hypot(sig, (upper - lower) / (2 * math.sqrt(3)))
                meas.notes.append(
                    f"side view: {lower:.2f} mm if the part is equally tall everywhere along this profile; a feature "
                    f"lower than {thickness_mm:.1f} mm on the side away from the camera reads short (the photo allows up "
                    f"to {upper:.2f} mm) — a side photo taken straight above the part narrows this"
                )
        meas.thickness = Measured(
            value=meas.width.value, source=Source.measured, sigma_mm=round(sig, 3), evidence=meas.width.evidence
        )
        meas.notes.append("side view: thickness = short side of the profile")
        if stated_thickness_mm is not None and meas.thickness.value > stated_thickness_mm + max(
            TALL_MARGIN_MM, TALL_MARGIN_REL * stated_thickness_mm
        ):
            meas.notes.append(
                f"side view: the part stands {meas.thickness.value:.1f} mm tall, clearly above the stated "
                f"{stated_thickness_mm:.1f} mm thickness — it has features taller than the plate (top-view outline "
                "measured at the stated thickness)"
            )

    if view == ViewKind.top and footprint is not ground and thickness_mm is not None:
        _height_bounds(meas, ground, thickness_mm)
    if seg.source in MODEL_MASK_SOURCES:
        meas = widen_measurements(meas, seg.score, seg.source)
        capture = with_confidence_check(capture, seg.score, f"the part's outline in the {view.value} photo")

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
        photo_field=soft_field,
        footprint_mat=footprint,
        features=ff,
        detection=det,
        pose=pose,
        segmentation=seg,
        notes=meas.notes,
        H_top=H_top,
        hole_fits=hole_fits,
        top_px_per_mm=_top_px_per_mm(det, footprint, H_display),
    )


def with_confidence_check(capture: CaptureReport, confidence: float, what: str) -> CaptureReport:
    """The capture report plus a `mask_confidence` check: a warning (not a failure) below `RETAKE_BELOW`, so the
    job asks whether to retake rather than stopping; the values are already widened for it."""
    why = retake_reason(what, confidence)
    check = CaptureCheck(
        name="mask_confidence",
        passed=True,
        severity="warn" if why else "ok",
        value=round(float(confidence), 4),
        threshold=RETAKE_BELOW,
        reason=why or f"The segmenter is {confidence:.0%} sure of {what}.",
    )
    return capture.model_copy(update={"checks": [*capture.checks, check]})


def _height_bounds(meas: Measurements, ground: Polygon, thickness_mm: float) -> None:
    """Record what a single top photo allows for a thick part's length and width (``Measured.bound_mm``).

    The height correction reads every outline edge at the stated top height. A silhouette cannot tell an end that
    stands the full height from a longer one that sits lower (a battery's terminal at mid-height, a rounded or
    chamfered end): the lower it sits, the longer the part. The photo allows anything from the corrected reading (full
    height) to the mat-plane reading (on the mat). A side photo or a walk-around shows the heights and settles it.
    """
    _, up_l, up_w, _ = min_area_rect(np.asarray(ground.exterior.coords))
    up_l, up_w = max(up_l, up_w), min(up_l, up_w)
    changed = []
    for name, up in (("length", up_l), ("width", up_w)):
        m: Measured = getattr(meas, name)
        if up > m.value + 0.01:
            setattr(meas, name, m.model_copy(update={"bound_mm": (m.value, round(float(up), 3))}))
            changed.append(f"{name} {m.value:.2f}–{up:.2f} mm")
    if changed:
        meas.notes.append(
            f"top view at {thickness_mm:.1f} mm: read with every edge at the stated height; an end or side that sits "
            f"lower reads short, so this photo alone allows {', '.join(changed)} (a side photo settles it)"
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
