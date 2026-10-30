"""Reviewer rounds: a linked follow-up job that starts from the reviewed model and gives the fixer the person's pins.

SYNTHETIC photos, every model stage a deterministic mock. Pins are placed with the parent's own rectified grid."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from partsmith_schemas import Pin

from services.agent import jobs, mock_brain, orchestrator, providers, service
from services.agent.jobs import JobManager
from services.agent.orchestrator import RunOptions
from services.agent.providers import ModelRequest
from services.agent.tests import synth_samples as S
from services.common import blobs
from services.geom_worker.program import parse_params

pytestmark = pytest.mark.slow


@pytest.fixture(scope="module")
def spacer(tmp_path_factory: pytest.TempPathFactory) -> Path:
    spec = next(s for s in S.SAMPLES if s.id == "spacer-01")
    return S.write_sample(spec, tmp_path_factory.mktemp("review"))


def _run(path: Path) -> Any:
    sample = service.load_sample(path)
    o = RunOptions(question_timeout_s=0.0, mat_id=str(sample.meta["mat_id"]), package=False, fix_mode="pipeline")
    return service.start_fix_job(sample.photos, service.sample_job_input(sample.meta), sync=True, options=o)


@pytest.fixture(scope="module")
def parent(spacer: Path) -> Any:
    job = _run(spacer)
    assert job.events[-1].t == "done" and job.summary.status == "done"
    return job


def edge_pin(job: Any, note: str = "the outer edge should be further out") -> Pin:
    """A pin on the measured outline of `job`'s top view, as the web would send it (normalised on the rectified image)."""
    rect = job.read_json("rectified.json")
    top = job.read_json("measurements.json")["top"]
    M = np.asarray(top["part_to_mat"], dtype=np.float64)
    x, y = top["outline_mm"][0]
    mx, my = (M @ np.array([x, y, 1.0]))[:2]
    size = orchestrator.image_size(blobs.get(rect["sha"]))
    assert size is not None
    ppm, (x0, y0) = float(rect["px_per_mm"]), rect["origin_mm"]
    return Pin(id=1, u=(mx - x0) * ppm / size[0], v=(my - y0) * ppm / size[1], note=note)


def test_review_round_starts_from_parent_model(parent: Any) -> None:
    child = service.start_review_job(parent.id, 1, [edge_pin(parent)], "make it match the photo", sync=True)
    assert child.events[-1].t == "done", [e for e in child.events if e.t == "log"]
    assert child.input.parent_job == parent.id and child.input.review_round == 1
    assert child.input.photo_shas == parent.input.photo_shas
    assert child.summary.title.endswith("· review round 1")
    assert child.events[-1].summary["parent_job"] == parent.id
    calls = {e.stage for e in child.events if e.t == "model_call"}
    assert not calls & {"understand", "plan", "build"}, calls  # no new reading, plan or program
    first_code = next(e for e in child.events if e.t == "artifact" and e.kind == "code" and e.iter == 1)
    first = {s.name: float(s.default) for s in parse_params(blobs.get(first_code.sha).decode())}
    assert first == pytest.approx(parent.read_json("values.json"))
    rr = child.read_json("review_round.json")
    assert rr["parent_job"] == parent.id and rr["round"] == 1 and rr["note"] == "make it match the photo"
    (pin,) = rr["pins"]
    assert pin["id"] == 1 and pin["mat_mm"] is not None and pin["part_mm"] is not None
    assert isinstance(pin["before_mm"], float) and pin["before_mm"] < 1.0  # on the outline of a verified model
    assert pin["after_mm"] is None or isinstance(pin["after_mm"], float)
    first_build = next(i for i, e in enumerate(child.events) if e.t == "iteration")
    fixes = [e for e in child.events[first_build:] if e.t == "stage" and e.stage == "fix" and e.status != "start"]
    assert fixes and "Reviewer round 1" in fixes[0].label  # one fix round even though the parent verified
    assert any(e.t == "log" and e.msg.startswith("Reviewer round 1: 1 pin(s)") for e in child.events)
    assert not (parent.dir / "review_round.json").exists()


def test_reviewer_notes_reach_fixer(parent: Any) -> None:
    seen: list[ModelRequest] = []

    def fix(req: ModelRequest) -> dict[str, Any]:
        seen.append(req)
        return mock_brain.fix(req)

    providers.register_mock("fix", fix, replace=True)
    pin = edge_pin(parent, note="this corner is square on the real part")
    child = service.start_review_job(parent.id, 1, [pin], "", sync=True)
    assert child.events[-1].t == "done"
    hits = [r for r in seen if "Reviewer pin 1" in r.messages[-1]["content"]]
    assert hits, [r.messages[-1]["content"][-400:] for r in seen]
    text = hits[0].messages[-1]["content"]
    assert "this corner is square on the real part" in text and "local mismatch" in text
    assert len(hits[0].images) >= 1  # the pin crop rides along with the overlays


def test_review_round_from_replay_writes_no_replay_files(
    parent: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(jobs, "REPLAYS_DIR", tmp_path / "replays")
    monkeypatch.setattr(blobs, "REPLAY_BLOBS", tmp_path / "replays" / "_blobs")
    jobs.export_replay(parent)
    replay_dir = tmp_path / "replays" / parent.id

    def listing() -> dict[str, float]:
        return {str(p.relative_to(replay_dir)): os.stat(p).st_mtime for p in replay_dir.rglob("*")}

    before = listing()
    old = service.manager()
    service.reset_manager(JobManager(root=tmp_path / "runs"))  # the live parent is gone: only the replay remains
    try:
        rp = service.manager().get(parent.id)
        assert rp is not None and rp.summary.is_replay
        child = service.start_review_job(parent.id, 1, [edge_pin(rp)], "", sync=True)
        assert child.events[-1].t == "done"
        assert child.dir.parent == tmp_path / "runs" and child.input.parent_job == parent.id
        assert listing() == before
    finally:
        service.reset_manager(JobManager(root=old.root))


def test_review_job_needs_a_finished_parent_with_photos(parent: Any) -> None:
    with pytest.raises(KeyError):
        service.start_review_job("j_nope", 1, [], "x", sync=True)


def test_lessons_used_recorded(spacer: Path) -> None:
    from services.registry.store import get_registry

    reg = get_registry()
    lid = reg.add_lesson("spacer", "spacer: check the bore against the measured diameter first", {"job_id": "j_test"})
    reg.set_lesson_status(lid, "promoted", "test")
    try:
        job = _run(spacer)
        used = job.read_json("lessons_used.json")
        assert used is not None and used["family"] == "spacer" and lid in used["lesson_ids"]
    finally:
        reg.set_lesson_status(lid, "rejected", "test")
