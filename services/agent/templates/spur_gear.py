"""Spur gear (mixer, toy, printer, window motor): a toothed wheel with a hub and a shaft bore, flat or D-shaped."""

import math

import cadquery as cq

FAMILY = "gear"
TITLE = "Spur gear"
SUMMARY = (
    "Straight-cut gear with a raised hub and a shaft bore, round or D-shaped. The tooth flanks are a straight-sided "
    "approximation of the usual curve: good for slow, light loads such as a toy or a window motor, and not for speed."
)
TAGS = ["spur gear", "gear", "cog", "pinion", "mixer gear", "toy gear", "window motor"]
MEASURE_MAP = {
    "length": "pitch_d",
    "width": "pitch_d",
    "thickness": "thickness",
    "bore.diameter": "bore_d",
    "bore.flat_depth": "flat_depth",
}

PARAMS = {  # name: (default, min, max, step, unit, affects_fit, label)
    "pitch_d": (40.0, 12.0, 120.0, 0.1, "mm", True, "Pitch diameter"),
    "teeth": (24, 8, 60, 1, "", True, "Teeth"),
    "thickness": (6.0, 2.0, 20.0, 0.1, "mm", True, "Tooth face width"),
    "bore_d": (5.0, 2.0, 20.0, 0.05, "mm", True, "Shaft bore diameter"),
    "flat_depth": (0.0, 0.0, 3.0, 0.05, "mm", True, "D-flat depth (0 = round bore)"),
    "hub_d": (14.0, 6.0, 40.0, 0.1, "mm", False, "Hub diameter"),
    "hub_height": (4.0, 0.0, 15.0, 0.1, "mm", False, "Hub height above the teeth"),
}


def build(p: dict[str, float]) -> cq.Workplane:
    z = int(p["teeth"])
    t = p["thickness"]
    m = p["pitch_d"] / z
    rp = p["pitch_d"] / 2
    ra, rf = rp + m, rp - 1.25 * m
    pitch = 2 * math.pi / z
    pts = []
    for i in range(z):
        c = i * pitch
        flank = [(rf, -0.32), (rp, -0.25), (ra, -0.13), (ra, 0.13), (rp, 0.25), (rf, 0.32)]
        pts += [(r * math.cos(c + w * pitch), r * math.sin(c + w * pitch)) for r, w in flank]
    gear = cq.Workplane("XY").polyline(pts).close().extrude(t)

    rb = min(p["bore_d"], 2 * rf - 3.0) / 2
    hub_h = p["hub_height"]
    hub_r = min(max(p["hub_d"] / 2, rb + 1.5), rf - 0.5)
    if hub_h > 0.1:
        gear = gear.union(cq.Workplane("XY").workplane(offset=t - 0.2).circle(hub_r).extrude(hub_h + 0.2))

    bore = cq.Workplane("XY").workplane(offset=-1).circle(rb).extrude(t + hub_h + 2)
    flat = min(p["flat_depth"], rb * 0.6)
    if flat > 0.05:
        keep = cq.Workplane("XY").workplane(offset=-2).center(-flat / 2, 0).rect(2 * rb - flat, 2 * rb + 2)
        bore = bore.intersect(keep.extrude(t + hub_h + 4))
    return gear.cut(bore)


def interfaces(p: dict[str, float]) -> list[dict[str, str | float | list[float]]]:
    """Mating interfaces for the functional probes: the bore takes the shaft (measured across the round)."""
    return [
        {
            "id": "shaft_bore", "label": "shaft bore", "mate_label": "shaft",
            "at": [0.0, 0.0, p["thickness"] / 2], "axis": [0.0, 1.0, 0.0],
            "mates": [2.0, 3.0, 4.0, 5.0, 6.0, 8.0, 10.0, 12.0],
        }
    ]  # fmt: skip


result = build({k: v[0] for k, v in PARAMS.items()})
