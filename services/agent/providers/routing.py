"""Stage routing table: which model serves which pipeline stage, with fallbacks. The one place to change routing.

| stage            | role             | default chain (first available key wins)                                   | OPEN_WEIGHTS_ONLY=1                |
|------------------|------------------|----------------------------------------------------------------------------|------------------------------------|
| understand       | Understander     | muse-spark-1.3 (Meta API, vision, strict JSON)                              | Glimmer (Modal → Together)         |
| plan, build, fix | Planner/Builder/Fixer | Muse Spark Open: Baseten → Fireworks → Together → muse-spark-1.3      | Spark Open: Baseten → FW → Together |
| fix_agent        | Fixer agent (tools) | Muse Spark Open: Baseten → Fireworks → Together → muse-spark-1.3    | Spark Open: Baseten → FW → Together |
| spec_lookup      | Spec finder      | muse-wonder-1.0 with web_search (citations)                                | none → deterministic mock          |
| judge            | Judge            | Muse Glimmer 30B: llama.cpp on Modal → Together                            | same                               |
| capture_triage   | Capture triage   | Muse Glimmer 30B: llama.cpp on Modal → Together                            | same                               |
| voice_map        | Voice editor     | muse-spark-1.3                                                             | Spark Open                         |
| variant          | Variant mapper   | muse-spark-1.3                                                             | Spark Open                         |
| steer_plan       | Factory planner  | muse-wonder-1.0                                                            | Spark Open                         |
| segment          | Segmenter        | sam-3.1 (Meta API) → SAM 3 open weights on Modal                           | SAM 3 open weights on Modal        |
| segment_points   | Feature cutter   | sam-3.1 point/box prompts                                                  | none → deterministic mock          |
| segment_video    | Orbit tracker    | sam-3.1 video (Files API) → SAM 3.1 multiplex on Modal                     | SAM 3.1 multiplex on Modal         |
| image            | Preview images   | muse-image-1.0 (previews, iterative edits, install cards)                  | none → deterministic mock          |
| reconstruct      | Region completer | muse-image-1.0 (completes the broken region; code keeps the rest)          | none → deterministic mock          |
| transcribe       | Transcriber      | muse-voice-transcribe-1.0 (file endpoint)                                  | none → deterministic mock          |
| transcribe_stream| Live voice       | muse-voice-transcribe-1.0 realtime WebSocket (file endpoint fallback)      | none → deterministic mock          |

A stage whose chain has no configured key runs in mock mode (one warning, shown in `status()`).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from .config import Mode, env, settings, warn_once

Protocol = Literal["responses", "chat", "sam_meta", "sam_open", "image", "voice"]
Kind = Literal["complete", "agent", "search", "segment", "video", "image", "transcribe"]


@dataclass(frozen=True)
class Endpoint:
    name: str  # stable id used in events and pricing: meta, baseten, fireworks, together, modal_glimmer, modal_sam3
    where: str  # human label for /status
    key_env: str | None
    url_env: str | None  # env var holding the base URL (required when there is no default)
    default_base_url: str | None
    open_weights: bool
    key_optional: bool = False  # self-hosted servers: the URL is what matters, the key is an optional guard

    def base_url(self) -> str | None:
        url = (env(self.url_env) if self.url_env else None) or self.default_base_url
        return url.rstrip("/") if url else None

    def key(self) -> str | None:
        return env(self.key_env) if self.key_env else None

    def missing(self) -> list[str]:
        """Env vars that must be set before this endpoint can be called live."""
        out: list[str] = []
        if self.default_base_url is None and self.url_env and not env(self.url_env):
            out.append(self.url_env)
        if self.key_env and not self.key_optional and not env(self.key_env):
            out.append(self.key_env)
        return out

    def ready(self) -> bool:
        return not self.missing()


@dataclass(frozen=True)
class Route:
    endpoint: Endpoint
    model: str
    label: str  # model family shown in the UI
    protocol: Protocol

    @property
    def provider(self) -> str:
        return self.endpoint.name


META = Endpoint("meta", "Meta Model API", "MODEL_API_KEY", "META_API_BASE", "https://api.meta.ai/v1", False)
BASETEN = Endpoint("baseten", "Baseten", "BASETEN_API_KEY", "BASETEN_BASE_URL", "https://inference.baseten.co/v1", True)
FIREWORKS = Endpoint(
    "fireworks", "Fireworks", "FIREWORKS_API_KEY", "FIREWORKS_BASE_URL", "https://api.fireworks.ai/inference/v1", True
)
TOGETHER = Endpoint(
    "together", "Together", "TOGETHER_API_KEY", "TOGETHER_BASE_URL", "https://api.together.xyz/v1", True
)
MODAL_GLIMMER = Endpoint(
    "modal_glimmer", "Modal GPU (llama.cpp, self-hosted)", "GLIMMER_API_KEY", "GLIMMER_BASE_URL", None, True, True
)
MODAL_SAM3 = Endpoint("modal_sam3", "Modal GPU (self-hosted)", "SAM3_OPEN_API_KEY", "SAM3_OPEN_URL", None, True, True)

ENDPOINTS = {e.name: e for e in (META, BASETEN, FIREWORKS, TOGETHER, MODAL_GLIMMER, MODAL_SAM3)}

SPARK_OPEN_DEFAULT_ID = "meta-models/muse-spark-open"

SPARK_13 = Route(META, "muse-spark-1.3", "Muse Spark 1.3", "responses")
WONDER = Route(META, "muse-wonder-1.0", "Muse Wonder", "responses")
SPARK_OPEN_BASETEN = Route(BASETEN, SPARK_OPEN_DEFAULT_ID, "Muse Spark Open", "chat")
SPARK_OPEN_FIREWORKS = Route(FIREWORKS, "accounts/fireworks/models/muse-spark-open", "Muse Spark Open", "chat")
SPARK_OPEN_TOGETHER = Route(TOGETHER, SPARK_OPEN_DEFAULT_ID, "Muse Spark Open", "chat")
GLIMMER_MODAL = Route(MODAL_GLIMMER, "muse-glimmer", "Muse Glimmer 30B (GGUF Q4_K_M)", "chat")
GLIMMER_TOGETHER = Route(TOGETHER, "meta-models/Muse-Glimmer-30B", "Muse Glimmer 30B", "chat")
SAM_31 = Route(META, "sam-3.1", "SAM 3.1", "sam_meta")
SAM_3_OPEN = Route(MODAL_SAM3, "sam3", "SAM 3 (open weights)", "sam_open")
MUSE_IMAGE = Route(META, "muse-image-1.0", "Muse Image", "image")
MUSE_VOICE = Route(META, "muse-voice-transcribe-1.0", "Muse Voice Transcribe", "voice")

SPARK_OPEN_CHAIN = (SPARK_OPEN_BASETEN, SPARK_OPEN_FIREWORKS, SPARK_OPEN_TOGETHER)
GLIMMER_CHAIN = (GLIMMER_MODAL, GLIMMER_TOGETHER)


@dataclass(frozen=True)
class StageSpec:
    stage: str
    role: str
    kind: Kind
    chain: tuple[Route, ...]
    open_chain: tuple[Route, ...]
    default_reasoning: str | None = None  # applied when the request sets none


STAGES: dict[str, StageSpec] = {
    s.stage: s
    for s in (
        StageSpec("understand", "Understander", "complete", (SPARK_13,), GLIMMER_CHAIN),
        StageSpec("plan", "Planner", "complete", (*SPARK_OPEN_CHAIN, SPARK_13), SPARK_OPEN_CHAIN, "medium"),
        StageSpec("build", "Builder", "complete", (*SPARK_OPEN_CHAIN, SPARK_13), SPARK_OPEN_CHAIN, "medium"),
        StageSpec("fix", "Fixer", "complete", (*SPARK_OPEN_CHAIN, SPARK_13), SPARK_OPEN_CHAIN, "medium"),
        StageSpec("fix_agent", "Fixer agent", "agent", (*SPARK_OPEN_CHAIN, SPARK_13), SPARK_OPEN_CHAIN, "medium"),
        StageSpec("spec_lookup", "Spec finder", "search", (WONDER,), (), "medium"),
        StageSpec("judge", "Judge", "complete", GLIMMER_CHAIN, GLIMMER_CHAIN, "medium"),
        StageSpec("capture_triage", "Capture triage", "complete", GLIMMER_CHAIN, GLIMMER_CHAIN, "low"),
        StageSpec("voice_map", "Voice editor", "complete", (SPARK_13,), SPARK_OPEN_CHAIN, "low"),
        StageSpec("variant", "Variant mapper", "complete", (SPARK_13,), SPARK_OPEN_CHAIN, "low"),
        StageSpec("steer_plan", "Factory planner", "complete", (WONDER,), SPARK_OPEN_CHAIN, "medium"),
        StageSpec("segment", "Segmenter", "segment", (SAM_31, SAM_3_OPEN), (SAM_3_OPEN,)),
        StageSpec("segment_points", "Feature cutter", "segment", (SAM_31,), ()),
        StageSpec("segment_video", "Orbit tracker", "video", (SAM_31, SAM_3_OPEN), (SAM_3_OPEN,)),
        StageSpec("image", "Preview images", "image", (MUSE_IMAGE,), ()),
        StageSpec("reconstruct", "Region completer", "image", (MUSE_IMAGE,), ()),
        StageSpec("transcribe", "Transcriber", "transcribe", (MUSE_VOICE,), ()),
        StageSpec("transcribe_stream", "Live voice", "transcribe", (MUSE_VOICE,), ()),
    )
}


def stage_spec(stage: str) -> StageSpec:
    try:
        return STAGES[stage]
    except KeyError:
        raise ValueError(f"unknown provider stage {stage!r}; known: {', '.join(STAGES)}") from None


@dataclass
class Resolution:
    """How a stage will run right now."""

    spec: StageSpec
    mode: Mode
    routes: list[Route]  # live routes to try in order (empty unless mode == "live")
    display: Route | None  # route shown in /status (first live route, else the intended primary)
    missing: list[str] = field(default_factory=list)
    note: str = ""


def chain_for(spec: StageSpec, open_weights_only: bool) -> tuple[Route, ...]:
    return spec.open_chain if open_weights_only else spec.chain


def resolve(stage: str) -> Resolution:
    spec = stage_spec(stage)
    s = settings()
    chain = chain_for(spec, s.open_weights_only)
    primary = chain[0] if chain else None
    if s.mode == "mock":
        return Resolution(spec, "mock", [], primary, note="PROVIDER_MODE=mock → deterministic mock")
    if s.mode == "replay":
        return Resolution(
            spec, "replay", [], primary, note="PROVIDER_MODE=replay → recorded responses (mock if missing)"
        )
    if not chain:
        note = "no open-weight model for this stage → deterministic mock"
        warn_once(f"{stage}: {note} (OPEN_WEIGHTS_ONLY=1)")
        return Resolution(spec, "mock", [], None, note=note)
    ready = [r for r in chain if r.endpoint.ready()]
    missing: list[str] = []
    for r in chain:
        for m in r.endpoint.missing():
            if m not in missing:
                missing.append(m)
    if not ready:
        note = f"{' / '.join(missing)} missing → deterministic mock"
        warn_once(f"provider stage {stage!r}: {note}")
        return Resolution(spec, "mock", [], primary, missing, note)
    note = ""
    if ready[0] is not primary and primary is not None:
        note = f"{' / '.join(primary.endpoint.missing())} missing → {ready[0].endpoint.where} fallback"
    return Resolution(spec, "live", ready, ready[0], missing, note)
