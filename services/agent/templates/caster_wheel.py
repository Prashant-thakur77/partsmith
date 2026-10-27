"""Caster wheel (furniture, trolley, office chair): solid tread, axle bore, lightening holes between spokes."""

import math

import cadquery as cq

FAMILY = "wheel"
TITLE = "Caster wheel"
SUMMARY = (
    "Solid caster wheel lying on its side face: rounded tread edges, an axle bore and lightening holes that leave "
    "spokes between the hub and the rim."
)
TAGS = ["wheel", "caster", "castor", "trolley", "furniture", "roller"]
# Where each knob moves the outline (normalised model frame; see services/agent/templates/__init__.py).
REGIONS = {
    "edge_fillet": [
        ("xz", 0.75, 1.0, 0.0, 0.3, -1),
        ("xz", -1.0, -0.75, 0.0, 0.3, -1),
        ("xz", 0.75, 1.0, 0.7, 1.0, -1),
        ("xz", -1.0, -0.75, 0.7, 1.0, -1),
        ("yz", 0.75, 1.0, 0.0, 0.3, -1),
        ("yz", -1.0, -0.75, 0.0, 0.3, -1),
        ("yz", 0.75, 1.0, 0.7, 1.0, -1),
        ("yz", -1.0, -0.75, 0.7, 1.0, -1),
    ],
    "rim_thickness": [("xy", -0.85, 0.85, -0.85, 0.85, 1)],
    "hub_d": [("xy", -0.6, 0.6, -0.6, 0.6, 1)],
    "spoke_count": [("xy", -0.85, 0.85, -0.85, 0.85, 0)],
}
MEASURE_MAP = {
    "length": "diameter",
    "width": "diameter",
    "thickness": "tread_width",
    "hole_1.diameter": "bore_d",
    "side.thickness": "tread_width",  # short side of the side photo's silhouette
}

PARAMS = {  # name: (default, min, max, step, unit, affects_fit, label)
    "diameter": (50.0, 20.0, 120.0, 0.1, "mm", True, "Wheel diameter"),
    "tread_width": (18.0, 6.0, 50.0, 0.1, "mm", True, "Tread width"),
    "bore_d": (8.0, 3.0, 20.0, 0.05, "mm", True, "Axle bore diameter"),
    "hub_d": (18.0, 8.0, 40.0, 0.1, "mm", False, "Hub diameter"),
    "rim_thickness": (5.0, 2.0, 15.0, 0.1, "mm", False, "Rim thickness"),
    "spoke_count": (5, 0, 10, 1, "", False, "Spokes (lightening holes)"),
    "edge_fillet": (2.0, 0.0, 6.0, 0.1, "mm", False, "Tread edge fillet"),
}


def build(p: dict[str, float]) -> cq.Workplane:
    radius, w = p["diameter"] / 2, p["tread_width"]
    rim = min(p["rim_thickness"], radius * 0.3)
    hub_r = min(p["hub_d"] / 2, radius - rim - 2.0)
    rb = min(p["bore_d"] / 2, hub_r - 1.0, radius * 0.4)

    wheel = cq.Workplane("XY").circle(radius).extrude(w)
    f = min(p["edge_fillet"], w * 0.3, rim * 0.6)
    if f > 0.1:
        wheel = wheel.edges().fillet(f)

    n = int(p["spoke_count"])
    band = radius - rim - hub_r
    if n > 0 and band > 2.0:
        rc = hub_r + band / 2
        d = min(band * 0.8, 2 * math.pi * rc / n * 0.6) if n > 1 else band * 0.8
        if d > 1.5:
            pts = [(rc * math.cos(2 * math.pi * i / n), rc * math.sin(2 * math.pi * i / n)) for i in range(n)]
            cut = cq.Workplane("XY").workplane(offset=-1).pushPoints(pts).circle(d / 2).extrude(w + 2)
            wheel = wheel.cut(cut)
    return wheel.cut(cq.Workplane("XY").workplane(offset=-1).circle(rb).extrude(w + 2))


result = build({k: v[0] for k, v in PARAMS.items()})
