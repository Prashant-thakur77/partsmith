"""Shelf support pin (bookcase, kitchen cabinet): a peg for the side panel's hole with a flat rest for the shelf."""

import cadquery as cq

FAMILY = "clip"
TITLE = "Shelf support pin"
SUMMARY = (
    "Small peg that plugs into a hole in a cabinet's side panel, with a flat rest the shelf sits on. Crush ribs on the "
    "peg take up a loose hole, and an optional lip stops the shelf sliding off."
)
TAGS = ["shelf pin", "shelf support", "shelf peg", "bookcase", "kitchen cabinet", "cupboard shelf"]
MEASURE_MAP = {"length": "rest_length", "width": "rest_width", "thickness": "peg_length", "peg.diameter": "peg_d"}

PARAMS = {  # name: (default, min, max, step, unit, affects_fit, label)
    "rest_length": (16.0, 8.0, 40.0, 0.1, "mm", True, "Rest length"),
    "rest_width": (9.0, 6.0, 24.0, 0.1, "mm", True, "Rest width"),
    "rest_thickness": (2.5, 1.5, 6.0, 0.05, "mm", True, "Rest thickness"),
    "peg_d": (5.0, 3.0, 8.0, 0.05, "mm", True, "Peg diameter"),
    "peg_length": (9.0, 4.0, 20.0, 0.1, "mm", True, "Peg length"),
    "rib_count": (4, 0, 8, 1, "", False, "Crush ribs on the peg"),
    "lip_height": (1.5, 0.0, 4.0, 0.1, "mm", False, "Lip at the rest's end (0 = none)"),
}


def build(p: dict[str, float]) -> cq.Workplane:
    length, width, t = p["rest_length"], p["rest_width"], p["rest_thickness"]
    rest = cq.Workplane("XY").rect(length, width).extrude(t)
    r = min(1.5, width / 2 - 1.0)
    rest = rest.edges("|Z and >X").fillet(r)

    # The peg stands up from the rest near its -X end, the end that meets the panel.
    peg_r = min(p["peg_d"] / 2, width / 2 - 0.5)
    x = -length / 2 + max(min(width / 2, length * 0.3), peg_r + 0.9)  # the ribs stay inside the rest's end
    peg = cq.Workplane("XY").workplane(offset=t - 0.2).center(x, 0).circle(peg_r).extrude(p["peg_length"] + 0.2)
    n = int(p["rib_count"])
    if n > 0:
        for i in range(n):
            rib = (
                cq.Workplane("XY")
                .workplane(offset=t - 0.2)
                .center(peg_r, 0)
                .rect(0.8, 0.9)
                .extrude(p["peg_length"] * 0.7)
                .rotate((0, 0, 0), (0, 0, 1), 360.0 * i / n)
                .translate((x, 0, 0))
            )
            peg = peg.union(rib)
    pin = rest.union(peg)

    # The lip rises at the +X end, on the peg's side, so the rest's far edge holds the shelf back.
    lip = p["lip_height"]
    if lip > 0.1:
        block = (
            cq.Workplane("XY")
            .workplane(offset=t - 0.2)
            .center(length / 2 - 1.2, 0)
            .rect(1.4, width - 2 * r)
            .extrude(lip + 0.2)
        )
        pin = pin.union(block)
    return pin


result = build({k: v[0] for k, v in PARAMS.items()})
