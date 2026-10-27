"""provenance.json: everything needed to tell where a report's numbers came from.

Model ids / providers / modes per stage (from the runs' model_call events), git sha, verifier thresholds (read from
the shared schemas, not retyped), seeds, dataset hashes and generator versions.
"""

from __future__ import annotations

import datetime as dt
import json
import subprocess
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
MANIFESTS = {
    "synthetic_bench": REPO / "data" / "synthetic" / "bench_manifest.json",
    "demo_samples": REPO / "data" / "synthetic" / "samples" / "manifest.json",
    "suite_control": REPO / "data" / "synthetic" / "suites" / "control" / "manifest.json",
    "suite_redteam": REPO / "data" / "synthetic" / "suites" / "redteam" / "manifest.json",
}


def git_sha() -> str | None:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=REPO, capture_output=True, text=True, timeout=5, check=True
        )
        return out.stdout.strip() or None
    except Exception:
        return None


def git_dirty() -> bool | None:
    try:
        out = subprocess.run(["git", "status", "--porcelain"], cwd=REPO, capture_output=True, text=True, timeout=10)
        return bool(out.stdout.strip())
    except Exception:
        return None


def thresholds() -> dict[str, Any]:
    from partsmith_schemas import common

    keys = ("HAUSDORFF_PASS_MM", "IOU_PASS", "FEATURE_TOL_MM", "BBOX_TOL_MM", "MIN_WALL_MM")
    out: dict[str, Any] = {k: getattr(common, k) for k in keys if hasattr(common, k)}
    try:
        from services.metrology import capture_gate as cg

        out["capture_gate"] = {
            k: getattr(cg, k)
            for k in dir(cg)
            if k.isupper() and isinstance(getattr(cg, k), int | float) and not k.startswith("_")
        }
    except Exception:
        pass
    return out


def stage_models(model_calls: Iterable[Mapping[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Per stage: each distinct (provider, model, mode) with its call count and tokens."""
    agg: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for c in model_calls:
        key = (str(c.get("stage")), str(c.get("provider")), str(c.get("model")), str(c.get("mode")))
        row = agg.setdefault(
            key,
            {
                "provider": key[1],
                "model": key[2],
                "mode": key[3],
                "calls": 0,
                "tokens_in": 0,
                "tokens_out": 0,
                "usd": 0.0,
            },
        )
        row["calls"] += 1
        row["tokens_in"] += int(c.get("tokens_in") or 0)
        row["tokens_out"] += int(c.get("tokens_out") or 0)
        row["usd"] = round(row["usd"] + float(c.get("usd") or 0.0), 6)
    out: dict[str, list[dict[str, Any]]] = {}
    for (stage, *_), row in sorted(agg.items()):
        out.setdefault(stage, []).append(row)
    return out


def manifest_hashes() -> dict[str, Any]:
    out: dict[str, Any] = {}
    for name, p in MANIFESTS.items():
        if not p.exists():
            out[name] = None
            continue
        m = json.loads(p.read_text())
        out[name] = {
            "file": str(p.relative_to(REPO)),
            "dataset_sha256": m.get("dataset_sha256"),
            "generator": m.get("generator"),
            "seed": m.get("seed"),
            "n_samples": len(m.get("samples") or []),
        }
    return out


def build(
    *,
    report: str,
    mode: str,
    model_calls: Iterable[Mapping[str, Any]] = (),
    seeds: Mapping[str, Any] | None = None,
    extra: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    from tools.synth import GENERATOR_VERSION

    try:
        from services.agent.templates import list_templates

        templates = {t.name: t.code_sha for t in list_templates()}
    except Exception:
        templates = {}
    return {
        "report": report,
        "generated_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "git_sha": git_sha(),
        "git_dirty": git_dirty(),
        "mode": mode,
        "stages": stage_models(model_calls),
        "thresholds": thresholds(),
        "seeds": dict(seeds or {}),
        "datasets": manifest_hashes(),
        "generator_versions": {"tools.synth": GENERATOR_VERSION},
        "template_code_sha": templates,
        **dict(extra or {}),
    }


def write(prov: Mapping[str, Any], *paths: Path) -> None:
    for p in paths:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(prov, indent=1, default=str) + "\n")
