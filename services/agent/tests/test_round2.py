"""Round-2 agent features: the agentic fixer, points, orbit height, cited specs, gated completions, package extras.

Capabilities other services provide (point segmentation, orbit measurement, spec lookup, Muse Image completion and its
code gate) are replaced here by small fakes with the documented call shapes; nothing touches the network.
"""

from __future__ import annotations

import types
from pathlib import Path
from typing import Any

import pytest
from partsmith_schemas import JobInput, Measured, Source
from partsmith_schemas.common import Citation
from partsmith_schemas.partspec import BrokenRegion, DShaftBore

from services.agent import agent_loop, evidence, providers, service
from services.agent.jobs import load_job
from services.agent.orchestrator import FixRun, RunOptions
from services.agent.tests import synth_samples as S

SAMPLES = {s.id: s for s in S.SAMPLES}


@pytest.fixture(scope="module")
def sample_root(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("r2samples")
    for spec in S.SAMPLES:
        S.write_sample(spec, root)
    return root


def _run(root: Path, sid: str, **opts: Any) -> Any:
    sample = service.load_sample(root / sid)
    ji = service.sample_job_input(sample.meta)
    o = RunOptions(question_timeout_s=0.0, mat_id=str(sample.meta["mat_id"]), **opts)
    return service.start_fix_job(sample.photos, ji, sync=True, options=o)


# ------------------------------------------------------------------------------------------------- agentic fixer


@pytest.mark.slow
@pytest.mark.parametrize("mode", ["agent", "pipeline"])
def test_both_fix_modes_verify_and_replay(sample_root: Path, mode: str) -> None:
    job = _run(sample_root, "latch-01", fix_mode=mode)
    done = job.events[-1]
    assert done.status == "verified" and done.summary["fix_mode"] == mode
    kinds = {e.t for e in job.events}
    if mode == "agent":
        assert {"tool_call", "thought", "focus"} <= kinds
        calls = [e.name for e in job.events if e.t == "tool_call"]
        assert calls[0] == "inspect_residuals" and "render_overlay" in calls and "set_params" in calls
        fixes = [e.label for e in job.events if e.t == "stage" and e.stage == "fix" and e.status == "ok"]
        assert fixes and all("→" in f and "Hausdorff" in f for f in fixes)
        focus = [e for e in job.events if e.t == "focus"]
        assert all(e.at_mm is not None and len(e.at_mm) == 3 for e in focus)
    else:
        assert "tool_call" not in kinds
    assert service.detail_of(load_job(job.dir)) == service.detail_of(job)


@pytest.mark.slow
def test_mock_job_through_the_fix_loop_shows_the_agent_trace(sample_root: Path) -> None:
    """A mock job that needs fix rounds goes through the agentic fixer: its persisted events carry thought, tool_call
    and focus events from the real tool loop, and every model-side event says it is the deterministic mock."""
    job = _run(sample_root, "latch-01")
    assert job.events[-1].summary["fix_mode"] == "agent"
    events = load_job(job.dir).events  # what the API and the web read back (run.jsonl), not only the live list
    thoughts = [e for e in events if e.t == "thought"]
    calls = [e for e in events if e.t == "tool_call"]
    focus = [e for e in events if e.t == "focus"]
    assert len(thoughts) >= 1 and len(calls) >= 1 and len(focus) >= 1
    assert all(e.stage == agent_loop.STAGE for e in thoughts + calls)
    assert all(e.model == agent_loop.MOCK_MODEL and e.mode == "mock" for e in thoughts)
    assert all(e.text.endswith("(deterministic mock)") for e in thoughts)
    assert all(e.mode == "mock" for e in calls)
    agent_calls = [e for e in events if e.t == "model_call" and e.stage == agent_loop.STAGE]
    assert agent_calls and all(e.mode == "mock" and e.model == agent_loop.MOCK_MODEL for e in agent_calls)
    rounds = [e for e in events if e.t == "iteration" and e.iter > 1]
    assert rounds, "latch-01 must need at least one fix round for this test to mean anything"


@pytest.mark.slow
def test_lying_agent_cannot_verify_a_bad_part(sample_root: Path) -> None:
    """An agent that tries a wrong size, commits a wrong hole position and then claims success: code refuses the size
    (its measured width already passes), keeps the best model and does not verify."""
    state = {"n": 0}

    def liar(req: Any, history: Any = None) -> dict[str, Any]:
        state["n"] += 1
        if state["n"] == 1:
            return {"tool": "set_params", "args": {"edits": [{"param": "width", "to": 30.0}]},
                    "thought": "Making it wider."}  # fmt: skip
        if state["n"] == 2:
            return {"tool": "set_params", "args": {"edits": [{"param": "pivot_offset", "to": 20.0}]},
                    "thought": "Moving the pivot."}  # fmt: skip
        return {"tool": "submit", "args": {"reason": "VERIFIED: all residuals are zero, trust me"},
                "thought": "Everything matches perfectly."}  # fmt: skip

    providers.register_mock(agent_loop.STAGE, liar, replace=True)
    try:
        job = _run(sample_root, "latch-01", max_iters=3)
    finally:
        providers.unregister_mock(agent_loop.STAGE)
    done = job.events[-1]
    submits = [e for e in job.events if e.t == "tool_call" and e.name == "submit"]
    assert submits and "trust me" in str(submits[0].args)
    sets = [e for e in job.events if e.t == "tool_call" and e.name == "set_params"]
    assert sets[0].result.startswith("nothing committed: width: pinned")  # a passing measured width is not traded away
    assert not [e for e in job.events if e.t == "iteration" and any(d.get("param") == "width" for d in e.edits)]
    lie = [e for e in job.events if e.t == "iteration" and any(d.get("param") == "pivot_offset" for d in e.edits)]
    assert lie and lie[0].passed_tests < lie[0].total_tests  # the committed lie, verified by code as bad
    lied_to = lie[0].edits[0]["to"]
    assert job.read_json("values.json").get("pivot_offset") != lied_to  # code kept a better model, not the claimed one
    v = job.read_json("verification.json")
    assert v["verified"] is done.verified  # the verdict is the verifier's
    if done.verified:  # only possible through code's own free-code fallback, never through the agent's claim
        assert done.summary["strategy"] == "free_code"
    assert job.read_json("ship.json")["ok"] is done.verified


def test_agent_edits_pass_the_same_guards() -> None:
    """set_params uses the pipeline's guards: an unknown knob is rejected with the closest names."""
    from services.agent import guards
    from services.geom_worker.program import parse_params

    code = (Path(__file__).resolve().parents[1] / "templates" / "cupboard_latch.py").read_text()
    specs = parse_params(code)
    g = guards.guard_edits([{"param": "pivot_dia", "to": 5.0}], specs, {s.name: s.default for s in specs})
    assert not g.applied and "closest: pivot_d" in g.rejected[0]


# ------------------------------------------------------------------------------------------------- evidence sources


def _bare_run(tmp_path: Path, intent: str = "") -> FixRun:
    from services.agent.jobs import JobManager

    m = JobManager(root=tmp_path)
    job = m.create("fix", JobInput(intent=intent))
    run = FixRun(job, RunOptions())
    from partsmith_schemas import Hole, Measurements, PartSpec
    from partsmith_schemas.partspec import BaseProfile, ThroughHole

    d = Measured(value=4.2, source=Source.measured, sigma_mm=0.05)
    hole = Hole(id="hole_1", center_mm=(5.0, 0.0), diameter=d)
    run.measurements["top"] = Measurements(
        view="top", origin="synthetic", outline_mm=[(-10, -5), (10, -5), (10, 5), (-10, 5)], holes=[hole],
        length=Measured(value=20.0), width=Measured(value=10.0), area_mm2=200.0, symmetry_axis_deg=0.0,
    )  # fmt: skip
    run.spec = PartSpec(
        family="knob", base_profile=BaseProfile(kind="polyline", points_mm=[(-10, -5), (10, -5), (10, 5), (-10, 5)]),
        thickness=Measured(value=3.0, source=Source.inferred),
        features=[ThroughHole(id="hole_1", center_mm=(5.0, 0.0), diameter=d),
                  DShaftBore(id="bore", diameter=Measured(value=6.0, source=Source.inferred),
                             flat_depth=Measured(value=1.5, source=Source.inferred))],
        unknowns=[{"id": "bore.diameter", "question": "Shaft diameter?", "default": 6.0},
                  {"id": "hole_1.diameter", "question": "Hole?", "default": 4.0}],
    )  # fmt: skip
    return run


def test_cited_values_never_override_measured(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    run = _bare_run(tmp_path, intent="knob of my Prestige PIC20 induction cooktop")
    assert evidence.appliance_in(run.job.input.intent) == "Prestige PIC20"
    calls: list[Any] = []

    def fake_lookup(query: str, want: list[str]) -> Any:
        calls.append((query, want))
        cite = Citation(url="https://example.com/pic20-manual", title="PIC20 service manual", quote="6 mm D shaft")
        return types.SimpleNamespace(values=[
            {"name": "bore.diameter", "value_mm": 6.0, "citation": cite},
            {"name": "hole_1.diameter", "value_mm": 5.0, "citation": cite},  # measured 4.2: must not win
            {"name": "thickness", "value_mm": 9.0},  # no citation: ignored
        ], searched=True, notes=[])  # fmt: skip

    monkeypatch.setattr(providers, "lookup_spec", fake_lookup, raising=False)
    evidence.lookup_specs(run)
    assert calls and "PIC20" in calls[0][0]
    assert run.spec is not None
    bore = next(f for f in run.spec.features if f.id == "bore")
    assert isinstance(bore, DShaftBore) and bore.diameter.source == Source.cited
    assert bore.diameter.evidence is not None and bore.diameter.evidence.citation is not None
    assert bore.diameter.evidence.citation.url.endswith("pic20-manual")
    hole = next(f for f in run.spec.features if f.id == "hole_1")
    assert hole.diameter.value == 4.2 and hole.diameter.source == Source.measured
    logs = [e.msg for e in run.job.events if e.t == "log"]
    assert any("disagrees with the measured 4.20 mm" in m for m in logs)
    assert run.spec.thickness.source == Source.inferred  # uncited value ignored
    assert [u.id for u in run.spec.unknowns] == ["hole_1.diameter"]  # still a question for the human
    assert not evidence.accept_cited(run, "hole_1.diameter", 4.3, Citation(url="https://x"))  # within 0.5: silent no


@pytest.mark.slow
def test_completion_is_used_only_when_the_code_gate_accepts(
    sample_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Fake image model, REAL gate: a warped image (markers moved) is rejected and excluded; a clean completion next
    to the part is accepted and enters the broken region as inferred."""
    import cv2
    import numpy as np

    from services.metrology.measure import measure_photo
    from services.metrology.segment import ThresholdSegmenter

    spec = SAMPLES["cover-01"]
    photo = (sample_root / spec.id / "top.png").read_bytes()
    mo = measure_photo(photo, "top", segmenter=ThresholdSegmenter(), thickness_mm=spec.thickness_mm)
    assert mo.result.measurements is not None
    run = _bare_run(tmp_path)
    run.photos["top"] = photo
    run.mo["top"] = mo
    run.measurements["top"] = mo.result.measurements
    assert run.spec is not None
    run.spec.broken_region = BrokenRegion(polygon_mm=[], strategy="mirror")
    proposals: list[str] = []

    def reconstruct(rect_png: bytes, keep_png: bytes, instruction: str = "") -> Any:
        img = np.asarray(cv2.imdecode(np.frombuffer(rect_png, np.uint8), cv2.IMREAD_COLOR), dtype=np.uint8)
        keep = np.asarray(cv2.imdecode(np.frombuffer(keep_png, np.uint8), cv2.IMREAD_GRAYSCALE), dtype=np.uint8) > 127
        assert keep.mean() > 0.5 and not keep.all()  # the model may only touch the band next to the part
        if not proposals:
            out = np.roll(img, 5, axis=1)  # a warped image: the markers move
        else:
            close = np.linalg.norm(img.astype(np.float64) - np.array(spec.part_bgr, np.float64), axis=2) < 40
            _, lab, stats, _ = cv2.connectedComponentsWithStats(close.astype(np.uint8))
            part = lab == 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))  # the part, not marker edges
            xy = np.argwhere(part)[:, ::-1].astype(np.float64)
            axis = np.linalg.eigh(np.cov((xy - xy.mean(axis=0)).T))[1][:, -1]  # the part's long axis (x, y)
            grow = 24.0  # px: the part's own end shape, moved this far along its long axis (the sides run straight on)
            shift = np.array([[1, 0, grow * axis[0]], [0, 1, grow * axis[1]]], np.float32)
            moved = cv2.warpAffine(part.astype(np.uint8), shift, part.shape[::-1], flags=cv2.INTER_NEAREST) > 0
            out = img.copy()
            out[moved & ~part] = spec.part_bgr
        proposals.append(instruction)
        _, buf = cv2.imencode(".png", out)
        return types.SimpleNamespace(data=bytes(buf.tobytes()), mode="mock")

    monkeypatch.setattr(providers, "reconstruct", reconstruct)
    evidence.propose_completion(run)
    labels = [e.label for e in run.job.events if e.t == "artifact" and e.kind == "reconstruction"]
    assert any("rejected by code gate" in lb and "markers moved" in lb for lb in labels), labels
    assert run.completion_accepted is False
    evidence.propose_completion(run)
    labels = [e.label for e in run.job.events if e.t == "artifact" and e.kind == "reconstruction"]
    assert run.completion_accepted is True, labels
    assert any(lb.startswith("Muse Image proposal (mock), accepted by code gate: markers") for lb in labels)
    assert run.spec.broken_region.polygon_mm  # the completion, in the part frame, inferred


def test_mirror_completion_restores_a_symmetric_outline() -> None:
    broken = [(-10.0, -5.0), (10.0, -5.0), (10.0, 5.0), (-4.0, 5.0), (-10.0, -1.0)]
    out = evidence.mirror_completion(broken, 90.0)  # symmetric about the Y axis
    assert out is not None
    xs = [p[0] for p in out]
    assert min(xs) == pytest.approx(-10.0) and max(xs) == pytest.approx(10.0)
    from shapely.geometry import Polygon

    assert Polygon(out).area == pytest.approx(200.0, abs=0.5)


def test_mirror_completion_restores_a_notch_in_the_middle_of_an_end() -> None:
    """A piece missing from the middle of an end is its own mirror image about the long axis: only the end-to-end
    mirror restores it (the cover-tab demo's break)."""
    from shapely.geometry import Polygon

    notched = [(-20.0, -10.0), (20.0, -10.0), (20.0, -4.0), (14.0, -4.0), (14.0, 4.0), (20.0, 4.0), (20.0, 10.0),
               (-20.0, 10.0)]  # fmt: skip
    out = evidence.mirror_completion(notched, 0.0)
    assert out is not None and Polygon(out).area == pytest.approx(800.0, abs=1.0)
    # An outline far from symmetric end to end (a hook-like L) is not mirrored across: that would invent material.
    ell = [(-20.0, -10.0), (20.0, -10.0), (20.0, 10.0), (12.0, 10.0), (12.0, -4.0), (-20.0, -4.0)]
    out_l = evidence.mirror_completion(ell, 0.0)
    assert out_l is not None
    assert Polygon(out_l).area == pytest.approx(Polygon(ell).union(Polygon([(x, -y) for x, y in ell])).area, abs=1.0)


def test_a_broken_part_never_switches_to_a_copy_of_its_outline(tmp_path: Path) -> None:
    """Free code extrudes the measured outline: on a broken part that copies the break into the replacement."""
    run = _bare_run(tmp_path)
    assert run.spec is not None
    run.strategy = "template"
    run.spec.broken_region = BrokenRegion(polygon_mm=[], strategy="mirror")
    assert run.switch_strategy() is True
    assert run.strategy == "template" and not run.switches
    assert any("copy the break" in str(e.msg) for e in run.job.events if e.t == "log")


def test_a_missing_top_gets_no_outline_completion(tmp_path: Path) -> None:
    run = _bare_run(tmp_path)
    assert run.spec is not None
    run.spec.broken_region = BrokenRegion(polygon_mm=[], strategy="template", kind="height")
    evidence.propose_completion(run)
    assert run.spec.broken_region.polygon_mm == []
    assert not [e for e in run.job.events if e.t == "artifact"]


def test_user_taps_become_feature_points(tmp_path: Path) -> None:
    run = _bare_run(tmp_path)
    run.job.write_json(
        "points.json", {"top": [{"x": 812.5, "y": 640.0, "kind": "hole"}, {"x": 900, "y": 700, "kind": "x"}]}
    )
    pts = evidence.feature_points(run)
    users = [p for p in pts if p.source == "user"]
    assert [(p.id, p.kind, p.px) for p in users] == [
        ("tap_1", "hole", (812.5, 640.0)),
        ("tap_2", "hole", (900.0, 700.0)),
    ]


@pytest.mark.slow
def test_orbit_height_resolves_a_tall_feature(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A clip with an 11 mm hook arm on a 3 mm plate, top photo only. Without the orbit the arm height is the template
    default; with an orbit clip the visual-hull height (measured, evidence "orbit") sets it and the first build is
    closer. measure_orbit is replaced by a stand-in with its real return shape (its own tests cover the carving)."""
    from services.metrology import orbit as orbit_mod

    seen: dict[str, Any] = {}

    def fake_measure_orbit(video: bytes, call: Any, *, mime: str, segmenter: Any) -> Any:
        seen.update(mime=mime, n=len(video), has_call=call is not None)
        height = Measured(value=14.0, source=Source.measured, sigma_mm=0.2)
        return types.SimpleNamespace(frames=[], part_to_mat=None, max_height=height, notes=["12 frames kept"],
                                     rejected={"no mat": 1}, n_sampled=13)  # fmt: skip

    monkeypatch.setattr(orbit_mod, "measure_orbit", fake_measure_orbit)
    spec = S.SampleSpec("cliparm-01", "clip", {"length": 40.0, "width": 18.0, "thickness": 3.0, "arm_height": 11.0,
                        "hole_d": 4.2}, 3.0, family_hint="clip", intent="snap clip arm broke")  # fmt: skip
    S.write_sample(spec, tmp_path)
    sample = service.load_sample(tmp_path / spec.id)
    ji = service.sample_job_input(sample.meta)

    def opts() -> RunOptions:
        return RunOptions(question_timeout_s=0.0, mat_id=spec.mat_id, max_iters=1, fix_mode="pipeline")

    plain = service.start_fix_job(sample.photos, ji, sync=True, options=opts())
    clip = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 64
    orbit = service.start_fix_job({**sample.photos, "orbit": clip}, ji, sync=True, options=opts())
    assert seen == {"mime": "video/mp4", "n": len(clip), "has_call": True}
    logs = [e.msg for e in orbit.events if e.t == "log"]
    assert any("visual-hull height 14.00 mm (measured)" in m and "no mat ×1" in m for m in logs), logs
    assert any(e.t == "artifact" and e.kind == "video" for e in orbit.events)
    spec_json = orbit.read_json("partspec.json")
    assert spec_json["thickness"]["source"] == "user_stated"  # the stated plate thickness is not replaced
    v_plain, v_orbit = plain.read_json("values.json"), orbit.read_json("values.json")
    assert v_plain["arm_height"] == 8.0 and abs(v_orbit["arm_height"] - 11.0) < 0.6
    hd = [next(e.hausdorff_mm or 99.0 for e in j.events if e.t == "iteration") for j in (plain, orbit)]
    assert hd[1] < hd[0]


@pytest.mark.slow
def test_zip_and_ship_gate_in_package(sample_root: Path) -> None:
    job = _run(sample_root, "spacer-01")
    kinds = {e.kind for e in job.events if e.t == "artifact"}
    assert "zip" in kinds
    ship = job.read_json("ship.json")
    assert ship["ok"] is True and job.events[-1].summary["can_ship"] is True
    key = next(e.sha for e in job.events if e.t == "artifact" and e.kind == "zip")
    import io
    import zipfile

    from services.common import blobs

    names = set(zipfile.ZipFile(io.BytesIO(blobs.get(key))).namelist())
    assert {"part.py", "part.stl", "verification.json", "README.txt"} <= names
