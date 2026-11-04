"""Run untrusted part programs safely.

Two layers:

1. ``check_code`` — AST allowlist (`policy.py`), applied before anything runs. Rejected code never reaches a process.
2. ``run_program`` — the program runs in a CHILD process with restricted builtins, a fresh temp working directory,
   rlimits (CPU seconds, address space = warm baseline + ``mem_mb``, file size 256 MB, no core dumps) and no network:
   a new user+network namespace when the kernel allows it (``isolation="netns"``), otherwise the socket constructors
   are replaced so any attempt raises (``isolation="socket-patch"``).

A ``WarmPool`` keeps worker processes that have already imported cadquery; each job is a ``fork()`` of one of them, so
a knob rebuild costs the build itself, not the ~1 s OCCT import. Where ``fork`` is unavailable the pool spawns a fresh
interpreter per job (slower, same limits). This module never imports cadquery: the API process stays clean.
"""

from __future__ import annotations

import atexit
import json
import os
import queue
import select
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import warnings
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import numpy as np
import numpy.typing as npt

from services.common.paths import REPO_ROOT
from services.geom_worker.policy import Violation, check_code
from services.geom_worker.program import ProgramError, clamp, code_sha, parse_params

__all__ = [
    "ErrorKind",
    "ExecError",
    "ExecResult",
    "Mesh",
    "SolidInfo",
    "Violation",
    "WarmPool",
    "check_code",
    "default_pool",
    "run_program",
]

ErrorKind = Literal["syntax", "policy", "runtime", "timeout", "memory", "invalid_solid"]
OUTPUT_FORMATS = ("stl", "step", "3mf", "view", "glb")
_READY_TIMEOUT_S = 120.0


@dataclass(frozen=True)
class ExecError:
    kind: ErrorKind
    message: str
    line: int | None = None
    source_line: str = ""
    hint: str | None = None
    violations: tuple[Violation, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"kind": self.kind, "line": self.line, "message": self.message}
        if self.source_line:
            d["source_line"] = self.source_line
        if self.hint:
            d["hint"] = self.hint
        if self.violations:
            d["violations"] = [v.to_dict() for v in self.violations]
        return d

    def short(self) -> str:
        where = f"line {self.line}: " if self.line and not self.message.startswith(f"line {self.line}:") else ""
        return f"{self.kind} error, {where}{self.message}"


@dataclass(frozen=True)
class Mesh:
    """Triangle mesh in mm (CAD frame), vertices merged so topology checks work."""

    vertices: npt.NDArray[np.float64]
    faces: npt.NDArray[np.int64]

    def trimesh(self) -> Any:
        import trimesh

        return trimesh.Trimesh(vertices=self.vertices, faces=self.faces, process=False)


@dataclass(frozen=True)
class SolidInfo:
    volume_mm3: float
    area_mm2: float
    bbox_mm: tuple[float, float, float, float, float, float]
    valid: bool
    n_solids: int
    n_faces: int
    n_edges: int

    @property
    def size_mm(self) -> tuple[float, float, float]:
        b = self.bbox_mm
        return (b[3] - b[0], b[4] - b[1], b[5] - b[2])

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> SolidInfo:
        b = [float(x) for x in d["bbox_mm"]]
        return cls(
            volume_mm3=float(d["volume_mm3"]),
            area_mm2=float(d["area_mm2"]),
            bbox_mm=(b[0], b[1], b[2], b[3], b[4], b[5]),
            valid=bool(d["valid"]),
            n_solids=int(d["n_solids"]),
            n_faces=int(d["n_faces"]),
            n_edges=int(d["n_edges"]),
        )


@dataclass
class ExecResult:
    ok: bool
    error: ExecError | None
    params_used: dict[str, float]
    code_sha: str
    artifacts: dict[str, Path] = field(default_factory=dict)
    mesh: Mesh | None = None
    solid_info: SolidInfo | None = None
    features: dict[str, Any] | None = None
    ms: int = 0
    isolation: str = "none"
    versions: dict[str, str] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    stage_ms: dict[str, int] = field(default_factory=dict)
    log: str = ""
    passport: dict[str, Any] | None = None  # the passport mark's report (passport_mark.py) when one was asked for
    workdir: Path | None = None
    clamped: dict[str, float] = field(default_factory=dict)

    def error_dict(self) -> dict[str, Any] | None:
        return self.error.to_dict() if self.error else None

    def cleanup(self) -> None:
        """Delete the job's working directory (artifacts included). Copy what you need first."""
        if self.workdir is not None and self.workdir.exists():
            shutil.rmtree(self.workdir, ignore_errors=True)
        self.artifacts = {}

    def __enter__(self) -> ExecResult:
        return self

    def __exit__(self, *exc: object) -> None:
        self.cleanup()


