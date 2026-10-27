"""PartSmith-Bench: the full fix loop on benchmark photos, scored against hidden ground truth (PLAN §10).

Suites (never merged): `synthetic` (data/synthetic/bench, exact GT), `reference_objects` (published specs; synthetic
renders now, real photos from data/real/reference_objects/<object>/*.jpg when they exist) and `real_ruler`
(data/real/<part>/gt.yaml with gt_source: ruler, ±0.5 mm; "pending" while there are none).

Configs change one thing at a time (PLAN §10.3): B0 single shot without the mat scale, B1 single shot with
measurements, B2 visual-only feedback, PS the full loop, PS-noTemplate, PS-noJudge, PS-noHeightCorr, and the provider
routing variants PS-open / PS-open-all (live only: in mock mode they are identical to PS).

Every run goes through `services.agent.service.start_fix_job(..., sync=True)` exactly like a user's job; answers come
from meta.json (`user_thickness_mm`) or the question defaults. Ground truth is read ONLY by the scorer here, which
rebuilds the job's final part program and compares its dimensions with the GT; verified rate, iterations, wall-clock,
$ and tokens come from the job's events. Each run is stored as eval/runs/<mode>/<suite>/<config>/<sample>/
{score.json, run.jsonl.gz, part_py.txt, overlay.png}; `--from-runs` rebuilds every table from those files without re-running.

    uv run python -m eval.run                  # mock providers: a pipeline check, NOT model performance
    uv run python -m eval.run --from-runs      # tables from stored runs (make bench)
    uv run python -m eval.run --live           # real providers (make bench-live); refuses without a live builder
    uv run python -m eval.run --check-regression
"""

from __future__ import annotations

import argparse
import datetime as dt
import gzip
import json
import math
import multiprocessing
import os
import shutil
import subprocess
import sys
import time
from collections.abc import Mapping, Sequence
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import yaml

from . import charts, taxonomy
from .metrics import error_stats, rate
from .stats import cluster_bootstrap_mean, mcnemar_paired

REPO = Path(__file__).resolve().parents[1]
RUNS_DIR = REPO / "eval" / "runs"
REPORTS_DIR = REPO / "eval" / "reports"
SPLITS_LOCK = REPO / "eval" / "splits.lock"
BASELINE = REPO / "eval" / "baseline_metrics.json"
BENCH_DIR = REPO / "data" / "synthetic" / "bench"
REAL_DIR = REPO / "data" / "real"
BENCH_HOME = REPO / "var" / "bench"  # PARTSMITH_HOME of bench jobs: keeps them out of the app's job list
BENCH_N, BENCH_N_REF, BENCH_SEED = 60, 20, 7  # the frozen synthetic bench (eval/splits.lock)

SUITES = ("synthetic", "reference_objects", "real_ruler")  # dimension-scored suites (tables never merged)
GATE_SUITES = ("control", "redteam")  # expected-outcome suites: accept / reject / refuse
ALL_SUITES = SUITES + GATE_SUITES
SUITES_DIR = REPO / "data" / "synthetic" / "suites"
SUITE_SEED = 11
GROUND_TRUTH = {
    "synthetic": "synthetic_exact",
    "reference_objects": "reference_spec",
    "real_ruler": "ruler",
    "control": "expected_outcome",
    "redteam": "expected_outcome",
}
GT_NOTE = {
    "synthetic": "exact: the template mesh the photo was rendered from",
    "reference_objects": "published spec (AA cell: loose spec)",
    "real_ruler": "school ruler, ±0.5 mm (never caliper accuracy)",
}
PENDING_NOTE = {
    "synthetic": "no held-out runs stored",
    "reference_objects": "no held-out runs stored (real photos go in data/real/reference_objects/<object>/)",
    "real_ruler": "no real parts with ruler ground truth yet (data/real/<part>/gt.yaml, see eval/REPRODUCE.md)",
}
MOCK_TITLE = "pipeline check — deterministic mock providers, NOT model performance"
CI_TEXT = "95 %: bootstrap over samples (2000 resamples, seeded) for mean errors; Wilson for rates"
HEADLINE_CONFIG = "PS"


@dataclass(frozen=True)
class Config:
    name: str
    description: str
    options: dict[str, Any] = field(default_factory=dict)
    env: dict[str, str] = field(default_factory=dict)
    routing_variant: bool = False


CONFIGS: dict[str, Config] = {
    c.name: c
    for c in (
        Config("B0", "single shot from the raw photo, no mat scale", {"single_shot": True, "mat_scale": False}),
        Config("B1", "single shot with the mat measurements (no loop)", {"single_shot": True}),
        Config("B2", "full loop, visual-only feedback (overlays, no residual numbers)", {"numeric_feedback": False}),
        Config("PS", "full PartSmith loop with numeric residuals"),
        Config("PS-noTemplate", "PS without the template library (free code only)", {"templates": False}),
        Config("PS-noJudge", "PS without the judge", {"judge": False}),
        Config("PS-noHeightCorr", "PS without the parallax (height) correction", {"height_correction": False}),
        Config("PS-open", "PS; builder/fixer must be served by open weights (default chain)", routing_variant=True),
        Config(
            "PS-open-all", "PS with every stage on open weights", env={"OPEN_WEIGHTS_ONLY": "1"}, routing_variant=True
        ),
    )
}
MOCK_CONFIGS = tuple(n for n, c in CONFIGS.items() if not c.routing_variant)


# ---------------------------------------------------------------- tasks


@dataclass
class Task:
    suite: str
    config: str
    sample_id: str
    sample_dir: str  # folder with meta.json + photos (synthetic) or the part folder (real)
    split: str  # held_out | dev | unassigned
    kind: str  # template | reference_object | real
    group: str = ""  # family / object / part
    preset: str = ""
    photo: str | None = None  # a single photo file (real reference objects)
    mode: str = "mock"
    out_dir: str = ""


def load_splits(path: Path = SPLITS_LOCK) -> dict[str, Any]:
    return json.loads(path.read_text()) if path.exists() else {}


def split_of(suite: str, sample_id: str, splits: Mapping[str, Any]) -> str:
    """held_out / dev / unassigned. The synthetic bench and the reference objects are never used for tuning, so they
    are held out; real parts follow the lists frozen in eval/splits.lock."""
    if suite in ("synthetic", "reference_objects"):
        return "held_out"
    real = splits.get("real_parts") or {}
    if sample_id in (real.get("held_out") or []):
        return "held_out"
    if sample_id in (real.get("dev") or []):
        return "dev"
    return "unassigned"


def gate_config(configs: Sequence[str]) -> str:
    """Control / red-team photos test the product, so they run with the headline config only."""
    return HEADLINE_CONFIG if HEADLINE_CONFIG in configs or not configs else configs[0]


def ensure_suite(name: str) -> Path:
    """Render data/synthetic/suites/<name>/ when it is missing or was made by another generator version."""
    from tools.synth import GENERATOR_VERSION
    from tools.synth.suites import make_suite

    root = SUITES_DIR / name
    man = root / "manifest.json"
    if man.exists():
        m = json.loads(man.read_text())
        if (
            m.get("generator") == GENERATOR_VERSION
            and m.get("seed") == SUITE_SEED
            and all((root / e["id"] / "gt.yaml").exists() for e in m["samples"])
        ):
            return root
    make_suite(name, root, seed=SUITE_SEED)
    return root


