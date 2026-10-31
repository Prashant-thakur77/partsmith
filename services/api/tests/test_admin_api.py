"""Admin console routes: token gate, overview numbers from stored data, audit trail, moderation, rule switches and
the review queue filters. TEST DATA only (fake service, template parts)."""

from __future__ import annotations

import time
from typing import Any

import pytest
from fastapi.testclient import TestClient
from partsmith_schemas import IterationEvent, ModelCallEvent

from services.admin import audit
from services.api import main as M
from services.api.tests.test_api import _err
from services.api.tests.test_review_api import EMPTY, Svc
from services.registry.store import get_registry
from services.registry.tests.fixtures import add_part
from services.review import store as review_store
from services.review.tests.fakes import finish

ADMIN = {"Authorization": "Bearer s3cret"}


@pytest.fixture
def svc(monkeypatch: pytest.MonkeyPatch) -> Svc:
    from services.api import deps

    s = Svc()
    monkeypatch.setattr(deps, "service", lambda: s)
    M._call_cache.clear()
    return s


@pytest.fixture
def client(svc: Svc, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("PARTSMITH_ADMIN_TOKEN", "s3cret")
    return TestClient(M.app)


ROUTES = [
    ("get", "/api/v1/admin/overview"),
    ("get", "/api/v1/admin/audit"),
    ("get", "/api/v1/admin/parts"),
    ("post", "/api/v1/admin/parts/x/unpublish"),
    ("post", "/api/v1/admin/parts/x/republish"),
    ("get", "/api/v1/admin/rules"),
    ("post", "/api/v1/admin/rules/x/disable"),
    ("post", "/api/v1/admin/rules/x/enable"),
]


def test_every_admin_route_needs_the_token_and_is_in_openapi(client: TestClient) -> None:
    paths = client.get("/api/v1/openapi.json").json()["paths"]
    for method, path in ROUTES:
        _err(getattr(client, method)(path, **({"json": {"reason": "r"}} if method == "post" else {})), 401,
             "admin_required")  # fmt: skip
        tpl = path.replace("/parts/x/", "/parts/{slug}/").replace("/rules/x/", "/rules/{rule_id}/")
        assert method in paths[tpl], tpl


def _job_with(svc: Svc, *, verified: bool, rounds: int, err: float, usd: float) -> Any:
    j = svc.new_job()
    j.emit(ModelCallEvent(job=j.id, provider="mock", model="m1", stage="build", mode="mock", usd=usd, tokens_in=10))
    for i in range(1, rounds + 1):
        j.emit(IterationEvent(job=j.id, iter=i, strategy="template", hausdorff_mm=err))
    finish(j, "verified" if verified else "best_effort")
    j.summary.verified = verified
    j.summary.status = "done"
    j.save_summary()
    return j


def test_overview_counts_come_from_jobs_reviews_registry_and_events(client: TestClient, svc: Svc) -> None:
    a = _job_with(svc, verified=True, rounds=1, err=0.2, usd=0.01)
    _job_with(svc, verified=True, rounds=3, err=0.4, usd=0.02)
    _job_with(svc, verified=False, rounds=6, err=0.9, usd=0.03)
    add_part("spacer", "s-one")
    add_part("spacer", "s-two")
    get_registry().request_need("dishwasher wheel 22 mm", "c1")
    client.post(f"/api/v1/review/{a.id}", json={**EMPTY, "action": "reject", "reason": "Wrong hole"}, headers=ADMIN)
    o = client.get("/api/v1/admin/overview", headers=ADMIN).json()
    assert o["jobs"] == {**o["jobs"], "total": 3, "finished": 3, "verified": 2, "n": 3}
    assert o["jobs"]["pass_rate"] == pytest.approx(2 / 3, abs=1e-3)
    # stored replays are counted from the listing the review queue reads, so the two blocks agree
    replays = [x for x in svc.manager().list(100_000, include_replays=True) if x.is_replay]
    assert o["jobs"]["replays_excluded"] == len(replays)
    assert o["rounds_to_verify"]["buckets"] == [{"rounds": 1, "count": 1}, {"rounds": 3, "count": 1}]
    assert o["max_error"]["n"] == 3 and o["max_error"]["median_mm"] == 0.4 and o["max_error"]["p90_mm"] == 0.9
    assert o["send_back"]["person"]["top"] == [{"reason": "Wrong hole", "count": 1}]
    assert o["send_back"]["test"]["n"] == 0
    assert o["review"]["rejected"] == 1 and o["review"]["waiting"] == 2
    assert o["registry"]["published"] == 2 and o["needs"]["open"] == 1
    assert o["cost"]["usd_total"] == pytest.approx(0.06) and o["cost"]["n_jobs"] == 3
    assert o["cost"]["by_stage"][0]["stage"] == "build" and o["cost"]["by_stage"][0]["calls"] == 3
    assert {"day", "cap_usd", "spent_usd", "source"} <= set(o["budget"])
    for block in ("jobs", "rounds_to_verify", "max_error", "send_back", "review", "registry", "needs", "cost"):
        assert o[block]["source"], block
    s = client.get("/api/v1/status").json()  # /status reads the same shared aggregation
    assert s["cost"] == {k: o["cost"][k] for k in ("usd_total", "usd_per_job_mean", "n_jobs")}
    assert "budget" in s


def test_test_reviews_never_count_as_people(client: TestClient, svc: Svc) -> None:
    a = finish(svc.new_job())
    review_store.decide(a.id, "reject", reason="scripted check", by="test", svc=svc)
    o = client.get("/api/v1/admin/overview", headers=ADMIN).json()
    assert o["send_back"]["person"]["n"] == 0 and o["send_back"]["test"]["top"][0]["reason"] == "scripted check"


def test_decisions_and_admin_writes_land_in_the_audit_log(client: TestClient, svc: Svc) -> None:
    a = finish(svc.new_job())
    client.post(f"/api/v1/review/{a.id}", json={**EMPTY, "action": "reject", "reason": "too thin"}, headers=ADMIN)
    need, _ = get_registry().request_need("door hinge leaf", "c1")
    client.patch(f"/api/v1/needs/{need.id}", json={"status": "in_progress"}, headers=ADMIN)
    lid = get_registry().add_lesson("spacer", "spacer: keep the bore round", {})
    client.post(f"/api/v1/lessons/{lid}/promote", json={}, headers=ADMIN)
    log = client.get("/api/v1/admin/audit", headers=ADMIN).json()
    acts = [i["action"] for i in log["items"]]
    assert acts == ["lesson.promoted", "need.status", "review.reject"]  # newest first
    rv = log["items"][2]
    assert rv["target"] == a.id and rv["actor"] == "person" and rv["note"] == "too thin"
    assert log["items"][1]["before"] == {"status": "open"} and log["items"][1]["after"] == {"status": "in_progress"}
    only = client.get("/api/v1/admin/audit?action=need.status", headers=ADMIN).json()
    assert only["total"] == 1 and only["items"][0]["target"] == need.id
    assert client.get(f"/api/v1/admin/audit?target={a.id}", headers=ADMIN).json()["total"] == 1
    assert client.get("/api/v1/admin/audit?action=lesson.*", headers=ADMIN).json()["total"] == 1


def test_unpublish_hides_from_search_and_mcp_but_keeps_the_slug(client: TestClient, svc: Svc) -> None:
    add_part("spacer", "s-one")
    add_part("spacer", "s-two", params={"height": 14.0})
    _err(client.post("/api/v1/admin/parts/s-one/unpublish", json={"reason": ""}, headers=ADMIN), 422,
         "validation_error")  # fmt: skip
    _err(client.post("/api/v1/admin/parts/nope/unpublish", json={"reason": "x"}, headers=ADMIN), 404, "part_not_found")
    _err(client.post("/api/v1/admin/parts/s-one/republish", json={"reason": "x"}, headers=ADMIN), 409, "not_withdrawn")
    r = client.post("/api/v1/admin/parts/s-one/unpublish", json={"reason": "duplicate"}, headers=ADMIN)
    assert r.status_code == 200 and r.json()["withdrawn"]["reason"] == "duplicate"
    slugs = [p["slug"] for p in client.get("/api/v1/parts?q=spacer").json()["items"]]
    assert slugs == ["s-two"]
    from services.mcp import server

    items, _ = get_registry().search("spacer", role="part")
    assert [p.slug for p in items] == ["s-two"] and server is not None
    d = client.get("/api/v1/parts/s-one").json()
    assert d["slug"] == "s-one" and d["withdrawn"]["reason"] == "duplicate"
    assert client.get("/api/v1/parts/s-two").json()["withdrawn"] is None
    listed = client.get("/api/v1/admin/parts", headers=ADMIN).json()
    row = next(i for i in listed["items"] if i["slug"] == "s-one")
    assert listed["withdrawn"] == 1 and row["withdrawn"]["reason"] == "duplicate"
    keys = {c["key"]: c for c in row["criteria"]}
    assert keys["verified"]["ok"] is True and keys["max_error"]["ok"] is True
    assert keys["max_error"]["value"] == {"max_error_mm": 0.12, "limit_mm": 0.5}
    assert keys["accepted_by_person"]["ok"] is False and keys["has_params"]["ok"] is True
    assert (
        client.post("/api/v1/admin/parts/s-one/republish", json={"reason": "fixed"}, headers=ADMIN).status_code == 200
    )
    assert len(client.get("/api/v1/parts?q=spacer").json()["items"]) == 2
    acts = [i["action"] for i in client.get("/api/v1/admin/audit", headers=ADMIN).json()["items"]]
    assert acts == ["part.republish", "part.unpublish"]


def test_accept_by_a_person_shows_in_the_criteria(client: TestClient, svc: Svc) -> None:
    a = finish(svc.new_job())
    r = client.post(f"/api/v1/review/{a.id}", json={**EMPTY, "action": "accept", "publish": True}, headers=ADMIN)
    slug = r.json()["part_slug"]
    row = next(i for i in client.get("/api/v1/admin/parts", headers=ADMIN).json()["items"] if i["slug"] == slug)
    acc = next(c for c in row["criteria"] if c["key"] == "accepted_by_person")
    assert acc["ok"] is True and acc["value"]["job_id"] == a.id


def test_rules_list_disable_enable(client: TestClient, svc: Svc) -> None:
    reg = get_registry()
    lid = reg.add_lesson("spacer", "spacer: measure the bore twice", {"job_id": "j1"})
    reg.set_lesson_status(lid, "promoted", "reviewer")
    reg.add_lesson("spacer", "a candidate is not taught", {})
    got = client.get("/api/v1/admin/rules", headers=ADMIN).json()
    assert [i["id"] for i in got["items"]] == [lid] and got["items"][0]["origin_job"] == "j1"
    _err(client.post(f"/api/v1/admin/rules/{lid}/disable", json={"reason": ""}, headers=ADMIN), 422, "validation_error")
    _err(client.post("/api/v1/admin/rules/l_nope/disable", json={"reason": "x"}, headers=ADMIN), 404, "rule_not_found")
    _err(client.post(f"/api/v1/admin/rules/{lid}/enable", json={"reason": "x"}, headers=ADMIN), 409, "not_disabled")
    r = client.post(f"/api/v1/admin/rules/{lid}/disable", json={"reason": "made fits worse"}, headers=ADMIN)
    assert r.status_code == 200 and r.json()["disabled"]["reason"] == "made fits worse"
    got = client.get("/api/v1/admin/rules", headers=ADMIN).json()
    assert got["disabled"] == 1
    assert client.post(f"/api/v1/admin/rules/{lid}/enable", json={"reason": "retry"}, headers=ADMIN).status_code == 200
    acts = [i["action"] for i in audit.read()["items"]]
    assert acts == ["rule.enable", "rule.disable"]


def test_feedback_ids_with_slashes_can_be_switched_off(client: TestClient, svc: Svc, monkeypatch: Any) -> None:
    from services.review import ledger

    fid = "j_root/1/pin1"
    entry = {"id": fid, "by": "person", "outcome": "fixed", "kind": "pin", "what": "hole further left",
             "family": "spacer", "used_in": {"jobs": 0}}  # fmt: skip
    monkeypatch.setattr(ledger, "feedback", lambda **kw: {"items": [entry], "counts": {}, "families": []})
    got = client.get("/api/v1/admin/rules", headers=ADMIN).json()["items"]
    assert [(i["id"], i["kind"]) for i in got] == [(fid, "feedback")]
    r = client.post("/api/v1/admin/rules/j_root%2F1%2Fpin1/disable", json={"reason": "wrong"}, headers=ADMIN)
    assert r.status_code == 200, r.text
    from services.admin.rules import disabled_ids

    assert disabled_ids() == {fid}


def test_review_queue_filters(client: TestClient, svc: Svc) -> None:
    a = finish(svc.new_job(), family="spacer")
    b = finish(svc.new_job(), family="hook")
    c = finish(svc.new_job(), family="hook")
    review_store.decide(b.id, "reject", reason="scripted", by="test", svc=svc)
    client.post(f"/api/v1/review/{c.id}", json={**EMPTY, "action": "reject", "reason": "bad"}, headers=ADMIN)

    def ids(q: str) -> set[str]:
        return {i["root_job"] for i in client.get(f"/api/v1/review/queue?{q}").json()["items"]}

    assert ids("") == {a.id, b.id, c.id}
    assert ids("family=hook") == {b.id, c.id}
    assert ids("status=waiting") == {a.id}
    assert ids("by=test") == {b.id} and ids("by=person") == {c.id}
    assert ids("older_than_h=1") == set()
    a.summary.updated_at = time.time() - 7200
    a.save_summary()
    assert ids("older_than_h=1") == {a.id}
    _err(client.get("/api/v1/review/queue?status=maybe"), 422, "validation_error")
