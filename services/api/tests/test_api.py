"""TestClient over every route. The agent service is a fast fake (real JobManager, scripted events); the registry,
bakes, Steer, uploads and SSE are real. No network, no keys."""

from __future__ import annotations

import io
import json
import threading
import time
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from partsmith_schemas import (
    DataOrigin,
    DoneEvent,
    JobInput,
    MetricEvent,
    QuestionEvent,
    StageEvent,
)
from PIL import ExifTags, Image

from services.agent import jobs
from services.api import deps
from services.api import main as M
from services.api.uploads import has_gps
from services.common import blobs
from services.registry.store import get_registry
from services.registry.tests.fixtures import add_part, make_part


def _jpeg(w: int = 640, h: int = 480, gps: bool = True) -> bytes:
    im = Image.new("RGB", (w, h), (200, 200, 205))
    exif = Image.Exif()
    exif[ExifTags.Base.Make] = "TestCam"
    if gps:
        exif[ExifTags.IFD.GPSInfo] = {1: "N", 2: (12.0, 34.0, 56.0), 3: "E", 4: (76.0, 54.0, 32.0)}
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=92, exif=exif)
    return buf.getvalue()


class FakeService:
    """Scripted stand-in for services/agent/service.py (same function names and shapes)."""

    def __init__(self) -> None:
        self.mgr = jobs.JobManager(max_workers=4)
        self.photos: dict[str, dict[str, bytes]] = {}
        self.inputs: dict[str, JobInput] = {}

    def manager(self) -> jobs.JobManager:
        return self.mgr

    def _runner(self, ask: bool) -> Any:
        def run(j: jobs.Job) -> None:
            j.emit(StageEvent(job=j.id, stage="capture", status="ok", label="markers found"))
            time.sleep(0.15)
            j.emit(StageEvent(job=j.id, stage="measure", status="ok"))
            if ask:
                ans = j.ask(QuestionEvent(job=j.id, id="q1", text="Say the thickness in mm"), timeout_s=10)
                j.log(f"answer {ans.value}")
            j.emit(MetricEvent(job=j.id, iter=1, name="hausdorff_mm", value=0.31, threshold=0.5))
            if j.input.intent != "no-outline":
                j.write_text("part.py", make_part("spacer").code)
                j.write_json("verification.json", make_part("spacer").verification)
                j.write_json("outline.json", {"outline_mm": [[0, 0], [10, 0], [10, 5]], "holes": []})
            j.emit(DoneEvent(job=j.id, verified=True, status="verified", summary={"max_error_mm": 0.31}))

        return run

    def start_fix_job(self, photos: dict[str, bytes], job_input: JobInput, *, sync: bool = False) -> jobs.Job:
        job = self.mgr.create("fix", job_input, title="test fix")
        self.photos[job.id] = photos
        self.inputs[job.id] = job_input
        self.mgr.start(job, self._runner(ask=job_input.intent == "ask"))
        return job

    def start_demo_job(self, sample_id: str, *, sync: bool = False) -> jobs.Job:
        job = self.mgr.create("fix", JobInput(origin=DataOrigin.synthetic), title=f"{sample_id} (synthetic)")
        self.mgr.start(job, self._runner(ask=False))
        return job

    def list_demo_samples(self) -> list[dict[str, Any]]:
        return [{"id": "spacer-easy-01", "title": "Spacer (synthetic)", "family_hint": "spacer", "kind": "template"}]

    def job_detail(self, job_id: str) -> dict[str, Any]:
        job = self.mgr.get(job_id)
        if job is None:
            raise KeyError(job_id)
        return {
            "summary": job.summary.model_dump(mode="json"),
            "events": [e.model_dump() for e in job.events],
            "partspec": None,
            "measurements": {},
            "verification": None,
            "code": job.read_text("part.py"),
            "params": [],
            "values": {},
            "artifacts": {},
            "question": None,
        }

    def answer(self, job_id: str, qid: str, value: str | float, via: str = "text") -> Any:
        job = self.mgr.get(job_id)
        assert job is not None
        job.answer(qid, value, via)
        return job.summary

    def edit(
        self, job_id: str, *, text: str | None = None, audio: bytes | None = None, mime: str = "audio/wav"
    ) -> dict[str, Any]:
        job = self.mgr.get(job_id)
        if job is None or not job.read_text("part.py"):
            raise KeyError(f"job {job_id} has no part program yet")
        return {
            "transcript": text or "audio",
            "edits": [],
            "not_understood": [],
            "confidence": 0.0,
            "mode": "mock",
            "bake": None,
            "got_audio": audio is not None,
            "mime": mime,
        }

    def _outline(self, job_id: str) -> None:
        job = self.mgr.get(job_id)
        if job is None or not job.read_json("outline.json"):
            raise KeyError(f"job {job_id} has no model outline yet")

    def preview(self, job_id: str) -> dict[str, Any]:
        self._outline(job_id)
        return {"url": "/api/v1/blobs/x.png", "label": "AI preview", "mode": "mock"}

    def fit_outline(self, job_id: str, mat_id: str) -> dict[str, Any]:
        self._outline(job_id)
        return {
            "mat_id": mat_id,
            "outline_mm": [[0, 0], [1, 0], [1, 1]],
            "holes": [],
            "dims": [],
            "placement": {"cx_mm": 0, "cy_mm": 0, "theta_deg": 0},
        }

    def fit_check(self, job_id: str, photo: bytes, mat_id: str) -> dict[str, Any]:
        self._outline(job_id)
        return {
            "passed": True,
            "iou": 0.98,
            "hausdorff_mm": 0.3,
            "mean_mm": 0.1,
            "reasons": [],
            "overlay_url": "",
            "capture": {"passed": True, "checks": []},
            "gps_free": not has_gps(photo),
        }

    def cancel(self, job_id: str) -> Any:
        job = self.mgr.get(job_id)
        if job is None:
            raise KeyError(job_id)
        job.cancel()
        return job.summary

    def measure(
        self, photo: bytes, view: str = "top", *, thickness_mm: float | None = None, mat_id: str | None = None
    ) -> dict[str, Any]:
        if len(photo) < 1000:
            raise ValueError("no mat markers found")
        return {
            "capture": {"passed": True, "checks": []},
            "view": view,
            "thickness_mm": thickness_mm,
            "gps_free": not has_gps(photo),
        }

    def bake_job(self, job_id: str, params: dict[str, float], formats: Any) -> Any:
        from services.geom_worker.bake import bake

        job = self.mgr.get(job_id)
        code = job.read_text("part.py") if job else None
        if not code:
            raise KeyError(job_id)
        out = bake(code, params, formats)
        return out.to_bake_result(job_id, lambda fmt, p: blobs.url(blobs.put(p.read_bytes(), p.suffix)))

    def publish(self, job_id: str, *, slug: str | None = None) -> Any:
        part = make_part("spacer", slug or "published-spacer")
        part.provenance.job_id = job_id
        get_registry().upsert_part(part)
        return part

    def replays(self) -> list[dict[str, Any]]:
        return [
            {
                "id": "j_replay",
                "title": "r",
                "origin": "synthetic",
                "provider_mode": "mock",
                "verified": True,
                "max_error_mm": 0.2,
                "iterations": 2,
            }
        ]


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch) -> Iterator[FakeService]:
    f = FakeService()
    monkeypatch.setattr(deps, "service", lambda: f)
    monkeypatch.setattr(M, "HEARTBEAT_S", 0.05)
    M._call_cache.clear()
    yield f
    f.mgr.shutdown()


