"""Deboss a passport id into a finished part. Trusted code: it runs INSIDE the sandbox child, after the part program
has returned its solid (`child.execute`), never as part of the program. Never import this from the API process.

Rules (mm, CAD frame, Z up, Z = 0 the mounting face):
- Debossed only (cut 0.4 mm into the face). Raised text would add 0.4 mm to the face it sits on, and the faces that are
  free are the outer ones whose position is a measured dimension.
- Only on a planar face facing +Z (up, away from the mounting face): the bottom touches what the part mounts on and the
  side walls carry the measured outline. The largest such face with room wins.
- Room = a free rectangle of at least 25 x 8 mm (more when the id is wider) inside the face, 0.5 mm clear of its
  edges and holes, 3 mm clear of every declared mating interface, with at least 0.8 mm of material left under the
  text and no material within 0.3 mm above it (where the cutter reaches). No such face → the part is left as it was
  and the report says why.
- After the cut the solid is checked again: still one valid solid, watertight mesh, bounding box, every hole (Ø,
  centre, depth), plate thickness and declared interface gaps unchanged within 0.001 mm. Any change → the mark is
  undone (the original solid is exported) and the report names the check.

Font: Bitstream Vera Sans from the reportlab package (a declared dependency, so every machine renders the same
glyphs); cap height 4 mm.
"""

from __future__ import annotations

import math
import os
from typing import Any

import cadquery as cq

STYLE = "deboss"
DEPTH_MM = 0.4
TEXT_HEIGHT_MM = 4.0  # cap height of the glyphs
FLOOR_MM = 0.8  # material that must stay under the text
TEXT_PAD_MM = 1.0  # clear border around the glyphs inside the rectangle
EDGE_CLEAR_MM = 0.5  # rectangle to face edges / holes
INTERFACE_KEEPOUT_MM = 3.0
MIN_FREE_MM = (25.0, 8.0)  # (long side, short side)
DIM_TOL_MM = 1e-3
UP_COS = math.cos(math.radians(1.0))
GRID_MM = 0.5
OVERCUT_MM = 0.2  # the cutting tool pokes this far above the face so the cut is clean
FONT_FILE = "Vera.ttf"
FONT_LABEL = "Bitstream Vera Sans (reportlab)"


def font_path() -> str | None:
    try:
        import reportlab
    except ImportError:
        return None
    p = os.path.join(os.path.dirname(reportlab.__file__), "fonts", FONT_FILE)
    return p if os.path.isfile(p) else None


def _val(wp: cq.Workplane) -> cq.Shape:
    v = wp.val()
    if not isinstance(v, cq.Shape):
        raise TypeError(f"expected a shape, got {type(v).__name__}")
    return v


def _text_solid(text: str, font: str) -> tuple[cq.Shape, float, float]:
    """The id as a solid DEPTH_MM + OVERCUT_MM tall from z = 0, its glyph box centred on the origin.
    Returns (solid, width, height) of the glyph box."""
    probe = _val(cq.Workplane("XY").text("H", 10.0, 1.0, fontPath=font, combine=False)).BoundingBox()
    size = TEXT_HEIGHT_MM * 10.0 / probe.ylen  # font size whose cap height is TEXT_HEIGHT_MM
    wp = cq.Workplane("XY").text(text, size, DEPTH_MM + OVERCUT_MM, fontPath=font, combine=False,
                                 halign="center", valign="center")  # fmt: skip
    glyphs = _val(wp).Solids()
    # One tool: glyphs that touch (kerned pairs such as "AT") would otherwise make the cut keep a glyph as its own solid.
    solid: cq.Shape = glyphs[0].fuse(*glyphs[1:]).clean() if len(glyphs) > 1 else glyphs[0]
    bb = solid.BoundingBox()
    solid = solid.translate(cq.Vector(-(bb.xmin + bb.xmax) / 2, -(bb.ymin + bb.ymax) / 2, -bb.zmin))
    return solid, bb.xlen, bb.ylen


def _face_region(face: cq.Face) -> Any:
    """The face as a shapely polygon in XY (it is horizontal), from its triangulation."""
    from OCP.BRep import BRep_Tool
    from OCP.BRepMesh import BRepMesh_IncrementalMesh
    from OCP.TopLoc import TopLoc_Location
    from shapely.geometry import Polygon
    from shapely.ops import unary_union

    BRepMesh_IncrementalMesh(face.wrapped, 0.01, False, 0.1, False)
    loc = TopLoc_Location()
    poly = BRep_Tool.Triangulation_s(face.wrapped, loc)
    if poly is None:
        return None
    trsf = loc.Transformation()
    pts = [poly.Node(i).Transformed(trsf) for i in range(1, poly.NbNodes() + 1)]
    xy = [(p.X(), p.Y()) for p in pts]
    tris = []
    for t in poly.Triangles():
        a, b, c = (xy[t.Value(k) - 1] for k in (1, 2, 3))
        tri = Polygon([a, b, c])
        if tri.area > 1e-9:
            tris.append(tri)
    if not tris:
        return None
    # A tiny buffer closes the hairline gaps between triangles before the union.
    return unary_union([t.buffer(1e-6) for t in tris]).buffer(-1e-6)


