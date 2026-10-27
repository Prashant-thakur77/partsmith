from __future__ import annotations

import json
import logging
from typing import Any

import numpy as np
import pytest

from services.agent import providers
from services.agent.providers import ModelRequest, ProviderError, jsonschema_lite, media, replay

from .conftest import FakeHub, responses_stream

NESTED: dict[str, Any] = {
    "type": "object",
    "$defs": {
        "edit": {
            "type": "object",
            "properties": {"param": {"type": "string"}, "to": {"type": "number", "minimum": 0.5}},
            "required": ["param", "to"],
            "additionalProperties": False,
        }
    },
    "properties": {
        "edits": {"type": "array", "items": {"$ref": "#/$defs/edit"}, "minItems": 1},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "kind": {"anyOf": [{"type": "null"}, {"type": "string", "enum": ["a", "b"]}]},
        "ok": {"type": "boolean"},
    },
    "required": ["edits", "confidence", "kind", "ok"],
    "additionalProperties": False,
}


def test_builtin_mock_is_schema_valid_and_free(events: list[Any]) -> None:
    with providers.job_context("job", events.append):
        out = providers.complete(
            "voice_map", ModelRequest(messages=[{"role": "user", "content": "x"}], json_schema=NESTED)
        )
    assert out.mode == "mock" and out.usd == 0.0 and out.provider == "mock"
    assert jsonschema_lite.validate(out.json, NESTED) == []
    assert out.json["edits"][0] == {"param": "mock", "to": 0.5}
    assert "MODEL_API_KEY" in out.note
    (ev,) = events
    assert ev.mode == "mock" and ev.usd == 0 and ev.ok


def test_builtin_build_mock_returns_labelled_program() -> None:
    out = providers.complete("build", ModelRequest(messages=[{"role": "user", "content": "spec"}]))
    assert "MOCK" in out.text and "PARAMS" in out.text and "def build(p)" in out.text


def test_registered_mock_handler_is_used_and_validated() -> None:
    seen: list[ModelRequest] = []

    def handler(req: ModelRequest) -> dict[str, Any]:
        seen.append(req)
        return {"edits": [{"param": req.mock_context["p"], "to": 2.0}], "confidence": 0.9, "kind": "a", "ok": True}

    providers.register_mock("voice_map", handler)
    req = ModelRequest(messages=[{"role": "user", "content": "x"}], json_schema=NESTED, mock_context={"p": "hole_d"})
    out = providers.complete("voice_map", req)
    assert out.json["edits"] == [{"param": "hole_d", "to": 2.0}] and seen[0] is req
    providers.register_mock("voice_map", lambda r: {"edits": []}, replace=False)  # kept: existing handler wins
    assert providers.complete("voice_map", req).json["confidence"] == 0.9
    providers.register_mock("voice_map", lambda r: {"edits": []})
    with pytest.raises(ProviderError, match="schema-invalid"):
        providers.complete("voice_map", req)
    providers.register_mock("judge", lambda r: '{"vetoes": []}')
    schema = {"type": "object", "properties": {"vetoes": {"type": "array"}}, "required": ["vetoes"]}
    assert providers.complete("judge", ModelRequest(messages=[], json_schema=schema)).json == {"vetoes": []}


def test_mock_segment_image_and_transcript() -> None:
    img = np.full((60, 80, 3), 235, dtype=np.uint8)
    img[20:40, 30:60] = 20
    masks = providers.segment(media.encode_png(img), "black plastic part")
    assert len(masks) == 1
    mask, score = masks[0]
    assert mask.shape == (60, 80) and mask.dtype == bool and score == 0.5
    assert mask[20:40, 30:60].all() and mask.sum() == 20 * 30
    assert providers.segment(media.encode_png(np.full((10, 10, 3), 100, np.uint8)), "part") == []
    with pytest.raises(ValueError, match="one short noun phrase"):
        providers.segment(media.encode_png(img), "hole, slot")

    res = providers.generate_image("a clip", [media.encode_png(img)])
    assert res.mode == "mock" and res.mime == "image/png" and media.image_size(res.data) == (80, 60)
    assert res.data != media.encode_png(img)  # labelled
    t = providers.transcribe(media.silent_wav(0.2), "audio/wav", "hi")
    assert t.mode == "mock" and "MOCK" in t.note and t.text
    providers.register_mock("transcribe", lambda r: f"sha {r.mock_context['audio_sha256'][:6]}")
    assert providers.transcribe(b"abc", "audio/wav").text.startswith("sha ")


