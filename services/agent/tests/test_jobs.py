import threading

import pytest
from partsmith_schemas import DoneEvent, JobInput, QuestionEvent, StageEvent

from services.agent.jobs import JobManager, load_job


@pytest.fixture()
def manager(tmp_path):
    m = JobManager(root=tmp_path)
    yield m
    m.shutdown()


def test_events_persist_and_reload(manager):
    job = manager.create("fix", JobInput(intent="test"))

    def runner(j):
        j.emit(StageEvent(job="", stage="measure", status="start"))
        j.emit(StageEvent(job="", stage="measure", status="ok", ms=12))
        j.emit(DoneEvent(job="", verified=False, status="best_effort", summary={"max_error_mm": 0.8}))

    manager.run_sync(job, runner)
    assert [e.seq for e in job.events] == [0, 1, 2]
    assert job.summary.status == "done" and job.summary.max_error_mm == 0.8
    again = load_job(job.dir)
    assert len(again.events) == 3 and again.summary.status == "done"


def test_question_pauses_until_answer(manager):
    job = manager.create("fix", JobInput())
    got: dict[str, object] = {}

    def runner(j):
        ans = j.ask(QuestionEvent(job="", id="q1", text="Hole depth?", expects="number_mm"), timeout_s=5)
        got["value"] = ans.value
        j.emit(DoneEvent(job="", verified=False, status="best_effort"))

    t = threading.Thread(target=manager.run_sync, args=(job, runner))
    t.start()
    for _ in range(100):
        if job.pending_question() is not None:
            break
        threading.Event().wait(0.02)
    assert job.summary.status == "waiting_for_answer"
    job.answer("q1", 4.5)
    t.join(5)
    assert got["value"] == 4.5 and job.summary.status == "done"


def test_runner_exception_marks_failed(manager):
    job = manager.create("fix", JobInput())

    def runner(j):
        raise RuntimeError("boom")

    manager.run_sync(job, runner)
    assert job.summary.status == "failed"
    assert job.events[-1].t == "done"


def test_cancel_unblocks_question(manager):
    job = manager.create("fix", JobInput())

    def runner(j):
        j.ask(QuestionEvent(job="", id="q", text="?"), timeout_s=5)

    t = threading.Thread(target=manager.run_sync, args=(job, runner))
    t.start()
    for _ in range(100):
        if job.pending_question() is not None:
            break
        threading.Event().wait(0.02)
    job.cancel()
    t.join(5)
    assert job.summary.status == "cancelled"


def test_old_titles_say_synthetic_once() -> None:
    from services.agent.jobs import say_synthetic_once

    assert (
        say_synthetic_once("Spacer / standoff (synthetic, clean) (synthetic sample)")
        == "Spacer / standoff (synthetic, clean)"
    )
    assert say_synthetic_once("Hook (synthetic sample)") == "Hook (synthetic sample)"  # the only mention stays
    assert say_synthetic_once("Battery cover (synthetic, paper)") == "Battery cover (synthetic, paper)"


def test_list_shows_a_recorded_run_once_and_replay_only_runs_labelled(tmp_path, monkeypatch):
    """A run that is both local and recorded lists once (local wins); a run that exists only as a recording (a review
    round) is listed too, marked is_replay, so "every job on this instance" really is every job it can open."""
    from services.agent import jobs

    monkeypatch.setattr(jobs, "REPLAYS_DIR", tmp_path / "replays")
    m = JobManager(root=tmp_path / "runs")
    try:
        both = m.create("fix", JobInput(intent="local and recorded"))
        only = m.create("fix", JobInput(intent="recorded only"))

        def finish(j):
            j.emit(DoneEvent(job="", verified=False, status="best_effort"))

        for j in (both, only):
            m.run_sync(j, finish)
            jobs.export_replay(j)
        import shutil

        shutil.rmtree(only.dir)
        fresh = JobManager(root=tmp_path / "runs")
        try:
            listed = fresh.list(50, include_replays=True)
            assert sorted(s.id for s in listed) == sorted([both.id, only.id])
            by = {s.id: s for s in listed}
            assert not by[both.id].is_replay and by[only.id].is_replay
            assert [s.id for s in fresh.list(50)] == [both.id]
        finally:
            fresh.shutdown()
    finally:
        m.shutdown()
