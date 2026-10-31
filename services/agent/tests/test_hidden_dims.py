"""Sizes the photo cannot see (inner bore Ø, socket depth …): typed by the user, given to the builder as numbers the
program must use, set and locked on the knob that holds them, checked against the program after the verdict, and
listed as user-stated (never verified). TEST DATA only; mock providers, no network."""

from __future__ import annotations

from typing import Any

import pytest
from partsmith_schemas import HiddenDim, JobInput, Verification
from partsmith_schemas.common import DataOrigin, Source
from partsmith_schemas.verification import ParamSpec
from pydantic import ValidationError

from services.agent import hidden_dims, service
from services.agent.orchestrator import FixRun, Round, RunOptions
from services.agent.templates import get_template
from services.verifier.part_tests import unchecked_values


def _spec(name: str, default: float = 5.0, lo: float = 1.0, hi: float = 20.0, step: float = 0.1) -> ParamSpec:
    return ParamSpec(name=name, default=default, min=lo, max=hi, step=step, unit="mm", label=name)


def test_schema_limits() -> None:
    assert HiddenDim(name="bore_d", value_mm=8.0).value_mm == 8.0
    for bad in ({"name": "", "value_mm": 3}, {"name": "bore_d", "value_mm": 0}, {"name": "x" * 41, "value_mm": 3}):
        with pytest.raises(ValidationError):
            HiddenDim.model_validate(bad)
    with pytest.raises(ValidationError):
        JobInput(hidden_dims=[HiddenDim(name="wall", value_mm=2.0)] * 5)
    assert JobInput().hidden_dims == []


def test_match_knob_prefers_the_kind_list_order() -> None:
    specs = [_spec("hole_d"), _spec("bore_d"), ParamSpec(name="rib_count", default=2, min=0, max=6, step=1, unit="")]
    assert (k := hidden_dims.match_knob("bore_d", specs)) is not None and k.name == "bore_d"
    assert (k := hidden_dims.match_knob("hole_d", specs)) is not None and k.name == "hole_d"
    assert hidden_dims.match_knob("socket_depth", specs) is None
    assert hidden_dims.match_knob("my own words", specs) is None
    assert hidden_dims.label("bore_d") == "Inner bore Ø" and hidden_dims.label("pin_length") == "pin length"


def test_prompt_block_lists_numbers_the_program_must_use() -> None:
    dims = [HiddenDim(name="bore_d", value_mm=8.0), HiddenDim(name="Lip depth", value_mm=2.5)]
    block = hidden_dims.prompt_block(dims, [_spec("bore_d")])
    assert "user-stated, not measured" in block and "Use these exact values" in block
    assert "- Inner bore Ø = 8 mm (knob bore_d)" in block and "- Lip depth = 2.5 mm" in block
    assert hidden_dims.prompt_block([]) == ""


def test_check_statuses() -> None:
    specs = [_spec("bore_d", step=0.05), _spec("wall", hi=4.0)]
    dims = [
        HiddenDim(name="bore_d", value_mm=8.0),
        HiddenDim(name="wall", value_mm=9.0),  # outside the knob's range
        HiddenDim(name="socket_depth", value_mm=6.0),  # no knob holds it
    ]
    rows = hidden_dims.check(dims, specs, {"bore_d": 8.02, "wall": 2.0})
    assert [r["status"] for r in rows] == ["checked", "used_not_checked", "used_not_checked"]
    assert rows[0]["knob"] == "bore_d" and rows[0]["model_mm"] == 8.02 and rows[0]["tol_mm"] == 0.05
    assert "not part of verified" in rows[0]["note"] and "outside" in rows[1]["note"]
    assert "used, not checked from the photo" in rows[2]["note"]
    assert hidden_dims.check(dims[:1], specs, {"bore_d": 7.0})[0]["status"] == "mismatch"
    lines = hidden_dims.reason_lines(rows)
    assert lines[0].startswith("Inner bore Ø 8 mm stated by the user: ") and len(lines) == 3


