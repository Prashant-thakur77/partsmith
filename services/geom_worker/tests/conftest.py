from __future__ import annotations

from collections.abc import Iterator

import pytest

from services.geom_worker.sandbox import WarmPool

PLATE = """
import cadquery as cq
import math

PARAMS = {  # name: (default, min, max, step, unit, affects_fit, label)
    "length": (40.0, 10.0, 120.0, 0.1, "mm", True, "Length"),
    "width": (20.0, 8.0, 60.0, 0.1, "mm", True, "Width"),
    "thickness": (3.0, 1.2, 8.0, 0.1, "mm", True, "Plate thickness"),
    "hole_d": (4.2, 2.0, 8.0, 0.05, "mm", True, "Screw hole"),
    "hole_count": (2, 1, 4, 1, "", False, "Holes"),
}


def build(p):
    plate = cq.Workplane("XY").rect(p["length"], p["width"]).extrude(p["thickness"]).edges("|Z").fillet(2.0)
    n = int(p["hole_count"])
    pts = [(-p["length"] / 2 + p["length"] * (i + 1) / (n + 1), 0) for i in range(n)]
    return plate.faces(">Z").workplane().pushPoints(pts).hole(p["hole_d"])


result = build({k: v[0] for k, v in PARAMS.items()})
"""


@pytest.fixture(scope="session")
def pool() -> Iterator[WarmPool]:
    p = WarmPool(size=2)
    p.warm()
    yield p
    p.close()


@pytest.fixture
def plate_code() -> str:
    return PLATE
