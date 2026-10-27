"""CPU silhouettes (no OpenGL): orthographic views in millimetre frames and camera-pose views for photo overlays.

Every triangle is filled on its own with ``cv2.fillConvexPoly``. One ``fillPoly`` call over all triangles uses an
even-odd rule, so overlapping triangles cancel and the silhouette gets holes.

OpenCV fills every pixel whose centre lies within half a pixel of the polygon, which grows a shape by up to 0.5 px.
We render at ``supersample`` x resolution and area-average back down (coverage >= 50 %), which shrinks that bias to
0.5 / supersample px.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

import cv2
import numpy as np
import numpy.typing as npt

FloatArray = npt.NDArray[np.float64]
BoolMask = npt.NDArray[np.bool_]

ViewName = Literal["top", "side_xz", "side_yz"]
VIEW_AXES: dict[str, tuple[int, int]] = {"top": (0, 1), "side_xz": (0, 2), "side_yz": (1, 2)}
_SHIFT = 4  # fixed-point bits for sub-pixel vertex positions
_MAX_CANVAS_PX = 80_000_000


@dataclass(frozen=True)
class Frame:
    """A pixel grid over a 2-D plane in mm. u is right, v is UP (image rows go down).

    Pixel (col, row) covers u in [u0 + col/ppm, u0 + (col+1)/ppm] and v in [v0 - (row+1)/ppm, v0 - row/ppm];
    (u0_mm, v0_mm) is the top-left corner of the image.
    """

    px_per_mm: float
    u0_mm: float
    v0_mm: float
    width_px: int
    height_px: int

    @property
    def shape(self) -> tuple[int, int]:
        return (self.height_px, self.width_px)

    def to_px(self, uv_mm: npt.ArrayLike) -> FloatArray:
        """mm -> continuous pixel coordinates (x = col, y = row) with OpenCV's convention: integers are pixel centres."""
        uv = np.asarray(uv_mm, dtype=np.float64)
        x = (uv[..., 0] - self.u0_mm) * self.px_per_mm - 0.5
        y = (self.v0_mm - uv[..., 1]) * self.px_per_mm - 0.5
        return np.stack([x, y], axis=-1)

    def to_mm(self, xy_px: npt.ArrayLike) -> FloatArray:
        xy = np.asarray(xy_px, dtype=np.float64)
        u = self.u0_mm + (xy[..., 0] + 0.5) / self.px_per_mm
        v = self.v0_mm - (xy[..., 1] + 0.5) / self.px_per_mm
        return np.stack([u, v], axis=-1)

    @classmethod
    def around(cls, uv_mm: npt.ArrayLike, px_per_mm: float, margin_mm: float = 3.0) -> Frame:
        """Smallest frame that holds the points plus a margin."""
        pts = np.asarray(uv_mm, dtype=np.float64).reshape(-1, 2)
        lo = pts.min(axis=0) - margin_mm
        hi = pts.max(axis=0) + margin_mm
        w = int(np.ceil((hi[0] - lo[0]) * px_per_mm))
        h = int(np.ceil((hi[1] - lo[1]) * px_per_mm))
        return cls(px_per_mm=px_per_mm, u0_mm=float(lo[0]), v0_mm=float(hi[1]), width_px=max(w, 1), height_px=max(h, 1))

    def union(self, other: Frame) -> Frame:
        """Frame at this resolution covering both frames."""
        u0 = min(self.u0_mm, other.u0_mm)
        v0 = max(self.v0_mm, other.v0_mm)
        u1 = max(self.u0_mm + self.width_px / self.px_per_mm, other.u0_mm + other.width_px / other.px_per_mm)
        v1 = min(self.v0_mm - self.height_px / self.px_per_mm, other.v0_mm - other.height_px / other.px_per_mm)
        w = int(np.ceil((u1 - u0) * self.px_per_mm))
        h = int(np.ceil((v0 - v1) * self.px_per_mm))
        return Frame(self.px_per_mm, u0, v0, w, h)


def project(vertices: npt.ArrayLike, view: str) -> FloatArray:
    """Orthographic projection of CAD-frame vertices (mm) onto a view plane: top -> (x, y), side_xz -> (x, z),
    side_yz -> (y, z)."""
    a, b = VIEW_AXES[view]
    v = np.asarray(vertices, dtype=np.float64)
    return np.stack([v[:, a], v[:, b]], axis=1)


def apply_2d(T: npt.ArrayLike, uv: npt.ArrayLike) -> FloatArray:
    """Apply a 3x3 homogeneous 2-D transform to (..., 2) points."""
    M = np.asarray(T, dtype=np.float64)
    p = np.asarray(uv, dtype=np.float64)
    return p @ M[:2, :2].T + M[:2, 2]


def _supersample(frame: Frame, supersample: int) -> int:
    ss = max(1, int(supersample))
    while ss > 1 and frame.width_px * frame.height_px * ss * ss > _MAX_CANVAS_PX:
        ss -= 1
    return ss


def _downsample(canvas: npt.NDArray[np.uint8], frame: Frame, ss: int) -> BoolMask:
    if ss == 1:
        return canvas > 0
    small = cv2.resize(canvas, (frame.width_px, frame.height_px), interpolation=cv2.INTER_AREA)
    return np.asarray(small >= 128)


