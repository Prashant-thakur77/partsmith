from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from partsmith_schemas import DataOrigin, DoneEvent, JobInput, StageEvent

from services.agent import jobs
from services.registry import seed as S
from services.registry.store import get_registry
from services.registry.tests.fixtures import make_part


def _fake_service() -> SimpleNamespace:
    """Pipeline stand-in: each 'run' finishes at once; publish makes a part from a template (TEST DATA)."""
    mgr = jobs.JobManager()
    calls: dict[str, int] = {"runs": 0}

    def start_demo_job(sample_id: str, *, sync: bool = False) -> jobs.Job:
        calls["runs"] += 1
        job = mgr.create("fix", JobInput(origin=DataOrigin.synthetic), title=f"{sample_id} (synthetic)")

        bad = sample_id.startswith("bad")

        def runner(j: jobs.Job) -> None:
            j.emit(StageEvent(job=j.id, stage="measure", status="ok"))
            j.emit(
                DoneEvent(
                    job=j.id,
                    verified=not bad,
                    status="best_effort" if bad else "verified",
                    summary={"max_error_mm": 5.0 if bad else 0.1},
                )
            )

        return mgr.run_sync(job, runner)

    def publish(job_id: str, *, slug: str | None = None) -> Any:
        part = make_part("spacer", slug)
        part.provenance.job_id = job_id
        get_registry().upsert_part(part)
        return part

    return SimpleNamespace(
        list_demo_samples=lambda: [
            {"id": "spacer-easy-01", "title": "Spacer", "family_hint": "spacer"},
            {"id": "spacer-easy-02", "title": "Spacer 2", "family_hint": "spacer"},
            {"id": "bad-glare-01", "title": "Glare", "family_hint": "clip"},
        ],
        start_demo_job=start_demo_job,
        publish=publish,
        calls=calls,
        manager=lambda: mgr,
    )


def test_seed_is_idempotent_and_exports_replays(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    fake = _fake_service()
    monkeypatch.setattr(S, "_service", lambda: fake)
    monkeypatch.setattr(S, "SAMPLES_DIR", tmp_path / "no-committed-samples")
    out = S.seed(log=lambda m: None)
    assert out["seeded"] == ["spacer-easy-01", "spacer-easy-02"]
    assert out["failed"] == ["bad-glare-01: best effort 5.00 mm > 2 mm, not published"]
    assert get_registry().get_part("bad-glare-01") is None
    reg = get_registry()
    part = reg.get_part("spacer-easy-01")
    assert part is not None and part.provenance.origin == DataOrigin.synthetic
    assert reg.thumbnail("spacer-easy-01") is not None
    index = json.loads((jobs.REPLAYS_DIR / S.INDEX_NAME).read_text())
    assert set(index) == {"spacer-easy-01", "spacer-easy-02", "bad-glare-01"}  # every finished run is a replay
    assert all((jobs.REPLAYS_DIR / jid / "run.jsonl").exists() for jid in index.values())

    again = S.seed(log=lambda m: None)
    assert again["seeded"] == [] and again["skipped"] == ["spacer-easy-01", "spacer-easy-02", "bad-glare-01"]
    assert fake.calls["runs"] == 3  # nothing re-ran
    assert S.seed(retry=True, max_error_mm=None, log=lambda m: None)["seeded"] == ["bad-glare-01"]
    assert S.seed(if_empty=True, log=lambda m: None) == {"seeded": [], "skipped": [], "failed": []}


@pytest.mark.slow
def test_seed_runs_the_real_pipeline(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """End to end with the real agent service on a rendered SYNTHETIC sample (mock providers)."""
    service = pytest.importorskip("services.agent.service")
    from services.agent.tests.synth_samples import SampleSpec, write_sample

    root = tmp_path / "samples"
    write_sample(
        SampleSpec(
            id="spacer-seed-01",
            template="spacer",
            params={"outer_d": 12.0, "height": 8.0},
            thickness_mm=8.0,
            family_hint="spacer",
        ),
        root,
    )
    from PIL import Image

    png = root / "spacer-seed-01" / "top.png"  # the folder format wants top.jpg
    Image.open(png).convert("RGB").save(png.with_suffix(".jpg"), quality=95)
    png.unlink()
    monkeypatch.setattr(service, "SAMPLES_DIRS", (root,))
    monkeypatch.setattr(S, "SAMPLES_DIR", root)
    out = S.seed(include_real=False, log=lambda m: None)
    assert out["seeded"] == ["spacer-seed-01"], out
    part = get_registry().get_part("spacer-seed-01")
    assert part is not None and part.provenance.origin == DataOrigin.synthetic
    assert get_registry().thumbnail("spacer-seed-01") is not None
    again = S.seed(include_real=False, log=lambda m: None)
    assert again["skipped"] == ["spacer-seed-01"] and again["seeded"] == []
