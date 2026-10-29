"""SAM 3.1, SAM 3 open, Muse Image and Muse Voice adapters against fake transports."""

from __future__ import annotations

import base64
import json
from typing import Any

import httpx
import numpy as np
import pytest
from meta_sam_parser._mask_codec import _encode_raster

from services.agent import providers
from services.agent.providers import clients, media, pricing, sam_parse

from .conftest import FakeHub, Obj

PNG_64x48 = media.encode_png(np.zeros((48, 64, 3), dtype=np.uint8))


def _sam_text(conf: str = ";c=0.87") -> str:
    raster = [0, 1, 1, 0, 1, 1, 1, 1, 0, 1, 1, 0]  # 3 rows x 4 cols
    payload = _encode_raster(raster, 4, 3)
    # Box is 8x6 px (x 10..17, y 20..25): the 4x3 raster is upscaled 2x into it.
    return f"<0f>3<|box;x1=10;y1=20;x2=17;y2=25;w=64;h=48{conf}|><|mask;x=0;y=0;data=3,4,{payload}|>"


# A real sam-3.1 reply (2026-10-29, smoke prompt "black square" on a 128 px image with a 64 px square at 32..95):
# the live API also puts the confidence in the mask token, which the parser library rejects unless it is stripped.
LIVE_SAM_REPLY = (
    "<0f>0<|box;x1=32;y1=32;x2=95;y2=95;w=128;h=128;c=0.7730495929718018|>"
    "<|mask;x=0;y=0;c=0.7730495929718018;data=64,64,!!!!!(y:U@_p.y|>\n"
)


def test_parse_masks_reads_a_recorded_live_reply_with_confidence_in_the_mask_token() -> None:
    ((mask, score),) = sam_parse.parse_masks(LIVE_SAM_REPLY, 128, 128)
    assert score == pytest.approx(0.7730495929718018)
    ys, xs = np.nonzero(mask)
    assert [int(v) for v in (xs.min(), xs.max(), ys.min(), ys.max())] == [32, 95, 32, 95] and mask.sum() == 64 * 64
    clean, _ = sam_parse.split_confidence(LIVE_SAM_REPLY)
    assert "c=" not in clean and "data=64,64,!!!!!(y:U@_p.y" in clean


def test_parse_masks_pastes_box_local_raster_into_full_frame() -> None:
    ((mask, score),) = sam_parse.parse_masks(_sam_text(), 64, 48)
    assert mask.shape == (48, 64) and score == pytest.approx(0.87)
    expected = np.zeros((48, 64), bool)
    expected[20:26, 10:18] = np.kron(np.array([[0, 1, 1, 0], [1, 1, 1, 1], [0, 1, 1, 0]], bool), np.ones((2, 2), bool))
    assert np.array_equal(mask, expected)
    ((_, default_score),) = sam_parse.parse_masks(_sam_text(conf=""), 64, 48)
    assert default_score == 1.0
    assert sam_parse.parse_masks("", 64, 48) == []


def test_stream_shim_closes_lane_from_content_part_done() -> None:
    lane = {"item_id": "i", "output_index": 0, "content_index": 0}
    events = [
        Obj(type="response.output_text.delta", **lane, delta="<0f>"),
        {"type": "response.content_part.done", **lane, "part": {"type": "output_text", "text": "<0f>full"}},
        {"type": "response.completed", "response": {"usage": {}}},
    ]
    text, final = sam_parse.stream_text(events)
    assert text == "<0f>full" and final == {"usage": {}}
    with pytest.raises(providers.ProviderError, match=r"response\.failed"):
        sam_parse.stream_text([{"type": "response.failed", "response": {"error": {"message": "x"}}}])


def test_sam_31_live_request_shape(monkeypatch: pytest.MonkeyPatch, hub: FakeHub, events: list[Any]) -> None:
    monkeypatch.setenv("MODEL_API_KEY", "k-meta-000000")
    text = _sam_text()
    lane = {"item_id": "i", "output_index": 0, "content_index": 0}
    hub.handlers[("responses", "meta")] = [
        [
            {"type": "response.output_text.delta", **lane, "delta": text},
            {"type": "response.content_part.done", **lane, "part": {"type": "output_text", "text": text}},
        ]
    ]
    with providers.job_context("j", events.append):
        masks = providers.segment(PNG_64x48, "  snap   hook ")
    kw = hub.calls_for("responses")[0]
    assert kw["model"] == "sam-3.1" and kw["stream"] is True and kw["store"] is False
    assert kw["metadata"] == {"mask_encoding": "one_bit", "include_confidence": "true"}
    content = kw["input"][0]["content"]
    assert kw["input"][0]["role"] == "user" and content[0] == {"type": "input_text", "text": "snap hook"}
    assert content[1]["image_url"].startswith("data:image/png;base64,")
    assert len(masks) == 1 and masks[0][0].sum() == 2 * 2 * 8
    assert events[0].usd == pytest.approx(pricing.SAM_31_PER_IMAGE_USD) and events[0].provider == "meta"


