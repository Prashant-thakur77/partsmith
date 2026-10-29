"""Battery compartment cover (remote control, toy, clock): thin door with hinge tongues and a snap latch."""

import cadquery as cq

FAMILY = "cover"
TITLE = "Battery compartment cover"
SUMMARY = (
    "Thin sliding/tilting battery door: tongues at one end tuck under the case lip, a cantilever snap latch at the "
    "other end clicks into the case. Grip grooves on the outer face."
)
TAGS = ["battery cover", "battery door", "remote control", "toy", "lid", "snap-fit"]
MEASURE_MAP = {"length": "length", "width": "width", "thickness": "thickness"}

PARAMS = {  # name: (default, min, max, step, unit, affects_fit, label)
    "length": (45.0, 26.0, 100.0, 0.1, "mm", True, "Overall length including tongues"),
    "width": (30.01, 16.0, 60.0, 0.1, "mm", True, "Width"),
    "thickness": (1.5, 1.0, 3.0, 0.05, "mm", True, "Door thickness"),
    "tongue_length": (3.0, 1.5, 6.0, 0.1, "mm", True, "Tongue length"),
    "tongue_width": (4.8, 3.0, 12.0, 0.1, "mm", True, "Tongue width"),
    "tongue_count": (1, 1, 3, 1, "", True, "Hinge tongues"),
    "latch_width": (10.0, 4.0, 30.0, 0.1, "mm", True, "Latch width"),
    "latch_height": (3.5, 2.0, 8.0, 0.1, "mm", True, "Latch height above the inner face"),
    "latch_overhang": (0.8, 0.4, 2.0, 0.05, "mm", True, "Latch hook overhang"),
    "groove_count": (0, 0, 12, 1, "", False, "Grip grooves (outer face)"),
    "corner_radius": (1.5, 0.0, 8.0, 0.1, "mm", False, "Corner radius"),
}


def build(p: dict[str, float]) -> cq.Workplane:
    length, width, t = p["length"], p["width"], p["thickness"]
    tl = p["tongue_length"]
    plate_len = length - tl
    x0 = -length / 2 + tl  # where the door plate starts; tongues stick out beyond it

    plate = cq.Workplane("XY").center(x0 + plate_len / 2, 0).rect(plate_len, width).extrude(t)
    r = min(p["corner_radius"], width / 2 - 0.5, plate_len / 4)
    if r > 0.2:
        plate = plate.edges("|Z and >X").fillet(r)
        r_back = min(r, 1.0)
        if r_back > 0.2:
            plate = plate.edges("|Z and <X").fillet(r_back)

    # Grip grooves across the outer face (z = 0), keeping >= 0.9 mm of material.
    g = int(p["groove_count"])
    gd = min(0.5, t - 0.9)
    if g > 0 and gd > 0.1:
        xs = [(i - (g - 1) / 2) * 2.0 + x0 + plate_len * 0.35 for i in range(g)]
        cut = cq.Workplane("XY").workplane(offset=-1).pushPoints([(x, 0) for x in xs]).rect(1.0, width * 0.6)
        plate = plate.cut(cut.extrude(1 + gd))

    # Tongues, a little thinner than the door.
    n = int(p["tongue_count"])
    tt = max(0.8, min(t, t * 0.75))
    tw = min(p["tongue_width"], (width - 2.0) / n - 1.0)
    pitch = (width - 2.0) / n
    for i in range(n):
        y = -width / 2 + 1.0 + pitch * (i + 0.5)
        tongue = cq.Workplane("XY").box(tl + 0.5, tw, tt, centered=(False, True, False)).translate((-length / 2, y, 0))
        plate = plate.union(tongue)

    # Snap latch on the inner face (+Z) at the far end, hook pointing outwards (+X).
    lw = min(p["latch_width"], width - 4.0)
    lh = p["latch_height"]
    lip = p["latch_overhang"]
    la = max(1.0, t * 0.8)
    x_out = length / 2 - 1.0 - lip  # outer face of the latch arm
    z_top = t + lh
    arm = cq.Workplane("XY").box(la, lw, lh + 0.2, centered=(False, True, False)).translate((x_out - la, 0, t - 0.2))
    lip_h = min(max(lip * 1.5 + 0.6, 1.2), lh - 0.6)
    z0 = z_top - lip_h
    prof = [(x_out - 0.2, z0), (x_out + lip, z0), (x_out + lip, z0 + max(0.9, lip_h * 0.4)), (x_out - 0.2, z_top)]
    hook = cq.Workplane("XZ").polyline(prof).close().extrude(lw / 2, both=True)
    return plate.union(arm).union(hook)


result = build({k: v[0] for k, v in PARAMS.items()})