@pytest.fixture
def client(fake: FakeService) -> TestClient:
    return TestClient(M.app)


def _wait_done(fake: FakeService, jid: str, timeout: float = 10.0) -> None:
    t0 = time.time()
    while time.time() - t0 < timeout:
        job = fake.mgr.get(jid)
        if job is not None and job.finished:
            return
        time.sleep(0.02)
    raise AssertionError("job did not finish")


def _err(r: Any, status: int, code: str) -> dict[str, Any]:
    assert r.status_code == status, r.text
    e = r.json()["error"]
    assert e["code"] == code, e
    return dict(e)


# ------------------------------------------------------------------------------------------------- system


def test_health_status_openapi(client: TestClient, fake: FakeService) -> None:
    assert client.get("/api/v1/health").json() == {"ok": True, "version": M.VERSION}
    jid = client.post("/api/v1/jobs/demo", json={"sample": "spacer-easy-01"}).json()["id"]
    _wait_done(fake, jid)
    job = fake.mgr.get(jid)
    assert job is not None
    job.emit(
        {
            "t": "model_call",
            "job": jid,
            "provider": "baseten",
            "model": "muse-spark-open",
            "stage": "build",
            "mode": "live",
            "tokens_in": 100,
            "tokens_out": 50,
            "ms": 900,
            "usd": 0.002,
        }
    )
    s = client.get("/api/v1/status").json()
    assert s["mode"] in ("mock", "live", "replay", "mixed")
    assert {p["stage"] for p in s["providers"]} >= {"build", "judge", "segment"}
    assert all("key_present" in p for p in s["providers"])
    assert s["jobs"] == {"total": 1, "verified": 1}
    assert s["cost"]["n_jobs"] == 1 and s["cost"]["usd_total"] == pytest.approx(0.002)
    call = next(c for c in s["model_calls"] if c["provider"] == "baseten")
    assert call["calls"] == 1 and call["open_weights"] is True and call["ms_mean"] == 900
    assert s["open_weights"]["calls_on_open_weights"] == 1
    spec = client.get("/api/v1/openapi.json").json()
    assert spec["openapi"].startswith("3.")
    for path in ("/api/v1/parts/{slug}/bake", "/api/v1/jobs/{job_id}/events", "/api/v1/steer", "/api/v1/bench"):
        assert path in spec["paths"]
    assert all(op.get("summary") for p in spec["paths"].values() for op in p.values())


def test_unknown_route_and_validation_use_envelope(client: TestClient) -> None:
    _err(client.get("/api/v1/nope"), 404, "not_found")
    _err(client.post("/api/v1/needs", json={"query": "x"}), 422, "validation_error")


def test_rate_limiter_blocks_bursts() -> None:
    rl = M.RateLimiter(2)
    assert rl.allow("a")[0] and rl.allow("a")[0]
    ok, retry = rl.allow("a")
    assert not ok and retry > 0 and rl.allow("b")[0]


