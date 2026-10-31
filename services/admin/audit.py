"""Append-only audit log of admin actions: `$PARTSMITH_HOME/audit.jsonl`, one JSON object per line.

Every write that changes what others see records who did it (`actor`: "admin token", or a review's `by`), what it
touched, the state before and after, a note and any numbers the decision rested on. Lines are only ever appended;
a missing or partly broken file reads as the lines that parse.
"""

from __future__ import annotations

import json
import secrets
import threading
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from services.common.paths import home

ADMIN = "admin token"
MAX_LIMIT = 1000
_lock = threading.Lock()


def path() -> Path:
    return home() / "audit.jsonl"


def record(
    action: str,
    target: str,
    *,
    actor: str = ADMIN,
    before: Any = None,
    after: Any = None,
    note: str | None = None,
    numbers: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Append one entry and return it. Never raises on a write error: an admin action does not fail because the log
    could not be written (the error is kept in the returned entry as `logged: false`)."""
    entry: dict[str, Any] = {
        "id": "a_" + secrets.token_hex(5),
        "at": time.time(),
        "action": action,
        "target": target,
        "actor": actor,
        "before": before,
        "after": after,
        "note": note,
        "numbers": dict(numbers) if numbers else None,
    }
    line = json.dumps(entry, default=str, sort_keys=True)
    try:
        with _lock, path().open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except OSError:
        return {**entry, "logged": False}
    return entry


def read(limit: int = 100, *, action: str | None = None, target: str | None = None) -> dict[str, Any]:
    """Newest first. `action` and `target` are exact matches (`action` may end in `*` for a prefix, e.g. `rule.*`).
    Returns {"items", "total" (after filters), "actions" (every action name seen), "source"}."""
    limit = max(1, min(int(limit), MAX_LIMIT))
    rows: list[dict[str, Any]] = []
    p = path()
    if p.exists():
        with _lock:
            text = p.read_text(encoding="utf-8", errors="replace")
        for line in text.splitlines():
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if isinstance(row, dict) and "action" in row:
                rows.append(row)
    actions = sorted({str(r["action"]) for r in rows})

    def keep(r: Mapping[str, Any]) -> bool:
        if action:
            a = str(r.get("action"))
            if not (a.startswith(action[:-1]) if action.endswith("*") else a == action):
                return False
        return not target or str(r.get("target")) == target

    got = [r for r in rows if keep(r)]
    got.reverse()
    return {"items": got[:limit], "total": len(got), "actions": actions, "source": "audit.jsonl on this server"}
