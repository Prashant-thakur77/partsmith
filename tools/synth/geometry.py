"""Part meshes and their exact ground-truth dimensions.

Meshes come from the geometry sandbox (`run_program`) so a synthetic part is exactly what the CAD template builds.
CAD frame: z up, the part rests on z = 0, footprint centred on the origin. Mat frame: x right, y down, z into the
table. Ground truth is computed from the mesh/CAD features (never from a render):

- top view: `length`/`width` = sides of the minimum-area rectangle of the orthographic footprint (rotating calipers on
  the convex hull of the projected vertices — the same definition the metrology uses), `hole_k.diameter` = through
  openings that are see-through from straight above (exact cylinder diameters from the CAD features);
- side view (the part rotated 90° about its CAD x axis so its thickness faces the camera): `thickness` = short side of
  that view's footprint rectangle (the overall thickness of a part lying flat).
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

import numpy as np
from numpy.typing import NDArray
from scipy.spatial import ConvexHull

from services.metrology import testing as T

F64 = NDArray[np.float64]
I64 = NDArray[np.int64]

HOLE_VIS_PX_PER_MM = 20.0
_MESH_CACHE: dict[tuple[str, tuple[tuple[str, float], ...]], PartMesh] = {}


class BuildError(RuntimeError):
    """The CAD program did not produce a valid mesh."""


@dataclass(frozen=True)
class PartMesh:
    vertices: F64  # CAD frame, mm
    faces: I64
    features: dict[str, Any] = field(default_factory=dict)
    params: dict[str, float] = field(default_factory=dict)
    code_sha: str = ""

    @property
    def height_mm(self) -> float:
        return float(self.vertices[:, 2].max() - self.vertices[:, 2].min())


def build_mesh(code: str, params: Mapping[str, float] | None = None, *, cache_key: str | None = None) -> PartMesh:
    """Run a part program in the sandbox and return its mesh, features and the (clamped) params used."""
    from services.geom_worker.sandbox import run_program

    key = None
    if cache_key is not None:
        key = (cache_key, tuple(sorted((k, float(v)) for k, v in (params or {}).items())))
        if key in _MESH_CACHE:
            return _MESH_CACHE[key]
    with run_program(code, dict(params or {}), outputs=(), features=True, timeout_s=60.0) as res:
        if not res.ok or res.mesh is None:
            raise BuildError(res.error.short() if res.error else "no mesh")
        pm = PartMesh(
            vertices=np.asarray(res.mesh.vertices, dtype=np.float64),
            faces=np.asarray(res.mesh.faces, dtype=np.int64),
            features=dict(res.features or {}),
            params={k: float(v) for k, v in res.params_used.items()},
            code_sha=res.code_sha,
        )
    if key is not None:
        _MESH_CACHE[key] = pm
    return pm


# ---------------------------------------------------------------- poses


def rot_z(deg: float) -> F64:
    c, s = math.cos(math.radians(deg)), math.sin(math.radians(deg))
    return np.array([[c, -s, 0.0], [s, c, 0.0], [0.0, 0.0, 1.0]])


CAD_TO_MAT_FLIP = np.diag([1.0, -1.0, -1.0])  # 180° about x: CAD z up -> mat z into the table (a proper rotation)
SIDE_ROT = np.array([[1.0, 0.0, 0.0], [0.0, 0.0, -1.0], [0.0, 1.0, 0.0]])  # +90° about CAD x: (x, y, z) -> (x, -z, y)


def lay_on_side(vertices: F64) -> F64:
    """The part rotated +90° about its CAD x axis, resting on z = 0 and centred in x/y (bbox centre)."""
    v = np.asarray(vertices, dtype=np.float64) @ SIDE_ROT.T
    lo, hi = v.min(axis=0), v.max(axis=0)
    return np.asarray(v - np.array([(lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2, lo[2]]), dtype=np.float64)


@dataclass(frozen=True)
class Placement:
    """Where a CAD-frame part lies on the mat: yaw about CAD z, then the CAD origin at `center_mm` (mat frame)."""

    center_mm: tuple[float, float]
    yaw_deg: float

    def matrix(self) -> F64:
        """4×4 CAD → mat transform."""
        M = np.eye(4)
        M[:3, :3] = CAD_TO_MAT_FLIP @ rot_z(self.yaw_deg)
        M[:2, 3] = self.center_mm
        return M

    def apply(self, pts: F64) -> F64:
        p = np.asarray(pts, dtype=np.float64).reshape(-1, 3)
        M = self.matrix()
        return np.asarray(p @ M[:3, :3].T + M[:3, 3], dtype=np.float64)

    def apply_xy(self, pts_xy: F64) -> F64:
        p = np.asarray(pts_xy, dtype=np.float64).reshape(-1, 2)
        return self.apply(np.c_[p, np.zeros(len(p))])[:, :2]


# ---------------------------------------------------------------- ground truth


def min_area_rect(points_xy: F64) -> tuple[float, float, float]:
    """(length, width, angle_deg of the long side) of the minimum-area rectangle, by rotating calipers (float64)."""
    p = np.asarray(points_xy, dtype=np.float64).reshape(-1, 2)
    hull = p[ConvexHull(p).vertices]
    e = np.roll(hull, -1, axis=0) - hull
    ang = np.arctan2(e[:, 1], e[:, 0])
    best = (math.inf, 0.0, 0.0, 0.0)
    for a in ang:
        c, s = math.cos(a), math.sin(a)
        x = hull[:, 0] * c + hull[:, 1] * s
        y = -hull[:, 0] * s + hull[:, 1] * c
        ex, ey = float(x.max() - x.min()), float(y.max() - y.min())
        if ex * ey < best[0] - 1e-12:
            best = (ex * ey, ex, ey, math.degrees(a))
    _, ex, ey, a_deg = best
    if ex >= ey:
        return ex, ey, a_deg % 180.0
    return ey, ex, (a_deg + 90.0) % 180.0


def ortho_silhouette(vertices: F64, faces: I64, px_per_mm: float = HOLE_VIS_PX_PER_MM) -> tuple[NDArray[np.uint8], F64]:
    """Orthographic top-view silhouette (row i = y, column j = x, 20 px/mm) and the mm position of pixel (0, 0)."""
    xy = np.asarray(vertices, dtype=np.float64)[:, :2]
    lo = xy.min(axis=0) - 1.0
    hi = xy.max(axis=0) + 1.0
    w, h = math.ceil((hi[0] - lo[0]) * px_per_mm), math.ceil((hi[1] - lo[1]) * px_per_mm)
    px = (xy - lo) * px_per_mm - 0.5
    m = T.rasterize((h, w), [[px[f]] for f in np.asarray(faces)])
    return m, lo


@dataclass(frozen=True)
class GTHole:
    name: str
    diameter_mm: float
    center_cad_mm: tuple[float, float]
    depth_mm: float


def visible_holes(pm: PartMesh) -> list[GTHole]:
    """Through openings from the CAD features that are see-through from straight above, named hole_1.. in a stable
    order (by x, then y in the CAD frame)."""
    feats = pm.features.get("holes") or []
    m, lo = ortho_silhouette(pm.vertices, pm.faces)
    out: list[tuple[float, float, float, float]] = []
    seen: list[tuple[float, float]] = []
    for hdict in feats:
        if not hdict.get("through"):
            continue
        cx, cy = (float(c) for c in hdict["center_mm"])
        d = float(hdict["diameter_mm"])
        if any(math.hypot(cx - sx, cy - sy) < 0.25 * d for sx, sy in seen):
            continue  # the same opening reported by two cylindrical faces (e.g. counterbore)
        # see-through test: the centre and a ring at 0.6 r are empty in the orthographic silhouette
        ring = [(cx + 0.6 * d / 2 * math.cos(a), cy + 0.6 * d / 2 * math.sin(a)) for a in np.linspace(0, 2 * np.pi, 8)]
        ok = True
        for x, y in [(cx, cy), *ring]:
            j, i = int((x - lo[0]) * HOLE_VIS_PX_PER_MM), int((y - lo[1]) * HOLE_VIS_PX_PER_MM)
            if not (0 <= i < m.shape[0] and 0 <= j < m.shape[1]) or m[i, j]:
                ok = False
                break
        if ok:
            # the smallest coaxial cylinder is the see-through opening (countersinks/counterbores are wider)
            dmin = min(
                float(o["diameter_mm"])
                for o in feats
                if o.get("through") and math.hypot(float(o["center_mm"][0]) - cx, float(o["center_mm"][1]) - cy) < 0.05
            )
            out.append((cx, cy, dmin, float(hdict.get("depth_mm", 0.0))))
            seen.append((cx, cy))
    out.sort(key=lambda t: (round(t[0], 2), round(t[1], 2)))
    return [GTHole(f"hole_{i + 1}", d, (x, y), dep) for i, (x, y, d, dep) in enumerate(out)]


def top_dims(pm: PartMesh) -> dict[str, float]:
    L, W, _ = min_area_rect(pm.vertices[:, :2])
    return {"length": L, "width": W}


def side_dims(pm: PartMesh) -> dict[str, float]:
    v = lay_on_side(pm.vertices)
    L, W, _ = min_area_rect(v[:, :2])
    return {"side_length": L, "thickness": W, "side_height": float(v[:, 2].max())}
