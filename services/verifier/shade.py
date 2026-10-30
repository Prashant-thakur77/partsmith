"""A shaded picture of a mesh for model reviewers (the judge): orthographic, flat Lambert shading, painter's order.

A silhouette cannot tell a rolled barrel from a flat tab or a countersink from a plain hole; a shaded view can. This is
only a picture for a vision model to look at. No measurement is taken from it.
"""

from __future__ import annotations

import math

import cv2
import numpy as np
import numpy.typing as npt

FloatArray = npt.NDArray[np.float64]

BASE_BGR = np.asarray((205, 165, 120), np.float64)  # light steel blue
BG_BGR = (255, 255, 255)
LIGHT = np.asarray((-0.35, 0.45, 0.82), np.float64)  # view frame: x right, y up, z towards the viewer
AMBIENT = 0.32


def view_matrix(azimuth_deg: float, elevation_deg: float) -> FloatArray:
    """Rotation from the CAD frame (Z up) to a view frame (x right, y up, z towards the viewer)."""
    az, el = math.radians(azimuth_deg), math.radians(elevation_deg)
    rz = np.array([[math.cos(az), -math.sin(az), 0.0], [math.sin(az), math.cos(az), 0.0], [0.0, 0.0, 1.0]])
    # look from -Y towards +Y with Z up, then tilt the camera down by `el`
    to_view = np.array([[1.0, 0.0, 0.0], [0.0, 0.0, 1.0], [0.0, -1.0, 0.0]])
    rx = np.array([[1.0, 0.0, 0.0], [0.0, math.cos(el), -math.sin(el)], [0.0, math.sin(el), math.cos(el)]])
    return np.asarray(rx @ to_view @ rz, dtype=np.float64)


def shaded_png(
    vertices: FloatArray,
    faces: npt.NDArray[np.int64],
    *,
    size_px: int = 640,
    azimuth_deg: float = 35.0,
    elevation_deg: float = 35.0,
    margin: float = 0.06,
) -> bytes | None:
    """PNG of the mesh seen from (azimuth, elevation), fitted to a `size_px` square. None for an empty mesh."""
    v = np.asarray(vertices, np.float64).reshape(-1, 3)
    f = np.asarray(faces, np.int64).reshape(-1, 3)
    if not len(v) or not len(f):
        return None
    p = v @ view_matrix(azimuth_deg, elevation_deg).T
    tri = p[f]  # (n, 3, 3)
    n = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    norm = np.linalg.norm(n, axis=1)
    keep = (norm > 1e-12) & (n[:, 2] > 0)  # front faces only (CAD tessellation winds outward)
    tri, n = tri[keep], n[keep] / norm[keep, None]
    if not len(tri):
        return None
    lo, hi = p[:, :2].min(axis=0), p[:, :2].max(axis=0)
    span = float(max(hi - lo)) or 1.0
    scale = size_px * (1 - 2 * margin) / span
    off = (size_px - (hi - lo) * scale) / 2
    xy = (tri[:, :, :2] - lo) * scale + off
    xy[:, :, 1] = size_px - xy[:, :, 1]  # image y goes down
    lambert = np.clip(n @ (LIGHT / np.linalg.norm(LIGHT)), 0.0, 1.0)
    shade = AMBIENT + (1 - AMBIENT) * lambert
    colors = np.clip(BASE_BGR[None, :] * shade[:, None], 0, 255)
    img = np.full((size_px, size_px, 3), BG_BGR, np.uint8)
    pts = np.round(xy * 16).astype(np.int32)
    for i in np.argsort(tri[:, :, 2].mean(axis=1)):  # far to near
        c = colors[i]
        cv2.fillConvexPoly(img, pts[i], (int(c[0]), int(c[1]), int(c[2])), cv2.LINE_AA, shift=4)
    ok, buf = cv2.imencode(".png", img)
    return bytes(buf.tobytes()) if ok else None
