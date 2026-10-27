"""Isolation for provider tests: no keys, no `.env`, temp PARTSMITH_HOME, fake clients, no sleeping, no network."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from services.agent import providers
from services.agent.providers import clients, mocks, retry

ENV_VARS = (
    "PROVIDER_MODE",
    "PROVIDER_RECORD",
    "OPEN_WEIGHTS_ONLY",
    "PROVIDER_FALLBACK_TO_MOCK",
    "PROVIDER_MAX_RETRIES",
    "PROVIDER_TIMEOUT_S",
    "MODEL_API_KEY",
    "META_API_KEY",
    "META_API_BASE",
    "BASETEN_API_KEY",
    "BASETEN_BASE_URL",
    "SPARK_OPEN_MODEL",
    "FIREWORKS_API_KEY",
    "FIREWORKS_BASE_URL",
    "TOGETHER_API_KEY",
    "TOGETHER_BASE_URL",
    "GLIMMER_BASE_URL",
    "GLIMMER_API_KEY",
    "SAM3_OPEN_URL",
    "SAM3_OPEN_API_KEY",
    "HF_TOKEN",
)


@pytest.fixture(autouse=True)
def isolated(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[None]:
    for name in ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("PARTSMITH_ENV_FILE", str(tmp_path / "no.env"))
    monkeypatch.setenv("PARTSMITH_HOME", str(tmp_path / "home"))
    monkeypatch.setattr(retry, "sleep", lambda s: None)
    providers.reset_state()
    mocks.clear_mocks()

    def no_network(base_url: str, api_key: str, timeout_s: float) -> Any:
        raise AssertionError(f"test tried to build a real client for {base_url}")

    clients.set_client_factory(no_network)
    yield
    providers.reset_state()
    mocks.clear_mocks()


class Obj(dict[str, Any]):
    """Dict that also allows attribute access, like SDK objects."""

    def __getattr__(self, name: str) -> Any:
        try:
            return self[name]
        except KeyError:
            raise AttributeError(name) from None


class FakeHTTPError(Exception):
    def __init__(self, status_code: int, message: str = "boom") -> None:
        super().__init__(message)
        self.status_code = status_code


def responses_stream(text: str, tokens_in: int = 100, tokens_out: int = 20, cached: int = 0) -> list[dict[str, Any]]:
    """A Responses event stream that, like the real API, has content_part.done but no output_text.done."""
    lane = {"item_id": "msg_1", "output_index": 0, "content_index": 0}
    half = len(text) // 2
    return [
        {"type": "response.created"},
        {"type": "response.output_text.delta", **lane, "delta": text[:half]},
        {"type": "response.output_text.delta", **lane, "delta": text[half:]},
        {"type": "response.content_part.done", **lane, "part": {"type": "output_text", "text": text}},
        {
            "type": "response.completed",
            "response": {
                "output": [],
                "usage": {
                    "input_tokens": tokens_in,
                    "output_tokens": tokens_out,
                    "input_tokens_details": {"cached_tokens": cached},
                },
            },
        },
    ]


def chat_stream(text: str, tokens_in: int = 100, tokens_out: int = 20) -> list[Obj]:
    half = len(text) // 2
    return [
        Obj(choices=[Obj(delta=Obj(content=text[:half]))]),
        Obj(choices=[Obj(delta=Obj(content=text[half:], reasoning_content="thinking"))]),
        Obj(choices=[], usage=Obj(prompt_tokens=tokens_in, completion_tokens=tokens_out)),
    ]


Handler = Callable[[dict[str, Any]], Any]


@dataclass
class FakeClient:
    base_url: str
    api_key: str
    hub: FakeHub

    def __post_init__(self) -> None:
        hub = self.hub
        client = self

        class _Responses:
            def create(self, **kw: Any) -> Any:
                hub.calls.append(("responses", client.base_url, kw))
                return hub.handle("responses", client.base_url, kw)

        class _Completions:
            def create(self, **kw: Any) -> Any:
                hub.calls.append(("chat", client.base_url, kw))
                return hub.handle("chat", client.base_url, kw)

        class _Files:
            def create(self, **kw: Any) -> Any:
                hub.calls.append(("files", client.base_url, kw))
                return Obj(id=f"file-{len(hub.calls)}")

        class _Models:
            def list(self) -> Any:
                hub.calls.append(("models", client.base_url, {}))
                return Obj(data=[Obj(id=i) for i in hub.model_ids])

        self.responses = _Responses()
        self.chat = Obj(completions=_Completions())
        self.files = _Files()
        self.models = _Models()


@dataclass
class FakeHub:
    """Collects every SDK call; `handlers[(api, base_url_substring)]` produce replies (callable or list of replies)."""

    handlers: dict[tuple[str, str], Any] = field(default_factory=dict)
    calls: list[tuple[str, str, dict[str, Any]]] = field(default_factory=list)
    keys_seen: list[str] = field(default_factory=list)
    model_ids: list[str] = field(default_factory=lambda: ["meta-models/muse-spark-open"])

    def factory(self, base_url: str, api_key: str, timeout_s: float) -> FakeClient:
        self.keys_seen.append(api_key)
        return FakeClient(base_url, api_key, self)

    def handle(self, api: str, base_url: str, kw: dict[str, Any]) -> Any:
        for (h_api, needle), handler in self.handlers.items():
            if h_api == api and needle in base_url:
                reply = handler
                if isinstance(handler, list):  # a queue of replies; the last one repeats
                    reply = handler.pop(0) if len(handler) > 1 else handler[0]
                if isinstance(reply, Exception):
                    raise reply
                return reply(kw) if callable(reply) else reply
        raise AssertionError(f"no fake handler for {api} at {base_url}")

    def calls_for(self, api: str) -> list[dict[str, Any]]:
        return [kw for a, _, kw in self.calls if a == api]


@pytest.fixture
def hub() -> FakeHub:
    h = FakeHub()
    clients.set_client_factory(h.factory)
    return h


@pytest.fixture
def events() -> list[Any]:
    return []
