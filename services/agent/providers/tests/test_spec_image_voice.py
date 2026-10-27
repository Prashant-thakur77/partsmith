"""Wonder spec lookup, Muse Image region completion / edits / install cards, realtime voice, Glimmer crops,
and the open-weights summary."""

from __future__ import annotations

import base64
import io
import json
import threading
import time
from typing import Any

import httpx
import numpy as np
import pytest
from PIL import Image

from services.agent import providers
from services.agent.providers import ModelRequest, chat, clients, media, realtime, spec, telemetry

from .conftest import FakeHub, Obj, chat_stream

# ------------------------------------------------------------------------------------------------ spec lookup


def test_spec_mock_is_labelled_and_never_invents() -> None:
    empty = providers.lookup_spec("Whirlpool WTW5000 lid hinge", ["pin_diameter"])
    assert empty.values == [] and empty.searched is False and empty.mode == "mock"
    assert empty.notes == [spec.MOCK_NOTE]
    out = providers.lookup_spec("hinge", ["pin_diameter", "length"], fixture={"pin_diameter": 4.0})
    (v,) = out.values
    assert v["name"] == "pin_diameter" and v["value_mm"] == 4.0
    assert v["citation"].url.startswith("https://example.invalid/") and "MOCK" in v["citation"].title
    assert out.searched is False


def _search_response(searched: bool = True) -> dict[str, Any]:
    answer = {
        "values": [
            {
                "name": "pin diameter",
                "value": 0.25,
                "unit": "in",
                "url": "https://oem.example.com/hinge/",
                "title": "OEM",
                "quote": "Pin: 1/4 in",
            },
            {
                "name": "length",
                "value": 42,
                "unit": "mm",
                "url": "https://made-up.example.org/x",
                "title": "?",
                "quote": "42 mm",
            },
            {
                "name": "colour",
                "value": 1,
                "unit": "mm",
                "url": "https://oem.example.com/hinge",
                "title": "",
                "quote": "",
            },
        ],
        "notes": "length came from a forum",
    }
    text = "Here you go: " + json.dumps(answer)
    output: list[dict[str, Any]] = []
    if searched:
        output.append(
            {
                "type": "web_search_call",
                "status": "completed",
                "action": {"type": "search", "sources": [{"url": "https://parts.example.net/a"}]},
            }
        )
    output.append(
        {
            "type": "message",
            "content": [
                {
                    "type": "output_text",
                    "text": text,
                    "annotations": [
                        {
                            "type": "url_citation",
                            "url": "https://oem.example.com/hinge",
                            "start_index": 0,
                            "end_index": 4,
                        }
                    ],
                }
            ],
        }
    )
    return {"output": output, "usage": {"input_tokens": 1000, "output_tokens": 200}}


def test_spec_live_accepts_only_cited_requested_values(monkeypatch: pytest.MonkeyPatch, hub: FakeHub) -> None:
    monkeypatch.setenv("MODEL_API_KEY", "k-meta-000000")
    resp = _search_response()
    text = resp["output"][-1]["content"][0]["text"]
    lane = {"item_id": "m", "output_index": 0, "content_index": 0}
    hub.handlers[("responses", "meta")] = [
        [
            {"type": "response.output_text.delta", **lane, "delta": text},
            {"type": "response.completed", "response": resp},
        ]
    ]
    out = providers.lookup_spec("Whirlpool lid hinge", ["pin_diameter", "length"])
    kw = hub.calls_for("responses")[0]
    assert kw["model"] == "muse-wonder-1.0" and kw["tools"] == [{"type": "web_search", "search_context_size": "high"}]
    assert kw["include"] == ["web_search_call.results"] and "text" not in kw
    assert out.searched and out.queries == 1 and out.mode == "live"
    (v,) = out.values
    assert v["name"] == "pin_diameter" and v["value_mm"] == pytest.approx(6.35)
    assert v["citation"].url == "https://oem.example.com/hinge/" and v["citation"].quote == "Pin: 1/4 in"
    joined = " | ".join(out.notes)
    assert "length: rejected" in joined and "unrequested value 'colour'" in joined and "model note" in joined
    assert out.usd == pytest.approx((1000 * 4.0 + 200 * 20.0) / 1e6 + 0.0025)


def test_spec_without_search_accepts_nothing() -> None:
    searched, queries, cited, sources = spec.search_evidence(_search_response(searched=False))
    assert (searched, queries) == (False, 0) and "https://oem.example.com/hinge" in cited
    answer = json.loads(_search_response()["output"][-1]["content"][0]["text"].split(": ", 1)[1])
    values, notes = spec.accept_values(answer, ["pin_diameter"], searched, sources, cited)
    assert values == [] and "no web search ran" in notes[0]


