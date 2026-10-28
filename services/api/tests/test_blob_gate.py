"""Printable files behind content-addressed links (`/blobs/<key>`, `/bakes/<key>/<name>`) go through the same export
gate as the part and job download routes; previews stay open. Also: the lying-model evidence files are served."""

from __future__ import annotations

import json
from typing import Any

import pytest
from fastapi.testclient import TestClient
from partsmith_schemas import ArtifactEvent

from services.api import main as M
from services.api import usage
from services.api.common import IMMUTABLE
from services.api.tests.test_api import FakeService, _err, _wait_done
from services.common import blobs
from services.common.paths import REPO_ROOT
from services.registry.store import get_registry
from services.registry.tests.fixtures import add_part, make_part

STL = b"solid t\nendsolid t\n"


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


def _job(client: TestClient, fake: FakeService) -> str:
    jid = str(client.post("/api/v1/jobs/demo", json={"sample": "spacer-easy-01"}).json()["id"])
    _wait_done(fake, jid)
    return jid


def _emit(fake: FakeService, jid: str, kind: str, data: bytes, ext: str) -> str:
    job = fake.mgr.get(jid)
    assert job is not None
    key = blobs.put(data, ext)
    job.emit(ArtifactEvent(job=jid, kind=kind, sha=key, url=blobs.url(key), label=kind))
    return f"/api/v1/blobs/{key}"


def _set_state(fake: FakeService, jid: str, state: str) -> None:
    job = fake.mgr.get(jid)
    assert job is not None
    if state == "verified":
        job.write_json("verification.json", make_part("spacer").verification)
    elif state == "best_effort":
        job.write_json("verification.json", make_part("spacer", verified=False, max_error_mm=0.8).verification)
    else:
        job.write_json("verification.json", {"verified": False, "status": "failed", "reasons": ["no solid"]})


def test_job_blob_links_follow_the_export_gate(client: TestClient, fake: FakeService) -> None:
    jid = _job(client, fake)
    stl = _emit(fake, jid, "stl", STL, ".stl")
    tmf = _emit(fake, jid, "threemf", STL + b"3mf", ".3mf")
    step = _emit(fake, jid, "step", STL + b"step", ".step")
    zipped = _emit(fake, jid, "zip", b"PK\x05\x06" + b"\0" * 18, ".zip")
    coupon = _emit(fake, jid, "coupon", STL + b"coupon", ".stl")
    png = _emit(fake, jid, "mask_overlay", b"\x89PNG\r\n\x1a\nfake", ".png")
    view = _emit(fake, jid, "view", b"{}", ".json")

    _set_state(fake, jid, "verified")
    r = client.get(stl)
    assert r.status_code == 200 and r.content == STL
    assert r.headers["cache-control"] == M.GATED_CACHE  # never cached by a shared cache
    assert client.get(png).headers["cache-control"] == IMMUTABLE

    _set_state(fake, jid, "best_effort")
    for url in (stl, tmf, step, zipped):
        e = _err(client.get(url), 409, "needs_ack")
        assert "ack=1" in e["message"]
        assert client.get(f"{url}?ack=1").status_code == 200
    # a 304 revalidation cannot skip the gate either
    _err(client.get(stl, headers={"If-None-Match": f'"{stl.rsplit("/", 1)[-1].split(".")[0]}"'}), 409, "needs_ack")

    _set_state(fake, jid, "failed")
    for url in (stl, tmf, step, zipped):
        _err(client.get(f"{url}?ack=1"), 409, "not_shippable")
    # previews and the fit-test coupon stay open in every state
    for url in (png, view, coupon):
        assert client.get(url).status_code == 200


def test_unowned_printable_blob_is_refused_and_preview_blob_is_open(client: TestClient) -> None:
    stray = blobs.put(STL + b"stray", ".stl")
    e = _err(client.get(f"/api/v1/blobs/{stray}?ack=1"), 409, "not_shippable")
    assert "No verification record" in e["message"]
    glb = blobs.put(b"glTF fake", ".glb")
    assert client.get(f"/api/v1/blobs/{glb}").status_code == 200


