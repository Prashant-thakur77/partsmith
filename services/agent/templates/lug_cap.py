"""Screw cap with thread lugs (bottle, jar, oil can): a closed cap that grips the neck's thread with short lugs."""

import math

import cadquery as cq

FAMILY = "cover"
TITLE = "Screw cap with thread lugs"
SUMMARY = (
    "Round cap for a bottle or jar with a fluted grip and a sealing ring under the top. Short lugs inside catch the "
    "neck's thread; they are not a full helical thread, so check the fit on your neck before trusting a seal."
)
TAGS = ["bottle cap", "screw cap", "jar lid", "lug cap", "oil can", "lid"]
MEASURE_MAP = {"length": "outer_d", "width": "outer_d", "thickness": "height", "side.thickness": "height"}

PARAMS = {  # name: (default, min, max, step, unit, affects_fit, label)
    "outer_d": (32.0, 16.0, 80.0, 0.1, "mm", True, "Outside diameter"),
    "height": (14.0, 6.0, 40.0, 0.1, "mm", True, "Overall height"),
    "wall": (1.8, 1.2, 4.0, 0.05, "mm", True, "Side wall"),
    "top_thickness": (2.0, 1.0, 5.0, 0.05, "mm", False, "Top thickness"),
    "lug_count": (4, 0, 8, 1, "", True, "Thread lugs"),
    "lug_depth": (0.9, 0.4, 2.0, 0.05, "mm", True, "How far each lug sticks in"),
    "seal_height": (1.5, 0.0, 4.0, 0.1, "mm", False, "Sealing ring height (0 = none)"),
    "grip_count": (24, 0, 48, 1, "", False, "Grip flutes"),
    "grip_depth": (0.5, 0.2, 1.2, 0.05, "mm", False, "Flute depth"),
}


def build(p: dict[str, float]) -> cq.Workplane:
    height, wall, top = p["height"], p["wall"], p["top_thickness"]
    ro = p["outer_d"] / 2
    ri = ro - wall
    top = min(top, height - 3.0)
    # The closed top sits on the bed (z = 0); the cap opens towards +Z.
    cap = cq.Workplane("XY").circle(ro).extrude(height)
    cap = cap.cut(cq.Workplane("XY").workplane(offset=top).circle(ri).extrude(height))

    n = int(p["grip_count"])
    if n > 0:
        pitch = 2 * math.pi * ro / n
        rf = min(pitch * 0.3, 2.5)
        depth = min(p["grip_depth"], rf * 0.9, wall * 0.5)
        rc = ro + rf - depth
        pts = [(rc * math.cos(2 * math.pi * i / n), rc * math.sin(2 * math.pi * i / n)) for i in range(n)]
        cap = cap.cut(cq.Workplane("XY").workplane(offset=-1).pushPoints(pts).circle(rf).extrude(height + 2))

    # Thread lugs, near the open end, sunk a little into the wall.
    k = int(p["lug_count"])
    if k > 0:
        ld = min(p["lug_depth"], ri * 0.2)
        lw = min(6.0, 2 * math.pi * ri / k * 0.6)
        lh = min(1.4, (height - top) * 0.3)
        z = height - lh - min(1.5, (height - top) * 0.2)
        for i in range(k):
            lug = (
                cq.Workplane("XY")
                .workplane(offset=z)
                .center(ri - ld / 2 + wall * 0.15, 0)
                .rect(ld + wall * 0.3, lw)
                .extrude(lh)
                .rotate((0, 0, 0), (0, 0, 1), 360.0 * i / k)
            )
            cap = cap.union(lug)

    # A sealing ring under the top, pressing into the neck.
    sh = min(p["seal_height"], height - top - 1.0)
    rs = ri - max(2.0, ri * 0.14)
    if sh > 0.1 and rs > 2.0:
        cap = cap.union(cq.Workplane("XY").workplane(offset=top - 0.2).circle(rs).circle(rs - 0.9).extrude(sh + 0.2))
    return cap


result = build({k: v[0] for k, v in PARAMS.items()})
