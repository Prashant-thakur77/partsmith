import cadquery as cq
import math

FAMILY = "hook"
TITLE = "Wall hook"
SUMMARY = "Screw-on back plate with countersunk holes and a J-shaped arm"
TAGS = ["hook","coat hook","towel","wall","hanger","screw-on"]
REGIONS = {
    "hole_shift": [("holes_x", -1.0, 1.0, -1.0, 1.0, 1)],
    "hole_y": [("holes_y", -1.0, 1.0, -1.0, 1.0, 1)],
    "hole_spread": [("holes", -1.0, 1.0, -1.0, 1.0, 0)],
    "tip_length": [("holes", -1.0, 1.0, -1.0, 1.0, 0), ("xz", -0.6, 1.0, 0.0, 1.0, 1)],
    "bend_radius": [("holes", -1.0, 1.0, -1.0, 1.0, 0), ("xz", -1.0, 1.0, 0.0, 1.0, 1)],
    "arm_thickness": [("xz", -1.0, -0.6, 0.0, 1.0, 1)],
    "corner_radius": [
        ("xy", -1.0, -0.8, -1.0, -0.6, -1),
        ("xy", 0.8, 1.0, 0.6, 1.0, -1),
        ("xy", -1.0, -0.8, 0.6, 1.0, -1),
        ("xy", 0.8, 1.0, -1.0, -0.6, -1),
    ],
}
MEASURE_MAP = {
    "length": "length",
    "width": "width",
    "thickness": "plate_thickness",
    "hole_1.diameter": "hole_d",
    "side.thickness": "reach",
}

PARAMS = {
    "length": (66.35, 40.0, 120.0, 0.05, "mm", True, "Back plate length"),
    "width": (19.4, 12.0, 50.0, 0.05, "mm", True, "Back plate width"),
    "plate_thickness": (3.0, 2.0, 8.0, 0.1, "mm", True, "Back plate thickness"),
    "hole_d": (4.09, 2.5, 6.0, 0.01, "mm", True, "Screw hole diameter"),
    "hole_count": (1, 1, 3, 1, "", False, "Screw holes"),
    "arm_width": (14.0, 6.0, 40.0, 0.1, "mm", False, "Arm width (Y)"),
    "arm_thickness": (6.0, 3.0, 10.0, 0.1, "mm", False, "Arm thickness (X)"),
    "reach": (28.0, 14.0, 70.0, 0.1, "mm", True, "Reach from wall (Z)"),
    "bend_radius": (8.0, 4.0, 20.0, 0.1, "mm", False, "Bend radius (arm centreline)"),
    "tip_length": (14.0, 3.0, 40.0, 0.1, "mm", False, "Tip length past bend"),
    "corner_radius": (3.5, 0.0, 9.0, 0.1, "mm", False, "Plate corner radius"),
    "hole_shift": (1.7, -30.0, 30.0, 0.05, "mm", True, "Hole row shift along plate"),
    "hole_y": (0.0, -15.0, 15.0, 0.05, "mm", True, "Hole row offset across plate"),
    "hole_spread": (1.0, 0.3, 2.0, 0.05, "", True, "Hole spacing factor"),
}

def build(p: dict) -> cq.Workplane:
    length, width, t = p["length"], p["width"], p["plate_thickness"]
    n = int(p["hole_count"])
    hole_d = min(p["hole_d"], width/2 - 1.0)
    a = p["arm_thickness"]
    aw = min(p["arm_width"], width)
    # arm at +X end (mirrored vs original template) to match measured hole at -13.9
    holes_zone = n * max(2.5*hole_d, 7.0)
    room = length - holes_zone - 4.0
    bend = max(min(p["bend_radius"], room - a - 1.0), a/2 + 1.0)
    tip = max(min(p["tip_length"], room - a - bend), 0.5)
    reach = max(p["reach"], t + bend + a)
    xc = length/2 - 1.0 - a/2
    zb = reach - bend
    xe = xc - bend - tip
    ro, ri = bend + a/2, bend - a/2
    s = 0.7071067811865476

    plate = cq.Workplane("XY").rect(length, width).extrude(t)
    r = min(p["corner_radius"], width/2 - 0.5)
    if r > 0.2:
        plate = plate.edges("|Z").fillet(r)

    # holes zone to the left of arm
    x_h0 = xe - a/2 - 2.0
    x_min = -length/2
    span = x_h0 - x_min
    step = span / n if n else span
    xs = [x_min + step*(i+0.5) for i in range(n)]
    xm = sum(xs)/n if n else 0
    lim_x = length/2 - hole_d*1.2
    lim_y = max(width/2 - hole_d - 0.5, 0.0)
    hy = min(max(p["hole_y"], -lim_y), lim_y)
    moved = p["hole_shift"] != 0.0 or p["hole_spread"] != 1.0 or p["hole_y"] != 0.0
    pts = [] if moved else [(x, 0.0) for x in xs]
    for x in xs if moved else []:
        xh = min(max(xm + (x - xm)*p["hole_spread"] + p["hole_shift"], -lim_x), lim_x)
        if all(abs(xh - q[0]) > hole_d*2.2 for q in pts):
            pts.append((xh, hy))
    # ensure at least one point
    if not pts and n:
        pts = [(min(max(xm + p["hole_shift"], -lim_x), lim_x), hy)]
    plate = plate.faces(">Z").workplane().pushPoints(pts).cskHole(hole_d, hole_d*2.0, 82)

    # mirrored J-arm: vertical at xc, bends left (-X) and tip extends left
    arm = (
        cq.Workplane("XZ")
        .moveTo(xc + a/2, 0)
        .lineTo(xc + a/2, zb)
        .threePointArc((xc - bend + ro*s, zb + ro*s), (xc - bend, zb + ro))
        .lineTo(xe, zb + ro)
        .threePointArc((xe - a/2, zb + bend), (xe, zb + ri))
        .lineTo(xc - bend, zb + ri)
        .threePointArc((xc - bend + ri*s, zb + ri*s), (xc - a/2, zb))
        .lineTo(xc - a/2, 0)
        .close()
        .extrude(aw/2, both=True)
    )
    return plate.union(arm)

result = build({k: v[0] for k, v in PARAMS.items()})
