"""Code rules from the first live seed (2026-10-29), each with the recorded live values it came from.

The fixtures copy only the few numbers each rule reads from the recorded live runs (partspec / measurements /
verification of the SYNTHETIC demo samples); nothing reads gt.yaml. Mock mode, no network.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from types import SimpleNamespace
from typing import Any

import pytest
from partsmith_schemas import JobInput, Measured, Measurements, PartSpec, Source
from partsmith_schemas.partspec import BaseProfile, BrokenRegion, Family
from partsmith_schemas.verification import PartTest, Verification, ViewMetrics

from services.agent import evidence, guards, mock_brain, providers, service
from services.agent.orchestrator import (
    FixRun,
    Round,
    RunOptions,
    _StageNote,
    format_gate_failures,
    why_not_verified,
)
from services.agent.providers import ModelRequest

# demo-l-bracket, live: the top outline (part frame) and the side photo's note; the part is intact.
L_OUTLINE = [
    (23.094, 15.12), (20.439, 15.132), (20.199, 11.936), (19.953, 11.625), (7.008, 8.816), (-21.438, 8.786),
    (-22.262, 8.491), (-22.884, 7.849), (-23.155, 6.891), (-23.171, -12.73), (-22.874, -14.303), (-22.283, -14.907),
    (-21.188, -15.249), (22.429, -15.195), (23.156, -10.808),
]  # fmt: skip
L_SIDE_NOTE = (
    "side view: the part stands 31.3 mm tall, clearly above the stated 2.5 mm thickness — it has features taller "
    "than the plate (top-view outline measured at the stated thickness)"
)
L_MODEL_NOTE = (
    "Top long edge steps down from y~15.1 to y~8.8 for most of width; assumed broken/occluded flange edge, "
    "reconstruct to full rectangle by mirror/template."
)
L_INTENT = "Make a replacement for this broken l-bracket."


class _Job:
    def __init__(self, intent: str) -> None:
        self.input = JobInput(intent=intent)
        self.files: dict[str, Any] = {}

    def read_json(self, name: str) -> Any:
        return self.files.get(name)

    def write_json(self, name: str, data: Any) -> None:
        self.files[name] = data


def _m(value: float, sigma: float = 0.09) -> Measured:
    return Measured(value=value, source=Source.measured, sigma_mm=sigma)


def _top(
    outline: list[tuple[float, float]], length: float, width: float, area: float, sym: float | None
) -> Measurements:
    return Measurements(
        view="top", origin="synthetic", outline_mm=outline, length=_m(length), width=_m(width), area_mm2=area,
        symmetry_axis_deg=1.5 if sym is not None else None, symmetry_score=sym,
    )  # fmt: skip


def _side(notes: list[str]) -> Measurements:
    return Measurements(
        view="side", origin="synthetic", outline_mm=[(0, 0), (46, 0), (46, 31.3), (0, 31.3)], length=_m(46.4),
        width=_m(31.3), area_mm2=300.0, notes=notes,
    )  # fmt: skip


def _spec(
    family: Family, hint: str | None, thickness: float, outline: list[tuple[float, float]], **kw: Any
) -> PartSpec:
    return PartSpec(
        family=family, title="part", base_profile=BaseProfile(kind="polyline", points_mm=outline),
        thickness=Measured(value=thickness, source=Source.user_stated, sigma_mm=0.3), template_hint=hint, **kw,
    )  # fmt: skip


def _run(spec: PartSpec, meas: dict[str, Measurements], intent: str, points: Any = None) -> tuple[FixRun, list[str]]:
    run = FixRun.__new__(FixRun)
    run.spec, run.measurements, run.narration = spec, meas, None
    run.opts = RunOptions(points=points)
    run.job = _Job(intent)  # type: ignore[assignment]
    logs: list[str] = []
    run.log = lambda msg, level="info": logs.append(msg)  # type: ignore[method-assign]
    return run, logs


def _bracket(intent: str = L_INTENT, *, side: bool = True, sym: float = 0.9307, points: Any = None) -> Any:
    region = BrokenRegion(polygon_mm=[], strategy="mirror", kind="outline", note=L_MODEL_NOTE)
    spec = _spec(Family.bracket, "l_bracket", 2.5, L_OUTLINE, broken_region=region, intent=intent)
    meas = {"top": _top(L_OUTLINE, 46.366, 30.532, 1128.16, sym)}
    if side:
        meas["side"] = _side([L_SIDE_NOTE])
    return _run(spec, meas, intent, points)


# ------------------------------------------------------------------------------------------------- broken regions


def test_an_outline_break_only_the_model_saw_is_dropped() -> None:
    # live demo-l-bracket: generic "broken" request, mirror score 0.93 from the tall upright leg seen in perspective
    run, logs = _bracket()
    assert evidence.check_break_support(run) is True
    assert run.spec is not None and run.spec.broken_region is None
    saved = run.job.read_json("break_check.json")
    assert saved["dropped"] and "features above the plate" in saved["reason"]
    assert saved["model_region"]["note"] == L_MODEL_NOTE
    assert any("broken region dropped" in m for m in logs)


@pytest.mark.parametrize(
    ("intent", "side", "sym", "points", "why"),
    [
        ("Make a replacement for this broken l-bracket: a corner cracked off.", True, 0.9307, None, "'corner'"),
        (L_INTENT, True, 0.9307, {"top": [{"x": 900.0, "y": 700.0, "kind": "broken_edge"}]}, "tapped 1 broken"),
        (L_INTENT, False, 0.9307, None, "asymmetric"),  # no side photo: asymmetry is evidence
    ],
)
def test_an_outline_break_with_evidence_is_kept(intent: str, side: bool, sym: float, points: Any, why: str) -> None:
    run, logs = _bracket(intent, side=side, sym=sym, points=points)
    assert evidence.check_break_support(run) is False
    assert run.spec is not None and run.spec.broken_region is not None
    assert why in logs[-1] and run.job.read_json("break_check.json") is None


def test_a_symmetric_outline_with_generic_words_has_no_break() -> None:
    run, _ = _bracket(side=False, sym=0.995)
    assert evidence.check_break_support(run) is True and run.spec is not None and run.spec.broken_region is None


def test_break_evidence_words_and_the_mock_agree() -> None:
    assert guards.break_evidence(L_INTENT, broken_edge_taps=0, symmetry=0.99, taller_than_plate=False) is None
    for said in ("a piece is missing at one end", "the tip snapped off", "a corner cracked off"):
        assert guards.break_evidence(said, broken_edge_taps=0, symmetry=0.99, taller_than_plate=False)
    assert guards.break_evidence("", broken_edge_taps=0, symmetry=0.9, taller_than_plate=True) is None
    assert mock_brain.BROKEN_SYMMETRY == guards.BROKEN_SYMMETRY


def test_height_breaks_are_not_touched() -> None:
    run, _ = _bracket()
    assert run.spec is not None
    run.spec.broken_region = BrokenRegion(polygon_mm=[], strategy="template", kind="height")
    assert evidence.check_break_support(run) is False and run.spec.broken_region is not None


# ------------------------------------------------------------------------------------------------- planner override

LATCH_OUTLINE = [(-27.5, -8.0), (27.5, -8.0), (27.5, 8.0), (-27.5, 8.0)]


def _latch(family: Family = Family.latch, hint: str = "cupboard_latch", thickness: float = 7.5) -> Any:
    # live demo-cupboard-latch: 55.08 × 15.96 mm, 7.5 mm stated, side 7.7 mm (not taller than the plate), intact
    spec = _spec(family, hint, thickness, LATCH_OUTLINE)
    return _run(spec, {"top": _top(LATCH_OUTLINE, 55.083, 15.959, 807.38, 0.9904)}, "broken cupboard latch")


def test_free_code_for_an_intact_part_with_a_fitting_family_template_uses_the_template() -> None:
    run, logs = _latch()
    tpl = run.free_code_override()
    assert tpl is not None and tpl.name == "cupboard_latch"
    assert "free code stays the fallback" in logs[-1]


def test_no_override_when_the_template_does_not_fit_or_the_family_differs() -> None:
    run, logs = _latch(thickness=80.0)
    assert run.free_code_override() is None and "does not fit" in logs[-1]
    run, logs = _latch(family=Family.custom, hint="battery_cover")  # the ID-1 card: family custom
    assert run.free_code_override() is None and not logs


# ------------------------------------------------------------------------------------------------- hollow free code

PROG = """import cadquery as cq

