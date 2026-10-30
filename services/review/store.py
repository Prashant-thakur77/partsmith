"""Review state and decisions: a chain of reviewer rounds per first job, stored under `$PARTSMITH_HOME/reviews/`.

`<root_job>.json` holds the rounds `{round, job_id, decision, at, note, reason, pins, child_job, verdict, judge, ...}`
and the chain's status follows from them: `waiting` (the latest round is finished and undecided), `improving` (its
reviewer round is still running), `accepted`, `rejected`. Jobs stay immutable: improving starts a new linked job
(`service.start_review_job`), and nothing is ever written into a job's directory here (a replay's least of all).

Accept is a person's sign-off kept next to the code's verdict, never instead of it: nothing here sets `verified`.
Every number shown (pin mismatch before/after, agreement, kappa) is read from what code measured or counted.
"""

from __future__ import annotations

import importlib
import json
import re
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any, Literal

from partsmith_schemas import Pin, RuleChoice

from services.common import paths

Action = Literal["accept", "improve", "reject"]
Status = Literal["waiting", "improving", "accepted", "rejected"]
Publisher = Callable[[str, str], "str | None"]  # (job_id, provenance note) -> published part slug

MAX_PINS = 20
MAX_NOTE = 1000
MAX_REASON = 500
LIST_LIMIT = 500  # jobs scanned for the queue
CHAIN_MAX = 50
ACCEPTED_NOTE = "best effort, accepted by a person"
_ID_RE = re.compile(r"^[A-Za-z0-9_.-]{1,80}$")

_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


class ReviewError(Exception):
    """A review request code refuses: HTTP status + a stable error code (the API maps it to its envelope)."""

    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


# ------------------------------------------------------------------------------------------------- plumbing


def _svc(svc: Any) -> Any:
    return svc if svc is not None else importlib.import_module("services.agent.service")


def reviews_dir() -> Path:
    return paths.sub("reviews")


def _path(root: str) -> Path:
    if not _ID_RE.match(root):
        raise ReviewError(404, "job_not_found", f"no job {root!r}")
    return reviews_dir() / f"{root}.json"


def _lock(root: str) -> threading.Lock:
    with _locks_guard:
        return _locks.setdefault(root, threading.Lock())


def _load(root: str) -> dict[str, Any] | None:
    p = _path(root)
    return dict(json.loads(p.read_text(encoding="utf-8"))) if p.exists() else None


def _save(state: dict[str, Any]) -> None:
    p = _path(str(state["root_job"]))
    tmp = p.with_name(f".{p.name}.{threading.get_ident()}.tmp")
    tmp.write_text(json.dumps(state, indent=2, default=str), encoding="utf-8")
    tmp.replace(p)


def _all_states() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for p in sorted(reviews_dir().glob("*.json")):
        try:
            out.append(dict(json.loads(p.read_text(encoding="utf-8"))))
        except (OSError, ValueError):
            continue
    return out


def _get(mgr: Any, job_id: str) -> Any:
    return mgr.get(job_id) if job_id else None


def _root_of(mgr: Any, job: Any) -> str:
    """The first job of a chain: follow `parent_job` links up (bounded)."""
    cur = job
    for _ in range(CHAIN_MAX):
        parent = getattr(cur.input, "parent_job", None)
        if not parent:
            return str(cur.id)
        nxt = _get(mgr, parent)
        if nxt is None:
            return str(parent)
        cur = nxt
    return str(cur.id)


def _done(job: Any) -> Any:
    return next((e for e in reversed(job.events) if e.t == "done"), None)


def reviewable(job: Any) -> bool:
    """A finished fix job with a model to look at: done (verified or best effort), not a reference check."""
    if job.summary.kind != "fix" or not job.finished or job.summary.status != "done":
        return False
    if getattr(job.input, "purpose", "repair") == "reference_check":
        return False
    d = _done(job)
    return d is not None and d.status in ("verified", "best_effort")


