"""Every PartSmith model call goes through here. See README.md in this folder for the full guide.

Public API (the orchestrator, API, metrology and media code call only these):
    complete(stage, ModelRequest) -> Completion
    run_agent(stage, ModelRequest, tools, call_tool, *, max_turns=12) -> AgentResult        # tool loop
    segment(image_png, prompt) -> list[(bool mask, score)]                                   # SAM 3.1 text prompt
    segment_points(image_png, points_pos, points_neg=(), box=None) -> list[(mask, score)]    # SAM 3.1 points/box
    segment_video(video_bytes, mime, prompt, *, fps=5) -> list[FrameMask]                    # SAM 3.1 video
    lookup_spec(query, want, *, fixture=None) -> SpecLookup                                  # Wonder + web search
    buy_lookup(query, *, city=None, fixture=None) -> BuyResult                               # buy-or-print, cited only
    narrate_video(video, mime, *, width, height, duration_s, intent, voice_note) -> Narration  # Spark video+audio
    generate_image(prompt, reference_images, *, editable=False) -> ImageResult               # Muse Image
    reconstruct(rectified_png, keep_mask_png, instruction="") -> ImageResult
    edit_image(previous_id, instruction) -> ImageResult
    install_card(photo_png, render_png, steps) -> list[ImageResult]
    transcribe(audio, mime, language_hint=None) -> Transcript                                # Voice, file
    transcribe_stream(chunks, *, keywords=(), language_bias=("English", "Hindi")) -> Iterator[VoiceEvent]
    status() / overall_mode() / warnings() / stage_mode(stage) / open_weights_summary(events=None)
    job_context(job_id, emit, ctx="") -> every call inside emits model_call (+ thought / tool_call) events
    register_mock(stage, handler) -> plug a deterministic domain mock

Modes: PROVIDER_MODE=live|mock|replay (unset = live where the stage's key exists, mock otherwise).
OPEN_WEIGHTS_ONLY=1 routes every stage to open-weight models. Routing table: `routing.py`.
"""

from __future__ import annotations

from . import chat, clients, config, mocks, telemetry
from .agent import AgentResult, ToolResult, ToolSpec, run_agent
from .base import (
    Completion,
    ImageResult,
    MockHandler,
    ModelRequest,
    ProviderError,
    SchemaValidationError,
    Transcript,
    Usage,
)
from .buy import BuyResult, buy_lookup
from .config import Mode, reset_warnings
from .core import (
    complete,
    generate_image,
    open_weights_summary,
    overall_mode,
    segment,
    stage_mode,
    status,
    transcribe,
    warnings,
)
from .image_ops import edit_image, install_card, reconstruct
from .mocks import clear_mocks, register_mock, unregister_mock
from .narrate import Narration, narrate_video
from .realtime import VoiceEvent, transcribe_stream
from .routing import STAGES
from .spec import SpecLookup, lookup_spec
from .telemetry import JobLedger, job_context
from .vision import FrameMask, segment_points, segment_video


def reset_state() -> None:
    """Forget cached clients, model ids and warnings (tests, or after editing `.env` keys at runtime)."""
    clients.set_client_factory(None)
    clients.set_http_transport(None)
    clients.set_ws_connect(None)
    chat.reset_model_cache()
    reset_warnings()
    config._dotenv_cache.clear()
    mocks._mock_images.clear()


__all__ = [
    "STAGES",
    "AgentResult",
    "BuyResult",
    "Completion",
    "FrameMask",
    "ImageResult",
    "JobLedger",
    "MockHandler",
    "Mode",
    "ModelRequest",
    "Narration",
    "ProviderError",
    "SchemaValidationError",
    "SpecLookup",
    "ToolResult",
    "ToolSpec",
    "Transcript",
    "Usage",
    "VoiceEvent",
    "buy_lookup",
    "clear_mocks",
    "complete",
    "edit_image",
    "generate_image",
    "install_card",
    "job_context",
    "lookup_spec",
    "narrate_video",
    "open_weights_summary",
    "overall_mode",
    "reconstruct",
    "register_mock",
    "reset_state",
    "run_agent",
    "segment",
    "segment_points",
    "segment_video",
    "stage_mode",
    "status",
    "telemetry",
    "transcribe",
    "transcribe_stream",
    "unregister_mock",
    "warnings",
]
