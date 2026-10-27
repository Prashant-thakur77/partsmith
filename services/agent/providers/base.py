"""Request/response types shared by every provider adapter."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from .config import Mode


@dataclass
class ModelRequest:
    """One model call. Messages are `{"role": "system"|"developer"|"user"|"assistant", "content": str}`.

    `images` are raw bytes (PNG/JPEG/WebP) attached to the user message at `images_at` (default: the last user
    message). `json_schema` asks for strict JSON; the reply is parsed and validated (one repair retry).
    `mock_context` is never sent to a model and is excluded from the replay hash: it carries structured inputs for
    deterministic mock handlers.
    """

    messages: list[dict[str, str]]
    images: list[bytes] = field(default_factory=list)
    images_at: int | None = None
    image_labels: list[str] = field(default_factory=list)  # optional caption per image ("crop around hole_1")
    json_schema: dict[str, Any] | None = None
    schema_name: str = "result"
    strict: bool = True
    temperature: float | None = None
    max_tokens: int | None = None
    reasoning_effort: str | None = None
    tools: list[dict[str, Any]] | None = None
    stream: bool | None = None  # None = provider default (stream text calls to avoid gateway timeouts)
    timeout_s: float | None = None
    mock_context: dict[str, Any] = field(default_factory=dict)

    def image_message_index(self) -> int | None:
        if not self.images:
            return None
        if self.images_at is not None:
            return self.images_at
        for i in range(len(self.messages) - 1, -1, -1):
            if self.messages[i].get("role") == "user":
                return i
        return None


@dataclass
class Usage:
    tokens_in: int = 0
    tokens_out: int = 0
    cached_in: int = 0
    reasoning_tokens: int = 0

    def __add__(self, other: Usage) -> Usage:
        return Usage(
            self.tokens_in + other.tokens_in,
            self.tokens_out + other.tokens_out,
            self.cached_in + other.cached_in,
            self.reasoning_tokens + other.reasoning_tokens,
        )

    def to_dict(self) -> dict[str, int]:
        return {
            "tokens_in": self.tokens_in,
            "tokens_out": self.tokens_out,
            "cached_in": self.cached_in,
            "reasoning_tokens": self.reasoning_tokens,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any] | None) -> Usage:
        d = d or {}
        return cls(
            int(d.get("tokens_in", 0)),
            int(d.get("tokens_out", 0)),
            int(d.get("cached_in", 0)),
            int(d.get("reasoning_tokens", 0)),
        )


@dataclass
class Completion:
    text: str
    json: Any  # parsed + validated JSON when a schema was given, else None
    usage: Usage
    ms: int
    usd: float
    provider: str
    model: str
    mode: Mode
    stage: str
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    request_hash: str = ""
    note: str = ""

    @property
    def tokens_in(self) -> int:
        return self.usage.tokens_in

    @property
    def tokens_out(self) -> int:
        return self.usage.tokens_out


@dataclass
class ImageResult:
    data: bytes
    mime: str
    mode: Mode
    provider: str = ""
    model: str = ""
    usd: float = 0.0
    ms: int = 0
    note: str = ""
    response_id: str = ""  # set when the call was stored (store=True) so `edit_image` can continue from it


@dataclass
class Transcript:
    text: str
    mode: Mode
    provider: str = ""
    model: str = ""
    duration_ms: int | None = None
    usd: float = 0.0
    ms: int = 0
    language_hint: str | None = None
    note: str = ""


@dataclass
class LiveText:
    """What a text adapter returns before schema checks and pricing."""

    text: str
    usage: Usage
    model: str
    tool_calls: list[dict[str, Any]] = field(default_factory=list)


class ProviderError(RuntimeError):
    """A model call failed. Messages are redacted; `retryable` marks 429/5xx/timeouts."""

    def __init__(
        self,
        message: str,
        *,
        provider: str = "",
        status: int | None = None,
        retryable: bool = False,
        stage: str = "",
    ) -> None:
        super().__init__(message)
        self.provider = provider
        self.status = status
        self.retryable = retryable
        self.stage = stage
        self.usage = Usage()  # tokens already spent before the failure (e.g. a failed schema repair)


class SchemaValidationError(ProviderError):
    """The model's reply did not match the requested JSON schema, even after one repair retry."""

    def __init__(self, message: str, *, text: str, errors: list[str], provider: str = "", stage: str = "") -> None:
        super().__init__(message, provider=provider, stage=stage)
        self.text = text
        self.errors = errors


MockHandler = Callable[..., Any]
"""Deterministic stand-in for a stage. Agent stages get `(req, history)` and return {"tool", "args"} or {"final"}. Text stages return a dict (JSON answer) or str; `transcribe` returns str;
`segment` returns `list[(bool mask, score)]`; `image` returns PNG bytes."""
