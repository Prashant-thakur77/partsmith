"""Narrated walk-around: Spark proposes words and (time, pixel) points, never sizes; the mock is labelled."""

from __future__ import annotations

import json
from typing import Any

import pytest

from services.agent import providers
from services.agent.providers import narrate

from .conftest import FakeHub

INTENT = "Make a replacement for this broken drawer rail clip."
REPLY: dict[str, Any] = {
    "function": "holds the drawer rail",
    "mating_feature": "the rail's round pin",
    "break_description": "the left tab snapped",
    "features": [
        {"name": "pin hole", "kind": "hole", "t_s": 1.5, "x_px": 900, "y_px": 500, "said": "this hole takes the pin"},
        {"name": "broken tab", "kind": "broken_edge", "t_s": 99.0, "x_px": 1000, "y_px": 520, "said": "it snapped"},
    ],
    "notes": "",
}


def test_mock_is_labelled_and_comes_from_the_intent_only() -> None:
    a = providers.narrate_video(b"clip", "video/mp4", width=1920, height=1080, duration_s=6.0, intent=INTENT)
    b = providers.narrate_video(b"other clip", "video/mp4", width=1920, height=1080, duration_s=6.0, intent=INTENT)
    assert a.mode == "mock" and a.label == narrate.MOCK_NOTE and a.notes[0] == narrate.MOCK_NOTE
    assert a.function.startswith("MOCK:") and "drawer rail clip" in a.function
    assert a.break_description == "MOCK: the intent says it is broken"
    (p,) = a.features
    assert (p["t_s"], p["x_px"], p["y_px"], p["kind"]) == (3.0, 960.0, 540.0, "tab")
    assert a.features == b.features  # deterministic
    assert not any(k.endswith("_mm") for f in a.features for k in f)


def test_fixture_is_cleaned_and_bad_shapes_are_refused() -> None:
    out = providers.narrate_video(b"c", "video/mp4", width=1920, height=1080, duration_s=6.0, fixture=REPLY)
    assert [f["name"] for f in out.features] == ["pin hole", "broken tab"]
    assert out.features[1]["t_s"] == 6.0  # clamped to the clip
    bad = {**REPLY, "features": [{**REPLY["features"][0], "kind": "bore", "diameter_mm": 4.0}]}
    out = providers.narrate_video(b"c", "video/mp4", width=1920, height=1080, duration_s=6.0, fixture=bad)
    assert out.features == [] and any("did not match" in n for n in out.notes)


def test_live_sends_the_clip_as_a_file_with_strict_json(monkeypatch: pytest.MonkeyPatch, hub: FakeHub) -> None:
    monkeypatch.setenv("MODEL_API_KEY", "k-meta-000000")
    text = json.dumps(REPLY)
    lane = {"item_id": "m", "output_index": 0, "content_index": 0}
    done = {"output": [], "usage": {"input_tokens": 5000, "output_tokens": 300}}
    hub.handlers[("responses", "meta")] = [
        [
            {"type": "response.output_text.delta", **lane, "delta": text},
            {"type": "response.completed", "response": done},
        ]
    ]
    events: list[Any] = []
    with providers.job_context("j_test", events.append):
        out = providers.narrate_video(b"\x00\x00\x00\x18ftypmp42clip", "video/mp4", width=1920, height=1080,
                                      duration_s=6.0, intent=INTENT)  # fmt: skip
    assert hub.calls_for("files") and out.mode == "live" and out.function == "holds the drawer rail"
    kw = hub.calls_for("responses")[0]
    assert kw["model"] == "muse-spark-1.3" and kw["text"]["format"]["type"] == "json_schema"
    assert kw["text"]["format"]["strict"] is True and "tool_choice" not in kw
    parts = kw["input"][1]["content"]
    assert parts[1]["type"] == "input_file" and parts[1]["file_id"].startswith("file-")
    assert "1920 x 1080" in parts[0]["text"]
    calls = [e for e in events if getattr(e, "t", None) == "model_call"]
    assert [c.stage for c in calls] == ["narrate"] and calls[0].mode == "live"


def test_live_refuses_non_mp4_before_any_upload(monkeypatch: pytest.MonkeyPatch, hub: FakeHub) -> None:
    monkeypatch.setenv("MODEL_API_KEY", "k-meta-000000")
    with pytest.raises(providers.ProviderError, match="MP4 only"):
        providers.narrate_video(b"\x1aE\xdf\xa3", "video/webm", width=640, height=480, duration_s=4.0)
    assert not hub.calls_for("files") and not hub.calls_for("responses")
