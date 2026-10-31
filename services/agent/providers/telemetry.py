"""`job_context`: every model call inside it emits a `ModelCallEvent` (tokens, ms, $, mode, ok/error) via `emit`;
agentic stages also emit `ThoughtEvent` (reasoning summaries) and `ToolCallEvent`.

Every model call is also counted in a process-wide tally (with or without a job context) so the open-weights
evidence pack can say which model served which stage and how often (`open_weights_summary`).
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any

from partsmith_schemas.events import ModelCallEvent, ThoughtEvent, ToolCallEvent

from . import budget
from .base import Usage
from .config import Mode, log

EmitFn = Callable[[Any], object]  # receives ModelCallEvent | ThoughtEvent | ToolCallEvent


@dataclass
class JobLedger:
    """Running record of the model calls (and agent trace events) made inside one `job_context`."""

    job_id: str
    emit: EmitFn
    ctx: str = ""
    events: list[ModelCallEvent] = field(default_factory=list)
    trace: list[ThoughtEvent | ToolCallEvent] = field(default_factory=list)

    @property
    def usd_total(self) -> float:
        return round(float(sum(e.usd for e in self.events)), 8)

    @property
    def tokens_total(self) -> tuple[int, int]:
        return sum(e.tokens_in for e in self.events), sum(e.tokens_out for e in self.events)


_current: ContextVar[JobLedger | None] = ContextVar("partsmith_job_ledger", default=None)
_tally_lock = threading.Lock()
_tally: dict[tuple[str, str, str, str], list[int]] = {}  # (stage, provider, model, mode) -> [calls, tok_in, tok_out]


@contextmanager
def job_context(job_id: str, emit: EmitFn, ctx: str = "") -> Iterator[JobLedger]:
    """Attach model-call events to a job. Nested contexts shadow the outer one; works across `asyncio.to_thread`."""
    ledger = JobLedger(job_id=job_id, emit=emit, ctx=ctx)
    token = _current.set(ledger)
    try:
        yield ledger
    finally:
        _current.reset(token)


def current() -> JobLedger | None:
    return _current.get()


def _emit(ledger: JobLedger, event: Any) -> None:
    try:
        ledger.emit(event)
    except Exception:  # a broken event sink must never fail the model call
        log.exception("event sink failed")


def record_call(
    *,
    stage: str,
    provider: str,
    model: str,
    mode: Mode,
    usage: Usage,
    ms: int,
    usd: float,
    ok: bool = True,
    error: str | None = None,
) -> ModelCallEvent | None:
    if mode == "live":
        budget.add(usd, stage)
    if ok:
        with _tally_lock:
            row = _tally.setdefault((stage, provider, model, mode), [0, 0, 0])
            row[0] += 1
            row[1] += usage.tokens_in
            row[2] += usage.tokens_out
    ledger = _current.get()
    if ledger is None:
        return None
    event = ModelCallEvent(
        job=ledger.job_id,
        ctx=ledger.ctx,
        ts=time.time(),
        provider=provider,
        model=model,
        stage=stage,
        mode=mode,
        tokens_in=usage.tokens_in,
        tokens_out=usage.tokens_out,
        ms=ms,
        usd=usd,
        ok=ok,
        error=error,
    )
    ledger.events.append(event)
    _emit(ledger, event)
    return event


def record_thought(
    *, stage: str, model: str, text: str, iter: int | None = None, mode: Mode | None = None
) -> ThoughtEvent | None:
    """A reasoning *summary* (or the model's visible note); never raw chain of thought."""
    ledger = _current.get()
    if ledger is None or not text.strip():
        return None
    event = ThoughtEvent(
        job=ledger.job_id, ctx=ledger.ctx, ts=time.time(), stage=stage, model=model, text=text, iter=iter, mode=mode
    )
    ledger.trace.append(event)
    _emit(ledger, event)
    return event


def record_tool_call(
    *,
    stage: str,
    name: str,
    args: dict[str, Any],
    result: str,
    ok: bool,
    ms: int,
    iter: int | None = None,
    mode: Mode | None = None,
) -> ToolCallEvent | None:
    ledger = _current.get()
    if ledger is None:
        return None
    event = ToolCallEvent(
        job=ledger.job_id, ctx=ledger.ctx, ts=time.time(), stage=stage, name=name, args=args, result=result[:2000],
        ok=ok, ms=ms, iter=iter, mode=mode,
    )  # fmt: skip
    ledger.trace.append(event)
    _emit(ledger, event)
    return event


def tally() -> list[dict[str, Any]]:
    """Successful model calls in this process: one row per (stage, provider, model, mode)."""
    with _tally_lock:
        return [
            {
                "stage": k[0],
                "provider": k[1],
                "model": k[2],
                "mode": k[3],
                "calls": v[0],
                "tokens_in": v[1],
                "tokens_out": v[2],
            }
            for k, v in sorted(_tally.items())
        ]


def reset_tally() -> None:
    with _tally_lock:
        _tally.clear()


def tally_from_events(events: Iterable[ModelCallEvent | dict[str, Any]]) -> list[dict[str, Any]]:
    """Same rows as `tally()` but from recorded events (e.g. every `run.jsonl`)."""
    rows: dict[tuple[str, str, str, str], list[int]] = {}
    for ev in events:
        d = ev.model_dump() if isinstance(ev, ModelCallEvent) else ev
        if d.get("t", "model_call") != "model_call" or not d.get("ok", True):
            continue
        key = (str(d.get("stage", "")), str(d.get("provider", "")), str(d.get("model", "")), str(d.get("mode", "")))
        row = rows.setdefault(key, [0, 0, 0])
        row[0] += 1
        row[1] += int(d.get("tokens_in", 0))
        row[2] += int(d.get("tokens_out", 0))
    return [
        {
            "stage": k[0],
            "provider": k[1],
            "model": k[2],
            "mode": k[3],
            "calls": v[0],
            "tokens_in": v[1],
            "tokens_out": v[2],
        }
        for k, v in sorted(rows.items())
    ]
