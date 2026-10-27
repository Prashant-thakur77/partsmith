"""Reference objects: standardised everyday items with published dimensions, used as ground truth without a caliper.

Each object has a spec table (nominal, accepted range, which photo view shows it) and an exact parametric model
(a CadQuery program run in the geometry sandbox) for SYNTHETIC renders. The same spec tables score REAL photos of
these objects (`eval/measure_only.py`). A "loose" spec means the standard allows a wide range: the error is reported
both against the nominal value and as the distance to the accepted range.

Model details that are not part of a spec (the SD card's corner chamfer size, the AA cell's terminal button, the
LEGO stud size) are only there so the renders look right; they are never scored.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

View = Literal["top", "side"]


@dataclass(frozen=True)
class SpecDim:
    name: str  # matches the measured name: length, width, thickness
    nominal_mm: float
    lo_mm: float
    hi_mm: float
    view: View
    note: str = ""

    @property
    def tol_mm(self) -> float:
        """Half-width of the accepted range around the nominal value (the larger side)."""
        return max(self.nominal_mm - self.lo_mm, self.hi_mm - self.nominal_mm)

    def error(self, measured_mm: float) -> float:
        """Signed error vs the nominal value."""
        return measured_mm - self.nominal_mm

    def range_error(self, measured_mm: float) -> float:
        """Distance (≥ 0) from the measured value to the accepted range [lo, hi]."""
        return max(self.lo_mm - measured_mm, 0.0, measured_mm - self.hi_mm)

    def within_spec(self, measured_mm: float) -> bool:
        return self.lo_mm <= measured_mm <= self.hi_mm


@dataclass(frozen=True)
class ReferenceObject:
    key: str
    title: str
    dims: tuple[SpecDim, ...]
    loose: bool
    spec_note: str
    code: str  # CadQuery part program (PARAMS-free), CAD frame: z up, resting on z = 0, centred in x/y
    user_thickness_mm: float  # height of the top face in the top view (what the user would say)
    side_view: bool
    colour_bgr: tuple[int, int, int]
    accent_bgr: tuple[int, int, int] | None = None  # e.g. metal ends of a battery
    family_hint: str = "reference"

    def dim(self, name: str) -> SpecDim:
        for d in self.dims:
            if d.name == name:
                return d
        raise KeyError(f"{self.key} has no spec dimension {name!r}")

    def dims_for(self, view: View) -> tuple[SpecDim, ...]:
        return tuple(d for d in self.dims if d.view == view)


_CARD = """import cadquery as cq

L, W, T, R = 85.60, 53.98, 0.76, 3.18
result = cq.Workplane("XY").rect(L, W).extrude(T).edges("|Z").fillet(R)
"""

_SD = """import cadquery as cq

L, W, T, C = 32.0, 24.0, 2.1, 4.0
body = cq.Workplane("XY").rect(L, W).extrude(T)
cut = (
    cq.Workplane("XY")
    .polyline([(L / 2 - C, W / 2 + 0.01), (L / 2 + 0.01, W / 2 + 0.01), (L / 2 + 0.01, W / 2 - C)])
    .close()
    .extrude(T + 2)
    .translate((0, 0, -1))
)
result = body.cut(cut)
"""

_LEGO = """import cadquery as cq

L, W, H = 31.8, 15.8, 9.6
STUD_D, STUD_H, PITCH = 4.8, 1.7, 8.0
body = cq.Workplane("XY").rect(L, W).extrude(H)
pts = [((i - 1.5) * PITCH, (j - 0.5) * PITCH) for i in range(4) for j in range(2)]
studs = cq.Workplane("XY").workplane(offset=H).pushPoints(pts).circle(STUD_D / 2).extrude(STUD_H)
result = body.union(studs)
"""

_AA = """import cadquery as cq

D, L_TOTAL, BUTTON_D, BUTTON_H = 14.5, 50.5, 5.5, 1.0
body_l = L_TOTAL - BUTTON_H
body = cq.Workplane("YZ").circle(D / 2).extrude(body_l).edges().fillet(0.6)
button = cq.Workplane("YZ").workplane(offset=body_l).circle(BUTTON_D / 2).extrude(BUTTON_H).edges(">X").fillet(0.3)
result = body.union(button).translate((-L_TOTAL / 2, 0, D / 2))
"""

REFERENCE_OBJECTS: dict[str, ReferenceObject] = {
    "id1_card": ReferenceObject(
        key="id1_card",
        title="ID-1 card (bank / ID card)",
        dims=(
            SpecDim("length", 85.60, 85.47, 85.72, "top"),
            SpecDim("width", 53.98, 53.92, 54.03, "top"),
            SpecDim("thickness", 0.76, 0.68, 0.84, "side", "not photographed edge-on; listed for completeness"),
        ),
        loose=False,
        spec_note="ISO/IEC 7810 ID-1: 85.60 × 53.98 × 0.76 mm, corner radius 3.18 mm",
        code=_CARD,
        user_thickness_mm=0.76,
        side_view=False,
        colour_bgr=(120, 62, 28),
    ),
    "sd_card": ReferenceObject(
        key="sd_card",
        title="Full-size SD card",
        dims=(
            SpecDim("length", 32.0, 31.9, 32.1, "top"),
            SpecDim("width", 24.0, 23.9, 24.1, "top"),
            SpecDim("thickness", 2.1, 1.95, 2.25, "side"),
        ),
        loose=False,
        spec_note="full-size SD: 32.0 × 24.0 × 2.1 mm (corner chamfer modelled 4 × 4 mm, not scored)",
        code=_SD,
        user_thickness_mm=2.1,
        side_view=True,
        colour_bgr=(38, 36, 34),
    ),
    "lego_2x4": ReferenceObject(
        key="lego_2x4",
        title="LEGO 2×4 brick",
        dims=(
            SpecDim("length", 31.8, 31.75, 31.85, "top"),
            SpecDim("width", 15.8, 15.75, 15.85, "top"),
            SpecDim("thickness", 11.3, 11.2, 11.4, "side", "side view includes the studs: 9.6 body + 1.7 stud"),
        ),
        loose=False,
        spec_note="LEGO 2×4 brick body 31.8 × 15.8 × 9.6 mm, studs Ø4.8 × 1.7 mm (top-view outline = body)",
        code=_LEGO,
        user_thickness_mm=9.6,
        side_view=True,
        colour_bgr=(30, 40, 200),
    ),
    "aa_cell": ReferenceObject(
        key="aa_cell",
        title="AA cell (lying on its side)",
        dims=(
            SpecDim("length", 50.5, 49.2, 50.5, "top", "loose spec: accepted range 49.2–50.5 mm"),
            SpecDim("width", 14.5, 13.5, 14.5, "top", "loose spec: accepted range 13.5–14.5 mm (diameter)"),
        ),
        loose=True,
        spec_note="AA cell: diameter 13.5–14.5 mm, length 49.2–50.5 mm; modelled at 14.5 × 50.5 mm (loose spec)",
        code=_AA,
        user_thickness_mm=14.5,
        side_view=False,
        colour_bgr=(40, 120, 150),
        accent_bgr=(180, 180, 175),
    ),
}


def list_reference_objects() -> list[ReferenceObject]:
    return list(REFERENCE_OBJECTS.values())


def get_reference_object(key: str) -> ReferenceObject:
    try:
        return REFERENCE_OBJECTS[key]
    except KeyError:
        raise KeyError(f"unknown reference object {key!r} (known: {', '.join(REFERENCE_OBJECTS)})") from None
