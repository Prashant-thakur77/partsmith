"""Code that runs INSIDE the sandbox child process: isolation, limits, exec of the part program, exports, features.

Never import this module from the API process: it pulls in cadquery/OCCT. The parent talks to it only through
``job.json`` / ``result.json`` files in the job's throwaway working directory (see `sandbox.py`).
"""

from __future__ import annotations

import ast
import contextlib
import json
import math
import os
import resource
import socket
import sys
import time
import traceback
from collections.abc import Callable
from pathlib import Path
from typing import Any

import cadquery as cq
import numpy as np

from services.geom_worker import export
from services.geom_worker.policy import SAFE_BUILTINS
from services.verifier import solid_features

PROGRAM_FILENAME = "part.py"
MESH_TOL_MM = 0.01
MESH_ANG_RAD = 0.1
FILE_SIZE_LIMIT_MB = 256

_HINTS = (
    ("command not done", "fillet", "Fillet failed: the radius is probably too large for an adjacent edge or wall. "
     "Apply fillets last and use a smaller radius."),
    ("command not done", "chamfer", "Chamfer failed: the size is probably larger than an adjacent face."),
    ("No pending wires", "", "A 3-D operation needs a closed 2-D wire first (e.g. .rect(...) or .polyline(...).close())."),
    ("Cannot find a solid", "", "The operation needs a solid on the stack; check .end()/.workplane() calls."),
)  # fmt: skip


# ---------------------------------------------------------------- isolation + limits


def isolate_network() -> str:
    """Cut the child off the network. Returns which mechanism applied ("netns" or "socket-patch").

    A fresh user+network namespace has only a downed loopback, so no packet can leave. When unprivileged namespaces are
    not permitted we replace the socket constructors so any attempt raises before a syscall is made.
    """
    uid, gid = os.getuid(), os.getgid()
    try:
        os.unshare(os.CLONE_NEWUSER | os.CLONE_NEWNET)
    except (AttributeError, OSError):
        pass
    else:
        # Map our own uid/gid so files we create in the job dir keep a valid owner on every kernel (best effort).
        for path, text in (("setgroups", "deny"), ("uid_map", f"{uid} {uid} 1"), ("gid_map", f"{gid} {gid} 1")):
            with contextlib.suppress(OSError):
                Path(f"/proc/self/{path}").write_text(text)
        return "netns"

    def _blocked(*_a: Any, **_k: Any) -> Any:
        raise OSError("network access is disabled in the PartSmith sandbox")

    for name in ("socket", "create_connection", "create_server", "socketpair", "fromfd", "getaddrinfo"):
        if hasattr(socket, name):
            setattr(socket, name, _blocked)
    try:
        import _socket

        _socket.socket = _blocked  # type: ignore[misc,assignment]
    except ImportError:
        pass
    return "socket-patch"


def _vm_bytes() -> int:
    try:
        for line in Path("/proc/self/status").read_text().splitlines():
            if line.startswith("VmSize:"):
                return int(line.split()[1]) * 1024
    except OSError:
        pass
    return int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss) * 1024


def apply_limits(timeout_s: float, mem_mb: int) -> dict[str, int]:
    """CPU seconds, address space (warm baseline + mem_mb), file size, no core dumps, few open files."""
    cpu_used = resource.getrusage(resource.RUSAGE_SELF)
    cpu_s = math.ceil(cpu_used.ru_utime + cpu_used.ru_stime + timeout_s)
    resource.setrlimit(resource.RLIMIT_CPU, (cpu_s, cpu_s + 1))
    as_bytes = _vm_bytes() + mem_mb * 1024 * 1024
    resource.setrlimit(resource.RLIMIT_AS, (as_bytes, as_bytes))
    fsize = FILE_SIZE_LIMIT_MB * 1024 * 1024
    resource.setrlimit(resource.RLIMIT_FSIZE, (fsize, fsize))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    with contextlib.suppress(ValueError, OSError):
        resource.setrlimit(resource.RLIMIT_NOFILE, (256, 256))
    return {"cpu_s": cpu_s, "as_mb": as_bytes // (1024 * 1024), "fsize_mb": FILE_SIZE_LIMIT_MB}


# ---------------------------------------------------------------- restricted exec


def _restricted_import(name: str, globals: Any = None, locals: Any = None, fromlist: Any = (), level: int = 0) -> Any:
    if level == 0 and name == "cadquery":
        return cq
    if level == 0 and name == "math":
        return math
    raise ImportError(f"import of {name!r} is not allowed in part programs")


def _safe_builtins() -> dict[str, Any]:
    import builtins

    out = {n: getattr(builtins, n) for n in SAFE_BUILTINS if hasattr(builtins, n)}
    out["__import__"] = _restricted_import
    return out


def _strip_default_build(tree: ast.Module) -> ast.Module:
    """Drop top-level ``result = build(...)`` so the defaults are not built before the requested params."""
    body = []
    for node in tree.body:
        if (
            isinstance(node, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id == "result" for t in node.targets)
            and isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Name)
            and node.value.func.id == "build"
        ):
            continue
        body.append(node)
    tree.body = body
    return tree


