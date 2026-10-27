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
        part = make_part("spacer", slug, params={"height": 5.0 + len(get_registry().slugs())})  # distinct parts
        part.provenance.job_id = job_id
        get_registry().upsert_part(part)
        return part

    return SimpleNamespace(
        list_demo_samples=lambda: [
            {"id": "spacer-easy-01", "title": "Spacer", "family_hint": "spacer"},
            {"id": "spacer-easy-02", "title": "Spacer 2", "family_hint": "spacer"},
            {"id": "bad-glare-01", "title": "Glare", "family_hint": "clip"},
            {"id": "ref-id1-card", "title": "ID-1 card", "family_hint": None, "kind": "reference_object"},
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
    # product names from the part's own knobs, never the sample folder; a reference object is tagged, not listed
    assert out["seeded"] == ["spacer-8mm", "spacer-8mm-height6mm", "reference-spacer-standoff"]
    assert out["failed"] == ["bad-glare-01: best effort 5.00 mm > 2 mm, not published"]
    reg = get_registry()
    part = reg.get_part("spacer-8mm")
    assert part is not None and part.title == "Spacer, 8 mm" and part.provenance.origin == DataOrigin.synthetic
    assert reg.thumbnail("spacer-8mm") is not None
    assert {p.slug for p in reg.search("", role="part", limit=50)[0]} == {"spacer-8mm", "spacer-8mm-height6mm"}
    assert [p.slug for p in reg.search("", role="reference")[0]] == ["reference-spacer-standoff"]
    assert not any(s.startswith(("spacer-easy", "demo-")) for s in reg.slugs())
    index = json.loads((jobs.REPLAYS_DIR / S.INDEX_NAME).read_text())
    assert set(index) == {"spacer-easy-01", "spacer-easy-02", "bad-glare-01", "ref-id1-card"}  # every run is a replay
    assert all((jobs.REPLAYS_DIR / jid / "run.jsonl").exists() for jid in index.values())

    again = S.seed(log=lambda m: None)
    assert again["seeded"] == [] and set(again["skipped"]) >= {"spacer-8mm", "spacer-8mm-height6mm"}
    assert fake.calls["runs"] == 4  # nothing re-ran
    assert S.seed(retry=True, max_error_mm=None, log=lambda m: None)["seeded"] == ["spacer-8mm-height8mm"]
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
    assert out["seeded"] == ["spacer-12mm"], out
    part = get_registry().get_part("spacer-12mm")
    assert part is not None and part.provenance.origin == DataOrigin.synthetic and part.title == "Spacer, 12 mm"
    assert get_registry().thumbnail("spacer-12mm") is not None
    again = S.seed(include_real=False, log=lambda m: None)
    assert again["skipped"] == ["spacer-12mm"] and again["seeded"] == []
