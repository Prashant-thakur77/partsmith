"""The feedback log: every piece of feedback a reviewer gave, why they gave it, and what happened next.

It is read from the review chains (`store`), never kept as a second copy: one entry per pin note, general note, pasted
picture, rejection and acceptance. What happened next is measured by code — the reviewer round's mismatch at the pin
before and after (`review_round.json`), or the round's worst gap before and after — never judged by a model.

Fixed feedback from a person (not a test) is what later jobs of the same family are given (`for_prompt`); each job
records which entries it was given (`feedback_used.json`), so the log shows whether a lesson held or the mistake came
back.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any, Literal

from services.common import blobs, paths
from services.review import store

Outcome = Literal["fixed", "better", "not_fixed", "waiting", "not_measured", "rejected", "accepted"]
DEFAULT_LIMIT_MM = 0.5
PROMPT_ITEMS = 5  # past fixed feedback given to a new job of the same family


def classify(before_mm: float | None, after_mm: float | None, limit_mm: float, *, next_done: bool) -> Outcome:
    """Code's reading of one change: fixed (now within the limit), better (smaller, still over), not fixed."""
    if not next_done:
        return "waiting"
    if before_mm is None or after_mm is None:
        return "not_measured"
    if after_mm <= limit_mm:
        return "fixed"
    return "better" if after_mm < before_mm else "not_fixed"


def explain(outcome: str, before_mm: float | None, limit_mm: float, *, passed_next: bool = False) -> str:
    """The outcome in words, with the rule that set it (shown next to the label, so "fixed" never needs guessing)."""
    if outcome == "fixed":
        if passed_next:
            return "fixed: the next round passed verification"
        if before_mm is not None and before_mm <= limit_mm:
            return f"fixed: the gap is within the {limit_mm:.2f} mm limit (it already was before this round)"
        return f"fixed: the gap is now within the {limit_mm:.2f} mm limit"
    return {
        "better": f"better: the gap shrank but is still over the {limit_mm:.2f} mm limit",
        "not_fixed": "not fixed: the gap did not shrink",
        "waiting": "waiting: the next round has not finished",
        "not_measured": "not measured: no gap to compare here",
    }.get(outcome, "")


def _limit(job: Any) -> float:
    v = job.read_json("verification.json") if job is not None else None
    t = (v or {}).get("thresholds") or {}
    return float(t.get("hausdorff_mm") or DEFAULT_LIMIT_MM)


def _photo(job: Any) -> str | None:
    from services.review.images import top_rectified_key

    key = top_rectified_key(job) if job is not None else None
    return blobs.url(key) if key else None


