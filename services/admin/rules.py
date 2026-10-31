"""Taught rules: the promoted family rules (lessons) and a person's fixed feedback that new jobs of the same family
are given, which jobs used each one, and an off switch.

A disabled rule is kept (with who switched it off and why) but is no longer put into builder or fixer prompts
(`services/agent/orchestrator.py` filters on `disabled_ids()`). Switches live in `$PARTSMITH_HOME/disabled_rules.json`;
every change is written to the audit log.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any

from services.admin import audit
from services.common.paths import home

SOURCE = "registry lessons + review feedback log + lessons_used.json / feedback_used.json in run directories"
_lock = threading.Lock()


class RuleError(Exception):
    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


def _path() -> Path:
    return home() / "disabled_rules.json"


def _read() -> dict[str, dict[str, Any]]:
    try:
        data = json.loads(_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {str(k): dict(v) for k, v in data.items() if isinstance(v, dict)} if isinstance(data, dict) else {}


def _write(data: dict[str, dict[str, Any]]) -> None:
    p = _path()
    tmp = p.with_name(f".{p.name}.{threading.get_ident()}.tmp")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(p)


def disabled_ids() -> set[str]:
    """Rule ids (lesson ids or feedback-log ids) that must not reach a prompt."""
    with _lock:
        return set(_read())


def _list_all(svc: Any = None) -> list[dict[str, Any]]:
    from services.registry.store import get_registry
    from services.review import ledger
    from services.review import store as review_store

    disabled = _read()
    out: list[dict[str, Any]] = []
    used = review_store._used_by()
    tracks = review_store.lesson_tracks()
    for lesson in get_registry().lessons(status="promoted"):
        lid = str(lesson["id"])
        jobs = sorted(set(used.get(lid, [])))
        ev = lesson.get("evidence") or {}
        out.append(
            {
                "id": lid,
                "kind": "rule",
                "family": lesson["scope"],
                "text": lesson["rule"],
                "why": "",
                "by": lesson.get("promoted_by"),
                "created_at": lesson.get("created_at"),
                "origin_job": ev.get("job_id") or ev.get("root_job"),
                "used_in": jobs,
                "track": tracks.get(lid, {"used_in": 0, "accepted": 0, "improved": 0, "rejected": 0}),
                "disabled": disabled.get(lid),
            }
        )
    try:
        entries = ledger.feedback(svc=svc)["items"]
    except Exception:
        entries = []
    fb_used = ledger._used_by()
    for e in entries:
        fid = str(e["id"])
        eligible = (
            e.get("by") == "person"
            and e.get("outcome") == "fixed"
            and e.get("kind") in ("pin", "note")
            and e.get("what")
        )
        if not eligible and fid not in fb_used:
            continue
        u = e.get("used_in") or {}
        out.append(
            {
                "id": fid,
                "kind": "feedback",
                "family": e.get("family") or "custom",
                "text": e.get("what") or "",
                "why": e.get("why") or "",
                "by": e.get("by"),
                "created_at": e.get("at"),
                "origin_job": e.get("job_id"),
                "used_in": sorted(set(fb_used.get(fid, []))),
                "track": {
                    "used_in": int(u.get("jobs", 0)),
                    "accepted": int(u.get("accepted", 0)),
                    "improved": int(u.get("improved", 0)),
                    "rejected": int(u.get("rejected", 0)),
                },
                "disabled": disabled.get(fid),
            }
        )
    return out


def list_rules(svc: Any = None) -> dict[str, Any]:
    items = _list_all(svc)
    return {
        "items": items,
        "n": len(items),
        "disabled": sum(1 for i in items if i["disabled"]),
        "source": SOURCE,
    }


def _known(rule_id: str, svc: Any) -> dict[str, Any]:
    got = next((r for r in _list_all(svc) if r["id"] == rule_id), None)
    if got is None:
        raise RuleError(404, "rule_not_found", f"no taught rule {rule_id!r}")
    return got


def disable(rule_id: str, reason: str, *, actor: str = audit.ADMIN, svc: Any = None) -> dict[str, Any]:
    reason = reason.strip()
    if not reason:
        raise RuleError(422, "validation_error", "say why the rule is switched off")
    rule = _known(rule_id, svc)
    entry = {"reason": reason, "by": actor, "at": time.time()}
    with _lock:
        data = _read()
        before = data.get(rule_id)
        data[rule_id] = entry
        _write(data)
    audit.record(
        "rule.disable",
        rule_id,
        actor=actor,
        before={"disabled": before},
        after={"disabled": entry},
        note=reason,
        numbers={"used_in_jobs": len(rule["used_in"])},
    )
    return {**rule, "disabled": entry}


def enable(rule_id: str, reason: str, *, actor: str = audit.ADMIN, svc: Any = None) -> dict[str, Any]:
    reason = reason.strip()
    if not reason:
        raise RuleError(422, "validation_error", "say why the rule is switched back on")
    rule = _known(rule_id, svc)
    with _lock:
        data = _read()
        before = data.pop(rule_id, None)
        if before is None:
            raise RuleError(409, "not_disabled", f"{rule_id} is not switched off")
        _write(data)
    audit.record(
        "rule.enable", rule_id, actor=actor, before={"disabled": before}, after={"disabled": None}, note=reason
    )
    return {**rule, "disabled": None}
