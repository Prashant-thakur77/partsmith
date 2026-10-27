"""Job event stream (SSE + run.jsonl). PLAN §4.4. Every event carries ctx so stale results are discarded."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import Field

from .common import Strict


class _Ev(Strict):
    job: str
    seq: int = 0
    ts: float = 0.0
    ctx: str = ""


class StageEvent(_Ev):
    t: Literal["stage"] = "stage"
    stage: Literal[
        "capture",
        "measure",
        "understand",
        "ask",
        "plan",
        "build",
        "execute",
        "verify",
        "fix",
        "judge",
        "package",
        "learn",
    ]
    status: Literal["start", "ok", "fail", "skip"]
    ms: int | None = None
    label: str = ""  # human-readable progress label
    iter: int | None = None


class MetricEvent(_Ev):
    t: Literal["metric"] = "metric"
    iter: int
    name: str
    value: float
    threshold: float | None = None
    unit: str = "mm"


class ArtifactEvent(_Ev):
    t: Literal["artifact"] = "artifact"
    kind: Literal[
        "photo",
        "rectified",
        "mask_overlay",
        "measure_overlay",
        "render_overlay",
        "residual_heatmap",
        "stl",
        "step",
        "threemf",
        "code",
        "view",
        "verification",
        "template_pdf",
        "preview",
        "repair_card",
        "coupon",
        "partspec",
        "video",
        "feature_mask",
        "reconstruction",
        "install_card",
        "zip",
        "share_card",
    ]
    sha: str
    url: str
    iter: int | None = None
    label: str = ""


class QuestionEvent(_Ev):
    t: Literal["question"] = "question"
    id: str
    text: str
    expects: Literal["number_mm", "choice", "text"] = "number_mm"
    default: str | float | None = None
    choices: list[str] | None = None


class AnswerEvent(_Ev):
    t: Literal["answer"] = "answer"
    id: str
    value: str | float
    via: Literal["text", "voice"] = "text"


class ModelCallEvent(_Ev):
    t: Literal["model_call"] = "model_call"
    provider: str
    model: str
    stage: str
    mode: Literal["live", "mock", "replay"]
    tokens_in: int = 0
    tokens_out: int = 0
    ms: int = 0
    usd: float = 0.0
    ok: bool = True
    error: str | None = None


class IterationEvent(_Ev):
    t: Literal["iteration"] = "iteration"
    iter: int
    strategy: Literal["template", "free_code", "human"]
    edits: list[dict[str, Any]] = Field(default_factory=list)
    analysis: str = ""
    code_sha: str | None = None
    diff: str = ""
    hausdorff_mm: float | None = None
    iou: float | None = None
    passed_tests: int = 0
    total_tests: int = 0


class ThoughtEvent(_Ev):
    """A model's reasoning summary (never raw chain of thought), shown in the trace."""

    t: Literal["thought"] = "thought"
    stage: str
    model: str = ""
    text: str
    iter: int | None = None
    mode: Literal["live", "mock", "replay"] | None = None  # mock = a deterministic policy wrote it, no model ran


class ToolCallEvent(_Ev):
    """One tool call made by an agentic model stage; the result summary is what code returned."""

    t: Literal["tool_call"] = "tool_call"
    stage: str
    name: str
    args: dict[str, Any] = Field(default_factory=dict)
    result: str = ""
    ok: bool = True
    ms: int = 0
    iter: int | None = None
    mode: Literal["live", "mock", "replay"] | None = None  # mode of the turn that asked for the call


class FocusEvent(_Ev):
    """The agent points the viewer at a feature or location (part frame, mm)."""

    t: Literal["focus"] = "focus"
    feature: str = ""
    view: str = "top"
    at_mm: tuple[float, float, float] | None = None
    label: str = ""
    iter: int | None = None


class LogEvent(_Ev):
    t: Literal["log"] = "log"
    level: Literal["info", "warn", "error"] = "info"
    msg: str


class DoneEvent(_Ev):
    t: Literal["done"] = "done"
    verified: bool
    status: Literal["verified", "best_effort", "failed", "refused", "cancelled"]
    summary: dict[str, Any] = Field(default_factory=dict)


Event = Annotated[
    StageEvent
    | MetricEvent
    | ArtifactEvent
    | QuestionEvent
    | AnswerEvent
    | ModelCallEvent
    | IterationEvent
    | LogEvent
    | ThoughtEvent
    | ToolCallEvent
    | FocusEvent
    | DoneEvent,
    Field(discriminator="t"),
]
