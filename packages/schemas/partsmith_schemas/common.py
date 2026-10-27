"""Shared primitives. Units are millimetres everywhere; angles carry a _deg suffix."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=False, populate_by_name=True)


class Source(StrEnum):
    """Where a value came from. Shown on every number in the UI and exports."""

    measured = "measured"
    user_stated = "user_stated"
    inferred = "inferred"
    cited = "cited"  # found by a model with web search; carries a citation; never overrides a measured value


class DataOrigin(StrEnum):
    """Provenance of an input or run. Synthetic and mock data are always labelled as such."""

    real = "real"
    synthetic = "synthetic"
    reference_object = "reference_object"
    replay = "replay"


class GroundTruthSource(StrEnum):
    """What a bench error is measured against. Never conflate these in a report."""

    synthetic_exact = "synthetic_exact"
    reference_spec = "reference_spec"
    ruler = "ruler"
    caliper = "caliper"
    expected_outcome = "expected_outcome"
    """The expected refusal/accept outcome of a gate case (control and red-team suites), not a mm value."""


class Citation(Strict):
    url: str
    title: str = ""
    quote: str = ""


class Evidence(Strict):
    view: str | None = None
    pixels: list[list[float]] | None = None
    note: str | None = None
    citation: Citation | None = None


class Measured(Strict):
    value: float
    source: Source = Source.measured
    sigma_mm: float = Field(0.0, ge=0)
    evidence: Evidence | None = None


Point2 = tuple[float, float]
Json = dict[str, Any]

# Pass rule thresholds (PLAN §6.5). Code is the only authority for "verified".
HAUSDORFF_PASS_MM = 0.5
IOU_PASS = 0.97
FEATURE_TOL_MM = 0.15
BBOX_TOL_MM = 0.3
MIN_WALL_MM = 0.8
