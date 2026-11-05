"""After the colour prompt: the same photos through the full loop again, against their runs from the scale evaluation.

Written before the live run. `eval/SCALE_PLAN.md` measured the product with SAM's prompt as "plastic part", which rarely
returned a mask, so the threshold segmenter measured most runs. `eval/sam_prompts.py` then measured masks alone. Neither
says what the fix does to a whole job: SAM's mask is worse on holes, and the fix loop may or may not recover that.

Samples: 20 chosen by `random.Random(20261106)` from the 144 `synthetic/PS` runs in `eval/runs/live_scale`, chosen without
looking at outcomes. Photos are re-rendered from each sample's template, preset and seed; a sample whose ground truth does
not match its stored run is reported and not run. Scored by the bench's own `run_task`.

Reported, whatever comes back: which mask measured each run, median error per size, pass@0.5, verified, verified but off,
and exact McNemar on pass@0.5. The fix is called better or worse only at p < 0.05, and with 20 pairs a small difference will
not reach that, so a small difference is reported as no measured difference. No product change follows from this run.

Limits fixed now: each sample runs once, $8 of model calls, no new run after the stop time. Unfinished samples are reported
as not run. All photos are rendered, so this says nothing about real phone photos.

What changed once it ran: the first attempt ran in an environment built without `meta-sam-parser`, so every SAM call failed,
the threshold measured all 19 runs that reached measuring, and it tested nothing about the fix. It cost $5.03 and is not
stored or counted. `run` now stops before any model call if the parser is missing, and the samples were run again in the same
seeded order, with a new stop time.

    uv run python -m eval.after_fix render
    PROVIDER_MODE=live uv run python -m eval.after_fix run --stop-epoch <unix time> --out <dir>
    uv run python -m eval.after_fix report --out <dir>     # eval/reports/latest/after_fix.json from the stored runs
"""

from __future__ import annotations

import argparse
import gzip
import json
import random
import re
import statistics
import time
from collections.abc import Mapping, Sequence
from concurrent.futures import FIRST_COMPLETED, Future, ProcessPoolExecutor, wait
from multiprocessing import get_context
from pathlib import Path
from typing import Any

from . import run as bench
from . import stats

SEED = 20261106
N = 20
CAP_USD = 8.0
BEFORE = bench.RUNS_DIR / "live_scale" / "synthetic" / "PS"
AFTER = bench.RUNS_DIR / "live_after_fix"
DATA = bench.REPO / "var" / "after_fix" / "synthetic"
REPORT = bench.REPO / "eval" / "reports" / "latest" / "after_fix.json"


def samples() -> list[str]:
    ids = sorted(p.parent.name for p in BEFORE.glob("*/score.json"))
    return random.Random(SEED).sample(ids, min(N, len(ids)))


def _score(root: Path, sid: str) -> dict[str, Any] | None:
    path = root / sid / "score.json"
    return json.loads(path.read_text()) if path.exists() else None


def render_one(sid: str) -> dict[str, Any]:
    """Render one sample from its id and check its ground truth against the stored run."""
    import yaml

    from tools.synth import generate_sample
    from tools.synth.dataset import SampleSpec

    stored = _score(BEFORE, sid) or {}
    m = re.search(r"-s(\d+)$", sid)
    if not m:
        return {"id": sid, "ok": False, "why": "no seed in id"}
    preset = str(stored["preset"])
    name = sid.removeprefix("syn-")[: m.start() - len("syn-")].removesuffix(f"-{preset}").replace("-", "_")
    spec = SampleSpec("template", name, preset, size=(3000, 2250), jpeg_quality=90)
    folder = generate_sample(spec, DATA, seed=int(m.group(1)))
    if folder.name != sid:
        return {"id": sid, "ok": False, "why": f"rendered as {folder.name}"}
    gt = yaml.safe_load((folder / "gt.yaml").read_text())
    text = json.dumps(gt)
    wanted = [d["gt_mm"] for d in stored.get("dims") or [] if d.get("gt_mm") is not None]
    missing = [v for v in wanted if str(v) not in text]
    return {"id": sid, "ok": not missing, "why": f"ground truth differs: {missing}" if missing else ""}


def _init(env: Mapping[str, str]) -> None:
    bench._init_worker(env)


def run_one(task: bench.Task) -> dict[str, Any]:
    score = bench.run_task(task)
    (Path(task.out_dir) / "score.json").write_text(json.dumps(score, indent=1))
    return score


