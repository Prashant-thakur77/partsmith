"""Review store: queue, decisions, chains, rule promotion, judge-vs-person agreement, rule track records."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from services.agent import jobs
from services.registry.store import get_registry
from services.review import store
from services.review.store import ReviewError
from services.review.tests.fakes import FakeService, finish


@pytest.fixture
def svc() -> FakeService:
    return FakeService()


def _err(exc: pytest.ExceptionInfo[ReviewError], status: int, code: str) -> None:
    assert (exc.value.status, exc.value.code) == (status, code), exc.value.message


def test_queue_lists_finished_fix_jobs_only(svc: FakeService) -> None:
    a = finish(svc.new_job())
    finish(svc.new_job(), "refused")
    finish(svc.new_job(purpose="reference_check"))
    svc.new_job()  # still running
    items = store.queue(svc=svc)
    assert [i["job_id"] for i in items] == [a.id]
    (it,) = items
    assert it["status"] == "waiting" and it["round"] == 1 and it["root_job"] == a.id and it["family"] == "spacer"
    assert it["verdict"]["status"] == "verified" and it["judge"]["scores"] and it["is_replay"] is False


def test_improve_then_child_finishes_into_round_2(svc: FakeService) -> None:
    a = finish(svc.new_job())
    out = store.decide(
        a.id, "improve", pins=[{"u": 0.4, "v": 0.5, "note": "edge further left"}], note="also thicker", svc=svc
    )
    child_id = out["child_job"]
    assert child_id and svc.started[0][1] == 2 and svc.started[0][2][0].id == 1  # ids are given by the server
    assert out["state"]["status"] == "improving"
    assert [i["status"] for i in store.queue(svc=svc)] == ["improving"]
    with pytest.raises(ReviewError) as e:
        store.decide(a.id, "improve", note="again", svc=svc)
    _err(e, 409, "review_busy")
    with pytest.raises(ReviewError) as e:
        store.decide(child_id, "accept", svc=svc)
    _err(e, 409, "not_finished")
    child = svc.mgr.get(child_id)
    assert child is not None
    child.write_json(
        "review_round.json",
        {
            "parent_job": a.id,
            "round": 2,
            "note": "also thicker",
            "pins": [
                {
                    "id": 1,
                    "u": 0.4,
                    "v": 0.5,
                    "note": "edge further left",
                    "mat_mm": [10.0, 20.0],
                    "part_mm": [1.0, 2.0],
                    "before_mm": 0.84,
                    "after_mm": 0.21,
                }
            ],
        },
    )
    finish(child)
    (item,) = store.queue(svc=svc)
    assert item["status"] == "waiting" and item["round"] == 2 and item["job_id"] == child_id
    d = store.detail(a.id, svc=svc)
    assert d == store.detail(child_id, svc=svc)
    r1, r2 = d["rounds"]
    assert r1["decision"] == "improve" and r1["child_job"] == child_id and r2["decision"] is None
    (pin,) = r1["pins"]
    assert pin["before_mm"] == 0.84 and pin["after_mm"] == 0.21 and pin["mat_mm"] == [10.0, 20.0]
    assert set(r1["verdict"]) >= {"status", "max_error_mm"}
    # each improve note is a lesson candidate with the chain as evidence
    cands = [x for x in get_registry().lessons("spacer", "candidate") if x["evidence"].get("kind") == "improve_note"]
    assert {x["rule"] for x in cands} == {"spacer: edge further left", "spacer: also thicker"}
    # pin numbers continue across the chain
    store.decide(child_id, "improve", pins=[{"u": 0.1, "v": 0.1, "note": "x"}], svc=svc)
    assert svc.started[-1][2][0].id == 2


def test_accept_promotes_ticked_rules_only(svc: FakeService) -> None:
    a = finish(svc.new_job(), "best_effort")
    published: list[tuple[str, str]] = []

    def publisher(job_id: str, note: str) -> str:
        published.append((job_id, note))
        return "test-spacer"

    out = store.decide(
        a.id,
        "accept",
        rules=[
            {"text": "spacer: chamfer both bore ends", "keep": True, "source_pin": None},
            {"text": "spacer: one-off note", "keep": False, "source_pin": None},
        ],
        publish=True,
        publisher=publisher,
        svc=svc,
    )
    assert out["part_slug"] == "test-spacer" and published == [(a.id, store.ACCEPTED_NOTE)]
    assert out["state"]["status"] == "accepted"
    promoted = get_registry().lessons("spacer", "promoted")
    assert [x["rule"] for x in promoted] == ["spacer: chamfer both bore ends"]
    assert promoted[0]["promoted_by"] == "reviewer" and promoted[0]["evidence"]["job_ids"] == [a.id]
    assert [x["rule"] for x in get_registry().lessons("spacer", "candidate")] == ["spacer: one-off note"]
    with pytest.raises(ReviewError) as e:
        store.decide(a.id, "reject", reason="changed my mind", svc=svc)
    _err(e, 409, "review_decided")
    assert store.queue(svc=svc)[0]["status"] == "accepted"
    assert not (a.dir / "review.json").exists()  # nothing is written into the job's directory


def test_accept_with_zero_rules_and_reject_needs_a_reason(svc: FakeService) -> None:
    a, b = finish(svc.new_job()), finish(svc.new_job())
    assert store.decide(a.id, "accept", svc=svc)["state"]["status"] == "accepted"
    with pytest.raises(ReviewError) as e:
        store.decide(b.id, "reject", reason="  ", svc=svc)
    _err(e, 422, "validation_error")
    with pytest.raises(ReviewError) as e:
        store.decide(b.id, "improve", svc=svc)
    _err(e, 422, "review_empty")
    with pytest.raises(ReviewError) as e:
        store.decide(b.id, "improve", pins=[{"u": 1.2, "v": 0.5, "note": "off the image"}], svc=svc)
    _err(e, 422, "validation_error")
    with pytest.raises(ReviewError) as e:
        store.decide("j_nope", "accept", svc=svc)
    _err(e, 404, "job_not_found")
    out = store.decide(b.id, "reject", reason="wrong part entirely", svc=svc)
    assert out["state"]["status"] == "rejected"
    rej = [x for x in get_registry().lessons("spacer") if x["evidence"].get("kind") == "reject_reason"]
    assert rej and "wrong part entirely" in rej[0]["rule"] and rej[0]["status"] == "candidate"


def test_improve_on_a_replay_leaves_the_replay_untouched(svc: FakeService, tmp_path: Path) -> None:
    a = finish(svc.new_job())
    dest = jobs.export_replay(a)  # REPLAYS_DIR is under tmp (fixture)
    before = {p.name: p.stat().st_mtime for p in dest.iterdir()}
    svc.mgr = jobs.JobManager(root=tmp_path / "other_runs")  # only the replay is left
    (item,) = store.queue(svc=svc)
    assert item["is_replay"] is True
    out = store.decide(a.id, "improve", note="make the bore bigger", svc=svc)
    assert out["child_job"] and (store.reviews_dir() / f"{a.id}.json").exists()
    assert {p.name: p.stat().st_mtime for p in dest.iterdir()} == before
    assert not str(store.reviews_dir()).startswith(str(jobs.REPLAYS_DIR))
    child = svc.mgr.get(out["child_job"])
    assert child is not None
    finish(child)
    (item,) = store.queue(svc=svc)
    assert item["job_id"] == child.id and item["is_replay"] is False  # a live round of a replay is not a replay


def _state(root: str, rounds: list[tuple[str, dict[str, Any] | None]]) -> None:
    store._save(
        {
            "root_job": root,
            "rounds": [
                {"round": i + 1, "job_id": f"{root}_{i}", "decision": d, "judge": j, "pins": []}
                for i, (d, j) in enumerate(rounds)
            ],
        }
    )


def _judge(ok: bool, blocking: bool = False) -> dict[str, Any]:
    score = 4 if ok else 2
    return {
        "scores": [{"criterion": "outline", "score": score, "reason": ""}],
        "vetoes": [{"feature": "hole", "issue": "x", "severity": "blocking"}] if blocking else [],
    }


def test_stats_kappa_on_a_known_table() -> None:
    assert store.stats()["n"] == 0 and store.stats()["kappa"] is None
    # (judge ok, person ok) per decided round with a scorecard; a blocking veto makes the judge "not ok"
    _state("j_a", [("accept", _judge(True))])
    _state("j_b", [("reject", _judge(False))])
    _state("j_c", [("improve", _judge(True, blocking=True)), ("accept", _judge(True))])
    _state("j_d", [("accept", None), ("reject", {"scores": [], "vetoes": []})])  # judge missing: not counted
    s = store.stats()
    # (ok, accept) (not, reject) (not: blocking veto, improve) (ok, accept): full agreement
    assert s["n"] == 4 and s["both_ok"] == 2 and s["both_not"] == 2 and s["kappa"] == 1.0
    _state("j_a", [("reject", _judge(True))])  # judge ok, person not
    _state("j_b", [("accept", _judge(False))])  # judge not, person ok
    s = store.stats()
    assert s["n"] == 4 and s["agree"] == 2 and s["kappa"] == 0.0
    _state("j_b", [("reject", _judge(False))])
    s = store.stats()  # agree 3/4, judge_ok 2/4, person_ok 1/4 → po .75, pe .5 → kappa .5
    assert (s["agree"], s["judge_ok_person_not"], s["judge_not_person_ok"]) == (3, 1, 0)
    assert s["kappa"] == pytest.approx(0.5) and s["reviewers"] == 1


def test_lesson_track_counts_jobs_and_later_reviews(svc: FakeService) -> None:
    a, b, c = (finish(svc.new_job()) for _ in range(3))
    for j in (a, b, c):
        j.write_json("lessons_used.json", {"family": "spacer", "lesson_ids": ["l_x"]})
    store.decide(a.id, "accept", svc=svc)
    store.decide(b.id, "reject", reason="no", svc=svc)
    assert store.lesson_track("l_x") == {"used_in": 3, "accepted": 1, "improved": 0, "rejected": 1}
    assert store.lesson_track("l_none") == {"used_in": 0, "accepted": 0, "improved": 0, "rejected": 0}
    assert json.loads((store.reviews_dir() / f"{a.id}.json").read_text())["rounds"][0]["decision"] == "accept"
