"""Calibration, capture gate and photo measurements."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import Field

from .common import DataOrigin, Measured, Point2, Source, Strict


class MatKind(StrEnum):
    screen = "screen"
    paper = "paper"


class ViewKind(StrEnum):
    top = "top"
    side = "side"
    mating = "mating"
    fit_check = "fit_check"


class CaptureCheck(Strict):
    name: Literal[
        "markers", "reprojection", "blur", "coverage", "tilt", "exposure", "glare", "moire", "scale", "contrast"
    ]
    passed: bool
    severity: Literal["ok", "warn", "fail"]
    value: float | None = None
    threshold: float | None = None
    reason: str


class CaptureReport(Strict):
    passed: bool
    checks: list[CaptureCheck]
    retake_reason: str | None = None


class CameraPose(Strict):
    K: list[list[float]]
    dist: list[float] = Field(default_factory=list)
    R: list[list[float]]
    t_mm: list[float]
    camera_height_mm: float
    tilt_deg: float
    intrinsics_source: Literal["calibrated", "exif", "estimated", "synthetic"]


class Calibration(Strict):
    mat_id: str
    mat_kind: MatKind
    markers_found: int
    homography: list[list[float]]  # image px -> mat mm (plane z=0)
    reproj_error_px: float
    reproj_error_mm: float
    rectified_px_per_mm: float
    rectified_origin_mm: tuple[float, float] = (0.0, 0.0)  # mat-frame mm of the rectified image's top-left pixel
    scale_correction: float = 1.0  # screen card calibration or paper 50 mm ruler correction factor
    pose: CameraPose | None = None


class Hole(Strict):
    id: str
    center_mm: Point2
    diameter: Measured
    roundness_mm: float = 0.0


class Slot(Strict):
    id: str
    center_mm: Point2
    length: Measured
    width: Measured
    angle_deg: float


class Measurements(Strict):
    """Everything the metrology stage measured from one view, in the PART frame
    (centre of min-area rect, long side +X, Y up), millimetres."""

    view: ViewKind
    origin: DataOrigin
    outline_mm: list[Point2]
    holes: list[Hole] = Field(default_factory=list)
    slots: list[Slot] = Field(default_factory=list)
    length: Measured
    width: Measured
    thickness: Measured | None = None
    area_mm2: float
    symmetry_axis_deg: float | None = None
    symmetry_score: float | None = None
    height_correction_scale: float = 1.0
    part_to_mat: list[list[float]] = Field(default_factory=list)  # 3x3 affine, part frame -> mat frame (mm)
    mask_source: Literal["sam-3.1", "sam3-open", "threshold", "mock-threshold", "synthetic-gt"] = "threshold"
    mask_confidence: float | None = None
    notes: list[str] = Field(default_factory=list)


class FitCheckResult(Strict):
    """Screen fit check: the real part photographed lying on the model's 1:1 outline (docs/API.md)."""

    passed: bool
    iou: float
    hausdorff_mm: float
    mean_mm: float
    reasons: list[str] = Field(default_factory=list)
    overlay_url: str = ""
    capture: CaptureReport


class MeasureResult(Strict):
    capture: CaptureReport
    calibration: Calibration | None = None
    measurements: Measurements | None = None
    overlay_sha: str | None = None
    rectified_sha: str | None = None
    mask_sha: str | None = None


__all__ = [
    "Calibration",
    "CameraPose",
    "CaptureCheck",
    "CaptureReport",
    "FitCheckResult",
    "Hole",
    "MatKind",
    "MeasureResult",
    "Measured",
    "Measurements",
    "Slot",
    "Source",
    "ViewKind",
]
