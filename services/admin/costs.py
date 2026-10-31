"""Job and model-cost aggregates computed from the `model_call` events of every non-replay job on this server.

Shared by `/status` and the admin overview, so both pages read the same numbers from the same code.
"""

from __future__ import annotations

from typing import Any

from services.agent.providers.routing import ENDPOINTS

SOURCE = "model_call events of every non-replay job on this server"

_call_cache: dict[str, list[dict[str, Any]]] = {}


def model_calls(job: Any) -> list[dict[str, Any]]:
    """model_call events of a job (cached once the job is finished)."""
    if job.id in _call_cache:
        return _call_cache[job.id]
    calls = [e.model_dump() for e in job.events if e.t == "model_call"]
    if job.finished:
        _call_cache[job.id] = calls
    return calls


def aggregate(summaries: list[Any], mgr: Any, *, recorded: bool = False) -> dict[str, Any]:
    """{"jobs": {total, verified}, "cost": {usd_total, usd_per_job_mean, n_jobs}, "model_calls": [...],
    "last_live_call_ts": {provider: ts}} over the non-replay jobs in `summaries` (`recorded=True`: over the recorded
    runs instead, kept apart so a played-back log never counts as this server's spend)."""
    jobs_total = jobs_verified = 0
    costs: list[float] = []
    agg: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    last_live: dict[str, float] = {}
    for s in summaries:
        if bool(s.is_replay) != recorded:
            continue
        jobs_total += 1
        jobs_verified += int(s.verified)
        costs.append(float(s.cost_usd))
        job = mgr.get(s.id) if mgr is not None else None
        for c in model_calls(job) if job is not None else []:
            key = (c["stage"], c["provider"], c["model"], c["mode"])
            a = agg.setdefault(
                key,
                {
                    "stage": c["stage"],
                    "provider": c["provider"],
                    "model": c["model"],
                    "mode": c["mode"],
                    "calls": 0,
                    "failed": 0,
                    "tokens_in": 0,
                    "tokens_out": 0,
                    "usd": 0.0,
                    "ms_total": 0,
                },
            )
            a["calls"] += 1
            a["failed"] += int(not c.get("ok", True))
            a["tokens_in"] += c.get("tokens_in", 0)
            a["tokens_out"] += c.get("tokens_out", 0)
            a["usd"] = round(a["usd"] + c.get("usd", 0.0), 6)
            a["ms_total"] += c.get("ms", 0)
            if c["mode"] == "live":
                last_live[c["provider"]] = max(last_live.get(c["provider"], 0.0), c.get("ts", 0.0))
    calls = sorted(agg.values(), key=lambda a: (a["stage"], -a["calls"]))
    for a in calls:
        a["ms_mean"] = round(a.pop("ms_total") / a["calls"]) if a["calls"] else None
        ep = ENDPOINTS.get(a["provider"])
        a["open_weights"] = bool(ep and ep.open_weights)
    return {
        "jobs": {"total": jobs_total, "verified": jobs_verified},
        "cost": {
            "usd_total": round(sum(costs), 6),
            "usd_per_job_mean": round(sum(costs) / len(costs), 6) if costs else None,
            "n_jobs": len(costs),
        },
        "model_calls": calls,
        "last_live_call_ts": last_live,
    }
