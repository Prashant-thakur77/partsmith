"""Admin overview: one call that sums up the site, every number computed here from stored data.

Jobs, pass rate, rounds to verify and the max-error spread come from the non-replay jobs on this server; send-back
reasons from the review feedback log (a person's and a test's kept apart: test reviews never count as people);
queue size from the review store; parts and requests from the registry; cost from `model_call` events; today's spend
against the cap from the provider budget. Each block carries its `n` and a `source`.
"""

from __future__ import annotations

import math
import re
import time
from collections import Counter
from collections.abc import Sequence
from typing import Any

from services.admin import costs

JOBS_SOURCE = "non-replay fix jobs on this server (job summaries)"
TOP_REASONS = 8


def percentile(values: Sequence[float], q: float) -> float | None:
    """Nearest-rank percentile (q in 0..100) of `values`; None when empty."""
    xs = sorted(values)
    if not xs:
        return None
    k = max(1, math.ceil(q / 100 * len(xs)))
    return float(xs[k - 1])


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower()).rstrip(".!")


def reasons(items: Sequence[dict[str, Any]], limit: int = TOP_REASONS) -> dict[str, Any]:
    """Top send-back reasons (pin notes, general notes, reject reasons) by who gave them."""
    out: dict[str, Any] = {}
    for who in ("person", "test"):
        texts = [
            str(e["what"])
            for e in items
            if e.get("by", "person") == who
            and e.get("kind") in ("pin", "note", "reject")
            and str(e.get("what") or "").strip()
        ]
        shown: dict[str, str] = {}
        for t in texts:
            shown.setdefault(_norm(t), t.strip())
        counts = Counter(_norm(t) for t in texts)
        out[who] = {
            "n": len(texts),
            "top": [{"reason": shown[k], "count": c} for k, c in counts.most_common(limit)],
        }
    out["source"] = "review feedback log: pin notes, general notes and reject reasons"
    return out


def overview(svc: Any) -> dict[str, Any]:
    from services.agent import providers
    from services.registry.store import ROLE_REFERENCE_TAG, get_registry
    from services.review import ledger
    from services.review import store as review_store

    try:
        mgr = svc.manager()
        summaries = list(mgr.list(100_000))
    except Exception:
        mgr, summaries = None, []
    live = [s for s in summaries if not s.is_replay]
    fix = [s for s in live if s.kind == "fix"]
    finished = [s for s in fix if s.status in ("done", "failed")]
    verified = [s for s in finished if s.verified]
    rounds = Counter(int(s.iterations) for s in verified)
    errs = [float(s.max_error_mm) for s in finished if s.max_error_mm is not None]
    totals = costs.aggregate(summaries, mgr)

    by_stage: dict[str, dict[str, Any]] = {}
    for c in totals["model_calls"]:
        b = by_stage.setdefault(c["stage"], {"stage": c["stage"], "calls": 0, "usd": 0.0})
        b["calls"] += c["calls"]
        b["usd"] = round(b["usd"] + c["usd"], 6)
    by_model: dict[tuple[str, str], dict[str, Any]] = {}
    for c in totals["model_calls"]:
        m = by_model.setdefault((c["provider"], c["model"]), {"provider": c["provider"], "model": c["model"],
                                                               "calls": 0, "usd": 0.0, "modes": []})  # fmt: skip
        m["calls"] += c["calls"]
        m["usd"] = round(m["usd"] + c["usd"], 6)
        if c["mode"] not in m["modes"]:
            m["modes"].append(c["mode"])

    try:
        fb = ledger.feedback(svc=svc)["items"]
    except Exception:
        fb = []
    try:
        queue = review_store.queue(10_000, True, svc=svc)
    except Exception:
        queue = []
    qcount = Counter(i["status"] for i in queue)

    reg = get_registry()
    parts_all, _ = reg.search("", limit=1_000_000, include_withdrawn=True)
    withdrawn = reg.withdrawn()
    reference = [p for p in parts_all if ROLE_REFERENCE_TAG in p.tags]
    listed = [p for p in parts_all if ROLE_REFERENCE_TAG not in p.tags and p.slug not in withdrawn]
    needs = reg.needs(100_000)
    ncount = Counter(n.status for n in needs)

    return {
        "generated_at": time.time(),
        "mode": providers.overall_mode(),
        "jobs": {
            "total": len(fix),
            "finished": len(finished),
            "verified": len(verified),
            "pass_rate": round(len(verified) / len(finished), 4) if finished else None,
            "n": len(finished),
            "replays_excluded": sum(1 for s in summaries if s.is_replay),
            "source": JOBS_SOURCE + "; pass rate = verified / finished (done or failed)",
        },
        "rounds_to_verify": {
            "buckets": [{"rounds": r, "count": rounds[r]} for r in sorted(rounds)],
            "median": percentile([float(s.iterations) for s in verified], 50),
            "n": len(verified),
            "source": JOBS_SOURCE + ": fix rounds of each verified job",
        },
        "max_error": {
            "median_mm": percentile(errs, 50),
            "p90_mm": percentile(errs, 90),
            "n": len(errs),
            "source": JOBS_SOURCE + ": max error of each finished job (nearest-rank percentiles)",
        },
        "send_back": reasons(fb),
        "review": {
            "waiting": qcount.get("waiting", 0),
            "improving": qcount.get("improving", 0),
            "accepted": qcount.get("accepted", 0),
            "rejected": qcount.get("rejected", 0),
            "waiting_replays": sum(1 for i in queue if i["status"] == "waiting" and i.get("is_replay")),
            "n": len(queue),
            "source": "review store: one item per chain (replays included and counted apart)",
        },
        "registry": {
            "published": len(listed),
            "withdrawn": len(withdrawn),
            "reference": len(reference),
            "n": len(parts_all),
            "source": "registry records (reference objects and withdrawn parts counted apart)",
        },
        "needs": {
            "open": ncount.get("open", 0),
            "in_progress": ncount.get("in_progress", 0),
            "fulfilled": ncount.get("fulfilled", 0),
            "n": len(needs),
            "source": "registry requests",
        },
        "cost": {
            **totals["cost"],
            "by_stage": sorted(by_stage.values(), key=lambda b: -b["usd"]),
            "by_model": sorted(by_model.values(), key=lambda m: -m["usd"]),
            "model_calls": totals["model_calls"],
            "source": costs.SOURCE,
        },
        "budget": providers.budget.snapshot(),
    }