def _user_line(tb: Any) -> int | None:
    line = None
    for fr in traceback.extract_tb(tb):
        if fr.filename == PROGRAM_FILENAME:
            line = fr.lineno
    return line


def _hint(message: str, src_line: str) -> str | None:
    for needle, ctx, hint in _HINTS:
        if needle in message and (not ctx or ctx in src_line):
            return hint
    return None


def _error(kind: str, message: str, line: int | None, code: str) -> dict[str, Any]:
    src = code.splitlines()[line - 1].strip() if line and 0 < line <= len(code.splitlines()) else ""
    return {"kind": kind, "line": line, "message": message[:2000], "source_line": src, "hint": _hint(message, src)}


def _classify(exc: BaseException) -> str:
    text = f"{type(exc).__name__}: {exc}"
    if isinstance(exc, MemoryError) or "OutOfMemory" in text or "bad_alloc" in text:
        return "memory"
    return "runtime"


def run_user_code(code: str, params: dict[str, Any]) -> tuple[Any, dict[str, Any] | None]:
    """Exec the program with restricted builtins and return ``(build_result, error)``."""
    out, err, _ = run_user_code_ns(code, params)
    return out, err


def run_user_code_ns(code: str, params: dict[str, Any]) -> tuple[Any, dict[str, Any] | None, dict[str, Any]]:
    """Like `run_user_code`, also returning the program's namespace (for its optional `interfaces(p)`)."""
    ns: dict[str, Any] = {"__builtins__": _safe_builtins(), "__name__": "part"}
    out, err = _exec(code, params, ns)
    return out, err, ns


def _exec(code: str, params: dict[str, Any], ns: dict[str, Any]) -> tuple[Any, dict[str, Any] | None]:
    try:
        tree = ast.parse(code, filename=PROGRAM_FILENAME)
    except SyntaxError as e:
        return None, _error("syntax", f"SyntaxError: {e.msg}", e.lineno, code)
    has_build = any(isinstance(n, ast.FunctionDef) and n.name == "build" for n in tree.body)
    if has_build:
        tree = _strip_default_build(tree)
    try:
        exec(compile(tree, PROGRAM_FILENAME, "exec"), ns)
        out = ns["build"](dict(params)) if has_build else ns.get("result")
    except BaseException as e:
        if isinstance(e, SystemExit | KeyboardInterrupt):
            return None, _error("runtime", f"{type(e).__name__}", _user_line(e.__traceback__), code)
        kind = _classify(e)
        msg = type(e).__name__ + (f": {e}" if str(e) else "")
        if kind == "memory" and not str(e):
            msg += ": the program needed more memory than the sandbox allows"
        return None, _error(kind, msg, _user_line(e.__traceback__), code)
    if out is None:
        what = "build() returned None" if has_build else "the program defines neither build() nor result"
        return None, _error("runtime", what, None, code)
    return out, None


