"""Rigid 2-D registration of a model silhouette onto a measured silhouette: rotation, translation and mirror flips.

Never scales: a model that is 1 mm too long must show up as a 1 mm residual, not be shrunk to fit.

Method: symmetric chamfer distance between the two boundaries, read from distance transforms (bilinear), minimised
over (theta, tx, ty) with Nelder-Mead from a coarse sweep: centroids matched, 24 rotations, with and without a mirror
flip (a part lying upside down shows its mirror image from above).
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np
import numpy.typing as npt
from scipy.ndimage import map_coordinates
from scipy.optimize import minimize

from services.verifier.render import BoolMask, FloatArray, Frame

COARSE_STEP_DEG = 15.0
N_REFINE = 4
MAX_POINTS = 1500
OUTSIDE_PENALTY_MM = 10.0


@dataclass(frozen=True)
class Rigid2D:
    """p' = R(theta) . M . p + t, where M = diag(1, -1) when mirrored."""

    theta_deg: float = 0.0
    tx_mm: float = 0.0
    ty_mm: float = 0.0
    mirror: bool = False

    def matrix(self) -> FloatArray:
        th = np.radians(self.theta_deg)
        c, s = np.cos(th), np.sin(th)
        m = -1.0 if self.mirror else 1.0
        return np.array([[c, -s * m, self.tx_mm], [s, c * m, self.ty_mm], [0.0, 0.0, 1.0]])

    def apply(self, pts: npt.ArrayLike) -> FloatArray:
        M = self.matrix()
        p = np.asarray(pts, dtype=np.float64)
        out: FloatArray = p @ M[:2, :2].T + M[:2, 2]
        return out

    def inverse_apply(self, pts: npt.ArrayLike) -> FloatArray:
        M = np.linalg.inv(self.matrix())
        p = np.asarray(pts, dtype=np.float64)
        out: FloatArray = p @ M[:2, :2].T + M[:2, 2]
        return out


@dataclass(frozen=True)
class _DT:
    frame: Frame
    dist_mm: FloatArray

    def sample(self, pts_mm: FloatArray) -> FloatArray:
        px = self.frame.to_px(pts_mm)
        h, w = self.dist_mm.shape
        vals = map_coordinates(self.dist_mm, [px[:, 1], px[:, 0]], order=1, mode="nearest")
        # Points that leave the frame cost their distance outside it plus a penalty.
        ox = np.maximum(0, np.maximum(-px[:, 0], px[:, 0] - (w - 1)))
        oy = np.maximum(0, np.maximum(-px[:, 1], px[:, 1] - (h - 1)))
        outside = np.hypot(ox, oy) / self.frame.px_per_mm
        out: FloatArray = np.where(outside > 0, vals + outside + OUTSIDE_PENALTY_MM, vals)
        return out


def _boundary_dt(mask: BoolMask, frame: Frame) -> _DT:
    m = np.asarray(mask, dtype=np.uint8)
    edge = m - cv2.erode(m, np.ones((3, 3), np.uint8), borderType=cv2.BORDER_CONSTANT, borderValue=0)
    src = np.where(edge > 0, 0, 255).astype(np.uint8)
    dist = cv2.distanceTransform(src, cv2.DIST_L2, cv2.DIST_MASK_PRECISE)
    return _DT(frame, dist.astype(np.float64) / frame.px_per_mm)


def _boundary_points(mask: BoolMask, frame: Frame, max_points: int) -> FloatArray:
    m = np.ascontiguousarray(np.asarray(mask, dtype=np.uint8))
    cs, _ = cv2.findContours(m, cv2.RETR_LIST, cv2.CHAIN_APPROX_NONE)
    if not cs:
        return np.zeros((0, 2))
    pts = np.vstack([c.reshape(-1, 2) for c in cs]).astype(np.float64)
    if len(pts) > max_points:
        pts = pts[np.linspace(0, len(pts) - 1, max_points).astype(int)]
    return frame.to_mm(pts)


def _moments(mask: BoolMask, frame: Frame) -> tuple[FloatArray, float]:
    m = cv2.moments(np.asarray(mask, dtype=np.uint8), binaryImage=True)
    if m["m00"] == 0:
        return np.zeros(2), 0.0
    c_px = np.array([m["m10"] / m["m00"], m["m01"] / m["m00"]])
    c = frame.to_mm(c_px)
    # Principal axis in mm coordinates (v is up, image y is down, so flip the sign of mu11).
    ang = 0.5 * np.degrees(np.arctan2(-2 * m["mu11"], m["mu20"] - m["mu02"]))
    return c, float(ang)


@dataclass(frozen=True)
class AlignResult:
    transform: Rigid2D
    cost_mm: float  # symmetric mean boundary distance at the optimum (mm)


def align(model_mask: BoolMask, model_frame: Frame, photo_mask: BoolMask, photo_frame: Frame) -> AlignResult:
    """Find the rigid transform (model frame -> photo frame) that best overlays the model boundary on the photo's."""
    m_pts = _boundary_points(model_mask, model_frame, MAX_POINTS)
    p_pts = _boundary_points(photo_mask, photo_frame, MAX_POINTS)
    if len(m_pts) == 0 or len(p_pts) == 0:
        return AlignResult(Rigid2D(), float("inf"))
    dt_photo = _boundary_dt(photo_mask, photo_frame)
    dt_model = _boundary_dt(model_mask, model_frame)
    c_m, a_m = _moments(model_mask, model_frame)
    c_p, a_p = _moments(photo_mask, photo_frame)

    def cost(x: FloatArray, mirror: bool) -> float:
        T = Rigid2D(float(x[0]), float(x[1]), float(x[2]), mirror)
        fwd = dt_photo.sample(T.apply(m_pts)).mean()
        back = dt_model.sample(T.inverse_apply(p_pts)).mean()
        return float((fwd + back) / 2)

    def start(theta: float, mirror: bool) -> FloatArray:
        R = Rigid2D(theta, 0.0, 0.0, mirror)
        t = c_p - R.apply(c_m[None, :])[0]
        return np.array([theta, t[0], t[1]])

    candidates: list[tuple[float, FloatArray, bool]] = []
    for mirror in (False, True):
        base = a_p - (-a_m if mirror else a_m)
        for k in range(round(360 / COARSE_STEP_DEG)):
            x0 = start(base + k * COARSE_STEP_DEG, mirror)
            candidates.append((cost(x0, mirror), x0, mirror))
    candidates.sort(key=lambda c: c[0])

    best: tuple[float, FloatArray, bool] | None = None
    for _, x0, mirror in candidates[:N_REFINE]:
        simplex = np.array([x0, x0 + np.array([3.0, 0, 0]), x0 + np.array([0, 0.5, 0]), x0 + np.array([0, 0, 0.5])])
        r = minimize(
            cost, x0, args=(mirror,), method="Nelder-Mead",
            options={"initial_simplex": simplex, "xatol": 1e-3, "fatol": 1e-6, "maxiter": 600},
        )  # fmt: skip
        f = float(r.fun)
        # Prefer the un-mirrored pose when both fit equally well (symmetric parts).
        if best is None or f < best[0] - 1e-6 or (abs(f - best[0]) <= 1e-6 and best[2] and not mirror):
            best = (f, np.asarray(r.x), mirror)
    assert best is not None
    f, x, mirror = best
    theta = float((x[0] + 180.0) % 360.0 - 180.0)
    return AlignResult(Rigid2D(theta, float(x[1]), float(x[2]), mirror), f)
