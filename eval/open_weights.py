"""Open-weights evidence (eval/reports/latest/open_weights.json), built only from recorded model_call events.

Per stage: which model and provider served it, whether that model is open weights (from the provider routing table),
calls and tokens; the share of builder (build + fix) tokens served by open weights; the PS-open / PS-open-all bench rows
when those runs exist, otherwise "pending live run". Mock calls are reported as mock: they show the routing, not usage.
"""

from __future__ import annotations

import gzip
import json
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

BUILDER_STAGES = ("build", "fix", "fix_agent", "plan")  # the builder model: plan, write and fix the program
OPEN_CONFIGS = ("PS-open", "PS-open-all")


def open_weights_lookup() -> tuple[dict[str, bool], dict[str, bool]]:
    """(model id → open weights, provider/endpoint name → open weights) from the routing table."""
    from services.agent.providers import routing

    models: dict[str, bool] = {}
    endpoints: dict[str, bool] = {}
    for v in vars(routing).values():
        if isinstance(v, routing.Route):
            models[v.model] = bool(v.endpoint.open_weights)
            endpoints[v.endpoint.name] = bool(v.endpoint.open_weights)
    return models, endpoints


def is_open(provider: str, model: str, lookup: tuple[dict[str, bool], dict[str, bool]] | None = None) -> bool | None:
    models, endpoints = lookup or open_weights_lookup()
    if model in models:
        return models[model]
    if provider in endpoints:
        return endpoints[provider]
    return None


def read_model_calls(run_dirs: Iterable[Path]) -> list[dict[str, Any]]:
    """model_call events from stored runs (run.jsonl.gz), each tagged with the run's config."""
    out: list[dict[str, Any]] = []
    for d in run_dirs:
        p = d / "run.jsonl.gz"
        if not p.exists():
            continue
        cfg = d.parent.name
        with gzip.open(p, "rt", encoding="utf-8") as fh:
            for line in fh:
                e = json.loads(line)
                if e.get("t") == "model_call":
                    out.append({**e, "config": cfg})
    return out


def build(calls: Sequence[Mapping[str, Any]], table_rows: Mapping[str, Sequence[Mapping[str, Any]]]) -> dict[str, Any]:
    lookup = open_weights_lookup()
    stages: dict[str, dict[str, Any]] = {}
    for c in calls:
        st = stages.setdefault(str(c.get("stage")), {"models": {}, "calls": 0, "tokens": 0, "open_tokens": 0})
        tok = int(c.get("tokens_in") or 0) + int(c.get("tokens_out") or 0)
        ow = is_open(str(c.get("provider")), str(c.get("model")), lookup)
        key = f"{c.get('provider')}:{c.get('model')}"
        m = st["models"].setdefault(
            key,
            {
                "provider": c.get("provider"),
                "model": c.get("model"),
                "open_weights": ow,
                "modes": [],
                "calls": 0,
                "tokens": 0,
            },
        )
        m["calls"] += 1
        m["tokens"] += tok
        if c.get("mode") not in m["modes"]:
            m["modes"].append(c.get("mode"))
        st["calls"] += 1
        st["tokens"] += tok
        st["open_tokens"] += tok if ow else 0
    for st in stages.values():
        st["models"] = list(st["models"].values())
    # mock calls show the routing but are never counted as evidence (same rule as providers.open_weights_summary)
    builder = [c for c in calls if c.get("stage") in BUILDER_STAGES and c.get("mode") != "mock"]
    b_tok = sum(int(c.get("tokens_in") or 0) + int(c.get("tokens_out") or 0) for c in builder)
    b_open = sum(
        int(c.get("tokens_in") or 0) + int(c.get("tokens_out") or 0)
        for c in builder
        if is_open(str(c.get("provider")), str(c.get("model")), lookup)
    )
    b_calls_open = sum(1 for c in builder if is_open(str(c.get("provider")), str(c.get("model")), lookup))
    modes = sorted({str(c.get("mode")) for c in calls})
    live = "live" in modes
    rows: dict[str, Any] = {}
    for suite, rs in table_rows.items():
        for r in rs:
            if r.get("config") in OPEN_CONFIGS:
                rows.setdefault(suite, []).append(dict(r))
    summary: Any = None
    try:
        from services.agent import providers

        fn = getattr(providers, "open_weights_summary", None)
        summary = fn(list(calls)) if callable(fn) else None
    except Exception:
        summary = None
    return {
        "modes": modes,
        "mock_calls": sum(1 for c in calls if c.get("mode") == "mock"),
        "providers_summary": summary,
        "label": "live model calls" if live else "MOCK calls only: shows the routing, not real usage",
        "stages": stages,
        "builder": {
            "stages": list(BUILDER_STAGES),
            "calls": len(builder),
            "calls_on_open_weights": b_calls_open,
            "tokens": b_tok,
            "tokens_on_open_weights": b_open,
            "share_tokens_open_weights": (b_open / b_tok) if b_tok else None,
            "share_calls_open_weights": (b_calls_open / len(builder)) if builder else None,
            "note": "live and replay calls only; mock calls are excluded",
        },
        "open_configs": rows if rows else "pending live run",
    }
