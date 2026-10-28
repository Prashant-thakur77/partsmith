"""SAM point prompts get negative points (exclude taps, glare); an unsure outline mask asks for a retake."""

from __future__ import annotations

import pytest
from partsmith_schemas import JobInput
from partsmith_schemas.common import DataOrigin
from partsmith_schemas.measurement import CaptureReport

from services.agent import evidence, service
from services.agent.orchestrator import FixRun, RunOptions, _Finish
from services.metrology.measure import with_confidence_check


def _run(answers: dict[str, str] | None = None, points: dict[str, list[dict[str, object]]] | None = None) -> FixRun:
    job = service.manager().create("fix", JobInput(kind="fix", origin=DataOrigin.synthetic), title="negatives test")
    return FixRun(job, RunOptions(answers=dict(answers or {}), question_timeout_s=0.0, points=points))


def test_exclude_taps_are_negatives_not_features() -> None:
    taps = {"top": [{"x": 10.0, "y": 20.0, "kind": "exclude"}, {"x": 50.0, "y": 60.0, "kind": "hole"}]}
    run = _run(points=taps)
    assert evidence.point_negatives(run, "top") == [(10.0, 20.0)]
    assert evidence.point_negatives(run, "side") == []  # taps are top-photo pixels
    assert evidence.point_mask_source() == "mock-flood"  # the mock point segmenter says so


def test_unsure_outline_mask_asks_for_a_retake() -> None:
    low = with_confidence_check(CaptureReport(passed=True, checks=[]), 0.35, "the part's outline in the top photo")
    run = _run()
    run.confidence_retake("top", low)  # unattended: the default is to continue, with a logged warning
    qs = [e for e in run.job.events if e.t == "question"]
    assert [q.id for q in qs] == ["capture.retake.mask"] and "35% sure" in qs[0].text
    assert any(e.t == "log" and "wider ±σ" in e.msg for e in run.job.events)

    asked = _run(answers={"capture.retake.mask": "retake"})
    with pytest.raises(_Finish) as fin:
        asked.confidence_retake("top", low)
    assert fin.value.status == "failed" and "35% sure" in fin.value.summary["retake_reason"]

    sure = with_confidence_check(CaptureReport(passed=True, checks=[]), 0.9, "x")
    quiet = _run()
    quiet.confidence_retake("top", sure)
    assert not [e for e in quiet.job.events if e.t == "question"]
