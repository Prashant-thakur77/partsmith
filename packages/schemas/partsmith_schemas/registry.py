"""Jobs, registry parts, bakes and variants (PLAN §4.3, §8.3)."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from .common import DataOrigin, Strict
from .partspec import Family
from .verification import ParamSpec, Verification

JobKind = Literal["fix", "steer", "bake", "variant", "fit_check"]
JobStatus = Literal["queued", "running", "waiting_for_answer", "done", "failed", "cancelled"]
ProviderMode = Literal["live", "mock", "replay"]


class JobInput(Strict):
    kind: JobKind = "fix"
    intent: str = ""
    photo_shas: dict[str, str] = Field(default_factory=dict)  # view -> sha
    mat_kind: Literal["screen", "paper"] = "screen"
    screen_px_per_mm: float | None = None
    thickness_mm: float | None = None  # user-stated, optional
    family_hint: Family | None = None
    origin: DataOrigin = DataOrigin.real
    max_iters: int = 6
    budget_usd: float = 0.5
    provider_mode: ProviderMode | None = None


class JobSummary(Strict):
    id: str
    kind: JobKind
    status: JobStatus
    created_at: float
    updated_at: float
    title: str = ""
    origin: DataOrigin = DataOrigin.real
    provider_mode: ProviderMode = "mock"
    verified: bool = False
    max_error_mm: float | None = None
    iterations: int = 0
    cost_usd: float = 0.0
    part_slug: str | None = None
    is_replay: bool = False


class Provenance(Strict):
    origin: DataOrigin
    job_id: str | None = None
    photo_shas: list[str] = Field(default_factory=list)
    builder_model: str | None = None
    provider_mode: ProviderMode = "mock"
    created_by: str = "partsmith"
    forked_from: str | None = None
    note: str = ""


class PartFacts(Strict):
    bbox_mm: tuple[float, float, float]
    volume_mm3: float
    mass_g_pla: float
    mass_g_petg: float
    print_minutes_est: float
    supports_needed: bool
    orientation: str


class PartRecord(Strict):
    id: str
    slug: str
    title: str
    family: Family
    summary: str = ""
    tags: list[str] = Field(default_factory=list)
    version: int = 1
    status: Literal["draft", "verified", "best_effort", "published"]
    params: list[ParamSpec]
    defaults: dict[str, float]
    code: str
    code_sha: str
    verification: Verification | None = None
    provenance: Provenance
    facts: PartFacts | None = None
    licence: str = "CC-BY-4.0"
    created_at: float = 0.0
    mating: list[str] = Field(default_factory=list)  # slugs of parts that share an interface


class BakeResult(Strict):
    cache_key: str
    part_slug: str
    version: int
    params: dict[str, float]
    clamped: dict[str, float] = Field(default_factory=dict)  # params changed to respect ranges
    artifacts: dict[str, str]  # format -> url
    facts: PartFacts | None = None
    cache_hit: bool
    ms: int


class VariantResult(Strict):
    params: dict[str, float]
    applied: list[str]
    not_applied: list[str]
    confidence: float
    mode: ProviderMode


class Need(Strict):
    id: str
    query: str
    votes: int = 1
    status: Literal["open", "in_progress", "fulfilled"] = "open"
    created_at: float = 0.0