def ensure_bench_samples(ids: Sequence[str] | None = None) -> list[tuple[str, str, str]]:
    """(sample_id, kind, preset) of the frozen synthetic bench; renders only the samples that are missing."""
    from tools.synth import dataset_specs, generate_sample
    from tools.synth.dataset import default_sample_id

    out: list[tuple[str, str, str]] = []
    for spec, seed in dataset_specs(BENCH_N, BENCH_SEED, n_reference=BENCH_N_REF):
        sid = default_sample_id(spec, seed)
        if ids is not None and sid not in ids:
            out.append((sid, spec.kind, spec.preset))
            continue
        if not (BENCH_DIR / sid / "gt.yaml").exists():
            generate_sample(spec, BENCH_DIR, seed=seed)
        out.append((sid, spec.kind, spec.preset))
    return out


def pick(items: Sequence[str], limit: int | None, seed: int) -> list[str]:
    """Seeded subset (sorted), or everything when limit is None/0/≥ len."""
    if not limit or limit >= len(items):
        return list(items)
    rng = np.random.default_rng(seed)
    idx = sorted(rng.choice(len(items), size=limit, replace=False).tolist())
    return [items[i] for i in idx]


def collect_tasks(
    suites: Sequence[str], configs: Sequence[str], *, limit: int | None, n_ref: int | None, seed: int, mode: str
) -> tuple[list[Task], list[str]]:
    """Tasks to run plus notes (pending suites, subsets)."""
    from tools.synth.dataset import dataset_specs, default_sample_id

    splits = load_splits()
    notes: list[str] = []
    tasks: list[Task] = []
    specs = [(default_sample_id(s, sd), s) for s, sd in dataset_specs(BENCH_N, BENCH_SEED, n_reference=BENCH_N_REF)]
    plan: list[tuple[str, str, str, str, str, str | None]] = []  # suite, sid, dir, kind, preset/group, photo
    if "synthetic" in suites:
        tpl = [sid for sid, s in specs if s.kind == "template"]
        chosen = pick(tpl, limit, seed)
        if len(chosen) < len(tpl):
            notes.append(f"synthetic: seeded subset of {len(chosen)}/{len(tpl)} bench samples (seed {seed})")
        ensure_bench_samples(chosen)
        by_id = dict(specs)
        plan += [("synthetic", sid, str(BENCH_DIR / sid), "template", by_id[sid].preset, None) for sid in chosen]
    if "reference_objects" in suites:
        refs = [sid for sid, s in specs if s.kind == "reference_object"]  # round-robin over the 4 objects
        chosen = refs[:n_ref] if n_ref else refs
        ensure_bench_samples(chosen)
        by_id = dict(specs)
        plan += [
            ("reference_objects", sid, str(BENCH_DIR / sid), "reference_object", by_id[sid].preset, None)
            for sid in chosen
        ]
        real_ref = REAL_DIR / "reference_objects"
        n_real = 0
        if real_ref.exists():
            for obj in sorted(p for p in real_ref.iterdir() if p.is_dir()):
                for img_path in sorted(obj.glob("*.jp*g")):
                    if "side" in img_path.stem.lower():
                        continue
                    plan.append(
                        (
                            "reference_objects",
                            f"real-{obj.name}-{img_path.stem}",
                            str(obj),
                            "real",
                            "real",
                            str(img_path),
                        )
                    )
                    n_real += 1
        notes.append(
            f"reference_objects: {len(chosen)} synthetic renders"
            + (f" + {n_real} real photos" if n_real else "; real photos pending (data/real/reference_objects/)")
        )
    if "real_ruler" in suites:
        parts = [p for p in sorted(REAL_DIR.glob("*/gt.yaml")) if p.parent.name != "reference_objects"]
        ruler = [p.parent for p in parts if (yaml.safe_load(p.read_text()) or {}).get("gt_source") == "ruler"]
        ruler = [p for p in ruler if (p / "top.jpg").exists()]
        if not ruler:
            notes.append("real_ruler: no real parts with ruler ground truth yet (data/real/<part>/gt.yaml)")
        plan += [("real_ruler", p.name, str(p), "real", "real", None) for p in ruler]
    gate_plan: list[tuple[str, str, str, str, str, str | None]] = []
    for gs in (g for g in GATE_SUITES if g in suites):
        root = ensure_suite(gs)
        ids = [e["id"] for e in json.loads((root / "manifest.json").read_text())["samples"]]
        gate_plan += [(gs, sid, str(root / sid), gs, gs, None) for sid in ids]
        notes.append(f"{gs}: {len(ids)} synthetic photos with expected outcomes, run with {gate_config(configs)} only")
    for suite, sid, sdir, kind, preset, photo in gate_plan:
        cfg = gate_config(configs)
        run_dir = RUNS_DIR / mode / suite / cfg / sid
        tasks.append(Task(suite, cfg, sid, sdir, "held_out", kind, "", preset, photo, mode, str(run_dir)))
    for cfg in configs:
        for suite, sid, sdir, kind, preset, photo in plan:
            run_dir = RUNS_DIR / mode / suite / cfg / sid
            tasks.append(
                Task(suite, cfg, sid, sdir, split_of(suite, sid, splits), kind, "", preset, photo, mode, str(run_dir))
            )
    return tasks, notes


# ---------------------------------------------------------------- one run (worker process)


def _init_worker(env: Mapping[str, str]) -> None:
    os.environ.update(env)


def _job_inputs(task: Task) -> tuple[dict[str, bytes], Any, dict[str, Any]]:
    """(photos, JobInput, meta) — only what a user would provide; gt.yaml is not read here."""
    from partsmith_schemas import JobInput
    from partsmith_schemas.common import DataOrigin

    from services.agent import service

    d = Path(task.sample_dir)
    if task.photo is not None:  # a real photo of a reference object
        from tools.synth.reference_objects import get_reference_object

        ref = get_reference_object(d.name)
        meta = {"id": task.sample_id, "user_thickness_mm": ref.user_thickness_mm, "mat_id": None}
        ji = JobInput(
            intent=f"Measure this {ref.title} (reference object).",
            thickness_mm=ref.user_thickness_mm,
            origin=DataOrigin.reference_object,
        )
        return {"top": Path(task.photo).read_bytes()}, ji, meta
    if task.kind == "real":
        raw = yaml.safe_load((d / "gt.yaml").read_text()) or {}  # only the user-known fields are used
        thick = raw.get("user_thickness_mm")
        photos = {v: (d / f"{v}.jpg").read_bytes() for v in ("top", "side") if (d / f"{v}.jpg").exists()}
        meta = {"id": task.sample_id, "user_thickness_mm": thick, "mat_id": raw.get("mat_id")}
        ji = JobInput(
            intent=str(raw.get("intent") or "Make a replacement for this broken part."),
            thickness_mm=thick,
            origin=DataOrigin.real,
        )
        return photos, ji, meta
    sample = service.load_sample(d)
    return dict(sample.photos), service.sample_job_input(sample.meta), dict(sample.meta)


