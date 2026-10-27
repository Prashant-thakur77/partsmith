"""Every PartSmith model call goes through here.

Public API (the orchestrator, API and media code call only these):
    complete(stage, ModelRequest) -> Completion
    segment(image_png, prompt) -> list[(bool mask, score)]
    generate_image(prompt, reference_images) -> ImageResult
    transcribe(audio, mime, language_hint=None) -> Transcript
    status() -> list[ProviderStatus dict]; overall_mode(); warnings(); stage_mode(stage)
    job_context(job_id, emit, ctx="") -> context manager; every call inside emits a ModelCallEvent
    register_mock(stage, handler) -> plug a deterministic domain mock

Modes: PROVIDER_MODE=live|mock|replay (unset = live where the stage's key exists, mock otherwise).
OPEN_WEIGHTS_ONLY=1 routes every stage to open-weight models. Routing table: `routing.py`.
"""

from __future__ import annotations

from . import chat, clients, config
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
from .config import Mode, reset_warnings
from .core import complete, generate_image, overall_mode, segment, stage_mode, status, transcribe, warnings
from .mocks import clear_mocks, register_mock, unregister_mock
from .routing import STAGES
from .telemetry import JobLedger, job_context


def reset_state() -> None:
    """Forget cached clients, model ids and warnings (tests, or after editing `.env` keys at runtime)."""
    clients.set_client_factory(None)
    clients.set_http_transport(None)
    chat.reset_model_cache()
    reset_warnings()
    config._dotenv_cache.clear()


__all__ = [
    "STAGES",
    "Completion",
    "ImageResult",
    "JobLedger",
    "MockHandler",
    "Mode",
    "ModelRequest",
    "ProviderError",
    "SchemaValidationError",
    "Transcript",
    "Usage",
    "clear_mocks",
    "complete",
    "generate_image",
    "job_context",
    "overall_mode",
    "register_mock",
    "reset_state",
    "segment",
    "stage_mode",
    "status",
    "transcribe",
    "unregister_mock",
    "warnings",
]
