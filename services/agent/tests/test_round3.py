"""Round-3 job features end to end in mock mode: narrated walk-around, buy-or-print card, unchecked knobs labelled.

Uses the committed SYNTHETIC knob demo sample (top + side photos and a silent walk-around clip) plus a short
voice note, so the narration path runs. Only the photos and meta.json are read, never gt.yaml.
"""

from __future__ import annotations

import io
import json
import wave
from typing import Any

import pytest

from services.agent import providers, service
from services.agent.orchestrator import FixRun, RunOptions
from services.common.paths import REPO_ROOT

SAMPLE = REPO_ROOT / "data" / "synthetic" / "samples" / "demo-knob"
POINTS = {
    "function": "the knob that turns the oven's thermostat",
    "mating_feature": "the D-shaft",
    "break_description": "",
    "features": [
        {"name": "knob top", "kind": "tab", "t_s": 0.53, "x_px": 966.6, "y_px": 505.3, "said": "this is the top"},
        {"name": "off the part", "kind": "tab", "t_s": 0.53, "x_px": 40.0, "y_px": 40.0, "said": "and here"},
    ],
    "notes": "",
}


def _wav(seconds: float = 0.5, rate: int = 16000) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x00\x00" * int(seconds * rate))
    return buf.getvalue()


@pytest.fixture(scope="module")
def job() -> Any:
    """One mock job on the real clip (the synthetic photo and clip place the part differently on the mat, like a user
    who moves it: points are checked against the clip's own footprint and nothing is merged into the top view)."""
    if not (SAMPLE / "orbit.mp4").exists():
        pytest.skip("synthetic demo sample missing")
    providers.register_mock("narrate", lambda req: POINTS)
    try:
        sample = service.load_sample(SAMPLE)
        photos = {k: v for k, v in sample.photos.items() if k in ("top", "side")}
        photos["orbit"] = (SAMPLE / "orbit.mp4").read_bytes()
        photos["narration"] = _wav()
        ji = service.sample_job_input(sample.meta).model_copy(update={"city": "Pune"})
        opts = RunOptions(question_timeout_s=0.0, mat_id=str(sample.meta["mat_id"]), learn=False)
        return service.start_fix_job(photos, ji, sync=True, options=opts)
    finally:
        providers.unregister_mock("narrate")


@pytest.mark.slow
def test_narrated_walkaround_points_are_checked_and_measured(job: Any) -> None:
    calls = {e.stage for e in job.events if e.t == "model_call"}
    assert {"narrate", "transcribe", "segment_points"} <= calls
    assert any(e.t == "artifact" and e.kind == "narration" and "voice note" in e.label for e in job.events)
    assert any(e.t == "artifact" and e.kind == "narration" and "walk-around narration" in e.label for e in job.events)
    rec = job.read_json("narration.json")
    pts = {p["name"]: p for p in rec["points"]}
    assert pts["knob top"]["ok"] and pts["knob top"]["frame_index"] == 8, pts["knob top"]["reason"]
    assert (
        not pts["off the part"]["ok"] and pts["off the part"]["reason"] == "the point is not on the part in that frame"
    )
    (m,) = rec["measured"]
    assert m["id"] == "knob top" and m["provenance"] == "pointed by Spark (narration)" and m["ok"], m
    assert rec["narration"]["mode"] == "mock" and rec["narration"]["transcript"]
    assert rec["same_placement"] is False and rec["merged"] == []
    labels = [e.label for e in job.events if e.t == "stage" and e.stage == "measure" and e.status == "ok"]
    assert any("narration: 1/2 pointed feature(s) kept" in x for x in labels)
    logs = " | ".join(e.msg for e in job.events if e.t == "log")
    assert "narrated point 'off the part' dropped" in logs


@pytest.mark.slow
def test_buy_or_print_card_and_unchecked_labels(job: Any) -> None:
    v = job.read_json("verification.json")
    card = job.read_json("buy_or_print.json")
    assert card is not None and card["status"] == v["status"] and card["mode"] == "mock"
    assert card["lookup"]["city"] == "Pune" and card["lookup"]["offers"] == []
    assert card["prints"] and card["prints"][0]["grams"] > 0
    assert any(e.t == "model_call" and e.stage == "buy_lookup" for e in job.events)
    assert any(e.t == "artifact" and e.kind == "buy_or_print" for e in job.events)
    assert "unchecked" in v and all(u["source"] == "inferred" for u in v["unchecked"])
    assert json.loads(json.dumps(v))  # still plain JSON


def test_intent_for_models_carries_narrated_words_only() -> None:
    run = FixRun.__new__(FixRun)
    run.job = type("J", (), {"input": type("I", (), {"intent": "Fix this clip."})()})()  # minimal stand-in
    run.narration = None
    assert run.intent_for_models() == "Fix this clip."
    run.narration = providers.Narration("holds the rail", "", "left tab snapped", [], mode="live")
    text = run.intent_for_models()
    assert "function: holds the rail" in text and "break: left tab snapped" in text and "never a measurement" in text
