"""Run the full-loop part of the scale evaluation (eval/SCALE_PLAN.md) with the bench's own `run_task` and scoring.

    PROVIDER_MODE=live uv run python -m eval.scale_run [--dry-run]

Runs are stored under eval/runs/live_scale/<suite>/<config>/<sample>/, apart from the frozen bench in eval/runs/live. The
number of concurrent jobs is read from var/scale_data/concurrency.txt on every loop, so it can be tuned while running.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import time
from concurrent.futures import FIRST_COMPLETED, Future, ProcessPoolExecutor, wait
from concurrent.futures.process import BrokenProcessPool
from multiprocessing import get_context
from pathlib import Path
from typing import Any

from . import run as bench

ROOT = bench.REPO / "var" / "scale_data"
OUT = bench.RUNS_DIR / "live_scale"
SEED = 20261105
CAP_USD = 86.0
EST_USD_PER_RUN = 0.22


def _understood(score: dict[str, Any], out_dir: Path) -> None:
    """What Muse Spark said the part was, from the PartSpec this run logged."""
    import gzip

    from services.common import blobs

    path = out_dir / "run.jsonl.gz"
    if not path.exists():
        return
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        events = [json.loads(line) for line in fh]
    sha = next((e.get("sha") for e in events if e.get("t") == "artifact" and e.get("kind") == "partspec"), None)
    if not sha or not blobs.exists(sha):
        return
    spec = json.loads(blobs.get(sha))
    score["understood"] = {
        "family": spec.get("family"),
        "broken_region": bool(spec.get("broken_region")),
        "title": spec.get("title"),
        "n_features": len(spec.get("features") or []),
        "refusal": spec.get("refusal"),
    }


def run_one(task: bench.Task, scale_suite: str) -> dict[str, Any]:
    score = bench.run_task(task)
    score["scale_suite"] = scale_suite
    score["tree"] = os.environ.get("SCALE_TREE", "")
    try:
        _understood(score, Path(task.out_dir))
    except Exception as exc:  # the score stands without the extra note
        score["understood_error"] = f"{type(exc).__name__}: {exc}"[:200]
    (Path(task.out_dir) / "score.json").write_text(json.dumps(score, indent=1))
    return score


def tasks() -> list[tuple[bench.Task, str]]:
    man = json.loads((ROOT / "manifest.json").read_text())
    rows = [r for r in man["samples"] if not r.get("error")]
    by_suite: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        by_suite.setdefault(r["suite"], []).append(r)
    out: list[tuple[bench.Task, str]] = []

    def add(scale: str, suite: str, cfg: str, r: dict[str, Any], kind: str) -> None:
        sdir = ROOT / (r.get("dir") or f"{scale_alias(scale)}/{r['id']}")
        t = bench.Task(
            suite,
            cfg,
            r["id"],
            str(sdir),
            "held_out",
            kind,
            "",
            r.get("preset", ""),
            None,
            "live",
            str(OUT / scale / cfg / r["id"]),
        )
        out.append((t, scale))

    syn = by_suite.get("synthetic", [])
    for r in syn:
        add("synthetic", "synthetic", "PS", r, "template")
    for r in random.Random(SEED + 1).sample(syn, min(100, len(syn))):
        add("synthetic", "synthetic", "B1", r, "template")
    for r in by_suite.get("broken", []):
        add("broken", "synthetic", "PS", r, "template")
    for r in by_suite.get("reference_objects", []):
        add("reference_objects", "reference_objects", "PS", r, "reference_object")
    for scale in ("control_top", "control_side"):
        for r in by_suite.get(scale, []):
            add(scale, "control", "PS", r, "control")
    for r in by_suite.get("redteam", []):
        add("redteam", "redteam", "PS", r, "redteam")
    random.Random(SEED).shuffle(out)
    return out


def scale_alias(scale: str) -> str:
    return scale


def stages_usd() -> float:
    path = OUT / "stages" / "usd.json"
    return sum(json.loads(path.read_text()).values()) if path.exists() else 0.0


def concurrency(default: int) -> int:
    try:
        return max(0, int((ROOT / "concurrency.txt").read_text().strip()))
    except (OSError, ValueError):
        return default


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="print the task counts and stop")
    ap.add_argument("--max-workers", type=int, default=24)
    ap.add_argument("--stop-epoch", type=float, default=0.0, help="no new run starts after this time")
    a = ap.parse_args()
    todo = tasks()
    counts: dict[str, int] = {}
    for t, scale in todo:
        counts[f"{scale}/{t.config}"] = counts.get(f"{scale}/{t.config}", 0) + 1
    print(json.dumps(counts))
    if a.dry_run:
        return 0
    env = {"PARTSMITH_HOME": str(bench.BENCH_HOME), "PARTSMITH_BUY_LOOKUP": "0"}
    log_path = ROOT / "progress.log"
    spent, done = 0.0, 0
    queue = [(t, s) for t, s in todo if not (Path(t.out_dir) / "score.json").exists()]
    for t, _ in todo:
        p = Path(t.out_dir) / "score.json"
        if p.exists():
            spent += float(json.loads(p.read_text()).get("usd") or 0)
            done += 1
    ctx = get_context("spawn")
    ex = ProcessPoolExecutor(max_workers=a.max_workers, mp_context=ctx, initializer=bench._init_worker, initargs=(env,))
    inflight: dict[Future[dict[str, Any]], tuple[bench.Task, str]] = {}
    stop_reason = ""
    t0 = time.time()
    while queue or inflight:
        limit = concurrency(8)
        if not stop_reason:
            if a.stop_epoch and time.time() >= a.stop_epoch:
                stop_reason = "time"
            elif spent + stages_usd() + EST_USD_PER_RUN * len(inflight) >= CAP_USD:
                stop_reason = "spend"
        while queue and len(inflight) < limit and not stop_reason:
            t, s = queue.pop(0)
            inflight[ex.submit(run_one, t, s)] = (t, s)
        if stop_reason and not inflight:
            break
        if not inflight:
            time.sleep(5)
            continue
        finished, _ = wait(list(inflight), timeout=20, return_when=FIRST_COMPLETED)
        for f in finished:
            t, s = inflight.pop(f)
            try:
                r = f.result()
            except BrokenProcessPool as exc:
                r = {"usd": 0, "status": "crashed", "failure": str(exc)[:200]}
                score = {"suite": t.suite, "scale_suite": s, "config": t.config, "sample_id": t.sample_id, "split": "held_out", "kind": t.kind,
                         "preset": t.preset, "mode": "live", "gt_source": bench.GROUND_TRUTH[t.suite], "status": "crashed", "verified": False,
                         "failure": "worker process died (out of memory or killed)"}  # fmt: skip
                Path(t.out_dir).mkdir(parents=True, exist_ok=True)
                (Path(t.out_dir) / "score.json").write_text(json.dumps(score, indent=1))
                ex = ProcessPoolExecutor(
                    max_workers=a.max_workers, mp_context=ctx, initializer=bench._init_worker, initargs=(env,)
                )
            spent += float(r.get("usd") or 0)
            done += 1
            with log_path.open("a") as fh:
                fh.write(f"{time.strftime('%H:%M:%S')} done={done} left={len(queue)} inflight={len(inflight)} spent={spent:.2f} "
                         f"stages={stages_usd():.2f} {s}/{t.config} {t.sample_id} status={r.get('status')} verified={r.get('verified')} "
                         f"pass={r.get('pass_0_5')} wall={r.get('wall_s')} usd={r.get('usd')}\n")  # fmt: skip
    with log_path.open("a") as fh:
        fh.write(
            f"END reason={stop_reason or 'all done'} done={done} not_started={len(queue)} spent={spent:.2f} wall={time.time() - t0:.0f}\n"
        )
    (ROOT / "run_end.json").write_text(
        json.dumps(
            {"stop_reason": stop_reason or "all done", "done": done, "not_started": len(queue), "runs_usd": spent}
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
