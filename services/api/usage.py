"""Usage counter: API and MCP calls by route template and client fingerprint.

The fingerprint is a salted sha256 of (IP, user agent), truncated; raw IPs and user agents are never stored. The salt
is `PARTSMITH_USAGE_SALT` or a random value kept in `$PARTSMITH_HOME/usage_salt`. Counts are buffered in memory and
written in batches (every 10 s or 50 calls, and before every read).
"""

from __future__ import annotations

import hashlib
import os
import secrets
import threading
import time
from collections import Counter
from datetime import UTC, datetime, timedelta
from typing import Any

from services.common.paths import home
from services.registry.store import get_registry

FLUSH_EVERY_S = 10.0
FLUSH_AT = 50

_lock = threading.Lock()
_pending: Counter[tuple[str, str, str]] = Counter()
_last_flush = time.monotonic()
_salt: bytes | None = None


def _get_salt() -> bytes:
    global _salt
    if _salt is None:
        env = os.environ.get("PARTSMITH_USAGE_SALT")
        if env:
            _salt = env.encode()
        else:
            p = home() / "usage_salt"
            if not p.exists():
                p.write_text(secrets.token_hex(16))
            _salt = p.read_text().strip().encode()
    return _salt


def fingerprint(ip: str, user_agent: str) -> str:
    return hashlib.sha256(_get_salt() + b"|" + ip.encode() + b"|" + user_agent.encode()).hexdigest()[:16]


def _today() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d")


def record(route: str, ip: str, user_agent: str) -> None:
    global _last_flush
    key = (_today(), route[:160], fingerprint(ip, user_agent))
    with _lock:
        _pending[key] += 1
        due = sum(_pending.values()) >= FLUSH_AT or time.monotonic() - _last_flush > FLUSH_EVERY_S
    if due:
        flush()


def flush() -> None:
    global _last_flush
    with _lock:
        batch = dict(_pending)
        _pending.clear()
        _last_flush = time.monotonic()
    if batch:
        get_registry().add_usage(batch)


def reset() -> None:
    """Forget unflushed counts and the cached salt (tests)."""
    global _salt
    with _lock:
        _pending.clear()
    _salt = None


def summary() -> dict[str, Any]:
    """calls_total, mcp_calls, distinct_clients, last_7d {calls, mcp_calls, distinct_clients}, top_routes."""
    flush()
    rows = get_registry().usage()
    since = (datetime.now(UTC) - timedelta(days=6)).strftime("%Y-%m-%d")
    recent = [r for r in rows if r[0] >= since]
    by_route: Counter[str] = Counter()
    for _, route, _, n in rows:
        by_route[route] += n

    def agg(rs: list[tuple[str, str, str, int]]) -> dict[str, int]:
        return {"calls": sum(r[3] for r in rs), "mcp_calls": sum(r[3] for r in rs if r[1] == "/mcp"),
                "distinct_clients": len({r[2] for r in rs})}  # fmt: skip

    total = agg(rows)
    return {
        "calls_total": total["calls"],
        "mcp_calls": total["mcp_calls"],
        "distinct_clients": total["distinct_clients"],
        "last_7d": agg(recent),
        "top_routes": [{"route": r, "calls": n} for r, n in by_route.most_common(10)],
    }
