"""Round-2 routes: admin token, reference role, bundle/embed/presets/card, requests, lessons, usage, open weights,
fit-check live update, export gate, verify against a job, batches."""

from __future__ import annotations

import io
import json
import threading
import time
import zipfile
from typing import Any

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from services.api import main as M
from services.api import usage
from services.api.tests.test_api import FakeService, _err, _jpeg, _wait_done
from services.registry.store import ROLE_REFERENCE_TAG, get_registry
from services.registry.tests.fixtures import add_part, make_part

ADMIN = {"Authorization": "Bearer s3cret"}


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch) -> Any:
    from services.api import deps

    f = FakeService()
    monkeypatch.setattr(deps, "service", lambda: f)
    monkeypatch.setattr(M, "HEARTBEAT_S", 0.05)
    monkeypatch.setattr(M, "FOLLOW_POLL_S", 0.02)
    usage.reset()
    yield f
    f.mgr.shutdown()


@pytest.fixture
def client(fake: FakeService) -> TestClient:
    return TestClient(M.app)


def _demo(client: TestClient, fake: FakeService) -> str:
    jid = str(client.post("/api/v1/jobs/demo", json={"sample": "spacer-easy-01"}).json()["id"])
    _wait_done(fake, jid)
    return jid


def test_admin_token_guards_writes(client: TestClient, fake: FakeService, monkeypatch: pytest.MonkeyPatch) -> None:
    assert client.get("/api/v1/status").json()["admin"] == "open (dev)"
    monkeypatch.setenv("PARTSMITH_ADMIN_TOKEN", "s3cret")
    assert client.get("/api/v1/status").json()["admin"] == "token"
    jid = _demo(client, fake)
    _err(client.post(f"/api/v1/jobs/{jid}/publish", json={}), 401, "admin_required")
    _err(client.post(f"/api/v1/jobs/{jid}/publish", json={}, headers={"Authorization": "Bearer nope"}), 401,
         "admin_required")  # fmt: skip
    assert client.post(f"/api/v1/jobs/{jid}/publish", json={"slug": "my-spacer"}, headers=ADMIN).status_code == 200
    _err(client.post("/api/v1/steer", json={"brief": "desk cable kit", "count": 1}), 401, "admin_required")
    _err(client.post("/api/v1/steer/s_1/review", json={"slug": "x", "action": "approve"}), 401, "admin_required")
    lid = get_registry().add_lesson("global", "holes need +0.2 mm on PLA", {"job_id": jid})
    _err(client.post(f"/api/v1/lessons/{lid}/promote"), 401, "admin_required")
    assert client.get("/api/v1/parts").status_code == 200 and client.get("/api/v1/lessons").status_code == 200


def test_reference_objects_are_hidden_by_default(client: TestClient) -> None:
    add_part("spacer", "m3-spacer")
    ref = make_part("battery_cover", "reference-id1-card")
    ref.tags.append(ROLE_REFERENCE_TAG)
    get_registry().upsert_part(ref)
    assert [i["slug"] for i in client.get("/api/v1/parts").json()["items"]] == ["m3-spacer"]
    assert [i["slug"] for i in client.get("/api/v1/parts?role=reference").json()["items"]] == ["reference-id1-card"]
    assert client.get("/api/v1/parts?role=all").json()["total"] == 2
    assert {f["family"]: f["count"] for f in client.get("/api/v1/families").json()}["cover"] == 0
    assert client.get("/api/v1/parts/reference-id1-card").status_code == 200  # still reachable directly


