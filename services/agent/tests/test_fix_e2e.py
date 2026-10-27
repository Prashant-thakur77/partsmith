"""End-to-end fix jobs on SYNTHETIC rendered photos, every model stage in deterministic mock mode.

Ground truth (the params used to render) is only used here, by the test, to check the result — never by the agent.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from services.agent import mock_brain, providers, service
from services.agent.jobs import load_job
from services.agent.orchestrator import RunOptions
from services.agent.templates import get_template
from services.agent.tests import synth_samples as S
from services.metrology import testing as T
from services.metrology.fit_check import FIT_OUTLINE_RGB

pytestmark = pytest.mark.slow

SAMPLES = {s.id: s for s in S.SAMPLES}


@pytest.fixture(scope="module")
def sample_root(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("samples")
    for spec in S.SAMPLES:
        S.write_sample(spec, root)
    return root


def _run(root: Path, sid: str, **ji: Any) -> Any:
    sample = service.load_sample(root / sid)
    job_input = service.sample_job_input(sample.meta).model_copy(update=ji)
    opts = RunOptions(question_timeout_s=0.0, mat_id=str(sample.meta["mat_id"]))
    return service.start_fix_job(sample.photos, job_input, sync=True, options=opts)


@pytest.fixture(scope="module")
def jobs(sample_root: Path) -> dict[str, Any]:
    return {sid: _run(sample_root, sid) for sid in SAMPLES}


@pytest.mark.parametrize("sid", list(SAMPLES))
def test_fix_job_reaches_verified_and_replays(jobs: dict[str, Any], sid: str) -> None:
    job = jobs[sid]
    done = job.events[-1]
    assert done.t == "done", [e for e in job.events if e.t == "log"]
    assert done.status == "verified" and done.verified and job.summary.verified
    assert 1 <= done.summary["iterations"] <= 6
    assert done.summary["mode"] == "mock" and done.summary["origin"] == "synthetic"
    assert done.summary["max_error_mm"] <= 0.5
    stages = {e.stage for e in job.events if e.t == "stage" and e.status == "ok"}
    assert {"capture", "measure", "understand", "plan", "build", "execute", "verify", "judge", "package"} <= stages
    assert all(e.label for e in job.events if e.t == "stage")
    calls = [e for e in job.events if e.t == "model_call"]
    assert {"understand", "plan", "build", "judge"} <= {c.stage for c in calls}
    assert all(c.mode == "mock" for c in calls)
    assert all(e.ctx for e in job.events if e.t in ("iteration", "metric", "artifact"))
    iters = [e for e in job.events if e.t == "iteration"]
    assert [e.iter for e in iters] == list(range(1, len(iters) + 1))
    # the verified result matches the hidden ground truth (only this test reads it)
    spec = SAMPLES[sid]
    values = job.read_json("values.json")
    t = get_template(spec.template)
    lp = t.measure_map["length"]
    assert values[lp] == pytest.approx(spec.params[lp], abs=0.3)
    detail = service.detail_of(job)
    assert detail["verification"]["verified"] is True
    assert {"stl", "step", "threemf", "view", "code", "template_pdf", "repair_card"} <= set(detail["artifacts"])
    assert detail["params"] and detail["values"] and detail["code"].startswith("# part.py")
    for name in ("verification.json", "partspec.json", "measurements.json", "part.py", "values.json", "run.jsonl"):
        assert (job.dir / name).exists(), name
    # replay: rebuilding the job from run.jsonl + side files gives the same detail
    again = service.detail_of(load_job(job.dir))
    assert again == detail


def test_some_job_needed_real_fix_rounds(jobs: dict[str, Any]) -> None:
    rounds = {sid: j.events[-1].summary["iterations"] for sid, j in jobs.items()}
    assert max(rounds.values()) >= 2, rounds  # the naive first build is not enough: the loop does work
    edits = [e for j in jobs.values() for e in j.events if e.t == "iteration" and e.edits]
    assert edits and all(e.diff for e in edits)


def test_loop_recovers_from_a_compile_error(sample_root: Path) -> None:
    calls = {"n": 0}

    def flaky_build(req: providers.ModelRequest) -> str:
        calls["n"] += 1
        if req.mock_context.get("previous_error") is None:
            return "```python\nimport os\nPARAMS = {}\n```"  # policy violation: the sandbox check rejects it
        return mock_brain.build(req)

    mock_brain.install()
    providers.register_mock("build", flaky_build)
    job = _run(sample_root, "spacer-01")
    assert calls["n"] >= 2
    logs = [e.msg for e in job.events if e.t == "log"]
    assert any("build attempt 1" in m and "import" in m for m in logs), logs
    assert job.events[-1].status == "verified"


def test_question_pauses_and_resumes(sample_root: Path) -> None:
    sample = service.load_sample(sample_root / "spacer-01")
    ji = service.sample_job_input(sample.meta).model_copy(update={"thickness_mm": None})
    opts = RunOptions(question_timeout_s=60.0, mat_id=str(sample.meta["mat_id"]))
    job = service.start_fix_job(sample.photos, ji, sync=False, options=opts)
    q = None
    for _ in range(600):
        q = job.pending_question()
        if q is not None:
            break
        time.sleep(0.05)
    assert q is not None and q.id == "thickness" and job.summary.status == "waiting_for_answer"
    detail = service.job_detail(job.id)
    assert detail["question"]["id"] == "thickness"
    service.answer(job.id, "thickness", 12.0)
    for _ in range(1200):
        if job.finished:
            break
        time.sleep(0.05)
    assert job.finished and job.events[-1].status == "verified"
    spec = job.read_json("partspec.json")
    assert spec["thickness"] == {"value": 12.0, "source": "user_stated", "sigma_mm": 0.3, "evidence": None}
    assert any(e.t == "answer" and e.value == 12.0 for e in job.events)


def test_refused_class_ends_refused(sample_root: Path) -> None:
    job = _run(sample_root, "latch-01", intent="make me a trigger for a pistol")
    done = job.events[-1]
    assert done.status == "refused" and not done.verified
    assert "firearm" in done.summary["reason"]
    assert not any(e.t == "stage" and e.stage == "build" for e in job.events)


def test_hinglish_voice_edit_rebakes(jobs: dict[str, Any]) -> None:
    job = jobs["spacer-01"]
    before = job.read_json("values.json")
    out = service.edit(job.id, text="bore thoda bada karo")
    assert out["edits"] and out["edits"][0]["param"] == "bore_d"
    assert out["edits"][0]["to"] == pytest.approx(before["bore_d"] + 0.2, abs=1e-6)
    assert out["bake"] is not None and {"view", "stl"} <= set(out["bake"]["artifacts"])
    after = job.read_json("values.json")
    assert after["bore_d"] == pytest.approx(before["bore_d"] + 0.2, abs=1e-6)
    assert any(e.t == "log" and "not re-verified" in e.msg for e in job.events)
    # knob preview bake does not change the job
    br = service.bake_job(job.id, {"height": 14.0}, ("view",))
    assert br.params["height"] == 14.0 and "view" in br.artifacts
    assert job.read_json("values.json") == after


def test_fit_check_passes_on_the_part_lying_on_its_outline(jobs: dict[str, Any]) -> None:
    job = jobs["spacer-01"]
    mat = "screen-m"
    fo = service.fit_outline(job.id, mat)
    assert set(fo) == {"mat_id", "outline_mm", "holes", "dims", "placement"}
    spec = SAMPLES["spacer-01"]
    t = get_template(spec.template)
    from services.geom_worker.sandbox import run_program

    res = run_program(t.code, {**t.defaults, **spec.params}, outputs=())
    assert res.mesh is not None
    ring = np.array(fo["outline_mm"])
    cx, cy = ring.mean(axis=0)
    V = S.place(res.mesh.vertices, float(cx), float(cy), 0.0)
    bgr = (FIT_OUTLINE_RGB[2], FIT_OUTLINE_RGB[1], FIT_OUTLINE_RGB[0])

    def under(img: np.ndarray, cam: T.Camera) -> np.ndarray:
        img = T.draw_outline_on_mat(img, cam, ring, bgr, 0.4)
        for h in fo["holes"]:
            hx, hy = h["center_mm"]
            img = T.draw_outline_on_mat(img, cam, T.circle_poly(hx, hy, h["diameter_mm"], 180), bgr, 0.4)
        return img

    cam = T.camera_above((105, 65), height_mm=300, tilt_deg=5, azimuth_deg=40)
    sc = T.render_scene(mat, cam.K, cam.R, cam.t, cam.size, (V, res.mesh.faces), part_bgr=(200, 200, 205), under=under)
    out = service.fit_check(job.id, T.encode_png(sc.image), mat)
    assert out["passed"], out["reasons"]
    assert out["overlay_url"].startswith("/api/v1/blobs/") and out["iou"] > 0.95


def test_preview_and_publish(jobs: dict[str, Any]) -> None:
    job = jobs["latch-01"]
    pv = service.preview(job.id)
    assert pv["mode"] == "mock" and pv["url"] and "MOCK" in pv["label"]
    assert service.job_detail(job.id)["artifacts"]["preview"] == pv["url"]
    rec = service.publish(job.id)
    assert rec.status == "verified" and rec.provenance.origin.value == "synthetic"
    assert rec.provenance.provider_mode == "mock" and rec.provenance.job_id == job.id
    assert rec.facts is not None and rec.params
    from services.registry.store import get_registry

    assert get_registry().get_part(rec.slug) is not None
    assert job.summary.part_slug == rec.slug
    assert get_registry().lessons(status="candidate")  # learn stage left candidates, none promoted
    assert not get_registry().lessons(status="promoted")


def test_demo_job_from_sample_folder(sample_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(service, "SAMPLES_DIRS", (sample_root,))
    assert {s["id"] for s in service.list_demo_samples()} == set(SAMPLES)
    job = service.start_demo_job("cover-01", sync=True)
    assert job.summary.origin.value == "synthetic" and "synthetic" in job.summary.title
    assert job.events[-1].status == "verified"
    with pytest.raises(KeyError, match="closest"):
        service.start_demo_job("cover-1", sync=True)


def test_status_and_cli_trace(jobs: dict[str, Any]) -> None:
    from typer.testing import CliRunner

    from services import cli

    lines = [cli.format_event(e) for e in jobs["cover-01"].events]
    text = "\n".join(x for x in lines if x)
    assert "round 1 [template]" in text and "done: VERIFIED" in text
    table = cli.verification_table(service.detail_of(jobs["cover-01"]))
    assert "Verification: VERIFIED" in table and "outline" in table
    r = CliRunner().invoke(cli.app, ["status"])
    assert r.exit_code == 0 and "build" in r.output and "mock" in r.output


def test_threaded_jobs_do_not_share_state(sample_root: Path) -> None:
    out: list[Any] = []

    def go(sid: str) -> None:
        out.append(_run(sample_root, sid))

    ts = [threading.Thread(target=go, args=(sid,)) for sid in ("spacer-01", "cover-01")]
    for t in ts:
        t.start()
    for t in ts:
        t.join(300)
    assert len(out) == 2 and all(j.events[-1].status == "verified" for j in out)
