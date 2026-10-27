from __future__ import annotations

import json
import socket
import time

import pytest

from services.geom_worker.program import UnknownParamError
from services.geom_worker.sandbox import WarmPool, probe_network, run_program


def test_valid_program_produces_step_stl_and_mesh(pool: WarmPool, plate_code: str) -> None:
    with run_program(plate_code, {"hole_count": 3}, pool=pool, outputs=("stl", "step", "3mf", "glb", "view")) as r:
        assert r.ok, r.error
        assert r.error is None
        assert set(r.artifacts) == {"stl", "step", "3mf", "glb", "view"}
        assert r.artifacts["step"].read_text(errors="replace").startswith("ISO-10303-21")
        assert r.artifacts["stl"].stat().st_size > 1000
        assert r.solid_info is not None and r.solid_info.valid and r.solid_info.n_solids == 1
        assert r.solid_info.size_mm == pytest.approx((40.0, 20.0, 3.0), abs=1e-6)
        assert r.mesh is not None and r.mesh.trimesh().is_watertight
        assert r.params_used["hole_count"] == 3
        assert r.isolation in ("netns", "socket-patch")
        assert r.versions["cadquery"] == "2.8.0"
        feats = r.features or {}
        assert len(feats["holes"]) == 3
        workdir = r.workdir
    assert workdir is not None and not workdir.exists()  # cleaned by the context manager


def test_view_json_format(pool: WarmPool, plate_code: str) -> None:
    with run_program(plate_code, pool=pool, outputs=("view",)) as r:
        doc = json.loads(r.artifacts["view"].read_text())
    assert doc["units"] == "mm" and doc["version"] == 1
    m = doc["mesh"]
    assert len(m["positions"]) == len(m["normals"]) and len(m["positions"]) % 3 == 0
    assert len(m["indices"]) % 3 == 0 and max(m["indices"]) < len(m["positions"]) // 3
    assert sum(c for _, c in m["face_ranges"]) == len(m["indices"])
    assert doc["bbox"] == pytest.approx([-20, -10, 0, 20, 10, 3], abs=1e-3)
    # 4 straight + 4 fillet arcs on each of top/bottom, 4 vertical edges, 2 holes x (2 circles + seam).
    assert len(doc["edges"]) >= 20
    assert all(len(e) % 3 == 0 and len(e) >= 6 for e in doc["edges"])


def test_policy_violation_is_rejected_without_running(pool: WarmPool) -> None:
    r = run_program("import os\nos.system('touch /tmp/pwned')\n", pool=pool)
    assert not r.ok and r.error is not None
    assert r.error.kind == "policy" and r.error.line == 1
    assert r.workdir is None  # nothing was started
    assert r.error.violations


def test_syntax_error_has_line_number(pool: WarmPool) -> None:
    r = run_program("import cadquery as cq\n\nresult = cq.Workplane(.box(1, 2, 3)\n", pool=pool)
    assert r.error is not None and r.error.kind == "syntax" and r.error.line == 3


def test_runtime_error_maps_to_user_line(pool: WarmPool) -> None:
    code = (
        "import cadquery as cq\n"
        "PARAMS = {'r': (5.0, 0.1, 9.0, 0.1, 'mm', False, 'Fillet')}\n"
        "def build(p):\n"
        "    box = cq.Workplane('XY').box(4, 4, 4)\n"
        "    return box.edges().fillet(p['r'])\n"
        "result = build({k: v[0] for k, v in PARAMS.items()})\n"
    )
    r = run_program(code, pool=pool)
    assert r.error is not None and r.error.kind == "runtime"
    assert r.error.line == 5
    assert r.error.hint and "Fillet" in r.error.hint
    r.cleanup()


def test_infinite_loop_times_out(pool: WarmPool) -> None:
    t0 = time.perf_counter()
    r = run_program("while True:\n    pass\n", pool=pool, timeout_s=1.0)
    assert r.error is not None and r.error.kind == "timeout"
    assert time.perf_counter() - t0 < 10
    r.cleanup()


def test_memory_bomb_hits_memory_limit(pool: WarmPool) -> None:
    r = run_program("x = 'a' * (10 ** 10)\n", pool=pool, mem_mb=256)
    assert r.error is not None and r.error.kind == "memory"
    r.cleanup()