# ------------------------------------------------------------------------------------------------ Muse Image


def _symmetric_part() -> tuple[bytes, bytes, np.ndarray]:
    img = np.full((40, 60, 3), 230, np.uint8)
    img[10:30, 10:50] = (40, 60, 160)
    img[15:25, 14:18] = 230  # a hole on the left …
    img[15:25, 42:46] = 230  # … mirrored on the right
    keep = np.ones((40, 60), np.uint8) * 255
    keep[8:32, 36:50] = 0  # the broken right end (the mask ends where the part's outline ends)
    broken = img.copy()
    broken[8:32, 36:50] = 230
    return media.encode_png(broken), media.encode_png(np.dstack([keep] * 3)), img


def test_reconstruct_mock_mirrors_and_keeps_intact_pixels() -> None:
    broken, keep_png, truth = _symmetric_part()
    res = providers.reconstruct(broken, keep_png, "it is a symmetric bracket")
    out = media.decode_image_rgb(res.data)
    keep = media.decode_image_rgb(keep_png)[..., 0] > 127
    assert np.array_equal(out[keep], media.decode_image_rgb(broken)[keep])
    region = ~keep
    agree = (np.abs(out.astype(int) - truth.astype(int)).max(axis=2) < 10)[region].mean()
    assert agree > 0.9  # mirror restores the right end and its hole (the MOCK stamp covers a few pixels)
    assert res.mode == "mock" and "MOCK reconstruction" in res.note


def test_reconstruct_live_composites_generated_region(monkeypatch: pytest.MonkeyPatch, hub: FakeHub) -> None:
    monkeypatch.setenv("MODEL_API_KEY", "k-meta-000000")
    broken, keep_png, _ = _symmetric_part()
    generated = media.encode_png(np.full((80, 120, 3), 99, np.uint8))  # different size, every pixel changed
    hub.handlers[("responses", "meta")] = [
        Obj(id="resp_1", output=[Obj(type="image_generation_call", result=base64.b64encode(generated).decode())])
    ]
    res = providers.reconstruct(broken, keep_png)
    out = media.decode_image_rgb(res.data)
    keep = media.decode_image_rgb(keep_png)[..., 0] > 127
    assert np.array_equal(out[keep], media.decode_image_rgb(broken)[keep]) and (out[~keep] == 99).all()
    kw = hub.calls_for("responses")[0]
    content = kw["input"][0]["content"]
    assert (
        kw["model"] == "muse-image-1.0"
        and kw["store"] is False
        and [p["type"] for p in content] == ["input_text", "input_image", "input_image"]
    )
    assert res.usd == 0.01 and res.mode == "live"


def test_edit_chain_mock_and_live(monkeypatch: pytest.MonkeyPatch, hub: FakeHub) -> None:
    ref = np.full((120, 200, 3), 200, np.uint8)
    ref[40:80, 60:140] = 240  # a white clip on a grey mat
    first = providers.generate_image("a white clip", [media.encode_png(ref)], editable=True)
    assert first.response_id.startswith("mock-img-")
    edited = providers.edit_image(first.response_id, "show it in black PETG")
    assert edited.mode == "mock" and edited.response_id != first.response_id and edited.data != first.data
    with pytest.raises(ValueError, match="unknown image id"):
        providers.edit_image("mock-img-nope", "x")

    monkeypatch.setenv("MODEL_API_KEY", "k-meta-000000")
    png = media.encode_png(np.zeros((4, 4, 3), np.uint8))
    hub.handlers[("responses", "meta")] = [
        Obj(id="resp_9", output=[Obj(type="image_generation_call", result=base64.b64encode(png).decode())])
    ]
    live = providers.edit_image("resp_8", "make it black")
    kw = hub.calls_for("responses")[0]
    assert kw["previous_response_id"] == "resp_8" and kw["store"] is True and kw["input"] == "make it black"
    assert live.response_id == "resp_9"


def test_install_card_anchors_panels(monkeypatch: pytest.MonkeyPatch, hub: FakeHub) -> None:
    photo = media.encode_png(np.full((60, 90, 3), 120, np.uint8))
    render = media.encode_png(np.full((30, 30, 3), 250, np.uint8))
    mock_panels = providers.install_card(photo, render, ["remove the old clip", "push the new clip in", "test the lid"])
    assert (
        len(mock_panels) == 3 and len({p.data for p in mock_panels}) == 3 and all(p.mode == "mock" for p in mock_panels)
    )

    monkeypatch.setenv("MODEL_API_KEY", "k-meta-000000")
    png = media.encode_png(np.zeros((4, 4, 3), np.uint8))
    replies = iter(["resp_a", "resp_b"])
    hub.handlers[("responses", "meta")] = lambda kw: Obj(
        id=next(replies), output=[Obj(type="image_generation_call", result=base64.b64encode(png).decode())]
    )
    panels = providers.install_card(photo, render, ["step one", "step two"])
    first, second = hub.calls_for("responses")
    assert first["store"] is True and "previous_response_id" not in first and len(first["input"][0]["content"]) == 3
    assert (
        second["previous_response_id"] == "resp_a"
        and isinstance(second["input"], str)
        and "Panel 2 of 2" in second["input"]
    )
    assert [p.response_id for p in panels] == ["resp_a", "resp_b"] and sum(p.usd for p in panels) == pytest.approx(0.02)
    with pytest.raises(ValueError):
        providers.install_card(photo, render, [])


