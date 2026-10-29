"""verification.json: the single source for the Verified badge, README tables and the video (PLAN §6.5)."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from .common import HAUSDORFF_PASS_MM, IOU_PASS, DataOrigin, Source, Strict
from .measurement import CaptureReport, MateKind, MateMeasurement


class ParamSpec(Strict):
    """One knob in a part program's PARAMS block: name: (default, min, max, step, unit, affects_fit, label)."""

    name: str
    default: float
    min: float
    max: float
    step: float
    unit: Literal["mm", "deg", ""] = "mm"
    affects_fit: bool = True
    label: str = ""
    topology: bool = False  # integer knob that changes topology (rib_count, hole_count)


class ViewMetrics(Strict):
    view: str
    iou: float
    hausdorff_mm: float
    hd95_mm: float
    mean_mm: float
    worst_point_mm: tuple[float, float] | None = None
    over_area_mm2: float = 0.0  # model has material the photo lacks
    under_area_mm2: float = 0.0  # photo has material the model lacks


class FeatureResidual(Strict):
    feature_id: str
    quantity: str  # "diameter", "center_x", "length", ...
    measured_mm: float
    model_mm: float
    delta_mm: float  # model - measured
    tol_mm: float
    passed: bool


class PartTest(Strict):
    id: str
    description: str
    value: float | None
    expected: float | None
    tol: float | None
    passed: bool
    priority: Literal["P0", "P1"] = "P0"


class Validity(Strict):
    is_valid: bool
    single_solid: bool
    watertight: bool
    volume_mm3: float
    bbox_mm: tuple[float, float, float]
    min_wall_mm: float | None = None
    issues: list[str] = Field(default_factory=list)


class JudgeVeto(Strict):
    feature: str
    issue: str
    severity: Literal["blocking", "minor"]


class Thresholds(Strict):
    hausdorff_mm: float = HAUSDORFF_PASS_MM
    iou: float = IOU_PASS


class UncheckedValue(Strict):
    """A dimension of the final model (a PARAMS knob) that no measured or user-stated value was tested against.

    It comes from the program (a template default or a value inferred from the measured ones), so it is labelled
    inferred and NOT verified, whatever the part's status. The silhouette comparison only covers it as far as it
    changes a compared view's outline (`note` says which views were compared). A dimension the user stated because the
    photo cannot show it (the original length of a broken part) is listed with source `user_stated`: stated, not
    observed, so it is NOT verified either."""

    param: str
    label: str = ""
    value: float
    unit: Literal["mm", "deg", ""] = "mm"
    source: Source = Source.inferred
    note: str = ""


class Verification(Strict):
    verified: bool
    status: Literal["verified", "best_effort", "failed"]
    reasons: list[str] = Field(default_factory=list)  # why it did or did not pass, plain words
    thresholds: Thresholds = Field(default_factory=Thresholds)
    views: list[ViewMetrics] = Field(default_factory=list)
    residuals: list[FeatureResidual] = Field(default_factory=list)
    tests: list[PartTest] = Field(default_factory=list)
    validity: Validity | None = None
    vetoes: list[JudgeVeto] = Field(default_factory=list)
    max_error_mm: float | None = None
    # Knobs no test checked: inferred, never verified (filled when the job's final verdict is written).
    unchecked: list[UncheckedValue] = Field(default_factory=list)
    origin: DataOrigin = DataOrigin.real
    versions: dict[str, str] = Field(default_factory=dict)
    hashes: dict[str, str] = Field(default_factory=dict)
    ms: int = 0


FitClass = Literal["does not fit", "press fit", "sliding fit", "loose fit", "very loose"]


class PrintedFit(Strict):
    """The same fit after printing on one printer + material preset. Internal fits (a hole or gap in the model)
    print about the preset's clearance small on FDM; outer sizes print as modelled and no preset changes them."""

    preset: str
    title: str
    clearance_in_effect_mm: float  # what the preset (or the device's coupon learning) says internal fits lose
    clearance_source: Literal["learned", "preset"]
    clearance_label: str = ""
    internal: bool  # the model side is a hole or gap (it prints undersize), not an outer size
    clearance_mm: float  # printed as exported (no preset applied)
    fit: FitClass
    with_preset_clearance_mm: float | None = None  # with the preset applied at export (opens internal fit knobs)
    with_preset_fit: FitClass | None = None
    text: str


class MateFit(Strict):
    """One measured mate against the model's matching feature. Informational: it never sets `verified`."""

    mate_id: str
    mate_kind: MateKind
    model_feature: str = ""  # e.g. "shaft bore (interface shaft_bore)", "hole_1", "outer width across the footprint"
    model_feature_source: Literal["interface", "nearest_hole", "outer_size", "plate_thickness", "none"] = "none"
    model_feature_note: str = ""  # how the model feature was chosen, in plain words
    model_mm: float | None = None  # measured on the CAD solid (ray casts / B-rep features)
    mate_mm: float | None = None
    mate_sigma_mm: float | None = None
    clearance_mm: float | None = None  # diametral: gap minus what goes into it
    clearance_sigma_mm: float | None = None
    fit: FitClass | None = None
    fit_low: FitClass | None = None  # the class at clearance − σ
    fit_high: FitClass | None = None  # the class at clearance + σ
    passed: bool = False
    printed: PrintedFit | None = None
    text: str = ""


class MateFitResult(Strict):
    """mate_fit.json: the mating photo's measured mates and how the model fits them (code only)."""

    view: Literal["mating"] = "mating"
    capture: CaptureReport | None = None
    mates: list[MateMeasurement] = Field(default_factory=list)
    fits: list[MateFit] = Field(default_factory=list)
    preset: str | None = None
    notes: list[str] = Field(default_factory=list)
    origin: DataOrigin = DataOrigin.real