def test_cors_for_web_app(client: TestClient) -> None:
    r = client.options(
        "/api/v1/parts", headers={"Origin": "http://localhost:3000", "Access-Control-Request-Method": "GET"}
    )
    assert r.headers.get("access-control-allow-origin") == "http://localhost:3000"


# ------------------------------------------------------------------------------------------------- mats, blobs, bakes


def test_mats(client: TestClient) -> None:
    mats = client.get("/api/v1/mats").json()
    ids = {m["mat_id"] for m in mats}
    assert "paper-a4" in ids and mats[0]["markers"][0]["bits"]
    assert client.get("/api/v1/mats/paper-a4").json()["kind"] == "paper"
    r = client.get("/api/v1/mats/paper-a4/pdf")
    assert r.status_code == 200 and r.content[:5] == b"%PDF-" and r.headers["content-type"] == "application/pdf"
    e = _err(client.get("/api/v1/mats/paper-a5"), 404, "mat_not_found")
    assert "paper-a4" in e["closest_matches"]


def test_blobs_cache_headers_and_errors(client: TestClient) -> None:
    key = blobs.put(b"\x89PNG\r\n\x1a\nfake", ".png")
    r = client.get(f"/api/v1/blobs/{key}")
    assert r.status_code == 200 and r.headers["content-type"] == "image/png"
    assert "immutable" in r.headers["cache-control"]
    assert client.get(f"/api/v1/blobs/{key}", headers={"If-None-Match": r.headers["etag"]}).status_code == 304
    _err(client.get("/api/v1/blobs/not-a-key"), 400, "bad_key")
    _err(client.get("/api/v1/blobs/" + "0" * 64 + ".png"), 404, "blob_not_found")


# ------------------------------------------------------------------------------------------------- jobs


def test_fix_upload_strips_gps_and_validates(client: TestClient, fake: FakeService) -> None:
    photo = _jpeg()
    assert has_gps(photo)
    r = client.post(
        "/api/v1/jobs/fix",
        files={"top": ("top.jpg", photo, "image/jpeg")},
        data={
            "intent": "make it thicker",
            "thickness_mm": "3.5",
            "family_hint": "spacer",
            "screen_px_per_mm": "4.2",
            "mat_kind": "screen",
        },
    )
    assert r.status_code == 200, r.text
    jid = r.json()["id"]
    stored = fake.photos[jid]["top"]
    assert not has_gps(stored)
    with Image.open(io.BytesIO(stored)) as im:
        assert im.getexif()[ExifTags.Base.Make] == "TestCam"  # camera fields kept
    # pixels untouched: only metadata segments changed
    assert stored[stored.index(b"\xff\xda") :] == photo[photo.index(b"\xff\xda") :]
    ji = fake.inputs[jid]
    assert ji.thickness_mm == 3.5 and ji.screen_px_per_mm == 4.2 and ji.family_hint is not None
    _err(client.post("/api/v1/jobs/fix", files={"top": ("t.jpg", b"not an image", "image/jpeg")}), 422, "bad_image")
    _err(client.post("/api/v1/jobs/fix", files={"top": ("t.jpg", _jpeg(100, 80), "image/jpeg")}), 422, "too_small")
    gif = io.BytesIO()
    Image.new("RGB", (300, 300)).save(gif, "GIF")
    _err(
        client.post("/api/v1/jobs/fix", files={"top": ("t.gif", gif.getvalue(), "image/gif")}),
        415,
        "unsupported_media_type",
    )
    _err(client.post("/api/v1/jobs/fix", data={"intent": "x"}), 422, "validation_error")


def test_demo_list_detail_runlog(client: TestClient, fake: FakeService) -> None:
    samples = client.get("/api/v1/jobs/demo/samples").json()
    assert samples[0]["id"] == "spacer-easy-01"
    e = _err(client.post("/api/v1/jobs/demo", json={"sample": "spacer-easy-1"}), 404, "sample_not_found")
    assert "spacer-easy-01" in e["closest_matches"]
    jid = client.post("/api/v1/jobs/demo", json={"sample": "spacer-easy-01"}).json()["id"]
    _wait_done(fake, jid)
    assert any(j["id"] == jid for j in client.get("/api/v1/jobs?limit=5").json())
    d = client.get(f"/api/v1/jobs/{jid}").json()
    assert d["summary"]["verified"] is True
    lines = client.get(f"/api/v1/jobs/{jid}/run.jsonl").text.strip().splitlines()
    assert json.loads(lines[-1])["t"] == "done"
    e = _err(client.get(f"/api/v1/jobs/{jid[:-1]}x"), 404, "job_not_found")
    assert jid in e["closest_matches"]


def _read_sse(client: TestClient, url: str, headers: dict[str, str] | None = None) -> tuple[list[dict[str, Any]], int]:
    events: list[dict[str, Any]] = []
    heartbeats = 0
    with client.stream("GET", url, headers=headers or {}) as r:
        assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
        for line in r.iter_lines():
            if line.startswith("data: "):
                events.append(json.loads(line[6:]))
            elif line.startswith(": keep-alive"):
                heartbeats += 1
    return events, heartbeats