def test_list_memory_bomb(pool: WarmPool) -> None:
    r = run_program("x = [0] * (10 ** 9)\n", pool=pool, mem_mb=256)
    assert r.error is not None and r.error.kind == "memory"
    r.cleanup()


def test_import_os_is_policy() -> None:
    r = run_program("import os\n")
    assert r.error is not None and r.error.kind == "policy"


def test_network_is_blocked_in_child(pool: WarmPool) -> None:
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    port = srv.getsockname()[1]
    try:
        out = probe_network(pool, port=port)
    finally:
        srv.close()
    assert out["isolation"] in ("netns", "socket-patch")
    assert out["blocked"], out
    assert not any(a["connected"] for a in out["attempts"])


def test_no_solid_is_reported(pool: WarmPool) -> None:
    code = "import cadquery as cq\ndef build(p):\n    return cq.Workplane('XY').rect(2, 2)\nresult = build({})\n"
    r = run_program(code, pool=pool)
    assert r.error is not None and r.error.kind == "invalid_solid" and "solid" in r.error.message
    r.cleanup()


def test_two_solids_are_counted(pool: WarmPool) -> None:
    code = (
        "import cadquery as cq\n"
        "def build(p):\n"
        "    return cq.Workplane('XY').box(2, 2, 2).union(cq.Workplane('XY').box(2, 2, 2).translate((5, 0, 0)))\n"
        "result = build({})\n"
    )
    r = run_program(code, pool=pool)
    assert r.ok and r.solid_info is not None and r.solid_info.n_solids == 2
    r.cleanup()


def test_unknown_param_raises(plate_code: str) -> None:
    with pytest.raises(UnknownParamError):
        run_program(plate_code, {"lenght": 3.0})


def test_program_without_params_uses_result(pool: WarmPool) -> None:
    r = run_program("import cadquery as cq\nresult = cq.Workplane('XY').box(3, 4, 5)\n", pool=pool, outputs=())
    assert r.ok and r.solid_info is not None
    assert r.solid_info.volume_mm3 == pytest.approx(60.0)
    r.cleanup()


def test_warm_rebuild_is_fast(pool: WarmPool, plate_code: str) -> None:
    run_program(plate_code, pool=pool, outputs=()).cleanup()
    t0 = time.perf_counter()
    r = run_program(plate_code, {"length": 50.0}, pool=pool, outputs=("stl", "view"))
    elapsed = time.perf_counter() - t0
    r.cleanup()
    assert r.ok
    assert elapsed < 1.5  # typically ~0.3 s; generous for loaded CI machines


@pytest.mark.slow
def test_spawn_mode_fallback(plate_code: str) -> None:
    p = WarmPool(mode="spawn")
    try:
        r = run_program(plate_code, pool=p, outputs=("stl",))
        assert r.ok, r.error
        assert "stl" in r.artifacts
        r.cleanup()
        t = run_program("while True:\n    pass\n", pool=p, timeout_s=1.0)
        assert t.error is not None and t.error.kind == "timeout"
    finally:
        p.close()


def test_interfaces_are_validated_and_measured(pool: WarmPool) -> None:
    code = (
        "import cadquery as cq\n"
        "def build(p):\n"
        "    return cq.Workplane('XY').box(20, 20, 10, centered=(True, True, False)).faces('>Z').workplane().hole(5)\n"
        "def interfaces(p):\n"
        "    return [\n"
        "        {'id': 'bore', 'label': 'bore', 'at': [0, 0, 5], 'axis': [1, 0, 0], 'mates': [4, 5, 6]},\n"
        "        {'id': 'solid', 'label': 'inside', 'at': [8, 8, 5], 'axis': [1, 0, 0], 'mates': [1]},\n"
        "        {'id': 'bad', 'at': [0, 0], 'axis': [1, 0, 0]},\n"
        "        'not a dict',\n"
        "    ]\n"
        "result = build({})\n"
    )
    r = run_program(code, pool=pool, outputs=())
    r.cleanup()
    assert r.ok
    itf = {i["id"]: i for i in (r.features or {})["interfaces"]}
    assert itf["bore"]["gap_mm"] == pytest.approx(5.0, abs=1e-3)
    assert itf["solid"]["gap_mm"] is None and "inside the material" in itf["solid"]["note"]
    assert "bad" not in itf
    assert sum("malformed" in w for w in r.warnings) == 2