def _interface_probes(ns: dict[str, Any], params: dict[str, Any], warnings: list[str]) -> list[dict[str, Any]]:
    """The program's declared mating interfaces, `interfaces(p) -> [{id, label, at, axis, mates}]`, validated to plain
    numbers. The program only says WHERE to look; the gap itself is measured on the solid by our code."""
    fn = ns.get("interfaces")
    if not callable(fn):
        return []
    try:
        raw = fn(dict(params))
    except Exception as e:
        warnings.append(f"interfaces() failed: {type(e).__name__}: {e}")
        return []
    out: list[dict[str, Any]] = []
    for item in raw if isinstance(raw, list | tuple) else []:
        try:
            at = [float(x) for x in item["at"]]
            axis = [float(x) for x in item["axis"]]
            mates = sorted(float(m) for m in item.get("mates", []))[:24]
            if len(at) != 3 or len(axis) != 3 or not all(math.isfinite(x) for x in at + axis + mates):
                raise ValueError("at/axis must be 3 finite numbers")
            out.append(
                {
                    "id": str(item["id"])[:40],
                    "label": str(item.get("label", item["id"]))[:80],
                    "at": at,
                    "axis": axis,
                    "mates": mates,
                    "mate_label": str(item.get("mate_label", "part"))[:40],
                }
            )
        except (KeyError, TypeError, ValueError) as e:
            warnings.append(f"interfaces(): ignored a malformed entry ({type(e).__name__}: {e})")
    return out[:8]


def to_shape(obj: Any) -> cq.Shape | None:
    """Workplane / Shape / list of those -> one Shape (Compound when several)."""
    vals: list[Any]
    if isinstance(obj, cq.Workplane):
        vals = list(obj.vals())
    elif isinstance(obj, cq.Shape):
        vals = [obj]
    elif isinstance(obj, list | tuple):
        vals = [v for o in obj for v in (o.vals() if isinstance(o, cq.Workplane) else [o])]
    else:
        return None
    shapes = [v for v in vals if isinstance(v, cq.Shape)]
    if not shapes:
        return None
    if len(shapes) == 1:
        return shapes[0]
    return cq.Compound.makeCompound(shapes)


# ---------------------------------------------------------------- the job


def _versions() -> dict[str, str]:
    try:
        import OCP

        ocp = str(getattr(OCP, "__version__", "unknown"))
    except ImportError:
        ocp = "missing"
    return {"cadquery": str(cq.__version__), "ocp": ocp, "python": sys.version.split()[0]}


def solid_info(shape: cq.Shape) -> dict[str, Any]:
    xmin, ymin, zmin, xmax, ymax, zmax = export.tight_bbox(shape)
    try:
        valid = bool(shape.isValid())
    except Exception:
        valid = False
    return {
        "volume_mm3": float(shape.Volume()),
        "area_mm2": float(shape.Area()),
        "bbox_mm": [xmin, ymin, zmin, xmax, ymax, zmax],
        "size_mm": [xmax - xmin, ymax - ymin, zmax - zmin],
        "valid": valid,
        "n_solids": len(shape.Solids()),
        "n_faces": len(shape.Faces()),
        "n_edges": len(shape.Edges()),
    }