def _new_round(n: int, job_id: str) -> dict[str, Any]:
    return {
        "round": n,
        "job_id": job_id,
        "decision": None,
        "at": None,
        "note": "",
        "reason": "",
        "pins": [],
        "child_job": None,
        "verdict": None,
        "judge": None,
    }


def _state(mgr: Any, root: str) -> dict[str, Any]:
    """The stored chain, or a fresh one-round chain for a job nobody reviewed yet."""
    state = _load(root)
    if state is None:
        state = {"root_job": root, "rounds": [_new_round(1, root)], "created_at": time.time(), "updated_at": 0.0}
    return state


def _verdict(job: Any) -> dict[str, Any]:
    v = job.read_json("verification.json") if job is not None else None
    if not v:
        status = job.summary.status if job is not None else "missing"
        return {"status": status, "verified": False, "max_error_mm": None}
    return {"status": v.get("status"), "verified": bool(v.get("verified")), "max_error_mm": v.get("max_error_mm")}


def _judge(job: Any) -> dict[str, Any] | None:
    data = job.read_json("judge.json") if job is not None else None
    return dict(data) if isinstance(data, Mapping) else None


def _family(job: Any) -> str | None:
    spec = job.read_json("partspec.json") if job is not None else None
    if isinstance(spec, Mapping) and spec.get("family"):
        return str(spec["family"])
    d = _done(job) if job is not None else None
    fam = d.summary.get("family") if d is not None else None
    return str(fam) if fam else None


def _status(mgr: Any, state: Mapping[str, Any]) -> Status:
    last = state["rounds"][-1]
    if last["decision"] == "accept":
        return "accepted"
    if last["decision"] == "reject":
        return "rejected"
    job = _get(mgr, str(last["job_id"]))
    return "improving" if job is not None and not job.finished else "waiting"


def _outcomes(mgr: Any, child_id: str | None) -> dict[int, dict[str, Any]]:
    """Pin outcomes (mm positions, before/after mismatch) the reviewer round `child_id` measured, by pin id."""
    child = _get(mgr, child_id) if child_id else None
    data = child.read_json("review_round.json") if child is not None else None
    if not isinstance(data, Mapping):
        return {}
    return {int(p["id"]): dict(p) for p in data.get("pins") or [] if isinstance(p, Mapping) and "id" in p}


def _pins_out(mgr: Any, rnd: Mapping[str, Any]) -> list[dict[str, Any]]:
    got = _outcomes(mgr, rnd.get("child_job"))
    out: list[dict[str, Any]] = []
    for p in rnd.get("pins") or []:
        o = got.get(int(p["id"]), {})
        out.append(
            {
                "id": p["id"],
                "u": p["u"],
                "v": p["v"],
                "note": p.get("note", ""),
                "mat_mm": o.get("mat_mm"),
                "before_mm": o.get("before_mm"),
                "after_mm": o.get("after_mm"),
            }
        )
    return out


def _round_out(mgr: Any, rnd: Mapping[str, Any]) -> dict[str, Any]:
    job = _get(mgr, str(rnd["job_id"]))
    decided = rnd.get("decision") is not None
    s = job.summary if job is not None else None
    return {
        "round": rnd["round"],
        "job_id": rnd["job_id"],
        "decision": rnd.get("decision"),
        "at": rnd.get("at"),
        "note": rnd.get("note", ""),
        "reason": rnd.get("reason", ""),
        "pins": _pins_out(mgr, rnd),
        "verdict": rnd.get("verdict") if decided and rnd.get("verdict") else _verdict(job),
        "judge": rnd.get("judge") if decided else _judge(job),
        "child_job": rnd.get("child_job"),
        # additive: what the job page needs to label the round
        "job_status": s.status if s is not None else "missing",
        "title": s.title if s is not None else "",
        "cost_usd": s.cost_usd if s is not None else 0.0,
        "is_replay": bool(s.is_replay) if s is not None else False,
        "rules": list(rnd.get("rules") or []),
        "part_slug": rnd.get("part_slug"),
        "lesson_ids": list(rnd.get("lesson_ids") or []),
    }


