"""Hinge pin bracket (flap, cabinet lid, gate): a screw-down base with two lugs that carry a hinge pin."""

import cadquery as cq

FAMILY = "hinge"
TITLE = "Hinge pin bracket"
SUMMARY = (
    "Flat base with screw holes and two upright lugs. A pin runs through the lugs, so whatever sits in the gap between "
    "them can swing. Round-topped lugs clear the moving part."
)
TAGS = ["hinge bracket", "pin bracket", "clevis", "flap hinge", "lid hinge", "gate", "cabinet"]
MEASURE_MAP = {
    "length": "length",
    "width": "width",
    "thickness": "lug_height",
    "pin.diameter": "pin_d",
    "hole_1.diameter": "hole_d",
    "side.thickness": "lug_height",  # short side of the side photo's silhouette
}

PARAMS = {  # name: (default, min, max, step, unit, affects_fit, label)
    "length": (40.0, 24.0, 80.0, 0.1, "mm", True, "Base length"),
    "width": (24.0, 14.0, 50.0, 0.1, "mm", True, "Base width"),
    "base_thickness": (3.0, 2.0, 6.0, 0.1, "mm", True, "Base thickness"),
    "lug_height": (16.0, 8.0, 30.0, 0.1, "mm", True, "Lug height above the base"),
    "lug_thickness": (4.0, 2.5, 8.0, 0.1, "mm", True, "Lug thickness"),
    "lug_gap": (12.0, 2.0, 40.0, 0.1, "mm", True, "Gap between the lugs"),
    "pin_d": (5.0, 2.0, 10.0, 0.05, "mm", True, "Pin hole diameter"),
    "hole_d": (4.0, 2.5, 6.0, 0.1, "mm", True, "Screw hole diameter"),
    "hole_rows": (1, 1, 2, 1, "", True, "Rows of screw holes at each end"),
    "corner_radius": (2.0, 0.0, 6.0, 0.1, "mm", False, "Corner radius"),
}


def lug_sizes(p: dict[str, float]) -> tuple[float, float, float, float, float]:
    """Half the gap, lug thickness, lug width, pin hole radius and the pin's height, after the limits that keep walls."""
    lt = p["lug_thickness"]
    half_gap = max(1.0, min(p["lug_gap"], p["length"] - 2 * lt - 2 * (p["hole_d"] + 4.0)) / 2)
    pin_r = min(p["pin_d"] / 2, p["lug_height"] / 2 - 1.5)
    lug_w = min(p["width"] * 0.7, 2 * (p["lug_height"] - pin_r - 1.0))
    pin_r = min(pin_r, lug_w / 2 - 1.5)
    return half_gap, lt, lug_w, pin_r, p["base_thickness"] + p["lug_height"] - lug_w / 2


def build(p: dict[str, float]) -> cq.Workplane:
    length, width, t = p["length"], p["width"], p["base_thickness"]
    base = cq.Workplane("XY").rect(length, width).extrude(t)
    r = min(p["corner_radius"], width / 2 - 1.0)
    if r > 0.2:
        base = base.edges("|Z").fillet(r)

    half_gap, lt, lug_w, pin_r, z_pin = lug_sizes(p)
    hd = p["hole_d"]
    x_hole = (length / 2 + half_gap + lt) / 2
    ys = [0.0] if int(p["hole_rows"]) == 1 else [-width * 0.28, width * 0.28]
    pts = [(sign * x_hole, y) for sign in (-1.0, 1.0) for y in ys]
    base = base.cut(cq.Workplane("XY").workplane(offset=-1).pushPoints(pts).circle(hd / 2).extrude(t + 2))

    for sign in (-1.0, 1.0):
        x = sign * (half_gap + lt / 2)
        web = cq.Workplane("XY").workplane(offset=t - 0.2).center(x, 0).rect(lt, lug_w).extrude(z_pin - t + 0.2)
        top = cq.Workplane("YZ").workplane(offset=x - lt / 2).center(0, z_pin).circle(lug_w / 2).extrude(lt)
        base = base.union(web).union(top)
    pin = (
        cq.Workplane("YZ")
        .workplane(offset=-(half_gap + lt + 1))
        .center(0, z_pin)
        .circle(pin_r)
        .extrude(2 * (half_gap + lt + 1))
    )
    return base.cut(pin)


def interfaces(p: dict[str, float]) -> list[dict[str, str | float | list[float]]]:
    """Mating interfaces for the functional probes: the pin hole, probed inside one lug."""
    sizes = lug_sizes(p)
    half_gap, lt, z_pin = sizes[0], sizes[1], sizes[4]
    return [
        {
            "id": "pin_hole", "label": "pin hole", "mate_label": "hinge pin",
            "at": [half_gap + lt / 2, 0.0, z_pin], "axis": [0.0, 1.0, 0.0],
            "mates": [2.0, 3.0, 4.0, 5.0, 6.0, 8.0, 10.0],
        }
    ]  # fmt: skip


result = build({k: v[0] for k, v in PARAMS.items()})