def _up_faces(shape: cq.Shape) -> list[cq.Face]:
    out = []
    for f in shape.Faces():
        if f.geomType() != "PLANE":
            continue
        n = f.normalAt()
        if n.z >= UP_COS:
            out.append(f)
    return sorted(out, key=lambda f: -f.Area())


def _place(region: Any, w: float, h: float) -> tuple[float, float, float] | None:
    """(cx, cy, angle_deg) of a w x h rectangle fully inside `region`, nearest its centre; None when it does not fit."""
    from shapely import affinity
    from shapely.geometry import box
    from shapely.prepared import prep

    if region is None or region.is_empty:
        return None
    pr = prep(region)
    c = region.representative_point()
    xmin, ymin, xmax, ymax = region.bounds
    best: tuple[float, float, float, float] | None = None
    for angle in (0.0, 90.0):
        rect = box(-w / 2, -h / 2, w / 2, h / 2)
        if angle:
            rect = affinity.rotate(rect, angle, origin=(0, 0))
        hw, hh = (w / 2, h / 2) if not angle else (h / 2, w / 2)
        nx = int((xmax - xmin - 2 * hw) / GRID_MM) + 1
        ny = int((ymax - ymin - 2 * hh) / GRID_MM) + 1
        if nx <= 0 or ny <= 0:
            continue
        cands = [(xmin + hw + i * GRID_MM, ymin + hh + j * GRID_MM) for i in range(nx) for j in range(ny)]
        cands.sort(key=lambda p: (p[0] - c.x) ** 2 + (p[1] - c.y) ** 2)
        for x, y in cands:
            d2 = (x - c.x) ** 2 + (y - c.y) ** 2
            if best is not None and d2 >= best[3]:
                break
            if pr.contains(affinity.translate(rect, x, y)):
                best = (x, y, angle, d2)
                break
    return None if best is None else (best[0], best[1], best[2])


def _prism(cx: float, cy: float, w: float, h: float, angle: float, z0: float, z1: float) -> cq.Shape:
    s = _val(cq.Workplane("XY").box(w, h, z1 - z0, centered=(True, True, False)))
    s = s.rotate(cq.Vector(0, 0, 0), cq.Vector(0, 0, 1), angle)
    return s.translate(cq.Vector(cx, cy, z0))


def _snapshot(shape: cq.Shape, probes: list[dict[str, Any]]) -> dict[str, Any]:
    """What must not change: bbox, holes, plate thickness, interface gaps."""
    from services.geom_worker.export import tight_bbox
    from services.verifier import solid_features

    snap: dict[str, Any] = {
        "bbox_mm": list(tight_bbox(shape)),
        "holes": [
            [h["diameter_mm"], *h["center_mm"], h["z_min_mm"], h["z_max_mm"]] for h in solid_features._z_holes(shape)
        ],
        "plate_thickness_mm": solid_features.plate_thickness(shape),
    }
    if probes:
        snap["interfaces"] = [i.get("gap_mm") for i in solid_features.measure_interfaces(shape, probes)]
    return snap


def _same(a: Any, b: Any) -> bool:
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(_same(x, y) for x, y in zip(a, b, strict=True))
    if a is None or b is None:
        return a is b
    return abs(float(a) - float(b)) <= DIM_TOL_MM


def _watertight(shape: cq.Shape) -> bool:
    import trimesh

    from services.geom_worker.export import tessellate

    v, t = tessellate(shape, 0.01, 0.1)
    return bool(len(t)) and bool(trimesh.Trimesh(vertices=v, faces=t, process=True).is_watertight)