def test_bundle_embed_presets_card(client: TestClient) -> None:
    add_part("cable_clip", "desk-cable-clip")
    add_part("hook", "rough-hook", verified=False, max_error_mm=0.8)
    r = client.get("/api/v1/parts/desk-cable-clip/bundle.zip?length=50&preset=pla-fdm-0.4")
    assert r.status_code == 200 and r.headers["content-type"] == "application/zip"
    z = zipfile.ZipFile(io.BytesIO(r.content))
    assert "desk-cable-clip/README.md" in z.namelist()
    py = z.read("desk-cable-clip/part.py").decode()
    assert '"length": (50.0' in py and '"cable_d": (6.2' in py
    e = _err(client.get("/api/v1/parts/rough-hook/bundle.zip"), 409, "needs_ack")
    assert "ack=1" in e["message"] and "0.8" in e["message"]
    assert client.get("/api/v1/parts/rough-hook/bundle.zip?ack=1").status_code == 200
    page = client.get("/embed/desk-cable-clip?length=50")
    assert page.status_code == 200 and "frame-ancestors" in page.headers["content-security-policy"]
    assert "/api/v1/parts/desk-cable-clip/bake?length=50.0&amp;format=view&amp;download=1" in page.text
    pr = client.get("/api/v1/parts/desk-cable-clip/presets").json()
    assert pr["fit_knobs"] == ["cable_d", "hole_d"] and len(pr["presets"]) == 7
    assert len(client.get("/api/v1/presets").json()) == 7
    b = client.get("/api/v1/parts/desk-cable-clip/bake?format=view&preset=abs-fdm-0.4").json()
    assert b["preset"]["id"] == "abs-fdm-0.4" and b["params"]["hole_d"] == pytest.approx(3.8)
    e = _err(client.get("/api/v1/parts/desk-cable-clip/bake?preset=pla-fdm-04"), 422, "unknown_preset")
    assert "pla-fdm-0.4" in e["closest_matches"]
    card = client.get("/api/v1/parts/desk-cable-clip/card.png")
    assert card.status_code == 200 and Image.open(io.BytesIO(card.content)).size == (1200, 630)


def test_job_presets_use_the_part_rule(client: TestClient, fake: FakeService) -> None:
    """An unpublished job gets the same presets and the same preset → delta_mm rule as a published part."""
    from services.registry import presets

    jid = _demo(client, fake)
    pr = client.get(f"/api/v1/jobs/{jid}/presets").json()
    specs, values = fake.job_params(jid)
    assert pr["job_id"] == jid and pr["fit_knobs"] == [p.name for p in presets.fit_knobs(specs)] == ["bore_d"]
    assert pr["presets"] == presets.for_part(specs, values) and len(pr["presets"]) == 7
    b = client.get(f"/api/v1/jobs/{jid}/bake?format=view&preset=abs-fdm-0.4").json()
    assert b["preset"]["id"] == "abs-fdm-0.4" and b["preset"]["delta_mm"] == 0.30
    (ch,) = b["preset"]["changes"]
    assert ch["param"] == "bore_d" and ch["to"] == pytest.approx(values["bore_d"] + 0.30)
    assert b["params"]["bore_d"] == pytest.approx(ch["to"])
    assert b["params"]["height"] == pytest.approx(values["height"])  # outer sizes never change
    k = client.get(f"/api/v1/jobs/{jid}/bake?format=view&height=12&preset=pla-fdm-0.4").json()
    assert k["params"]["height"] == 12.0 and k["params"]["bore_d"] == pytest.approx(values["bore_d"] + 0.20)
    assert "preset" not in client.get(f"/api/v1/jobs/{jid}/bake?format=view").json()
    e = _err(client.get(f"/api/v1/jobs/{jid}/bake?preset=pla-fdm-04"), 422, "unknown_preset")
    assert "pla-fdm-0.4" in e["closest_matches"]
    _err(client.get("/api/v1/jobs/j_nope/presets"), 404, "job_not_found")


