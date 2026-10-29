"""Snap retaining clip: a screw-on plate with a cantilever hook that holds a panel or shelf edge."""

import cadquery as cq

FAMILY = "clip"
TITLE = "Snap retaining clip"
SUMMARY = (
    "Flat screw-on plate with a cantilever snap hook at one end; the panel edge slides under the hook lip. "
    "Gusset ribs behind the hook arm stiffen it."
)
TAGS = ["clip", "snap-fit", "panel", "shelf", "retainer", "screw-on"]
# Where each knob moves the outline (normalised model frame; see services/agent/templates/__init__.py).
REGIONS = {
    "hook_overhang": [("xz", 0.2, 0.85, 0.55, 1.0, 1)],
    "arm_height": [("xz", 0.4, 1.0, 0.75, 1.0, 1), ("yz", -1.0, 1.0, 0.75, 1.0, 1)],
    "arm_thickness": [("xz", 0.45, 0.95, 0.1, 1.0, 1), ("xy", 0.5, 1.0, -1.0, 1.0, 1)],
    "rib_count": [("xz", 0.8, 1.0, 0.1, 0.7, 0)],
    "corner_radius": [("xy", -1.0, -0.8, -1.0, -0.6, -1), ("xy", -1.0, -0.8, 0.6, 1.0, -1)],
}
MEASURE_MAP = {
    "length": "length",
    "width": "width",
    "thickness": "thickness",
    "hole_1.diameter": "hole_d",
    "side.thickness": "arm_height",  # overall height seen in the side photo
}

PARAMS = {  # name: (default, min, max, step, unit, affects_fit, label)
    "length": (43.7, 22.0, 80.0, 0.1, "mm", True, "Plate length"),
    "width": (18.0, 10.0, 40.0, 0.1, "mm", True, "Plate width"),
    "thickness": (3.0, 1.5, 6.0, 0.1, "mm", True, "Plate thickness"),
    "hole_d": (3.55, 2.5, 6.0, 0.05, "mm", True, "Screw hole diameter"),
    "arm_height": (6.6, 4.0, 20.0, 0.1, "mm", True, "Hook arm height above the plate"),
    "arm_thickness": (2.5, 1.2, 4.0, 0.1, "mm", True, "Hook arm thickness"),
    "hook_overhang": (1.0, 0.6, 3.0, 0.1, "mm", True, "Snap hook overhang"),
    "rib_count": (0, 0, 4, 1, "", False, "Stiffening ribs behind the arm"),
    "corner_radius": (0.8, 0.0, 6.0, 0.1, "mm", False, "Plate corner radius"),
}


def build(p: dict[str, float]) -> cq.Workplane:
    length, width, t = p["length"], p["width"], p["thickness"]
    arm_t, arm_h, lip = p["arm_thickness"], p["arm_height"], p["hook_overhang"]
    heel = min(4.0, length * 0.12)  # plate continues behind the arm; the ribs sit on it
    x_in = length / 2 - heel - arm_t  # inner face of the hook arm
    z_top = t + arm_h

    plate = cq.Workplane("XY").rect(length, width).extrude(t)
    r = min(p["corner_radius"], width / 2 - 0.5, length / 4)
    if r > 0.2:
        plate = plate.edges("|Z and <X").fillet(r)
    # Screw hole in the free half of the plate.
    edge = 5.04  # hole centre to the plate end: fixed, so the hole stays put when its size changes
    plate = plate.faces(">Z").workplane().center(-length / 2 + edge, 0).hole(p["hole_d"])

    arm = cq.Workplane("XY").box(arm_t, width, z_top, centered=(False, True, False)).translate((x_in, 0, 0))

    # Hook lip pointing back over the plate: flat catch face underneath, sloped lead-in on top.
    lip_h = min(max(lip * 1.5 + 1.0, 1.5), arm_h - 1.0)
    z0 = z_top - lip_h
    tip_h = max(0.9, lip_h * 0.4)
    profile = [(x_in + 0.2, z0), (x_in - lip, z0), (x_in - lip, z0 + tip_h), (x_in + 0.2, z_top)]
    hook = cq.Workplane("XZ").polyline(profile).close().extrude(width / 2, both=True)

    part = plate.union(arm).union(hook)

    n = int(p["rib_count"])
    if n > 0:
        rib_t = max(1.2, arm_t * 0.6)
        rib_h = min(arm_h * 0.6, z0 - t - 0.5)
        x_out = x_in + arm_t
        tri = [(x_out - 0.2, t - 0.2), (length / 2, t - 0.2), (x_out - 0.2, t + rib_h)]
        span = width - rib_t
        for i in range(n):
            y = 0.0 if n == 1 else -span / 2 + span * i / (n - 1)
            rib = cq.Workplane("XZ", origin=(0, y, 0)).polyline(tri).close().extrude(rib_t / 2, both=True)
            part = part.union(rib)
    return part


def interfaces(p: dict[str, float]) -> list[dict[str, str | float | list[float]]]:
    """Mating interfaces for the functional probes: the gap under the hook lip holds the panel edge."""
    length, t = p["length"], p["thickness"]
    arm_h, lip = p["arm_height"], p["hook_overhang"]
    x_in = length / 2 - min(4.0, length * 0.12) - p["arm_thickness"]
    z0 = t + arm_h - min(max(lip * 1.5 + 1.0, 1.5), arm_h - 1.0)
    return [
        {
            "id": "panel_gap", "label": "gap under the hook lip", "mate_label": "panel",
            "at": [x_in - lip / 2, 0.0, (t + z0) / 2], "axis": [0.0, 0.0, 1.0],
            "mates": [2.0, 3.0, 4.0, 5.0, 6.0, 8.0, 10.0, 12.0, 16.0, 18.0],
        }
    ]  # fmt: skip


result = build({k: v[0] for k, v in PARAMS.items()})
