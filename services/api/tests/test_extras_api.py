"""Search coverage on GET /parts, the search log and GET /demand, part data as JSON (verification.json, params.json)
and download file names. TEST DATA parts; no network, no keys."""

from __future__ import annotations

import json
from typing import Any

import pytest
from fastapi.testclient import TestClient

from services.api import main as M
from services.api.tests.test_api import FakeService, _err, _wait_done
from services.registry import demand
from services.registry.tests.fixtures import add_part

API = "/api/v1"


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch) -> Any:
    from services.api import deps

    f = FakeService()
    monkeypatch.setattr(deps, "service", lambda: f)
    yield f
    f.mgr.shutdown()


@pytest.fixture
def client(fake: FakeService) -> TestClient:
    return TestClient(M.app)


def _log() -> list[dict[str, Any]]:
    p = demand.log_path()
    return [json.loads(x) for x in p.read_text().splitlines()] if p.exists() else []


def test_search_reports_coverage_match_and_hint(client: TestClient) -> None:
    add_part("cable_clip", "desk-cable-clip")
    add_part("knob", "drawer-knob")
    good = client.get(f"{API}/parts", params={"q": "cable clip"}).json()
    assert good["match"] == "good" and good["coverage"] == 1.0 and good["hint"] is None
    assert good["items"][0]["slug"] == "desk-cable-clip" and good["items"][0]["coverage"] == 1.0
    partial = client.get(f"{API}/parts", params={"q": "cable clip 400 mm"}).json()
    assert partial["match"] == "partial" and partial["coverage"] == round(2 / 3, 3) and "/describe" in partial["hint"]
    none = client.get(f"{API}/parts", params={"q": "zeppelin gondola"}).json()
    assert none["match"] == "none" and none["coverage"] == 0.0 and none["total"] == 0
    assert none["hint"].startswith("No close match") and "/fix" in none["hint"]
    browse = client.get(f"{API}/parts").json()
    assert browse["match"] == "all" and browse["coverage"] is None and browse["hint"] is None
    assert "coverage" not in browse["items"][0]
    rows = _log()
    assert [r["q"] for r in rows] == ["cable clip", "cable clip 400 mm", "zeppelin gondola"]  # empty query not logged
    assert all(set(r) == {"q", "total", "best_coverage", "at"} for r in rows)
    client.get(f"{API}/parts", params={"q": "cable clip", "cursor": "24"})  # "Load more": same search, not re-logged
    assert len(_log()) == 3


def test_demand_lists_open_needs_and_missed_searches(client: TestClient) -> None:
    add_part("cable_clip", "desk-cable-clip")
    for _ in range(2):
        client.get(f"{API}/parts", params={"q": "Zeppelin gondola"})
    client.get(f"{API}/parts", params={"q": "cable clip"})
    client.post(f"{API}/needs", json={"query": "dishwasher rack wheel 22 mm"})
    d = client.get(f"{API}/demand").json()
    assert set(d) == {"needs", "missed_searches", "miss_below"} and d["miss_below"] == 0.5
    assert d["needs"][0]["query"] == "dishwasher rack wheel 22 mm" and d["needs"][0]["votes"] == 1
    assert d["needs"][0]["status"] == "open" and "photo_url" in d["needs"][0]
    assert len(d["missed_searches"]) == 1
    m = d["missed_searches"][0]
    assert m["q"] == "Zeppelin gondola" and m["count"] == 2 and m["best_coverage"] == 0.0 and m["last_at"]
    assert client.get(f"{API}/demand", params={"missed": 0, "needs": 0}).json() == {
        "needs": [], "missed_searches": [], "miss_below": 0.5,
    }  # fmt: skip
    _err(client.get(f"{API}/demand", params={"missed": 999}), 422, "validation_error")


def test_verification_json_is_the_stored_record(client: TestClient) -> None:
    part = add_part("cable_clip", "desk-cable-clip", max_error_mm=0.21)
    r = client.get(f"{API}/parts/desk-cable-clip/verification.json")
    assert r.status_code == 200 and "partsmith-desk-cable-clip-verification.json" in r.headers["content-disposition"]
    v = r.json()
    assert v["slug"] == "desk-cable-clip" and v["verified"] is True and v["status"] == "verified"
    assert v["max_error_mm"] == 0.21 and v["limit_mm"] == 0.5 and v["iou_limit"] == 0.97
    assert v["views"][0]["view"] == "top" and v["views"][0]["hausdorff_mm"] == 0.21
    assert v["code_sha"] == part.code_sha and v["published_at"].endswith("+00:00")
    assert v["verification"]["max_error_mm"] == 0.21 and v["origin"] == "synthetic"
    _err(client.get(f"{API}/parts/nope/verification.json"), 404, "part_not_found")