def _updated(mgr: Any, state: Mapping[str, Any]) -> float:
    job = _get(mgr, str(state["rounds"][-1]["job_id"]))
    return max(float(state.get("updated_at") or 0.0), float(job.summary.updated_at) if job is not None else 0.0)


def _detail(mgr: Any, state: Mapping[str, Any]) -> dict[str, Any]:
    from services.review.images import review_images

    last = _get(mgr, str(state["rounds"][-1]["job_id"]))
    return {
        "root_job": state["root_job"],
        "status": _status(mgr, state),
        "rounds": [_round_out(mgr, r) for r in state["rounds"]],
        "images": review_images(last) if last is not None else {"rectified": None, "overlay": None, "focus": None},
        "family": _family(last),
        "updated_at": _updated(mgr, state),
    }


def _locate(mgr: Any, job_id: str) -> tuple[Any, str]:
    job = _get(mgr, job_id) if _ID_RE.match(job_id) else None
    if job is None:
        raise ReviewError(404, "job_not_found", f"no job {job_id!r}")
    return job, _root_of(mgr, job)


# ------------------------------------------------------------------------------------------------- reads


def queue(limit: int = 50, include_replays: bool = True, *, svc: Any = None) -> list[dict[str, Any]]:
    """One item per chain (its latest round): open chains (waiting, improving) first, then decided ones, newest first."""
    mgr = _svc(svc).manager()
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for s in mgr.list(LIST_LIMIT, include_replays=include_replays):
        job = _get(mgr, s.id)
        if job is None or getattr(job.input, "parent_job", None) or s.id in seen:
            continue  # a reviewer round is shown through its chain
        if not reviewable(job):
            continue
        seen.add(s.id)
        state = _state(mgr, s.id)
        last = state["rounds"][-1]
        lj = _get(mgr, str(last["job_id"]))
        status = _status(mgr, state)
        chain_cost = sum(float(j.summary.cost_usd) for j in (_get(mgr, str(r["job_id"])) for r in state["rounds"]) if j)
        items.append(
            {
                "job_id": last["job_id"],
                "root_job": state["root_job"],
                "round": last["round"],
                "title": (lj.summary.title if lj is not None else job.summary.title) or job.id,
                "family": _family(lj or job),
                "status": status,
                "verdict": {k: v for k, v in _verdict(lj).items() if k in ("status", "max_error_mm", "verified")},
                "judge": _judge(lj),
                "cost_usd": float(lj.summary.cost_usd) if lj is not None else 0.0,
                "chain_cost_usd": round(chain_cost, 6),
                "is_replay": bool(
                    (lj or job).summary.is_replay
                ),  # the latest round's job: a live round of a replay is live
                "updated_at": _updated(mgr, state),
            }
        )
    open_ = sorted((i for i in items if i["status"] in ("waiting", "improving")), key=lambda i: -i["updated_at"])
    done = sorted((i for i in items if i["status"] not in ("waiting", "improving")), key=lambda i: -i["updated_at"])
    return (open_ + done)[:limit]


def detail(job_id: str, *, svc: Any = None) -> dict[str, Any]:
    """The chain any job of it belongs to: rounds with pins, outcomes, verdict and judge snapshots."""
    mgr = _svc(svc).manager()
    _, root = _locate(mgr, job_id)
    return _detail(mgr, _state(mgr, root))


def review_of(job: Any, *, svc: Any = None) -> dict[str, Any] | None:
    """{"status", "round", "root_job"} for a job's page, or None when it is not something to review."""
    mgr = _svc(svc).manager()
    root = _root_of(mgr, job)
    rj = job if root == job.id else _get(mgr, root)
    if rj is None or not reviewable(rj):
        return None
    state = _state(mgr, root)
    rnd = next((r for r in state["rounds"] if r["job_id"] == job.id), None)
    return {
        "status": _status(mgr, state),
        "round": rnd["round"] if rnd else 1,
        "root_job": root,
        "decision": rnd.get("decision") if rnd else None,
    }


