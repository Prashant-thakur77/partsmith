from __future__ import annotations

from typing import Any

import pytest
from partsmith_schemas.verification import ParamSpec

from services.agent import providers
from services.agent.providers import ModelRequest, media
from services.media import voice

PARAMS = [
    ParamSpec(name="thickness", default=3.0, min=1.2, max=8.0, step=0.1, label="Plate thickness"),
    ParamSpec(name="hole_d", default=4.2, min=2.0, max=8.0, step=0.05, label="Screw hole Ø"),
    ParamSpec(name="hook_thickness", default=1.6, min=0.8, max=4.0, step=0.1, label="Hook thickness"),
    ParamSpec(name="hook_overhang", default=1.2, min=0.6, max=3.0, step=0.1, label="Snap hook overhang"),
    ParamSpec(name="length", default=40.0, min=10.0, max=120.0, step=0.5, label="Overall length"),
    ParamSpec(name="clearance", default=0.2, min=0.0, max=0.6, step=0.05, label="Fit clearance"),
    ParamSpec(
        name="rib_count", default=2, min=0, max=6, step=1, unit="", affects_fit=False, label="Ribs", topology=True
    ),
]


def _map(text: str, values: dict[str, float] | None = None) -> voice.VoiceEditResult:
    return voice.transcribe_and_map(text, PARAMS, values)


def _edits(r: voice.VoiceEditResult) -> dict[str, tuple[float, float]]:
    return {e.param: (e.from_value, e.to) for e in r.edits}


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("hook ko 1 mm mota karo", {"hook_thickness": (1.6, 2.6)}),
        ("hole thoda bada", {"hole_d": (4.2, 4.4)}),
        ("make it 2 mm longer", {"length": (40.0, 42.0)}),
        ("make it two millimetres longer", {"length": (40.0, 42.0)}),
        ("hole ko dedh mm chhota karo", {"hole_d": (4.2, 2.7)}),
        ("set the hole to 5 mm", {"hole_d": (4.2, 5.0)}),
        ("plate thickness 4.5 mm", {"thickness": (3.0, 4.5)}),
        ("thoda dheela karo", {"clearance": (0.2, 0.4)}),
        ("add one more rib", {"rib_count": (2.0, 3.0)}),
        ("make it 1 cm shorter", {"length": (40.0, 30.0)}),
        ("hook ka overhang zero point five mm kam karo", {"hook_overhang": (1.2, 0.7)}),
    ],
)
def test_deterministic_mapping_english_and_hinglish(text: str, expected: dict[str, tuple[float, float]]) -> None:
    r = _map(text)
    assert r.mode == "mock" and r.transcript_mode == "text"
    assert _edits(r) == pytest.approx(expected), (text, r.not_understood)
    assert r.not_understood == []
    assert 0 < r.confidence <= 1


def test_relative_word_without_target_refers_back_and_bare_one_is_not_understood() -> None:
    r = _map("hole thoda bada, nahi thoda chhota")
    assert [e.to for e in r.edits] == pytest.approx([4.4, 4.2])
    lone = _map("thoda chhota")
    assert lone.edits == [] and lone.confidence == 0.0
    assert lone.not_understood and "which dimension" in lone.not_understood[0]


def test_two_edits_in_one_sentence_and_clamping() -> None:
    r = _map("make the hole 20 mm and the plate 2 mm thicker")
    by = {e.param: e for e in r.edits}
    assert by["hole_d"].to == 8.0 and "clamped" in by["hole_d"].reason
    assert by["thickness"].to == pytest.approx(5.0)


def test_ambiguous_and_unknown_are_reported() -> None:
    r = _map("make the hook bigger")  # hook_thickness or hook_overhang?
    assert r.edits == [] and "ambiguous" in r.not_understood[0]
    r2 = _map("paint it red")
    assert r2.edits == [] and r2.not_understood


def test_guard_rejects_unknown_params_and_snaps() -> None:
    edits, rejected = voice.apply_edits(
        [
            {"param": "hole_dia", "to": 5},
            {"param": "hole_d", "to": 5.0123, "reason": "r"},
            {"param": "thickness", "to": "x"},
        ],
        PARAMS,
        {},
    )
    assert [(e.param, e.to) for e in edits] == [("hole_d", 5.0)]
    assert "closest: hole_d" in rejected[0] and "no numeric target" in rejected[1]
    assert voice.snap_clamp(0.33, PARAMS[5]) == (0.35, False)  # snapped to the step, inside the range
    assert voice.snap_clamp(0.9, PARAMS[5]) == (0.6, True)


def test_live_style_mapping_goes_through_guard() -> None:
    providers.register_mock(
        "voice_map",
        lambda req: {
            "edits": [{"param": "length", "to": 500, "reason": "model"}],
            "not_understood": [],
            "confidence": 0.8,
        },
    )
    try:
        r = _map("much longer please")
    finally:
        providers.unregister_mock("voice_map")
    assert r.edits[0].to == 120.0 and "clamped" in r.edits[0].reason


def test_audio_path_uses_transcription_then_mapping() -> None:
    seen: list[ModelRequest] = []

    def fake_transcript(req: ModelRequest) -> str:
        seen.append(req)
        return "hook ko 1 mm mota karo"

    providers.register_mock("transcribe", fake_transcript)
    try:
        r = voice.transcribe_and_map(media.silent_wav(0.3), PARAMS, {"hook_thickness": 2.0})
    finally:
        providers.unregister_mock("transcribe")
    assert r.transcript_mode == "mock" and "MOCK transcript" in r.note
    assert _edits(r) == pytest.approx({"hook_thickness": (2.0, 3.0)})
    assert seen[0].mock_context["language_hint"] == "hinglish"
    d: dict[str, Any] = r.to_dict()
    assert d["edits"][0] == {"param": "hook_thickness", "from": 2.0, "to": 3.0, "reason": '"hook ko 1 mm mota karo"'}


def test_voice_map_request_shape() -> None:
    captured: list[ModelRequest] = []

    def capture(req: ModelRequest) -> dict[str, Any]:
        captured.append(req)
        return {"edits": [], "not_understood": [], "confidence": 0}

    providers.register_mock("voice_map", capture)
    try:
        _map("hole bada", {"hole_d": 5.0})
    finally:
        providers.unregister_mock("voice_map")
    req = captured[0]
    assert req.json_schema == voice.EDIT_SCHEMA and req.messages[0]["role"] == "system"
    assert "hole_d = 5 mm (range 2..8, step 0.05)" in req.messages[1]["content"]