def test_unchecked_values_lists_a_held_hidden_size_as_user_stated() -> None:
    specs = [_spec("bore_d"), _spec("height")]
    held = {"bore_d": (8.0, "the user stated the inner bore ø (8 mm)")}
    out = {
        u.param: u for u in unchecked_values(specs, {"bore_d": 8.0, "height": 10.0}, {}, [], ["top"], stated_knobs=held)
    }
    assert out["bore_d"].source == Source.user_stated and "inner bore" in out["bore_d"].note
    assert out["height"].source == Source.inferred
    moved = unchecked_values(specs, {"bore_d": 6.0, "height": 10.0}, {}, [], ["top"], stated_knobs=held)
    assert {u.param: u.source for u in moved}["bore_d"] == Source.inferred  # the model does not hold it: not stated


def _run(dims: list[HiddenDim]) -> FixRun:
    ji = JobInput(kind="fix", origin=DataOrigin.synthetic, hidden_dims=dims)
    job = service.manager().create("fix", ji, title="hidden size test")
    run = FixRun(job, RunOptions(question_timeout_s=0.0))
    run.template = get_template("spacer")
    run.strategy = "template"
    return run


def test_apply_stated_sets_and_locks_the_knob() -> None:
    run = _run([HiddenDim(name="bore_d", value_mm=8.0), HiddenDim(name="socket_depth", value_mm=4.0)])
    code = get_template("spacer").code
    values = run.apply_stated(code, {"bore_d": 3.4, "height": 10.0})
    assert values["bore_d"] == 8.0 and values["height"] == 10.0
    assert "bore_d" in run.locked and "inner bore" in run.locked["bore_d"]
    assert "height" not in run.locked


def test_builder_prompt_carries_the_stated_sizes(monkeypatch: pytest.MonkeyPatch) -> None:
    from partsmith_schemas.common import Measured
    from partsmith_schemas.partspec import BaseProfile, Family, PartSpec

    run = _run([HiddenDim(name="bore_d", value_mm=8.0)])
    run.spec = PartSpec(family=Family.spacer, base_profile=BaseProfile(kind="circle", points_mm=[(0.0, 0.0)]),
                        thickness=Measured(value=10.0))  # fmt: skip
    seen: list[Any] = []

    def fake_call(stage: str, req: Any) -> Any:
        seen.append(req)
        return type("C", (), {"text": "```python\n" + get_template("spacer").code + "\n```"})()

    monkeypatch.setattr(run, "call", fake_call)
    run.build_program("template")
    user = next(m["content"] for m in seen[0].messages if m["role"] == "user")
    assert "Inner bore Ø = 8 mm (knob bore_d)" in user and "user-stated, not measured" in user


def test_verdict_lists_the_check_and_writes_hidden_dims_json() -> None:
    run = _run([HiddenDim(name="bore_d", value_mm=8.0), HiddenDim(name="socket_depth", value_mm=4.0)])
    code = get_template("spacer").code
    values = run.apply_stated(code, {"bore_d": 3.4, "height": 10.0, "outer_d": 12.0})
    rnd = Round(1, "template", code, values, None, None)
    v = run.label_unchecked(Verification(verified=True, status="verified", reasons=["passes"]), rnd)
    bore = next(u for u in v.unchecked if u.param == "bore_d")
    assert bore.source == Source.user_stated
    assert v.reasons[0] == "passes" and any("Socket depth 4 mm" in r for r in v.reasons)
    rows = run.job.read_json("hidden_dims.json")["dims"]
    assert [r["status"] for r in rows] == ["checked", "used_not_checked"]
    again = run.label_unchecked(v, rnd)  # labelling twice never doubles the notes
    assert len(again.reasons) == len(v.reasons)
    detail = service.detail_of(run.job)
    assert [d["status"] for d in detail["hidden_dims"]] == ["checked", "used_not_checked"]


def test_job_detail_shows_pending_sizes_before_the_verdict() -> None:
    run = _run([HiddenDim(name="wall", value_mm=2.0)])
    (row,) = service.detail_of(run.job)["hidden_dims"]
    assert row["status"] == "pending" and row["label"] == "Wall thickness" and row["value_mm"] == 2.0