def test_sse_live_then_replay_and_resume(client: TestClient, fake: FakeService) -> None:
    photo = _jpeg(gps=False)
    jid = client.post("/api/v1/jobs/fix", files={"top": ("t.jpg", photo, "image/jpeg")}, data={"intent": "ask"}).json()[
        "id"
    ]

    def answer_later() -> None:
        job = fake.mgr.get(jid)
        t0 = time.time()
        while job is not None and job.pending_question() is None and time.time() - t0 < 5:
            time.sleep(0.02)
        time.sleep(0.2)  # long enough for heartbeats while the job waits
        r = TestClient(M.app).post(f"/api/v1/jobs/{jid}/answer", json={"id": "q1", "value": 3.0, "via": "voice"})
        assert r.status_code == 200, r.text

    t = threading.Thread(target=answer_later)
    t.start()
    events, heartbeats = _read_sse(client, f"/api/v1/jobs/{jid}/events")
    t.join()
    kinds = [e["t"] for e in events]
    assert kinds[0] == "stage" and kinds[-1] == "done" and "question" in kinds and "answer" in kinds
    assert [e["seq"] for e in events] == list(range(len(events)))
    assert heartbeats >= 1
    # finished job: replay everything with original ts, then end
    replay, _ = _read_sse(client, f"/api/v1/jobs/{jid}/events")
    assert [e["ts"] for e in replay] == [e["ts"] for e in events]
    tail, _ = _read_sse(client, f"/api/v1/jobs/{jid}/events?from_seq=3")
    assert tail[0]["seq"] == 3 and tail[-1]["t"] == "done"
    tail2, _ = _read_sse(client, f"/api/v1/jobs/{jid}/events", {"Last-Event-ID": "4"})
    assert tail2[0]["seq"] == 5
    _err(client.post(f"/api/v1/jobs/{jid}/answer", json={"id": "q1", "value": 1}), 409, "no_pending_question")


def test_job_actions(client: TestClient, fake: FakeService) -> None:
    jid = client.post("/api/v1/jobs/demo", json={"sample": "spacer-easy-01"}).json()["id"]
    _wait_done(fake, jid)
    assert client.post(f"/api/v1/jobs/{jid}/edit", json={"text": "hole 0.2 mm bigger"}).json()["transcript"] == (
        "hole 0.2 mm bigger"
    )
    r = client.post(f"/api/v1/jobs/{jid}/edit", files={"audio": ("a.webm", b"RIFFxxxx", "audio/webm")})
    assert r.json()["got_audio"] is True and r.json()["mime"] == "audio/webm"
    _err(client.post(f"/api/v1/jobs/{jid}/edit", json={}), 422, "validation_error")
    _err(
        client.post(f"/api/v1/jobs/{jid}/edit", files={"audio": ("a.txt", b"x", "text/plain")}),
        415,
        "unsupported_media_type",
    )
    assert client.post(f"/api/v1/jobs/{jid}/preview").json()["label"] == "AI preview"
    assert client.get(f"/api/v1/jobs/{jid}/fit-outline?mat_id=screen-m").json()["mat_id"] == "screen-m"
    _err(client.get(f"/api/v1/jobs/{jid}/fit-outline?mat_id=screen-q"), 404, "mat_not_found")
    r = client.post(
        f"/api/v1/jobs/{jid}/fit-check", files={"photo": ("p.jpg", _jpeg(), "image/jpeg")}, data={"mat_id": "screen-m"}
    )
    assert r.json()["passed"] is True and r.json()["gps_free"] is True
    b = client.get(f"/api/v1/jobs/{jid}/bake?height=12&format=stl,view").json()
    assert set(b["artifacts"]) == {"stl", "view"} and b["params"]["height"] == 12.0
    r = client.get(f"/api/v1/jobs/{jid}/bake?height=12&format=stl&download=1")
    assert r.status_code == 200 and r.headers["content-type"] == "model/stl" and len(r.content) > 84
    p = client.post(f"/api/v1/jobs/{jid}/publish", json={"slug": "my-spacer"}).json()
    assert p["slug"] == "my-spacer" and p["thumbnail_url"].startswith("/api/v1/blobs/")
    _err(client.post(f"/api/v1/jobs/{jid}/publish", json={"slug": "my-spacer"}), 409, "slug_taken")
    assert client.post(f"/api/v1/jobs/{jid}/cancel").status_code == 200
    assert client.get("/api/v1/replays").json()[0]["id"] == "j_replay"