def test_part_detail_ship_and_gated_bake_download(client: TestClient) -> None:
    """Part detail carries the export gate's decision; `/bake?download=1` enforces it like bundle.zip."""
    add_part("cable_clip", "desk-cable-clip")
    add_part("hook", "rough-hook", verified=False, max_error_mm=0.8)
    failed = make_part("spacer", "broken-spacer", verified=False)
    assert failed.verification is not None
    failed.verification = failed.verification.model_copy(update={"status": "failed", "reasons": ["no solid"]})
    get_registry().upsert_part(failed)

    ok = client.get("/api/v1/parts/desk-cable-clip").json()["ship"]
    assert ok["status"] == "verified" and ok["needs_ack"] is False and ok["reason"]
    rough = client.get("/api/v1/parts/rough-hook").json()["ship"]
    assert rough["status"] == "best_effort" and rough["needs_ack"] is True and "0.8" in rough["reason"]
    assert client.get("/api/v1/parts/broken-spacer").json()["ship"]["status"] == "blocked"

    # verified: unchanged, downloads directly
    r = client.get("/api/v1/parts/desk-cable-clip/bake?format=stl&download=1")
    assert r.status_code == 200 and len(r.content) > 84
    # best effort: the bake download can no longer bypass the bundle.zip gate
    e = _err(client.get("/api/v1/parts/rough-hook/bake?format=stl&download=1"), 409, "needs_ack")
    assert "ack=1" in e["message"] and "0.8" in e["message"]
    _err(client.get("/api/v1/parts/rough-hook/bake?format=step&download=1&preset=pla-fdm-0.4"), 409, "needs_ack")
    assert client.get("/api/v1/parts/rough-hook/bake?format=stl&download=1&ack=1").status_code == 200
    assert client.get("/api/v1/parts/rough-hook/bake?format=view&download=1").status_code == 200  # preview stays open
    assert client.get("/api/v1/parts/rough-hook/bake?format=glb&download=1").status_code == 200  # AR preview too
    assert client.get("/api/v1/parts/rough-hook/bake?format=stl").status_code == 200  # a bake result is not an export
    # failed: refused even with ack
    _err(client.get("/api/v1/parts/broken-spacer/bake?format=stl&download=1&ack=1"), 409, "not_shippable")
    _err(client.get("/api/v1/parts/broken-spacer/bundle.zip?ack=1"), 409, "not_shippable")