def _entries(
    state: Mapping[str, Any], mgr: Any, used: Mapping[str, list[str]], decisions: Mapping[str, str]
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    rounds = list(state.get("rounds") or [])
    for rnd in rounds:
        action = rnd.get("decision")
        if not action:
            continue
        job = store._get(mgr, str(rnd["job_id"]))
        child_id = rnd.get("child_job")
        child = store._get(mgr, str(child_id)) if child_id else None
        child_done = bool(child is not None and child.finished)
        limit = _limit(job)
        verdict = rnd.get("verdict") or store._verdict(job)
        nxt = store._verdict(child) if child is not None else None
        base = {
            "root_job": state["root_job"],
            "job_id": rnd["job_id"],
            "round": rnd["round"],
            "family": store._family(job) if job is not None else None,
            "title": job.summary.title if job is not None else "",
            "by": rnd.get("by", "person"),
            "at": rnd.get("at"),
            "why": rnd.get("why", ""),
            "photo": _photo(job),
            "verdict": verdict,
            "next_job": child_id,
            "next_verdict": nxt,
            "limit_mm": limit,
            "lesson_ids": list(rnd.get("lesson_ids") or []),
        }
        items: list[dict[str, Any]] = []
        if action == "improve":
            got = store._outcomes(mgr, child_id)
            for p in rnd.get("pins") or []:
                o = got.get(int(p["id"]), {})
                b, a = o.get("before_mm"), o.get("after_mm")
                items.append(
                    {
                        "kind": "pin",
                        "what": p.get("note", ""),
                        "where": {"pin": p["id"], "u": p["u"], "v": p["v"], "mat_mm": o.get("mat_mm")},
                        "before_mm": b,
                        "after_mm": a,
                        "outcome": classify(b, a, limit, next_done=child_done),
                    }
                )
                items[-1]["outcome_why"] = explain(items[-1]["outcome"], b, limit)
            b = verdict.get("max_error_mm") if isinstance(verdict, Mapping) else None
            a = nxt.get("max_error_mm") if child_done and nxt else None
            general = classify(b, a, limit, next_done=child_done)
            passed = bool(child_done and nxt and nxt.get("verified"))
            if passed:
                general = "fixed"  # the next round passed the verifier as a whole
            general_why = explain(general, b, limit, passed_next=passed)
            if rnd.get("note"):
                items.append(
                    {
                        "kind": "note",
                        "what": rnd["note"],
                        "where": None,
                        "before_mm": b,
                        "after_mm": a,
                        "outcome": general,
                        "outcome_why": general_why,
                    }
                )
            for url in [blobs.url(str(k)) for k in rnd.get("attachments") or [] if store._blob_ok(str(k))]:
                items.append(
                    {"kind": "picture", "what": "a reference picture", "picture": url, "where": None, "before_mm": b,
                     "after_mm": a, "outcome": general, "outcome_why": general_why}
                )  # fmt: skip
        elif action == "reject":
            items.append({"kind": "reject", "what": rnd.get("reason", ""), "where": None, "outcome": "rejected"})
        else:
            items.append(
                {"kind": "accept", "what": rnd.get("note", "") or "accepted", "where": None, "outcome": "accepted"}
            )
        for n, it in enumerate(items, 1):
            fid = f"{state['root_job']}/{rnd['round']}/{it['kind']}{n}"
            later = used.get(fid, [])
            got_decisions = [decisions.get(j) for j in later]
            out.append(
                {
                    "id": fid,
                    **base,
                    "before_mm": None,
                    "after_mm": None,
                    **it,
                    "used_in": {
                        "jobs": len(set(later)),
                        "accepted": got_decisions.count("accept"),
                        "improved": got_decisions.count("improve"),
                        "rejected": got_decisions.count("reject"),
                    },
                }
            )
    return out


def _used_by() -> dict[str, list[str]]:
    """feedback id -> the jobs whose prompts carried it (feedback_used.json in each run directory and replay)."""
    from services.agent import jobs

    out: dict[str, list[str]] = {}
    for base in (paths.runs_dir(), jobs.REPLAYS_DIR):
        if not base.exists():
            continue
        for f in base.glob("*/feedback_used.json"):
            try:
                ids = json.loads(f.read_text(encoding="utf-8")).get("ids") or []
            except (OSError, ValueError, AttributeError):
                continue
            for fid in ids:
                out.setdefault(str(fid), []).append(f.parent.name)
    return out


def feedback(
    *, family: str | None = None, outcome: str | None = None, by: str | None = None, svc: Any = None
) -> dict[str, Any]:
    """Every feedback entry, newest first, with counts per outcome. Filters are exact matches."""
    mgr = store._svc(svc).manager()
    decisions: dict[str, str] = {}
    states = store._all_states()
    for st in states:
        for r in st.get("rounds") or []:
            if r.get("decision") and r.get("by", "person") == "person":
                decisions[str(r["job_id"])] = str(r["decision"])
    used = _used_by()
    items = [e for st in states for e in _entries(st, mgr, used, decisions)]
    items = [
        e
        for e in items
        if (family is None or e["family"] == family) and (outcome is None or e["outcome"] == outcome)
        and (by is None or e["by"] == by)
    ]  # fmt: skip
    items.sort(key=lambda e: -float(e.get("at") or 0.0))
    counts: dict[str, int] = {}
    for e in items:
        counts[e["outcome"]] = counts.get(e["outcome"], 0) + 1
    return {"items": items, "counts": counts, "families": sorted({str(e["family"]) for e in items if e["family"]})}


def for_prompt(
    family: str, *, exclude_roots: Sequence[str] = (), limit: int = PROMPT_ITEMS, svc: Any = None
) -> list[dict[str, Any]]:
    """Past feedback a new `family` job is given: a person's (never a test's), measured as fixed, with the reason —
    newest first. Feedback from the job's own review chain is left out (it already has those notes)."""
    try:
        items = feedback(family=family, by="person", svc=svc)["items"]
    except Exception:
        return []
    out = [e for e in items if e["outcome"] == "fixed" and e["kind"] in ("pin", "note") and e["what"]
           and e["root_job"] not in exclude_roots]  # fmt: skip
    return out[:limit]


def prompt_line(e: Mapping[str, Any]) -> str:
    """One past-feedback line for a builder or fixer prompt."""
    why = f' — why: "{e["why"]}"' if e.get("why") else ""
    measured = (
        f" (gap {e['before_mm']:.2f} → {e['after_mm']:.2f} mm)"
        if e.get("before_mm") is not None and e.get("after_mm") is not None
        else ""
    )
    return f'A person reviewing an earlier {e["family"]} part said: "{e["what"]}"{why}; fixed{measured}'
