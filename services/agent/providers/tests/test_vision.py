"""SAM 3.1 point/box prompts and video tracking: mocks on real pixels, live shapes on fake transports."""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from typing import Any

import httpx
import numpy as np
import pytest
from meta_sam_parser._mask_codec import _encode_raster

from services.agent import providers
from services.agent.providers import clients, media, pricing, vision

from .conftest import FakeHub


def _part_png() -> bytes:
    img = np.full((60, 80, 3), 235, np.uint8)
    img[10:50, 10:70] = 30  # dark plate
    img[25:35, 35:45] = 235  # light hole showing the mat
    return media.encode_png(img)


def test_object_prompt_tokens() -> None:
    text = vision.object_prompt(80, 60, [(40.4, 30.0)], [(12, 12)], (5, 5, 90, 59))
    assert text == (
        "<0f>1<|box;x1=5;y1=5;x2=79;y2=59;w=80;h=60|><|point;x=40;y=30;w=80;h=60|>-<|point;x=12;y=12;w=80;h=60|>"
    )


def test_mock_points_flood_fill_hole_body_and_box() -> None:
    png = _part_png()
    ((hole, score),) = providers.segment_points(png, [(40, 30)])
    assert score == 0.5 and hole.sum() == 100 and hole[25:35, 35:45].all()
    ((body, _),) = providers.segment_points(png, [(15, 15)], points_neg=[(40, 30)])
    assert body.sum() == 40 * 60 - 100 and not body[30, 40]
    ((clipped, _),) = providers.segment_points(png, [(15, 15)], box=(10, 10, 29, 49))
    assert clipped.sum() == 20 * 40
    with pytest.raises(ValueError, match="positive point or a box"):
        providers.segment_points(png, [])


def test_points_live_request(monkeypatch: pytest.MonkeyPatch, hub: FakeHub, events: list[Any]) -> None:
    monkeypatch.setenv("MODEL_API_KEY", "k-meta-000000")
    payload = _encode_raster([1] * 12, 4, 3)
    text = f"<0f>1<|box;x1=35;y1=25;x2=44;y2=34;w=80;h=60;c=0.91|><|mask;x=0;y=0;data=3,4,{payload}|>"
    hub.handlers[("responses", "meta")] = [
        [{"type": "response.content_part.done", "part": {"type": "output_text", "text": text}}]
    ]
    with providers.job_context("j", events.append):
        ((mask, score),) = providers.segment_points(_part_png(), [(40, 30)], [(15, 15)])
    kw = hub.calls_for("responses")[0]
    assert kw["model"] == "sam-3.1" and kw["stream"] is True
    prompt = kw["input"][0]["content"][0]["text"]
    assert prompt.startswith("<0f>1<|point;x=40;y=30;w=80;h=60|>-<|point;")
    assert mask[25:35, 35:45].all() and mask.sum() == 100 and score == pytest.approx(0.91)
    assert events[0].stage == "segment_points" and events[0].usd == pytest.approx(pricing.SAM_31_PER_IMAGE_USD)


def _clip(n: int = 10, fps: float = 10.0) -> bytes:
    import cv2

    with tempfile.TemporaryDirectory() as tmp:
        path = str(Path(tmp) / "clip.mp4")
        writer = cv2.VideoWriter(path, cv2.VideoWriter.fourcc(*"mp4v"), fps, (64, 48))
        for i in range(n):
            frame = np.full((48, 64, 3), 230, np.uint8)
            frame[14:34, 5 + 3 * i : 25 + 3 * i] = 20
            writer.write(frame)
        writer.release()
        return Path(path).read_bytes()


def test_video_mock_runs_per_frame_segmentation() -> None:
    frames = providers.segment_video(_clip(), "video/mp4", "black block", fps=5)
    assert frames, "expected per-frame masks"
    idx = [f.frame_idx for f in frames]
    assert idx == sorted(idx) and all(f.mask.shape == (48, 64) for f in frames)
    expected_fps = 5.0 if shutil.which("ffmpeg") else 10.0  # resampled only when ffmpeg is present
    assert frames[1].t_s == pytest.approx(frames[1].frame_idx / expected_fps)
    assert all(abs(int(f.mask.sum()) - 400) < 120 for f in frames)


def test_video_needs_ffmpeg_for_webm(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(shutil, "which", lambda name: None)
    with pytest.raises(ValueError, match="MP4/MOV only and ffmpeg is not installed"):
        providers.segment_video(b"\x1aE\xdf\xa3 webm", "video/webm;codecs=vp9", "part")


def test_video_live_meta_upload_and_out_of_order_frames(
    monkeypatch: pytest.MonkeyPatch, hub: FakeHub, events: list[Any]
) -> None:
    monkeypatch.setenv("MODEL_API_KEY", "k-meta-000000")
    monkeypatch.setattr(shutil, "which", lambda name: None)  # MP4 passes through untouched
    clip = _clip(6, fps=6.0)
    payload = _encode_raster([1] * 4, 2, 2)

    def line(frame: int, x: int, c: float) -> str:
        return f"<{frame}f>1<|box;x1={x};y1=10;x2={x + 1};y2=11;w=64;h=48;c={c}|><|mask;x=0;y=0;data=2,2,{payload}|>"

    text = "\n".join([line(2, 30, 0.7), line(0, 10, 0.9), line(1, 20, 0.8)])
    hub.handlers[("responses", "meta")] = [
        [{"type": "response.content_part.done", "part": {"type": "output_text", "text": text}}]
    ]
    with providers.job_context("j", events.append):
        frames = providers.segment_video(clip, "video/mp4", "part")
    upload = hub.calls_for("files")[0]
    assert upload["purpose"] == "user_data" and upload["file"][2] == "video/mp4" and upload["file"][1] == clip
    content = hub.calls_for("responses")[0]["input"][0]["content"]
    assert content[1]["type"] == "input_video" and content[1]["file_id"].startswith("file-")
    assert [(f.frame_idx, round(f.t_s, 3), round(f.score, 2)) for f in frames] == [
        (0, 0.0, 0.9),
        (1, 0.167, 0.8),
        (2, 0.333, 0.7),
    ]
    assert frames[0].mask[10:12, 10:12].all() and frames[0].mask.sum() == 4
    assert events[0].usd == pytest.approx(pricing.video_cost_usd("meta", 6)) == pytest.approx(50 * 0.0002)


def test_video_open_weights_service(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPEN_WEIGHTS_ONLY", "1")
    monkeypatch.setenv("SAM3_OPEN_URL", "https://ws--sam3.modal.run")
    mask = np.zeros((48, 64), bool)
    mask[1:3, 1:3] = True
    seen: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        frame = {"frame_idx": 1, "t_s": 0.2, "masks": [{"object_id": "0", "score": 0.6, "rle": media.rle_encode(mask)}]}
        return httpx.Response(200, json={"width": 64, "height": 48, "frames": [frame]})

    clients.set_http_transport(httpx.MockTransport(handle))
    (f,) = providers.segment_video(_clip(4), "video/mp4", "part", fps=5)
    assert seen[0].url.path == "/segment_video" and (f.frame_idx, f.t_s, f.object_id) == (1, 0.2, "0")
    assert np.array_equal(f.mask, mask)


def test_status_rows_for_new_stages() -> None:
    rows = {r["stage"]: r for r in providers.status()}
    for stage in ("fix_agent", "spec_lookup", "segment_points", "segment_video", "reconstruct", "transcribe_stream"):
        assert rows[stage]["mode"] == "mock"
    assert rows["spec_lookup"]["model"] == "muse-wonder-1.0" and rows["fix_agent"]["provider"] == "baseten"