def test_transcribe_mock(client: TestClient) -> None:
    r = client.post(
        "/api/v1/transcribe",
        files={"audio": ("a.wav", b"RIFF....WAVEfmt ", "audio/wav")},
        data={"language_hint": "hinglish"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["mode"] == "mock" and body["text"] and "MOCK" in body["note"]


def test_measure_and_verify(client: TestClient) -> None:
    r = client.post(
        "/api/v1/measure", files={"photo": ("p.jpg", _jpeg(), "image/jpeg")}, data={"view": "top", "thickness_mm": "4"}
    )
    assert r.json()["gps_free"] is True and r.json()["thickness_mm"] == 4.0
    add_part("spacer", "m3-spacer")
    from services.agent.templates import get_template
    from services.geom_worker.sandbox import run_program
    from services.verifier.synthetic import synthetic_top_measurement

    res = run_program(get_template("spacer").code, {}, outputs=())
    meas, _ = synthetic_top_measurement(res)
    res.cleanup()
    body = {"part": "m3-spacer", "params": {}, "measurements": meas.model_dump(mode="json")}
    v = client.post("/api/v1/verify", json=body).json()
    assert v["origin"] == "synthetic" and v["views"][0]["hausdorff_mm"] < 0.5
    body["params"] = {"outer_d": 12.0}
    assert client.post("/api/v1/verify", json=body).json()["verified"] is False
    _err(client.post("/api/v1/verify", json={**body, "part": "m3-spacr"}), 404, "part_not_found")


# ------------------------------------------------------------------------------------------------- registry


def test_parts_search_detail_params(client: TestClient) -> None:
    add_part("caster_wheel", "caster-wheel-50")
    add_part("knob", "cooker-knob", verified=False)
    add_part("spacer", "m3-spacer")
    r = client.get("/api/v1/parts?q=wheel 50 mm").json()
    assert r["items"][0]["slug"] == "caster-wheel-50" and r["total"] >= 1
    card = r["items"][0]
    assert set(card) >= {
        "slug",
        "title",
        "family",
        "status",
        "origin",
        "max_error_mm",
        "thumbnail_url",
        "params_count",
        "topology_knobs",
    }
    page = client.get("/api/v1/parts?sort=title&limit=2").json()
    assert len(page["items"]) == 2 and page["next_cursor"] == "2" and page["total"] == 3
    assert client.get(f"/api/v1/parts?sort=title&limit=2&cursor={page['next_cursor']}").json()["next_cursor"] is None
    assert [i["slug"] for i in client.get("/api/v1/parts?verified=false").json()["items"]] == ["cooker-knob"]
    assert client.get("/api/v1/parts?sort=error").status_code == 200
    _err(client.get("/api/v1/parts?sort=popular"), 422, "validation_error")
    d = client.get("/api/v1/parts/caster-wheel-50").json()
    assert d["artifacts"]["step"] == "/api/v1/parts/caster-wheel-50/bake?format=step&download=1"
    assert d["lineage"] == [] and d["origin"] == "synthetic" and "code" in d
    e = _err(client.get("/api/v1/parts/caster-whel-50"), 404, "part_not_found")
    assert e["closest_matches"] == ["caster-wheel-50"]
    params = client.get("/api/v1/parts/m3-spacer/params").json()
    assert {p["name"] for p in params} >= {"outer_d", "bore_d"}


def test_part_bake_cache_download_and_errors(client: TestClient) -> None:
    add_part("spacer", "m3-spacer")
    a = client.get("/api/v1/parts/m3-spacer/bake?height=14&bore_d=50&format=stl&format=view").json()
    assert a["cache_hit"] is False and a["clamped"] == {"bore_d": 20.0} and set(a["artifacts"]) == {"stl", "view"}
    b = client.get("/api/v1/parts/m3-spacer/bake?height=14&bore_d=50&formats=view,stl").json()
    assert b["cache_hit"] is True and b["cache_key"] == a["cache_key"]
    f = client.get(a["artifacts"]["view"])
    assert f.status_code == 200 and f.headers["content-type"].startswith("application/json") and f.json()["mesh"]
    d = client.get("/api/v1/parts/m3-spacer/bake?format=step&download=1")
    assert d.status_code == 200 and b"ISO-10303-21" in d.content[:200]
    assert 'filename="m3-spacer.step"' in d.headers["content-disposition"]
    py = client.get("/api/v1/parts/m3-spacer/bake?format=py&download=1&height=20")
    assert '"height": (20.0' in py.text
    e = _err(client.get("/api/v1/parts/m3-spacer/bake?heigth=3"), 422, "unknown_param")
    assert "height" in e["closest_matches"]
    _err(client.get("/api/v1/parts/m3-spacer/bake?height=abc"), 422, "bad_param")
    _err(client.get("/api/v1/parts/m3-spacer/bake?format=obj"), 422, "bad_format")
    _err(client.get("/api/v1/bakes/" + "a" * 64 + "/part.stl"), 404, "bake_not_found")


def test_variant_matching_template_thumbnail_feedback(client: TestClient) -> None:
    add_part("clip", "shelf-clip")
    add_part("l_bracket", "shelf-bracket", params={"hole_d": 4.2})
    v = client.get(
        "/api/v1/parts/shelf-clip/variant", params={"want": "M4 hole, 3 ribs, make it 2x bigger overall"}
    ).json()
    assert v["params"]["hole_d"] == 4.5 and v["params"]["rib_count"] == 3 and v["mode"] == "mock"
    assert any("rescal" in x for x in v["not_applied"]) and v["confidence"] <= 0.75
    assert v["bake_url"].startswith("/api/v1/parts/shelf-clip/bake?")
    m = client.get("/api/v1/parts/shelf-clip/matching").json()
    assert m[0]["slug"] == "shelf-bracket" and "4.2 mm" in m[0]["reason"]
    pdf = client.get("/api/v1/parts/shelf-clip/template.pdf?length=50")
    assert pdf.status_code == 200 and pdf.content[:5] == b"%PDF-"
    png = client.get("/api/v1/parts/shelf-clip/thumbnail.png?scale=2")
    assert png.status_code == 200 and Image.open(io.BytesIO(png.content)).size == (1280, 960)
    card = client.get("/api/v1/parts?q=clip").json()["items"][0]
    assert card["thumbnail_url"].startswith("/api/v1/blobs/")
    fb = client.post("/api/v1/parts/shelf-clip/feedback", json={"result": "tight", "note": "0.2 mm tight"}).json()
    assert fb["result"] == "tight"
    assert client.get("/api/v1/parts/shelf-clip").json()["fit_reports"][0]["result"] == "tight"


def test_families_needs_stats(client: TestClient) -> None:
    add_part("hook", "wall-hook")
    add_part("hook", "big-hook", verified=False)
    fams = {f["family"]: f for f in client.get("/api/v1/families").json()}
    assert fams["hook"] == {"family": "hook", "title": "Hooks", "count": 2, "verified": 1}
    assert fams["wheel"]["count"] == 0  # template families are listed with honest zero counts
    n = client.post("/api/v1/needs", json={"query": "dishwasher rack wheel 22 mm"}).json()
    same_client = client.post("/api/v1/needs", json={"query": "Dishwasher rack wheel 22 mm"}).json()
    assert same_client["id"] == n["id"] and same_client["votes"] == 1 and same_client["counted"] is False
    other = client.post("/api/v1/needs", json={"query": "dishwasher rack wheel 22 MM"}, headers={"User-Agent": "b"})
    assert other.json()["votes"] == 2
    assert client.get("/api/v1/needs").json()[0]["votes"] == 2
    s = client.get("/api/v1/stats").json()
    assert s["parts"] == 2 and s["verified"] == 1 and s["synthetic"] == 2 and s["real"] == 0 and s["jobs"] == 0
    assert "grams_pla" in s


def test_steer_routes(client: TestClient) -> None:
    rid = client.post("/api/v1/steer", json={"brief": "desk cable kit", "count": 1}).json()["id"]
    from services.registry import steer

    state = steer.wait(rid, 60)
    assert state["status"] == "reviewing", state
    got = client.get(f"/api/v1/steer/{rid}").json()
    item = got["queue"][0]
    assert set(item) >= {"slug", "title", "family", "status", "job_id", "verified", "max_error_mm", "params"}
    assert got["lanes"][0]["status"] == "done"
    assert client.get("/api/v1/steer").json()[0]["id"] == rid
    _err(
        client.post(f"/api/v1/steer/{rid}/review", json={"slug": "nope", "action": "approve"}), 404, "slug_not_in_queue"
    )
    r = client.post(
        f"/api/v1/steer/{rid}/review", json={"slug": item["slug"], "action": "approve", "note": "ok"}
    ).json()
    assert r["queue"][0]["status"] == "published" and r["status"] == "done"
    assert client.get(f"/api/v1/parts/{item['slug']}").json()["origin"] == "synthetic"
    _err(
        client.post(f"/api/v1/steer/{rid}/review", json={"slug": item["slug"], "action": "approve"}), 409, "bad_review"
    )
    _err(client.get("/api/v1/steer/s_000000_deadbeef"), 404, "steer_not_found")
    lane_job = item["job_id"]
    assert client.get(f"/api/v1/jobs/{lane_job}").status_code in (200, 404)  # lane jobs live in the steer manager


# ------------------------------------------------------------------------------------------------- bench + agent docs


def test_bench_pending_and_report(client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    monkeypatch.setattr(M, "BENCH_REPORT", tmp_path / "missing.json")
    b = client.get("/api/v1/bench").json()
    assert b["status"] == "pending" and b["tables"]["synthetic"]["status"] == "pending"
    assert b["tables"]["real_ruler"]["ground_truth"] == "ruler" and b["failures"] == []
    rep = tmp_path / "report.json"
    rep.write_text(json.dumps({"generated_at": "2026-10-27", "tables": {}, "runs": [], "failures": []}))
    monkeypatch.setattr(M, "BENCH_REPORT", rep)
    assert client.get("/api/v1/bench").json()["status"] == "ok"


def test_llms_and_prompt_txt(client: TestClient) -> None:
    add_part("caster_wheel", "caster-wheel-50")
    for path in ("/api/v1/llms.txt", "/llms.txt"):
        t = client.get(path).text
        assert t.startswith("# PartSmith") and "caster-wheel-50" in t and "Never rescale" in t
    p = client.get("/prompt.txt").text
    assert "report_need" in p and "1 parts" in p


def test_mcp_over_http(fake: FakeService) -> None:
    add_part("spacer", "m3-spacer")
    headers = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}
    with TestClient(M.app) as c:
        init = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "0"},
            },
        }
        r = c.post("/mcp", json=init, headers=headers)
        assert r.status_code == 200, r.text
        assert r.json()["result"]["serverInfo"]["name"] == "partsmith"
        version = r.json()["result"]["protocolVersion"]
        h2 = {**headers, "MCP-Protocol-Version": version}
        tools = c.post("/mcp", json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}, headers=h2)
        assert tools.status_code == 200, tools.text
        names = {t["name"] for t in tools.json()["result"]["tools"]}
        assert {"search_parts", "get_variant", "bake", "report_need"} <= names
        call = {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "search_parts", "arguments": {"q": "spacer"}},
        }
        res = c.post("/mcp", json=call, headers=h2).json()["result"]
        assert "m3-spacer" in json.dumps(res)


