"""Footprint polygon (mat mm) → measurements in the PART frame: outline, size, holes, slots, symmetry, uncertainty.

PART frame: origin at the centre of the footprint's minimum-area rectangle, long side along +X, Y up (the mat's y points
down, so the part frame flips it). `PartFrame.matrix()` is the 3×3 affine part → mat.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

import cv2
import numpy as np
from numpy.typing import NDArray
from partsmith_schemas.common import DataOrigin, Evidence, Measured, Source
from partsmith_schemas.measurement import Hole, Measurements, Slot, ViewKind
from scipy.optimize import least_squares, minimize_scalar
from shapely import affinity
from shapely.geometry import MultiPolygon, Polygon
from shapely.geometry.base import BaseGeometry
from shapely.validation import make_valid

F64 = NDArray[np.float64]

OUTLINE_SIMPLIFY_MM = 0.15
MIN_OPENING_MM2 = 0.3
HOLE_MAX_ASPECT = 1.15
HOLE_MAX_REL_RMS = 0.04
SLOT_MAX_REL_RMS = 0.06


# ---------------------------------------------------------------- frames


@dataclass(frozen=True)
class PartFrame:
    cx_mm: float
    cy_mm: float
    theta_rad: float  # direction of the part's +X axis in the mat frame
    scale: float = 1.0  # true mm per nominal mat mm (screen card / paper ruler correction)

    def to_part(self, pts_mat: F64) -> F64:
        p = np.asarray(pts_mat, dtype=np.float64).reshape(-1, 2) - [self.cx_mm, self.cy_mm]
        c, s = math.cos(self.theta_rad), math.sin(self.theta_rad)
        x = p[:, 0] * c + p[:, 1] * s
        y = -p[:, 0] * s + p[:, 1] * c
        return np.asarray(np.c_[x, -y] * self.scale, dtype=np.float64)

    def to_mat(self, pts_part: F64) -> F64:
        return np.asarray(_apply_affine(self.matrix(), pts_part), dtype=np.float64)

    def matrix(self) -> F64:
        """3×3 affine part → mat: p_mat = c + Rot(θ)·diag(1, −1)·p_part / scale."""
        c, s = math.cos(self.theta_rad), math.sin(self.theta_rad)
        k = 1.0 / self.scale
        return np.array([[c * k, s * k, self.cx_mm], [s * k, -c * k, self.cy_mm], [0.0, 0.0, 1.0]])

    def angle_to_part_deg(self, mat_angle_rad: float) -> float:
        """Direction in the mat frame → direction in the part frame (deg, folded to [0, 180))."""
        d = np.array([[math.cos(mat_angle_rad), math.sin(mat_angle_rad)]])
        c, s = math.cos(self.theta_rad), math.sin(self.theta_rad)
        x = d[0, 0] * c + d[0, 1] * s
        y = -(-d[0, 0] * s + d[0, 1] * c)
        return math.degrees(math.atan2(y, x)) % 180.0


def _apply_affine(M: F64, pts: F64) -> F64:
    p = np.asarray(pts, dtype=np.float64).reshape(-1, 2)
    return np.asarray(p @ M[:2, :2].T + M[:2, 2], dtype=np.float64)


def min_area_rect(pts: F64) -> tuple[tuple[float, float], float, float, float]:
    """(centre, long side, short side, angle of the long side in rad)."""
    (cx, cy), (rw, rh), ang = cv2.minAreaRect(np.asarray(pts, dtype=np.float32).reshape(-1, 1, 2))
    th = math.radians(ang)
    if rw < rh:
        rw, rh = rh, rw
        th += math.pi / 2
    th = (th + math.pi / 2) % math.pi - math.pi / 2  # (-90°, 90°]
    return (float(cx), float(cy)), float(rw), float(rh), th


def part_frame_from(poly_mat: Polygon, scale: float = 1.0) -> PartFrame:
    (cx, cy), _, _, th = min_area_rect(np.asarray(poly_mat.exterior.coords))
    return PartFrame(cx, cy, th, scale)


def largest_polygon(geom: BaseGeometry) -> Polygon | None:
    g = geom if geom.is_valid else make_valid(geom)
    if isinstance(g, Polygon):
        return g if not g.is_empty else None
    polys = [p for p in getattr(g, "geoms", []) if isinstance(p, Polygon)]
    polys += [q for p in getattr(g, "geoms", []) if isinstance(p, MultiPolygon) for q in p.geoms]
    return max(polys, key=lambda p: p.area) if polys else None


# ---------------------------------------------------------------- uncertainty


@dataclass(frozen=True)
class SigmaModel:
    """1σ error model (mm). Lengths get two edges; positions one edge (averaged over the feature)."""

    reproj_mm: float = 0.0  # homography RMS residual on the marker corners
    edge_mm: float = 0.05  # localisation of one mask edge
    height_rel: float = 0.0  # relative size error from the top-face height (σ_h / Zc)
    scale_rel: float = 0.0  # mat scale error (screen card match / paper print)

    def length(self, length_mm: float) -> float:
        L = abs(length_mm)
        return math.sqrt(
            2 * self.edge_mm**2 + self.reproj_mm**2 + (L * self.height_rel) ** 2 + (L * self.scale_rel) ** 2
        )

    def diameter(self, d_mm: float, n_points: int) -> float:
        # A circle fit averages the edge error over many boundary points (but not below a quarter of one edge).
        edge = self.edge_mm * max(2.0 / math.sqrt(max(n_points, 1)), 0.25) * math.sqrt(2)
        return math.sqrt(edge**2 + self.reproj_mm**2 + (d_mm * self.height_rel) ** 2 + (d_mm * self.scale_rel) ** 2)


# ---------------------------------------------------------------- fits


@dataclass(frozen=True)
class CircleFit:
    cx: float
    cy: float
    r: float
    rms: float
    roundness: float  # peak-to-valley radial deviation
    n: int


def fit_circle_algebraic(pts: F64) -> tuple[float, float, float]:
    """Kåsa least-squares circle: x² + y² + Dx + Ey + F = 0."""
    p = np.asarray(pts, dtype=np.float64)
    mu = p.mean(axis=0)
    q = p - mu
    A = np.c_[q, np.ones(len(q))]
    b = -(q**2).sum(axis=1)
    (D, E, F), *_ = np.linalg.lstsq(A, b, rcond=None)
    cx, cy = -D / 2, -E / 2
    r = math.sqrt(max(cx**2 + cy**2 - F, 0.0))
    return float(cx + mu[0]), float(cy + mu[1]), r


def fit_circle(pts: F64) -> CircleFit:
    """Algebraic start, then geometric refinement (Levenberg–Marquardt on radial residuals)."""
    p = np.asarray(pts, dtype=np.float64)
    cx, cy, r = fit_circle_algebraic(p)

    def res(v: F64) -> F64:
        return np.asarray(np.hypot(p[:, 0] - v[0], p[:, 1] - v[1]) - v[2], dtype=np.float64)

    sol = least_squares(res, np.array([cx, cy, r]), method="lm")
    cx, cy, r = (float(v) for v in sol.x)
    rr = res(sol.x)
    return CircleFit(cx, cy, abs(r), float(np.sqrt(np.mean(rr**2))), float(rr.max() - rr.min()), len(p))


@dataclass(frozen=True)
class SlotFit:
    cx: float
    cy: float
    length: float  # overall, end to end
    width: float
    angle_rad: float
    rms: float


def fit_slot(pts: F64) -> SlotFit | None:
    """Obround fit: min-area rectangle for the axis, circle fits to both end arcs for the width."""
    p = np.asarray(pts, dtype=np.float64)
    (cx, cy), L, W, th = min_area_rect(p)
    if L <= W * 1.05:
        return None
    u = np.array([math.cos(th), math.sin(th)])
    v = np.array([-u[1], u[0]])
    a = (p - [cx, cy]) @ u
    b = (p - [cx, cy]) @ v
    half = L / 2 - W / 2
    ends = []
    for sign in (1, -1):
        sel = sign * a > half - 0.05 * W
        if sel.sum() < 6:
            return None
        ends.append(fit_circle(p[sel]))
    r = (ends[0].r + ends[1].r) / 2
    c0 = np.array([ends[0].cx, ends[0].cy])
    c1 = np.array([ends[1].cx, ends[1].cy])
    length = float(np.linalg.norm(c0 - c1) + 2 * r)
    mid = np.abs(a) <= half
    side_res = np.abs(b[mid]) - r if mid.any() else np.zeros(1)
    rms = float(np.sqrt(np.mean(np.r_[side_res, ends[0].rms, ends[1].rms] ** 2)))
    centre = (c0 + c1) / 2
    return SlotFit(float(centre[0]), float(centre[1]), length, 2 * r, th, rms)


def symmetry_axis(poly: Polygon) -> tuple[float, float]:
    """Best mirror axis (angle in the polygon's frame, deg in [0, 180)) and its overlap IoU after reflection.

    Coarse sweep through the centroid, then a 1-D refinement of the angle and of the axis offset.
    """
    P = poly.simplify(0.1, preserve_topology=True)
    cx, cy = P.centroid.x, P.centroid.y
    area = P.area
    if area <= 0:
        return 0.0, 0.0

    def iou(theta: float, off: float = 0.0) -> float:
        c2, s2 = math.cos(2 * theta), math.sin(2 * theta)
        nx, ny = -math.sin(theta), math.cos(theta)
        ox, oy = cx + off * nx, cy + off * ny
        # reflection about the line through (ox, oy) with direction theta
        M = [c2, s2, s2, -c2, ox - c2 * ox - s2 * oy, oy - s2 * ox + c2 * oy]
        Q = affinity.affine_transform(P, M)
        inter = P.intersection(Q).area
        return float(inter / (2 * area - inter))

    thetas = np.radians(np.arange(0.0, 180.0, 2.0))
    scores = [iou(t) for t in thetas]
    t0 = float(thetas[int(np.argmax(scores))])
    r = minimize_scalar(
        lambda t: -iou(t),
        bounds=(t0 - math.radians(2.5), t0 + math.radians(2.5)),
        method="bounded",
        options={"xatol": 1e-4},
    )
    t_best = float(r.x)
    span = max(0.5, 0.05 * math.sqrt(area))
    r2 = minimize_scalar(lambda o: -iou(t_best, o), bounds=(-span, span), method="bounded", options={"xatol": 1e-3})
    best = max(-float(r.fun), -float(r2.fun))
    deg = math.degrees(t_best) % 180.0
    return (0.0 if deg > 179.995 else deg), best


@dataclass(frozen=True)
class SeeThroughFit:
    """A vertical through-hole of a part with thickness h, fitted to the region where the mat shows through.

    Seen from a camera, the bottom opening (z = 0) projects onto the mat plane as disc(c, r); the top opening (height h)
    projects as disc(n + (c − n)/s, r/s), with n the camera nadir and s = (Zc − h)/Zc. Only their intersection — a lens
    when the camera is off-axis — shows the mat. (c, r) are fitted to that lens's boundary in mat-plane coordinates.
    """

    cx: float  # hole axis, mat mm
    cy: float
    r: float
    rms: float
    roundness: float
    n: int
    sigma_d: float  # 1σ of the diameter (fit statistics + thickness uncertainty)
    shift_mm: float  # offset between the two projected openings
    height_mm: float


def _lens_residuals(q: F64, c: F64, r: float, nadir: F64, s: float) -> F64:
    c2 = nadir + (c - nadir) / s
    d1 = np.hypot(q[:, 0] - c[0], q[:, 1] - c[1]) - r
    d2 = np.hypot(q[:, 0] - c2[0], q[:, 1] - c2[1]) - r / s
    return np.asarray(np.maximum(d1, d2), dtype=np.float64)


def _fit_lens(q: F64, nadir: F64, s: float) -> tuple[F64, F64] | None:
    m = q.mean(axis=0)
    # lens centroid ≈ midpoint of the two projected centres → back out the axis
    c0 = nadir + 2 * (m - nadir) / (1 + 1 / s)
    shift = float(np.linalg.norm((c0 - nadir) * (1 / s - 1)))
    r0 = float(np.max(np.hypot(q[:, 0] - m[0], q[:, 1] - m[1]))) + shift / 2
    best = None
    for rs in (r0, 0.8 * r0, 1.25 * r0):

        def res(v: F64) -> F64:
            return _lens_residuals(q, v[:2], float(v[2]), nadir, s)

        sol = least_squares(res, np.array([c0[0], c0[1], rs]), method="trf", x_scale=1.0)
        if best is None or sol.cost < best.cost:
            best = sol
    if best is None or not best.success:
        return None
    return np.asarray(best.x, dtype=np.float64), np.asarray(best.jac, dtype=np.float64)


def fit_see_through_hole(
    q_ground: F64, nadir: tuple[float, float], camera_height_mm: float, height_mm: float, height_sigma_mm: float = 0.3
) -> SeeThroughFit | None:
    """Fit a vertical cylindrical hole to its see-through region's boundary (mat-plane coordinates, mm)."""
    q = np.asarray(q_ground, dtype=np.float64).reshape(-1, 2)
    if len(q) < 8 or camera_height_mm <= height_mm:
        return None
    n = np.asarray(nadir, dtype=np.float64)
    s = (camera_height_mm - height_mm) / camera_height_mm
    out = _fit_lens(q, n, s)
    if out is None:
        return None
    x, J = out
    c, r = x[:2], float(x[2])
    if r <= 0:
        return None
    res = _lens_residuals(q, c, r, n, s)
    dof = max(len(q) - 3, 1)
    s2 = float(res @ res) / dof
    try:
        cov = np.linalg.inv(J.T @ J) * s2
        sig_r = float(math.sqrt(max(cov[2, 2], 0.0)))
    except np.linalg.LinAlgError:
        sig_r = float("nan")
    # Sensitivity to the stated thickness: refit at h ± σ_h.
    dd = []
    for dh in (-height_sigma_mm, height_sigma_mm):
        hh = height_mm + dh
        if 0 < hh < camera_height_mm:
            alt = _fit_lens(q, n, (camera_height_mm - hh) / camera_height_mm)
            if alt is not None:
                dd.append(abs(2 * float(alt[0][2]) - 2 * r))
    sig_h = max(dd) if dd else 0.0
    sig_d = math.hypot(2 * sig_r if math.isfinite(sig_r) else 0.0, sig_h)
    shift = float(np.linalg.norm((c - n) * (1 / s - 1)))
    return SeeThroughFit(
        cx=float(c[0]),
        cy=float(c[1]),
        r=r,
        rms=float(np.sqrt(np.mean(res**2))),
        roundness=float(res.max() - res.min()),
        n=len(q),
        sigma_d=sig_d,
        shift_mm=shift,
        height_mm=height_mm,
    )


# ---------------------------------------------------------------- footprint → measurements


@dataclass
class FootprintFeatures:
    frame: PartFrame
    outline_part: F64
    length_mm: float
    width_mm: float
    area_mm2: float
    holes: list[tuple[CircleFit, F64]]  # fit (part frame) + ring (part frame)
    slots: list[tuple[SlotFit, F64]]
    other_openings_mm2: list[float] = field(default_factory=list)
    symmetry_deg: float | None = None
    symmetry_score: float | None = None


def analyse_footprint(poly_mat: Polygon, *, scale: float = 1.0, symmetry: bool = True) -> FootprintFeatures:
    """Geometry of a footprint polygon (mat mm, may have interior rings = through openings)."""
    frame = part_frame_from(poly_mat, scale)
    ext_part = frame.to_part(np.asarray(poly_mat.exterior.coords)[:-1])
    _, L, W, _ = min_area_rect(ext_part)
    outline = cv2.approxPolyDP(ext_part.astype(np.float32).reshape(-1, 1, 2), OUTLINE_SIMPLIFY_MM, True)
    outline_part = outline.reshape(-1, 2).astype(np.float64)
    holes: list[tuple[CircleFit, F64]] = []
    slots: list[tuple[SlotFit, F64]] = []
    other: list[float] = []
    for ring in poly_mat.interiors:
        pts = frame.to_part(np.asarray(ring.coords)[:-1])
        area = abs(Polygon(pts).area)
        if area < MIN_OPENING_MM2:
            continue
        if len(pts) < 8:
            other.append(area)
            continue
        cf = fit_circle(pts)
        _, rl, rs, _ = min_area_rect(pts)
        aspect = rl / max(rs, 1e-9)
        if aspect <= HOLE_MAX_ASPECT and cf.rms <= HOLE_MAX_REL_RMS * cf.r:
            holes.append((cf, pts))
            continue
        sf = fit_slot(pts) if aspect > HOLE_MAX_ASPECT else None
        if sf is not None and sf.rms <= SLOT_MAX_REL_RMS * sf.width:
            slots.append((sf, pts))
        else:
            other.append(area)
    holes.sort(key=lambda h: (round(h[0].cx, 1), round(h[0].cy, 1)))
    slots.sort(key=lambda s: (round(s[0].cx, 1), round(s[0].cy, 1)))
    poly_part = Polygon(ext_part, [frame.to_part(np.asarray(r.coords)[:-1]) for r in poly_mat.interiors])
    sym_deg = sym_score = None
    if symmetry:
        sym_deg, sym_score = symmetry_axis(Polygon(ext_part))
    return FootprintFeatures(
        frame=frame,
        outline_part=outline_part,
        length_mm=L,
        width_mm=W,
        area_mm2=float(abs(poly_part.area)),
        holes=holes,
        slots=slots,
        other_openings_mm2=other,
        symmetry_deg=sym_deg,
        symmetry_score=sym_score,
    )


def build_measurements(
    poly_mat: Polygon,
    *,
    view: ViewKind,
    origin: DataOrigin,
    sigma: SigmaModel,
    scale: float = 1.0,
    to_px: Callable[[F64], F64] | None = None,
    thickness: Measured | None = None,
    height_correction_scale: float = 1.0,
    mask_source: str = "threshold",
    mask_confidence: float | None = None,
    notes: list[str] | None = None,
    hole_fits: Sequence[SeeThroughFit] = (),
) -> tuple[Measurements, FootprintFeatures]:
    """`Measurements` (schema) for a footprint polygon. Every value is `source=measured` with a 1σ estimate.

    `to_px` (mat mm → image px) fills the evidence pixels so the UI can point at what was measured. `hole_fits`
    (see-through cylinder fits, mat frame) replace the plain circle fit for the holes they match.
    """
    ff = analyse_footprint(poly_mat, scale=scale)
    fr = ff.frame
    v = view.value

    def ev(pts_part: F64, note: str) -> Evidence:
        px = None
        if to_px is not None:
            px = [[round(float(a), 2), round(float(b), 2)] for a, b in to_px(fr.to_mat(pts_part))]
        return Evidence(view=v, pixels=px, note=note)

    L, W = ff.length_mm, ff.width_mm
    length = Measured(
        value=round(L, 3),
        source=Source.measured,
        sigma_mm=round(sigma.length(L), 3),
        evidence=ev(np.array([[-L / 2, 0.0], [L / 2, 0.0]]), "long side of the footprint's minimum-area rectangle"),
    )
    width = Measured(
        value=round(W, 3),
        source=Source.measured,
        sigma_mm=round(sigma.length(W), 3),
        evidence=ev(np.array([[0.0, -W / 2], [0.0, W / 2]]), "short side of the footprint's minimum-area rectangle"),
    )
    holes: list[Hole] = []
    fits_part = [(f, fr.to_part(np.array([[f.cx, f.cy]]))[0]) for f in hole_fits]
    for i, (cf, _) in enumerate(ff.holes, start=1):
        d = 2 * cf.r
        sig = sigma.diameter(d, cf.n)
        cx, cy = cf.cx, cf.cy
        roundness = cf.roundness
        note = f"circle fit, rms {cf.rms:.3f} mm over {cf.n} edge points"
        match = [(f, c) for f, c in fits_part if math.hypot(c[0] - cf.cx, c[1] - cf.cy) < max(cf.r, 0.5)]
        if match:
            f, c = match[0]
            d = 2 * f.r * scale
            cx, cy = float(c[0]), float(c[1])
            roundness = f.roundness
            sig = math.hypot(f.sigma_d * scale, sigma.diameter(d, f.n))
            note = (
                f"see-through fit, h={f.height_mm:.1f} mm: vertical cylinder whose top and bottom openings overlap by "
                f"{max(0.0, 2 * f.r - f.shift_mm):.2f} mm in the photo; rms {f.rms:.3f} mm over {f.n} edge points"
            )
        holes.append(
            Hole(
                id=f"hole_{i}",
                center_mm=(round(cx, 3), round(cy, 3)),
                diameter=Measured(
                    value=round(d, 3),
                    source=Source.measured,
                    sigma_mm=round(sig, 3),
                    evidence=ev(np.array([[cx, cy]]), note),
                ),
                roundness_mm=round(roundness, 3),
            )
        )
    slots: list[Slot] = []
    for i, (sf, _) in enumerate(ff.slots, start=1):
        slots.append(
            Slot(
                id=f"slot_{i}",
                center_mm=(round(sf.cx, 3), round(sf.cy, 3)),
                length=Measured(
                    value=round(sf.length, 3),
                    sigma_mm=round(sigma.length(sf.length), 3),
                    evidence=ev(np.array([[sf.cx, sf.cy]]), "obround fit: end-arc centres + 2r"),
                ),
                width=Measured(
                    value=round(sf.width, 3),
                    sigma_mm=round(sigma.diameter(sf.width, 20), 3),
                    evidence=ev(np.array([[sf.cx, sf.cy]]), "obround fit: mean end-arc diameter"),
                ),
                angle_deg=round(math.degrees(sf.angle_rad) % 180.0, 2),
            )
        )
    out_notes = list(notes or [])
    for a in ff.other_openings_mm2:
        out_notes.append(f"irregular through-opening of {a:.1f} mm² not classified as a hole or slot")
    source_lit = (
        mask_source
        if mask_source in ("sam-3.1", "sam3-open", "threshold", "mock-threshold", "synthetic-gt")
        else "threshold"
    )
    m = Measurements(
        view=view,
        origin=origin,
        outline_mm=[(round(float(x), 3), round(float(y), 3)) for x, y in ff.outline_part],
        holes=holes,
        slots=slots,
        length=length,
        width=width,
        thickness=thickness,
        area_mm2=round(ff.area_mm2, 2),
        symmetry_axis_deg=None if ff.symmetry_deg is None else round(ff.symmetry_deg, 2),
        symmetry_score=None if ff.symmetry_score is None else round(ff.symmetry_score, 4),
        height_correction_scale=round(height_correction_scale, 6),
        part_to_mat=fr.matrix().tolist(),
        mask_source=source_lit,
        mask_confidence=None if mask_confidence is None else round(float(mask_confidence), 4),
        notes=out_notes,
    )
    return m, ff
