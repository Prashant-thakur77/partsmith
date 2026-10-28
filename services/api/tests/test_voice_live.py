"""Live voice WebSocket relay: browser PCM → realtime transcripts → edits through the same mapping and guards as
POST /edit. The provider stream is the labelled mock or a scripted fake; no network, no keys."""

from __future__ import annotations

import time
from collections.abc import Iterable, Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from partsmith_schemas import DataOrigin, JobInput
from starlette.websockets import WebSocketDisconnect

from services.agent import providers
from services.agent.providers import ProviderError, realtime
from services.agent.providers.realtime import VoiceEvent
from services.agent.templates import get_template
from services.api import deps, voice_live
from services.api import main as M
from services.api.tests.test_api import FakeService
from services.geom_worker.program import parse_params

FRAME = b"\x01\x00" * 1600  # 100 ms of 16 kHz s16le mono


class VoiceService(FakeService):
    """FakeService whose `edit` runs the real voice→knob mapper and guards (no bake), like the agent service."""

    def edit(
        self, job_id: str, *, text: str | None = None, audio: bytes | None = None, mime: str = "audio/wav"
    ) -> dict[str, Any]:
        from services.media.voice import transcribe_and_map

        specs, values = self.job_params(job_id)
        res = transcribe_and_map(text or "", specs, values)
        job = self.mgr.get(job_id)
        assert job is not None
        job.write_json("values.json", {**values, **{e.param: e.to for e in res.edits}})
        return {**res.to_dict(), "bake": None}


@pytest.fixture
def svc(monkeypatch: pytest.MonkeyPatch) -> Iterator[VoiceService]:
    f = VoiceService()
    monkeypatch.setattr(deps, "service", lambda: f)
    yield f
    f.mgr.shutdown()


@pytest.fixture
def client(svc: VoiceService) -> TestClient:
    return TestClient(M.app)


def _job(svc: VoiceService, template: str | None = "spacer") -> str:
    job = svc.mgr.create("fix", JobInput(origin=DataOrigin.synthetic), title="voice test")
    if template:
        job.write_text("part.py", get_template(template).code)
    return str(job.id)


def _until_closed(ws: Any, limit: int = 400) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for _ in range(limit):
        msg = ws.receive_json()
        out.append(msg)
        if msg["type"] == "closed":
            return out
    raise AssertionError(f"no 'closed' message: {out[-5:]}")


def _url(jid: str) -> str:
    return f"/api/v1/jobs/{jid}/voice/live"


@pytest.mark.timeout(30)
def test_mock_session_partials_then_final_then_guarded_edit(client: TestClient, svc: VoiceService) -> None:
    jid = _job(svc, "spacer")
    with client.websocket_connect(_url(jid)) as ws:
        ready = ws.receive_json()
        assert ready["type"] == "ready" and ready["mode"] == "mock" and ready["sample_rate"] == 16000
        assert "Bore diameter" in ready["keywords"] and ready["language_bias"] == ["English", "Hindi"]
        assert ready["mock_script"] == "hole thoda bada karo" and "mock" in ready["note"]
        for _ in range(20):  # 2 s of audio
            ws.send_bytes(FRAME)
        ws.send_json({"type": "stop"})
        msgs = _until_closed(ws)
    kinds = [m["type"] for m in msgs]
    assert kinds.index("partial") < kinds.index("final") < kinds.index("edit")
    partials = [m["text"] for m in msgs if m["type"] == "partial"]
    assert partials[:2] == ["hole", "hole thoda"] and all(m.get("mode", "mock") == "mock" for m in msgs[:-1])
    final = next(m for m in msgs if m["type"] == "final")
    assert final["text"] == "hole thoda bada karo"
    edit = next(m for m in msgs if m["type"] == "edit")["result"]
    assert edit["transcript"] == "hole thoda bada karo" and edit["transcript_mode"] == "mock"
    assert [(e["param"], e["from"], e["to"]) for e in edit["edits"]] == [("bore_d", 3.4, 3.6)]
    closed = msgs[-1]
    assert closed["reason"] == "stopped" and closed["finals"] == 1 and closed["edits"] == 1
    assert closed["bytes"] == 20 * len(FRAME) and closed["seconds"] == 2.0
    job = svc.mgr.get(jid)
    assert job is not None and job.read_json("values.json")["bore_d"] == 3.6
    stages = [e for e in job.events if e.t == "model_call"]
    assert stages and stages[0].stage == "transcribe_stream" and stages[0].mode == "mock"
    assert any(e.t == "log" and "live voice (mock) heard" in e.msg for e in job.events)


