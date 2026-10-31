"""Job list thumbnails: the measured photo cropped to the part, cached, 404 without a photo."""

from __future__ import annotations

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from services.api import job_thumbs
from services.api import main as M
from services.common import blobs
from services.review.tests.fakes import FakeService, finish


@pytest.fixture
def svc(monkeypatch: pytest.MonkeyPatch) -> FakeService:
    from services.api import deps

    s = FakeService()
    monkeypatch.setattr(deps, "service", lambda: s)
    return s


def _png(w: int, h: int) -> bytes:
    img = np.full((h, w, 3), 200, np.uint8)
    img[h // 4 : 3 * h // 4, w // 4 : 3 * w // 4] = 30
    ok, buf = cv2.imencode(".png", img)
    assert ok
    return bytes(buf)


def test_render_crops_and_shrinks() -> None:
    out = cv2.imdecode(np.frombuffer(job_thumbs.render(_png(1000, 600), [0.25, 0.25, 0.75, 0.75]), np.uint8), 1)
    h, w = out.shape[:2]
    assert max(h, w) == job_thumbs.THUMB_PX and abs(w / h - 500 / 300) < 0.05
    assert out.mean() < 60  # the dark part fills the crop
    small = cv2.imdecode(np.frombuffer(job_thumbs.render(_png(100, 50), None), np.uint8), 1)
    assert small.shape[:2] == (50, 100)  # never upscaled
    with pytest.raises(ValueError):
        job_thumbs.render(b"not an image", None)


def test_endpoint_serves_cached_jpeg_or_404(svc: FakeService) -> None:
    client = TestClient(M.app)
    job = finish(svc.new_job())
    assert client.get(f"/api/v1/jobs/{job.id}/thumbnail.jpg").json()["error"]["code"] == "no_photo"
    key = blobs.put(_png(800, 500), ".png")
    job.write_json("rectified.json", {"sha": key, "px_per_mm": 10.0, "origin_mm": [0.0, 0.0]})
    r = client.get(f"/api/v1/jobs/{job.id}/thumbnail.jpg")
    assert r.status_code == 200 and r.headers["content-type"] == "image/jpeg"
    assert r.content[:2] == b"\xff\xd8"
    assert client.get(f"/api/v1/jobs/{job.id}/thumbnail.jpg").content == r.content  # cached file
    assert client.get("/api/v1/jobs/j_nope/thumbnail.jpg").status_code == 404


def _stl_box() -> bytes:
    import trimesh

    return bytes(trimesh.creation.box(extents=(20.0, 10.0, 5.0)).export(file_type="stl"))


def test_render_model_draws_a_shaded_png() -> None:
    out = cv2.imdecode(np.frombuffer(job_thumbs.render_model(_stl_box()), np.uint8), cv2.IMREAD_COLOR)
    assert out is not None
    assert out.shape[:2] == (job_thumbs.MODEL_PX, job_thumbs.MODEL_PX)
    assert (out < 250).any() and (out == 255).all(axis=2).any()  # a shaded shape on a white background
    with pytest.raises(ValueError):
        job_thumbs.render_model(b"not a mesh")


def test_model_picture_endpoint_serves_cached_png_or_404(svc: FakeService) -> None:
    from partsmith_schemas import ArtifactEvent

    client = TestClient(M.app)
    job = finish(svc.new_job())
    assert client.get(f"/api/v1/jobs/{job.id}/model.png").json()["error"]["code"] == "no_model"
    key = blobs.put(_stl_box(), ".stl")
    job.emit(ArtifactEvent(job=job.id, kind="stl", sha=key, url=blobs.url(key), label="STL export"))
    r = client.get(f"/api/v1/jobs/{job.id}/model.png")
    assert r.status_code == 200 and r.headers["content-type"] == "image/png"
    assert r.content[:8] == b"\x89PNG\r\n\x1a\n"
    assert client.get(f"/api/v1/jobs/{job.id}/model.png").content == r.content  # cached file
    assert client.get("/api/v1/jobs/j_nope/model.png").status_code == 404
