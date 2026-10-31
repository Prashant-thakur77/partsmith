"""Printing facts stored with a job under older rules are re-derived (TEST DATA: a template program, a tmp home)."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from partsmith_schemas import JobInput

from services.agent import buy_or_print as bop
from services.agent.jobs import Job, JobManager
from services.agent.templates import get_template
from services.geom_worker.bake import FACTS_RULE
from services.geom_worker.program import set_defaults


@pytest.fixture()
def manager(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[JobManager]:
    monkeypatch.setenv("PARTSMITH_HOME", str(tmp_path / "home"))
    m = JobManager(root=tmp_path / "runs")
    yield m
    m.shutdown()


def _spacer_job(manager: JobManager, *, replay: bool = False) -> Job:
    job = manager.create("fix", JobInput())
    job.write_text("part.py", set_defaults(get_template("spacer").code, {"outer_d": 7.0, "height": 12.0}))
    stale = {"bbox_mm": [7.0, 7.0, 12.0], "volume_mm3": 350.0, "mass_g_pla": 0.43, "mass_g_petg": 0.44,
             "print_minutes_est": 4.0, "supports_needed": True, "orientation": "-Z: mounting face (Z=0) on the bed"}  # fmt: skip
    job.write_json("facts.json", stale)
    job.summary.is_replay = replay
    return job


def test_stale_job_facts_are_rederived_and_marked(manager: JobManager) -> None:
    job = _spacer_job(manager)
    facts = bop.job_facts(job)
    assert facts is not None and not facts.supports_needed  # an upright spacer's 45 deg chamfers need no supports
    assert job.read_json(bop.FACTS_RULE_FILE) == {"rule": FACTS_RULE}
    assert job.read_json("facts.json")["supports_needed"] is False


def test_a_replay_is_never_rewritten(manager: JobManager) -> None:
    job = _spacer_job(manager, replay=True)
    facts = bop.job_facts(job)
    assert facts is not None and not facts.supports_needed
    assert job.read_json("facts.json")["supports_needed"] is True and job.read_json(bop.FACTS_RULE_FILE) is None
