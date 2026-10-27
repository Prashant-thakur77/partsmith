"""Measure the model itself: holes (cylindrical faces with axis parallel to Z), bbox, plate thickness, minimum wall.

`measure_solid` runs inside the sandbox child (OCCT objects never leave it) and returns plain JSON-able data;
`SolidFeatures.from_dict` turns that into typed objects on the parent side.

Definitions (mm, CAD frame, Z up):
- hole: concave cylindrical face(s) sharing one axis parallel to Z and one radius, covering >= 180 deg of the circle
  (so a D-shaft bore counts; a concave corner fillet, 90 deg, does not). ``through`` when both ends open to air.
- plate thickness: the most common amount of material met by vertical rays over the part's footprint.
- min wall: inward ray casts from surface samples; reported as the 2nd percentile (robust to corner artefacts),
  with the raw minimum kept alongside.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, cast

import numpy as np

if TYPE_CHECKING:
    import cadquery as cq

AXIS_PARALLEL_COS = math.cos(math.radians(1.0))
HOLE_MIN_COVERAGE_DEG = 180.0
MERGE_TOL_MM = 1e-3
WALL_SAMPLES = 1500
WALL_PERCENTILE = 2.0
THICKNESS_GRID = 40
THICKNESS_BIN_MM = 0.02
NEAR_HIT_MM = 0.12
FEATURE_TOL_MM = 0.05


@dataclass(frozen=True)
class ModelHole:
    diameter_mm: float
    center_mm: tuple[float, float]
    z_min_mm: float
    z_max_mm: float
    through: bool
    coverage_deg: float

    @property
    def depth_mm(self) -> float:
        return self.z_max_mm - self.z_min_mm


@dataclass(frozen=True)
class SolidFeatures:
    bbox_mm: tuple[float, float, float, float, float, float]
    holes: list[ModelHole] = field(default_factory=list)
    plate_thickness_mm: float | None = None
    min_wall_mm: float | None = None
    min_wall_raw_mm: float | None = None
    n_faces: int = 0

    @property
    def size_mm(self) -> tuple[float, float, float]:
        b = self.bbox_mm
        return (b[3] - b[0], b[4] - b[1], b[5] - b[2])

    @property
    def height_mm(self) -> float:
        return self.size_mm[2]

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> SolidFeatures:
        holes = [
            ModelHole(
                diameter_mm=float(h["diameter_mm"]),
                center_mm=(float(h["center_mm"][0]), float(h["center_mm"][1])),
                z_min_mm=float(h["z_min_mm"]),
                z_max_mm=float(h["z_max_mm"]),
                through=bool(h["through"]),
                coverage_deg=float(h["coverage_deg"]),
            )
            for h in d.get("holes", [])
        ]
        b = d["bbox_mm"]
        return cls(
            bbox_mm=(float(b[0]), float(b[1]), float(b[2]), float(b[3]), float(b[4]), float(b[5])),
            holes=holes,
            plate_thickness_mm=d.get("plate_thickness_mm"),
            min_wall_mm=d.get("min_wall_mm"),
            min_wall_raw_mm=d.get("min_wall_raw_mm"),
            n_faces=int(d.get("n_faces", 0)),
        )


# ------------------------------------------------------------------ child side (OCCT)


def _z_holes(shape: cq.Shape) -> list[dict[str, Any]]:
    import cadquery as cq
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.BRepTools import BRepTools

    groups: list[dict[str, Any]] = []
    for f in shape.Faces():
        if f.geomType() != "CYLINDER":
            continue
        surf = BRepAdaptor_Surface(f.wrapped)
        cyl = surf.Cylinder()
        ax = cyl.Axis()
        d = ax.Direction()
        if abs(d.Z()) < AXIS_PARALLEL_COS:
            continue
        r = cyl.Radius()
        loc = ax.Location()
        # Axis point at z = 0 (axis is parallel to Z, so x, y are the centre).
        cx, cy = loc.X(), loc.Y()
        umin, umax, vmin, vmax = BRepTools.UVBounds_s(f.wrapped)
        p = surf.Value((umin + umax) / 2, (vmin + vmax) / 2)
        normal = f.normalAt(cq.Vector(p.X(), p.Y(), p.Z()))
        radial = (p.X() - cx, p.Y() - cy)
        if normal.x * radial[0] + normal.y * radial[1] >= 0:
            continue  # convex: a boss or an outer fillet, not a hole
        bb = f.BoundingBox()
        span = math.degrees(abs(umax - umin))
        for g in groups:
            if abs(g["cx"] - cx) < MERGE_TOL_MM and abs(g["cy"] - cy) < MERGE_TOL_MM and abs(g["r"] - r) < MERGE_TOL_MM:
                g["span"] += span
                g["zmin"] = min(g["zmin"], bb.zmin)
                g["zmax"] = max(g["zmax"], bb.zmax)
                break
        else:
            groups.append({"cx": cx, "cy": cy, "r": r, "span": span, "zmin": bb.zmin, "zmax": bb.zmax})

    def open_end(g: dict[str, Any], z: float) -> bool:
        probes = [(g["cx"], g["cy"])] + [
            (g["cx"] + 0.7 * g["r"] * math.cos(a), g["cy"] + 0.7 * g["r"] * math.sin(a))
            for a in (0.3, 0.3 + math.pi / 2, 0.3 + math.pi, 0.3 + 1.5 * math.pi)
        ]
        solid = cast(Any, shape)  # isInside lives on Solid/Compound
        outside = sum(not solid.isInside(cq.Vector(x, y, z), 1e-4) for x, y in probes)
        return outside >= 3

    out = []
    for g in groups:
        coverage = min(g["span"], 360.0)
        if coverage < HOLE_MIN_COVERAGE_DEG:
            continue
        through = open_end(g, g["zmax"] + 0.05) and open_end(g, g["zmin"] - 0.05)
        out.append(
            {
                "diameter_mm": 2 * g["r"],
                "center_mm": [g["cx"], g["cy"]],
                "z_min_mm": g["zmin"],
                "z_max_mm": g["zmax"],
                "depth_mm": g["zmax"] - g["zmin"],
                "through": through,
                "coverage_deg": coverage,
            }
        )
    out.sort(key=lambda h: (round(h["center_mm"][0], 3), round(h["center_mm"][1], 3), -h["diameter_mm"]))
    return out


def _intersector(shape: cq.Shape) -> Any:
    from OCP.IntCurvesFace import IntCurvesFace_ShapeIntersector

    inter = IntCurvesFace_ShapeIntersector()
    inter.Load(shape.wrapped, 1e-6)
    return inter


def _hits(inter: Any, origin: Any, direction: Any) -> list[float]:
    """Sorted ray parameters (mm along the unit direction) of every intersection with the B-rep."""
    from OCP.gp import gp_Dir, gp_Lin, gp_Pnt

    o = [float(x) for x in origin]
    d = [float(x) for x in direction]
    inter.Perform(gp_Lin(gp_Pnt(o[0], o[1], o[2]), gp_Dir(d[0], d[1], d[2])), -1e-9, 1e9)
    if not inter.IsDone():
        return []
    return sorted(inter.WParameter(i) for i in range(1, inter.NbPnt() + 1))


def plate_thickness(shape: cq.Shape, grid: int = THICKNESS_GRID) -> float | None:
    """Most common vertical material thickness over the footprint (exact B-rep ray casts)."""
    bb = shape.BoundingBox()
    inter = _intersector(shape)
    totals = []
    for x in np.linspace(bb.xmin, bb.xmax, grid + 2)[1:-1]:
        for y in np.linspace(bb.ymin, bb.ymax, grid + 2)[1:-1]:
            w = _hits(inter, (x, y, bb.zmax + 1.0), (0.0, 0.0, -1.0))
            w = [v for i, v in enumerate(w) if i == 0 or v - w[i - 1] > 1e-6]  # drop duplicates on shared edges
            if len(w) < 2 or len(w) % 2:
                continue
            totals.append(float(sum(w[i + 1] - w[i] for i in range(0, len(w), 2))))
    if not totals:
        return None
    t = np.array(totals)
    bins = np.round(t / THICKNESS_BIN_MM).astype(int)
    vals, counts = np.unique(bins, return_counts=True)
    mode_bin = vals[np.argmax(counts)]
    return float(np.median(t[bins == mode_bin]))


def wall_thickness(
    shape: cq.Shape, mesh: Any, n: int = WALL_SAMPLES, seed: int = 7
) -> tuple[float | None, float | None]:
    """(robust min wall, raw min wall): material length along the inward normal at surface samples.

    Samples come from the tessellation, which sits up to one chord tolerance off the true surface; a hit closer
    than NEAR_HIT_MM is the sample's own surface, so the wall is measured from that hit to the next one.
    """
    import trimesh

    pts, face_idx = trimesh.sample.sample_surface(mesh, n, seed=seed)
    normals = mesh.face_normals[face_idx]
    inter = _intersector(shape)
    walls = []
    for p, nn in zip(pts, normals, strict=True):
        w = [v for v in _hits(inter, p, -nn) if v > 1e-6]
        if not w:
            continue
        if w[0] < NEAR_HIT_MM:
            if len(w) < 2:
                continue
            walls.append(w[1] - w[0])
        else:
            walls.append(w[0])
    if not walls:
        return None, None
    d = np.array(walls)
    return float(np.percentile(d, WALL_PERCENTILE)), float(d.min())


def measure_solid(shape: cq.Shape) -> dict[str, Any]:
    """All model features as plain data (runs in the sandbox child)."""
    import trimesh

    from services.geom_worker.export import tessellate, tight_bbox

    bb = tight_bbox(shape)
    v, t = tessellate(shape, FEATURE_TOL_MM, 0.3)  # only used to place wall samples; reuses a finer mesh if present
    mesh = trimesh.Trimesh(vertices=v, faces=t, process=True)
    plate = plate_thickness(shape)
    wall, wall_raw = wall_thickness(shape, mesh)
    return {
        "bbox_mm": list(bb),
        "size_mm": [bb[3] - bb[0], bb[4] - bb[1], bb[5] - bb[2]],
        "height_mm": bb[5] - bb[2],
        "holes": _z_holes(shape),
        "plate_thickness_mm": plate,
        "min_wall_mm": wall,
        "min_wall_raw_mm": wall_raw,
        "n_faces": len(shape.Faces()),
    }


def measure_interfaces(shape: cq.Shape, probes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Measure each declared interface gap on the solid: from the probe point (which must be in air) cast a ray each
    way along the axis; the gap is the sum of the two distances to the first surface. A ray that hits nothing means the
    gap is open on that side (None)."""
    import cadquery as cq

    inter = _intersector(shape)
    solid = cast(Any, shape)
    out = []
    for pr in probes:
        at = np.asarray(pr["at"], dtype=np.float64)
        ax = np.asarray(pr["axis"], dtype=np.float64)
        n = float(np.linalg.norm(ax))
        gap: float | None = None
        note = ""
        if n == 0:
            note = "zero axis"
        elif solid.isInside(cq.Vector(*at), 1e-4):
            note = "probe point is inside the material"
        else:
            ax = ax / n
            fwd = [w for w in _hits(inter, at, ax) if w > 1e-6]
            back = [w for w in _hits(inter, at, -ax) if w > 1e-6]
            if fwd and back:
                gap = float(fwd[0] + back[0])
            else:
                note = "open on one side"
        out.append({**pr, "gap_mm": gap, "note": note})
    return out
