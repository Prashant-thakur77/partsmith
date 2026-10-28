"""Round-3 web routes: coupon fit reports + learned clearance in preset bakes, and the per-job impact panel."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient
from partsmith_schemas import ArtifactEvent

from services.api import main as M
from services.api import usage
from services.api.tests.test_api import FakeService, _err, _wait_done
from services.registry.tests.fixtures import add_part

DEVICE = "web-device-0001"


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch) -> Any:
    from services.api import deps

    f = FakeService()
    monkeypatch.setattr(deps, "service", lambda: f)
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


def _coupon(client: TestClient, fit: str, amount: str | None = None, **extra: Any) -> Any:
    body = {"preset": "pla-fdm-0.4", "session": DEVICE, "features": [{"feature": "bore", "fit": fit, "amount": amount}]}
    return client.post("/api/v1/fit-reports/coupon", json={**body, **extra})


def test_coupon_report_learns_and_labels(client: TestClient) -> None:
    before = client.get(f"/api/v1/fit-reports/coupon/pla-fdm-0.4?session={DEVICE}").json()
    assert before["source"] == "preset" and before["clearance_mm"] == 0.20 and before["range_mm"] == [0.0, 0.45]
    r = _coupon(client, "tight", "very")
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["accepted"] == 1 and out["id"].startswith("cr_")
    lc = out["learned"]
    assert lc["source"] == "learned" and lc["clearance_mm"] == pytest.approx(0.30)
    assert lc["label"] == "learned from 1 coupon report" and lc["reports"] == 1
    every = client.get(f"/api/v1/fit-reports/coupon?session={DEVICE}").json()
    assert len(every) == 7 and {x["preset"]: x["source"] for x in every}["pla-fdm-0.4"] == "learned"
    assert all(x["source"] == "preset" for x in client.get("/api/v1/fit-reports/coupon").json())


def test_coupon_report_validation(client: TestClient, fake: FakeService) -> None:
    e = _err(client.post("/api/v1/fit-reports/coupon", json={"preset": "pla-fdm-04", "session": DEVICE,
                                                            "features": [{"feature": "a", "fit": "ok"}]}),
             422, "unknown_preset")  # fmt: skip
    assert "pla-fdm-0.4" in e["closest_matches"]
    _err(client.post("/api/v1/fit-reports/coupon", json={"preset": "pla-fdm-0.4", "session": "x",
                                                        "features": [{"feature": "a", "fit": "ok"}]}),
         422, "validation_error")  # fmt: skip
    _err(_coupon(client, "snug"), 422, "validation_error")
    _err(_coupon(client, "tight", "slightly"), 422, "validation_error")
    _err(client.post("/api/v1/fit-reports/coupon", json={"preset": "pla-fdm-0.4", "session": DEVICE, "features": []}),
         422, "validation_error")  # fmt: skip
    _err(_coupon(client, "ok", slug="no-such-part"), 404, "part_not_found")
    _err(_coupon(client, "ok", job_id="j_nope"), 404, "job_not_found")
    _err(client.get("/api/v1/fit-reports/coupon/nylon"), 422, "unknown_preset")
    _err(client.get("/api/v1/fit-reports/coupon/pla-fdm-0.4?session=bad id"), 422, "validation_error")


def test_part_bake_uses_the_learned_clearance_only_on_fit_knobs(client: TestClient) -> None:
    add_part("spacer", "test-spacer")
    plain = client.get(f"/api/v1/parts/test-spacer/bake?format=view&preset=pla-fdm-0.4&fit_session={DEVICE}").json()
    assert plain["preset"]["source"] == "preset" and plain["preset"]["delta_mm"] == 0.20
    assert plain["params"]["bore_d"] == pytest.approx(3.6)
    _coupon(client, "tight", "very")
    b = client.get(
        f"/api/v1/parts/test-spacer/bake?format=view&height=12&preset=pla-fdm-0.4&fit_session={DEVICE}"
    ).json()
    p = b["preset"]
    assert p["source"] == "learned" and p["delta_mm"] == pytest.approx(0.30) and p["preset_delta_mm"] == 0.20
    assert p["label"] == "learned from 1 coupon report"
    assert b["params"]["bore_d"] == pytest.approx(3.7)
    assert b["params"]["height"] == 12.0 and b["params"]["outer_d"] == 8.0  # measured sizes never change
    # another device still gets the documented preset; no session keeps the old behaviour
    other = client.get(
        "/api/v1/parts/test-spacer/bake?format=view&preset=pla-fdm-0.4&fit_session=other-device-1"
    ).json()
    assert other["params"]["bore_d"] == pytest.approx(3.6)
    assert (
        client.get("/api/v1/parts/test-spacer/bake?format=view&preset=pla-fdm-0.4").json()["preset"]["source"]
        == "preset"
    )
    _err(client.get("/api/v1/parts/test-spacer/bake?format=view&preset=pla-fdm-0.4&fit_session=no"), 422,
         "validation_error")  # fmt: skip


def test_job_bake_uses_the_learned_clearance(client: TestClient, fake: FakeService) -> None:
    jid = _demo(client, fake)
    _, values = fake.job_params(jid)
    _coupon(client, "loose", job_id=jid)
    b = client.get(f"/api/v1/jobs/{jid}/bake?format=view&preset=pla-fdm-0.4&fit_session={DEVICE}").json()
    assert b["preset"]["source"] == "learned" and b["preset"]["delta_mm"] == pytest.approx(0.15)
    assert b["params"]["bore_d"] == pytest.approx(values["bore_d"] + 0.15)
    assert b["params"]["height"] == pytest.approx(values["height"])


def test_job_impact(client: TestClient, fake: FakeService) -> None:
    jid = _demo(client, fake)
    job = fake.mgr.get(jid)
    assert job is not None
    empty = client.get(f"/api/v1/jobs/{jid}/impact").json()
    assert empty["minutes_to_file"] is None and empty["label"] == "estimate"
    # the fake job's verification stub carries a 1000 mm³ volume → PLA grams from the mesh volume
    assert empty["filament"]["source"].startswith("verified mesh") and empty["filament"]["grams"] == pytest.approx(1.24)
    job.write_json("facts.json", {"mass_g_pla": 3.1, "volume_mm3": 2500.0, "print_minutes_est": 9.0})
    job.emit(ArtifactEvent(job=jid, kind="stl", url="/api/v1/blobs/x.stl", sha="0" * 64, label="STL export"))
    out = client.get(f"/api/v1/jobs/{jid}/impact").json()
    assert out["minutes_to_file"]["kind"] == "stl" and out["minutes_to_file"]["minutes"] >= 0
    assert out["filament"]["grams"] == 3.1 and out["print_minutes_est"] == 9.0
    assert {c["currency"] for c in out["cost"]} == {"INR", "USD"}
    _err(client.get("/api/v1/jobs/j_nope/impact"), 404, "job_not_found")
