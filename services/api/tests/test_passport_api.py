"""Repair passport routes: resolve, QR codes, the export gate on reprint and the passport mark on bakes (fixtures,
mock providers, no network)."""

from __future__ import annotations

import io
from collections.abc import Iterator
from typing import Any

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from services.api import deps
from services.api import main as M
from services.api.tests.test_api import FakeService, _err, _wait_done
from services.common import blobs
from services.geom_worker.program import code_sha, parse_params
from services.geom_worker.tests.test_passport_mark import BIG
from services.registry import passport as PP
from services.registry.store import get_registry
from services.registry.tests.fixtures import add_part, make_part


class PassportFake(FakeService):
    def bake_job(self, job_id: str, params: dict[str, float], formats: Any, *, passport: str | None = None) -> Any:
        from services.geom_worker.bake import bake

        job = self.mgr.get(job_id)
        code = job.read_text("part.py") if job else None
        if not code:
            raise KeyError(job_id)
        out = bake(code, params, formats, passport=passport)
        return out.to_bake_result(job_id, lambda fmt, p: blobs.url(blobs.put(p.read_bytes(), p.suffix)))


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch) -> Iterator[PassportFake]:
    f = PassportFake()
    monkeypatch.setattr(deps, "service", lambda: f)
    M._call_cache.clear()
    yield f
    f.mgr.shutdown()


@pytest.fixture
def client(fake: PassportFake) -> TestClient:
    return TestClient(M.app)


def _big_part(slug: str = "big-plate", *, verified: bool = True) -> Any:
    base = make_part("spacer", slug, verified=verified)
    specs = parse_params(BIG)
    part = base.model_copy(update={"code": BIG, "code_sha": code_sha(BIG), "params": specs,
                                   "defaults": {s.name: float(s.default) for s in specs}})  # fmt: skip
    get_registry().upsert_part(part)
    return part


def test_resolve_a_published_part_any_case_and_unknown_ids(client: TestClient) -> None:
    part = add_part("spacer", "spacer-pp")
    pid = PP.part_id(part)
    r = client.get(f"/api/v1/passport/{pid.lower()}")
    assert r.status_code == 200, r.text
    p = r.json()
    assert p["id"] == pid and p["kind"] == "part" and p["slug"] == "spacer-pp" and p["published"]
    assert p["version"] == part.version and not p["superseded"] and p["status"] == "verified" and p["verified"]
    assert p["values"] == pytest.approx(part.defaults) and p["preset"]["id"] == "pla-fdm-0.4"
    assert p["ship"]["status"] == "verified" and p["page_url"] == "/parts/spacer-pp"
    detail = client.get("/api/v1/parts/spacer-pp").json()
    assert detail["passport"] == {"id": pid, "url": f"/p/{pid}", "qr_svg_url": f"/api/v1/passport/{pid}/qr.svg",
                                  "qr_png_url": f"/api/v1/passport/{pid}/qr.png"}  # fmt: skip
    typo = pid[:5] + ("0" if pid[5] != "0" else "1")
    e = _err(client.get(f"/api/v1/passport/{typo}"), 404, "passport_not_found")
    assert pid in e["closest_matches"]
    e = _err(client.get("/api/v1/passport/not-an-id"), 404, "passport_not_found")
    assert "letters or digits" in e["message"]


def test_qr_codes_point_at_the_passport_page(client: TestClient) -> None:
    import cv2

    pid = PP.part_id(add_part("spacer", "spacer-qr"))
    svg = client.get(f"/api/v1/passport/{pid}/qr.svg")
    assert svg.status_code == 200 and svg.headers["content-type"].startswith("image/svg+xml")
    assert "<svg" in svg.text and pid in svg.text
    png = client.get(f"/api/v1/passport/{pid}/qr.png")
    assert png.status_code == 200 and png.headers["content-type"] == "image/png"
    img = np.array(Image.open(io.BytesIO(png.content)).convert("L"))
    assert cv2.QRCodeDetector().detectAndDecode(img)[0] == f"http://testserver/p/{pid}"
    forwarded = client.get(f"/api/v1/passport/{pid}/qr.png", headers={"X-Forwarded-Host": "partsmith.example",
                                                                       "X-Forwarded-Proto": "https"})  # fmt: skip
    img = np.array(Image.open(io.BytesIO(forwarded.content)).convert("L"))
    assert cv2.QRCodeDetector().detectAndDecode(img)[0] == f"https://partsmith.example/p/{pid}"
    _err(client.get("/api/v1/passport/000000/qr.svg"), 404, "passport_not_found")


