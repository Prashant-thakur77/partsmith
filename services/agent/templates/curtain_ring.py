"""Curtain ring (curtain rod, shower rail): a ring that slides on the rod, with eyelets for the curtain's hook."""

import math

import cadquery as cq

FAMILY = "hook"
TITLE = "Curtain ring"
SUMMARY = (
    "Flat ring that slides along a curtain rod, with an eyelet below for the curtain's hook. Small bumps inside the "
    "ring ride on the rod and keep the ring from sticking."
)
TAGS = ["curtain ring", "curtain glider", "curtain rod", "shower rail", "eyelet", "drapery ring"]
MEASURE_MAP = {"length": "inner_d", "width": "inner_d", "thickness": "thickness", "bore.diameter": "inner_d"}

PARAMS = {  # name: (default, min, max, step, unit, affects_fit, label)
    "inner_d": (30.0, 12.0, 70.0, 0.1, "mm", True, "Inside diameter (rod plus clearance)"),
    "ring_wall": (4.0, 2.0, 8.0, 0.1, "mm", False, "Ring wall"),
    "thickness": (5.0, 2.5, 12.0, 0.1, "mm", True, "Ring thickness"),
    "eyelet_count": (1, 0, 2, 1, "", True, "Eyelets"),
    "eyelet_d": (4.0, 2.0, 8.0, 0.1, "mm", True, "Eyelet hole diameter"),
    "eyelet_wall": (2.5, 1.5, 5.0, 0.1, "mm", False, "Wall around the eyelet"),
    "bump_count": (3, 0, 8, 1, "", False, "Bumps inside the ring"),
    "bump_height": (0.8, 0.4, 2.0, 0.05, "mm", True, "Bump height"),
}


def build(p: dict[str, float]) -> cq.Workplane:
    t = p["thickness"]
    inner = p["inner_d"] / 2
    outer = inner + p["ring_wall"]
    ring = cq.Workplane("XY").circle(outer).circle(inner).extrude(t)

    # Bumps along the top half of the bore, where the ring hangs on the rod.
    n = int(p["bump_count"])
    if n > 0:
        pitch = math.pi * inner / n
        br = min(1.2, pitch * 0.4)
        bh = min(p["bump_height"], br * 0.9)
        pts = [
            (
                (inner + br - bh) * math.cos(math.pi * (i + 0.5) / n),
                (inner + br - bh) * math.sin(math.pi * (i + 0.5) / n),
            )
            for i in range(n)
        ]
        ring = ring.union(cq.Workplane("XY").pushPoints(pts).circle(br).extrude(t))

    # Eyelets: the first below the ring, a second on the side when asked for. Each hole clears the ring's outer wall.
    hr = p["eyelet_d"] / 2
    er = hr + p["eyelet_wall"]
    centre = outer + hr + 0.5
    spots = [(0.0, -centre), (centre, 0.0)][: int(p["eyelet_count"])]
    if spots:
        ring = ring.union(cq.Workplane("XY").pushPoints(spots).circle(er).extrude(t))
        ring = ring.cut(cq.Workplane("XY").workplane(offset=-1).pushPoints(spots).circle(hr).extrude(t + 2))
    return ring


result = build({k: v[0] for k, v in PARAMS.items()})
