"""Jobs, registry parts, bakes and variants (PLAN §4.3, §8.3)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from .common import DataOrigin, Strict
from .partspec import Family
from .verification import ParamSpec, Verification

JobKind = Literal["fix", "steer", "bake", "variant", "fit_check"]
JobStatus = Literal["queued", "running", "waiting_for_answer", "done", "failed", "cancelled"]
ProviderMode = Literal["live", "mock", "replay"]
JobPurpose = Literal["repair", "reference_check"]


class HiddenDim(Strict):
    """A size the photo cannot show (inner bore Ø, socket depth …), stated by the user: name + millimetres. Never
    observed, so never part of `verified`; see services/agent/hidden_dims.py."""

    name: str = Field(min_length=1, max_length=40)  # a named kind ("bore_d", "socket_depth" …) or the user's words
    value_mm: float = Field(gt=0, le=2000)


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
    city: str | None = None  # optional: lets the buy-or-print card look for nearby print shops and repair cafés
    # "reference_check": a measurement check of a known object (bundled reference samples, benches). Set only by
    # server code (start_demo_job / eval), never from a public request; nothing is meant to be printed.
    purpose: JobPurpose = "repair"
    # A reviewer round: the job a person reviewed and sent back with notes (server-set by the review page; the round
    # starts from that job's model). 0 / None for every other job.
    parent_job: str | None = None
    review_round: int = 0
    # Sizes the photo cannot show, stated by the user (at most 4): used by the builder, checked against the program
    # where a knob holds them, never part of `verified`.
    hidden_dims: list[HiddenDim] = Field(default_factory=list, max_length=4)


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


# ---- repair passport (services/registry/passport.py, docs/API.md "Repair passport") --------------------------------


class PassportCheck(Strict):
    """One re-measurement after the passport id was debossed (before / after; any change undoes the mark)."""

    name: str
    passed: bool
    before: Any = None
    after: Any = None


class PassportMark(Strict):
    """What happened when a bake asked for `passport=1`. Code decides; `applied` is false whenever no safe face
    existed or a re-measurement changed."""

    text: str
    applied: bool
    reason: str
    style: Literal["deboss"] = "deboss"
    depth_mm: float | None = None
    text_height_mm: float | None = None
    font: str = ""
    face: dict[str, Any] | None = None  # {"z_mm", "area_mm2", "normal"}
    box_mm: dict[str, float] | None = None  # {"cx", "cy", "w", "h", "angle_deg"}
    free_needed_mm: list[float] | None = None  # [long side, short side]
    removed_mm3: float | None = None
    checks: list[PassportCheck] = Field(default_factory=list)


class PassportPreset(Strict):
    id: str
    title: str
    source: Literal["job_spec", "default"]  # the job's stated material + printer, or the PLA 0.4 mm default
    delta_mm: float


class PassportShip(Strict):
    status: Literal["verified", "best_effort", "blocked"]
    reason: str
    needs_ack: bool
    source: str


class PassportLink(Strict):
    """The passport id as shown on a part page or a job (copy link, QR downloads)."""

    id: str
    url: str  # web path "/p/{id}"
    qr_svg_url: str
    qr_png_url: str


class Passport(Strict):
    """`GET /passport/{id}`: what a printed passport id points at, and how to reprint it."""

    id: str
    kind: Literal["part", "job"]
    url: str  # "/p/{id}"
    title: str
    family: Family
    slug: str | None = None
    version: int | None = None  # the part version this id was issued for
    current_version: int | None = None
    superseded: bool = False  # issued for an older version of the same geometry (same program + values)
    job_id: str | None = None
    job_status: JobStatus | None = None
    published: bool
    values: dict[str, float]  # knob values the passport stands for
    preset: PassportPreset
    status: Literal["verified", "best_effort", "failed", "unknown"]
    verified: bool
    max_error_mm: float | None = None
    threshold_mm: float | None = None
    ship: PassportShip
    origin: DataOrigin
    page_url: str  # "/parts/{slug}" or "/jobs/{id}"
    bake_url: str  # API bake route (BakeResult); add format/preset/fit_session/download/ack/passport
    presets_url: str
    qr_svg_url: str
    qr_png_url: str
    fix_url: str  # "/fix?family=…&intent=…" for "it broke in a new place"
    notes: list[str] = Field(default_factory=list)
