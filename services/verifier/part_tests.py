"""Part tests generated from the PartSpec and the measurements, evaluated against values measured on the model.

P0 (blocking): every measured hole diameter within +/-0.15 mm, footprint length/width within +/-0.3 mm, thickness within
+/-0.3 mm when it was measured or stated by the user, side-view thickness (short side of the side silhouette) within
+/-0.3 mm, and validity: valid solid, single solid, watertight mesh,
volume > 0, min wall >= 0.8 mm (FDM). P1 (reported, not blocking): hole centres within 0.3 mm, blind-hole depths.

Values that were only *inferred* by a model never become a test: the verifier only checks numbers that came from a
measurement or from the user.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal

from partsmith_schemas.common import BBOX_TOL_MM, FEATURE_TOL_MM, MIN_WALL_MM, Measured, Source
from partsmith_schemas.measurement import Measurements
from partsmith_schemas.partspec import BlindHole, PartSpec, ThroughHole
from partsmith_schemas.verification import PartTest

THICKNESS_TOL_MM = 0.3
CENTER_TOL_MM = 0.3
DEPTH_TOL_MM = 0.3

Op = Literal["eq", "ge", "le", "true"]
Value = float | bool | None


@dataclass(frozen=True)
class TestDef:
    __test__ = False  # not a pytest class

    id: str
    description: str
    quantity: str  # key into the model-values dict, e.g. "hole:hole_1.diameter", "bbox.x", "valid"
    op: Op
    expected: float | None = None
    tol: float | None = None
    priority: Literal["P0", "P1"] = "P0"


@dataclass(frozen=True)
class ExpectedHole:
    """A hole the model must have, in the measurement frame of the top view."""

    id: str
    center_mm: tuple[float, float]
    diameter_mm: float
    depth_mm: float | None = None


def _trusted(m: Measured | None) -> bool:
    return m is not None and m.source in (Source.measured, Source.user_stated)


def expected_holes(partspec: PartSpec | None, measurements: Mapping[str, Measurements]) -> list[ExpectedHole]:
    """Measured top-view holes, plus PartSpec holes with measured/user-stated diameters that the photo did not list."""
    out: list[ExpectedHole] = []
    top = measurements.get("top")
    if top is not None:
        for h in top.holes:
            if _trusted(h.diameter):
                out.append(ExpectedHole(h.id, (h.center_mm[0], h.center_mm[1]), h.diameter.value))
    seen = {h.id for h in out}
    if partspec is not None:
        for f in partspec.features:
            if isinstance(f, ThroughHole | BlindHole) and f.id not in seen and _trusted(f.diameter):
                depth = f.depth.value if isinstance(f, BlindHole) and _trusted(f.depth) else None
                out.append(ExpectedHole(f.id, (f.center_mm[0], f.center_mm[1]), f.diameter.value, depth))
    return out


def expected_thickness(partspec: PartSpec | None, measurements: Mapping[str, Measurements]) -> Measured | None:
    for m in measurements.values():
        if _trusted(m.thickness):
            return m.thickness
    if partspec is not None and _trusted(partspec.thickness):
        return partspec.thickness
    return None


def generate_tests(partspec: PartSpec | None, measurements: Mapping[str, Measurements]) -> list[TestDef]:
    """All tests for this part, in a stable order."""
    tests: list[TestDef] = []
    for h in expected_holes(partspec, measurements):
        tests.append(
            TestDef(
                f"{h.id}.diameter",
                f"{h.id} diameter == {h.diameter_mm:.2f} +/- {FEATURE_TOL_MM} mm",
                f"hole:{h.id}.diameter",
                "eq",
                h.diameter_mm,
                FEATURE_TOL_MM,
            )
        )
        tests.append(
            TestDef(
                f"{h.id}.center",
                f"{h.id} centre within {CENTER_TOL_MM} mm of the measured position",
                f"hole:{h.id}.center_offset",
                "le",
                0.0,
                CENTER_TOL_MM,
                "P1",
            )
        )
        if h.depth_mm is not None:
            tests.append(
                TestDef(
                    f"{h.id}.depth",
                    f"{h.id} depth == {h.depth_mm:.2f} +/- {DEPTH_TOL_MM} mm",
                    f"hole:{h.id}.depth",
                    "eq",
                    h.depth_mm,
                    DEPTH_TOL_MM,
                    "P1",
                )
            )
    top = measurements.get("top")
    if top is not None:
        if _trusted(top.length):
            tests.append(
                TestDef(
                    "bbox.x",
                    f"length (long side of the footprint) == {top.length.value:.2f} +/- {BBOX_TOL_MM} mm",
                    "bbox.x",
                    "eq",
                    top.length.value,
                    BBOX_TOL_MM,
                )
            )
        if _trusted(top.width):
            tests.append(
                TestDef(
                    "bbox.y",
                    f"width (short side of the footprint) == {top.width.value:.2f} +/- {BBOX_TOL_MM} mm",
                    "bbox.y",
                    "eq",
                    top.width.value,
                    BBOX_TOL_MM,
                )
            )
    side = measurements.get("side")
    if side is not None and _trusted(side.width):
        tests.append(
            TestDef(
                "side.thickness",
                f"side-view thickness (short side of the side silhouette) == {side.width.value:.2f} +/- "
                f"{THICKNESS_TOL_MM} mm",
                "side.thickness",
                "eq",
                side.width.value,
                THICKNESS_TOL_MM,
            )
        )
    th = expected_thickness(partspec, measurements)
    if th is not None:
        tests.append(
            TestDef(
                "thickness",
                f"plate thickness == {th.value:.2f} +/- {THICKNESS_TOL_MM} mm",
                "thickness",
                "eq",
                th.value,
                THICKNESS_TOL_MM,
            )
        )
    tests += [
        TestDef("valid", "the solid passes the OCCT validity check", "valid", "true"),
        TestDef("single_solid", "exactly one solid body", "single_solid", "true"),
        TestDef("watertight", "the mesh is watertight (printable)", "watertight", "true"),
        TestDef("volume", "volume > 0", "volume", "ge", 0.0, 0.0),
        TestDef("min_wall", f"thinnest wall >= {MIN_WALL_MM} mm (FDM)", "min_wall", "ge", MIN_WALL_MM, 0.0),
    ]
    return tests


def _passes(t: TestDef, v: Value) -> bool:
    if v is None:
        return False
    if t.op == "true":
        return bool(v)
    x = float(v)
    exp = t.expected if t.expected is not None else 0.0
    tol = t.tol or 0.0
    if t.op == "eq":
        return abs(x - exp) <= tol + 1e-9
    if t.op == "le":
        return x <= exp + tol + 1e-9
    if t.id == "volume":
        return x > exp
    return x >= exp - tol - 1e-9


def evaluate_tests(tests: list[TestDef], values: Mapping[str, Value]) -> list[PartTest]:
    """Evaluate tests against model values. A value that could not be measured on the model fails its test."""
    out: list[PartTest] = []
    for t in tests:
        v = values.get(t.quantity)
        desc = t.description if v is not None else f"{t.description} (not found on the model)"
        num = None if v is None or isinstance(v, bool) else float(v)
        if isinstance(v, bool):
            num = 1.0 if v else 0.0
        out.append(
            PartTest(
                id=t.id,
                description=desc,
                value=num,
                expected=t.expected,
                tol=t.tol,
                passed=_passes(t, v),
                priority=t.priority,
            )
        )
    return out
