"""Chair leg cap (chair, stool, table): a cup that fits over a round leg and spreads its weight on the floor."""

import math

import cadquery as cq

FAMILY = "spacer"
TITLE = "Chair leg cap"
SUMMARY = (
    "Round cup that slips over the end of a chair or table leg, on a wider sole that protects the floor. Ribs inside "
    "grip the leg. It suits a flexible filament best, and a stiff one needs an exact leg size."
)
TAGS = ["chair leg cap", "chair glide", "furniture foot", "leg tip", "stool", "table leg", "ferrule"]
MEASURE_MAP = {"length": "sole_d", "width": "sole_d", "thickness": "height", "bore.diameter": "leg_d"}

PARAMS = {  # name: (default, min, max, step, unit, affects_fit, label)
    "leg_d": (22.0, 8.0, 60.0, 0.1, "mm", True, "Leg diameter"),
    "wall": (2.5, 1.2, 6.0, 0.05, "mm", False, "Cup wall"),
    "height": (24.0, 8.0, 60.0, 0.1, "mm", True, "Overall height"),
    "sole_d": (34.0, 14.0, 90.0, 0.1, "mm", True, "Sole diameter"),
    "sole_thickness": (5.0, 2.0, 12.0, 0.1, "mm", True, "Sole thickness"),
    "rib_count": (6, 0, 12, 1, "", True, "Grip ribs inside"),
    "rib_depth": (0.6, 0.2, 1.5, 0.05, "mm", True, "How far each rib sticks in"),
}


def build(p: dict[str, float]) -> cq.Workplane:
    sole_t = min(p["sole_thickness"], p["height"] - 3.0)
    height = p["height"]
    rs = p["sole_d"] / 2
    ri = min(p["leg_d"] / 2, rs - 1.5)
    ro = min(ri + p["wall"], rs)
    cap = cq.Workplane("XY").circle(rs).extrude(sole_t)
    cap = cap.union(cq.Workplane("XY").workplane(offset=sole_t - 0.2).circle(ro).extrude(height - sole_t + 0.2))
    cap = cap.cut(cq.Workplane("XY").workplane(offset=sole_t).circle(ri).extrude(height))

    n = int(p["rib_count"])
    if n > 0:
        depth = min(p["rib_depth"], ri * 0.2)
        rib_w = min(1.6, 2 * math.pi * ri / n * 0.4)
        wall = ro - ri
        for i in range(n):
            rib = (
                cq.Workplane("XY")
                .workplane(offset=sole_t - 0.1)
                .center(ri - depth / 2 + wall * 0.2, 0)
                .rect(depth + wall * 0.4, rib_w)
                .extrude(height - sole_t + 0.1)
                .rotate((0, 0, 0), (0, 0, 1), 360.0 * i / n)
            )
            cap = cap.union(rib)
    return cap


result = build({k: v[0] for k, v in PARAMS.items()})