def test_params_json_is_a_typed_schema(client: TestClient) -> None:
    part = add_part("cable_clip", "desk-cable-clip")
    s = client.get(f"{API}/parts/desk-cable-clip/params.json").json()
    assert s["$schema"].endswith("2020-12/schema") and s["type"] == "object" and s["additionalProperties"] is False
    assert set(s["properties"]) == {p.name for p in part.params}
    for p in part.params:
        prop = s["properties"][p.name]
        assert prop["minimum"] == p.min and prop["maximum"] == p.max and prop["default"] == part.defaults[p.name]
        assert prop["type"] == ("integer" if p.topology else "number") and prop["unit"] == (p.unit or None)
        assert prop["description"]
    assert s["bake"] == f"{API}/parts/desk-cable-clip/bake"
    _err(client.get(f"{API}/parts/nope/params.json"), 404, "part_not_found")


def test_downloads_are_named_after_the_part_and_its_changed_knobs(client: TestClient) -> None:
    add_part("cable_clip", "desk-cable-clip")
    r = client.get(f"{API}/parts/desk-cable-clip/bake", params={"format": "stl", "download": 1})
    assert r.status_code == 200 and 'attachment; filename="partsmith-desk-cable-clip.stl"' in r.headers[
        "content-disposition"]  # fmt: skip
    r = client.get(f"{API}/parts/desk-cable-clip/bake", params={"format": "stl", "download": 1, "cable_d": 8})
    assert 'filename="partsmith-desk-cable-clip-cable8.stl"' in r.headers["content-disposition"]
    # the content-addressed bake link carries the same name
    b = client.get(f"{API}/parts/desk-cable-clip/bake", params={"format": "stl", "cable_d": 8}).json()
    f = client.get(b["artifacts"]["stl"])
    assert f.status_code == 200 and 'filename="partsmith-desk-cable-clip-cable8.stl"' in f.headers[
        "content-disposition"]  # fmt: skip
    t = client.get(f"{API}/templates/spacer/bake", params={"format": "stl", "download": 1, "ack": 1, "height": 12})
    assert 'filename="partsmith-spacer-height12.stl"' in t.headers["content-disposition"]


def test_job_download_is_named_after_the_job(client: TestClient, fake: FakeService) -> None:
    jid = str(client.post(f"{API}/jobs/demo", json={"sample": "spacer-easy-01"}).json()["id"])
    _wait_done(fake, jid)
    r = client.get(f"{API}/jobs/{jid}/bake", params={"format": "stl", "download": 1, "ack": 1, "height": 12})
    assert r.status_code == 200
    cd = r.headers["content-disposition"]
    assert "partsmith-job-" in cd and "-height12.stl" in cd


def test_fix_job_takes_sizes_the_photo_cannot_show(client: TestClient, fake: FakeService) -> None:
    from services.api.tests.test_api import _jpeg

    dims = [{"name": "bore_d", "value_mm": 8.0}, {"name": "socket depth", "value_mm": 4.5}]
    r = client.post(
        f"{API}/jobs/fix",
        files={"top": ("t.jpg", _jpeg(), "image/jpeg")},
        data={"mat_kind": "screen", "hidden_dims": json.dumps(dims)},
    )
    assert r.status_code == 200, r.text
    ji = fake.inputs[r.json()["id"]]
    assert [(d.name, d.value_mm) for d in ji.hidden_dims] == [("bore_d", 8.0), ("socket depth", 4.5)]
    top = {"top": ("t.jpg", _jpeg(), "image/jpeg")}
    for bad in ("not json", '{"name": "x"}', '[{"name": "bore_d", "value_mm": -1}]', json.dumps(dims * 3)):
        e = _err(client.post(f"{API}/jobs/fix", files=top, data={"hidden_dims": bad}), 422, "invalid_hidden_dims")
        assert "hidden_dims" in e["message"]
    ok = client.post(f"{API}/jobs/fix", files=top, data={"hidden_dims": ""})
    assert ok.status_code == 200 and fake.inputs[ok.json()["id"]].hidden_dims == []