# ------------------------------------------------------------------------------------------------ realtime voice


def test_realtime_mock_events() -> None:
    events = list(providers.transcribe_stream([b"\0\0" * 160], mock_text="hole thoda bada. make it 2 mm longer"))
    kinds = [e.kind for e in events]
    assert kinds[0] == "speech_start" and kinds.count("final") == 2 and kinds[-1] == "speech_end"
    finals = [e.text for e in events if e.kind == "final"]
    assert finals == ["hole thoda bada", "make it 2 mm longer"] and all(e.mode == "mock" for e in events)
    assert [e.text for e in events if e.kind == "partial"][:2] == ["hole", "hole thoda"]


class FakeWS:
    def __init__(self, script: list[dict[str, Any]], reject: bool = False) -> None:
        self.sent: list[Any] = []
        self.script = script
        self.reject = reject
        self.acked = False
        self.ended = threading.Event()
        self.closed = False

    def send(self, message: Any) -> None:
        self.sent.append(message)
        if isinstance(message, str) and json.loads(message).get("type") == "endStream":
            self.ended.set()

    def recv(self, timeout: float | None = None) -> str:
        if not self.acked:
            self.acked = True
            return json.dumps({"type": "error", "message": "bad key"} if self.reject else {"sessionId": "s1"})
        if self.script:
            return json.dumps(self.script.pop(0))
        self.ended.wait(2)
        raise ConnectionError("closed by server")

    def close(self) -> None:
        self.closed = True


def test_realtime_live_protocol(monkeypatch: pytest.MonkeyPatch, events: list[Any]) -> None:
    monkeypatch.setenv("MODEL_API_KEY", "k-meta-000000")
    ws = FakeWS(
        [
            {"type": "speechStart", "turnId": 1},
            {"type": "transcript", "transcript": "hook ko", "final": False},
            {"type": "speechEnd", "turnId": 1},
            {"type": "speechComplete", "turnId": 1, "transcript": "hook ko 1 mm mota karo"},
            {"type": "audioProgress"},
        ]
    )
    urls: list[str] = []

    def connect(url: str, **kw: Any) -> FakeWS:
        urls.append(url)
        return ws

    clients.set_ws_connect(connect)
    pcm = [b"\x01\x00" * 1600, b"\x02\x00" * 1600]  # 2 × 0.1 s
    with providers.job_context("j", events.append):
        out = list(providers.transcribe_stream(pcm, keywords=["hook thickness"], pace=False))
    assert urls == ["wss://api.meta.ai/v1/asr/realtime"]
    hs = json.loads(ws.sent[0])
    assert hs["authorization"] == {"accessToken": "Bearer k-meta-000000"} and hs["mode"] == "ENDPOINTING"
    assert (
        hs["audioEncoding"] == "PCM_16KHZ"
        and hs["keywords"] == ["hook thickness"]
        and hs["languageBias"] == ["English", "Hindi"]
    )
    assert ws.sent[1:3] == pcm and json.loads(ws.sent[3]) == {"type": "endStream"} and ws.closed
    assert [(e.kind, e.text) for e in out] == [
        ("speech_start", ""), ("partial", "hook ko"), ("speech_end", ""), ("final", "hook ko 1 mm mota karo"),
    ]  # fmt: skip
    assert events[-1].stage == "transcribe_stream" and events[-1].usd == pytest.approx(0.18 * 0.2 / 3600)


def test_realtime_falls_back_to_file_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MODEL_API_KEY", "k-meta-000000")
    monkeypatch.setenv("PROVIDER_MAX_RETRIES", "0")
    posted: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        posted.append(request)
        return httpx.Response(200, json={"transcript": "hole thoda bada", "audioDurationMs": 100})

    clients.set_http_transport(httpx.MockTransport(handle))
    clients.set_ws_connect(lambda url, **kw: FakeWS([], reject=True))
    out = list(providers.transcribe_stream([b"\0\0" * 1600], pace=False))
    assert [(e.kind, e.text) for e in out] == [("final", "hole thoda bada")] and len(posted) == 1
    assert 'name="audio"' in posted[0].content.decode("latin-1")

    def refuse(url: str, **kw: Any) -> Any:
        raise OSError("network down")

    clients.set_ws_connect(refuse)
    assert [e.text for e in providers.transcribe_stream([b"\0\0" * 1600], pace=False)] == ["hole thoda bada"]


