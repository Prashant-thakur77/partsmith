"""Review routes: public reads, admin writes, the decision contract the web page codes against, every error code once."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from services.api import main as M
from services.api.tests.test_api import _err
from services.registry.store import get_registry
from services.registry.tests.fixtures import make_part
from services.review.tests.fakes import FakeService, finish

ADMIN = {"Authorization": "Bearer s3cret"}
EMPTY = {"pins": [], "note": "", "reason": "", "rules": [], "publish": False}  # the web sends all six fields


class Svc(FakeService):
    def publish(self, job_id: str, *, slug: str | None = None, note: str = "") -> Any:
        part = make_part("spacer", slug or f"spacer-{job_id[-6:]}", verified=False)
        part.provenance.job_id = job_id
        part.provenance.note = note
        get_registry().upsert_part(part)
        return part


@pytest.fixture
def svc(monkeypatch: pytest.MonkeyPatch) -> Svc:
    from services.api import deps

    s = Svc()
    monkeypatch.setattr(deps, "service", lambda: s)
    return s


@pytest.fixture
def client(svc: Svc) -> TestClient:
    return TestClient(M.app)


def test_reads_are_public_and_listed_in_openapi(client: TestClient, svc: Svc, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PARTSMITH_ADMIN_TOKEN", "s3cret")
    a = finish(svc.new_job())
    items = client.get("/api/v1/review/queue?include_replays=1").json()["items"]
    assert [i["job_id"] for i in items] == [a.id]
    assert set(items[0]) >= {
        "job_id",
        "root_job",
        "round",
        "title",
        "family",
        "status",
        "verdict",
        "judge",
        "cost_usd",
        "is_replay",
        "updated_at",
    }
    assert set(items[0]["verdict"]) >= {"status", "max_error_mm"}
    d = client.get(f"/api/v1/review/{a.id}").json()
    assert set(d) >= {"root_job", "status", "rounds", "images"} and set(d["images"]) == {
        "rectified",
        "overlay",
        "focus",
        "worst",
    }
    focus = d["images"]["focus"]
    if focus is not None:  # the part's box on the photo, as fractions, for the page's zoom
        u0, v0, u1, v1 = focus
        assert 0 <= u0 < u1 <= 1 and 0 <= v0 < v1 <= 1
    assert set(d["rounds"][0]) >= {
        "round",
        "job_id",
        "decision",
        "at",
        "note",
        "reason",
        "pins",
        "verdict",
        "judge",
        "child_job",
    }
    assert client.get("/api/v1/review/stats").json()["n"] == 0
    paths = client.get("/api/v1/openapi.json").json()["paths"]
    assert {"/api/v1/review/queue", "/api/v1/review/stats", "/api/v1/review/{job_id}"} <= set(paths)
    _err(client.post(f"/api/v1/review/{a.id}", json={**EMPTY, "action": "accept"}), 401, "admin_required")
    _err(client.post(f"/api/v1/review/{a.id}/rules/draft"), 401, "admin_required")
    assert client.post(f"/api/v1/review/{a.id}", json={**EMPTY, "action": "accept"}, headers=ADMIN).status_code == 200


def test_improve_draft_accept_and_publish(client: TestClient, svc: Svc) -> None:
    a = finish(svc.new_job(), "best_effort")
    r = client.post(
        f"/api/v1/review/{a.id}",
        json={
            **EMPTY,
            "action": "improve",
            "note": "corner is square",
            "pins": [{"u": 0.2, "v": 0.3, "note": "here"}, {"u": 0.5, "v": 0.5, "note": "and here"}],
        },
    )
    assert r.status_code == 200, r.text
    out = r.json()
    child = out["child_job"]
    assert child and out["part_slug"] is None and out["state"]["status"] == "improving"
    assert [p["id"] for p in out["state"]["rounds"][0]["pins"]] == [1, 2]
    _err(client.post(f"/api/v1/review/{a.id}", json={**EMPTY, "action": "improve", "note": "x"}), 409, "review_busy")
    _err(client.post(f"/api/v1/review/{child}", json={**EMPTY, "action": "accept"}), 409, "not_finished")
    cj = svc.mgr.get(child)
    assert cj is not None
    finish(cj, "best_effort")
    drafts = client.post(f"/api/v1/review/{child}/rules/draft").json()["rules"]
    assert [d["text"] for d in drafts] == ["spacer: here", "spacer: and here", "spacer: corner is square"]
    assert set(drafts[0]) == {"text", "source_pin", "scope"}
    rules = [dict(d, keep=i == 0) for i, d in enumerate(drafts)]
    for d in rules:
        d.pop("scope")
    r = client.post(f"/api/v1/review/{child}", json={**EMPTY, "action": "accept", "rules": rules, "publish": True})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["state"]["status"] == "accepted" and out["part_slug"]
    part = get_registry().get_part(out["part_slug"])
    assert part is not None and "accepted by a person" in part.provenance.note
    assert [x["rule"] for x in get_registry().lessons("spacer", "promoted")] == ["spacer: here"]
    lessons = client.get("/api/v1/lessons").json()
    assert all("track" in x for x in lessons)


def test_error_codes(client: TestClient, svc: Svc) -> None:
    a = finish(svc.new_job())
    _err(client.get("/api/v1/review/j_nope"), 404, "job_not_found")
    _err(client.post("/api/v1/review/j_nope", json={**EMPTY, "action": "accept"}), 404, "job_not_found")
    _err(client.post(f"/api/v1/review/{a.id}", json={**EMPTY, "action": "improve"}), 422, "review_empty")
    _err(client.post(f"/api/v1/review/{a.id}", json={**EMPTY, "action": "reject"}), 422, "validation_error")
    _err(
        client.post(
            f"/api/v1/review/{a.id}", json={**EMPTY, "action": "improve", "pins": [{"u": 1.5, "v": 0.5, "note": "x"}]}
        ),
        422,
        "validation_error",
    )
    _err(client.post(f"/api/v1/review/{a.id}", json={**EMPTY, "action": "maybe"}), 422, "validation_error")
    running = svc.new_job()
    _err(client.post(f"/api/v1/review/{running.id}", json={**EMPTY, "action": "accept"}), 409, "not_finished")
    assert (
        client.post(f"/api/v1/review/{a.id}", json={**EMPTY, "action": "reject", "reason": "wrong"}).status_code == 200
    )
    _err(client.post(f"/api/v1/review/{a.id}", json={**EMPTY, "action": "accept"}), 409, "review_decided")


def _png(w: int = 320, h: int = 240) -> bytes:
    import io

    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (w, h), (200, 120, 40)).save(buf, format="PNG")
    return buf.getvalue()


def test_a_pasted_screenshot_goes_with_an_improve(client: TestClient, svc: Svc) -> None:
    a = finish(svc.new_job(), "best_effort")
    up = client.post(f"/api/v1/review/{a.id}/attachments", files={"image": ("paste.png", _png(), "image/png")})
    assert up.status_code == 200, up.text
    key = up.json()["key"]
    assert up.json()["url"].endswith(key)
    _err(
        client.post(f"/api/v1/review/{a.id}/attachments", files={"image": ("x.txt", b"not an image", "text/plain")}),
        422,
        "bad_image",
    )
    _err(
        client.post(f"/api/v1/review/{a.id}", json={**EMPTY, "action": "improve", "attachments": ["nope.png"]}),
        422,
        "validation_error",
    )
    # an image alone is enough to send a part back
    r = client.post(f"/api/v1/review/{a.id}", json={**EMPTY, "action": "improve", "attachments": [key]})
    assert r.status_code == 200, r.text
    assert svc.attachments[-1] == [key]
    (rnd, _) = r.json()["state"]["rounds"]
    assert len(rnd["attachments"]) == 1 and rnd["attachments"][0].endswith(key)


def test_the_feedback_log_is_public_and_keeps_the_why(client: TestClient, svc: Svc) -> None:
    a = finish(svc.new_job(), "best_effort")
    r = client.post(
        f"/api/v1/review/{a.id}",
        json={**EMPTY, "action": "reject", "reason": "wrong part", "why": "a clip, not a cover"},
    )
    assert r.status_code == 200, r.text
    log = client.get("/api/v1/review/feedback").json()  # not taken for a job id
    (e,) = log["items"]
    assert (e["kind"], e["what"], e["why"], e["outcome"]) == ("reject", "wrong part", "a clip, not a cover", "rejected")
    assert log["counts"] == {"rejected": 1} and log["families"] == ["spacer"]
    assert client.get("/api/v1/review/feedback", params={"outcome": "fixed"}).json()["items"] == []
    assert client.get("/api/v1/review/feedback", params={"outcome": "nonsense"}).status_code == 422