def test_unpublished_job_resolves_to_its_job_then_to_its_part(client: TestClient, fake: PassportFake) -> None:
    job = fake.start_demo_job("spacer-easy-01")
    _wait_done(fake, job.id)
    pid = PP.job_id(job.id)
    detail = client.get(f"/api/v1/jobs/{job.id}").json()
    assert detail["passport"]["id"] == pid and detail["passport"]["url"] == f"/p/{pid}"
    p = client.get(f"/api/v1/passport/{pid}").json()
    assert p["kind"] == "job" and not p["published"] and p["job_id"] == job.id and p["page_url"] == f"/jobs/{job.id}"
    assert p["bake_url"] == f"/api/v1/jobs/{job.id}/bake" and p["status"] == "verified"
    part = add_part("spacer", "spacer-from-job")
    job.summary.part_slug = part.slug
    job.save_summary()
    p = client.get(f"/api/v1/passport/{pid}").json()
    assert p["kind"] == "part" and p["slug"] == "spacer-from-job" and p["id"] == pid and p["job_id"] == job.id
    assert any("published as spacer-from-job" in n for n in p["notes"])


def test_reprint_goes_through_the_export_gate(client: TestClient) -> None:
    part = add_part("spacer", "spacer-be", verified=False)
    p = client.get(f"/api/v1/passport/{PP.part_id(part)}").json()
    assert p["ship"]["status"] == "best_effort" and p["ship"]["needs_ack"]
    url = p["bake_url"] + "?format=stl&download=1&preset=" + p["preset"]["id"]
    _err(client.get(url), 409, "needs_ack")
    r = client.get(url + "&ack=1")
    assert r.status_code == 200 and r.content[:5] != b"solid" and len(r.content) > 84


def test_passport_mark_on_part_bakes(client: TestClient) -> None:
    part = _big_part()
    pid = PP.part_id(part)
    r = client.get("/api/v1/parts/big-plate/bake?format=stl&passport=1")
    assert r.status_code == 200, r.text
    mark = r.json()["passport"]
    assert mark["applied"] and mark["text"] == pid and all(c["passed"] for c in mark["checks"])
    plain = client.get("/api/v1/parts/big-plate/bake?format=stl").json()
    assert "passport" not in plain and plain["cache_key"] != r.json()["cache_key"]
    assert plain["facts"]["bbox_mm"] == pytest.approx(r.json()["facts"]["bbox_mm"], abs=1e-3)
    dl = client.get("/api/v1/parts/big-plate/bake?format=stl&download=1&passport=1")
    assert dl.status_code == 200 and dl.headers["x-partsmith-passport"] == f"applied {pid}"
    moved = client.get("/api/v1/parts/big-plate/bake?format=stl&passport=1&length=80").json()["passport"]
    assert not moved["applied"] and "knobs differ" in moved["reason"] and "length" in moved["reason"]
    small = add_part("spacer", "spacer-small")
    rep = client.get("/api/v1/parts/spacer-small/bake?format=stl&passport=1").json()["passport"]
    assert rep["text"] == PP.part_id(small) and not rep["applied"] and "no safe place" in rep["reason"]


def test_passport_mark_on_job_bakes(client: TestClient, fake: PassportFake) -> None:
    job = fake.start_demo_job("spacer-easy-01")
    _wait_done(fake, job.id)
    job.write_text("part.py", BIG)
    r = client.get(f"/api/v1/jobs/{job.id}/bake?format=stl&passport=1")
    assert r.status_code == 200, r.text
    mark = r.json()["passport"]
    assert mark["applied"] and mark["text"] == PP.job_id(job.id), mark
    dl = client.get(f"/api/v1/jobs/{job.id}/bake?format=stl&passport=1&download=1")
    assert dl.status_code == 200 and dl.headers["x-partsmith-passport"].startswith("applied ")


def test_passport_routes_are_mounted() -> None:
    routes = set(M.iter_routes())
    assert {("GET", "/api/v1/passport/{passport_id}"), ("GET", "/api/v1/passport/{passport_id}/qr.svg"),
            ("GET", "/api/v1/passport/{passport_id}/qr.png")} <= routes  # fmt: skip
