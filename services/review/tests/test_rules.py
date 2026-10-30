"""Rule drafts: one per note in the chain, through the `review_rules` stage (mock = the note, scoped), labelled calls."""

from __future__ import annotations

from typing import Any

from services.agent import providers
from services.agent.providers import ModelRequest
from services.review import rules, store
from services.review.tests.fakes import FakeService, finish


def _chain(svc: FakeService) -> tuple[Any, Any]:
    a = finish(svc.new_job())
    out = store.decide(
        a.id,
        "improve",
        pins=[{"u": 0.4, "v": 0.5, "note": "the corner is square"}, {"u": 0.6, "v": 0.5, "note": ""}],
        note="hole is for an M3 screw",
        svc=svc,
    )
    child = svc.mgr.get(out["child_job"])
    assert child is not None
    child.write_json(
        "review_round.json", {"pins": [{"id": 1, "part_mm": [1.0, 2.0], "before_mm": 0.9, "after_mm": 0.2}]}
    )
    return a, finish(child)


def test_draft_one_rule_per_note_with_mock_label() -> None:
    svc = FakeService()
    _, child = _chain(svc)
    drafts = rules.draft(child.id, svc=svc)
    assert drafts == [
        {"text": "spacer: the corner is square", "source_pin": 1, "scope": "spacer"},
        {"text": "spacer: hole is for an M3 screw", "source_pin": None, "scope": "spacer"},
    ]
    calls = [e for e in child.events if e.t == "model_call" and e.stage == "review_rules"]
    assert len(calls) == 2 and all(c.mode == "mock" for c in calls)
    assert rules.draft(finish(svc.new_job()).id, svc=svc) == []  # no notes, no drafts


def test_draft_skip_and_user_prompt() -> None:
    seen: list[ModelRequest] = []

    def writer(req: ModelRequest) -> dict[str, Any]:
        seen.append(req)
        return {"rule": "skip"} if "M3" in req.messages[-1]["content"] else {"rule": "spacer: square the corners"}

    providers.register_mock("review_rules", writer, replace=True)
    svc = FakeService()
    _, child = _chain(svc)
    assert rules.draft(child.id, svc=svc) == [
        {"text": "spacer: square the corners", "source_pin": 1, "scope": "spacer"}
    ]
    user = seen[0].messages[-1]["content"]
    assert "before 0.90 mm, after 0.20 mm" in user and "pin 1 at (1.0, 2.0) mm" in user