def run_task(task: Task) -> dict[str, Any]:
    """Run one fix job and score it; writes score.json, run.jsonl.gz (and overlay.png on failure)."""
    from services.agent import service
    from services.agent.orchestrator import RunOptions

    t0 = time.perf_counter()
    cfg = CONFIGS[task.config]
    out = Path(task.out_dir)
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    score: dict[str, Any] = {
        "suite": task.suite,
        "config": task.config,
        "sample_id": task.sample_id,
        "split": task.split,
        "kind": task.kind,
        "preset": task.preset,
        "mode": task.mode,
        "gt_source": GROUND_TRUTH[task.suite],
    }
    try:
        photos, ji, meta = _job_inputs(task)
        answers: dict[str, str | float] = {}
        if meta.get("user_thickness_mm"):
            answers["thickness"] = float(meta["user_thickness_mm"])
        opts = RunOptions(
            answers=answers,
            question_timeout_s=0.0,
            mat_id=meta.get("mat_id") or None,
            package=False,
            learn=False,
            **cfg.options,
        )
        job = service.start_fix_job(photos, ji, sync=True, options=opts, title=f"bench {task.config} {task.sample_id}")
    except Exception as exc:  # a crash is a result to report, not a reason to stop the bench
        score.update(
            status="crashed",
            verified=False,
            failure=f"{type(exc).__name__}: {exc}"[:300],
            wall_s=round(time.perf_counter() - t0, 2),
        )
        (out / "score.json").write_text(json.dumps(score, indent=1))
        return score
    wall = time.perf_counter() - t0
    events = [e.model_dump(mode="json", exclude_none=True) for e in job.events]
    with gzip.open(out / "run.jsonl.gz", "wt", encoding="utf-8") as fh:
        for e in events:
            fh.write(json.dumps(e) + "\n")
    score.update(job_summary(events))
    score["wall_s"] = round(wall, 2)
    code, values = job.read_text("part.py"), job.read_json("values.json") or {}
    if code:
        (out / "part_py.txt").write_text(code)  # not .py: stored programs must not be linted/imported
    if task.suite == "redteam":
        score.update(valid=bool(code), dims=[], missed=[], extra_holes=0, pass_0_3=False, pass_0_5=False)
    else:
        score.update(score_model(code, {k: float(v) for k, v in values.items()}, task))
    if task.suite in GATE_SUITES:
        score.update(gate_outcome(score, task))
    # red-team misses are reported by the red-team table, not as build failures
    score["failure_category"] = None if task.suite == "redteam" or gate_ok(score) else taxonomy.classify(score, events)
    if not score.get("pass_0_5") and task.suite != "redteam":
        png = failure_overlay(events) if task.config == HEADLINE_CONFIG else None  # the gallery shows PS only
        if png is not None:
            (out / "overlay.png").write_bytes(png)
            score["overlay"] = "overlay.png"
        score["failure"] = failure_reason(score, events)
    (out / "score.json").write_text(json.dumps(score, indent=1))
    return score