def rasterize_triangles(tris_px: npt.ArrayLike, height: int, width: int, supersample: int = 1) -> BoolMask:
    """Fill triangles given in continuous pixel coordinates (M x 3 x 2). Degenerate (edge-on) triangles are skipped."""
    frame = Frame(1.0, 0.0, 0.0, width, height)
    ss = _supersample(frame, supersample)
    t = np.asarray(tris_px, dtype=np.float64).reshape(-1, 3, 2)
    # Pixel-centre convention: centre of output pixel i is at i; at ss x, it is at (i + 0.5) * ss - 0.5.
    t = (t + 0.5) * ss - 0.5
    area = np.abs(
        (t[:, 1, 0] - t[:, 0, 0]) * (t[:, 2, 1] - t[:, 0, 1]) - (t[:, 2, 0] - t[:, 0, 0]) * (t[:, 1, 1] - t[:, 0, 1])
    )
    t = t[area > 1e-6]
    canvas = np.zeros((height * ss, width * ss), np.uint8)
    fixed = np.round(t * (1 << _SHIFT)).astype(np.int32)
    for tri in fixed:
        cv2.fillConvexPoly(canvas, tri, 255, cv2.LINE_8, _SHIFT)
    return _downsample(canvas, Frame(1.0, 0.0, 0.0, width, height), ss)


def silhouette(
    vertices: npt.ArrayLike,
    faces: npt.ArrayLike,
    view: str,
    frame: Frame,
    *,
    transform: npt.ArrayLike | None = None,
    supersample: int = 4,
) -> BoolMask:
    """Orthographic silhouette of a mesh in `frame`; `transform` (3x3) moves the projected points first."""
    uv = project(vertices, view)
    if transform is not None:
        uv = apply_2d(transform, uv)
    tris = frame.to_px(uv)[np.asarray(faces)]
    return rasterize_triangles(tris, frame.height_px, frame.width_px, supersample)


def rasterize_polygon(
    outline_mm: npt.ArrayLike, holes_mm: Sequence[npt.ArrayLike], frame: Frame, *, supersample: int = 4
) -> BoolMask:
    """Mask of a polygon with holes (mm). The outline is filled, then each hole is cleared, so winding never matters."""
    ss = _supersample(frame, supersample)
    canvas = np.zeros((frame.height_px * ss, frame.width_px * ss), np.uint8)

    def px(poly: npt.ArrayLike) -> npt.NDArray[np.int32]:
        p = (frame.to_px(np.asarray(poly, dtype=np.float64)) + 0.5) * ss - 0.5
        return np.round(p * (1 << _SHIFT)).astype(np.int32).reshape(-1, 1, 2)

    cv2.fillPoly(canvas, [px(outline_mm)], 255, cv2.LINE_8, _SHIFT)
    for h in holes_mm:
        cv2.fillPoly(canvas, [px(h)], 0, cv2.LINE_8, _SHIFT)
    return _downsample(canvas, frame, ss)


def circle_polygon(center_mm: tuple[float, float], diameter_mm: float, n: int = 180) -> FloatArray:
    a = np.linspace(0, 2 * np.pi, n, endpoint=False)
    r = diameter_mm / 2
    return np.column_stack([center_mm[0] + r * np.cos(a), center_mm[1] + r * np.sin(a)])


# ------------------------------------------------------------------ camera-pose silhouettes (photo-frame overlays)

_FLIP = np.diag([1.0, -1.0, -1.0, 1.0])


def placement_matrix(cx_mm: float, cy_mm: float, theta_deg: float) -> FloatArray:
    """CAD frame -> mat frame: T = translate(cx, cy) . Rz(theta) . diag(1, -1, -1) (mat y down, z into the table)."""
    th = np.radians(theta_deg)
    c, s = np.cos(th), np.sin(th)
    T = np.eye(4)
    T[:2, :2] = [[c, -s], [s, c]]
    T[0, 3], T[1, 3] = cx_mm, cy_mm
    out: FloatArray = T @ _FLIP
    return out


def silhouette_camera(
    vertices: npt.ArrayLike,
    faces: npt.ArrayLike,
    K: npt.ArrayLike,
    R: npt.ArrayLike,
    t: npt.ArrayLike,
    height: int,
    width: int,
    *,
    placement: npt.ArrayLike | None = None,
    dist: npt.ArrayLike | None = None,
    supersample: int = 1,
) -> BoolMask:
    """Silhouette as the phone camera saw it. Vertices are CAD-frame mm; `placement` (4x4) puts them on the mat;
    (K, R, t) is the camera pose from the mat markers (mat frame -> camera). Triangles behind the camera are dropped."""
    v = np.asarray(vertices, dtype=np.float64)
    if placement is not None:
        P = np.asarray(placement, dtype=np.float64)
        v = v @ P[:3, :3].T + P[:3, 3]
    Rm = np.asarray(R, dtype=np.float64)
    tv = np.asarray(t, dtype=np.float64).reshape(3)
    Km = np.asarray(K, dtype=np.float64)
    cam = v @ Rm.T + tv
    if dist is not None and np.any(np.asarray(dist)):
        rvec, _ = cv2.Rodrigues(Rm)
        uv, _ = cv2.projectPoints(v.reshape(-1, 1, 3), rvec, tv, Km, np.asarray(dist, dtype=np.float64))
        uv = uv.reshape(-1, 2)
    else:
        h = cam @ Km.T
        uv = h[:, :2] / h[:, 2:3]
    f = np.asarray(faces)
    front = np.all(cam[f][:, :, 2] > 1e-6, axis=1)
    return rasterize_triangles(uv[f[front]], height, width, supersample)
