"""Desk cable grommet (office desk, TV unit): a lined hole in a table top, with notches the cables sit in."""

import cadquery as cq

FAMILY = "cable_clip"
TITLE = "Desk cable grommet"
SUMMARY = (
    "Ring that lines a cable hole in a desk or TV unit: a thin flange sits on the table top and a sleeve drops into "
    "the hole. Notches in the sleeve's bottom edge guide the cables out."
)
TAGS = ["cable grommet", "desk grommet", "cable hole", "desk", "tv unit", "wire grommet"]
MEASURE_MAP = {"length": "flange_d", "width": "flange_d", "thickness": "sleeve_depth", "bore.diameter": "hole_d"}

PARAMS = {  # name: (default, min, max, step, unit, affects_fit, label)
    "hole_d": (54.0, 16.0, 110.0, 0.1, "mm", True, "Sleeve outside diameter (the table's hole)"),
    "flange_d": (66.0, 22.0, 130.0, 0.1, "mm", True, "Flange diameter"),
    "flange_thickness": (2.5, 1.5, 6.0, 0.05, "mm", False, "Flange thickness"),
    "sleeve_depth": (18.0, 6.0, 50.0, 0.1, "mm", True, "Sleeve depth"),
    "sleeve_wall": (2.5, 1.2, 6.0, 0.05, "mm", False, "Sleeve wall"),
    "notch_count": (2, 0, 4, 1, "", False, "Cable notches"),
    "notch_width": (14.0, 4.0, 30.0, 0.1, "mm", False, "Notch width"),
}


def build(p: dict[str, float]) -> cq.Workplane:
    ft = p["flange_thickness"]
    depth = p["sleeve_depth"]
    rf = p["flange_d"] / 2
    ro = min(p["hole_d"] / 2, rf - 1.5)
    ri = max(ro - p["sleeve_wall"], 3.0)
    ring = cq.Workplane("XY").circle(rf).circle(ri).extrude(ft)
    ring = ring.union(cq.Workplane("XY").workplane(offset=ft - 0.2).circle(ro).circle(ri).extrude(depth + 0.2))

    # Notches through the sleeve's far edge, leaving the top third of the sleeve whole.
    n = int(p["notch_count"])
    if n > 0:
        width = min(p["notch_width"], ri * 0.9)
        notch_h = depth * 0.6
        for i in range(n):
            notch = (
                cq.Workplane("XY")
                .workplane(offset=ft + depth - notch_h)
                .center((ri + ro) / 2, 0)
                .rect(ro - ri + 2.0, width)
                .extrude(notch_h + 1.0)
                .rotate((0, 0, 0), (0, 0, 1), 360.0 * i / n + 45.0)
            )
            ring = ring.cut(notch)
    return ring


result = build({k: v[0] for k, v in PARAMS.items()})