PARAMS = {
    "height": (9.6, 1.0, 20.0, 0.1, "mm", True, "Body height"),
}


def build(p: dict) -> cq.Workplane:
    return cq.Workplane("XY").box(32.0, 16.0, p["height"])


result = build({k: v[0] for k, v in PARAMS.items()})
"""


def _round(plate_mm: float, height_mm: float, expected: float = 9.6) -> Round:
    # live demo-ref-lego-2x4: plate thickness 1.70 mm vs the stated 9.60 mm on an 11.4 mm tall hollow brick
    test = PartTest(
        id="thickness", description=f"plate thickness == {expected:.2f} +/- 0.3 mm", value=plate_mm,
        expected=expected, tol=0.3, passed=abs(plate_mm - expected) <= 0.3,
    )  # fmt: skip
    v = Verification(verified=False, status="best_effort", tests=[test])
    si = SimpleNamespace(size_mm=(31.8, 15.8, height_mm))
    return Round(1, "free_code", PROG, {}, SimpleNamespace(solid_info=si), SimpleNamespace(verification=v))  # type: ignore[arg-type]


def test_a_hollow_free_code_solid_is_a_code_finding() -> None:
    run = FixRun.__new__(FixRun)
    finding = run.hollow_finding(_round(1.7, 11.4))
    assert finding is not None and "1.70 mm" in finding and "9.60 mm thick" in finding
    assert run.hollow_finding(_round(1.7, 5.0)) is None  # short, not hollow: the height knob fixes it
    assert run.hollow_finding(_round(6.0, 11.4)) is None  # thin but not hollow
    assert run.hollow_finding(_round(9.6, 11.4)) is None


def test_a_hollow_free_code_solid_is_rebuilt_once_with_the_finding() -> None:
    run = FixRun.__new__(FixRun)
    run.iteration, run.template, run.current, run.best, run.stated = 0, None, None, None, {}
    run.opts, run.rebuilt = RunOptions(), set()
    logs: list[str] = []
    run.log = lambda msg, level="info": logs.append(msg)  # type: ignore[method-assign]

    @contextmanager
    def stage(name: str, label: str) -> Iterator[_StageNote]:
        yield _StageNote(label)

    feedbacks: list[Any] = []
    rounds = iter([_round(1.7, 11.4), _round(9.6, 11.4), _round(1.7, 11.4)])

    def build_program(strategy: str, feedback: Any = None) -> str:
        feedbacks.append(feedback)
        return PROG

    run.stage = stage  # type: ignore[method-assign]
    run.build_program = build_program  # type: ignore[method-assign]
    run.evaluate = lambda *a, **kw: next(rounds)  # type: ignore[method-assign]
    rnd = run.build_round("free_code", iter_label="first build")
    assert feedbacks[0] is None and feedbacks[1] is not None and feedbacks[1][0] == PROG
    assert "plate thickness of 1.70 mm" in feedbacks[1][1] and rnd.verification is not None
    assert rnd.verification.tests[0].passed and run.iteration == 2 and "rebuilding once" in logs[0]
    assert run.build_round("free_code", iter_label="again").verification is not None  # hollow again: no 2nd rebuild
    assert len(feedbacks) == 3 and run.iteration == 3


def test_the_builder_prompt_asks_for_a_solid_body() -> None:
    from services.agent import prompt_loader

    p = prompt_loader.load("build")
    assert p.version >= 2 and "no hollow underside or hidden cavity" in p.developer


# ------------------------------------------------------------------------------------------------- the fixer sees the gate


def test_the_fixer_is_told_which_gate_fails() -> None:
    # live demo-knob: side view Hausdorff 0.43 mm and IoU 0.970, but a 15.8 mm silhouette is gated on the mean (0.19)
    side = ViewMetrics(
        view="side", iou=0.9703, hausdorff_mm=0.4335, hd95_mm=0.4115, mean_mm=0.1897, over_area_mm2=3.6,
        under_area_mm2=14.67,
    )  # fmt: skip
    top = ViewMetrics(view="top", iou=0.982, hausdorff_mm=0.374, hd95_mm=0.3, mean_mm=0.136)
    v = Verification(verified=False, status="best_effort", views=[top, side])
    gates = {"top": ["hausdorff", "iou"], "side": ["hausdorff", "mean"]}
    why = why_not_verified(v, gates)
    assert len(why) == 1 and "side view: mean edge distance 0.19 mm > 0.15 mm" in why[0]
    assert "missing 14.7 mm²" in why[0]
    assert why_not_verified(v) == []  # read with IoU gates only (what the fixer saw), nothing looks wrong
    assert "not verified because: side view: mean edge" in format_gate_failures(v, gates)
    ok = Verification(verified=True, status="verified", views=[top])
    assert format_gate_failures(ok, gates) == ""


# ------------------------------------------------------------------------------------------------- reference checks


def test_only_bundled_reference_samples_are_reference_checks() -> None:
    ref = service.load_sample(service.find_sample("demo-ref-aa-cell"))
    part = service.load_sample(service.find_sample("demo-spacer"))
    assert service.sample_job_input(ref.meta).purpose == "reference_check"
    assert service.sample_job_input(part.meta).purpose == "repair"
    assert JobInput().purpose == "repair"


def _refusing_understand(seen: list[ModelRequest]) -> Any:
    def handler(req: ModelRequest) -> dict[str, Any]:
        seen.append(req)
        spec = mock_brain.understand(req)
        # the live reply for demo-ref-aa-cell, 2026-10-29
        spec.update(family="custom", refusal="This is an AA battery cell reference object, not a rigid plastic part "
                    "that can be reproduced by FDM 3D printing.")  # fmt: skip
        return spec

    return handler


def _logs(job: Any) -> list[str]:
    return [str(e.msg) for e in job.events if e.t == "log"]


@pytest.mark.slow
def test_a_model_refusal_is_ignored_on_a_reference_check_only() -> None:
    seen: list[ModelRequest] = []
    providers.register_mock("understand", _refusing_understand(seen))
    job = service.start_demo_job("demo-ref-aa-cell", sync=True)
    assert job.summary.status == "done", _logs(job)
    assert any("model refusal ignored on a reference check" in m for m in _logs(job))
    user = seen[0].messages[1]["content"]
    assert "Purpose: a measurement check of a known reference object" in user and "do not refuse" in user
    ship = job.read_json("ship.json")
    assert ship["purpose"] == "reference_check" and ship["reason"].startswith("measurement check of a reference")
    spec = job.read_json("partspec.json")
    assert spec["refusal"] is None

    seen.clear()
    repair = service.start_demo_job("demo-spacer", sync=True)  # the same refusal on a repair job still refuses
    done = [e for e in repair.events if e.t == "done"][-1]
    assert done.status == "refused" and "Purpose:" not in seen[0].messages[1]["content"]


# ------------------------------------------------------------------------------------------------- template means template

KNOB_REWRITE = """import cadquery as cq

