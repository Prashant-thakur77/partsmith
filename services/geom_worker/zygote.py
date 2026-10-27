"""Warm worker ("zygote"): imports cadquery once, then forks one fresh child per job.

Protocol (one JSON object per line): the parent writes a job on stdin, the zygote answers on its private stdout with
``{"status": "exited"|"signaled"|"timeout", "exit_code", "signal", "wall_ms", "maxrss_kb"}``. The child itself writes
``result.json`` into the job's working directory. Start with ``python -m services.geom_worker.zygote``.
"""

from __future__ import annotations

import contextlib
import json
import os
import select
import signal
import sys
import time
from typing import Any

WALL_FACTOR = 1.5
WALL_GRACE_S = 2.0


def _warm_up() -> None:
    """Touch the code paths a job uses so the first fork is as fast as the rest."""
    import tempfile
    from pathlib import Path

    import cadquery as cq

    from services.geom_worker import child, export
    from services.verifier import solid_features

    # No booleans or parallel meshing here: they start OCCT's thread pool, and a forked child would inherit the pool
    # object without its threads and deadlock on first use. Children start their own pool when they need one.
    wp = cq.Workplane("XY").box(10, 8, 3).edges("|Z").fillet(1)
    shape = child.to_shape(wp)
    assert shape is not None
    with tempfile.TemporaryDirectory() as d:
        export.export_stl(shape, Path(d) / "w.stl")
        export.export_step(shape, Path(d) / "w.step")
        export.view_json(shape)
    solid_features.measure_solid(shape)


def _wait(pid: int, deadline_s: float) -> tuple[str, int, int, int]:
    """Wait for the child; kill it at the deadline. Returns (status, exit_code, signal, maxrss_kb)."""
    try:
        pidfd: int | None = os.pidfd_open(pid)
    except (AttributeError, OSError):
        pidfd = None
    end = time.monotonic() + deadline_s
    timed_out = False
    while True:
        done, status, usage = os.wait4(pid, os.WNOHANG)
        if done:
            break
        remaining = end - time.monotonic()
        if remaining <= 0:
            timed_out = True
            with contextlib.suppress(ProcessLookupError):
                os.kill(pid, signal.SIGKILL)
            _, status, usage = os.wait4(pid, 0)
            break
        if pidfd is not None:
            select.select([pidfd], [], [], min(remaining, 1.0))
        else:
            time.sleep(min(remaining, 0.005))
    if pidfd is not None:
        os.close(pidfd)
    rss = int(usage.ru_maxrss)
    if timed_out:
        return "timeout", -1, signal.SIGKILL, rss
    if os.WIFSIGNALED(status):
        return "signaled", -1, os.WTERMSIG(status), rss
    return "exited", os.WEXITSTATUS(status), 0, rss


def run_forked(job: dict[str, Any], proto_fds: tuple[int, ...]) -> dict[str, Any]:
    from services.geom_worker import child

    t0 = time.perf_counter()
    pid = os.fork()
    if pid == 0:  # child
        code = 0
        try:
            signal.signal(signal.SIGTERM, signal.SIG_DFL)
            child.child_main(job, close_fds=proto_fds)
        except BaseException:
            code = 70
        os._exit(code)
    deadline = float(job.get("timeout_s", 10)) * WALL_FACTOR + WALL_GRACE_S
    status, exit_code, sig, rss = _wait(pid, deadline)
    return {
        "status": status,
        "exit_code": exit_code,
        "signal": sig,
        "wall_ms": int((time.perf_counter() - t0) * 1000),
        "maxrss_kb": rss,
    }


def main() -> int:
    # Private protocol channel: keep the real stdout for replies, point fd 1 at stderr so stray prints can't corrupt it.
    proto_out = os.fdopen(os.dup(1), "w", buffering=1)
    os.dup2(2, 1)
    t0 = time.perf_counter()
    _warm_up()
    threads = len(os.listdir("/proc/self/task")) if os.path.isdir("/proc/self/task") else -1
    hello = {"ready": True, "pid": os.getpid(), "warm_ms": int((time.perf_counter() - t0) * 1000), "threads": threads}
    proto_out.write(json.dumps(hello))
    proto_out.write("\n")
    proto_out.flush()
    fds = (0, proto_out.fileno())
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            job = json.loads(line)
            reply = run_forked(job, fds)
        except Exception as e:
            reply = {"status": "zygote_error", "error": f"{type(e).__name__}: {e}"}
        proto_out.write(json.dumps(reply) + "\n")
        proto_out.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