def test_requests_votes_photo_status(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    files = {"photo": ("p.jpg", _jpeg(), "image/jpeg")}
    n = client.post("/api/v1/needs", data={"query": "mixer jar coupler 22 mm"}, files=files).json()
    assert n["votes"] == 1 and n["photo_url"].startswith("/api/v1/blobs/")
    assert client.post(f"/api/v1/needs/{n['id']}/vote").json()["counted"] is False  # the asker already voted
    v = client.post(f"/api/v1/needs/{n['id']}/vote", headers={"User-Agent": "phone"}).json()
    assert v["votes"] == 2 and v["counted"] is True
    _err(client.post("/api/v1/needs/n_nope/vote"), 404, "need_not_found")
    monkeypatch.setenv("PARTSMITH_ADMIN_TOKEN", "s3cret")
    _err(client.patch(f"/api/v1/needs/{n['id']}", json={"status": "in_progress"}), 401, "admin_required")
    s = client.patch(f"/api/v1/needs/{n['id']}", json={"status": "in_progress"}, headers=ADMIN).json()
    assert s["status"] == "in_progress"
    assert client.get("/api/v1/needs?status=open").json() == []
    assert client.get("/api/v1/needs?status=in_progress").json()[0]["id"] == n["id"]


def test_lessons_list_promote_reject(client: TestClient) -> None:
    reg = get_registry()
    a = reg.add_lesson("global", "PLA holes print 0.2 mm small", {"job_ids": ["j_1"], "slug": "m3-spacer"})
    b = reg.add_lesson("hook", "hooks need 4 mm arms", {})
    got = client.get("/api/v1/lessons?status=candidate").json()
    assert {x["id"] for x in got} == {a, b}
    links = next(x for x in got if x["id"] == a)["links"]
    assert {(link["kind"], link["id"]) for link in links} == {("job", "j_1"), ("part", "m3-spacer")}
    p = client.post(f"/api/v1/lessons/{a}/promote", json={"by": "prashant"}).json()
    assert p["status"] == "promoted" and p["promoted_by"] == "prashant"
    assert client.post(f"/api/v1/lessons/{b}/reject").json()["status"] == "rejected"
    assert [x["id"] for x in client.get("/api/v1/lessons?status=promoted").json()] == [a]
    _err(client.post("/api/v1/lessons/l_nope/promote"), 404, "lesson_not_found")


def test_usage_counter_in_stats(client: TestClient) -> None:
    add_part("spacer", "m3-spacer")
    for ua in ("a", "a", "b"):
        client.get("/api/v1/parts", headers={"User-Agent": ua})
    client.post("/mcp", json={}, headers={"User-Agent": "agent"})  # 503 without the lifespan, still counted
    s = client.get("/api/v1/stats").json()
    assert s["calls_total"] >= 4 and s["mcp_calls"] == 1 and s["distinct_clients"] >= 3
    assert s["last_7d"]["calls"] == s["calls_total"]
    assert {"route": "/api/v1/parts", "calls": 3} in s["usage"]["top_routes"]
    rows = get_registry().usage()
    assert all(len(r[2]) == 16 and "testclient" not in r[2] for r in rows)  # hashed, never raw


def test_open_weights_evidence(client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    from services.agent import providers
    from services.api import round2

    monkeypatch.setattr(round2, "OPEN_WEIGHTS_REPORT", tmp_path / "missing.json")
    monkeypatch.delattr(providers, "open_weights_summary", raising=False)
    r = client.get("/api/v1/status/open-weights").json()
    assert r["status"] == "pending" and r["stages"] and len(r["notes"]) == 2
    monkeypatch.setattr(providers, "open_weights_summary", lambda: {"stages": ["build"]}, raising=False)
    rep = tmp_path / "ow.json"
    rep.write_text(json.dumps({"runs": 3}))
    monkeypatch.setattr(round2, "OPEN_WEIGHTS_REPORT", rep)
    r = client.get("/api/v1/status/open-weights").json()
    assert r["status"] == "ok" and r["summary"] == {"stages": ["build"]} and r["report"] == {"runs": 3}


def test_fit_check_updates_a_following_page(client: TestClient, fake: FakeService) -> None:
    jid = _demo(client, fake)
    seen: list[dict[str, Any]] = []

    def follow() -> None:
        with TestClient(M.app).stream("GET", f"/api/v1/jobs/{jid}/events?follow=1") as r:
            for line in r.iter_lines():
                if line.startswith("data: "):
                    ev = json.loads(line[6:])
                    seen.append(ev)
                    if ev.get("name") == "fit_check_passed":
                        return

    t = threading.Thread(target=follow, daemon=True)
    t.start()
    time.sleep(0.3)  # the laptop is subscribed and the job is already done
    assert any(e["t"] == "done" for e in seen) and t.is_alive()
    files = {"photo": ("p.jpg", _jpeg(), "image/jpeg")}
    assert client.post(f"/api/v1/jobs/{jid}/fit-check", files=files, data={"mat_id": "screen-m"}).status_code == 200
    t.join(5)
    assert not t.is_alive()
    names = [e.get("name") for e in seen if e["t"] == "metric"]
    assert "fit_check_passed" in names and seen[-1]["value"] == 1.0


def test_export_gate_on_job_publish_and_download(client: TestClient, fake: FakeService) -> None:
    jid = _demo(client, fake)
    job = fake.mgr.get(jid)
    assert job is not None
    job.write_json("verification.json", make_part("spacer", verified=False, max_error_mm=0.8).verification)
    e = _err(client.get(f"/api/v1/jobs/{jid}/bake?format=stl&download=1"), 409, "needs_ack")
    assert "best effort" in e["message"]
    assert client.get(f"/api/v1/jobs/{jid}/bake?format=stl&download=1&ack=1").status_code == 200
    assert client.get(f"/api/v1/jobs/{jid}/bake?format=view&download=1").status_code == 200  # previews are open
    _err(client.post(f"/api/v1/jobs/{jid}/publish", json={"slug": "rough"}), 409, "needs_ack")
    p = client.post(f"/api/v1/jobs/{jid}/publish", json={"slug": "rough", "ack": True}).json()
    assert p["ship"]["status"] == "best_effort"
    job.write_json("verification.json", {"verified": False, "status": "failed", "reasons": ["no solid"]})
    _err(client.get(f"/api/v1/jobs/{jid}/bake?format=stl&download=1&ack=1"), 409, "not_shippable")


def test_verify_against_a_job(client: TestClient, fake: FakeService, monkeypatch: pytest.MonkeyPatch) -> None:
    from services.agent.templates import get_template
    from services.geom_worker.sandbox import run_program
    from services.verifier.synthetic import synthetic_top_measurement

    add_part("spacer", "m3-spacer")
    res = run_program(get_template("spacer").code, {}, outputs=())
    meas, _ = synthetic_top_measurement(res)
    res.cleanup()
    jid = _demo(client, fake)
    orig = fake.job_detail
    monkeypatch.setattr(
        fake, "job_detail", lambda j: {**orig(j), "measurements": {"top": meas.model_dump(mode="json")}}
    )
    v = client.post("/api/v1/verify", json={"part": "m3-spacer", "job_id": jid}).json()
    assert v["views"][0]["hausdorff_mm"] < 0.5 and isinstance(v["functional"], dict)
    _err(client.post("/api/v1/verify", json={"part": "m3-spacer"}), 422, "validation_error")


def test_batches_routes(client: TestClient, fake: FakeService, monkeypatch: pytest.MonkeyPatch) -> None:
    jid = _demo(client, fake)
    monkeypatch.setenv("PARTSMITH_ADMIN_TOKEN", "s3cret")
    body = {"name": "Saturday walk-ins", "customers": [{"name": "Asha", "contact": "98", "jobs": [jid]}]}
    _err(client.post("/api/v1/batches", json=body), 401, "admin_required")
    b = client.post("/api/v1/batches", json=body, headers=ADMIN).json()
    assert b["rows"][0]["job_id"] == jid and b["rows"][0]["verified"] is True
    b2 = client.post(f"/api/v1/batches/{b['id']}/jobs", json={"customer": "Ravi", "job_id": jid}, headers=ADMIN).json()
    assert [c["name"] for c in b2["customers"]] == ["Asha", "Ravi"]
    pdf = client.get(f"/api/v1/batches/{b['id']}/sheet.pdf", headers=ADMIN)
    assert pdf.status_code == 200 and pdf.content[:5] == b"%PDF-" and b"Asha" in pdf.content
    assert client.get("/api/v1/batches", headers=ADMIN).json()[0]["id"] == b["id"]
    _err(client.get("/api/v1/batches/b_nope", headers=ADMIN), 404, "batch_not_found")


def test_bench_surfaces_evidence_reports(client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    (tmp_path / "bypass.json").write_text(json.dumps({"suite": "lying-brain", "attempts": 12, "blocked": 12}))
    (tmp_path / "program_vs_mesh.json").write_text("{broken")
    monkeypatch.setattr(M, "BENCH_REPORT", tmp_path / "report.json")
    ev = client.get("/api/v1/bench").json()["evidence"]
    assert ev["bypass"]["blocked"] == 12 and ev["program_vs_mesh"] is None and ev["impact"] is None
    (tmp_path / "report.json").write_text(json.dumps({"tables": {}, "runs": [], "failures": []}))
    assert client.get("/api/v1/bench").json()["evidence"]["bypass"]["attempts"] == 12


def test_open_weights_uses_recorded_calls(client: TestClient, fake: FakeService) -> None:
    jid = _demo(client, fake)
    job = fake.mgr.get(jid)
    assert job is not None
    job.emit({"t": "model_call", "job": jid, "provider": "baseten", "model": "muse-spark-open", "stage": "build",
              "mode": "live", "tokens_in": 10, "tokens_out": 5, "ms": 100, "usd": 0.001})  # fmt: skip
    r = client.get("/api/v1/status/open-weights").json()
    assert r["summary"] is not None and "build" in json.dumps(r["summary"])
