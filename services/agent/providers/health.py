"""Route latency: a text route whose recent calls for a stage run slow is tried after the other ready routes for a while.

The fallback chains only moved on when a provider failed. Live, 2026-10-29, the shared Baseten hackathon deployment of
Spark Open went from a median of 8 s per fixer turn to 28 s (one turn took 318 s); the battery cover hit the job's
wall-clock cap and ended best effort where the morning's run verified. A route whose last `WINDOW` calls for a stage
average more than `SLOW_MEAN_S` is moved behind the other ready routes for that stage for `COOL_DOWN_S`, then gets a
fresh window. Windows are per stage: a vision call that reads two photos is slow by nature (understand, 36–55 s) and
says nothing about the same model's fixer turns. Only the order changes: every call still emits its `model_call` event
with the model that served it.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING

from .config import log

if TYPE_CHECKING:
    from .routing import Route

SLOW_MEAN_S = 40.0
WINDOW = 6
MIN_CALLS = 3
COOL_DOWN_S = 900.0

clock: Callable[[], float] = time.monotonic  # tests replace this
_lock = threading.Lock()
_samples: dict[tuple[str, str, str], deque[float]] = {}
_slow: dict[tuple[str, str, str], tuple[float, float]] = {}  # (stage, route) -> (until, mean seconds that demoted it)


def _key(route: Route, stage: str) -> tuple[str, str, str]:
    return stage, route.provider, route.model


def note(route: Route, stage: str, ms: int) -> None:
    """Count one live text call (success or failure: a timeout is slow too) against its route for `stage`."""
    k = _key(route, stage)
    with _lock:
        if k in _slow:
            return
        q = _samples.setdefault(k, deque(maxlen=WINDOW))
        q.append(ms / 1000)
        mean = sum(q) / len(q)
        if len(q) >= MIN_CALLS and mean > SLOW_MEAN_S:
            _slow[k] = (clock() + COOL_DOWN_S, mean)
            q.clear()
            log.warning(
                f"{route.endpoint.where} ({route.model}) is slow for {stage}: {mean:.0f} s per call over the last "
                f"{WINDOW} or fewer calls; other ready routes go first for {COOL_DOWN_S / 60:.0f} min"
            )


def slow(route: Route, stage: str) -> float | None:
    """The mean seconds per call that demoted `route` for `stage`, while its cool-down lasts; else None."""
    k = _key(route, stage)
    with _lock:
        hit = _slow.get(k)
        if hit is None:
            return None
        if clock() >= hit[0]:
            del _slow[k]
            return None
        return hit[1]


def order(routes: Sequence[Route], stage: str) -> tuple[list[Route], str]:
    """`routes` with the ones slow for `stage` moved last (only when a route that is not slow remains), and a note."""
    marks = [(r, slow(r, stage)) for r in routes]
    fast = [r for r, m in marks if m is None]
    if not fast or len(fast) == len(routes):
        return list(routes), ""
    late = [(r, m) for r, m in marks if m is not None]
    why = "; ".join(f"{r.endpoint.where} slow ({m:.0f} s per call)" for r, m in late)
    return fast + [r for r, _ in late], f"{why} → {fast[0].endpoint.where} first"


def reset() -> None:
    with _lock:
        _samples.clear()
        _slow.clear()
