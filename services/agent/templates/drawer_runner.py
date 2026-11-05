"""Drawer runner (wardrobe, desk, kitchen drawer): a screw-down strip with a raised rail the drawer slides on."""

import cadquery as cq

FAMILY = "bracket"
TITLE = "Drawer runner"
SUMMARY = (
    "Long flat strip that screws to the cabinet wall, with a raised rail along one edge for the drawer to ride on. "
    "The rail tapers at the front so the drawer finds it, and the screw holes are counterbored."
)
TAGS = ["drawer runner", "drawer slide", "drawer guide", "drawer rail", "wardrobe", "desk", "kitchen drawer"]
MEASURE_MAP = {"length": "length", "width": "width", "thickness": "base_thickness", "hole_1.diameter": "hole_d"}

PARAMS = {  # name: (default, min, max, step, unit, affects_fit, label)
    "length": (120.0, 60.0, 200.0, 0.5, "mm", True, "Runner length"),
    "width": (18.0, 10.0, 40.0, 0.1, "mm", True, "Overall width"),
    "base_thickness": (3.0, 2.0, 6.0, 0.1, "mm", True, "Strip thickness"),
    "rail_width": (6.0, 3.0, 16.0, 0.1, "mm", True, "Rail width"),
    "rail_height": (6.0, 3.0, 14.0, 0.1, "mm", True, "Rail height above the strip"),
    "lead_in": (12.0, 0.0, 30.0, 0.5, "mm", False, "Tapered front of the rail"),
    "hole_count": (3, 2, 6, 1, "", True, "Screw holes"),
    "hole_d": (4.0, 2.5, 6.0, 0.1, "mm", True, "Screw hole diameter"),
    "corner_radius": (2.0, 0.0, 5.0, 0.1, "mm", False, "Corner radius"),
}


def build(p: dict[str, float]) -> cq.Workplane:
    length, width, t = p["length"], p["width"], p["base_thickness"]
    strip = cq.Workplane("XY").rect(length, width).extrude(t)
    r = min(p["corner_radius"], width / 2 - 1.0)
    if r > 0.2:
        strip = strip.edges("|Z").fillet(r)

    # The rail runs along the +Y edge; the screws sit in the flat part left beside it.
    rw = max(2.0, min(p["rail_width"], width - p["hole_d"] - 5.0))
    flat = width - rw
    y_hole = -width / 2 + flat / 2
    hd = min(p["hole_d"], flat - 2.0)
    n = int(p["hole_count"])
    span = length - 2 * max(hd + 4.0, 10.0)
    xs = [-span / 2 + span * i / (n - 1) for i in range(n)]
    pts = [(x, y_hole) for x in xs]
    strip = strip.cut(cq.Workplane("XY").workplane(offset=-1).pushPoints(pts).circle(hd / 2).extrude(t + 2))
    cb_depth = min(1.4, t - 1.0)
    strip = strip.cut(
        cq.Workplane("XY").workplane(offset=t - cb_depth).pushPoints(pts).circle(hd * 0.95).extrude(cb_depth + 1)
    )

    # Side profile of the rail: flat along its length, tapering down towards the front (+X).
    h = p["rail_height"]
    x0, x1 = -length / 2 + r, length / 2 - r
    lead = min(p["lead_in"], (x1 - x0) * 0.4)
    z0 = t - 0.3
    if lead > 0.2:
        prof = [(x0, z0), (x0, t + h), (x1 - lead, t + h), (x1, t + h * 0.3), (x1, z0)]
    else:
        prof = [(x0, z0), (x0, t + h), (x1, t + h), (x1, z0)]
    rail = cq.Workplane("XZ").polyline(prof).close().extrude(rw / 2, both=True).translate((0, width / 2 - rw / 2, 0))
    return strip.union(rail)


result = build({k: v[0] for k, v in PARAMS.items()})
