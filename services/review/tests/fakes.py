"""A scripted stand-in for the agent service (manager + start_review_job) and hand-made finished jobs: TEST DATA."""

from __future__ import annotations

from typing import Any, Literal

from partsmith_schemas import DoneEvent, JobInput, Pin

from services.agent import jobs
from services.registry.tests.fixtures import make_part

SCORES_OK = [{"criterion": c, "score": 4, "reason": "test"} for c in ("outline", "features", "printability", "fit")]


def finish(job: jobs.Job, status: str = "verified", *, family: str = "spacer", judge: Any = "ok") -> jobs.Job:
    part = make_part("spacer", verified=status == "verified")
    job.write_text("part.py", part.code)
    assert part.verification is not None
    job.write_json("verification.json", part.verification)
    job.write_json("partspec.json", {"family": family, "title": "test spacer"})
    if judge == "ok":
        job.write_json("judge.json", {"model": "m", "mode": "mock", "scores": SCORES_OK, "vetoes": [], "notes": ""})
    elif judge is not None:
        job.write_json("judge.json", judge)
    job.emit(DoneEvent(job=job.id, verified=status == "verified", status=status, summary={"family": family}))
    return job


class FakeService:
    def __init__(self) -> None:
        self.mgr = jobs.JobManager()
        self.started: list[tuple[str, int, list[Pin], str]] = []
        self.attachments: list[list[str]] = []

    def manager(self) -> jobs.JobManager:
        return self.mgr

    def new_job(
        self, *, parent: str | None = None, round: int = 0, purpose: Literal["repair", "reference_check"] = "repair"
    ) -> jobs.Job:
        ji = JobInput(parent_job=parent, review_round=round, purpose=purpose)
        job = self.mgr.create("fix", ji, title="test spacer" + (f" · review round {round}" if round else ""))
        job.summary.status = "running"
        job.save_summary()
        return job

    def start_review_job(self, parent_id: str, round: int, pins: list[Pin], note: str, **kw: Any) -> jobs.Job:
        if self.mgr.get(parent_id) is None:
            raise KeyError(f"no job {parent_id!r}")
        self.started.append((parent_id, round, list(pins), note))
        self.attachments.append(list(kw.get("attachments") or []))
        return self.new_job(parent=parent_id, round=round)
