"""Daily spend cap for live model calls.

`PARTSMITH_DAILY_USD_CAP` (USD, per UTC day; unset or 0 = no cap). Every live call's cost is added as it is recorded
(`telemetry.record_call`); before a live call is made, `check(stage)` raises `BudgetExceeded` once today's spend has
reached the cap. Nothing falls back silently: the job or request fails with a clear message, so a public deployment
cannot run up the model bill. Spend is kept in `$PARTSMITH_HOME/spend/<YYYY-MM-DD>.json`, so a restart does not reset it.
"""

from __future__ import annotations

import json
import threading
from datetime import UTC, datetime
from typing import Any

from services.common.paths import sub

from .base import ProviderError
from .config import env

_lock = threading.Lock()


class BudgetExceeded(ProviderError):
    """Today's live spend reached PARTSMITH_DAILY_USD_CAP."""


def cap_usd() -> float | None:
    raw = env("PARTSMITH_DAILY_USD_CAP")
    try:
        cap = float(raw) if raw else 0.0
    except ValueError:
        return None
    return cap if cap > 0 else None


def _today() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d")


def _path(day: str) -> Any:
    return sub("spend") / f"{day}.json"


def _read(day: str) -> dict[str, Any]:
    try:
        data = json.loads(_path(day).read_text())
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def spent_today() -> float:
    with _lock:
        return float(_read(_today()).get("usd", 0.0))


def add(usd: float, stage: str = "") -> None:
    """Add a live call's cost to today's total (no-op for free calls)."""
    if usd <= 0:
        return
    day = _today()
    with _lock:
        data = _read(day)
        data["usd"] = round(float(data.get("usd", 0.0)) + usd, 8)
        data["calls"] = int(data.get("calls", 0)) + 1
        if stage:
            by = data.setdefault("by_stage", {})
            by[stage] = round(float(by.get(stage, 0.0)) + usd, 8)
        p = _path(day)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, sort_keys=True))
        tmp.replace(p)


def check(stage: str) -> None:
    """Raise `BudgetExceeded` if a live call for `stage` would go over today's cap."""
    cap = cap_usd()
    if cap is None:
        return
    spent = spent_today()
    if spent >= cap:
        raise BudgetExceeded(
            f"{stage}: today's model budget is used up (${spent:.2f} of ${cap:.2f}); live calls resume after 00:00 UTC",
            stage=stage,
        )


def snapshot() -> dict[str, Any]:
    """Today's spend against the cap, for /status and the admin console."""
    cap = cap_usd()
    day = _today()
    with _lock:
        data = _read(day)
    spent = float(data.get("usd", 0.0))
    return {
        "day": day,
        "cap_usd": cap,
        "spent_usd": round(spent, 6),
        "remaining_usd": round(max(cap - spent, 0.0), 6) if cap is not None else None,
        "calls": int(data.get("calls", 0)),
        "by_stage": data.get("by_stage", {}),
        "source": "live model_call costs recorded on this server today (UTC)",
    }