# ------------------------------------------------------------------------------------------------- decisions


def _clean_pins(pins: Sequence[Pin | Mapping[str, Any]], first_id: int = 1) -> list[Pin]:
    """Validated pins; a pin sent without an id (the web sends only u, v, note) is numbered from `first_id` on."""
    nxt = first_id
    raw: list[Pin | dict[str, Any]] = []
    for p in pins:
        if isinstance(p, Mapping) and p.get("id") is None:
            raw.append({**{k: v for k, v in p.items() if k != "id"}, "id": nxt})
            nxt += 1
        else:
            raw.append(p if isinstance(p, Pin) else dict(p))
    try:
        out = [p if isinstance(p, Pin) else Pin.model_validate(p) for p in raw]
    except ValueError as exc:
        raise ReviewError(422, "validation_error", f"pins: {exc}") from exc
    if len(out) > MAX_PINS:
        raise ReviewError(422, "validation_error", f"at most {MAX_PINS} pins per round")
    if len({p.id for p in out}) != len(out):
        raise ReviewError(422, "validation_error", "pin ids must be unique")
    return out


def _lesson_evidence(state: Mapping[str, Any], rnd: Mapping[str, Any], **extra: Any) -> dict[str, Any]:
    return {
        "source": "review",
        "root_job": state["root_job"],
        "job_id": rnd["job_id"],
        "job_ids": [r["job_id"] for r in state["rounds"]],
        "round": rnd["round"],
        **extra,
    }


def _registry() -> Any:
    from services.registry.store import get_registry

    return get_registry()


