"""Spacer / standoff: a tube with a through bore, chamfered ends and optional wrench flats."""

import math

import cadquery as cq

FAMILY = "spacer"
TITLE = "Spacer / standoff"
SUMMARY = (
    "Cylindrical spacer with a through bore for a screw (M3 clearance by default) and chamfered ends. "
    "Wrench flats (0 = round) stop it turning and change its cross-section."
)
TAGS = ["spacer", "standoff", "bushing", "washer", "pcb", "m3"]
MEASURE_MAP = {"length": "outer_d", "width": "outer_d", "thickness": "height", "hole_1.diameter": "bore_d"}

PARAMS = {  # name: (default, min, max, step, unit, affects_fit, label)
    "outer_d": (8.0, 4.0, 30.0, 0.05, "mm", True, "Outer diameter"),
    "height": (8.5, 2.0, 60.0, 0.1, "mm", True, "Height"),
    "bore_d": (3.9, 1.5, 20.0, 0.05, "mm", True, "Bore diameter"),
    "chamfer": (0.4, 0.0, 1.5, 0.05, "mm", False, "End chamfer"),
    "flat_count": (0, 0, 6, 1, "", False, "Wrench flats"),
    "flat_depth": (0.8, 0.2, 3.0, 0.05, "mm", False, "Flat depth"),
}


def build(p: dict[str, float]) -> cq.Workplane:
    radius, height = p["outer_d"] / 2, p["height"]
    rb = min(p["bore_d"] / 2, radius - 1.0)
    part = cq.Workplane("XY").circle(radius).extrude(height)

    n = int(p["flat_count"])
    depth = min(p["flat_depth"], (radius - rb) * 0.5)
    if n > 0 and depth > 0.05:
        if n >= 3:  # neighbouring flats must not swallow each other
            depth = min(depth, radius * (1 - math.cos(math.pi / n)) * 0.9)
        for i in range(n):
            ang = 360.0 * i / n
            cutter = (
                cq.Workplane("XY")
                .box(radius + 2, 4 * radius, height + 2, centered=(False, True, False))
                .translate((radius - depth, 0, -1))
                .rotate((0, 0, 0), (0, 0, 1), ang)
            )
            part = part.cut(cutter)

    part = part.cut(cq.Workplane("XY").workplane(offset=-1).circle(rb).extrude(height + 2))
    c = min(p["chamfer"], (radius - rb) * 0.4, height * 0.2)
    while c > 0.05:  # short edges between close flats can refuse a big chamfer: halve it until OCCT accepts
        try:
            return part.faces(">Z or <Z").edges().chamfer(c)
        except Exception:
            c = c / 2
    return part


result = build({k: v[0] for k, v in PARAMS.items()})
