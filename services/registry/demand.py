"""Search demand: what people searched the registry for, and which searches found no close part.

Every non-empty registry search (REST `GET /parts?q=` and the MCP `search_parts` tool) appends one JSON line to
`$PARTSMITH_HOME/search_log.jsonl`: the query text, how many parts it returned, the best coverage among them and the
UTC time. No IP, user agent or any client id is written. `missed_searches` groups the log by normalised query and keeps
the groups whose best coverage stayed below `MISS_BELOW` — the parts people want that the registry does not have yet.

Typing in the search box searches as you type, so "cab", "cable", "cable cl" arrive one after another: an entry whose
normalised text starts a later entry within `TYPING_GAP_S` seconds is treated as a half-typed query and skipped.
"""

from __future__ import annotations

import json
import re
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from services.common.paths import home

LOG_NAME = "search_log.jsonl"
MISS_BELOW = 0.5  # a search whose best coverage is below this found no close part
TYPING_GAP_S = 30.0
MAX_Q = 200
MIN_Q = 3
READ_LAST = 20_000  # lines read for grouping (newest)

_lock = threading.Lock()


def log_path() -> Path:
    return home() / LOG_NAME


def normalize(q: str) -> str:
    """Lowercase words and numbers, single spaces: "Cable  Clip, 8mm!" -> "cable clip 8 mm"."""
    return " ".join(re.findall(r"[a-z]+|\d+(?:\.\d+)?", q.lower()))


def log_search(q: str, total: int, best_coverage: float | None, *, now: datetime | None = None) -> bool:
    """Append one search to the log (thread-safe). Returns False (nothing written) for queries too short to mean
    anything. Never raises: demand logging must not break a search."""
    text = " ".join(q.split())[:MAX_Q]
    if len(normalize(text)) < MIN_Q:
        return False
    row = {
        "q": text,
        "total": int(total),
        "best_coverage": None if best_coverage is None else round(float(best_coverage), 3),
        "at": (now or datetime.now(UTC)).isoformat(timespec="seconds"),
    }
    try:
        line = json.dumps(row, ensure_ascii=False) + "\n"
        with _lock, log_path().open("a", encoding="utf-8") as fh:
            fh.write(line)
    except OSError:
        return False
    return True


def _read(limit: int = READ_LAST) -> list[dict[str, Any]]:
    path = log_path()
    if not path.is_file():
        return []
    with _lock:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()[-limit:]
    out: list[dict[str, Any]] = []
    for ln in lines:
        try:
            row = json.loads(ln)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict) and isinstance(row.get("q"), str) and isinstance(row.get("at"), str):
            out.append(row)
    return out


def _ts(at: str) -> float:
    try:
        return datetime.fromisoformat(at).timestamp()
    except ValueError:
        return 0.0


def _typed_on(rows: list[dict[str, Any]], i: int) -> bool:
    """True when row i looks half-typed: a later row within TYPING_GAP_S extends its normalised text."""
    norm, t0 = normalize(rows[i]["q"]), _ts(rows[i]["at"])
    for later in rows[i + 1 :]:
        dt = _ts(later["at"]) - t0
        if dt > TYPING_GAP_S:
            return False
        other = normalize(later["q"])
        if other != norm and other.startswith(norm):
            return True
    return False


def missed_searches(limit: int = 50) -> list[dict[str, Any]]:
    """Searches that found no close part, grouped by normalised query: [{q, count, best_coverage, last_at}], most
    asked first (then most recent). `q` is the latest wording; `best_coverage` the best any of its searches got."""
    rows = sorted(_read(), key=lambda r: _ts(r["at"]))
    groups: dict[str, dict[str, Any]] = {}
    for i, row in enumerate(rows):
        if _typed_on(rows, i):
            continue
        key = normalize(row["q"])
        cov = row.get("best_coverage")
        cov_f = float(cov) if isinstance(cov, int | float) else 0.0
        g = groups.setdefault(key, {"q": row["q"], "count": 0, "best_coverage": cov_f, "last_at": row["at"]})
        g["count"] += 1
        g["best_coverage"] = max(g["best_coverage"], cov_f)
        if _ts(row["at"]) >= _ts(g["last_at"]):
            g["last_at"], g["q"] = row["at"], row["q"]
    missed = [g for g in groups.values() if g["best_coverage"] < MISS_BELOW]
    missed.sort(key=lambda g: (-g["count"], -_ts(g["last_at"])))
    return missed[:limit]