def emboss(
    shape: cq.Shape, text: str, *, probes: list[dict[str, Any]] | None = None
) -> tuple[cq.Shape, dict[str, Any]]:
    """(shape to export, report). The report always says whether the mark was applied and why not."""
    probes = probes or []
    report: dict[str, Any] = {
        "text": text, "applied": False, "reason": "", "style": STYLE, "depth_mm": DEPTH_MM,
        "text_height_mm": TEXT_HEIGHT_MM, "font": FONT_LABEL, "face": None, "box_mm": None, "checks": [],
    }  # fmt: skip

    def skip(why: str) -> tuple[cq.Shape, dict[str, Any]]:
        report["reason"] = why
        return shape, report

    if not text or len(text) > 12 or not text.isalnum():
        return skip("the passport id must be 1-12 letters or digits")
    if len(shape.Solids()) != 1 or not shape.isValid():
        return skip("the mark needs one valid solid")
    font = font_path()
    if font is None:
        return skip("no font file for the mark (reportlab's Vera.ttf is missing)")
    tool, tw, th = _text_solid(text, font)
    w = max(MIN_FREE_MM[0], tw + 2 * TEXT_PAD_MM)
    h = max(MIN_FREE_MM[1], th + 2 * TEXT_PAD_MM)
    report["free_needed_mm"] = [round(w, 2), round(h, 2)]
    keepouts = [(p["at"][0], p["at"][1]) for p in probes if len(p.get("at", ())) == 3]

    from shapely.geometry import Point

    placed = None
    why = "no planar face faces up (away from the mounting face)"
    for face in _up_faces(shape):
        if face.Area() < w * h:
            why = f"no face facing up has a free {w:.0f} x {h:.0f} mm area"
            break  # sorted by area: no smaller face can hold the rectangle
        z = face.Center().z
        region = _face_region(face)
        if region is None:
            continue
        region = region.buffer(-EDGE_CLEAR_MM)
        for x, y in keepouts:
            region = region.difference(Point(x, y).buffer(INTERFACE_KEEPOUT_MM))
        spot = _place(region, w, h)
        if spot is None:
            why = f"no face facing up has a free {w:.0f} x {h:.0f} mm area away from holes, edges and mating interfaces"
            continue
        cx, cy, ang = spot
        under = _prism(cx, cy, w, h, ang, z - DEPTH_MM - FLOOR_MM, z)
        if shape.intersect(under).Volume() < under.Volume() * 0.999:
            why = f"the free area has less than {DEPTH_MM + FLOOR_MM:g} mm of material under it"
            continue  # a pocket, a thin wall, an overhang
        above = _prism(cx, cy, w, h, ang, z + 1e-4, z + OVERCUT_MM + 0.1)
        if shape.intersect(above).Volume() > 1e-6:
            why = "something overhangs the free area"
            continue
        placed = (face, z, cx, cy, ang)
        break
    if placed is None:
        return skip(f"not marked: {why}, so the part has no safe place for its passport id")
    face, z, cx, cy, ang = placed
    report["face"] = {"z_mm": round(z, 4), "area_mm2": round(face.Area(), 2), "normal": [0.0, 0.0, 1.0]}
    report["box_mm"] = {"cx": round(cx, 3), "cy": round(cy, 3), "w": round(w, 2), "h": round(h, 2), "angle_deg": ang}

    before = _snapshot(shape, probes)
    cutter = tool.rotate(cq.Vector(0, 0, 0), cq.Vector(0, 0, 1), ang).translate(cq.Vector(cx, cy, z - DEPTH_MM))
    try:
        marked = shape.cut(cutter).clean()
    except Exception as e:  # the kernel refused the cut: leave the part as it was
        return skip(f"the CAD kernel could not cut the mark ({type(e).__name__})")
    solids = marked.Solids()
    if len(solids) == 1:
        marked = solids[0]
    checks: list[dict[str, Any]] = []

    def check(name: str, ok: bool, b: Any = None, a: Any = None) -> None:
        checks.append({"name": name, "passed": bool(ok), "before": b, "after": a})

    valid = len(solids) == 1 and marked.isValid()
    check("one valid solid", valid, 1, len(solids))
    if valid:
        after = _snapshot(marked, probes)
        check("bounding box unchanged", _same(before["bbox_mm"], after["bbox_mm"]), before["bbox_mm"], after["bbox_mm"])
        check("holes unchanged", _same(before["holes"], after["holes"]), len(before["holes"]), len(after["holes"]))
        check("plate thickness unchanged", _same(before["plate_thickness_mm"], after["plate_thickness_mm"]),
              before["plate_thickness_mm"], after["plate_thickness_mm"])  # fmt: skip
        if probes:
            check("mating interfaces unchanged", _same(before["interfaces"], after["interfaces"]),
                  before["interfaces"], after["interfaces"])  # fmt: skip
        removed = shape.Volume() - marked.Volume()
        check("material removed only by the text", 0 < removed <= tool.Volume() * DEPTH_MM / (DEPTH_MM + OVERCUT_MM)
              * 1.01 + 1e-6, None, round(removed, 3))  # fmt: skip
        check("watertight mesh", _watertight(marked))
        report["removed_mm3"] = round(removed, 3)
    report["checks"] = checks
    failed = [c["name"] for c in checks if not c["passed"]]
    if failed:
        return skip("the mark was undone because a check failed: " + ", ".join(failed))
    report["applied"] = True
    report["reason"] = (
        f"debossed {DEPTH_MM:g} mm into the top face at z = {z:.2f} mm; bounding box, holes, plate thickness"
        + (" and mating interfaces" if probes else "")
        + " re-measured unchanged"
    )
    return marked, report
