"""The fix job's "where it fits" photo (SYNTHETIC renders, every model stage in mock mode): taps or the mock pointer
locate the mate, code measures it, and the final verdict gets P1 "fits where it goes" tests that never set verified."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from partsmith_schemas import JobInput
from partsmith_schemas.common import DataOrigin
from partsmith_schemas.verification import Verification

from services.agent import mating, mock_brain, service
from services.agent.orchestrator import FixRun, RunOptions
from services.agent.templates import get_template
from services.agent.tests import synth_samples as S
from services.metrology import testing as T
from services.metrology.calibrate import detect_mat
from services.metrology.capture_gate import run_gate
from services.metrology.measure import decode_image
from tools.synth.mating import MateScene, MatingGT, render_mating


def _run(points: dict[str, list[dict[str, Any]]] | None = None, intent: str = "") -> FixRun:
    ji = JobInput(kind="fix", origin=DataOrigin.synthetic, intent=intent)
    job = service.manager().create("fix", ji, title="mating test")
    return FixRun(job, RunOptions(question_timeout_s=0.0, points=points))


def _photo(scene: MateScene, size: float) -> tuple[bytes, MatingGT]:
    img, gt, _ = render_mating(scene, size)
    return T.encode_png(img), gt


def test_kind_hint_reads_the_users_words() -> None:
    assert mating.kind_hint("knob for the mixer, it goes on a D-shaft") == "mate_peg"
    assert mating.kind_hint("clip that holds the shelf panel") == "mate_slot"
    assert mating.kind_hint("plug for the socket in the lid") == "mate_hole"
    assert mating.kind_hint("") is None


def test_the_mating_photo_passes_the_same_capture_gate() -> None:
    png, _ = _photo("shaft", 6.0)
    img = decode_image(png)
    rep = run_gate(img, detect_mat(img))
    assert rep.passed, rep.retake_reason


def test_tapped_shaft_is_measured_and_stored() -> None:
    png, gt = _photo("shaft", 6.0)
    run = _run({"mating": [{"x": gt.tap_px[0], "y": gt.tap_px[1], "kind": "mate_peg"}]})
    run.photos["mating"] = png
    label = mating.measure(run)
    assert label is not None and label.startswith("mating: shaft Ø6.0"), label
    res = run.mate_result
    assert res is not None and len(res.mates) == 1
    m = res.mates[0]
    assert m.ok and m.point_source == "user" and m.size is not None
    assert abs(m.size.value - 6.0) <= max(m.size.sigma_mm, 0.02)
    assert run.job.read_json("mate_fit.json")["mates"][0]["kind"] == "mate_peg"
    kinds = {e.kind for e in run.job.events if e.t == "artifact"}
    assert "mate_overlay" in kinds
    assert not [e for e in run.job.events if e.t == "model_call" and e.stage == "mate_points"]  # taps: no pointer


def test_without_taps_the_mock_pointer_finds_it_and_says_mock() -> None:
    png, _ = _photo("socket", 8.0)
    run = _run(intent="the plug that goes into this socket")
    run.photos["mating"] = png
    run.set_ctx()
    mock_brain.install(replace=False)  # FixRun.run() does this in a job
    label = mating.measure(run)
    res = run.mate_result
    assert res is not None and res.mates and res.mates[0].point_source == "mock"
    assert res.mates[0].kind == "mate_hole" and label is not None and "socket Ø" in label
    assert any("MOCK" in n for n in res.notes)
    calls = [e for e in run.job.events if e.t == "model_call" and e.stage == "mate_points"]
    assert calls and all(c.mode == "mock" for c in calls)


def test_no_mating_photo_changes_nothing() -> None:
    run = _run()
    assert mating.measure(run) is None and run.mate_result is None
    v = Verification(verified=True, status="verified", reasons=["ok"])
    assert mating.check(run, v, SimpleNamespace(exec_result=None, code="")) is v  # type: ignore[arg-type]
    assert run.job.read_json("mate_fit.json") is None


def test_check_adds_p1_tests_and_a_reason_but_never_touches_verified() -> None:
    png, gt = _photo("shaft", 6.0)
    run = _run({"mating": [{"x": gt.tap_px[0], "y": gt.tap_px[1], "kind": "mate_peg"}]})
    run.photos["mating"] = png
    mating.measure(run)
    t = get_template("knob")
    feats = {"bbox_mm": [-15, -15, 0, 15, 15, 16], "holes": [], "plate_thickness_mm": None,
             "interfaces": [{"id": "shaft_bore", "label": "shaft bore", "mate_label": "shaft", "gap_mm": 5.9}]}  # fmt: skip
    b = SimpleNamespace(exec_result=SimpleNamespace(features=feats), code=t.code)
    v = Verification(verified=True, status="verified", reasons=["every view within 0.5 mm"])
    out = mating.check(run, v, b)  # type: ignore[arg-type]
    assert out.verified is True and out.status == "verified"
    (test,) = [x for x in out.tests if x.id.startswith("fit.mate.")]
    assert test.priority == "P1" and not test.passed and "does not fit" in test.description
    assert out.reasons[0] == "every view within 0.5 mm" and out.reasons[-1].startswith("Does not fit where it goes")
    stored = run.job.read_json("mate_fit.json")
    assert stored["fits"][0]["fit"] == "does not fit" and stored["preset"] == "pla-fdm-0.4"
    again = mating.check(run, out, b)  # type: ignore[arg-type]
    assert len([x for x in again.tests if x.id.startswith("fit.mate.")]) == 1  # idempotent
    assert len([r for r in again.reasons if "where it goes" in r]) == 1


# ------------------------------------------------------------------------------------------------- end to end (slow)

SPACER = next(s for s in S.SAMPLES if s.id == "spacer-01")  # bore_d 8.6 mm


def _job(root: Path, shaft_mm: float | None) -> Any:
    S.write_sample(SPACER, root)
    sample = service.load_sample(root / SPACER.id)
    photos = dict(sample.photos)
    points = None
    if shaft_mm is not None:
        png, gt = _photo("shaft", shaft_mm)
        photos["mating"] = png
        points = {"mating": [{"x": gt.tap_px[0], "y": gt.tap_px[1], "kind": "mate_peg"}]}
    ji = service.sample_job_input(sample.meta)
    opts = RunOptions(question_timeout_s=0.0, mat_id=str(sample.meta["mat_id"]))
    return service.start_fix_job(photos, ji, sync=True, options=opts, points=points)


@pytest.mark.slow
@pytest.mark.parametrize(("shaft", "fit"), [(8.4, "sliding fit"), (8.85, "does not fit")])
def test_spacer_job_checks_the_fit_on_its_shaft(tmp_path: Path, shaft: float, fit: str) -> None:
    job = _job(tmp_path, shaft)
    done = job.events[-1]
    assert done.t == "done" and done.status == "verified", [e.msg for e in job.events if e.t == "log"]
    res = job.read_json("mate_fit.json")
    (f,) = res["fits"]
    assert f["fit"] == fit and f["model_feature_source"] == "nearest_hole"
    assert f["model_mm"] == pytest.approx(SPACER.params["bore_d"], abs=0.1)
    v = job.read_json("verification.json")
    assert v["verified"] is True
    assert any(t["id"] == "fit.mate.mate_1" and t["priority"] == "P1" for t in v["tests"])
    ship = job.read_json("ship.json")
    assert ship["ok"] is True
    assert ("does not fit where it goes" in ship["reason"]) is (fit == "does not fit")
    labels = [e.label for e in job.events if e.t == "stage" and e.stage == "measure" and e.status == "ok"]
    assert any("mating: shaft Ø" in lb for lb in labels)
    assert "mate_fit" in service.detail_of(job)["artifacts"]


@pytest.mark.slow
def test_spacer_job_without_a_mating_photo_has_no_fit(tmp_path: Path) -> None:
    job = _job(tmp_path, None)
    v = job.read_json("verification.json")
    assert not [t for t in v["tests"] if t["id"].startswith("fit.mate.")]
    assert not [r for r in v["reasons"] if "where it goes" in r] and job.read_json("mate_fit.json") is None