def decide(
    job_id: str,
    action: Action,
    *,
    pins: Sequence[Pin | Mapping[str, Any]] = (),
    note: str = "",
    reason: str = "",
    rules: Sequence[RuleChoice | Mapping[str, Any]] = (),
    publish: bool = False,
    publisher: Publisher | None = None,
    svc: Any = None,
) -> dict[str, Any]:
    """Record a person's decision on the latest round of `job_id`'s chain. Returns {"state", "child_job",
    "part_slug"}. Improve starts the linked reviewer round; accept promotes the ticked rules (and publishes when asked,
    best effort labelled as accepted by a person); reject keeps the reason as a lesson candidate."""
    service = _svc(svc)
    mgr = service.manager()
    job, root = _locate(mgr, job_id)
    if action not in ("accept", "improve", "reject"):
        raise ReviewError(422, "validation_error", f"unknown action {action!r}")
    note, reason = note.strip()[:MAX_NOTE], reason.strip()[:MAX_REASON]
    first_id = 1
    if _load(root) is not None:
        used = [int(p["id"]) for r in _state(mgr, root)["rounds"] for p in r.get("pins") or []]
        first_id = max(used, default=0) + 1  # pin numbers continue across the chain's rounds
    clean = _clean_pins(pins, first_id)
    choices = [r if isinstance(r, RuleChoice) else RuleChoice.model_validate(r) for r in rules]
    if action == "improve" and not clean and not note:
        raise ReviewError(422, "review_empty", "improve needs at least one pin or a note")
    if action == "reject" and not reason:
        raise ReviewError(422, "validation_error", "reject needs a short reason")
    with _lock(root):
        rj = _get(mgr, root)
        if rj is None or not reviewable(rj):
            raise ReviewError(409, "not_finished", f"job {root} is not a finished fix job with a model to review")
        state = _state(mgr, root)
        idx = next((i for i, r in enumerate(state["rounds"]) if r["job_id"] == job.id), None)
        last = state["rounds"][-1]
        lj = _get(mgr, str(last["job_id"]))
        if idx is None or idx != len(state["rounds"]) - 1:
            if lj is not None and not lj.finished:
                raise ReviewError(409, "review_busy", f"reviewer round {last['job_id']} is still running")
            raise ReviewError(409, "review_decided", f"{job.id} is not the latest round; review {last['job_id']}")
        if last["decision"] is not None:
            raise ReviewError(409, "review_decided", f"{job.id} was already {last['decision']}ed")
        if not job.finished:
            raise ReviewError(409, "not_finished", f"job {job.id} is {job.summary.status}; review it once it is done")
        rnd = state["rounds"][idx]
        family = _family(job) or "custom"
        rnd.update(
            {
                "decision": action,
                "at": time.time(),
                "note": note,
                "reason": reason,
                "verdict": _verdict(job),
                "judge": _judge(job),
            }
        )
        child_id: str | None = None
        part_slug: str | None = None
        if action == "improve":
            try:
                child = service.start_review_job(job.id, int(rnd["round"]) + 1, clean, note)
            except KeyError as exc:
                raise ReviewError(404, "job_not_found", str(exc.args[0]) if exc.args else str(exc)) from exc
            except ValueError as exc:
                raise ReviewError(422, "validation_error", str(exc)) from exc
            child_id = str(child.id)
            rnd["pins"] = [p.model_dump(mode="json") for p in clean]
            rnd["child_job"] = child_id
            state["rounds"].append(_new_round(int(rnd["round"]) + 1, child_id))
            ids = [
                _registry().add_lesson(
                    family,
                    f"{family}: {text}"[:300],
                    _lesson_evidence(state, rnd, kind="improve_note", source_pin=pid, child_job=child_id),
                )
                for pid, text in [*((p.id, p.note) for p in clean if p.note.strip()), *([(None, note)] if note else [])]
            ]
            rnd["lesson_ids"] = ids
        elif action == "reject":
            rnd["lesson_ids"] = [
                _registry().add_lesson(
                    family,
                    f"{family}: rejected by a reviewer — {reason}"[:300],
                    _lesson_evidence(state, rnd, kind="reject_reason"),
                )
            ]
        else:
            verified = bool((rnd["verdict"] or {}).get("verified"))
            if publish and not job.summary.is_replay and publisher is not None:
                part_slug = publisher(job.id, "" if verified else ACCEPTED_NOTE)
            rnd["sign_off"] = {
                "by": "reviewer",
                "at": rnd["at"],
                "verified_by_code": verified,
                "label": "verified by code, accepted by a person" if verified else ACCEPTED_NOTE,
            }
            rnd["part_slug"] = part_slug
            rnd["rules"] = [c.model_dump(mode="json") for c in choices]
            rnd["lesson_ids"] = _keep_rules(state, rnd, family, choices, mgr)
        state["updated_at"] = time.time()
        _save(state)
        return {"state": _detail(mgr, state), "child_job": child_id, "part_slug": part_slug}


def _keep_rules(
    state: Mapping[str, Any], rnd: Mapping[str, Any], family: str, choices: Sequence[RuleChoice], mgr: Any
) -> list[str]:
    """Ticked rules are promoted (a person's tick is the promotion rule), unticked ones stay candidates; each carries
    the chain's jobs and its pin's before/after mismatch."""
    reg = _registry()
    outcomes: dict[int, dict[str, Any]] = {}
    for r in state["rounds"]:
        for pid, o in _outcomes(mgr, r.get("child_job")).items():
            outcomes[pid] = {"round": r["round"], **o}
    ids: list[str] = []
    for c in choices:
        o = outcomes.get(c.source_pin, {}) if c.source_pin is not None else {}
        ev = _lesson_evidence(
            state,
            rnd,
            kind="review_rule",
            source_pin=c.source_pin,
            before_mm=o.get("before_mm"),
            after_mm=o.get("after_mm"),
            pin_note=o.get("note"),
        )
        lid = reg.add_lesson(family, c.text, ev)
        if c.keep:
            reg.set_lesson_status(lid, "promoted", "reviewer")
        ids.append(lid)
    return ids