def test_job_bake_blob_links_are_gated(client: TestClient, fake: FakeService) -> None:
    jid = _job(client, fake)
    _set_state(fake, jid, "best_effort")
    res = client.get(f"/api/v1/jobs/{jid}/bake?format=stl,view").json()
    stl, view = res["artifacts"]["stl"], res["artifacts"]["view"]
    assert f"job:{jid}" in blobs.owners(stl.rsplit("/", 1)[-1])
    _err(client.get(stl), 409, "needs_ack")
    assert client.get(f"{stl}?ack=1").status_code == 200
    assert client.get(view).status_code == 200
    _set_state(fake, jid, "verified")
    assert client.get(stl).status_code == 200


@pytest.mark.parametrize("claimed", [True, False])
def test_part_bake_file_links_follow_the_export_gate(client: TestClient, claimed: bool) -> None:
    add_part("cable_clip", "desk-cable-clip")
    add_part("hook", "rough-hook", verified=False, max_error_mm=0.8)
    failed = make_part("spacer", "broken-spacer", verified=False)
    assert failed.verification is not None
    failed.verification = failed.verification.model_copy(update={"status": "failed", "reasons": ["no solid"]})
    get_registry().upsert_part(failed)

    def links(slug: str) -> dict[str, Any]:
        if claimed:  # through the REST bake route (records the claim)
            arts: dict[str, Any] = client.get(f"/api/v1/parts/{slug}/bake?format=stl,3mf,step,glb,view").json()[
                "artifacts"
            ]
            return arts
        from services.registry import parts as P  # e.g. the MCP bake tool: no claim, found from the bake manifest

        res = P.bake_part(slug, formats=["stl", "3mf", "step", "glb", "view"])
        key = res.cache_key
        assert blobs.owners(key) == []
        return dict(res.artifacts)

    ok = links("desk-cable-clip")
    assert client.get(ok["stl"]).status_code == 200
    rough = links("rough-hook")
    for fmt in ("stl", "3mf", "step"):
        _err(client.get(rough[fmt]), 409, "needs_ack")
        assert client.get(f"{rough[fmt]}?ack=1").status_code == 200
    assert client.get(rough["glb"]).status_code == 200  # previews stay open
    assert client.get(rough["view"]).status_code == 200
    bad = links("broken-spacer")
    _err(client.get(f"{bad['stl']}?ack=1"), 409, "not_shippable")
    assert client.get(bad["view"]).status_code == 200


def test_owner_index_is_idempotent_and_validated() -> None:
    key = blobs.put(STL, ".stl")
    assert blobs.is_printable(key) and not blobs.is_printable(blobs.put(b"x", ".png"))
    blobs.claim(key, "job:j_1")
    blobs.claim(key, "job:j_1")
    blobs.claim(key, "part:p")
    assert blobs.owners(key) == ["job:j_1", "part:p"]
    with pytest.raises(ValueError):
        blobs.claim("not-a-key.stl", "job:x")
    with pytest.raises(ValueError):
        blobs.claim(key, "job:a\njob:b")


def test_lying_model_evidence_files_are_served(client: TestClient) -> None:
    """/judges reads the caught-lie records from /bench and their overlays from /bench/files."""
    path = REPO_ROOT / "eval" / "reports" / "latest" / "bypass.json"
    if not path.exists():
        pytest.skip("eval.bypass has not been run in this checkout")
    caught = json.loads(path.read_text()).get("caught") or []
    assert client.get("/api/v1/bench").json()["evidence"]["bypass"]["caught"] == caught
    for c in caught:
        r = client.get(f"/api/v1/bench/files/{c['overlay']}")
        assert r.status_code == 200 and r.headers["content-type"] == "image/jpeg" and len(r.content) <= 150_000
