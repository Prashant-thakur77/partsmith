from __future__ import annotations

import asyncio
import base64
import io
from types import SimpleNamespace
from typing import Any

import pytest
from mcp.server.mcpserver.exceptions import ToolError
from PIL import Image

from services.mcp import server as S
from services.registry.store import get_registry
from services.registry.tests.fixtures import add_part


def _call(srv: Any, name: str, args: dict[str, Any]) -> dict[str, Any]:
    res = asyncio.run(srv.call_tool(name, args))
    assert not res.is_error, res
    out: dict[str, Any] = res.structured_content
    return out


@pytest.fixture
def srv() -> Any:
    return S.build_server(allow_paths=True)


def test_tools_have_schemas_descriptions_and_annotations(srv: Any) -> None:
    tools = {t.name: t for t in asyncio.run(srv.list_tools())}
    assert set(tools) == {
        "search_parts",
        "get_part",
        "get_variant",
        "bake",
        "find_matching",
        "list_families",
        "measure_photo",
        "start_fix_job",
        "get_job",
        "report_need",
        "verify",
        "get_lessons",
    }
    for name, t in tools.items():
        assert t.description and len(t.description) > 40, name
        assert t.input_schema["type"] == "object"
        assert t.annotations is not None
        assert t.annotations.read_only_hint is (name not in ("start_fix_job", "report_need")), name
    assert "want" in tools["get_variant"].input_schema["properties"]
    ro = {t.name for t in asyncio.run(S.build_server(read_only=True).list_tools())}
    assert "start_fix_job" not in ro and "report_need" not in ro and "search_parts" in ro


def test_registry_tools(srv: Any) -> None:
    add_part("cable_clip", "desk-cable-clip")
    add_part("clip", "shelf-clip", params={"hole_d": 3.5})
    found = _call(srv, "search_parts", {"q": "cable clip 6 mm"})
    assert found["items"][0]["slug"] == "desk-cable-clip" and found["items"][0]["url"].startswith("http")
    assert found["match"] in ("good", "partial") and 0.5 <= found["coverage"] <= 1.0
    assert found["items"][0]["coverage"] == found["coverage"]
    none = _call(srv, "search_parts", {"q": "zeppelin"})
    assert none["match"] == "none" and none["coverage"] == 0.0 and "/describe" in none["hint"]
    browse = _call(srv, "search_parts", {})
    assert browse["match"] == "all" and browse["coverage"] is None and browse["hint"] is None
    from services.registry import demand

    assert [m["q"] for m in demand.missed_searches()] == ["zeppelin"]  # agent searches count as demand too
    part = _call(srv, "get_part", {"slug": "desk-cable-clip"})
    assert "code" not in part and part["artifacts"]["stl"].startswith("http://localhost:8000/api/v1/parts/")
    v = _call(srv, "get_variant", {"slug": "desk-cable-clip", "want": "for an 8 mm cable, 3 channels"})
    assert v["params"]["cable_d"] == 8.0 and v["params"]["channel_count"] == 3 and v["mode"] == "mock"
    assert v["bake_url"].startswith("http://localhost:8000/api/v1/parts/desk-cable-clip/bake?")
    b = _call(
        srv,
        "bake",
        {"slug": "desk-cable-clip", "params": {"cable_d": 8.0}, "formats": ["stl"], "inline_stl_path": True},
    )
    assert b["artifacts"]["stl"].startswith("http") and b["stl_path"].endswith("part.stl")
    assert _call(srv, "bake", {"slug": "desk-cable-clip", "params": {"cable_d": 8.0}, "formats": ["stl"]})["cache_hit"]
    m = _call(srv, "find_matching", {"slug": "desk-cable-clip"})
    assert m["items"][0]["slug"] == "shelf-clip" and "3.5 mm" in m["items"][0]["reason"]
    fams = _call(srv, "list_families", {})["families"]
    assert {f["family"] for f in fams} == {"cable_clip", "clip"}
    need = _call(srv, "report_need", {"query": "dishwasher rack wheel 22 mm"})
    assert need["votes"] == 1 and get_registry().needs()[0].query.startswith("dishwasher")


def test_errors_name_closest_matches(srv: Any) -> None:
    add_part("spacer", "m3-spacer")
    with pytest.raises(ToolError, match="m3-spacer"):
        asyncio.run(srv.call_tool("get_part", {"slug": "m3-spacr"}))
    with pytest.raises(ToolError, match="Valid knobs: outer_d"):
        asyncio.run(srv.call_tool("bake", {"slug": "m3-spacer", "params": {"radius": 3.0}}))


