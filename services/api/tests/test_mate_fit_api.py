"""The "where it fits" photo through the API: mating taps in the points payload and GET /jobs/{id}/mate-fit."""

from __future__ import annotations

import json
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from partsmith_schemas.common import Measured
from partsmith_schemas.measurement import MateMeasurement
from partsmith_schemas.verification import MateFitResult

from services.api import errors, round3
from services.api.tests.test_api import FakeService, _err, _jpeg, _wait_done
from services.api.uploads import parse_points
from services.verifier.mate_fit import PrinterFit, check_fits

SHAFT_BORE = {"id": "shaft_bore", "label": "shaft bore", "mate_label": "shaft", "gap_mm": 6.2}


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch) -> Any:
    from services.api import deps

    f = FakeService()
    monkeypatch.setattr(deps, "service", lambda: f)
    yield f
    f.mgr.shutdown()


def test_parse_points_takes_mating_taps_with_their_own_kinds() -> None:
    raw = json.dumps({"top": [{"x": 1, "y": 2}], "mating": [{"x": 10, "y": 20, "kind": "mate_peg"}, {"x": 5, "y": 6}]})
    assert parse_points(raw) == {
        "top": [{"x": 1.0, "y": 2.0, "kind": "hole"}],
        "mating": [{"x": 10.0, "y": 20.0, "kind": "mate_peg"}, {"x": 5.0, "y": 6.0, "kind": "mate_hole"}],
    }
    assert parse_points(json.dumps({"mating": [{"x": 3, "y": 4, "kind": "exclude"}]})) == {
        "mating": [{"x": 3.0, "y": 4.0, "kind": "exclude"}]
    }
    bads: list[dict[str, Any]] = [
        {"mating": [{"x": 1, "y": 2, "kind": "hole"}]},
        {"top": [{"x": 1, "y": 2, "kind": "mate_peg"}]},
        {"side": []},
    ]
    for bad in bads:
        with pytest.raises(errors.ApiError) as e:
            parse_points(json.dumps(bad))
        assert e.value.code == "invalid_points"


def test_fix_upload_takes_mating_taps_only_with_the_mating_photo(fake: FakeService) -> None:
    from services.api.main import app

    client = TestClient(app)
    taps = json.dumps({"mating": [{"x": 100, "y": 120, "kind": "mate_slot"}]})
    files = {"top": ("top.jpg", _jpeg(), "image/jpeg"), "mating": ("m.jpg", _jpeg(), "image/jpeg")}
    r = client.post("/api/v1/jobs/fix", files=files, data={"points": taps})
    assert r.status_code == 200, r.text
    assert fake.points[r.json()["id"]] == {"mating": [{"x": 100.0, "y": 120.0, "kind": "mate_slot"}]}
    top = {"top": ("top.jpg", _jpeg(), "image/jpeg")}
    _err(client.post("/api/v1/jobs/fix", files=top, data={"points": taps}), 422, "invalid_points")


def _stored(fake: FakeService) -> str:
    job = fake.start_demo_job("spacer-easy-01")
    _wait_done(fake, job.id)
    mate = MateMeasurement(id="mate_1", kind="mate_peg", point_px=(10.0, 10.0), ok=True, material="material",
                           shape="strip", size=Measured(value=6.0, sigma_mm=0.02))  # fmt: skip
    feats = {"bbox_mm": [-15, -15, 0, 15, 15, 16], "interfaces": [SHAFT_BORE]}
    fits = check_fits([mate], feats, PrinterFit("pla-fdm-0.4", "PLA · FDM 0.4 mm nozzle", 0.2, "preset"))
    job.write_json("mate_fit.json", MateFitResult(mates=[mate], fits=fits, preset="pla-fdm-0.4"))
    return job.id


def test_mate_fit_route_returns_the_record_and_recomputes_the_printer_note(fake: FakeService) -> None:
    app = FastAPI()
    errors.install(app)
    app.include_router(round3.router)
    client = TestClient(app)
    plain = fake.start_demo_job("spacer-easy-01")
    _wait_done(fake, plain.id)
    _err(client.get(f"/api/v1/jobs/{plain.id}/mate-fit"), 404, "no_mate_fit")
    jid = _stored(fake)
    r = client.get(f"/api/v1/jobs/{jid}/mate-fit")
    assert r.status_code == 200, r.text
    (f,) = r.json()["fits"]
    assert f["fit"] == "sliding fit" and f["clearance_mm"] == pytest.approx(0.2)
    assert f["printed"]["clearance_in_effect_mm"] == pytest.approx(0.2) and f["printed"]["clearance_source"] == "preset"
    r = client.get(f"/api/v1/jobs/{jid}/mate-fit", params={"preset": "abs-fdm-0.4"})
    (g,) = r.json()["fits"]
    assert g["printed"]["preset"] == "abs-fdm-0.4" and g["printed"]["clearance_mm"] == pytest.approx(0.2 - 0.3)
    assert g["clearance_mm"] == f["clearance_mm"]  # the CAD and the measured mate never change
    _err(client.get(f"/api/v1/jobs/{jid}/mate-fit", params={"preset": "nylon"}), 422, "unknown_preset")
    r = client.get(f"/api/v1/jobs/{jid}/mate-fit", params={"fit_session": "dev-abcdefgh1234"})
    assert r.status_code == 200 and r.json()["fits"][0]["printed"]["clearance_source"] == "preset"  # no reports yet