# ------------------------------------------------------------------------------------------- worker processes


def _child_env() -> dict[str, str]:
    env = dict(os.environ)
    py_path = [str(REPO_ROOT), str(REPO_ROOT / "packages" / "schemas")]
    if env.get("PYTHONPATH"):
        py_path.append(env["PYTHONPATH"])
    env["PYTHONPATH"] = os.pathsep.join(py_path)
    for k in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
        env[k] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


class _Zygote:
    """One warm worker process. Not thread-safe; the pool hands it to one caller at a time."""

    def __init__(self) -> None:
        self.proc = subprocess.Popen(
            [sys.executable, "-m", "services.geom_worker.zygote"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            cwd=str(REPO_ROOT),
            env=_child_env(),
            text=True,
            bufsize=1,
        )
        hello = self._readline(_READY_TIMEOUT_S)
        info = json.loads(hello) if hello else {}
        if not info.get("ready"):
            self.close()
            raise RuntimeError("geometry worker failed to start (cadquery import failed?)")
        self.threads = int(info.get("threads", -1))
        if self.threads > 1:  # forking a multi-threaded process can deadlock the child; the timeout still applies
            warnings.warn(f"geometry worker has {self.threads} threads before fork", RuntimeWarning, stacklevel=2)

    def _readline(self, timeout_s: float) -> str | None:
        assert self.proc.stdout is not None
        r, _, _ = select.select([self.proc.stdout], [], [], timeout_s)
        if not r:
            return None
        line = self.proc.stdout.readline()
        return line or None

    def alive(self) -> bool:
        return self.proc.poll() is None

    def run(self, job: dict[str, Any]) -> dict[str, Any]:
        assert self.proc.stdin is not None
        self.proc.stdin.write(json.dumps(job) + "\n")
        self.proc.stdin.flush()
        wait_s = float(job.get("timeout_s", 10)) * 2 + 30
        line = self._readline(wait_s)
        if line is None:
            raise RuntimeError("geometry worker did not answer")
        reply: dict[str, Any] = json.loads(line)
        return reply

    def close(self) -> None:
        try:
            if self.proc.stdin:
                self.proc.stdin.close()
            self.proc.wait(timeout=2)
        except (OSError, subprocess.TimeoutExpired):
            self.proc.kill()
            self.proc.wait()


def _run_spawned(job: dict[str, Any]) -> dict[str, Any]:
    """Fallback without fork: a fresh interpreter per job (imports cadquery every time)."""
    workdir = Path(job["workdir"])
    job_file = workdir / "job.json"
    job_file.write_text(json.dumps(job))
    t0 = time.perf_counter()
    # The child imports cadquery before the limits apply, so allow the import time on top of the job's budget.
    deadline = float(job.get("timeout_s", 10)) * 1.5 + 30
    proc = subprocess.Popen(
        [sys.executable, "-m", "services.geom_worker.child", str(job_file)],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        cwd=str(workdir),
        env=_child_env(),
    )
    try:
        rc = proc.wait(timeout=deadline)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
        wall_ms = int((time.perf_counter() - t0) * 1000)
        return {"status": "timeout", "exit_code": -1, "signal": int(signal.SIGKILL), "wall_ms": wall_ms}
    wall_ms = int((time.perf_counter() - t0) * 1000)
    if rc < 0:
        return {"status": "signaled", "exit_code": -1, "signal": -rc, "wall_ms": wall_ms}
    return {"status": "exited", "exit_code": rc, "signal": 0, "wall_ms": wall_ms}


class WarmPool:
    """Pool of warm workers. ``mode="fork"`` (default where available) forks a fresh child per job from a process that
    already imported cadquery; ``mode="spawn"`` starts a new interpreter per job. Thread-safe."""

    def __init__(self, size: int = 1, mode: Literal["fork", "spawn"] | None = None) -> None:
        if mode is None:
            env_mode = os.environ.get("PARTSMITH_SANDBOX_MODE", "")
            mode = "spawn" if env_mode == "spawn" or not hasattr(os, "fork") else "fork"
        self.mode: Literal["fork", "spawn"] = mode
        self.size = max(1, size)
        self._idle: queue.Queue[_Zygote | None] = queue.Queue()
        self._all: list[_Zygote] = []
        self._lock = threading.Lock()
        self._closed = False
        for _ in range(self.size):
            self._idle.put(None)  # started lazily on first use

    def warm(self) -> None:
        """Start every worker now (blocks until each has imported cadquery and warmed up)."""
        if self.mode != "fork":
            return
        held = [self._idle.get() for _ in range(self.size)]
        try:
            held = [z if z is not None and z.alive() else self._start() for z in held]
        finally:
            for z in held:
                self._idle.put(z)

    def _start(self) -> _Zygote:
        z = _Zygote()
        with self._lock:
            self._all.append(z)
        return z

    def run_job(self, job: dict[str, Any]) -> dict[str, Any]:
        if self._closed:
            raise RuntimeError("pool is closed")
        if self.mode == "spawn":
            return _run_spawned(job)
        z = self._idle.get()
        try:
            if z is None or not z.alive():
                z = self._start()
            try:
                return z.run(job)
            except (RuntimeError, OSError, ValueError) as e:
                z.close()
                z = None
                return {"status": "zygote_error", "error": f"{type(e).__name__}: {e}"}
        finally:
            self._idle.put(z)

    def close(self) -> None:
        self._closed = True
        with self._lock:
            for z in self._all:
                z.close()
            self._all.clear()


_DEFAULT_POOL: WarmPool | None = None
_DEFAULT_LOCK = threading.Lock()


def default_pool() -> WarmPool:
    """Process-wide pool (size from PARTSMITH_GEOM_WORKERS, default 2), closed at exit."""
    global _DEFAULT_POOL
    with _DEFAULT_LOCK:
        if _DEFAULT_POOL is None:
            _DEFAULT_POOL = WarmPool(size=int(os.environ.get("PARTSMITH_GEOM_WORKERS", "2")))
            atexit.register(_DEFAULT_POOL.close)
        return _DEFAULT_POOL


# ------------------------------------------------------------------------------------------- public API


def _fail(kind: ErrorKind, message: str, *, line: int | None = None, **kw: Any) -> ExecError:
    return ExecError(kind=kind, message=message, line=line, **kw)


def _classify_crash(reply: Mapping[str, Any], timeout_s: float, mem_mb: int) -> ExecError:
    status = reply.get("status")
    sig = int(reply.get("signal") or 0)
    rss_mb = int(reply.get("maxrss_kb") or 0) / 1024
    timeout = _fail("timeout", f"the program ran longer than {timeout_s:g} s (CPU/wall limit)")
    memory = _fail("memory", f"the program ran out of memory (peak {rss_mb:.0f} MB, limit {mem_mb} MB)")
    if status == "timeout":
        return timeout
    if status == "signaled":
        if sig == signal.SIGXCPU:
            return timeout
        if rss_mb > 0.8 * mem_mb:
            return memory
        if sig == signal.SIGKILL:  # hard CPU limit
            return timeout
        try:
            name = signal.Signals(sig).name
        except ValueError:
            name = str(sig)
        return _fail("runtime", f"the CAD kernel crashed ({name})")
    if status == "zygote_error":
        return _fail("runtime", f"geometry worker error: {reply.get('error')}")
    return _fail("runtime", f"the worker exited without a result (exit code {reply.get('exit_code')})")


def run_program(
    code: str,
    params: Mapping[str, float] | None = None,
    *,
    timeout_s: float = 10.0,
    mem_mb: int = 1536,
    outputs: Iterable[str] = ("stl", "step", "view"),
    features: bool = True,
    pool: WarmPool | None = None,
    passport: str | None = None,
) -> ExecResult:
    """Check, then execute a part program in the sandbox and collect its mesh, solid facts, features and artifacts.

    ``passport``: deboss this id into the solid after the program ran (trusted code in the child, never the program;
    see `passport_mark.py`); the report comes back as ``ExecResult.passport``.

    ``params`` are clamped to the PARAMS ranges (missing ones take defaults). Unknown names raise
    ``program.UnknownParamError``. Errors never raise: they come back as ``ExecResult.error`` with a kind and the
    user-code line number. Call ``cleanup()`` (or use ``with``) when the artifacts are no longer needed.
    """
    t0 = time.perf_counter()
    sha = code_sha(code)
    outs = [o for o in outputs if o in OUTPUT_FORMATS]

    def done(err: ExecError, params_used: dict[str, float] | None = None) -> ExecResult:
        return ExecResult(
            ok=False, error=err, params_used=params_used or {}, code_sha=sha, ms=int((time.perf_counter() - t0) * 1000)
        )

    violations = check_code(code)
    if violations:
        first = violations[0]
        if first.kind == "syntax":
            return done(_fail("syntax", first.message, line=first.line, violations=tuple(violations)))
        return done(
            _fail(
                "policy",
                "; ".join(f"line {v.line}: {v.message}" for v in violations[:5])
                + (f" (+{len(violations) - 5} more)" if len(violations) > 5 else ""),
                line=first.line,
                violations=tuple(violations),
            )
        )
    try:
        specs = parse_params(code)
    except ProgramError as e:
        if params or "PARAMS" in code:
            return done(_fail("policy", f"PARAMS: {e.message}", line=e.line))
        specs = []
    params_used, changed = clamp(params or {}, specs)

    workdir = Path(tempfile.mkdtemp(prefix="partsmith-exec-"))
    job = {
        "op": "run",
        "code": code,
        "params": params_used,
        "outputs": outs,
        "features": features,
        "timeout_s": float(timeout_s),
        "mem_mb": int(mem_mb),
        "workdir": str(workdir),
    }
    if passport:
        job["passport"] = passport
    reply = (pool or default_pool()).run_job(job)
    result_file = workdir / "result.json"
    log_file = workdir / "log.txt"
    log = log_file.read_text(errors="replace")[-4000:] if log_file.exists() else ""
    base = ExecResult(
        ok=False, error=None, params_used=params_used, code_sha=sha, workdir=workdir, log=log, clamped=changed
    )
    if not result_file.exists():
        base.error = _classify_crash(reply, timeout_s, mem_mb)
        base.ms = int((time.perf_counter() - t0) * 1000)
        return base

    res = json.loads(result_file.read_text())
    if res.get("error"):
        err = res["error"]
        base.error = ExecError(
            kind=err.get("kind", "runtime"),
            message=err.get("message", ""),
            line=err.get("line"),
            source_line=err.get("source_line") or "",
            hint=err.get("hint"),
        )
    base.ok = bool(res.get("ok")) and base.error is None
    base.isolation = res.get("isolation", "none")
    base.versions = dict(res.get("versions") or {})
    base.warnings = list(res.get("warnings") or [])
    base.stage_ms = dict(res.get("stage_ms") or {})
    if res.get("solid_info"):
        base.solid_info = SolidInfo.from_dict(res["solid_info"])
    base.features = res.get("features")
    base.passport = res.get("passport")
    base.artifacts = {fmt: workdir / name for fmt, name in (res.get("artifacts") or {}).items()}
    if res.get("mesh_file") and (workdir / res["mesh_file"]).exists():
        base.mesh = _load_mesh(workdir / res["mesh_file"])
    base.ms = int((time.perf_counter() - t0) * 1000)
    return base


def _load_mesh(path: Path) -> Mesh:
    import trimesh

    with np.load(path) as z:
        v, f = z["vertices"], z["faces"]
    tm = trimesh.Trimesh(vertices=v, faces=f, process=True)
    return Mesh(vertices=np.asarray(tm.vertices, dtype=np.float64), faces=np.asarray(tm.faces, dtype=np.int64))


def probe_network(pool: WarmPool | None = None, port: int = 9) -> dict[str, Any]:
    """Self-test of the network isolation: the child tries to reach ``127.0.0.1:port`` and a public address."""
    workdir = Path(tempfile.mkdtemp(prefix="partsmith-probe-"))
    try:
        reply = (pool or default_pool()).run_job(
            {"op": "probe_network", "port": port, "timeout_s": 5, "mem_mb": 256, "workdir": str(workdir)}
        )
        f = workdir / "result.json"
        out: dict[str, Any] = json.loads(f.read_text()) if f.exists() else {"ok": False, "reply": reply}
        return out
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
