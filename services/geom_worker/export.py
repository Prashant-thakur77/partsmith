"""Exporters: STL, STEP, 3MF, GLB and the web viewer's ``view.json``.

The STL/STEP/3MF/view writers take an OCCT-backed ``cq.Shape`` and therefore run inside the sandbox child. GLB is
written from the triangle mesh (numpy arrays) and works anywhere.

Units
-----
STL, STEP, 3MF and view.json are in millimetres, Z up (the CAD frame). GLB follows glTF 2.0: metres and +Y up, so the
mesh is rotated -90 deg about X ((x, y, z) -> (x, z, -y)) and scaled by 0.001. AR viewers then show the part at true size.

view.json (format version 1)
----------------------------
::

    {
      "version": 1,
      "units": "mm",
      "bbox": [xmin, ymin, zmin, xmax, ymax, zmax],
      "mesh": {
        "positions": [x0, y0, z0, x1, ...],      # float, 3 decimals (1 um), CAD frame, Z up
        "normals":   [nx0, ny0, nz0, ...],        # unit vertex normals, smooth within a B-rep face, sharp across faces
        "indices":   [i0, i1, i2, ...],           # triangles, counter-clockwise seen from outside
        "face_ranges": [[start, count], ...]      # per B-rep face: slice of `indices` (start and count in indices)
      },
      "edges": [[x, y, z, x, y, z, ...], ...]     # one polyline per B-rep edge, discretised from the OCCT curve
    }

Vertices are not shared between B-rep faces, which keeps creases sharp. The viewer draws ``mesh`` as a
BufferGeometry and ``edges`` as line segments (CAD-style outlines).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np
import numpy.typing as npt

if TYPE_CHECKING:
    import cadquery as cq

STL_TOL_MM = 0.01
STL_ANG_RAD = 0.1
VIEW_TOL_MM = 0.01
VIEW_ANG_RAD = 0.1
EDGE_DEFLECTION_MM = 0.02
EDGE_ANG_RAD = 0.1
VIEW_DECIMALS = 3

FloatArray = npt.NDArray[np.float64]
IntArray = npt.NDArray[np.int64]


def tight_bbox(shape: cq.Shape) -> tuple[float, float, float, float, float, float]:
    """Exact bounding box from the geometry (OCCT's default box is padded by tolerances and the mesh)."""
    from OCP.Bnd import Bnd_Box
    from OCP.BRepBndLib import BRepBndLib

    box = Bnd_Box()
    BRepBndLib.AddOptimal_s(shape.wrapped, box, False, False)
    xmin, ymin, zmin, xmax, ymax, zmax = box.Get()
    return (xmin, ymin, zmin, xmax, ymax, zmax)


def ensure_mesh(shape: cq.Shape, tol_mm: float, ang_rad: float) -> None:
    """Triangulate with an ABSOLUTE chord tolerance, single-threaded.

    (CadQuery's own ``Shape.mesh`` uses a relative tolerance; parallel meshing must not run in the warm worker because
    a forked child would inherit a thread pool without threads.) An existing finer triangulation is kept.
    """
    from OCP.BRepMesh import BRepMesh_IncrementalMesh

    BRepMesh_IncrementalMesh(shape.wrapped, tol_mm, False, ang_rad, False)


def tessellate_faces(
    shape: cq.Shape, tol_mm: float, ang_rad: float
) -> tuple[FloatArray, IntArray, list[tuple[int, int]]]:
    """Triangulate every B-rep face. Returns (vertices Nx3, triangles Mx3, per-face (first_triangle, n_triangles))."""
    from OCP.BRep import BRep_Tool
    from OCP.TopAbs import TopAbs_Orientation
    from OCP.TopLoc import TopLoc_Location

    ensure_mesh(shape, tol_mm, ang_rad)
    verts: list[FloatArray] = []
    tris: list[IntArray] = []
    groups: list[tuple[int, int]] = []
    offset = 0
    n_tris = 0
    for f in shape.Faces():
        loc = TopLoc_Location()
        poly = BRep_Tool.Triangulation_s(f.wrapped, loc)
        if poly is None:
            continue
        trsf = loc.Transformation()
        nodes = [poly.Node(i).Transformed(trsf) for i in range(1, poly.NbNodes() + 1)]
        v = np.array([[p.X(), p.Y(), p.Z()] for p in nodes], dtype=np.float64)
        t = np.array([[tr.Value(1), tr.Value(2), tr.Value(3)] for tr in poly.Triangles()], dtype=np.int64) - 1
        if f.wrapped.Orientation() == TopAbs_Orientation.TopAbs_REVERSED:
            t = t[:, [0, 2, 1]]
        verts.append(v)
        tris.append(t + offset)
        groups.append((n_tris, len(t)))
        offset += len(v)
        n_tris += len(t)
    if not verts:
        return np.zeros((0, 3)), np.zeros((0, 3), dtype=np.int64), []
    return np.concatenate(verts), np.concatenate(tris), groups


def tessellate(
    shape: cq.Shape, tol_mm: float = STL_TOL_MM, ang_rad: float = STL_ANG_RAD
) -> tuple[FloatArray, IntArray]:
    """Vertices (N x 3, mm) and triangles (M x 3). Vertices are duplicated per B-rep face; merge before topology checks."""
    v, t, _ = tessellate_faces(shape, tol_mm, ang_rad)
    return v, t


def vertex_normals(vertices: FloatArray, triangles: IntArray) -> FloatArray:
    """Area-weighted vertex normals (vertices are per face, so normals stay sharp across B-rep faces)."""
    n = np.zeros_like(vertices)
    if len(triangles) == 0:
        return n
    tri = vertices[triangles]
    fn = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])  # length = 2 * area -> area weighting
    for k in range(3):
        np.add.at(n, triangles[:, k], fn)
    length = np.linalg.norm(n, axis=1, keepdims=True)
    return np.divide(n, length, out=np.zeros_like(n), where=length > 0)


