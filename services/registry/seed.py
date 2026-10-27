"""Seed the registry ONLY from parts that went through the real pipeline.

For each committed synthetic sample (`data/synthetic/samples/<id>/`) the full agent pipeline runs
(`service.start_demo_job(id, sync=True)`), and a finished run is published with `service.publish` — its origin stays
`synthetic` and the part page says so. Real captures in `data/real/<id>/` (top.jpg [+ side.jpg, mating.jpg] and
meta.json) go through `service.start_fix_job` the same way with origin `real`. Each seeded run is also exported as a
labelled replay (`data/replays/<job_id>/`) so the judge path works on a fresh clone.

Verified runs are always published; best-effort runs only up to `MAX_PUBLISH_ERROR_MM` (every finished run is still
exported as a replay). Idempotent: a sample whose slug is in the registry, or that ran before without being published
(`$PARTSMITH_HOME/seed_state.json`; `--retry` re-runs those), is skipped; an existing replay for a sample is kept.

    uv run python -m services.registry.seed [--if-empty] [--refresh-replays]
"""

from __future__ import annotations

import argparse
import importlib
import json
import re
import shutil
from collections.abc import Callable
from pathlib import Path
from types import ModuleType
from typing import Any

from partsmith_schemas import DataOrigin, JobInput
from partsmith_schemas.partspec import Family

from services.agent import jobs
from services.common.paths import REPO_ROOT, home
from services.registry import parts as P
from services.registry.publish import dedupe_published, publish_part
from services.registry.store import Registry, get_registry

REAL_DIR = REPO_ROOT / "data" / "real"
SAMPLES_DIR = REPO_ROOT / "data" / "synthetic" / "samples"
INDEX_NAME = "seed_index.json"  # sample id -> replay job id, next to the replays
MAX_PUBLISH_ERROR_MM = 2.0  # best-effort runs worse than this are not published (still exported as replays)


def _service() -> ModuleType:
    return importlib.import_module("services.agent.service")


def slug_for(sample_id: str) -> str:
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", sample_id.lower())).strip("-")[:80] or "part"


def _index_path() -> Path:
    return jobs.REPLAYS_DIR / INDEX_NAME


def _read_index() -> dict[str, str]:
    p = _index_path()
    try:
        data = json.loads(p.read_text()) if p.exists() else {}
    except json.JSONDecodeError:
        data = {}
    return {str(k): str(v) for k, v in data.items()}


def _write_index(index: dict[str, str]) -> None:
    p = _index_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(dict(sorted(index.items())), indent=1) + "\n")


def _state_path() -> Path:
    return home() / "seed_state.json"


def _read_state() -> dict[str, Any]:
    p = _state_path()
    try:
        return dict(json.loads(p.read_text())) if p.exists() else {}
    except json.JSONDecodeError:
        return {}


def _write_state(state: dict[str, Any], sid: str, job_id: str, reason: str) -> None:
    state[sid] = {"job_id": job_id, "reason": reason}
    _state_path().write_text(json.dumps(state, indent=1))


def _real_samples() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if not REAL_DIR.exists():
        return out
    for d in sorted(REAL_DIR.iterdir()):
        if (d / "top.jpg").exists() and (d / "meta.json").exists():
            meta = json.loads((d / "meta.json").read_text())
            out.append({"id": d.name, "title": meta.get("title", d.name), "dir": d, "meta": meta})
    return out


def _run_real(svc: ModuleType, sample: dict[str, Any]) -> Any:
    d: Path = sample["dir"]
    meta: dict[str, Any] = sample["meta"]
    photos = {v: (d / f"{v}.jpg").read_bytes() for v in ("top", "side", "mating") if (d / f"{v}.jpg").exists()}
    hint = meta.get("family_hint")
    job_input = JobInput(
        intent=str(meta.get("intent", "")),
        mat_kind=meta.get("mat_kind", "screen"),
        thickness_mm=meta.get("user_thickness_mm"),
        family_hint=Family(str(hint)) if hint in Family.__members__ else None,
        origin=DataOrigin.real,
    )
    return svc.start_fix_job(photos, job_input, sync=True)