# ------------------------------------------------------------------------------------------------- agreement, rule track records


def _judge_ok(judge: Mapping[str, Any]) -> bool:
    blocking = any(v.get("severity") == "blocking" for v in judge.get("vetoes") or [] if isinstance(v, Mapping))
    scores = [int(s["score"]) for s in judge.get("scores") or [] if isinstance(s, Mapping) and "score" in s]
    return not blocking and min(scores) >= 3


def stats() -> dict[str, Any]:
    """Judge vs person over every decided round that has a judge scorecard: judge_ok = no blocking veto and every
    score ≥ 3; person_ok = accept. Cohen's kappa on the 2×2 table (None when n < 2 or undefined)."""
    t = {"both_ok": 0, "both_not": 0, "judge_ok_person_not": 0, "judge_not_person_ok": 0}
    for state in _all_states():
        for r in state.get("rounds") or []:
            judge = r.get("judge")
            if r.get("decision") not in ("accept", "improve", "reject") or not isinstance(judge, Mapping):
                continue
            if not judge.get("scores"):
                continue  # the judge was unavailable: nothing to agree or disagree with
            j, p = _judge_ok(judge), r["decision"] == "accept"
            key = (
                "both_ok"
                if j and p
                else "both_not"
                if not j and not p
                else "judge_ok_person_not"
                if j
                else "judge_not_person_ok"
            )
            t[key] += 1
    n = sum(t.values())
    agree = t["both_ok"] + t["both_not"]
    kappa: float | None = None
    if n >= 2:
        po = agree / n
        j_ok = (t["both_ok"] + t["judge_ok_person_not"]) / n
        p_ok = (t["both_ok"] + t["judge_not_person_ok"]) / n
        pe = j_ok * p_ok + (1 - j_ok) * (1 - p_ok)
        kappa = round((po - pe) / (1 - pe), 4) if pe < 1 else None
    return {"n": n, "agree": agree, **t, "kappa": kappa, "reviewers": 1}


def _used_by() -> dict[str, list[str]]:
    """lesson id -> the jobs whose prompts carried it (lessons_used.json in each run directory, replays included)."""
    from services.agent import jobs

    out: dict[str, list[str]] = {}
    for base in (paths.runs_dir(), jobs.REPLAYS_DIR):
        if not base.exists():
            continue
        for f in base.glob("*/lessons_used.json"):
            try:
                ids = json.loads(f.read_text(encoding="utf-8")).get("lesson_ids") or []
            except (OSError, ValueError, AttributeError):
                continue
            for lid in ids:
                out.setdefault(str(lid), []).append(f.parent.name)
    return out


def lesson_tracks() -> dict[str, dict[str, int]]:
    """Per promoted rule: the jobs that were given it, and how the person's later reviews of those jobs went."""
    used = _used_by()
    decisions: dict[str, str] = {}
    for state in _all_states():
        for r in state.get("rounds") or []:
            if r.get("decision"):
                decisions[str(r["job_id"])] = str(r["decision"])
    out: dict[str, dict[str, int]] = {}
    for lid, job_ids in used.items():
        got = [decisions.get(j) for j in job_ids]
        out[lid] = {
            "used_in": len(set(job_ids)),
            "accepted": got.count("accept"),
            "improved": got.count("improve"),
            "rejected": got.count("reject"),
        }
    return out


def lesson_track(lesson_id: str) -> dict[str, int]:
    return lesson_tracks().get(lesson_id, {"used_in": 0, "accepted": 0, "improved": 0, "rejected": 0})


__all__ = [
    "ReviewError",
    "decide",
    "detail",
    "lesson_track",
    "lesson_tracks",
    "queue",
    "review_of",
    "reviewable",
    "stats",
]
