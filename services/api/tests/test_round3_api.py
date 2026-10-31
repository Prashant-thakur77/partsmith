"""Round-3 routes: buy-or-print card for jobs and published parts (mock providers, fixtures, no network)."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from partsmith_schemas import PartFacts

from services.agent.providers import mocks
from services.api import errors, round3
from services.api.tests.test_api import FakeService, _err, _wait_done
from services.registry.store import get_registry
from services.registry.tests.fixtures import make_part

FACTS = PartFacts(bbox_mm=(45.0, 30.0, 1.5), volume_mm3=1921.4, mass_g_pla=2.38, mass_g_petg=2.44,
                  print_minutes_est=5.6, supports_needed=False, orientation="-Z: as modelled")  # fmt: skip
SOURCES = ["https://shop.example.com/remote-cover", "https://fab.example.in/"]
ANSWER = {
    "offers": [
        {"seller": "Shop", "price": 349, "currency": "INR", "url": SOURCES[0], "quote": "Price: ₹349"},
        {"seller": "Uncited", "price": 199, "currency": "INR", "url": "https://elsewhere.example.org", "quote": "₹199"},
    ],
    "places": [{"name": "Fab Lab", "kind": "maker_space", "url": SOURCES[1], "quote": "3D printing service"}],
}


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch) -> Any:
    from services.api import deps

    f = FakeService()
    monkeypatch.setattr(deps, "service", lambda: f)
    yield f
    f.mgr.shutdown()


@pytest.fixture
def client(fake: FakeService) -> TestClient:
    app = FastAPI()
    errors.install(app)
    app.include_router(round3.router)
    return TestClient(app)


def _job(client: TestClient, fake: FakeService, *, facts: bool = True) -> str:
    job = fake.start_demo_job("spacer-easy-01")
    _wait_done(fake, job.id)
    if facts:
        job.write_json("facts.json", FACTS)
    return job.id


def test_job_card_print_side_then_cited_lookup(client: TestClient, fake: FakeService) -> None:
    jid = _job(client, fake)
    r = client.get(f"/api/v1/jobs/{jid}/buy-or-print")
    assert r.status_code == 200, r.text
    card = r.json()
    assert card["lookup"] is None and card["status"] == "verified" and card["mode"] == "mock"
    pla, petg = card["prints"]
    assert pla["material"] == "PLA" and pla["grams"] == pytest.approx(1921.4 / 1000 * 1.24, abs=0.01)
    assert pla["filament_cost"]["INR"] == pytest.approx(pla["grams"] / 1000 * 1200, abs=0.01)
    assert pla["print_minutes"] == 5.6 and petg["grams"] > pla["grams"]
    assert any("not a quote" in a for a in pla["assumptions"])
    assert "POST" in card["notes"][0]

    # POST runs the (mock) lookup; a fixture answer goes through the live rules: uncited offers are dropped
    mocks.register_mock("buy_lookup", lambda req: {"answer": ANSWER, "sources": SOURCES})
    r = client.post(f"/api/v1/jobs/{jid}/buy-or-print", json={"city": "Pune"})
    assert r.status_code == 200, r.text
    card = r.json()
    lk = card["lookup"]
    assert card["mode"] == "mock" and lk["label"].startswith("MOCK") and lk["city"] == "Pune"
    assert [o["seller"] for o in lk["offers"]] == ["Shop"] and lk["offers"][0]["url"] == SOURCES[0]
    assert [p["name"] for p in lk["places"]] == ["Fab Lab"]
    assert any("Uncited" in d for d in lk["dropped"])
    assert any("no seller or price on this card came from the web" in n for n in card["notes"])
    job = fake.mgr.get(jid)
    assert job is not None and any(e.t == "model_call" and e.stage == "buy_lookup" for e in job.events)
    # GET now returns the stored card; the verification file is untouched
    stored = client.get(f"/api/v1/jobs/{jid}/buy-or-print").json()
    assert stored["lookup"]["offers"][0]["seller"] == "Shop" and stored["recorded"] is False
    assert job.read_json("verification.json")["status"] == "verified"


def test_stored_card_is_marked_recorded_when_the_server_replays(
    client: TestClient, fake: FakeService, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A server in PROVIDER_MODE=replay reads stored cards back: they say recorded, so the web never shows LIVE."""
    jid = _job(client, fake)
    mocks.register_mock("buy_lookup", lambda req: {"answer": ANSWER, "sources": SOURCES})
    assert client.post(f"/api/v1/jobs/{jid}/buy-or-print", json={}).json()["recorded"] is False  # ran just now
    monkeypatch.setenv("PROVIDER_MODE", "replay")
    assert client.get(f"/api/v1/jobs/{jid}/buy-or-print").json()["recorded"] is True


def test_job_card_errors(client: TestClient, fake: FakeService) -> None:
    _err(client.get("/api/v1/jobs/j_nope/buy-or-print"), 404, "job_not_found")
    from partsmith_schemas import JobInput

    job = fake.start_fix_job({"top": b"x"}, JobInput(intent="no-outline"))
    _wait_done(fake, job.id)
    _err(client.get(f"/api/v1/jobs/{job.id}/buy-or-print"), 409, "no_program")
    _err(client.post(f"/api/v1/jobs/{job.id}/buy-or-print", json={}), 409, "no_program")


def test_part_card_uses_facts_and_the_source_jobs_lookup(client: TestClient, fake: FakeService) -> None:
    jid = _job(client, fake)
    mocks.register_mock("buy_lookup", lambda req: {"answer": ANSWER, "sources": SOURCES})
    assert client.post(f"/api/v1/jobs/{jid}/buy-or-print", json={}).status_code == 200
    part = make_part("spacer", "spacer-card")
    part = part.model_copy(update={"facts": FACTS, "provenance": part.provenance.model_copy(update={"job_id": jid})})
    get_registry().upsert_part(part)
    card = client.get("/api/v1/parts/spacer-card/buy-or-print").json()
    assert card["slug"] == "spacer-card" and card["prints"][0]["grams"] == pytest.approx(2.38, abs=0.01)
    assert card["lookup"]["offers"][0]["seller"] == "Shop"
    _err(client.get("/api/v1/parts/no-such-part/buy-or-print"), 404, "part_not_found")
