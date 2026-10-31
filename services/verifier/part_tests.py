"""Part tests generated from the PartSpec and the measurements, evaluated against values measured on the model.

P0 (blocking): every measured hole diameter within +/-0.15 mm, footprint length/width within +/-0.3 mm, thickness within
+/-0.3 mm when it was measured or stated by the user, side-view thickness (short side of the side silhouette) within
+/-0.3 mm, and validity: valid solid, single solid, watertight mesh,
volume > 0, min wall >= 0.8 mm (FDM). P1 (reported, not blocking): hole centres within 0.3 mm, blind-hole depths.

Height-bound tests (P0, `height_bound_tests`): a thick part seen only from the top has a length/width the photo cannot
pin down (an end that sits lower than the stated height reads short, see `Measured.bound_mm`). When nothing shows the
heights (no side view, no walk-around) and the model's 3D form is a guess (an extruded outline, not a family template),
the model must be within +/-0.3 mm both of the full-height reading and of the reading for ends at half the height, so
a single top photo of such a part whose ends might sit lower cannot verify it.

Values that were only *inferred* by a model never become a test: the verifier only checks numbers that came from a
measurement or from the user.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from partsmith_schemas.common import BBOX_TOL_MM, FEATURE_TOL_MM, MIN_WALL_MM, Measured, Source
from partsmith_schemas.measurement import Measurements
from partsmith_schemas.partspec import BlindHole, PartSpec, ThroughHole
from partsmith_schemas.verification import ParamSpec, PartTest, UncheckedValue

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


HEIGHT_TESTS = (("length", "bbox.x", "bbox.x.height"), ("width", "bbox.y", "bbox.y.height"))


def height_bound_tests(
    measurements: Mapping[str, Measurements], values: Mapping[str, Value], *, heights_seen: bool
) -> list[PartTest]:
    """P0 tests for top-view dimensions that only hold if the part's ends stand the full stated height.

    ``Measured.bound_mm`` = (full-height reading, on-the-mat reading). The plausible alternative checked here is an
    end at half the stated height (the midpoint): the model must be within ``BBOX_TOL_MM`` of both readings.
    ``heights_seen``: a side view or walk-around frames compare the heights themselves, or the program is a family
    template whose walls stand the stated height by design; no test is added then.
    """
    top = measurements.get("top")
    if top is None or heights_seen:
        return []
    out: list[PartTest] = []
    for name, key, tid in HEIGHT_TESTS:
        m: Measured = getattr(top, name)
        model = values.get(key)
        if m.bound_mm is None or not _trusted(m) or model is None or isinstance(model, bool):
            continue
        lo, hi = m.bound_mm
        mid = (lo + hi) / 2.0
        worst = max(abs(float(model) - lo), abs(float(model) - mid))
        out.append(
            PartTest(
                id=tid,
                description=(
                    f"{name} without a side view: the top photo reads {lo:.2f} mm if the ends stand the full stated "
                    f"height and {mid:.2f} mm if they sit at half of it; the model must be within +/-{BBOX_TOL_MM} mm "
                    "of both (a side photo settles it)"
                ),
                value=round(worst, 4),
                expected=0.0,
                tol=BBOX_TOL_MM,
                passed=worst <= BBOX_TOL_MM + 1e-9,
            )
        )
    return out


# MEASURE_MAP key (a measured quantity) -> the id of the test that compares the model with it
_KEY_TEST = {"length": "bbox.x", "width": "bbox.y", "thickness": "thickness", "side.thickness": "side.thickness"}


def unchecked_values(
    params: Sequence[ParamSpec],
    values: Mapping[str, float],
    measure_map: Mapping[str, str],
    tests: Sequence[PartTest],
    views: Sequence[str],
    stated: Mapping[str, Measured] | None = None,
    stated_knobs: Mapping[str, tuple[float, str]] | None = None,
) -> list[UncheckedValue]:
    """Every dimension knob of the program that no blocking test compared with a measured or user-stated value.

    A knob counts as checked when the program's MEASURE_MAP ties it to a measured quantity and that quantity's P0
    test ran (pass or fail). Counts (unit "") are not dimensions. Everything else comes from the program, a
    template default or a value inferred from the measured ones, and is labelled inferred, not verified.

    ``stated`` (measured quantity -> the user's value): a dimension the photo cannot show, which the user stated (the
    original length of a broken part). Its knob is listed with source ``user_stated`` while the model holds that
    value: stated, not observed, so still not verified.

    ``stated_knobs`` (knob -> (the user's value, what they stated)): a hidden size the user typed (inner bore Ø,
    socket depth) that this knob holds. Listed with source ``user_stated`` while the model holds that value.
    """
    p0 = {t.id for t in tests if t.priority == "P0"}
    checked = set()
    for key, knob in measure_map.items():
        tid = _KEY_TEST.get(key, key if key.endswith(".diameter") else None)
        if tid is not None and tid in p0:
            checked.add(knob)
    said = {measure_map[k]: m for k, m in (stated or {}).items() if k in measure_map}
    seen = ", ".join(views) if views else "no view"
    out: list[UncheckedValue] = []
    for p in params:
        if p.unit == "" or p.name in checked:
            continue
        value = round(float(values.get(p.name, p.default)), 4)
        m = said.get(p.name)
        hidden = (stated_knobs or {}).get(p.name)
        if m is None and hidden is not None and abs(value - hidden[0]) <= max(BBOX_TOL_MM, p.step / 2.0):
            out.append(
                UncheckedValue(
                    param=p.name,
                    label=p.label,
                    value=value,
                    unit=p.unit,
                    source=Source.user_stated,
                    note=(
                        f"stated by the user: {hidden[1]}; the photo cannot show it, so this value is not verified "
                        "and not in the max error"
                    ),
                )
            )
            continue
        if m is not None and abs(value - m.value) <= BBOX_TOL_MM:
            out.append(
                UncheckedValue(
                    param=p.name,
                    label=p.label,
                    value=value,
                    unit=p.unit,
                    source=Source.user_stated,
                    note=(
                        f"stated by the user ({m.value:g} +/- {m.sigma_mm:g} mm), not observed: the photo shows the "
                        "broken part, so this value is not verified and not in the max error"
                    ),
                )
            )
            continue
        out.append(
            UncheckedValue(
                param=p.name,
                label=p.label,
                value=value,
                unit=p.unit,
                note=(
                    "not measured: from the program (template default or inferred from the measured values); no "
                    f"test compares it with the photo, which covers it only as far as it changes the compared "
                    f"silhouettes ({seen})"
                ),
            )
        )
    return out
