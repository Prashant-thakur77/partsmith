"""Sliding battery door (TV remote, torch, toy): side rails run in the case's grooves and a flexible clip holds it shut."""

import cadquery as cq

FAMILY = "cover"
TITLE = "Sliding battery door"
SUMMARY = (
    "Flat battery door that slides on two side rails. A U-shaped cut leaves a flexible clip with a bump near the end "
    "of the door, which snaps into the case. Grip grooves on the outer face."
)
TAGS = ["battery door", "sliding door", "sliding cover", "tv remote", "remote control", "torch", "snap clip"]
MEASURE_MAP = {"length": "length", "width": "width", "thickness": "thickness"}

PARAMS = {  # name: (default, min, max, step, unit, affects_fit, label)
    "length": (48.0, 30.0, 90.0, 0.1, "mm", True, "Door length"),
    "width": (36.0, 22.0, 60.0, 0.1, "mm", True, "Overall width, rails included"),
    "thickness": (1.5, 1.0, 3.0, 0.05, "mm", True, "Door thickness"),
    "rail_width": (1.6, 1.0, 3.0, 0.05, "mm", True, "How far each rail sticks out"),
    "rail_thickness": (0.9, 0.6, 2.0, 0.05, "mm", True, "Rail thickness"),
    "clip_length": (9.0, 5.0, 16.0, 0.1, "mm", True, "Clip length"),
    "clip_width": (9.0, 5.0, 20.0, 0.1, "mm", True, "Clip width"),
    "slot_width": (0.9, 0.6, 1.6, 0.05, "mm", False, "Cut around the clip"),
    "bump_height": (0.8, 0.3, 1.6, 0.05, "mm", True, "Clip bump height"),
    "groove_count": (5, 0, 10, 1, "", False, "Grip grooves (outer face)"),
    "corner_radius": (1.5, 0.0, 4.0, 0.1, "mm", False, "Corner radius at the clip end"),
}


def build(p: dict[str, float]) -> cq.Workplane:
    length, width, t = p["length"], p["width"], p["thickness"]
    rw = p["rail_width"]
    plate_w = width - 2 * rw
    plate = cq.Workplane("XY").rect(length, plate_w).extrude(t)
    r = min(p["corner_radius"], plate_w / 2 - 1.0)
    if r > 0.2:
        plate = plate.edges("|Z and >X").fillet(r)

    # The flexible clip: a U-shaped cut, open towards the root, with the free end near +X.
    slot = p["slot_width"]
    cl = min(p["clip_length"], length * 0.4)
    cw = min(p["clip_width"], plate_w - 2 * slot - 4.0)
    x_end = length / 2 - 1.5  # the cut stops short of the door's end
    x_root = x_end - slot - cl
    outer = (
        cq.Workplane("XY")
        .workplane(offset=-1)
        .center((x_root + x_end) / 2, 0)
        .rect(x_end - x_root, cw + 2 * slot)
        .extrude(t + 2)
    )
    tab = (
        cq.Workplane("XY")
        .workplane(offset=-2)
        .center((x_root - 1 + x_end - slot) / 2, 0)
        .rect(x_end - slot - x_root + 1, cw)
        .extrude(t + 4)
    )
    plate = plate.cut(outer.cut(tab))

    # Grip grooves across the outer face (z = 0), behind the clip, keeping at least 0.7 mm of material.
    pitch = 1.6
    x0 = -length / 2 + 3.0
    g = int(min(p["groove_count"], max(0.0, (x_root - 1.0 - x0) / pitch)))
    gd = min(0.4, t - 0.7)
    if g > 0 and gd > 0.1:
        pts = [(x0 + i * pitch, 0.0) for i in range(g)]
        plate = plate.cut(
            cq.Workplane("XY").workplane(offset=-1).pushPoints(pts).rect(0.8, plate_w * 0.7).extrude(1 + gd)
        )

    # The bump that snaps into the case, on the clip's inner face (+Z), near its free end.
    bh = p["bump_height"]
    bx = x_end - slot - 2.2
    prof = [(bx - 1.8, t - 0.2), (bx - 0.3, t + bh), (bx + 0.5, t + bh), (bx + 1.4, t - 0.2)]
    plate = plate.union(cq.Workplane("XZ").polyline(prof).close().extrude(cw / 2 - 0.4, both=True))

    # Side rails, thinner than the door, stopping short of the clip end.
    rt = min(p["rail_thickness"], t)
    rail_len = length - max(r, 0.0) - 3.0
    x_mid = -length / 2 + rail_len / 2
    for sign in (-1.0, 1.0):
        y = sign * (plate_w / 2 + rw / 2 - 0.25)
        plate = plate.union(cq.Workplane("XY").center(x_mid, y).rect(rail_len, rw + 0.5).extrude(rt))
    return plate


result = build({k: v[0] for k, v in PARAMS.items()})
