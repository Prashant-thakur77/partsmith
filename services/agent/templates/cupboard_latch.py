"""Cupboard turn-button latch: a rounded bar that pivots on one screw and swings over the door edge."""

import cadquery as cq

FAMILY = "latch"
TITLE = "Cupboard turn-button latch"
SUMMARY = (
    "Turn button for cupboard doors and hatches: a stadium-shaped bar on a countersunk pivot screw. The catch end "
    "is relieved underneath so it reaches over the door; finger ridges on top."
)
TAGS = ["latch", "turn button", "cupboard", "cabinet", "catch", "door"]
MEASURE_MAP = {"length": "length", "width": "width", "thickness": "thickness", "hole_1.diameter": "pivot_d"}

PARAMS = {  # name: (default, min, max, step, unit, affects_fit, label)
    "length": (45.0, 25.0, 90.0, 0.1, "mm", True, "Length"),
    "width": (14.0, 9.0, 30.0, 0.1, "mm", True, "Width"),
    "thickness": (6.0, 3.0, 12.0, 0.1, "mm", True, "Thickness"),
    "pivot_d": (4.2, 2.5, 6.0, 0.05, "mm", True, "Pivot screw hole diameter"),
    "pivot_offset": (8.0, 0.0, 25.0, 0.1, "mm", True, "Pivot offset from centre"),
    "step_depth": (2.5, 0.0, 6.0, 0.1, "mm", True, "Underside relief at the catch end"),
    "catch_length": (14.0, 5.0, 40.0, 0.1, "mm", True, "Catch end length"),
    "grip_count": (2, 0, 4, 1, "", False, "Finger ridges"),
    "edge_fillet": (0.8, 0.0, 2.0, 0.05, "mm", False, "Top edge fillet"),
}


def build(p: dict[str, float]) -> cq.Workplane:
    length, width, t = p["length"], p["width"], p["thickness"]
    hole_d = min(p["pivot_d"], width - 4.0)
    catch = min(p["catch_length"], length * 0.4)
    x_catch = length / 2 - catch  # the relieved end starts here
    xp = -min(p["pivot_offset"], length / 2 - width / 2)  # pivot sits on the round end, never under the catch
    xp = min(xp, x_catch - hole_d - 2.0)

    bar = cq.Workplane("XY").slot2D(length, width).extrude(t)
    f = min(p["edge_fillet"], t * 0.3, width * 0.2)
    if f > 0.05:
        bar = bar.faces(">Z").edges().fillet(f)

    step = min(p["step_depth"], t - 1.5)
    if step > 0.1:
        relief = cq.Workplane("XY").box(catch + 1, width + 2, step + 1, centered=(False, True, False))
        bar = bar.cut(relief.translate((x_catch, 0, -1)))

    csk = min(hole_d * 2.0, width - 2.0)
    bar = bar.faces(">Z").workplane(centerOption="ProjectedOrigin").center(xp, 0).cskHole(hole_d, csk, 90)

    n = int(p["grip_count"])
    if n > 0:
        xs = [x_catch + catch / 2 + (i - (n - 1) / 2) * 2.5 for i in range(n)]
        ridges = (
            cq.Workplane("XY")
            .workplane(offset=t - 0.3)
            .pushPoints([(x, 0) for x in xs])
            .rect(1.2, width * 0.55)
            .extrude(1.3)
        )
        bar = bar.union(ridges)
    return bar


result = build({k: v[0] for k, v in PARAMS.items()})