def test_mock_script_fits_the_job() -> None:
    hook = parse_params(get_template("hook").code)
    clip = parse_params(get_template("clip").code)
    knob = parse_params(get_template("knob").code)
    vals = {s.name: s.default for s in clip}
    assert voice_live.mock_script(clip, vals) == "hook ko 1 mm mota karo"  # "Hook arm thickness"
    assert voice_live.mock_script(knob, {s.name: s.default for s in knob}) == "hole thoda bada karo"
    assert voice_live.mock_script(hook, {s.name: s.default for s in hook}) == "hole thoda bada karo"
    assert voice_live.mock_script([], {}) == voice_live.DEFAULT_MOCK_SCRIPT
    kw = voice_live.knob_keywords(hook)
    assert kw[0] == "Back plate length" and len(kw) <= voice_live.MAX_KEYWORDS and len(set(kw)) == len(kw)


@pytest.mark.timeout(30)
def test_live_stream_final_is_clamped_by_the_guards(
    client: TestClient, svc: VoiceService, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: dict[str, Any] = {}

    def fake_stream(chunks: Iterable[bytes], **kw: Any) -> Iterator[VoiceEvent]:
        seen.update(kw)
        got = 0
        for c in chunks:
            got += len(c)
            if got == len(FRAME):
                yield VoiceEvent("speech_start", turn_id="1")
                yield VoiceEvent("partial", "bore diameter", "1")
        seen["bytes"] = got
        yield VoiceEvent("final", "bore diameter 50 mm", "1")
        yield VoiceEvent("speech_end", turn_id="1")

    monkeypatch.setattr(providers, "transcribe_stream", fake_stream)
    monkeypatch.setattr(realtime, "mode", lambda: "live")
    jid = _job(svc, "spacer")
    with client.websocket_connect(_url(jid)) as ws:
        ready = ws.receive_json()
        assert ready["mode"] == "live" and "mock_script" not in ready
        ws.send_bytes(FRAME)
        assert ws.receive_json()["type"] == "speech_start"
        assert ws.receive_json() == {"type": "partial", "turn_id": "1", "mode": "live", "text": "bore diameter"}
        ws.send_bytes(FRAME)
        ws.send_json({"type": "stop"})
        msgs = _until_closed(ws)
    assert seen["keywords"][:2] == ["Outer diameter", "Height"] and seen["pace"] is False
    assert seen["language_bias"] == ("English", "Hindi") and seen["bytes"] == 2 * len(FRAME)
    edit = next(m for m in msgs if m["type"] == "edit")["result"]
    assert edit["edits"][0]["param"] == "bore_d" and edit["edits"][0]["to"] == 20.0  # asked 50, PARAMS max is 20
    assert edit["transcript_mode"] == "live" and msgs[-1]["reason"] == "stopped"


@pytest.mark.timeout(30)
def test_time_cap_closes_the_session(client: TestClient, svc: VoiceService, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(voice_live, "MAX_SECONDS", 0.4)
    jid = _job(svc)
    t0 = time.monotonic()
    with client.websocket_connect(_url(jid)) as ws:
        assert ws.receive_json()["max_seconds"] == 0.4
        msgs = _until_closed(ws)
    assert {"type": "capped", "reason": "time", "limit": 0.4} in msgs
    assert msgs[-1]["reason"] == "time_cap" and msgs[-1]["finals"] == 0  # no audio → the mock hears nothing
    assert time.monotonic() - t0 < 10


@pytest.mark.timeout(30)
def test_size_cap_stops_the_upload_but_keeps_what_was_heard(
    client: TestClient, svc: VoiceService, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(voice_live, "MAX_BYTES", 3 * len(FRAME))
    jid = _job(svc)
    with client.websocket_connect(_url(jid)) as ws:
        ws.receive_json()
        for _ in range(4):
            ws.send_bytes(FRAME)
        msgs = _until_closed(ws)
    assert {"type": "capped", "reason": "size", "limit": 3 * len(FRAME)} in msgs
    assert msgs[-1]["reason"] == "size_cap" and msgs[-1]["bytes"] == 3 * len(FRAME)
    assert msgs[-1]["finals"] == 1  # the mock's utterance is flushed when the upload ends


@pytest.mark.timeout(30)
def test_malformed_frames(client: TestClient, svc: VoiceService) -> None:
    jid = _job(svc)
    with client.websocket_connect(_url(jid)) as ws:
        ws.receive_json()
        ws.send_text("not json")
        warn = ws.receive_json()
        assert warn["type"] == "warning" and warn["code"] == "bad_frame"
        ws.send_json({"type": "ping"})
        assert ws.receive_json() == {"type": "pong"}
        ws.send_bytes(b"\x01\x00\x02")  # half a sample
        msgs = _until_closed(ws)
    assert msgs[0]["type"] == "error" and msgs[0]["code"] == "bad_frame" and "even" in msgs[0]["message"]
    assert msgs[-1]["reason"] == "error" and msgs[-1]["edits"] == 0
    with client.websocket_connect(_url(jid)) as ws:
        ws.receive_json()
        ws.send_bytes(b"RIFF" + b"\0" * 40)
        assert ws.receive_json()["code"] == "bad_frame"


@pytest.mark.timeout(30)
def test_provider_error_is_reported_not_hung(
    client: TestClient, svc: VoiceService, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(chunks: Iterable[bytes], **kw: Any) -> Iterator[VoiceEvent]:
        for _ in chunks:
            yield VoiceEvent("partial", "hook", "1", mode="live")
            raise ProviderError("Muse Voice stream closed: 1011", provider="meta")

    monkeypatch.setattr(providers, "transcribe_stream", broken)
    jid = _job(svc)
    with client.websocket_connect(_url(jid)) as ws:
        ws.receive_json()
        ws.send_bytes(FRAME)
        msgs = _until_closed(ws)
    assert [m["type"] for m in msgs] == ["partial", "error", "closed"]
    assert msgs[1]["code"] == "provider_error" and "1011" in msgs[1]["message"] and msgs[2]["reason"] == "error"


def test_unknown_job_no_program_and_foreign_origin(client: TestClient, svc: VoiceService) -> None:
    with client.websocket_connect(_url("j_nope")) as ws:
        err = ws.receive_json()
        assert err["type"] == "error" and err["code"] == "job_not_found"
    with client.websocket_connect(_url(_job(svc, None))) as ws:
        assert ws.receive_json()["code"] == "no_program"
    foreign = {"origin": "https://elsewhere.example"}
    with pytest.raises(WebSocketDisconnect) as exc, client.websocket_connect(_url(_job(svc)), headers=foreign):
        pass
    assert exc.value.code == voice_live.POLICY
    with client.websocket_connect(_url(_job(svc)), headers={"origin": "http://localhost:3000"}) as ws:
        assert ws.receive_json()["type"] == "ready"
        ws.send_json({"type": "stop"})
        assert _until_closed(ws)[-1]["reason"] == "stopped"


def test_busy_when_too_many_sessions(client: TestClient, svc: VoiceService, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(voice_live, "MAX_SESSIONS", 0)
    with client.websocket_connect(_url(_job(svc))) as ws:
        assert ws.receive_json()["code"] == "busy"


def test_route_is_listed() -> None:
    assert ("WS", "/api/v1/jobs/{job_id}/voice/live") in set(M.iter_routes())