def test_every_documented_route_exists() -> None:
    routes = set(M.iter_routes())
    expected = {
        ("GET", "/api/v1/health"),
        ("GET", "/api/v1/status"),
        ("GET", "/api/v1/openapi.json"),
        ("GET", "/api/v1/mats"),
        ("GET", "/api/v1/mats/{mat_id}"),
        ("GET", "/api/v1/mats/{mat_id}/pdf"),
        ("GET", "/api/v1/blobs/{key}"),
        ("GET", "/api/v1/bakes/{cache_key}/{name}"),
        ("POST", "/api/v1/jobs/fix"),
        ("POST", "/api/v1/jobs/demo"),
        ("GET", "/api/v1/jobs/demo/samples"),
        ("GET", "/api/v1/jobs"),
        ("GET", "/api/v1/jobs/{job_id}"),
        ("GET", "/api/v1/jobs/{job_id}/events"),
        ("POST", "/api/v1/jobs/{job_id}/answer"),
        ("POST", "/api/v1/jobs/{job_id}/edit"),
        ("POST", "/api/v1/jobs/{job_id}/preview"),
        ("GET", "/api/v1/jobs/{job_id}/fit-outline"),
        ("POST", "/api/v1/jobs/{job_id}/fit-check"),
        ("GET", "/api/v1/jobs/{job_id}/run.jsonl"),
        ("GET", "/api/v1/jobs/{job_id}/bake"),
        ("POST", "/api/v1/jobs/{job_id}/publish"),
        ("POST", "/api/v1/jobs/{job_id}/cancel"),
        ("POST", "/api/v1/transcribe"),
        ("GET", "/api/v1/replays"),
        ("POST", "/api/v1/measure"),
        ("POST", "/api/v1/verify"),
        ("GET", "/api/v1/parts"),
        ("GET", "/api/v1/parts/{slug}"),
        ("GET", "/api/v1/parts/{slug}/params"),
        ("GET", "/api/v1/parts/{slug}/bake"),
        ("GET", "/api/v1/parts/{slug}/variant"),
        ("GET", "/api/v1/parts/{slug}/matching"),
        ("GET", "/api/v1/parts/{slug}/template.pdf"),
        ("GET", "/api/v1/parts/{slug}/thumbnail.png"),
        ("POST", "/api/v1/parts/{slug}/feedback"),
        ("GET", "/api/v1/families"),
        ("POST", "/api/v1/needs"),
        ("GET", "/api/v1/needs"),
        ("GET", "/api/v1/stats"),
        ("POST", "/api/v1/steer"),
        ("GET", "/api/v1/steer"),
        ("GET", "/api/v1/steer/{run_id}"),
        ("POST", "/api/v1/steer/{run_id}/review"),
        ("GET", "/api/v1/bench"),
        ("GET", "/api/v1/llms.txt"),
        ("GET", "/api/v1/prompt.txt"),
        ("GET", "/llms.txt"),
        ("GET", "/prompt.txt"),
        ("POST", "/mcp"),
    }
    assert expected <= routes, expected - routes