def run(stop_epoch: float, out: Path, workers: int) -> int:
    import importlib.util

    if importlib.util.find_spec("meta_sam_parser") is None:
        raise SystemExit("meta-sam-parser is not installed, so SAM cannot answer: uv sync --all-extras")
    ok = json.loads((DATA.parent / "rendered.json").read_text())
    todo = []
    for row in ok:
        stored = _score(BEFORE, row["id"]) or {}
        if row["ok"] and not (out / row["id"] / "score.json").exists():
            todo.append(
                bench.Task(
                    "synthetic",
                    "PS",
                    row["id"],
                    str(DATA / row["id"]),
                    "held_out",
                    "template",
                    "",
                    str(stored.get("preset") or ""),
                    None,
                    "live",
                    str(out / row["id"]),
                )
            )
    env = {"PARTSMITH_HOME": str(DATA.parent / "home"), "PARTSMITH_BUY_LOOKUP": "0"}
    ex = ProcessPoolExecutor(max_workers=workers, mp_context=get_context("spawn"), initializer=_init, initargs=(env,))
    inflight: dict[Future[dict[str, Any]], bench.Task] = {}
    spent = 0.0
    while todo or inflight:
        can_start = time.time() < stop_epoch and spent + 0.3 * len(inflight) < CAP_USD
        while todo and len(inflight) < workers and can_start:
            t = todo.pop(0)
            inflight[ex.submit(run_one, t)] = t
        if not inflight:
            break
        finished, _ = wait(list(inflight), timeout=20, return_when=FIRST_COMPLETED)
        for f in finished:
            t = inflight.pop(f)
            try:
                r = f.result()
            except Exception as exc:  # stays in the table as a failed run
                r = {"status": "crashed", "failure": f"{type(exc).__name__}: {exc}"[:200], "usd": 0, "verified": False}
                Path(t.out_dir).mkdir(parents=True, exist_ok=True)
                (Path(t.out_dir) / "score.json").write_text(json.dumps({**r, "sample_id": t.sample_id}, indent=1))
            spent += float(r.get("usd") or 0)
            print(f"{time.strftime('%H:%M:%S')} {t.sample_id} {r.get('status')} verified={r.get('verified')} "
                  f"pass={r.get('pass_0_5')} usd={r.get('usd')} spent={spent:.2f} left={len(todo)}", flush=True)  # fmt: skip
    print("not started:", [t.sample_id for t in todo], flush=True)
    return 0


def mask_of(run_dir: Path) -> str:
    """The segmenter this run logged as measuring, from its own "Measured ... (mask: x)" line."""
    path = run_dir / "run.jsonl.gz"
    if not path.exists():
        return "no log"
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        for line in fh:
            e = json.loads(line)
            text = str(e.get("msg") or e.get("label") or "")
            m = re.search(r"\(mask: ([^)]+)\)", text)
            if m and text.startswith("Measured"):
                return m.group(1)
    return "no measure line"


def _side(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    errors = [float(d["error_mm"]) for r in rows for d in r.get("dims") or [] if d.get("error_mm") is not None]
    verified = [r for r in rows if r.get("verified")]
    return {
        "n": len(rows),
        "median_error_mm": round(statistics.median(errors), 3) if errors else None,
        "pass_0_5": sum(bool(r.get("pass_0_5")) for r in rows),
        "verified": len(verified),
        "verified_but_off": sum(not r.get("pass_0_5") for r in verified),
        "usd": round(sum(float(r.get("usd") or 0) for r in rows), 2),
    }


def report(out: Path) -> dict[str, Any]:
    planned = samples()
    pairs = []
    for sid in planned:
        after = _score(out, sid)
        before = _score(BEFORE, sid)
        if after and before:
            pairs.append((sid, before, after))
    b_only = sum(bool(b.get("pass_0_5")) and not a.get("pass_0_5") for _, b, a in pairs)
    a_only = sum(bool(a.get("pass_0_5")) and not b.get("pass_0_5") for _, b, a in pairs)
    masks: dict[str, dict[str, int]] = {"before": {}, "after": {}}
    by_mask: dict[str, list[dict[str, Any]]] = {}
    for sid, _, a in pairs:
        key_b, key_a = mask_of(BEFORE / sid), mask_of(out / sid)
        masks["before"][key_b] = masks["before"].get(key_b, 0) + 1
        masks["after"][key_a] = masks["after"].get(key_a, 0) + 1
        by_mask.setdefault(key_a, []).append(a)
    rendered = (
        json.loads((DATA.parent / "rendered.json").read_text()) if (DATA.parent / "rendered.json").exists() else []
    )
    out_doc = {
        "planned": len(planned),
        "paired": len(pairs),
        "not_run": [s for s in planned if not _score(out, s)],
        "not_rendered": [r for r in rendered if not r["ok"]],
        "masks": masks,
        "before": _side([b for _, b, _ in pairs]),
        "after": _side([a for _, _, a in pairs]),
        "after_by_mask": {k: _side(v) for k, v in sorted(by_mask.items())},
        "discordant": {"before_only": b_only, "after_only": a_only},
        "mcnemar_p": stats.mcnemar_exact(b_only, a_only),
        "note": "Same rendered photos and scoring as the scale evaluation's runs. Nothing here is a real phone photo.",
        "source": "uv run python -m eval.after_fix report",
    }
    REPORT.write_text(json.dumps(out_doc, indent=1) + "\n")
    return out_doc


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("step", choices=["render", "run", "report"])
    ap.add_argument("--stop-epoch", type=float, default=0.0)
    ap.add_argument("--out", type=Path, default=AFTER)
    ap.add_argument("--workers", type=int, default=6)
    a = ap.parse_args()
    if a.step == "render":
        DATA.mkdir(parents=True, exist_ok=True)
        with ProcessPoolExecutor(max_workers=4) as ex:
            rows = list(ex.map(render_one, samples()))
        (DATA.parent / "rendered.json").write_text(json.dumps(rows, indent=1))
        print(f"{sum(r['ok'] for r in rows)} of {len(rows)} match their stored ground truth")
        for r in rows:
            if not r["ok"]:
                print(" ", r)
        return 0
    if a.step == "run":
        return run(a.stop_epoch, a.out, a.workers)
    print(json.dumps(report(a.out), indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
