"""Product routes: playground templates, Describe it, saving a variant, Print it, print shops (mock providers, no
network). Bakes run the real sandbox on small templates."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from services.api import main as M
from services.api.tests.test_api import FakeService, _err, _wait_done, fake  # noqa: F401
from services.registry import describe
from services.registry.store import get_registry
from services.registry.tests.fixtures import add_part

API = "/api/v1"
CLIP = "a cable clip for a 6 mm cable, screws down with one M3 screw, 20 mm wide, 45 mm long"


@pytest.fixture
def client(fake: FakeService) -> TestClient:  # noqa: F811
    return TestClient(M.app)


# ------------------------------------------------------------------------------------------------- playground


def test_templates_list_detail_and_unknown(client: TestClient) -> None:
    r = client.get(f"{API}/templates")
    assert r.status_code == 200, r.text
    cards = r.json()
    assert len(cards) == 16 and {c["name"] for c in cards} >= {"cable_clip", "spacer", "knob", "drawer_runner"}
    clip = next(c for c in cards if c["name"] == "cable_clip")
    assert [p["title"] for p in clip["presets"]][:2] == ["M3 screw", "M4 screw"]
    assert clip["thumbnail_url"] == f"{API}/templates/cable_clip/thumbnail.png" and clip["coupon"] is True
    d = client.get(f"{API}/templates/spacer").json()
    assert "PARAMS" in d["code"] and d["measure_map"]["hole_1.diameter"] == "bore_d"
    e = _err(client.get(f"{API}/templates/cable_clp"), 404, "template_not_found")
    assert "cable_clip" in e["closest_matches"]


def test_template_bake_print_plan_clamp_and_gate(client: TestClient) -> None:
    r = client.get(f"{API}/templates/spacer/bake", params={"bore_d": 3.4, "height": 99, "format": "view"})
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["part_slug"] == "spacer" and b["clamped"] == {"height": 60.0} and b["artifacts"]["view"]
    plan = b["print_plan"]
    assert plan["layer_mm"] == 0.2 and plan["walls"] == 4 and plan["orientation"] and plan["estimates"][0]["grams"] > 0
    assert b["ship"]["status"] == "best_effort" and b["ship"]["needs_ack"] is True
    assert "bore_d=3.4" in b["downloads"]["stl"]
    again = client.get(f"{API}/templates/spacer/bake", params={"bore_d": 3.4, "height": 99, "format": "view"})
    assert again.json()["cache_hit"] is True
    _err(client.get(f"{API}/templates/spacer/bake", params={"bore": 3}), 422, "unknown_param")
    # printable files are not checked against a real part: acknowledge first
    _err(client.get(f"{API}/templates/spacer/bake", params={"format": "stl", "download": 1}), 409, "needs_ack")
    f = client.get(f"{API}/templates/spacer/bake", params={"format": "stl", "download": 1, "ack": 1})
    assert f.status_code == 200 and f.headers["content-disposition"].endswith('spacer.stl"')
    # the content-addressed link of a template bake goes through the same decision
    stl = client.get(f"{API}/templates/spacer/bake", params={"format": "stl"}).json()["artifacts"]["stl"]
    _err(client.get(stl), 409, "needs_ack")
    assert client.get(stl + "?ack=1").status_code == 200


def test_newer_template_bakes_at_its_knob_but_stays_a_template_at_the_export_gate(client: TestClient) -> None:
    detail = client.get(f"{API}/templates/drawer_runner").json()
    assert detail["family"] == "bracket" and {p["name"] for p in detail["params"]} >= {"length", "hole_count"}
    r = client.get(f"{API}/templates/drawer_runner/bake", params={"length": 150, "hole_count": 4, "format": "view"})
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["clamped"] == {} and b["artifacts"]["view"]
    assert b["ship"]["status"] == "best_effort" and b["ship"]["needs_ack"] is True
    assert "nothing compared it with a photo" in b["ship"]["reason"]
    _err(client.get(f"{API}/templates/drawer_runner/bake", params={"format": "stl", "download": 1}), 409, "needs_ack")


def test_template_thumbnail_and_coupon(client: TestClient) -> None:
    r = client.get(f"{API}/templates/spacer/thumbnail.png")
    assert r.status_code == 200 and r.content[:8] == b"\x89PNG\r\n\x1a\n"
    c = client.get(f"{API}/templates/spacer/coupon.stl", params={"bore_d": 3.4})
    assert c.status_code == 200 and len(c.content) > 1000
    _err(client.get(f"{API}/templates/battery_cover/coupon.stl"), 404, "no_coupon")


# ------------------------------------------------------------------------------------------------- describe it


def test_describe_matches_your_numbers(client: TestClient) -> None:
    r = client.post(f"{API}/describe", json={"text": CLIP})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["status"] == "done" and d["template"] == "cable_clip" and d["planner"]["mode"] == "mock"
    by = {v["param"]: v for v in d["values"]}
    assert by["cable_d"]["source"] == "user" and by["cable_d"]["quote"] == "for a 6 mm cable"
    assert by["hole_d"]["value"] == 3.4 and by["hole_count"]["value"] == 1
    assert by["wall"]["source"] == "default"
    assert d["checks"]["status"] == "matches" and d["checks"]["label"] == "Matches your numbers"
    assert {i["param"]: i["status"] for i in d["checks"]["items"]} == {
        "length": "met", "width": "met", "cable_d": "met", "hole_d": "met", "hole_count": "met",
    }  # fmt: skip
    assert "not verified" in d["label"] and d["print_plan"]["walls"] == 4 and d["coupon"] is True
    assert [e["stage"] for e in d["events"]] == ["describe_plan"]
    assert client.get(f"{API}/describe/{d['id']}").json()["checks"]["status"] == "matches"
    _err(client.get(f"{API}/describe/d_000000_00000000"), 404, "describe_not_found")


def test_describe_example_runs_the_pipeline_with_the_mock_planner(client: TestClient) -> None:
    r = client.get(f"{API}/describe/example")
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["example"] is True and d["id"] == "example" and d["planner"]["mode"] == "mock" and d["events"] == []
    assert d["text"] == describe.EXAMPLE_TEXT and d["status"] == "done" and d["template"] == "spacer"
    by = {v["param"]: v for v in d["values"]}
    assert by["height"]["source"] == "user" and by["height"]["value"] == 12
    assert by["outer_d"]["source"] == "user" and by["outer_d"]["value"] == 7
    assert by["bore_d"]["source"] == "user" and by["chamfer"]["source"] == "default"
    assert d["checks"]["status"] == "matches" and "Example result" in d["label"] and "not verified" in d["label"]
    assert client.get(f"{API}/describe/example").json() == d  # computed once
    assert "example" not in describe.recent(50)  # not stored as a description


def test_describe_asks_then_answers_without_a_second_call(client: TestClient) -> None:
    d = client.post(f"{API}/describe", json={"text": "a cable clip for a 6 mm cable, 20 mm wide"}).json()
    assert d["status"] == "needs_answers" and [q["param"] for q in d["questions"]] == ["length", "hole_d"]
    _err(client.post(f"{API}/describe/{d['id']}/answers", json={"answers": {"wall": 2}}), 409, "no_pending_question")
    a = client.post(f"{API}/describe/{d['id']}/answers", json={"answers": {"length": 50, "hole_d": None}}).json()
    assert a["status"] == "done" and len(a["events"]) == 1
    by = {v["param"]: v for v in a["values"]}
    assert by["length"]["source"] == "answer" and by["length"]["value"] == 50 and by["hole_d"]["source"] == "default"
    assert a["checks"]["status"] == "matches"
    _err(client.post(f"{API}/describe/{d['id']}/answers", json={"answers": {}}), 409, "no_pending_question")


def test_describe_clamped_and_no_fit(client: TestClient) -> None:
    d = client.post(f"{API}/describe", json={"text": "cable clip for a 30 mm cable, 40 mm long, one M4 screw"}).json()
    assert d["status"] == "done"
    item = next(i for i in d["checks"]["items"] if i["param"] == "cable_d")
    assert item["status"] == "clamped" and item["stated"] == 30 and item["set"] == 16 and "2–16 mm" in item["note"]
    assert d["checks"]["status"] == "partial"
    n = client.post(f"{API}/describe", json={"text": "a gear with 20 teeth, module 1"}).json()
    assert n["status"] == "no_fit" and n["template"] is None and n["bake"] is None
    assert {x["href"] for x in n["no_fit"]["next"]} == {"/fix", "/requests"}
    _err(client.post(f"{API}/describe", json={"text": "a"}), 422, "validation_error")


# ------------------------------------------------------------------------------------------------- variants


def test_save_variant_is_best_effort_and_admin_only(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    add_part("spacer", "spacer")
    r = client.post(f"{API}/parts/spacer/variants", json={"params": {"height": 14}})
    assert r.status_code == 200, r.text
    v = r.json()
    assert v["action"] == "renamed" and v["slug"] != "spacer" and v["slug"].startswith("spacer-")
    part = v["part"]
    assert part["status"] == "best_effort" and part["provenance"]["forked_from"] == "spacer"
    assert part["verification"]["verified"] is False and "not itself checked against a photo" in v["label"]
    assert part["verification"]["unchecked"][0]["param"] == "height"
    assert part["ship"]["status"] == "best_effort" and v["changed"] == [{"param": "height", "from": 10.0, "to": 14.0}]
    assert get_registry().get_part(v["slug"]) is not None
    _err(client.post(f"{API}/parts/spacer/variants", json={"params": {"height": 10}}), 409, "no_change")
    monkeypatch.setenv("PARTSMITH_ADMIN_TOKEN", "s3cret")
    _err(client.post(f"{API}/parts/spacer/variants", json={"params": {"height": 12}}), 401, "admin_required")
    ok = client.post(
        f"{API}/parts/spacer/variants", json={"params": {"height": 12}}, headers={"Authorization": "Bearer s3cret"}
    )
    assert ok.status_code == 200


# ------------------------------------------------------------------------------------------------- print it


def test_print_plans_and_shops(client: TestClient, fake: FakeService) -> None:  # noqa: F811
    add_part("spacer", "spacer")
    p = client.get(f"{API}/parts/spacer/print-plan", params={"height": 12}).json()
    assert p["print_plan"]["bbox_mm"][2] == pytest.approx(12.0, abs=0.01) and p["ship"]["status"] == "verified"
    job = fake.start_demo_job("spacer-easy-01")
    _wait_done(fake, job.id)
    j = client.get(f"{API}/jobs/{job.id}/print-plan").json()
    assert j["print_plan"]["supports_needed"] in (True, False) and j["ship"]["status"] == "verified"
    s: dict[str, Any] = client.post(f"{API}/print-shops", json={"city": "Pune", "title": "Cable clip"}).json()
    assert s["mode"] == "mock" and s["city"] == "Pune" and s["cached"] is False
    assert client.post(f"{API}/print-shops", json={"city": "pune", "title": "cable clip"}).json()["cached"] is True
    _err(client.post(f"{API}/print-shops", json={"city": "", "title": "x"}), 422, "validation_error")
