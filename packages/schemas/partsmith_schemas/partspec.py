"""PartSpec: the typed contract between understand -> plan -> build -> verify."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field

from .common import Measured, Point2, Source, Strict


class Family(StrEnum):
    clip = "clip"
    knob = "knob"
    bracket = "bracket"
    hook = "hook"
    spacer = "spacer"
    cover = "cover"
    wheel = "wheel"
    latch = "latch"
    gear = "gear"
    cable_clip = "cable_clip"
    hinge = "hinge"
    custom = "custom"


class BaseProfile(Strict):
    kind: Literal["polyline", "spline", "circle", "rect"]
    points_mm: list[Point2]
    source: Source = Source.measured
    sigma_mm: float = 0.0


class ThroughHole(Strict):
    kind: Literal["through_hole"] = "through_hole"
    id: str
    center_mm: Point2
    diameter: Measured
    countersink: bool = False


class BlindHole(Strict):
    kind: Literal["blind_hole"] = "blind_hole"
    id: str
    center_mm: Point2
    diameter: Measured
    depth: Measured


class SlotFeature(Strict):
    kind: Literal["slot"] = "slot"
    id: str
    center_mm: Point2
    length: Measured
    width: Measured
    angle_deg: float = 0.0


class Boss(Strict):
    kind: Literal["boss"] = "boss"
    id: str
    center_mm: Point2
    outer_d: Measured
    inner_d: Measured | None = None
    height: Measured


class Rib(Strict):
    kind: Literal["rib"] = "rib"
    id: str
    from_mm: Point2
    to_mm: Point2
    width: Measured
    height: Measured


class SnapHook(Strict):
    kind: Literal["snap_hook"] = "snap_hook"
    id: str
    anchor: str
    overhang: Measured
    angle_deg: float
    thickness: Measured
    note: str | None = None


class DShaftBore(Strict):
    kind: Literal["d_shaft_bore"] = "d_shaft_bore"
    id: str
    diameter: Measured
    flat_depth: Measured


class FilletAll(Strict):
    kind: Literal["fillet_all"] = "fillet_all"
    id: str
    radius: Measured


Feature = Annotated[
    ThroughHole | BlindHole | SlotFeature | Boss | Rib | SnapHook | DShaftBore | FilletAll,
    Field(discriminator="kind"),
]


class BrokenRegion(Strict):
    """Where the part is broken. ``kind="outline"``: a piece of the top-view outline is missing (``polygon_mm`` is the
    completed outline or the missing patch, part frame). ``kind="height"``: the top of the part is missing, so the side
    photo shows it shorter than it was; code takes the break height from the side measurement and leaves everything
    above it out of the side and walk-around comparisons (``polygon_mm`` stays empty)."""

    polygon_mm: list[Point2]
    strategy: Literal["mirror", "mating_part", "template", "user"]
    kind: Literal["outline", "height"] = "outline"
    note: str | None = None


class Fit(Strict):
    clearance_mm: float = 0.2
    material: Literal["PLA", "PETG", "ABS", "ASA", "TPU"] = "PLA"
    printer: Literal["FDM_0_4", "FDM_0_6", "SLA"] = "FDM_0_4"


class Unknown(Strict):
    id: str
    question: str
    expects: Literal["number_mm", "choice", "text"] = "number_mm"
    default: str | float | None = None
    choices: list[str] | None = None


class PartSpec(Strict):
    family: Family
    units: Literal["mm"] = "mm"
    title: str = ""
    base_profile: BaseProfile
    thickness: Measured
    features: list[Feature] = Field(default_factory=list)
    broken_region: BrokenRegion | None = None
    fit: Fit = Field(default_factory=Fit)
    unknowns: list[Unknown] = Field(default_factory=list)
    intent: str = ""
    refusal: str | None = None  # set when the object is not a printable rigid part or is a refused class
    template_hint: str | None = None