def seed(
    if_empty: bool = False,
    *,
    include_real: bool = True,
    export_replays: bool = True,
    refresh_replays: bool = False,
    only: list[str] | None = None,
    max_error_mm: float | None = MAX_PUBLISH_ERROR_MM,
    retry: bool = False,
    reg: Registry | None = None,
    log: Callable[[str], None] = print,
) -> dict[str, list[str]]:
    """Run every sample through the pipeline and publish the finished runs. Returns
    `{"seeded": [slug], "skipped": [slug], "failed": [sample id: reason]}`. Verified runs are always published;
    best-effort runs only when their max error is at most `max_error_mm` (None = publish every finished run)."""
    reg = reg or get_registry()
    result: dict[str, list[str]] = {"seeded": [], "skipped": [], "failed": []}
    if if_empty and reg.slugs():
        log(f"registry already has {len(reg.slugs())} parts; --if-empty → nothing to do")
        return result
    svc = _service()
    committed = {d.name for d in SAMPLES_DIR.iterdir()} if SAMPLES_DIR.exists() else set()
    samples: list[dict[str, Any]] = [
        dict(s, kind="synthetic") for s in svc.list_demo_samples() if not committed or s["id"] in committed
    ]  # only the committed demo set (data/synthetic/bench is for the benchmark, not the registry)
    if include_real:
        samples += [dict(s, kind="real") for s in _real_samples()]
    if only:
        samples = [s for s in samples if s["id"] in only]
    index = _read_index()
    state = _read_state()
    for s in samples:
        sid, slug = str(s["id"]), slug_for(str(s["id"]))
        existing = reg.get_part(slug)
        if existing is not None:
            result["skipped"].append(slug)
            P.after_publish(existing, reg=reg)  # cheap when the thumbnail is current
            continue
        if sid in state and not retry:  # ran before and was not published: do not spend the run again
            result["skipped"].append(slug)
            continue
        log(f"seeding {sid} ({s['kind']}) …")
        try:
            job = svc.start_demo_job(sid, sync=True) if s["kind"] == "synthetic" else _run_real(svc, s)
        except Exception as exc:  # one broken sample must not stop the seed
            result["failed"].append(f"{sid}: {type(exc).__name__}: {exc}")
            continue
        if job.summary.status != "done":
            result["failed"].append(f"{sid}: job {job.id} ended {job.summary.status}")
            _write_state(state, sid, job.id, f"ended {job.summary.status}")
            continue
        err = job.summary.max_error_mm
        if export_replays:
            _export(job, sid, index, refresh_replays)
        if not job.summary.verified and max_error_mm is not None and (err is None or err > max_error_mm):
            shown = f"{err:.2f} mm" if err is not None else "unknown"
            reason = f"best effort {shown} > {max_error_mm:g} mm, not published"
            result["failed"].append(f"{sid}: {reason}")
            _write_state(state, sid, job.id, reason)
            continue
        try:
            part = svc.publish(job.id, slug=slug)
        except Exception as exc:
            result["failed"].append(f"{sid}: publish failed: {type(exc).__name__}: {exc}")
            continue
        outcome = dedupe_published(part.slug, reg=reg) if reg.get_part(part.slug) else publish_part(part, reg=reg)
        result["seeded"].append(outcome.part.slug)
        if outcome.part.slug != slug:  # folded into an identical existing part: remember, so it is not re-run
            _write_state(state, sid, job.id, f"published as {outcome.part.slug} ({outcome.action})")
        log(
            f"  → {part.slug}: {part.status}"
            + (
                f", max error {part.verification.max_error_mm:.3f} mm"
                if part.verification and part.verification.max_error_mm is not None
                else ""
            )
        )
    return result


def _export(job: jobs.Job, sid: str, index: dict[str, str], refresh: bool) -> None:
    """Export the run as a labelled replay unless this sample already has one (or `refresh`)."""
    old = index.get(sid)
    if old and (jobs.REPLAYS_DIR / old).exists() and not refresh:
        return
    if old and old != job.id and (jobs.REPLAYS_DIR / old).exists():
        shutil.rmtree(jobs.REPLAYS_DIR / old)
    jobs.export_replay(job)
    index[sid] = job.id
    _write_index(index)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0] if __doc__ else "seed the registry")
    ap.add_argument("--if-empty", action="store_true", help="do nothing when the registry already has parts")
    ap.add_argument("--refresh-replays", action="store_true", help="re-export replays even when one exists")
    ap.add_argument("--no-real", action="store_true", help="skip data/real")
    ap.add_argument("--only", nargs="*", help="sample ids to seed")
    ap.add_argument("--retry", action="store_true", help="re-run samples that ran before but were not published")
    ap.add_argument(
        "--max-error-mm",
        type=float,
        default=MAX_PUBLISH_ERROR_MM,
        help="publish best-effort runs up to this max error (verified runs always publish)",
    )
    a = ap.parse_args(argv)
    out = seed(
        a.if_empty,
        include_real=not a.no_real,
        refresh_replays=a.refresh_replays,
        only=a.only,
        max_error_mm=a.max_error_mm,
        retry=a.retry,
    )
    print(json.dumps(out, indent=1))
    return 1 if out["failed"] and not out["seeded"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