def test_photo_and_job_tools_use_the_service(monkeypatch: pytest.MonkeyPatch, srv: Any, tmp_path: Any) -> None:
    seen: dict[str, Any] = {}

    def measure(photo: bytes, view: str = "top", **kw: Any) -> dict[str, Any]:
        seen["measure"] = (len(photo), view, kw)
        return {"capture": {"passed": True}, "overlay_url": "/api/v1/blobs/abc.png"}

    def start_fix_job(photos: dict[str, bytes], ji: Any, sync: bool = False) -> Any:
        seen["fix"] = (sorted(photos), ji.intent, ji.thickness_mm)
        summary = SimpleNamespace(model_dump=lambda mode="json": {"id": "j_1", "status": "running"})
        return SimpleNamespace(id="j_1", summary=summary)

    def job_detail(job_id: str) -> dict[str, Any]:
        if job_id != "j_1":
            raise KeyError(job_id)
        return {"summary": {"id": "j_1"}, "events": [{}, {}], "code": "x", "artifacts": {"stl": "/api/v1/blobs/s.stl"}}

    fake = SimpleNamespace(measure=measure, start_fix_job=start_fix_job, job_detail=job_detail)
    monkeypatch.setattr(S, "_svc", lambda: fake)
    img = io.BytesIO()
    Image.new("RGB", (400, 300), (120, 120, 120)).save(img, "PNG")
    b64 = base64.b64encode(img.getvalue()).decode()
    out = _call(srv, "measure_photo", {"image_base64": b64, "thickness_mm": 3.0})
    assert out["overlay_url"] == "http://localhost:8000/api/v1/blobs/abc.png" and seen["measure"][1] == "top"
    p = tmp_path / "top.png"
    p.write_bytes(img.getvalue())
    job = _call(srv, "start_fix_job", {"top_path": str(p), "intent": "hook snapped", "thickness_mm": 4.0})
    assert job["page"].endswith("/jobs/j_1") and seen["fix"] == (["top"], "hook snapped", 4.0)
    j = _call(srv, "get_job", {"job_id": "j_1"})
    assert j["events_count"] == 2 and "code" not in j and j["artifacts"]["stl"].startswith("http")
    with pytest.raises(ToolError, match="no job"):
        asyncio.run(srv.call_tool("get_job", {"job_id": "j_2"}))
    http_only = S.build_server(allow_paths=False)
    with pytest.raises(ToolError, match="only accepted over stdio"):
        asyncio.run(http_only.call_tool("measure_photo", {"path": str(p)}))
    with pytest.raises(ToolError, match="does not decode"):
        asyncio.run(srv.call_tool("measure_photo", {"image_base64": base64.b64encode(b"nope").decode()}))


def test_round2_tools_gate_verify_lessons(monkeypatch: pytest.MonkeyPatch, srv: Any) -> None:
    from services.agent.templates import get_template
    from services.geom_worker.sandbox import run_program
    from services.verifier.synthetic import synthetic_top_measurement

    add_part("spacer", "m3-spacer")
    add_part("hook", "rough-hook", verified=False, max_error_mm=0.8)
    assert _call(srv, "get_part", {"slug": "rough-hook"})["ship"]["status"] == "best_effort"
    with pytest.raises(ToolError, match="ack=true"):
        asyncio.run(srv.call_tool("bake", {"slug": "rough-hook", "formats": ["stl"]}))
    ok = _call(srv, "bake", {"slug": "rough-hook", "formats": ["stl"], "ack": True})
    assert ok["ship"]["status"] == "best_effort" and ok["artifacts"]["stl"].startswith("http")

    res = run_program(get_template("spacer").code, {}, outputs=())
    meas, _ = synthetic_top_measurement(res)
    res.cleanup()
    fake = SimpleNamespace(job_detail=lambda j: {"measurements": {"top": meas.model_dump(mode="json")}} if j == "j_1"
                           else (_ for _ in ()).throw(KeyError(j)))  # fmt: skip
    monkeypatch.setattr(S, "_svc", lambda: fake)
    v = _call(srv, "verify", {"slug": "m3-spacer", "job_id": "j_1"})
    assert v["views"][0]["hausdorff_mm"] < 0.5 and "verified" in v
    with pytest.raises(ToolError, match="no job"):
        asyncio.run(srv.call_tool("verify", {"slug": "m3-spacer", "job_id": "j_9"}))

    reg = get_registry()
    lid = reg.add_lesson("global", "PLA holes print 0.2 mm small", {"job_id": "j_1"})
    assert _call(srv, "get_lessons", {})["lessons"] == []  # only promoted by default
    reg.set_lesson_status(lid, "promoted", "test")
    got = _call(srv, "get_lessons", {})["lessons"]
    assert got[0]["id"] == lid and got[0]["links"][0]["id"] == "j_1"
