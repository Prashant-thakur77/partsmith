from __future__ import annotations

import pytest

from services.agent.templates import get_template
from services.registry import steer
from services.registry.store import get_registry
from services.registry.tests.fixtures import add_part


def test_mock_plan_is_a_coherent_kit() -> None:
    plan = steer.mock_plan("cupboard hardware kit, M3 screws, 5 mm grid", 7)
    parts = plan["parts"]
    assert len(parts) == 7
    templates = {p["template"] for p in parts}
    assert {"cupboard_latch", "hinge_leaf"} <= templates
    for p in parts:
        t = get_template(p["template"])
        for name, v in p["params"].items():
            spec = t.param(name)
            assert spec.min <= v <= spec.max
        if "hole_d" in p["params"]:
            assert p["params"]["hole_d"] == 3.4  # one shared M3 clearance
        for k in ("length", "width"):
            if k in p["params"] and p["params"][k] >= 5:
                assert p["params"][k] % 5 == pytest.approx(0, abs=1e-6) or p["params"][k] in (
                    t.param(k).min,
                    t.param(k).max,
                )
    assert len({p["slug"] for p in parts}) == 7


def test_check_plan_guards_model_output() -> None:
    add_part("clip", "kit-clip")
    raw = {
        "family_title": "Kit",
        "parts": [
            {
                "slug": "kit-clip",
                "title": "Clip",
                "template": "clip",
                "params": {"hole_d": 99, "lenght": 50},
                "why": "",
            },
            {"slug": "kit-clip", "title": "Clip 2", "template": "clip", "params": {}, "why": ""},
            {"slug": "Bad Slug!", "title": "Hook", "template": "hooks", "params": {}, "why": ""},
            {"slug": "x", "title": "?", "template": "zeppelin", "params": {}, "why": ""},
        ],
    }
    title, parts, notes = steer.check_plan(raw, 5)
    assert title == "Kit"
    # unique within the plan, clean; registry collisions are resolved when a part is published
    assert [p["slug"] for p in parts] == ["kit-clip", "kit-clip-2", "bad-slug"]
    assert parts[0]["params"]["hole_d"] == 6.0 and parts[0]["params"]["length"] == 50.0
    assert parts[2]["template"] == "hook"
    assert any("zeppelin" in n for n in notes) and any("clamped" in n for n in notes)


def test_steer_run_review_flow() -> None:
    rid = steer.start("desk cable kit", 2, sync=True)
    state = steer.get(rid)
    assert state["status"] == "reviewing" and state["planner"]["mode"] == "mock"
    assert len(state["plan"]) == 2 and all(lane["status"] == "done" for lane in state["lanes"])
    q = state["queue"]
    assert all(item["status"] == "pending_review" and item["job_id"] for item in q)
    assert all(item["verified"] for item in q), q  # self-check of a template against its own render passes
    first, second = q[0]["slug"], q[1]["slug"]

    state = steer.review(rid, first, "approve")
    part = get_registry().get_part(first)
    assert part is not None and part.provenance.origin.value == "synthetic"
    assert "SYNTHETIC self-check" in part.provenance.note
    assert get_registry().thumbnail(first) is not None
    assert next(x for x in state["queue"] if x["slug"] == first)["status"] == "published"
    with pytest.raises(ValueError):
        steer.review(rid, first, "approve")

    before = next(p for p in state["plan"] if p["slug"] == second)["params"]
    state = steer.review(rid, second, "send_back", "2 mm wider")
    assert state["history"][-1]["applied"], state["history"][-1]
    state = steer.wait(rid, 60)
    item = next(x for x in state["queue"] if x["slug"] == second)
    assert item["status"] == "pending_review"
    after = next(p for p in state["plan"] if p["slug"] == second)["params"]
    assert after != before
    state = steer.review(rid, second, "reject", "not needed")
    assert state["status"] == "done"
    assert get_registry().get_part(second) is None
    assert steer.list_runs()[0]["id"] == rid
