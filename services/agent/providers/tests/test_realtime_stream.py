"""Realtime voice mock pacing: events are released while audio is still arriving (a browser sees partials as the
user talks), the rest when the upload ends; an empty upload hears nothing."""

from __future__ import annotations

import json
import time
from collections.abc import Generator, Iterator
from typing import Any, cast

import pytest

from services.agent import providers
from services.agent.providers import ModelRequest, mocks, realtime

QUARTER_S = b"\0\0" * 4000  # 0.25 s of 16 kHz s16le mono


def test_mock_releases_events_as_audio_arrives() -> None:
    log: list[str] = []

    def mic() -> Iterator[bytes]:
        for i in range(3):
            log.append(f"chunk{i}")
            yield QUARTER_S

    for ev in providers.transcribe_stream(mic(), mock_text="hook ko 1 mm mota karo", pace=False):
        log.append(f"{ev.kind}:{ev.text}")
    # one event per 0.25 s received, interleaved with the upload, then the rest flushed at the end
    assert log[:6] == ["chunk0", "speech_start:", "chunk1", "partial:hook", "chunk2", "partial:hook ko"]
    assert log[-2:] == ["final:hook ko 1 mm mota karo", "speech_end:"]


def test_mock_hears_nothing_without_audio() -> None:
    assert list(providers.transcribe_stream(iter(()), mock_text="hook ko 1 mm mota karo")) == []


def test_registered_mock_gets_the_clip_size_and_mode_is_mock() -> None:
    sizes: list[int] = []

    def handler(req: ModelRequest) -> str:
        sizes.append(int(req.mock_context["audio_bytes"]))
        return "dedh mm patla"

    mocks.register_mock("transcribe_stream", handler)
    events = list(providers.transcribe_stream([QUARTER_S, QUARTER_S], pace=False))
    assert sizes == [2 * len(QUARTER_S)] and [e.text for e in events if e.kind == "final"] == ["dedh mm patla"]
    assert realtime.mode() == "mock"


class _ScriptedWS:
    """Minimal live socket: acks, sends the scripted frames, then fails or closes."""

    def __init__(self, frames: list[dict[str, object]], fail: bool) -> None:
        self.frames = frames
        self.fail = fail
        self.acked = False

    def send(self, message: object) -> None:
        pass

    def recv(self, timeout: float | None = None) -> str:
        if not self.acked:
            self.acked = True
            return json.dumps({"sessionId": "s1"})
        if self.frames:
            return json.dumps(self.frames.pop(0))
        time.sleep(0.05)
        raise ConnectionError("1011 server error" if self.fail else "closed")

    def close(self) -> None:
        pass


def test_live_stream_records_a_model_call_however_it_ends(monkeypatch: pytest.MonkeyPatch) -> None:
    from services.agent.providers import ProviderError, clients

    monkeypatch.setenv("MODEL_API_KEY", "k-meta-000000")
    events: list[Any] = []
    frames: list[dict[str, object]] = [{"type": "transcript", "transcript": "hook", "final": False}]

    def chunks() -> Iterator[bytes]:
        yield QUARTER_S
        time.sleep(0.2)  # still uploading when the server fails

    clients.set_ws_connect(lambda url, **kw: _ScriptedWS(list(frames), fail=True))
    with providers.job_context("j", events.append), pytest.raises(ProviderError):
        list(providers.transcribe_stream(chunks(), pace=False))
    failed = [e for e in events if e.t == "model_call"]
    assert len(failed) == 1 and failed[0].ok is False and failed[0].usd > 0

    events.clear()
    clients.set_ws_connect(lambda url, **kw: _ScriptedWS(list(frames), fail=False))
    with providers.job_context("j", events.append):
        stream = cast(Generator[Any, None, None], providers.transcribe_stream(chunks(), pace=False))
        assert next(stream).text == "hook"
        stream.close()  # the caller stops reading (the browser left)
    calls = [e for e in events if e.t == "model_call"]
    assert len(calls) == 1 and calls[0].ok is True and calls[0].mode == "live"
