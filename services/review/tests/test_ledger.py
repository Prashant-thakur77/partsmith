"""The feedback log: what a reviewer said, why, and what code measured next; what later jobs are given."""

from __future__ import annotations

import pytest

from services.review import ledger, store
from services.review.tests.fakes import FakeService, finish


@pytest.fixture
def svc() -> FakeService:
    return FakeService()


def _round2(svc: FakeService, parent_id: str, child_id: str, before: float, after: float, status: str) -> None:
    child = svc.mgr.get(child_id)
    assert child is not None
    child.write_json(
        "review_round.json",
        {"parent_job": parent_id, "round": 2, "note": "", "pins": [
            {"id": 1, "u": 0.4, "v": 0.5, "note": "edge further left", "mat_mm": [10.0, 20.0], "part_mm": [1.0, 2.0],
             "before_mm": before, "after_mm": after},
        ]},
    )  # fmt: skip
    finish(child, status)


def test_classify_reads_the_measured_change() -> None:
    assert ledger.classify(0.84, 0.21, 0.5, next_done=True) == "fixed"
    assert ledger.classify(1.80, 0.90, 0.5, next_done=True) == "better"
    assert ledger.classify(0.60, 0.70, 0.5, next_done=True) == "not_fixed"
    assert ledger.classify(None, 0.2, 0.5, next_done=True) == "not_measured"
    assert ledger.classify(0.84, None, 0.5, next_done=False) == "waiting"


def test_every_piece_of_feedback_is_logged_with_its_reason_and_result(svc: FakeService) -> None:
    a = finish(svc.new_job(), "best_effort")
    out = store.decide(
        a.id,
        "improve",
        pins=[{"u": 0.4, "v": 0.5, "note": "edge further left"}],
        note="also thicker",
        why="it has to clip into the rail",
        svc=svc,
    )
    log = ledger.feedback(svc=svc)
    assert [e["outcome"] for e in log["items"]] == ["waiting", "waiting"]  # the next round is still running
    _round2(svc, a.id, out["child_job"], 0.84, 0.21, "verified")
    store.decide(out["child_job"], "accept", why="matches the rail clip now", svc=svc)
    b = finish(svc.new_job(), "best_effort")
    store.decide(b.id, "reject", reason="wrong part photographed", by="test", svc=svc)

    items = {e["kind"]: e for e in ledger.feedback(svc=svc)["items"]}
    pin = items["pin"]
    assert pin["what"] == "edge further left" and pin["why"] == "it has to clip into the rail"
    assert (pin["before_mm"], pin["after_mm"], pin["outcome"]) == (0.84, 0.21, "fixed")
    assert pin["where"]["pin"] == 1 and pin["by"] == "person" and pin["family"] == "spacer"
    assert items["note"]["outcome"] == "fixed"  # the next round passed the verifier
    assert items["accept"]["why"] == "matches the rail clip now" and items["accept"]["outcome"] == "accepted"
    assert items["reject"]["what"] == "wrong part photographed" and items["reject"]["by"] == "test"
    assert ledger.feedback(by="test", svc=svc)["counts"] == {"rejected": 1}
    assert ledger.feedback(outcome="fixed", svc=svc)["counts"] == {"fixed": 2}


def test_later_jobs_get_only_a_persons_fixed_feedback(svc: FakeService) -> None:
    a = finish(svc.new_job(), "best_effort")
    out = store.decide(a.id, "improve", pins=[{"u": 0.4, "v": 0.5, "note": "edge further left"}], why="rail", svc=svc)
    _round2(svc, a.id, out["child_job"], 0.84, 0.21, "verified")
    t = finish(svc.new_job(), "best_effort")
    out_t = store.decide(t.id, "improve", pins=[{"u": 0.4, "v": 0.5, "note": "test-only note"}], by="test", svc=svc)
    _round2(svc, t.id, out_t["child_job"], 0.84, 0.21, "verified")
    n = finish(svc.new_job(), "best_effort")
    out_n = store.decide(n.id, "improve", pins=[{"u": 0.4, "v": 0.5, "note": "did not help"}], svc=svc)
    _round2(svc, n.id, out_n["child_job"], 0.84, 0.95, "best_effort")

    got = ledger.for_prompt("spacer", svc=svc)
    assert [e["what"] for e in got] == ["edge further left"]  # not the test's, not the unfixed one
    line = ledger.prompt_line(got[0])
    assert '"edge further left"' in line and 'why: "rail"' in line and "0.84 → 0.21 mm" in line
    assert ledger.for_prompt("spacer", exclude_roots=[a.id], svc=svc) == []  # its own chain already has its notes
    assert ledger.for_prompt("hinge", svc=svc) == []
