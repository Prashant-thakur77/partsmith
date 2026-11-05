"""Pointer knob (cooler, fan regulator, oven, radio): a skirted knob with a pointer tip and a D-shaft bore."""

import math

import cadquery as cq

FAMILY = "knob"
TITLE = "Pointer knob with D-shaft"
SUMMARY = (
    "Regulator knob for a cooler, fan or oven: a wide skirt with a pointer tip that shows the setting, a fluted grip "
    "above it and a line on top. A blind D-shaped bore from the underside fits a flatted shaft."
)
TAGS = ["pointer knob", "fan knob", "cooler knob", "regulator knob", "oven knob", "skirted knob", "d-shaft"]
MEASURE_MAP = {
    "length": "skirt_d",
    "width": "skirt_d",
    "thickness": "height",
    "bore.diameter": "bore_d",
    "bore.flat_depth": "flat_depth",
    "side.thickness": "height",  # short side of the side photo's silhouette
}

PARAMS = {  # name: (default, min, max, step, unit, affects_fit, label)
    "skirt_d": (38.0, 20.0, 80.0, 0.1, "mm", True, "Skirt diameter"),
    "grip_d": (26.0, 12.0, 60.0, 0.1, "mm", True, "Grip diameter"),
    "height": (16.0, 8.0, 30.0, 0.1, "mm", True, "Overall height"),
    "skirt_height": (3.0, 1.5, 6.0, 0.1, "mm", False, "Skirt height"),
    "pointer_length": (5.0, 2.0, 12.0, 0.1, "mm", False, "Pointer length past the skirt"),
    "bore_d": (6.0, 3.0, 10.0, 0.05, "mm", True, "Shaft bore diameter"),
    "flat_depth": (1.5, 0.0, 3.0, 0.05, "mm", True, "D-flat depth (0 = round bore)"),
    "bore_depth": (11.0, 4.0, 25.0, 0.1, "mm", True, "Bore depth"),
    "grip_count": (10, 0, 24, 1, "", False, "Grip flutes"),
    "grip_depth": (0.8, 0.3, 1.6, 0.05, "mm", False, "Flute depth"),
}


def build(p: dict[str, float]) -> cq.Workplane:
    height = p["height"]
    rs = p["skirt_d"] / 2
    sh = min(p["skirt_height"], height - 3.0)
    rg = min(p["grip_d"], p["skirt_d"] - 2.0) / 2
    knob = cq.Workplane("XY").circle(rs).extrude(sh)

    # The pointer tip, in the skirt's own thickness, at +X.
    tip = p["pointer_length"]
    half = min(rs * 0.3, tip * 0.8 + 1.5)
    pointer = cq.Workplane("XY").polyline([(rs - 1.5, -half), (rs + tip, 0.0), (rs - 1.5, half)]).close().extrude(sh)
    knob = knob.union(pointer)

    grip = cq.Workplane("XY").workplane(offset=sh - 0.2).circle(rg).extrude(height - sh + 0.2)
    n = int(p["grip_count"])
    if n > 0:
        pitch = 2 * math.pi * rg / n
        rf = min(pitch * 0.3, 2.5)
        depth = min(p["grip_depth"], rf * 0.9)
        rc = rg + rf - depth
        pts = [
            (rc * math.cos(2 * math.pi * (i + 0.5) / n), rc * math.sin(2 * math.pi * (i + 0.5) / n)) for i in range(n)
        ]
        grip = grip.cut(cq.Workplane("XY").workplane(offset=sh + 0.1).pushPoints(pts).circle(rf).extrude(height))
    knob = knob.union(grip)

    # A line on top, in line with the pointer.
    line = cq.Workplane("XY").workplane(offset=height - 0.6).center(rg / 2, 0).rect(rg, 1.2).extrude(1.0)
    knob = knob.cut(line)

    rb = min(p["bore_d"], 2 * rg - 5.0) / 2
    depth_b = min(p["bore_depth"], height - 2.0)
    bore = cq.Workplane("XY").workplane(offset=-1).circle(rb).extrude(depth_b + 1)
    flat = min(p["flat_depth"], rb * 0.6)
    if flat > 0.05:
        keep = cq.Workplane("XY").workplane(offset=-2).center(-flat / 2, 0).rect(2 * rb - flat, 2 * rb + 2)
        bore = bore.intersect(keep.extrude(depth_b + 4))
    return knob.cut(bore)


def interfaces(p: dict[str, float]) -> list[dict[str, str | float | list[float]]]:
    """Mating interfaces for the functional probes: the bore takes the control shaft (measured across the round)."""
    depth_b = min(p["bore_depth"], p["height"] - 2.0)
    return [
        {
            "id": "shaft_bore", "label": "shaft bore", "mate_label": "shaft",
            "at": [0.0, 0.0, depth_b / 2], "axis": [0.0, 1.0, 0.0],
            "mates": [3.0, 4.0, 5.0, 6.0, 6.35, 8.0, 10.0],
        }
    ]  # fmt: skip


result = build({k: v[0] for k, v in PARAMS.items()})