def test_unavailable_service_is_503(monkeypatch: pytest.MonkeyPatch) -> None:
    from services.api.errors import ApiError

    def boom() -> Any:
        raise ApiError(503, "agent_unavailable", "x")

    monkeypatch.setattr(deps, "service", boom)
    _err(TestClient(M.app).get("/api/v1/jobs"), 503, "agent_unavailable")


def test_missing_job_state_is_409_not_500(client: TestClient, fake: FakeService) -> None:
    photo = _jpeg(gps=False)
    jid = client.post(
        "/api/v1/jobs/fix", files={"top": ("t.jpg", photo, "image/jpeg")}, data={"intent": "no-outline"}
    ).json()["id"]
    _wait_done(fake, jid)
    e = _err(client.get(f"/api/v1/jobs/{jid}/fit-outline?mat_id=screen-m"), 409, "no_model_outline")
    assert "no model outline" in e["message"] and "Steer" in e["message"]
    files = {"photo": ("p.jpg", _jpeg(), "image/jpeg")}
    _err(
        client.post(f"/api/v1/jobs/{jid}/fit-check", files=files, data={"mat_id": "screen-m"}), 409, "no_model_outline"
    )
    _err(client.post(f"/api/v1/jobs/{jid}/preview"), 409, "no_preview_source")
    _err(client.post(f"/api/v1/jobs/{jid}/edit", json={"text": "2 mm taller"}), 409, "no_program")
    _err(client.get(f"/api/v1/jobs/{jid}/bake?format=stl"), 409, "no_program")
    tiny = io.BytesIO()
    Image.new("RGB", (300, 300), (0, 0, 0)).save(tiny, "PNG")
    e = _err(client.post("/api/v1/measure", files={"photo": ("p.png", tiny.getvalue(), "image/png")}), 422,
             "invalid_request")  # fmt: skip
    assert "markers" in e["message"]