def test_sam3_open_service(monkeypatch: pytest.MonkeyPatch, events: list[Any]) -> None:
    monkeypatch.setenv("OPEN_WEIGHTS_ONLY", "1")
    monkeypatch.setenv("SAM3_OPEN_URL", "https://ws--partsmith-sam3.modal.run/")
    monkeypatch.setenv("SAM3_OPEN_API_KEY", "k-sam3-secret")
    mask = np.zeros((48, 64), bool)
    mask[1:5, 2:9] = True
    seen: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path == "/health":
            return httpx.Response(200, json={"ok": True, "model": "sam3"})
        return httpx.Response(
            200, json={"width": 64, "height": 48, "masks": [{"score": 0.9, "rle": media.rle_encode(mask)}]}
        )

    clients.set_http_transport(httpx.MockTransport(handle))
    with providers.job_context("j", events.append):
        ((got, score),) = providers.segment(PNG_64x48, "clip")
    body = json.loads(seen[0].content)
    assert seen[0].url == "https://ws--partsmith-sam3.modal.run/segment"
    assert seen[0].headers["authorization"] == "Bearer k-sam3-secret"
    assert body["prompt"] == "clip" and base64.b64decode(body["image_b64"]) == PNG_64x48
    assert np.array_equal(got, mask) and score == 0.9
    assert events[0].provider == "modal_sam3" and events[0].usd == 0.0
    from services.agent.providers import routing, sam_open

    assert sam_open.health(routing.SAM_3_OPEN)["ok"] is True


def test_rle_roundtrip() -> None:
    rng = np.random.default_rng(0)
    for shape in [(5, 7), (1, 1), (16, 3)]:
        m = rng.random(shape) > 0.5
        assert np.array_equal(media.rle_decode(media.rle_encode(m)), m)
    full = np.ones((2, 2), bool)
    assert media.rle_encode(full)["counts"] == [0, 4]


def test_muse_image_wraps_references_in_user_message(monkeypatch: pytest.MonkeyPatch, hub: FakeHub) -> None:
    monkeypatch.setenv("MODEL_API_KEY", "k-meta-000000")
    out_png = media.encode_png(np.full((4, 4, 3), 7, np.uint8))
    hub.handlers[("responses", "meta")] = [
        Obj(
            output=[Obj(type="reasoning"), Obj(type="image_generation_call", result=base64.b64encode(out_png).decode())]
        )
    ]
    res = providers.generate_image("show the fix", [PNG_64x48, PNG_64x48])
    kw = hub.calls_for("responses")[0]
    assert kw["model"] == "muse-image-1.0" and kw["store"] is False
    assert kw["tools"] == [{"type": "image_generation", "output_format": "png"}]
    (msg,) = kw["input"]
    assert msg["role"] == "user" and msg["content"][0] == {"type": "input_text", "text": "show the fix"}
    assert [p["type"] for p in msg["content"][1:]] == ["input_image", "input_image"]
    assert res.data == out_png and res.mime == "image/png" and res.mode == "live" and res.usd == 0.01
    hub.handlers[("responses", "meta")] = [Obj(output=[])]
    with pytest.raises(providers.ProviderError, match="no image"):
        providers.generate_image("x")
    assert hub.calls_for("responses")[-1]["input"] == "x"


def test_voice_transcription_request(monkeypatch: pytest.MonkeyPatch, events: list[Any]) -> None:
    monkeypatch.setenv("MODEL_API_KEY", "k-meta-000000")
    seen: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200, json={"sessionId": "s", "transcript": " hook ko 1 mm mota karo ", "audioDurationMs": 20_000}
        )

    clients.set_http_transport(httpx.MockTransport(handle))
    wav = media.silent_wav(0.5)
    with providers.job_context("j", events.append):
        t = providers.transcribe(wav, "audio/wav", language_hint="hinglish")
    req = seen[0]
    assert str(req.url) == "https://api.meta.ai/v1/asr/transcribe"
    assert req.headers["authorization"] == "Bearer k-meta-000000"
    assert req.headers["accept"] == "application/json"
    body = req.content.decode("latin-1")
    assert 'name="request"' in body and 'name="audio"' in body
    request_json = json.loads(body.split("application/json\r\n\r\n", 1)[1].split("\r\n--", 1)[0])
    assert request_json == {
        "model": "muse-voice-transcribe-1.0",
        "audioEncoding": "WAV",
        "mode": "PUSH_TO_TALK",
        "languageBias": ["Hindi", "English"],
    }
    assert t.text == "hook ko 1 mm mota karo" and t.duration_ms == 20_000 and t.mode == "live"
    assert t.usd == pytest.approx(0.18 * 20 / 3600)
    assert events[0].usd == pytest.approx(t.usd)


def test_voice_http_error_is_classified(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MODEL_API_KEY", "k-meta-000000")
    monkeypatch.setenv("PROVIDER_MAX_RETRIES", "0")
    clients.set_http_transport(httpx.MockTransport(lambda r: httpx.Response(413, text="too big")))
    with pytest.raises(providers.ProviderError, match="HTTP 413"):
        providers.transcribe(media.silent_wav(0.1), "audio/wav")


def test_modal_sam3_service_rle_matches_client_decoder() -> None:
    """The Modal app can't be imported here (no `modal` in this env), so run its encoder from source."""
    import ast
    from pathlib import Path

    src = Path(__file__).resolve().parents[4] / "infra" / "modal" / "sam3.py"
    tree = ast.parse(src.read_text())
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "rle_encode")
    ns: dict[str, Any] = {}
    exec(compile(ast.Module(body=[fn], type_ignores=[]), str(src), "exec"), ns)
    rng = np.random.default_rng(1)
    for shape in [(9, 13), (1, 4)]:
        m = rng.random(shape) > 0.6
        m[0, 0] = True
        assert np.array_equal(media.rle_decode(ns["rle_encode"](m)), m)