def test_realtime_pacing_uses_wall_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MODEL_API_KEY", "k-meta-000000")
    waits: list[float] = []
    monkeypatch.setattr(realtime, "sleep", waits.append)
    clients.set_ws_connect(lambda url, **kw: FakeWS([{"type": "speechComplete", "transcript": "ok"}]))
    t0 = time.monotonic()
    list(providers.transcribe_stream([b"\0\0" * 16000, b"\0\0" * 16000], pace=True))  # 2 × 1 s
    assert waits and waits[0] == pytest.approx(1.0, abs=0.2) and time.monotonic() - t0 < 2


# ------------------------------------------------------------------------------------------------ Glimmer crops


def test_glimmer_multiple_labelled_crops(monkeypatch: pytest.MonkeyPatch, hub: FakeHub) -> None:
    monkeypatch.setenv("GLIMMER_BASE_URL", "https://ws--glimmer.modal.run")
    big = media.encode_png(np.zeros((3000, 1500, 3), np.uint8))
    small = media.encode_png(np.zeros((64, 64, 3), np.uint8))
    hub.handlers[("chat", "modal.run")] = [chat_stream('{"vetoes": []}')]
    req = ModelRequest(
        messages=[{"role": "user", "content": "judge"}],
        images=[small, big, small],
        image_labels=["photo", "hotspot crop around hole_1", ""],
    )
    providers.complete("judge", req)
    parts = hub.calls_for("chat")[0]["messages"][0]["content"]
    assert [p["type"] for p in parts] == ["text", "text", "image_url", "text", "image_url", "image_url"]
    assert parts[3]["text"] == "Image 2: hotspot crop around hole_1"
    second = base64.b64decode(parts[4]["image_url"]["url"].split(",", 1)[1])
    assert Image.open(io.BytesIO(second)).size == (512, 1024)  # downscaled to the 1024 px cap
    too_many = ModelRequest(messages=[{"role": "user", "content": "x"}], images=[small] * (chat.GLIMMER_MAX_IMAGES + 1))
    with pytest.raises(providers.ProviderError, match="at most 12 images"):
        providers.complete("judge", too_many)


def test_meta_image_labels() -> None:
    from services.agent.providers import meta

    req = ModelRequest(
        messages=[{"role": "user", "content": "x"}], images=[b"\x89PNG\r\n\x1a\nA"], image_labels=["crop"]
    )
    parts = meta.build_input(req)[0]["content"]
    assert [p["type"] for p in parts] == ["input_text", "input_text", "input_image"] and parts[1][
        "text"
    ] == "Image 1: crop"


# ------------------------------------------------------------------------------------------------ evidence


def test_open_weights_summary(monkeypatch: pytest.MonkeyPatch, hub: FakeHub) -> None:
    telemetry.reset_tally()
    providers.complete("plan", ModelRequest(messages=[{"role": "user", "content": "x"}]))  # mock
    monkeypatch.setenv("GLIMMER_BASE_URL", "https://ws--glimmer.modal.run")
    hub.handlers[("chat", "modal.run")] = [chat_stream("fine", 30, 5)]
    providers.complete("judge", ModelRequest(messages=[{"role": "user", "content": "x"}]))
    summary = providers.open_weights_summary()
    assert (
        summary["judge"]["open_weights"] is True and summary["judge"]["calls"] == 1 and summary["judge"]["tokens"] == 35
    )
    assert summary["judge"]["provider"] == "modal_glimmer" and summary["judge"]["model"] == "muse-glimmer"
    assert summary["plan"]["calls"] == 0 and summary["plan"]["modes"] == {"mock": 1}
    recorded = [
        {
            "t": "model_call",
            "stage": "build",
            "provider": "baseten",
            "model": "meta-models/muse-spark-open",
            "mode": "live",
            "tokens_in": 10,
            "tokens_out": 2,
            "ok": True,
        },
        {"t": "model_call", "stage": "build", "provider": "baseten", "model": "x", "mode": "live", "ok": False},
        {"t": "thought", "stage": "build"},
    ]
    from_events = providers.open_weights_summary(recorded)
    assert from_events == {
        "build": {
            "model": "meta-models/muse-spark-open", "provider": "baseten", "open_weights": True, "calls": 1, "tokens": 12,
            "modes": {"live": 1},
            "routes": [{"provider": "baseten", "model": "meta-models/muse-spark-open", "mode": "live", "open_weights": True, "calls": 1, "tokens": 12}],
        }
    }  # fmt: skip