def job_summary(events: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Status, cost, tokens, providers and the convergence curve from a job's events."""
    done = next((e for e in reversed(events) if e.get("t") == "done"), None)
    calls = [e for e in events if e.get("t") == "model_call"]
    modes = sorted({str(c.get("mode")) for c in calls})
    providers: dict[str, list[str]] = {}
    for c in calls:
        providers.setdefault(str(c.get("stage")), [])
        p = f"{c.get('provider')}:{c.get('model')}"
        if p not in providers[str(c.get("stage"))]:
            providers[str(c.get("stage"))].append(p)
    curve: dict[int, dict[str, float]] = {}
    for e in events:
        if e.get("t") == "metric" and e.get("iter") and e.get("name") in ("max_error_mm", "hausdorff_mm", "iou"):
            curve.setdefault(int(e["iter"]), {})[str(e["name"])] = float(e["value"])
    summ = dict(done.get("summary") or {}) if done else {}
    first_ok = next((i for i, m in sorted(curve.items()) if m.get("max_error_mm", math.inf) <= 0.5), None)
    return {
        "status": done.get("status") if done else "no_done_event",
        "verified": bool(done.get("verified")) if done else False,
        "iterations": int(summ.get("iterations") or 0),
        "iterations_to_converge": first_ok,
        "strategy": summ.get("strategy"),
        "template": summ.get("template"),
        "verifier_max_error_mm": summ.get("max_error_mm"),
        "retake_reason": summ.get("retake_reason") or summ.get("reason"),
        "failed_checks": taxonomy.failed_checks(summ),
        "usd": round(sum(float(c.get("usd") or 0) for c in calls), 6),
        "tokens_in": sum(int(c.get("tokens_in") or 0) for c in calls),
        "tokens_out": sum(int(c.get("tokens_out") or 0) for c in calls),
        "model_calls": len(calls),
        "model_ms": sum(int(c.get("ms") or 0) for c in calls),
        "provider_modes": modes,
        "providers": providers,
        "convergence": [{"iter": i, **m} for i, m in sorted(curve.items())],
    }


def gate_outcome(score: Mapping[str, Any], task: Task) -> dict[str, Any]:
    """What the product did with a control / red-team photo, vs what it should have done (gt.yaml `expect`)."""
    from tools.synth.suites import expected

    exp = expected(yaml.safe_load((Path(task.sample_dir) / "gt.yaml").read_text()) or {})
    status = str(score.get("status") or "")
    checks = list(score.get("failed_checks") or [])
    if status == "refused":
        outcome = "refuse"
    elif status == "failed" and (checks or score.get("retake_reason")):
        outcome = "reject"  # stopped at capture / measurement with a retake reason
    elif status in ("crashed", "no_done_event"):
        outcome = "error"
    else:
        outcome = "accept"  # the job went on to build a part (verified, best effort or a failed build)
    correct = outcome == exp.outcome and (outcome != "reject" or not exp.checks or bool(set(checks) & set(exp.checks)))
    return {
        "expected_outcome": exp.outcome,
        "expected_checks": list(exp.checks),
        "expected_why": exp.why,
        "outcome": outcome,
        "outcome_correct": correct,
    }


def gate_ok(score: Mapping[str, Any]) -> bool:
    """A run that needs no failure category: it passed (control photos must also be accepted)."""
    if score.get("suite") == "control":
        return bool(score.get("outcome_correct")) and bool(score.get("pass_0_5"))
    return bool(score.get("pass_0_5"))


def failure_overlay(events: Sequence[Mapping[str, Any]], max_side: int = 480) -> bytes | None:
    """The last residual overlay (or the measurement overlay) of a job, downscaled for the gallery."""
    import cv2

    from services.common import blobs

    arts = [e for e in events if e.get("t") == "artifact" and e.get("kind") in ("residual_heatmap", "measure_overlay")]
    res = [e for e in arts if e.get("kind") == "residual_heatmap"] or arts
    if not res:
        return None
    try:
        data = blobs.get(str(res[-1]["sha"]))
    except Exception:
        return None
    img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        return None
    s = max_side / max(img.shape[:2])
    if s < 1:
        img = cv2.resize(img, (round(img.shape[1] * s), round(img.shape[0] * s)), interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".png", img)
    return bytes(buf.tobytes()) if ok else None


def failure_reason(score: Mapping[str, Any], events: Sequence[Mapping[str, Any]]) -> str:
    if score.get("status") in ("failed", "refused") and score.get("retake_reason"):
        return f"job {score['status']}: {score['retake_reason']}"
    if not score.get("valid"):
        return f"no valid final model ({score.get('valid_reason') or score.get('status')})"
    worst = max(score.get("dims") or [], key=lambda d: abs(d["error_mm"]), default=None)
    parts = []
    if worst is not None:
        parts.append(f"worst {worst['name']} {worst['error_mm']:+.2f} mm")
    if score.get("missed"):
        parts.append("missing " + ", ".join(score["missed"][:4]))
    return "; ".join(parts) or str(score.get("status"))


# ---------------------------------------------------------------- scoring (the only place that reads ground truth)


def gt_dims(task: Task) -> list[dict[str, Any]]:
    """Named GT dims for the FINAL MODEL: length, width, thickness (overall), hole_k.diameter."""
    d = Path(task.sample_dir)
    if task.suite == "reference_objects":
        from tools.synth.reference_objects import get_reference_object

        key = d.name if task.photo is not None else yaml.safe_load((d / "gt.yaml").read_text())["name"]
        ref = get_reference_object(key)
        return [{"name": s.name, "value_mm": s.nominal_mm, "lo_mm": s.lo_mm, "hi_mm": s.hi_mm} for s in ref.dims]
    raw = yaml.safe_load((d / "gt.yaml").read_text()) or {}
    if task.suite == "real_ruler":
        dims = raw.get("dims") or {}
        out = [{"name": k, "value_mm": float(dims[k])} for k in ("length", "width", "thickness") if k in dims]
        out += [
            {"name": f"hole_{i + 1}.diameter", "value_mm": float(h["diameter"])}
            for i, h in enumerate(raw.get("holes") or [])
        ]
        return out
    out = [{"name": x["name"], "value_mm": float(x["value_mm"])} for x in raw.get("dims", []) if x["view"] == "top"]
    side = [x for x in raw.get("dims", []) if x["view"] == "side" and x["name"] == "thickness"]
    info = raw.get("info") or {}
    if side:
        out.append({"name": "thickness", "value_mm": float(side[0]["value_mm"])})
    elif info.get("height_mm") is not None and info.get("side_length_mm") is not None:
        out.append({"name": "thickness", "value_mm": min(float(info["height_mm"]), float(info["side_length_mm"]))})
    return out


def model_dims(code: str, values: Mapping[str, float]) -> tuple[dict[str, float], list[float], bool, str]:
    """(length/width/thickness, see-through hole diameters, valid, reason) of a part program, measured the same way
    as the GT (tools.synth.geometry)."""
    from services.geom_worker.sandbox import run_program
    from tools.synth import geometry as G

    with run_program(code, dict(values), outputs=(), features=True, timeout_s=60.0) as res:
        if not res.ok or res.mesh is None:
            return {}, [], False, res.error.short() if res.error else "no mesh"
        si = res.solid_info
        valid = bool(si is not None and si.valid and si.n_solids == 1)
        reason = "" if valid else f"solid valid={si.valid if si else None}, solids={si.n_solids if si else None}"
        pm = G.PartMesh(np.asarray(res.mesh.vertices), np.asarray(res.mesh.faces), dict(res.features or {}))
    dims = {**G.top_dims(pm), "thickness": G.side_dims(pm)["thickness"]}
    holes = [h.diameter_mm for h in G.visible_holes(pm)]
    return dims, holes, valid, reason


def compare(gt: Sequence[Mapping[str, Any]], dims: Mapping[str, float], holes: Sequence[float]) -> dict[str, Any]:
    """Match model dims to GT by name; holes by nearest diameter (frames differ, so not by position)."""
    from .measure_only import match_holes

    rows: list[dict[str, Any]] = []
    missed: list[str] = []
    for g in gt:
        name = str(g["name"])
        if name.startswith("hole_"):
            continue
        if name in dims:
            v = float(dims[name])
            row = {
                "name": name,
                "gt_mm": float(g["value_mm"]),
                "model_mm": round(v, 4),
                "error_mm": round(v - float(g["value_mm"]), 4),
            }
            if g.get("lo_mm") is not None:
                row["within_spec"] = bool(float(g["lo_mm"]) <= v <= float(g["hi_mm"]))
            rows.append(row)
        else:
            missed.append(name)
    hg = [g for g in gt if str(g["name"]).startswith("hole_")]
    pairs, miss_i, extra_j = match_holes(hg, [(d, (0.0, 0.0)) for d in holes], "diameter")
    for i, j in pairs:
        v, gv = float(holes[j]), float(hg[i]["value_mm"])
        rows.append({"name": str(hg[i]["name"]), "gt_mm": gv, "model_mm": round(v, 4), "error_mm": round(v - gv, 4)})
    missed += [str(hg[i]["name"]) for i in miss_i]
    errs = [abs(r["error_mm"]) for r in rows]
    complete = not missed and bool(rows)
    return {
        "dims": rows,
        "missed": missed,
        "extra_holes": len(extra_j),
        "pass_0_3": complete and all(e <= 0.3 + 1e-9 for e in errs),
        "pass_0_5": complete and all(e <= 0.5 + 1e-9 for e in errs),
    }


def score_model(code: str | None, values: Mapping[str, float], task: Task) -> dict[str, Any]:
    gt = gt_dims(task)
    if not code:
        return {
            "valid": False,
            "valid_reason": "no part program",
            "dims": [],
            "pass_0_3": False,
            "pass_0_5": False,
            "missed": [str(g["name"]) for g in gt],
            "extra_holes": 0,
        }
    try:
        dims, holes, valid, reason = model_dims(code, values)
    except Exception as exc:
        dims, holes, valid, reason = {}, [], False, f"{type(exc).__name__}: {exc}"[:200]
    out = (
        compare(gt, dims, holes)
        if dims
        else {
            "dims": [],
            "missed": [str(g["name"]) for g in gt],
            "extra_holes": 0,
            "pass_0_3": False,
            "pass_0_5": False,
        }
    )
    out.update(valid=valid, valid_reason=reason)
    return out


# ---------------------------------------------------------------- running many


def run_tasks(tasks: Sequence[Task], *, jobs: int, live: bool, log: Any = print) -> list[dict[str, Any]]:
    """Run tasks grouped by config (a config's env is set per worker process). Bench jobs live in var/bench."""
    results: list[dict[str, Any]] = []
    base_env = {"PARTSMITH_HOME": str(BENCH_HOME)}
    if not live:
        base_env["PROVIDER_MODE"] = "mock"
    for cfg in dict.fromkeys(t.config for t in tasks):
        group = [t for t in tasks if t.config == cfg]
        env = {**base_env, **CONFIGS[cfg].env}
        t0 = time.perf_counter()
        ctx = multiprocessing.get_context("spawn")  # fresh interpreters: no fork of a threaded parent
        with ProcessPoolExecutor(
            max_workers=max(1, jobs), mp_context=ctx, initializer=_init_worker, initargs=(env,)
        ) as ex:
            got = list(ex.map(run_task, group, chunksize=1))
        results += got
        ok = sum(bool(r.get("pass_0_5")) for r in got)
        log(f"{cfg:16s} {len(got):3d} runs  pass@0.5 {ok}/{len(got)}  {time.perf_counter() - t0:.0f} s")
    return results


def load_runs(mode: str | None = None) -> tuple[str, list[dict[str, Any]]]:
    """Stored score.json files. Picks `mode`, else live runs when there are any, else mock."""
    modes = sorted(p.name for p in RUNS_DIR.iterdir() if p.is_dir()) if RUNS_DIR.exists() else []
    if mode is None:
        mode = "live" if "live" in modes else "mock"
    root = RUNS_DIR / mode
    scores = [json.loads(p.read_text()) for p in sorted(root.glob("*/*/*/score.json"))] if root.exists() else []
    return mode, scores


# ---------------------------------------------------------------- report


def _f(x: Any, nd: int = 3) -> float | None:
    return None if x is None or (isinstance(x, float) and not math.isfinite(x)) else round(float(x), nd)


def _ci(c: Sequence[float], nd: int = 3) -> str:
    return "–" if any(not math.isfinite(v) for v in c) else f"[{c[0]:.{nd}f}, {c[1]:.{nd}f}]"


def config_row(cfg: str, runs: Sequence[Mapping[str, Any]], seed: int = 0) -> dict[str, Any]:
    runs = sorted(runs, key=lambda r: (str(r.get("suite")), str(r.get("sample_id"))))  # order-free bootstrap CIs
    errs = [float(d["error_mm"]) for r in runs for d in r.get("dims") or []]
    st = error_stats(errs, seed=seed)
    # dims of one part are correlated: the CI resamples whole runs, not single dimensions
    mean_ci = cluster_bootstrap_mean(
        [[abs(float(d["error_mm"])) for d in r.get("dims") or []] for r in runs], seed=seed
    )
    n = len(runs)
    ver = rate(sum(bool(r.get("verified")) for r in runs), n)
    p5 = rate(sum(bool(r.get("pass_0_5")) for r in runs), n)
    p3 = rate(sum(bool(r.get("pass_0_3")) for r in runs), n)
    val = rate(sum(bool(r.get("valid")) for r in runs), n)
    its = [int(r.get("iterations") or 0) for r in runs]
    wall = [float(r.get("wall_s") or 0) for r in runs]
    usd = [float(r.get("usd") or 0) for r in runs]
    tok = [int(r.get("tokens_in") or 0) + int(r.get("tokens_out") or 0) for r in runs]
    modes = sorted({m for r in runs for m in r.get("provider_modes") or []})
    return {
        "config": cfg,
        "description": CONFIGS[cfg].description if cfg in CONFIGS else "",
        "n": n,
        "dims": st.n,
        "median_abs_err_mm": _f(st.median_mm),
        "mean_abs_err_mm": _f(st.mean_mm),
        "mean_ci95": _ci(mean_ci),
        "p90_mm": _f(st.p90_mm),
        "pass@0.3": _f(p3.rate),
        "pass@0.5": _f(p5.rate),
        "pass@0.5_ci95": _ci(p5.ci95, 2),
        "verified_rate": _f(ver.rate),
        "verified_ci95": _ci(ver.ci95, 2),
        "valid_rate": _f(val.rate),
        "median_iters": _f(float(np.median(its)) if its else math.nan, 1),
        "median_wall_s": _f(float(np.median(wall)) if wall else math.nan, 1),
        "usd_per_job": _f(float(np.mean(usd)) if usd else math.nan, 4),
        "tokens_per_job": _f(float(np.mean(tok)) if tok else math.nan, 0),
        "provider_modes": ",".join(modes) or "–",
    }


COLUMNS = [
    "config",
    "n",
    "median_abs_err_mm",
    "mean_abs_err_mm",
    "mean_ci95",
    "p90_mm",
    "pass@0.5",
    "pass@0.5_ci95",
    "verified_rate",
    "verified_ci95",
    "valid_rate",
    "median_iters",
    "median_wall_s",
    "usd_per_job",
    "tokens_per_job",
    "provider_modes",
]


def build_tables(scores: Sequence[Mapping[str, Any]], mode: str, notes: Sequence[str]) -> dict[str, Any]:
    tables: dict[str, Any] = {}
    for suite in SUITES:
        runs = [s for s in scores if s["suite"] == suite]
        held = [s for s in runs if s.get("split") == "held_out"]
        prefix = f"{MOCK_TITLE} · " if mode == "mock" else ""
        title = f"{prefix}{suite.replace('_', ' ')} (GT: {GT_NOTE[suite]})"
        suite_notes = [n for n in notes if n.startswith(suite)]
        if not held:
            extra = f" ({len(runs)} run(s) outside the held-out split)" if runs else ""
            tables[suite] = {
                "title": title,
                "n": 0,
                "ground_truth": GROUND_TRUTH[suite],
                "ci": CI_TEXT,
                "columns": [],
                "rows": [],
                "headline": {"median_abs_err_mm": None},
                "median_abs_err_mm": None,
                "status": "pending",
                "mode": mode,
                "note": "; ".join(suite_notes) or f"{PENDING_NOTE[suite]}{extra}",
            }
            continue
        cfgs = [c for c in CONFIGS if any(r["config"] == c for r in held)]
        rows = [config_row(c, [r for r in held if r["config"] == c]) for c in cfgs]
        head = next((r for r in rows if r["config"] == HEADLINE_CONFIG), rows[0])
        n_samples = len({r["sample_id"] for r in held})
        dev = [s for s in runs if s.get("split") != "held_out"]
        note = "; ".join(
            [*suite_notes, f"headline = {head['config']} on the held-out split ({n_samples} samples)"]
            + ([f"{len(dev)} dev/unassigned run(s) excluded from the tables"] if dev else [])
            + (
                ["MOCK providers: these numbers check the pipeline, they do not measure any model"]
                if mode == "mock"
                else []
            )
        )
        n_real = len({r["sample_id"] for r in held if r.get("kind") == "real"})
        photos = (
            "real photos"
            if n_real == n_samples
            else (f"{n_real} real + {n_samples - n_real} synthetic renders" if n_real else "synthetic renders")
        )
        tables[suite] = {
            "title": title,
            "photos": photos,
            "n": n_samples,
            "ground_truth": GROUND_TRUTH[suite],
            "ci": CI_TEXT,
            "columns": COLUMNS,
            "rows": rows,
            "headline": {
                "config": head["config"],
                "median_abs_err_mm": head["median_abs_err_mm"],
                "mean_abs_err_mm": head["mean_abs_err_mm"],
                "pass_at_0_5": head["pass@0.5"],
                "verified_rate": head["verified_rate"],
                "n": head["n"],
            },
            "median_abs_err_mm": head["median_abs_err_mm"],
            "status": "ok",
            "mode": mode,
            "note": note,
            "mcnemar_B1_vs_PS": mcnemar_b1_ps(held),
        }
    for gs in GATE_SUITES:
        tables[gs] = gate_table(gs, [s for s in scores if s["suite"] == gs], mode)
    return tables


GATE_COLUMNS = ["case", "expected", "expected_checks", "outcome", "failed_checks", "correct"]


def gate_table(suite: str, runs: Sequence[Mapping[str, Any]], mode: str) -> dict[str, Any]:
    """Control: share of intact parts accepted (false rejections); red-team: share handled as expected."""
    prefix = f"{MOCK_TITLE} · " if mode == "mock" else ""
    what = "intact parts, normal photos → accept" if suite == "control" else "photos that must be rejected or refused"
    if not runs:
        return {
            "title": f"{prefix}{suite} ({what})",
            "n": 0,
            "ground_truth": GROUND_TRUTH[suite],
            "ci": CI_TEXT,
            "columns": [],
            "rows": [],
            "headline": {"correct_rate": None},
            "status": "pending",
            "mode": mode,
            "note": f"pending: no {suite} runs stored",
        }
    rows = [
        {
            "case": r["sample_id"],
            "expected": r.get("expected_outcome"),
            "expected_checks": ",".join(r.get("expected_checks") or []) or "any",
            "outcome": r.get("outcome"),
            "failed_checks": ",".join(r.get("failed_checks") or []) or "–",
            "correct": bool(r.get("outcome_correct")),
        }
        for r in sorted(runs, key=lambda x: str(x["sample_id"]))
    ]
    k = sum(r["correct"] for r in rows)
    rr = rate(k, len(rows))
    head: dict[str, Any] = {"correct": k, "n": len(rows), "correct_rate": _f(rr.rate), "ci95": _ci(rr.ci95, 2)}
    if suite == "control":
        fr = rate(sum(r["outcome"] != "accept" for r in rows), len(rows))
        head["false_reject_rate"] = _f(fr.rate)
        head["false_reject_ci95"] = _ci(fr.ci95, 2)
        head["pass_at_0_5"] = _f(rate(sum(bool(r.get("pass_0_5")) for r in runs), len(runs)).rate)
    else:
        by = {o: sum(r["expected"] == o for r in rows) for o in ("reject", "refuse")}
        head.update({f"{o}_expected": n for o, n in by.items()})
        head.update(
            {f"{o}_correct": sum(r["correct"] for r in rows if r["expected"] == o) for o in ("reject", "refuse")}
        )
    return {
        "title": f"{prefix}{suite} ({what})",
        "n": len(rows),
        "ground_truth": GROUND_TRUTH[suite],
        "ci": "95 % Wilson",
        "columns": GATE_COLUMNS,
        "rows": rows,
        "headline": head,
        "status": "ok",
        "mode": mode,
        "note": f"{k}/{len(rows)} handled as expected ({head['ci95']}); config {runs[0]['config']}",
    }


def failure_taxonomy(scores: Sequence[Mapping[str, Any]]) -> dict[str, dict[str, dict[str, int]]]:
    """Count per failure category, per suite and config (runs without a category are not failures)."""
    out: dict[str, dict[str, dict[str, int]]] = {}
    for suite in dict.fromkeys(s["suite"] for s in scores):
        if suite == "redteam":
            continue
        for cfg in dict.fromkeys(s["config"] for s in scores if s["suite"] == suite):
            runs = [s for s in scores if s["suite"] == suite and s["config"] == cfg]
            cats = [s.get("failure_category", taxonomy.classify(s)) if not gate_ok(s) else None for s in runs]
            out.setdefault(suite, {})[cfg] = {**taxonomy.counts(cats), "runs": len(runs)}
    return out


def mcnemar_b1_ps(runs: Sequence[Mapping[str, Any]]) -> dict[str, Any] | None:
    """Paired exact McNemar on pass@0.5 for samples run under both B1 and PS."""
    b1 = {r["sample_id"]: bool(r.get("pass_0_5")) for r in runs if r["config"] == "B1"}
    ps = {r["sample_id"]: bool(r.get("pass_0_5")) for r in runs if r["config"] == "PS"}
    common = sorted(set(b1) & set(ps))
    if not common:
        return None
    b, c, p = mcnemar_paired([b1[s] for s in common], [ps[s] for s in common])
    return {"n_pairs": len(common), "b1_only": b, "ps_only": c, "p_value": round(p, 6), "metric": "pass@0.5"}


def run_summaries(scores: Sequence[Mapping[str, Any]]) -> dict[str, dict[str, list[dict[str, Any]]]]:
    keep = (
        "sample_id",
        "split",
        "preset",
        "status",
        "verified",
        "valid",
        "pass_0_5",
        "iterations",
        "wall_s",
        "usd",
        "tokens_in",
        "tokens_out",
        "strategy",
        "template",
        "failure",
    )
    out: dict[str, dict[str, list[dict[str, Any]]]] = {}
    for s in scores:
        row = {k: s.get(k) for k in keep}
        errs = [abs(float(d["error_mm"])) for d in s.get("dims") or []]
        row["max_abs_err_mm"] = round(max(errs), 4) if errs else None
        out.setdefault(s["suite"], {}).setdefault(s["config"], []).append(row)
    return out


def failures_gallery(
    scores: Sequence[Mapping[str, Any]], mode: str, out_dir: Path, limit: int = 24
) -> list[dict[str, Any]]:
    """Failed PS runs (held-out first) with their overlay copied into the report and into the local blob store."""
    from services.common import blobs

    gal = out_dir / "gallery"
    fails = [s for s in scores if not s.get("pass_0_5") and s["config"] == HEADLINE_CONFIG and s["suite"] in SUITES]
    fails.sort(key=lambda s: (s.get("split") != "held_out", s["suite"], s["sample_id"]))
    out: list[dict[str, Any]] = []
    for s in fails[:limit]:
        src = RUNS_DIR / mode / s["suite"] / s["config"] / s["sample_id"] / "overlay.png"
        url, file = "", None
        if src.exists():
            gal.mkdir(parents=True, exist_ok=True)
            file = f"gallery/{s['suite']}-{s['sample_id']}.png"
            shutil.copyfile(src, out_dir / file)
            try:
                url = blobs.url(blobs.put(src.read_bytes(), ".png"))
            except Exception:
                url = ""
        out.append(
            {
                "title": f"{s['sample_id']} · {s['config']} ({s['suite']}, {s.get('split')})",
                "reason": s.get("failure") or s.get("status") or "",
                "overlay_url": url,
                "overlay_file": file,
            }
        )
    return out


def write_charts(scores: Sequence[Mapping[str, Any]], mode: str, out_dir: Path) -> list[str]:
    files: list[str] = []
    cdir = out_dir / "charts"
    cdir.mkdir(parents=True, exist_ok=True)
    tag = " [MOCK]" if mode == "mock" else ""
    for suite in SUITES:
        runs = [s for s in scores if s["suite"] == suite and s.get("split") == "held_out"]
        if not runs:
            continue
        curves: dict[str, list[float | None]] = {}
        for cfg in CONFIGS:
            cr = [r for r in runs if r["config"] == cfg]
            if not cr:
                continue
            n_it = max((len(r.get("convergence") or []) for r in cr), default=0)
            med: list[float | None] = []
            for i in range(n_it):
                # a run that already stopped keeps its last value (the best it reached is what it ships)
                vals = []
                for r in cr:
                    c = [x.get("max_error_mm") for x in r.get("convergence") or [] if x.get("max_error_mm") is not None]
                    if c:
                        vals.append(min(c[: i + 1]) if i < len(c) else min(c))
                med.append(float(np.median(vals)) if vals else None)
            curves[f"{cfg} (N={len(cr)})"] = med
        p = cdir / f"convergence_{suite}.svg"
        p.write_text(charts.convergence_svg(curves, f"{suite}: best verifier max error by iteration{tag}"))
        files.append(str(p.relative_to(out_dir)))
        hist = {
            cfg: [abs(float(d["error_mm"])) for r in runs if r["config"] == cfg for d in r.get("dims") or []]
            for cfg in ("B1", "PS")
            if any(r["config"] == cfg for r in runs)
        }
        if hist:
            p = cdir / f"errors_{suite}.svg"
            p.write_text(charts.histogram_svg(hist, f"{suite}: final-model dimension error vs GT{tag}"))
            files.append(str(p.relative_to(out_dir)))
    return files


def latest_measure_only() -> dict[str, Any] | None:
    """Aggregates of the newest measure_only report (no per-photo rows), plus its printed `summary` lines."""
    from .measure_only import summary_lines

    reps = sorted(REPORTS_DIR.glob("*/measure_only.json"))
    if not reps:
        return None
    r = json.loads(reps[-1].read_text())
    return {
        "date": r.get("date"),
        "file": str(reps[-1].relative_to(REPO)),
        "summary": "\n".join(summary_lines(r)),
        "gate": r.get("gate"),
        "synthetic_manifest": r.get("synthetic_manifest"),
        "sections": r.get("sections"),
    }


def git_sha() -> str | None:
    try:
        return (
            subprocess.run(
                ["git", "rev-parse", "HEAD"], cwd=REPO, capture_output=True, text=True, timeout=5, check=True
            ).stdout.strip()
            or None
        )
    except Exception:
        return None


def build_report(scores: Sequence[Mapping[str, Any]], mode: str, notes: Sequence[str], out_dir: Path) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    return {
        "status": "ok",
        "generated_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "git_sha": git_sha(),
        "mode": mode,
        "label": MOCK_TITLE if mode == "mock" else "live providers",
        "notes": list(notes),
        "configs": {k: {"description": c.description, "options": c.options, "env": c.env} for k, c in CONFIGS.items()},
        "tables": build_tables(scores, mode, notes),
        "runs": run_summaries(scores),
        "failures": failures_gallery(scores, mode, out_dir),
        "charts": write_charts(scores, mode, out_dir),
        "measure_only": latest_measure_only(),
        "failure_taxonomy": failure_taxonomy(scores),
        "taxonomy_categories": dict(taxonomy.DESCRIPTIONS),
    }


def to_markdown(rep: Mapping[str, Any]) -> str:
    L = [f"# PartSmith-Bench — {rep['generated_at']}", ""]
    if rep["mode"] == "mock":
        L += [
            f"> **{MOCK_TITLE.upper()}.** Every model stage ran on deterministic mocks; these tables show that the "
            "pipeline and the scorer work end to end, not how well any model performs.",
            "",
        ]
    L.append(f"Mode: `{rep['mode']}` · git `{(rep.get('git_sha') or 'n/a')[:10]}` · CI: {CI_TEXT}.")
    for n in rep.get("notes") or []:
        L.append(f"- {n}")
    short = [
        "config",
        "n",
        "median_abs_err_mm",
        "mean_abs_err_mm",
        "mean_ci95",
        "pass@0.5",
        "pass@0.5_ci95",
        "verified_rate",
        "valid_rate",
        "median_iters",
        "median_wall_s",
        "usd_per_job",
        "tokens_per_job",
    ]
    for suite, t in rep["tables"].items():
        L += [
            "",
            f"## {t['title']}",
            "",
            f"Ground truth: `{t['ground_truth']}` · N = {t['n']} samples · {t['note']}",
            "",
        ]
        if t["status"] != "ok":
            L.append("**pending**")
            continue
        if suite in GATE_SUITES:
            L.append("| " + " | ".join(GATE_COLUMNS) + " |")
            L.append("|" + "---|" * len(GATE_COLUMNS))
            for r in t["rows"]:
                L.append("| " + " | ".join(str(r.get(c)) for c in GATE_COLUMNS) + " |")
            continue
        L.append("| " + " | ".join(short) + " |")
        L.append("|" + "---|" * len(short))
        for r in t["rows"]:
            L.append("| " + " | ".join("–" if r.get(c) is None else str(r.get(c)) for c in short) + " |")
        m = t.get("mcnemar_B1_vs_PS")
        if m:
            L.append("")
            L.append(
                f"Paired exact McNemar, B1 vs PS on {m['metric']} ({m['n_pairs']} pairs): B1-only passes "
                f"{m['b1_only']}, PS-only passes {m['ps_only']}, p = {m['p_value']:.4g}."
            )
        for c in rep.get("charts") or []:
            if suite in c:
                L.append(f"\n![{c}]({c})")
    tax = rep.get("failure_taxonomy") or {}
    if tax:
        cats = list(taxonomy.CATEGORIES)
        L += [
            "",
            "## Failure taxonomy (one category per failed run)",
            "",
            "| suite | config | runs | " + " | ".join(cats) + " |",
            "|" + "---|" * (len(cats) + 3),
        ]
        for suite, cfgs in tax.items():
            for cfg, c in cfgs.items():
                L.append(f"| {suite} | {cfg} | {c['runs']} | " + " | ".join(str(c[k]) for k in cats) + " |")
    L += ["", "## Failure gallery (PS)", ""]
    if not rep["failures"]:
        L.append("None.")
    for f in rep["failures"]:
        img = f" ![overlay]({f['overlay_file']})" if f.get("overlay_file") else ""
        L.append(f"- **{f['title']}** — {f['reason']}{img}")
    mo = rep.get("measure_only")
    if mo:
        g = mo.get("gate") or {}
        L += [
            "",
            "## Measurement only (Phase 1 bench)",
            "",
            f"From `{mo['file']}`: synthetic mean {g.get('synthetic', {}).get('mean_mm', float('nan')):.3f} mm, "
            f"reference objects mean {g.get('reference_objects', {}).get('mean_mm', float('nan')):.3f} mm → gate "
            f"{'PASS' if g.get('pass') else 'FAIL'}.",
        ]
    L.append("")
    return "\n".join(L)


def write_report(
    rep: Mapping[str, Any],
    out_dir: Path,
    scores: Sequence[Mapping[str, Any]] = (),
    seed: int | None = None,
    *,
    latest: bool = True,
) -> tuple[Path, Path]:
    """report.{json,md} + provenance.json + open_weights.json in `out_dir` (and in eval/reports/latest/ unless
    `latest=False`, e.g. a smoke run written elsewhere with --out)."""
    from . import open_weights, provenance

    jp, mp = out_dir / "report.json", out_dir / "report.md"
    jp.write_text(json.dumps(rep, indent=1) + "\n")
    mp.write_text(to_markdown(rep))
    targets = [out_dir]
    if latest:
        (REPORTS_DIR / "latest").mkdir(parents=True, exist_ok=True)
        (REPORTS_DIR / "latest" / "report.json").write_text(json.dumps(rep, indent=1) + "\n")
        targets.append(REPORTS_DIR / "latest")
    run_dirs = [RUNS_DIR / str(s.get("mode")) / s["suite"] / s["config"] / s["sample_id"] for s in scores]
    calls = open_weights.read_model_calls(run_dirs)
    prov = provenance.build(
        report="eval/run.py",
        mode=str(rep["mode"]),
        model_calls=calls,
        seeds={"synthetic_bench": BENCH_SEED, "subset": seed, "suites": SUITE_SEED},
        extra={"configs": rep.get("configs"), "n_runs": len(scores)},
    )
    provenance.write(prov, *(t / "provenance.json" for t in targets))
    rows = {k: t.get("rows") or [] for k, t in rep["tables"].items() if k in SUITES}
    ow = {
        "generated_at": rep["generated_at"],
        "git_sha": rep.get("git_sha"),
        "mode": rep["mode"],
        **open_weights.build(calls, rows),
    }
    for p in (t / "open_weights.json" for t in targets):
        p.write_text(json.dumps(ow, indent=1) + "\n")
    return jp, mp


# ---------------------------------------------------------------- regression check


REGRESSION_METRICS = {  # metric: (direction, allowed slack)
    "median_abs_err_mm": ("max", 0.15),
    "pass@0.5": ("min", 0.15),
    "verified_rate": ("min", 0.15),
    "valid_rate": ("min", 0.10),
}


def baseline_from(rep: Mapping[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {
        "mode": rep["mode"],
        "generated_at": rep["generated_at"],
        "git_sha": rep.get("git_sha"),
        "slack": {k: v[1] for k, v in REGRESSION_METRICS.items()},
        "tables": {},
    }
    for suite, t in rep["tables"].items():
        if t["status"] != "ok":
            continue
        out["tables"][suite] = {r["config"]: {k: r.get(k) for k in REGRESSION_METRICS} for r in t["rows"]}
    return out


def check_regression(rep: Mapping[str, Any], baseline: Mapping[str, Any]) -> list[str]:
    """Regressions (empty = OK). Only like-for-like modes are compared."""
    if baseline.get("mode") != rep["mode"]:
        return []
    slack = {**{k: v[1] for k, v in REGRESSION_METRICS.items()}, **(baseline.get("slack") or {})}
    bad: list[str] = []
    for suite, cfgs in (baseline.get("tables") or {}).items():
        t = rep["tables"].get(suite) or {}
        rows = {r["config"]: r for r in t.get("rows") or []}
        for cfg, metrics in cfgs.items():
            cur = rows.get(cfg)
            if cur is None:
                continue
            for k, base in metrics.items():
                v = cur.get(k)
                if base is None or v is None or k not in REGRESSION_METRICS:
                    continue
                way = REGRESSION_METRICS[k][0]
                if (way == "max" and v > base + slack[k]) or (way == "min" and v < base - slack[k]):
                    bad.append(f"{suite}/{cfg}: {k} {v} vs baseline {base} (slack {slack[k]})")
    return bad


# ---------------------------------------------------------------- CLI


def live_ready() -> str | None:
    """None when the builder stage has a live provider, else the reason to refuse."""
    from services.agent import providers

    mode = providers.stage_mode("build")
    if mode != "live":
        return (
            f"no live provider for the builder (build stage mode: {mode}). Set a builder key in .env "
            "(BASETEN_API_KEY / FIREWORKS_API_KEY / TOGETHER_API_KEY / MODEL_API_KEY), check `make smoke`, "
            "or run without --live for the mock pipeline check."
        )
    return None


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m eval.run", description="PartSmith-Bench: full loop vs ground truth.")
    ap.add_argument("--suite", action="append", choices=ALL_SUITES, help="repeatable; default all")
    ap.add_argument("--configs", default=None, help=f"comma list from {', '.join(CONFIGS)}")
    ap.add_argument("--limit", type=int, default=None, help="synthetic samples (seeded subset; 0 = all 60)")
    ap.add_argument("--n-ref", type=int, default=None, help="reference-object renders (default: 4 in mock, all live)")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--jobs", type=int, default=min(4, os.cpu_count() or 1))
    ap.add_argument("--live", action="store_true", help="real providers (refuses without a live builder)")
    ap.add_argument("--from-runs", action="store_true", help="rebuild tables from eval/runs without re-running")
    ap.add_argument("--mode", choices=("mock", "live"), default=None, help="which stored runs --from-runs reads")
    ap.add_argument("--check-regression", action="store_true", help="exit 1 when worse than eval/baseline_metrics.json")
    ap.add_argument("--write-baseline", action="store_true", help="store this report's metrics as the baseline")
    ap.add_argument("--out", type=Path, default=None)
    a = ap.parse_args(argv)

    notes: list[str] = []
    scores: list[dict[str, Any]] = []
    mode = "live" if a.live else "mock"
    if a.from_runs:
        mode, scores = load_runs(a.mode)
        if scores:
            notes.append(f"tables rebuilt from {len(scores)} stored run(s) in eval/runs/{mode}/ (nothing re-run)")
        else:
            notes.append("no stored runs: ran a small synthetic subset with mock providers (6 samples) instead")
            a.limit = a.limit or 6
            mode = "mock"
    if not scores:
        if a.live:
            why = live_ready()
            if why:
                print(f"refusing --live: {why}", file=sys.stderr)
                return 2
        suites = a.suite or list(ALL_SUITES)
        default_cfgs = list(CONFIGS) if a.live else list(MOCK_CONFIGS)
        cfgs = [c.strip() for c in a.configs.split(",")] if a.configs else default_cfgs
        unknown = [c for c in cfgs if c not in CONFIGS]
        if unknown:
            print(f"unknown config(s) {unknown}", file=sys.stderr)
            return 2
        if not a.live:
            skipped = [c for c in cfgs if CONFIGS[c].routing_variant]
            cfgs = [c for c in cfgs if not CONFIGS[c].routing_variant]
            if skipped or not a.configs:
                notes.append(
                    "PS-open / PS-open-all are provider-routing variants: identical to PS with mock "
                    "providers, so they run only with --live"
                )
        limit = a.limit if a.limit is not None else (6 if not a.live else 12)
        n_ref = a.n_ref if a.n_ref is not None else (4 if not a.live else None)
        tasks, tnotes = collect_tasks(suites, cfgs, limit=limit or None, n_ref=n_ref, seed=a.seed, mode=mode)
        notes += tnotes
        print(f"{len(tasks)} runs ({mode}): {len(cfgs)} config(s) × {len(tasks) // max(len(cfgs), 1)} sample(s)")
        scores = run_tasks(tasks, jobs=a.jobs, live=a.live)
    out = a.out or REPORTS_DIR / dt.date.today().isoformat()
    rep = build_report(scores, mode, notes, out)
    jp, mp = write_report(rep, out, scores, a.seed, latest=a.out is None)
    for suite, t in rep["tables"].items():
        if t["status"] != "ok":
            print(f"{suite:18s} pending — {t['note']}")
            continue
        if suite in GATE_SUITES:
            h = t["headline"]
            extra = f"  false rejects {h['false_reject_rate']}" if suite == "control" else ""
            print(f"{suite:18s} handled as expected {h['correct']}/{h['n']} {h['ci95']}{extra}")
            for r in t["rows"]:
                if not r["correct"]:
                    print(
                        f"{'':18s}   ✗ {r['case']}: expected {r['expected']} ({r['expected_checks']}), got {r['outcome']} ({r['failed_checks']})"
                    )
            continue
        for r in t["rows"]:
            print(
                f"{suite:18s} {r['config']:16s} n={r['n']:3d} median {r['median_abs_err_mm']} mm  "
                f"mean {r['mean_abs_err_mm']} {r['mean_ci95']}  pass@0.5 {r['pass@0.5']} {r['pass@0.5_ci95']}  "
                f"verified {r['verified_rate']}  valid {r['valid_rate']}  iters {r['median_iters']}  "
                f"wall {r['median_wall_s']} s  ${r['usd_per_job']}"
            )
    if mode == "mock":
        print(f"NOTE: {MOCK_TITLE}")
    for suite, cfgs in rep["failure_taxonomy"].items():
        for cfg, c in cfgs.items():
            nz = {k: v for k, v in c.items() if k != "runs" and v}
            if nz:
                print(f"failures {suite}/{cfg}: " + ", ".join(f"{k} {v}" for k, v in nz.items()))
    print(
        f"wrote {jp.relative_to(REPO) if jp.is_relative_to(REPO) else jp}, {mp.name}, provenance.json, "
        "open_weights.json" + (" (+ eval/reports/latest/)" if a.out is None else "")
    )
    if a.write_baseline:
        BASELINE.write_text(json.dumps(baseline_from(rep), indent=1) + "\n")
        print(f"baseline written to {BASELINE.relative_to(REPO)}")
    if a.check_regression:
        if not BASELINE.exists():
            print("no eval/baseline_metrics.json; nothing to compare (write one with --write-baseline)")
            return 0
        base = json.loads(BASELINE.read_text())
        if base.get("mode") != mode:
            print(f"baseline mode {base.get('mode')!r} ≠ report mode {mode!r}: not comparable, skipped")
            return 0
        bad = check_regression(rep, base)
        for b in bad:
            print(f"REGRESSION {b}")
        if bad:
            return 1
        print("no regression against eval/baseline_metrics.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