def edge_polylines(
    shape: cq.Shape, deflection_mm: float = EDGE_DEFLECTION_MM, ang_rad: float = EDGE_ANG_RAD
) -> list[FloatArray]:
    """Discretise every B-rep edge from its OCCT curve (not from the mesh)."""
    from OCP.BRep import BRep_Tool
    from OCP.BRepAdaptor import BRepAdaptor_Curve
    from OCP.GCPnts import GCPnts_TangentialDeflection

    out: list[FloatArray] = []
    for e in shape.Edges():
        if BRep_Tool.Degenerated_s(e.wrapped):
            continue
        curve = BRepAdaptor_Curve(e.wrapped)
        disc = GCPnts_TangentialDeflection(curve, ang_rad, deflection_mm)
        pts = [disc.Value(i) for i in range(1, disc.NbPoints() + 1)]
        if len(pts) >= 2:
            out.append(np.array([[p.X(), p.Y(), p.Z()] for p in pts], dtype=np.float64))
    return out


def view_json(shape: cq.Shape, *, tol_mm: float = VIEW_TOL_MM, ang_rad: float = VIEW_ANG_RAD) -> dict[str, Any]:
    """Build the view.json document (see module docstring)."""
    v, t, groups = tessellate_faces(shape, tol_mm, ang_rad)
    n = vertex_normals(v, t)
    d = VIEW_DECIMALS
    return {
        "version": 1,
        "units": "mm",
        "bbox": [round(x, d) for x in tight_bbox(shape)],
        "mesh": {
            "positions": np.round(v, d).ravel().tolist(),
            "normals": np.round(n, d).ravel().tolist(),
            "indices": t.ravel().astype(int).tolist(),
            "face_ranges": [[start * 3, count * 3] for start, count in groups],
        },
        "edges": [np.round(p, d).ravel().tolist() for p in edge_polylines(shape)],
    }


def write_view_json(shape: cq.Shape, path: Path) -> None:
    path.write_text(json.dumps(view_json(shape), separators=(",", ":")))


def export_stl(shape: cq.Shape, path: Path, tol_mm: float = STL_TOL_MM, ang_rad: float = STL_ANG_RAD) -> None:
    """Binary STL, mm, absolute chord tolerance `tol_mm` (default 0.01 mm, well below the 0.5 mm acceptance)."""
    ensure_mesh(shape, tol_mm, ang_rad)
    shape.exportStl(str(path), tol_mm, ang_rad, ascii=False, relative=False, parallel=False)


def export_step(shape: cq.Shape, path: Path) -> None:
    """STEP AP214, unit mm (exact B-rep)."""
    import cadquery as cq

    cq.exporters.export(shape, str(path), exportType="STEP")


def export_3mf(shape: cq.Shape, path: Path, tol_mm: float = STL_TOL_MM, ang_rad: float = STL_ANG_RAD) -> None:
    """3MF, unit millimetre."""
    import cadquery as cq

    ensure_mesh(shape, tol_mm, ang_rad)  # the 3MF writer reuses an existing finer triangulation
    cq.exporters.export(shape, str(path), exportType="3MF", tolerance=tol_mm, angularTolerance=ang_rad)


def glb_bytes(vertices: FloatArray, faces: IntArray) -> bytes:
    """glTF binary: metres, +Y up (rotate -90 deg about X, scale 0.001)."""
    import trimesh

    mesh = trimesh.Trimesh(vertices=np.asarray(vertices, dtype=np.float64), faces=np.asarray(faces), process=True)
    # (x, y, z) mm, Z up -> (x, z, -y) m, Y up
    to_gltf = np.array([[1, 0, 0, 0], [0, 0, 1, 0], [0, -1, 0, 0], [0, 0, 0, 1]], dtype=np.float64)
    to_gltf[:3, :3] *= 0.001
    mesh.apply_transform(to_gltf)
    data = mesh.export(file_type="glb")
    if not isinstance(data, bytes):
        raise TypeError("GLB export did not return bytes")
    return data


def export_glb(vertices: FloatArray, faces: IntArray, path: Path) -> None:
    path.write_bytes(glb_bytes(vertices, faces))
