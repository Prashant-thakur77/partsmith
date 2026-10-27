"""Wall hook (coat / towel hook): a screw-on back plate with a J-shaped arm."""

import cadquery as cq

FAMILY = "hook"
TITLE = "Wall hook"
SUMMARY = (
    "Screw-on back plate with countersunk holes and a J-shaped arm: it leaves the wall, bends through a round "
    "and runs back up parallel to the wall, ending in a rounded tip."
)
TAGS = ["hook", "coat hook", "towel", "wall", "hanger", "screw-on"]
MEASURE_MAP = {
    "length": "length",
    "width": "width",
    "thickness": "plate_thickness",
    "hole_1.diameter": "hole_d",
}

PARAMS = {  # name: (default, min, max, step, unit, affects_fit, label)
    "length": (60.0, 36.0, 120.0, 0.1, "mm", True, "Back plate length"),
    "width": (22.0, 12.0, 50.0, 0.1, "mm", True, "Back plate width"),
    "plate_thickness": (4.0, 2.0, 8.0, 0.1, "mm", True, "Back plate thickness"),
    "hole_d": (4.0, 2.5, 6.0, 0.05, "mm", True, "Screw hole diameter"),
    "hole_count": (2, 1, 3, 1, "", False, "Screw holes"),
    "arm_width": (12.0, 6.0, 40.0, 0.1, "mm", False, "Arm width"),
    "arm_thickness": (5.0, 3.0, 10.0, 0.1, "mm", False, "Arm thickness"),
    "reach": (30.0, 14.0, 70.0, 0.1, "mm", True, "Reach from the wall"),
    "bend_radius": (8.0, 4.0, 20.0, 0.1, "mm", False, "Bend radius (arm centreline)"),
    "tip_length": (14.0, 3.0, 40.0, 0.1, "mm", False, "Tip length past the bend"),
    "corner_radius": (4.0, 0.0, 10.0, 0.1, "mm", False, "Plate corner radius"),
}


def build(p: dict[str, float]) -> cq.Workplane:
    length, width, t = p["length"], p["width"], p["plate_thickness"]
    n = int(p["hole_count"])
    hole_d = min(p["hole_d"], width / 2 - 1.0)
    a = p["arm_thickness"]
    aw = min(p["arm_width"], width)

    # Lengthwise layout: [edge | arm footprint | gap | holes zone | edge].
    holes_zone = n * max(2.5 * hole_d, 7.0)
    room = length - holes_zone - 4.0  # what the arm may occupy along X
    bend = max(min(p["bend_radius"], room - a - 1.0), a / 2 + 1.0)
    tip = max(min(p["tip_length"], room - a - bend), 0.5)
    reach = max(p["reach"], t + bend + a)
    xc = -length / 2 + 1.0 + a / 2  # arm centreline (vertical part)
    zb = reach - bend  # centreline height where the bend starts
    xe = xc + bend + tip  # tip end
    ro, ri = bend + a / 2, bend - a / 2
    s = 0.7071067811865476

    plate = cq.Workplane("XY").rect(length, width).extrude(t)
    r = min(p["corner_radius"], width / 2 - 0.5)
    if r > 0.2:
        plate = plate.edges("|Z").fillet(r)
    x_h0 = xe + a / 2 + 2.0
    step = (length / 2 - x_h0) / n
    pts = [(x_h0 + step * (i + 0.5), 0.0) for i in range(n)]
    plate = plate.faces(">Z").workplane().pushPoints(pts).cskHole(hole_d, hole_d * 2.0, 90)

    arm = (
        cq.Workplane("XZ")
        .moveTo(xc - a / 2, 0)
        .lineTo(xc - a / 2, zb)
        .threePointArc((xc + bend - ro * s, zb + ro * s), (xc + bend, zb + ro))
        .lineTo(xe, zb + ro)
        .threePointArc((xe + a / 2, zb + bend), (xe, zb + ri))
        .lineTo(xc + bend, zb + ri)
        .threePointArc((xc + bend - ri * s, zb + ri * s), (xc + a / 2, zb))
        .lineTo(xc + a / 2, 0)
        .close()
        .extrude(aw / 2, both=True)
    )
    return plate.union(arm)


result = build({k: v[0] for k, v in PARAMS.items()})
