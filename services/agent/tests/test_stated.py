"""A broken end of unknown length: the length comes from the user's own words (intent, one question, or a tapped
broken edge + the missing piece), never from a model, and enters as user-stated."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import numpy as np
import pytest
from partsmith_schemas import JobInput
from partsmith_schemas.common import DataOrigin, Measured, Source
from partsmith_schemas.measurement import Measurements
from partsmith_schemas.partspec import BaseProfile, BrokenRegion, Family, PartSpec
from partsmith_schemas.verification import ParamSpec

from services.agent import guards, service
from services.agent.orchestrator import FixRun, RunOptions
from services.agent.stated import (
    HEDGED_SIGMA_MM,
    RULER_SIGMA_MM,
    TAP_SIGMA_MM,
    check_stated_length,
    parse_answer_length,
    parse_intent_length,
)
from services.agent.templates import get_template

CORNER = [(20.0, 3.0), (23.8, 3.0), (23.8, 8.75), (20.0, 8.75)]  # reaches the +x end (and a side)
NOTCH = [(-3.0, 6.0), (3.0, 6.0), (3.0, 8.75), (-3.0, 8.75)]  # middle of a long edge: the length is measured


# ------------------------------------------------------------------------------------------------- parsing


@pytest.mark.parametrize(
    ("text", "mm", "sigma"),
    [
        ("Make a new latch, it was 51 mm long.", 51.0, RULER_SIGMA_MM),
        ("the corner snapped; it was about 5.1 cm long before it broke", 51.0, HEDGED_SIGMA_MM),
        ("original length: 51.3mm", 51.3, RULER_SIGMA_MM),
        ("length was around 48 mm", 48.0, HEDGED_SIGMA_MM),
        ("it was 51,5 mm long", 51.5, RULER_SIGMA_MM),
        ("it was 51 mm ± 0.2 mm long", 51.0, 0.2),
        ("2 inches long", 50.8, RULER_SIGMA_MM),
    ],
)
def test_intent_length_is_unit_aware(text: str, mm: float, sigma: float) -> None:
    sv = parse_intent_length(text)
    assert sv is not None and sv.value_mm == pytest.approx(mm) and sv.sigma_mm == pytest.approx(sigma)
    assert sv.how.startswith("intent:")


@pytest.mark.parametrize(
    "text",
    [
        "Make a replacement for this broken cupboard turn-button latch: a corner cracked off.",
        "it is 5 mm thick with a 4 mm hole",
        "",
        None,
    ],
)
def test_intent_without_a_length_gives_none(text: str | None) -> None:
    assert parse_intent_length(text) is None


def test_answers_numbers_units_and_skip() -> None:
    for raw, mm in ((51.3, 51.3), ("51.3", 51.3), ("51 mm", 51.0), ("5.1 cm", 51.0), ("about 51", 51.0)):
        sv = parse_answer_length(raw)
        assert not isinstance(sv, str) and sv is not None and sv.value_mm == pytest.approx(mm)
    for skip in ("skip", "", "Skip.", "don't know", None):
        assert parse_answer_length(skip) == "skip"
    for bad in ("banana", -3, "0"):
        assert parse_answer_length(bad) is None


def test_absurd_lengths_are_refused() -> None:
    assert check_stated_length(51.3, 0.5, knob_min=25, knob_max=90, broken_length_mm=47.6) is None
    over = check_stated_length(120, 0.5, knob_min=25, knob_max=90, broken_length_mm=47.6)
    assert over is not None and "outside" in over
    shorter = check_stated_length(30, 0.5, knob_min=25, knob_max=90, broken_length_mm=47.6)
    assert shorter is not None and "shorter than the broken piece" in shorter


def test_locked_knob_is_never_moved_by_the_guards() -> None:
    specs = [ParamSpec(name="length", default=45, min=25, max=90, step=0.1),
             ParamSpec(name="pivot_offset", default=8, min=0, max=25, step=0.1)]  # fmt: skip
    g = guards.guard_edits(
        [{"param": "length", "to": 50.0}, {"param": "pivot_offset", "to": 8.5}],
        specs, {"length": 51.3, "pivot_offset": 8.0}, locked={"length": "the user stated the original length"},
    )  # fmt: skip
    assert [e.param for e in g.applied] == ["pivot_offset"]
    assert any("length: the user stated" in r for r in g.rejected)


# ------------------------------------------------------------------------------------------------- the job step


def _run(region: list[tuple[float, float]], *, intent: str = "", answers: dict[str, Any] | None = None,
         points: dict[str, Any] | None = None) -> FixRun:  # fmt: skip
    hx, hy = 23.8, 8.75
    top = Measurements(
        view="top", origin="synthetic", outline_mm=[(-hx, -hy), (hx, -hy), (hx, hy), (-hx, hy)],
        length=Measured(value=2 * hx), width=Measured(value=2 * hy), area_mm2=4 * hx * hy,
        part_to_mat=np.eye(3).tolist(),
    )  # fmt: skip
    spec = PartSpec(
        family=Family.latch, base_profile=BaseProfile(kind="polyline", points_mm=top.outline_mm),
        thickness=Measured(value=5.0, source=Source.user_stated),
        broken_region=BrokenRegion(polygon_mm=region, strategy="mirror"),
    )  # fmt: skip
    ji = JobInput(kind="fix", intent=intent, origin=DataOrigin.synthetic)
    job = service.manager().create("fix", ji, title="stated length test")
    run = FixRun(job, RunOptions(answers=dict(answers or {}), question_timeout_s=0.0, points=points))
    run.measurements = {"top": top}
    run.spec = spec
    run.template = get_template("cupboard_latch")
    run.strategy = "template"
    return run


def _questions(run: FixRun) -> list[Any]:
    return [e for e in run.job.events if e.t == "question"]


def test_no_question_when_the_break_leaves_the_length_measurable() -> None:
    run = _run(NOTCH, answers={"length.original": 51.3})
    run.ask_stated_length()
    assert not _questions(run) and not run.stated and not run.locked


def test_question_when_the_break_spans_the_length_and_skip_keeps_it_inferred() -> None:
    run = _run(CORNER)  # no answer: the default "skip" after the (zero) timeout
    run.ask_stated_length()
    (q,) = _questions(run)
    assert q.id == "length.original" and "How long was it before it broke?" in q.text and q.default == "skip"
    assert not run.stated and not run.locked and "length" not in run.answers


def test_answer_is_applied_as_user_stated_and_locks_the_knob() -> None:
    run = _run(CORNER, answers={"length.original": "51.3 mm"})
    run.ask_stated_length()
    m = run.stated["length"]
    assert m.value == 51.3 and m.source == Source.user_stated and m.sigma_mm == RULER_SIGMA_MM
    assert m.evidence is not None and "stated by the user" in (m.evidence.note or "")
    assert "length" in run.locked and run.answers["length"] == 51.3
    assert run.job.read_json("stated.json")["knob"] == "length"
    code = run.template.code if run.template else ""
    values = run.apply_stated(code, {"length": 45.0, "width": 14.0})
    assert values == {"length": 51.3, "width": 14.0}  # code sets the knob; the builder's guess is replaced


def test_intent_length_needs_no_question() -> None:
    run = _run(CORNER, intent="The corner snapped off. It was about 5.1 cm long.")
    run.ask_stated_length()
    assert not _questions(run)
    assert run.stated["length"].value == 51.0 and run.stated["length"].sigma_mm == HEDGED_SIGMA_MM


@pytest.mark.parametrize("answer", ["120", "30"])
def test_absurd_answer_is_refused_and_the_length_stays_inferred(answer: str) -> None:
    run = _run(CORNER, answers={"length.original": answer})
    run.ask_stated_length()
    assert not run.stated and not run.locked
    assert any(e.t == "log" and "stated length refused" in e.msg for e in run.job.events)


def test_a_tapped_broken_edge_asks_only_for_the_missing_piece() -> None:
    taps = {"top": [{"x": 20.0, "y": 0.0, "kind": "broken_edge"}]}
    run = _run(CORNER, answers={"length.missing": 7.5}, points=taps)
    # identity calibration: photo px == mat mm == part frame mm (the real path maps the tap through the homography)
    det = SimpleNamespace(H=np.eye(3), to_mm=lambda pts, H=None: np.asarray(pts, dtype=np.float64))
    run.mo = {"top": SimpleNamespace(detection=det, H_top=None)}  # type: ignore[dict-item]
    run.ask_stated_length()
    (q,) = _questions(run)
    assert q.id == "length.missing" and "43.8 mm from the intact end" in q.text
    m = run.stated["length"]
    assert m.value == pytest.approx(43.8 + 7.5) and m.sigma_mm == pytest.approx(
        np.hypot(RULER_SIGMA_MM, TAP_SIGMA_MM), abs=1e-3
    )


def test_no_question_without_a_template_length_knob() -> None:
    run = _run(CORNER, answers={"length.original": 51.3})
    run.template, run.strategy = None, "free_code"
    run.ask_stated_length()
    assert not _questions(run) and not run.stated


@pytest.mark.slow
def test_latch_demo_with_a_scripted_answer() -> None:
    """The demo sample end to end (mock): one question, the scripted answer sets the length, the verdict lists it as
    user-stated and never counts it; nothing about the sample is read but its photos and meta.json."""
    from services.common.paths import REPO_ROOT

    sample = service.load_sample(REPO_ROOT / "data" / "synthetic" / "samples" / "demo-broken-latch-corner")
    opts = RunOptions(answers={"length.original": "51.3"}, question_timeout_s=0.0, mat_id=str(sample.meta["mat_id"]),
                      package=False, learn=False)  # fmt: skip
    job = service.start_fix_job(sample.photos, service.sample_job_input(sample.meta), sync=True, options=opts)
    d = service.job_detail(job.id)
    assert [e["id"] for e in d["events"] if e["t"] == "question"] == ["length.original"]
    assert d["values"]["length"] == pytest.approx(51.3)
    v = d["verification"]
    stated_rows = [u for u in v["unchecked"] if u["param"] == "length"]
    assert stated_rows and stated_rows[0]["source"] == "user_stated"
    assert not any(r["feature_id"] == "outline" and r["quantity"] == "length" for r in v["residuals"])
    assert next(t for t in v["tests"] if t["id"] == "bbox.x.stated")["passed"]