def execute(job: dict[str, Any], workdir: Path) -> dict[str, Any]:
    """Run one part program job. Never raises; failures are reported in the returned dict."""
    code: str = job["code"]
    params: dict[str, Any] = job.get("params") or {}
    outputs = set(job.get("outputs") or ())
    res: dict[str, Any] = {"ok": False, "error": None, "versions": _versions(), "warnings": [], "stage_ms": {}}
    t = time.perf_counter()

    def lap(name: str) -> None:
        nonlocal t
        now = time.perf_counter()
        res["stage_ms"][name] = int((now - t) * 1000)
        t = now

    built, err, ns = run_user_code_ns(code, params)
    lap("build")
    if err is not None:
        res["error"] = err
        return res
    shape = to_shape(built)
    if shape is None:
        res["error"] = _error("runtime", f"build() must return a cq.Workplane with a solid, got {type(built).__name__}",
                              None, code)  # fmt: skip
        return res
    info = solid_info(shape)
    res["solid_info"] = info
    lap("check")
    if info["n_solids"] == 0 or info["volume_mm3"] <= 0:
        res["error"] = _error("invalid_solid", "the program produced no solid with positive volume", None, code)
        return res
    if job.get("passport") and info["valid"]:
        # Trusted post-processing after the program returned: deboss the passport id where it touches nothing
        # measured, re-measure, and undo it when anything changed (passport_mark.py).
        from services.geom_worker import passport_mark

        try:
            shape, res["passport"] = passport_mark.emboss(
                shape, str(job["passport"]), probes=_interface_probes(ns, params, [])
            )
        except Exception as e:
            res["passport"] = {"text": str(job["passport"]), "applied": False,
                               "reason": f"the mark failed: {type(e).__name__}: {e}"[:300]}  # fmt: skip
        info = solid_info(shape)
        res["solid_info"] = info
        lap("passport")

    try:
        verts, tris = export.tessellate(shape, MESH_TOL_MM, MESH_ANG_RAD)
        np.savez(workdir / "mesh.npz", vertices=verts, faces=tris)
        res["mesh_file"] = "mesh.npz"
    except Exception as e:
        res["warnings"].append(f"tessellation failed: {type(e).__name__}: {e}")
    lap("mesh")

    if not info["valid"]:
        res["error"] = _error("invalid_solid", "the solid is not valid (OCCT BRepCheck failed: self-intersection, "
                              "open shell or degenerate face)", None, code)  # fmt: skip
        return res

    artifacts: dict[str, str] = {}
    writers: dict[str, tuple[str, Callable[[Path], None]]] = {
        "stl": ("part.stl", lambda p: export.export_stl(shape, p)),
        "step": ("part.step", lambda p: export.export_step(shape, p)),
        "3mf": ("part.3mf", lambda p: export.export_3mf(shape, p)),
        "view": ("view.json", lambda p: export.write_view_json(shape, p)),
        "glb": ("part.glb", lambda p: export.export_glb(*export.tessellate(shape, MESH_TOL_MM, MESH_ANG_RAD), p)),
    }
    for fmt, (fname, fn) in writers.items():
        if fmt not in outputs:
            continue
        try:
            fn(workdir / fname)
            artifacts[fmt] = fname
        except Exception as e:
            res["warnings"].append(f"{fmt} export failed: {type(e).__name__}: {e}")
        lap(f"export_{fmt}")
    res["artifacts"] = artifacts

    if job.get("features", True):
        try:
            res["features"] = solid_features.measure_solid(shape)
        except Exception as e:
            res["warnings"].append(f"feature measurement failed: {type(e).__name__}: {e}")
        lap("features")
        probes = _interface_probes(ns, params, res["warnings"])
        if probes and isinstance(res.get("features"), dict):
            try:
                res["features"]["interfaces"] = solid_features.measure_interfaces(shape, probes)
            except Exception as e:
                res["warnings"].append(f"interface measurement failed: {type(e).__name__}: {e}")
            lap("interfaces")
    res["ok"] = True
    return res


def probe_network(job: dict[str, Any]) -> dict[str, Any]:
    """Self-test: try to reach a listener the parent opened on localhost, and a public address."""
    attempts = []
    for host, port in [("127.0.0.1", int(job.get("port", 9))), ("1.1.1.1", 53)]:
        try:
            s = socket.create_connection((host, port), timeout=1.0)
            s.close()
            attempts.append({"target": f"{host}:{port}", "connected": True, "error": None})
        except Exception as e:
            attempts.append({"target": f"{host}:{port}", "connected": False, "error": f"{type(e).__name__}: {e}"})
    return {"ok": True, "attempts": attempts, "blocked": not any(a["connected"] for a in attempts)}


def child_main(job: dict[str, Any], *, close_fds: tuple[int, ...] = ()) -> None:
    """Entry point inside the forked/spawned child. Writes result.json; the caller exits the process."""
    workdir = Path(job["workdir"])
    os.chdir(workdir)
    for fd in close_fds:
        with contextlib.suppress(OSError):
            os.close(fd)
    log_fd = os.open(workdir / "log.txt", os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    null_fd = os.open(os.devnull, os.O_RDONLY)
    os.dup2(null_fd, 0)
    os.dup2(log_fd, 1)
    os.dup2(log_fd, 2)
    t0 = time.perf_counter()
    isolation = isolate_network()
    limits = apply_limits(float(job.get("timeout_s", 10)), int(job.get("mem_mb", 1536)))
    try:
        res = probe_network(job) if job.get("op") == "probe_network" else execute(job, workdir)
    except MemoryError:
        res = {"ok": False, "error": {"kind": "memory", "line": None, "message": "MemoryError: out of memory"}}
    res["isolation"] = isolation
    res["limits"] = limits
    res["child_ms"] = int((time.perf_counter() - t0) * 1000)
    tmp = workdir / "result.json.tmp"
    tmp.write_text(json.dumps(res))
    tmp.replace(workdir / "result.json")
    sys.stdout.flush()
    sys.stderr.flush()


def main(argv: list[str]) -> int:
    """Spawn-mode entry: ``python -m services.geom_worker.child <job.json>``."""
    job = json.loads(Path(argv[1]).read_text())
    child_main(job)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
