"""The judge's 1–5 scorecard: advisory only, saved to judge.json (never to verification.json), bad scores dropped."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from services.agent import orchestrator, providers, service
from services.agent.orchestrator import RunOptions
from services.agent.providers import ModelRequest, ProviderError
from services.agent.tests import synth_samples as S


@pytest.fixture(scope="module")
def spacer(tmp_path_factory: pytest.TempPathFactory) -> Path:
    spec = next(s for s in S.SAMPLES if s.id == "spacer-01")
    return S.write_sample(spec, tmp_path_factory.mktemp("judge"))


def _run(path: Path) -> Any:
    sample = service.load_sample(path)
    o = RunOptions(
        question_timeout_s=0.0, mat_id=str(sample.meta["mat_id"]), package=False, learn=False, fix_mode="pipeline"
    )
    return service.start_fix_job(sample.photos, service.sample_job_input(sample.meta), sync=True, options=o)


def test_parse_drops_bad_scores_and_keeps_vetoes() -> None:
    res = orchestrator.parse_judge_reply(
        {
            "vetoes": [{"feature": "hole_1", "issue": "missing", "severity": "blocking"}, {"feature": "x"}],
            "scores": [
                {"criterion": "outline", "score": 9, "reason": "too high"},
                {"criterion": "colour", "score": 3, "reason": "not a criterion"},
                {"criterion": "features", "score": 4, "reason": "holes match"},
                {"criterion": "features", "score": 2, "reason": "a second score for the same criterion"},
                {"criterion": "fit", "score": 3.0, "reason": "x" * 400},
                "garbage",
            ],
            "notes": "ok",
        },
        model="m",
        mode="live",
    )
    assert [v.feature for v in res.vetoes] == ["hole_1"]
    assert [(s.criterion, s.score) for s in res.scores] == [("features", 4), ("fit", 3)]
    assert len(res.scores[1].reason) <= 200
    assert res.notes == "ok" and res.model == "m" and res.mode == "live"
    assert orchestrator.parse_judge_reply({}, model=None, mode="mock").scores == []  # a reply without scores is fine


def test_score_summary_label() -> None:
    res = orchestrator.parse_judge_reply(
        {
            "vetoes": [],
            "notes": "",
            "scores": [
                {"criterion": c, "score": n, "reason": "r"}
                for c, n in (("outline", 4), ("features", 3), ("printability", 5), ("fit", 4))
            ],
        },
        model=None,
        mode="mock",
    )
    assert res.score_label() == "scores o4 f3 p5 u4"
    assert orchestrator.parse_judge_reply({}, model=None, mode="mock").score_label() == ""


def test_mock_judge_scores_are_rule_based() -> None:
    from services.agent import mock_brain

    good = mock_brain.judge(
        ModelRequest(
            messages=[],
            mock_context={
                "photo_openings": 1,
                "model_openings": 1,
                "hausdorff_mm": 0.2,
                "valid": True,
                "min_wall_mm": 2.0,
            },
        )
    )
    bad = mock_brain.judge(
        ModelRequest(
            messages=[], mock_context={"photo_openings": 2, "model_openings": 1, "hausdorff_mm": 1.4, "valid": False}
        )
    )
    g = {s["criterion"]: s["score"] for s in good["scores"]}
    b = {s["criterion"]: s["score"] for s in bad["scores"]}
    assert set(g) == set(b) == {"outline", "features", "printability", "fit"}
    assert g["outline"] > b["outline"] and g["features"] > b["features"] and g["printability"] > b["printability"]
    assert g["fit"] == 3 and all("mock" in s["reason"] for s in good["scores"])


@pytest.mark.slow
def test_judge_scores_parsed_and_saved(spacer: Path) -> None:
    job = _run(spacer)
    assert job.events[-1].t == "done", [e for e in job.events if e.t == "log"]
    data = job.read_json("judge.json")
    assert data is not None and data["mode"] == "mock"
    assert {s["criterion"] for s in data["scores"]} == {"outline", "features", "printability", "fit"}
    assert all(1 <= s["score"] <= 5 for s in data["scores"])
    assert isinstance(data["vetoes"], list) and "notes" in data
    labels = [e.label for e in job.events if e.t == "stage" and e.stage == "judge" and e.status != "start"]
    assert labels and "scores o" in labels[-1]
    assert "scores" not in (job.read_json("verification.json") or {})  # the judge's opinion is not the verdict


@pytest.mark.slow
def test_bad_scores_dropped(spacer: Path) -> None:
    def judge(req: ModelRequest) -> dict[str, Any]:
        return {
            "vetoes": [],
            "notes": "test judge",
            "scores": [
                {"criterion": "outline", "score": 9, "reason": "out of range"},
                {"criterion": "beauty", "score": 3, "reason": "unknown criterion"},
                {"criterion": "features", "score": 4, "reason": "holes match"},
            ],
        }

    providers.register_mock("judge", judge, replace=True)
    job = _run(spacer)
    assert job.events[-1].t == "done"
    data = job.read_json("judge.json")
    assert [(s["criterion"], s["score"]) for s in data["scores"]] == [("features", 4)]


@pytest.mark.slow
def test_judge_provider_error_gives_no_scorecard(spacer: Path) -> None:
    def judge(req: ModelRequest) -> dict[str, Any]:
        raise ProviderError("judge down")

    providers.register_mock("judge", judge, replace=True)
    job = _run(spacer)
    done = job.events[-1]
    assert done.t == "done" and done.status in ("verified", "best_effort")
    assert job.read_json("judge.json") is None
    assert any(e.t == "log" and "judge unavailable" in e.msg for e in job.events)