def test_record_then_replay_with_zero_keys(monkeypatch: pytest.MonkeyPatch, hub: FakeHub, events: list[Any]) -> None:
    schema = {
        "type": "object",
        "properties": {"a": {"type": "integer"}},
        "required": ["a"],
        "additionalProperties": False,
    }
    req = ModelRequest(
        messages=[{"role": "user", "content": "q"}], json_schema=schema, timeout_s=5, mock_context={"x": 1}
    )
    monkeypatch.setenv("MODEL_API_KEY", "k-meta-000000")
    monkeypatch.setenv("PROVIDER_RECORD", "1")
    hub.handlers[("responses", "meta")] = [responses_stream('{"a": 7}', 10, 3)]
    live = providers.complete("understand", req)
    files = list(replay.recordings_dir().glob("*.json"))
    assert len(files) == 1 and files[0].stem == live.request_hash
    saved = json.loads(files[0].read_text())
    assert saved["provider"] == "meta" and saved["response"]["json"] == {"a": 7}
    assert "k-meta" not in files[0].read_text()

    monkeypatch.delenv("MODEL_API_KEY")
    monkeypatch.delenv("PROVIDER_RECORD")
    monkeypatch.setenv("PROVIDER_MODE", "replay")
    other = ModelRequest(messages=[{"role": "user", "content": "q"}], json_schema=schema, timeout_s=99, stream=False)
    with providers.job_context("j", events.append):
        again = providers.complete("understand", other)
    assert again.mode == "replay" and again.json == {"a": 7} and again.usd == 0.0
    assert again.provider == "meta" and again.tokens_in == 10
    assert events[0].mode == "replay" and events[0].usd == 0.0
    assert len(hub.calls_for("responses")) == 1  # nothing live in replay


def test_replay_miss_falls_back_to_mock(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    monkeypatch.setenv("PROVIDER_MODE", "replay")
    with caplog.at_level(logging.WARNING, logger="partsmith.providers"):
        out = providers.complete("plan", ModelRequest(messages=[{"role": "user", "content": "unseen"}]))
    assert out.mode == "mock" and "replay miss" in out.note
    assert any("no recording" in r.message for r in caplog.records)


def test_request_hash_ignores_volatile_fields() -> None:
    a = ModelRequest(messages=[{"role": "user", "content": "x"}], timeout_s=1, stream=True, mock_context={"a": 1})
    b = ModelRequest(messages=[{"role": "user", "content": "x"}], timeout_s=9, stream=False)
    c = ModelRequest(messages=[{"role": "user", "content": "y"}])

    def h(r: ModelRequest) -> str:
        return replay.request_hash("complete", "plan", replay.completion_payload(r))

    assert h(a) == h(b) != h(c)
    assert replay.request_hash("complete", "plan", {}) != replay.request_hash("complete", "build", {})


def test_segment_record_and_replay_roundtrip(monkeypatch: pytest.MonkeyPatch) -> None:
    img = np.full((30, 40, 3), 230, dtype=np.uint8)
    img[5:15, 10:30] = 10
    png = media.encode_png(img)
    monkeypatch.setenv("PROVIDER_RECORD", "1")
    from services.agent.providers import meta

    mask = np.zeros((30, 40), bool)
    mask[5:15, 10:30] = True
    monkeypatch.setenv("MODEL_API_KEY", "k-meta-000000")
    monkeypatch.setattr(meta, "sam_segment", lambda route, image, prompt, timeout: [(mask, 0.8)])
    live = providers.segment(png, "part")
    assert live[0][1] == 0.8
    monkeypatch.delenv("MODEL_API_KEY")
    monkeypatch.setenv("PROVIDER_MODE", "replay")
    (again,) = providers.segment(png, "part")
    assert np.array_equal(again[0], mask) and again[1] == 0.8


def test_job_context_isolation_and_broken_sink() -> None:
    def broken(ev: Any) -> None:
        raise RuntimeError("sink down")

    outer: list[Any] = []
    with providers.job_context("outer", outer.append):
        with providers.job_context("inner", broken) as inner:
            providers.complete("plan", ModelRequest(messages=[{"role": "user", "content": "x"}]))
        providers.complete("plan", ModelRequest(messages=[{"role": "user", "content": "y"}]))
    assert len(inner.events) == 1 and inner.events[0].job == "inner"
    assert len(outer) == 1 and outer[0].job == "outer"
    providers.complete("plan", ModelRequest(messages=[{"role": "user", "content": "z"}]))  # no context: no emit
    assert len(outer) == 1


def test_jsonschema_lite() -> None:
    v = jsonschema_lite.validate
    assert v(True, {"type": "integer"}) != []
    assert v(3.0, {"type": "integer"}) == []
    assert v({"a": 1, "b": 2}, {"type": "object", "properties": {"a": {}}, "additionalProperties": False})
    assert v("abc", {"type": "string", "pattern": "^a", "maxLength": 3}) == []
    assert v(5, {"oneOf": [{"type": "integer"}, {"type": "number"}]})  # matches both → oneOf fails
    assert jsonschema_lite.extract_json('Sure!\n```json\n{"x": [1]}\n```') == {"x": [1]}
    assert jsonschema_lite.extract_json('prefix {"x": 1} suffix') == {"x": 1}
    with pytest.raises(ValueError):
        jsonschema_lite.extract_json("nothing here")
    assert jsonschema_lite.minimal_instance({"type": "string", "minLength": 6}) == "mock__"
    assert jsonschema_lite.minimal_instance({"type": "integer", "exclusiveMinimum": 0}) == 1