MEASURE_MAP = {"length": "diameter", "width": "diameter", "thickness": "height"}
PARAMS = {
    "diameter": (30.3, 24.0, 36.0, 0.1, "mm", True, "Knob diameter (scales measured profile)"),
    "height": (15.8, 10.0, 24.0, 0.1, "mm", True, "Knob height / thickness"),
    "bore_d": (6.2, 4.5, 8.0, 0.05, "mm", True, "Bore diameter"),
    "top_fillet": (0.9, 0.0, 3.0, 0.1, "mm", False, "Top edge fillet"),
    "knurl_count": (32, 16, 48, 1, "", False, "Knurl lobes"),
}


def build(p: dict) -> cq.Workplane:
    return cq.Workplane("XY").circle(p["diameter"] / 2).extrude(p["height"])


result = build({k: v[0] for k, v in PARAMS.items()})
"""


def test_a_template_build_runs_the_template_source_with_the_builders_values() -> None:
    # live knob rerun, 2026-10-29: the builder returned an extruded polyline with a knurl_count knob as "the knob template"
    from services.agent.templates import get_template
    from services.geom_worker.program import parse_params

    tpl = get_template("knob")
    run = FixRun.__new__(FixRun)
    logs: list[str] = []
    run.log = lambda msg, level="info": logs.append(msg)  # type: ignore[method-assign]
    out = run.template_program(tpl, KNOB_REWRITE)
    vals = {p.name: p.default for p in parse_params(out)}
    assert {p.name for p in parse_params(out)} == {p.name for p in tpl.params}
    assert vals["diameter"] == 30.3 and vals["height"] == 15.8 and vals["bore_d"] == 6.2 and vals["top_fillet"] == 0.9
    assert vals["grip_count"] == tpl.param("grip_count").default  # a knob the builder dropped keeps its default
    assert "knurl_count" in logs[0] and "template source" in logs[0]
    logs.clear()
    honest = "# part.py — knob\n" + tpl.code  # an honest template build (a header comment is fine) is kept as is
    assert run.template_program(tpl, honest) == honest and not logs


# ------------------------------------------------------------------------------------------------- pointed rims of hidden bores

HIDDEN_NOTE = (
    "possible hidden hole near mat (67.6, 152.9) mm, about Ø9.4 mm: the bore is not seen through from this angle — "
    "retake from straight above it or state its diameter"
)


def _pointed(note: str, at: tuple[float, float] = (67.55, 152.85)) -> Any:
    from partsmith_schemas.common import Evidence

    d = Measured(value=10.426, source=Source.measured, sigma_mm=0.012, evidence=Evidence(view="top", note=note))
    return SimpleNamespace(id="hole_1", kind="hole", ok=True, center_mm=at, values={"diameter": d})


def test_a_pointed_rim_over_a_hidden_bore_is_not_a_through_hole() -> None:
    # live demo-broken-latch-corner rerun: the SAM point measured the countersink rim where no mat shows through
    spec = _spec(Family.latch, "cupboard_latch", 5.0, LATCH_OUTLINE)
    top = _top(LATCH_OUTLINE, 47.12, 17.12, 700.0, 0.95)
    top.notes = [HIDDEN_NOTE]
    run, logs = _run(spec, {"top": top}, "a corner cracked off")
    rim = "SAM point prompt (sam-3.1); top-opening rim, h=5.0 mm, rms 0.028 mm; mask confidence 0.91: ±σ × 1.18"
    assert evidence._rim_of_hidden_bore(run, _pointed(rim)) is True and "stays a question" in logs[-1]
    assert (
        evidence._rim_of_hidden_bore(run, _pointed("SAM point prompt (sam-3.1); see-through cylinder, h=5.0 mm"))
        is False
    )
    assert evidence._rim_of_hidden_bore(run, _pointed(rim, at=(90.0, 152.9))) is False  # elsewhere: a missed hole
    top.notes = []
    assert evidence._rim_of_hidden_bore(run, _pointed(rim)) is False  # no hidden-bore flag: the usual merge applies


def test_install_card_check_step_fits_the_family() -> None:
    """A spacer does not "move": only families whose part moves in use get a movement check step."""
    assert evidence.install_steps("spacer")[2] == "Check that it sits flush and holds like the original"
    assert evidence.install_steps(None)[2] == "Check that it sits flush and holds like the original"
    assert "swings" in evidence.install_steps("hinge")[2]
    assert "turns" in evidence.install_steps("wheel")[2]
    assert all("moves" not in s for f in ("spacer", "bracket", "hook", "cover") for s in evidence.install_steps(f))


def test_every_install_card_panel_gets_the_same_code_drawn_title_strip() -> None:
    """The live card's third panel came back without the banner the model drew on the first two: code draws the strip
    on every panel, above the picture (nothing in it is covered)."""
    import io as _io

    import numpy as np
    from PIL import Image

    photo = Image.new("RGB", (1200, 900), (140, 150, 160))
    buf = _io.BytesIO()
    photo.save(buf, format="PNG")
    out = []
    for i, step in enumerate(evidence.install_steps("hook"), start=1):
        out.append(
            Image.open(_io.BytesIO(evidence.titled_panel(buf.getvalue(), f"Step {i} of 3: {step}"))).convert("RGB")
        )
    heights = {im.height for im in out}
    assert len(heights) == 1 and heights.pop() > 900  # one strip height for all panels, added above the 900 px picture
    strip = out[0].height - 900
    for im in out:
        assert im.getpixel((2, 2)) == evidence.BANNER_RGB  # the strip is there on every panel
        assert im.getpixel((600, strip + 450)) == (140, 150, 160)  # the picture below is untouched
        px = np.asarray(im.crop((0, 0, im.width, strip)))
        assert (px == 255).all(axis=2).any()  # white title text
