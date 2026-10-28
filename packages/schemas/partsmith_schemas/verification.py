"""verification.json: the single source for the Verified badge, README tables and the video (PLAN §6.5)."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from .common import HAUSDORFF_PASS_MM, IOU_PASS, DataOrigin, Source, Strict


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
    changes a compared view's outline (`note` says which views were compared)."""

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
