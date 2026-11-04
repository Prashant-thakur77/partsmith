"""Bench ablation switches on RunOptions: each one turns off exactly one thing. SYNTHETIC photos, mocks."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from partsmith_schemas.common import DataOrigin, Measured, Source
from partsmith_schemas.measurement import Hole, Measurements, ViewKind

from services.agent import service
from services.agent.orchestrator import RunOptions, guessed_scale, scale_measurements
from services.agent.tests import synth_samples as S


def _m(v: float, src: Source = Source.measured) -> Measured:
    return Measured(value=v, source=src, sigma_mm=0.1)


def test_scale_measurements_scales_in_plane_sizes_only() -> None:
    m = Measurements(
        view=ViewKind.top,
        origin=DataOrigin.synthetic,
        outline_mm=[(0, 0), (40, 0), (40, 20)],
        holes=[Hole(id="hole_1", center_mm=(5.0, -2.0), diameter=_m(4.0))],
        length=_m(40.0),
        width=_m(20.0),
        thickness=_m(3.0, Source.user_stated),
        area_mm2=800.0,
    )
    d = scale_measurements(m, 1.5)
    assert (d.length.value, d.width.value, d.area_mm2) == pytest.approx((60.0, 30.0, 1800.0))
    assert d.holes[0].diameter.value == pytest.approx(6.0) and d.holes[0].center_mm == pytest.approx((7.5, -3.0))
    assert d.outline_mm[1] == pytest.approx((60.0, 0.0))
    assert d.thickness is not None and d.thickness.value == 3.0  # what the user said stays
    assert any("ABLATION" in n for n in d.notes) and m.length.value == 40.0  # the original is untouched
    assert scale_measurements(m, 1.0) is m


def test_guessed_scale() -> None:
    assert guessed_scale(SimpleNamespace(detection=None)) == 1.0  # type: ignore[arg-type]
    st = SimpleNamespace(x_mm=0.0, y_mm=0.0, w_mm=100.0, h_mm=50.0)
    det = SimpleNamespace(image_size=(3000, 2000), mat=SimpleNamespace(stage=st), px_per_mm_at=lambda p: 7.0)
    f_px = 26.0 * (3000**2 + 2000**2) ** 0.5 / (36.0**2 + 24.0**2) ** 0.5
    assert guessed_scale(SimpleNamespace(detection=det)) == pytest.approx(7.0 * 300.0 / f_px)  # type: ignore[arg-type]


@pytest.fixture(scope="module")
def latch(tmp_path_factory: pytest.TempPathFactory) -> Path:
    spec = next(s for s in S.SAMPLES if s.id == "latch-01")
    return S.write_sample(spec, tmp_path_factory.mktemp("opts"))


def _run(path: Path, **opts: Any) -> Any:
    sample = service.load_sample(path)
    o = RunOptions(question_timeout_s=0.0, mat_id=str(sample.meta["mat_id"]), package=False, learn=False, **opts)
    return service.start_fix_job(sample.photos, service.sample_job_input(sample.meta), sync=True, options=o)


def _stages(job: Any) -> list[str]:
    return [e.stage for e in job.events if e.t == "stage" and e.status != "start"]


@pytest.mark.slow
def test_single_shot_builds_once(latch: Path) -> None:
    job = _run(latch, single_shot=True)
    assert job.events[-1].t == "done" and job.events[-1].summary["iterations"] == 1
    st = _stages(job)
    assert "fix" not in st and "judge" not in st and st.count("build") == 1


@pytest.mark.slow
def test_no_templates_no_judge_no_height_and_visual_only(latch: Path) -> None:
    job = _run(latch, templates=False, judge=False, max_iters=2)
    assert job.events[-1].summary["strategy"] == "free_code" and "judge" not in _stages(job)
    assert not [e for e in job.events if e.t == "model_call" and e.stage in ("plan", "judge")]
    flat = _run(latch, height_correction=False, max_iters=1)
    m = flat.read_json("measurements.json")["top"]
    assert m["height_correction_scale"] == 1.0
    vis = _run(latch, numeric_feedback=False, max_iters=2)
    assert vis.events[-1].t == "done"


@pytest.mark.slow
def test_no_mat_scale_keeps_model_guesses(latch: Path) -> None:
    job = _run(latch, mat_scale=False, single_shot=True)
    assert job.events[-1].t == "done"
    assert any("no mat scale" in e.msg for e in job.events if e.t == "log")
    # the verifier still compares against the calibrated measurements
    assert job.read_json("measurements.json")["top"]["notes"] and job.read_json("verification.json") is not None
