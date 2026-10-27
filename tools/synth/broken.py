"""SYNTHETIC broken parts for reconstruction evaluation: a template part with a region removed, GT = the intact part.

The break is a CadQuery cut appended to the template program (it runs in the sandbox like any part program):

- `tip`: everything above a height is gone (a snapped hook tip, a sheared clip arm);
- `tab`: a jagged piece missing at one end of the length (a lost tongue or tab);
- `corner`: a jagged triangular piece missing at one footprint corner (a cracked-off corner).

The ground truth keeps the intact part's dims and records the removed region (footprint polygon + height range).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray
from shapely.geometry import MultiPoint, Polygon

from . import geometry as G

F64 = NDArray[np.float64]
BREAK_KINDS = ("tip", "tab", "corner")
DESCRIPTIONS = {
    "tip": "the top of the part snapped off",
    "tab": "a piece is missing at one end",
    "corner": "a corner cracked off",
}


@dataclass(frozen=True)
class Break:
    kind: str
    polygon_cad_mm: tuple[tuple[float, float], ...]  # footprint of the cutter (CAD frame)
    z_range_mm: tuple[float, float]

    @property
    def description(self) -> str:
        return DESCRIPTIONS[self.kind]


def _jagged(a: F64, b: F64, rng: np.random.Generator, n: int = 4, amp: float = 1.2) -> list[tuple[float, float]]:
    """Points strictly between a and b, pushed sideways at random: a fracture line."""
    d = b - a
    nrm = np.array([-d[1], d[0]]) / max(float(np.linalg.norm(d)), 1e-9)
    out = []
    for t in np.linspace(0, 1, n + 2)[1:-1]:
        p = a + t * d + nrm * float(rng.uniform(-amp, amp))
        out.append((float(p[0]), float(p[1])))
    return out


def plan_break(kind: str, intact: G.PartMesh, rng: np.random.Generator) -> Break:
    if kind not in BREAK_KINDS:
        raise ValueError(f"unknown break {kind!r} (known: {', '.join(BREAK_KINDS)})")
    v = intact.vertices
    lo, hi = v.min(axis=0), v.max(axis=0)
    L, W, H = hi - lo
    pad = 2.0
    if kind == "tip":
        plate = float(intact.features.get("plate_thickness_mm") or 0.0)
        z_cut = max(plate + 1.0, float(rng.uniform(0.55, 0.75)) * H)
        if z_cut >= H - 0.5:
            raise ValueError("the part has nothing tall enough to snap off")
        poly = [
            (lo[0] - pad, lo[1] - pad),
            (hi[0] + pad, lo[1] - pad),
            (hi[0] + pad, hi[1] + pad),
            (lo[0] - pad, hi[1] + pad),
        ]
        return Break(kind, tuple((float(x), float(y)) for x, y in poly), (z_cut, float(H) + 1.0))
    if kind == "tab":
        side = 1.0 if rng.uniform() < 0.5 else -1.0
        depth = float(rng.uniform(0.12, 0.2)) * L
        span = float(rng.uniform(0.45, 0.7)) * W
        yc = float(rng.uniform(lo[1] + span / 2, hi[1] - span / 2))
        x_in = (hi[0] - depth) if side > 0 else (lo[0] + depth)
        x_out = (hi[0] + pad) if side > 0 else (lo[0] - pad)
        a, b = np.array([x_in, yc - span / 2]), np.array([x_in, yc + span / 2])
        poly = [
            (x_out, yc - span / 2),
            (float(a[0]), float(a[1])),
            *_jagged(a, b, rng),
            (float(b[0]), float(b[1])),
            (x_out, yc + span / 2),
        ]
        return Break(kind, tuple(poly), (-1.0, float(H) + 1.0))
    # corner: a wedge at the footprint's extreme point in a random diagonal direction
    sx = 1.0 if rng.uniform() < 0.5 else -1.0
    sy = 1.0 if rng.uniform() < 0.5 else -1.0
    d = np.array([sx * L, sy * W]) / math.hypot(L, W)  # towards a bbox corner
    xy = v[:, :2]
    tip = xy[int(np.argmax(xy @ d))]
    depth = float(rng.uniform(0.25, 0.4)) * min(L, W)
    nrm = np.array([-d[1], d[0]])
    base = tip - d * depth
    a, b = base - nrm * 1.6 * depth, base + nrm * 1.6 * depth
    out_a, out_b = a + d * (depth + 2 * pad), b + d * (depth + 2 * pad)
    poly = [
        (float(a[0]), float(a[1])),
        *_jagged(a, b, rng),
        (float(b[0]), float(b[1])),
        (float(out_b[0]), float(out_b[1])),
        (float(out_a[0]), float(out_a[1])),
    ]
    return Break(kind, tuple(poly), (-1.0, float(H) + 1.0))


def cutter_code(b: Break) -> str:
    """CadQuery lines appended to a part program: `build(p)` becomes the template's build minus the break region
    (the sandbox calls `build(params)`)."""
    pts = ", ".join(f"({x:.4f}, {y:.4f})" for x, y in b.polygon_cad_mm)
    z0, z1 = b.z_range_mm
    return (
        "\n\n# synthetic break (evaluation only)\n"
        "intact_build = build\n\n\n"
        "def build(p):\n"
        f"    cutter = cq.Workplane('XY').workplane(offset={z0:.4f}).polyline([{pts}]).close().extrude({z1 - z0:.4f})\n"
        "    return intact_build(p).cut(cutter)\n"
    )


def broken_mesh(code: str, params: dict[str, float], b: Break) -> G.PartMesh:
    return G.build_mesh(code + cutter_code(b), params)


def removed_footprint(intact: G.PartMesh, b: Break) -> Polygon:
    """Footprint (CAD xy) of the material the break removed: the cutter polygon ∩ the intact footprint hull."""
    v = intact.vertices
    if b.kind == "tip":  # what stood above the cut height
        above = v[v[:, 2] > b.z_range_mm[0]]
        out_t = MultiPoint([tuple(p) for p in above[:, :2]]).convex_hull if len(above) >= 3 else Polygon()
        return out_t if isinstance(out_t, Polygon) else Polygon()
    hull = MultiPoint([tuple(p) for p in v[:, :2]]).convex_hull
    cut = Polygon(b.polygon_cad_mm).buffer(0)
    out = cut.intersection(hull)
    return out if isinstance(out, Polygon) else Polygon()


def area_ratio(p: Polygon, intact: G.PartMesh) -> float:
    hull = MultiPoint([tuple(q) for q in intact.vertices[:, :2]]).convex_hull
    return float(p.area / hull.area) if hull.area > 0 else math.nan
