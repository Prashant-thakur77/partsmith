"""Fix-loop guardrails in code, not in the prompt: a scripted fixer replays the wall-hook pattern (it keeps shortening a
plate whose measured length already passes, while the outline gets worse) and code holds.

* the length edits are refused by the pinned-knob guard, with the reason logged as an event, so no round moves it;
* after two rounds that leave the keep rule's shortfall where it was, the loop stops ("stopped: no progress for 2
  rounds") instead of spending the remaining rounds.

The sample is a synthetic wall hook (corner radius 0.5 mm, so the template's default corners are the real misfit). The
recorded wall-hook job could not leave its template (its side photo showed the arm above the plate); the test pins that
situation by making `side_taller_than_plate` true. Nothing touches the network.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from services.agent import agent_loop, providers, service
from services.agent.orchestrator import FixRun, RunOptions
from services.agent.tests import synth_samples as S

pytestmark = pytest.mark.slow

HOOK = S.SampleSpec(
    "hook-guard",
    "hook",
    {"length": 50.0, "width": 22.0, "plate_thickness": 4.5, "reach": 24.0, "corner_radius": 0.5},
    4.5,
    family_hint="hook",
    intent="the wall hook came off the wall",
)


@pytest.fixture(scope="module")
def hook_root(tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("guard_samples")
    S.write_sample(HOOK, root)
    return root


def _run(root: Path, mode: str, monkeypatch: pytest.MonkeyPatch) -> Any:
    monkeypatch.setattr(FixRun, "side_taller_than_plate", lambda self: True)
    sample = service.load_sample(root / HOOK.id)
    ji = service.sample_job_input(sample.meta)
    o = RunOptions(question_timeout_s=0.0, mat_id=str(sample.meta["mat_id"]), max_iters=6, fix_mode=mode)  # type: ignore[arg-type]
    return service.start_fix_job(sample.photos, ji, sync=True, options=o)


def _wall_hook_edits(values: dict[str, Any]) -> list[dict[str, Any]]:
    """What the recorded fixer did: shorten the (passing) plate length by 2 mm, plus a change that makes the outline
    worse (rounder corners on a part with sharp ones)."""
    return [
        {"param": "length", "to": float(values["length"]) - 2.0, "reason": "shorten toward the footprint"},
        {"param": "corner_radius", "to": float(values["corner_radius"]) + 1.5, "reason": "reduce the corner gap"},
    ]


@pytest.mark.parametrize("mode", ["pipeline", "agent"])
def test_a_scripted_fixer_cannot_move_a_passing_pinned_length_and_the_loop_stops(
    hook_root: Path, mode: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = {"n": 0}

    def fixer(req: Any) -> dict[str, Any]:
        calls["n"] += 1
        values = req.mock_context["values"]
        edits = [dict(e, **{"from": float(values[e["param"]])}) for e in _wall_hook_edits(values)]
        return {"analysis": "scripted wall-hook fixer", "edits": edits, "code_patch": None}

    def agent(req: Any, history: Any = None) -> dict[str, Any]:
        # inspect, commit, inspect, commit (two rounds without progress), one more commit that code must refuse, submit
        calls["n"] += 1
        session = next(iter(agent_loop._POLICIES.values())).s
        if calls["n"] in (1, 3):
            return {"tool": "inspect_residuals", "args": {"view": "all"}, "thought": "Looking."}
        if calls["n"] in (2, 4, 5):
            return {
                "tool": "set_params",
                "args": {"edits": _wall_hook_edits(session.base.values)},
                "thought": "Shorten.",
            }
        return {"tool": "submit", "args": {"reason": "scripted fixer done"}, "thought": "Done."}

    if mode == "pipeline":
        providers.register_mock("fix", fixer, replace=True)
    else:
        providers.register_mock(agent_loop.STAGE, agent, replace=True)
    try:
        job = _run(hook_root, mode, monkeypatch)
    finally:
        providers.unregister_mock("fix" if mode == "pipeline" else agent_loop.STAGE)

    if mode == "pipeline":
        assert calls["n"] == 2, "the fixer is not asked again once the loop has stopped"
    rounds = [e for e in job.events if e.t == "iteration"]
    logs = [str(e.msg) for e in job.events if e.t == "log"]
    first = rounds[0]
    assert first.passed_tests == first.total_tests, "the first build's sizes (length included) must pass for this test"
    # the guard holds: no round moved the length, and the refusal is an event with its reason
    assert not [e for e in rounds if any(d.get("param") == "length" for d in e.edits)]
    pinned = [m for m in logs if m.startswith("guard: length: pinned")]
    assert (
        pinned and "its size test passes" in pinned[0] and "nothing in this round's evidence points at it" in pinned[0]
    )
    # the other edit went through and made things worse: two rounds without progress, then the loop stops
    assert [e.iter for e in rounds] == [1, 2, 3]
    assert all(any(d.get("param") == "corner_radius" for d in e.edits) for e in rounds[1:])
    assert all(e.pass_shortfall is not None and e.pass_shortfall >= first.pass_shortfall for e in rounds[1:])
    stops = [m for m in logs if m.startswith("stopped: no progress for 2 rounds")]
    assert len(stops) == 1 and "round 1 stays the closest to passing" in stops[0]
    assert not [m for m in logs if "switching from the template to free code" in m]
    done = job.events[-1]
    assert done.status == "best_effort" and not done.verified
    assert job.read_json("values.json")["length"] == pytest.approx(first_values(job)["length"])
    if mode == "agent":
        refused = [e for e in job.events if e.t == "tool_call" and e.name == "set_params" and "nothing committed: stopped"
                   in e.result]  # fmt: skip
        assert refused, "a set_params after the stop is refused by code"


def first_values(job: Any) -> dict[str, float]:
    """The first build's knob values, from the first round's program artifact (part.py after round 1)."""
    from services.common import blobs
    from services.geom_worker.program import defaults

    art = next(e for e in job.events if e.t == "artifact" and e.kind == "code" and e.iter == 1)
    return defaults(blobs.locate(art.url.rsplit("/", 1)[-1]).read_text())