def test_cancel_returns_the_cancelled_summary(client: TestClient, fake: FakeService) -> None:
    photo = _jpeg(gps=False)
    jid = client.post("/api/v1/jobs/fix", files={"top": ("t.jpg", photo, "image/jpeg")}, data={"intent": "ask"}).json()[
        "id"
    ]
    job = fake.mgr.get(jid)
    t0 = time.time()
    while job is not None and job.pending_question() is None and time.time() - t0 < 5:
        time.sleep(0.02)
    assert job is not None and job.summary.status == "waiting_for_answer"
    out = client.post(f"/api/v1/jobs/{jid}/cancel").json()
    assert out["status"] == "cancelled"
    assert client.post(f"/api/v1/jobs/{jid}/cancel").json()["status"] == "cancelled"  # idempotent


def test_sse_headers(client: TestClient, fake: FakeService) -> None:
    jid = client.post("/api/v1/jobs/demo", json={"sample": "spacer-easy-01"}).json()["id"]
    _wait_done(fake, jid)
    with client.stream("GET", f"/api/v1/jobs/{jid}/events") as r:
        assert r.headers["cache-control"] == "no-cache, no-transform"
        assert r.headers["x-accel-buffering"] == "no"


def test_bench_failure_overlays_and_report_files(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    root = tmp_path / "reports"
    (root / "latest").mkdir(parents=True)
    (root / "2026-10-27" / "gallery").mkdir(parents=True)
    png = io.BytesIO()
    Image.new("RGB", (20, 20)).save(png, "PNG")
    (root / "2026-10-27" / "gallery" / "a.png").write_bytes(png.getvalue())
    (root / "secret.env").write_text("KEY=1")
    blob = blobs.put(png.getvalue(), ".png")
    failures = [
        {"title": "blob ok", "reason": "r", "overlay_url": blobs.url(blob)},
        {"title": "file", "reason": "r", "overlay_url": "/api/v1/blobs/" + "e" * 64 + ".png",
         "overlay_file": "gallery/a.png"},
        {"title": "none", "reason": "r", "overlay_url": "/api/v1/blobs/" + "f" * 64 + ".png",
         "overlay_file": "gallery/missing.png"},
        {"title": "bare", "reason": "r"},
    ]  # fmt: skip
    (root / "latest" / "report.json").write_text(json.dumps({"tables": {}, "runs": [], "failures": failures}))
    monkeypatch.setattr(M, "BENCH_REPORT", root / "latest" / "report.json")
    got = [f["overlay_url"] for f in client.get("/api/v1/bench").json()["failures"]]
    assert got == [blobs.url(blob), "/api/v1/bench/files/2026-10-27/gallery/a.png", None, None]
    r = client.get(got[1])
    assert r.status_code == 200 and r.headers["content-type"] == "image/png"
    for bad in ("../../../etc/passwd", "%2e%2e/%2e%2e/etc/passwd", "secret.env", "2026-10-27/gallery/../../secret.env",
                "/etc/passwd", ".hidden/a.png"):  # fmt: skip
        assert client.get(f"/api/v1/bench/files/{bad}").status_code == 404, bad


def test_agent_docs_use_forwarded_host(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    add_part("spacer", "m3-spacer")
    monkeypatch.delenv("PARTSMITH_PUBLIC_URL", raising=False)
    t = client.get("/llms.txt", headers={"X-Forwarded-Host": "parts.example.com", "X-Forwarded-Proto": "https"}).text
    assert "https://parts.example.com/api/v1/parts/m3-spacer" in t and "testserver" not in t
    p = client.get("/api/v1/prompt.txt", headers={"X-Forwarded-Host": "localhost:3000"}).text
    assert "http://localhost:3000/mcp" in p
    bad = client.get("/llms.txt", headers={"X-Forwarded-Host": "evil.com/x y"}).text
    assert "evil" not in bad and "http://testserver/api/v1" in bad
    monkeypatch.setenv("PARTSMITH_PUBLIC_URL", "https://partsmith.dev/")
    assert "https://partsmith.dev/api/v1/parts/m3-spacer" in client.get("/llms.txt").text


def test_job_publish_dedupes_identical_parts(client: TestClient, fake: FakeService) -> None:
    ids = [client.post("/api/v1/jobs/demo", json={"sample": "spacer-easy-01"}).json()["id"] for _ in range(2)]
    for jid in ids:
        _wait_done(fake, jid)
    a = client.post(f"/api/v1/jobs/{ids[0]}/publish", json={"slug": "spacer-a"}).json()
    b = client.post(f"/api/v1/jobs/{ids[1]}/publish", json={"slug": "spacer-b"}).json()
    assert a["publish"]["action"] == "created"
    assert b["slug"] == "spacer-a" and b["publish"]["duplicate_of"] == "spacer-a"
    assert get_registry().slugs() == ["spacer-a"]
    job = fake.mgr.get(ids[1])
    assert job is not None and job.summary.part_slug == "spacer-a"
