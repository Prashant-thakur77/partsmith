"""`job_context`: every model call inside it emits a `ModelCallEvent` (tokens, ms, $, mode, ok/error) via `emit`."""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field

from partsmith_schemas.events import ModelCallEvent

from .base import Usage
from .config import Mode, log

EmitFn = Callable[[ModelCallEvent], object]


@dataclass
class JobLedger:
    """Running record of the model calls made inside one `job_context`."""

    job_id: str
    emit: EmitFn
    ctx: str = ""
    events: list[ModelCallEvent] = field(default_factory=list)

    @property
    def usd_total(self) -> float:
        return round(float(sum(e.usd for e in self.events)), 8)

    @property
    def tokens_total(self) -> tuple[int, int]:
        return sum(e.tokens_in for e in self.events), sum(e.tokens_out for e in self.events)


_current: ContextVar[JobLedger | None] = ContextVar("partsmith_job_ledger", default=None)


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
    try:
        ledger.emit(event)
    except Exception:  # a broken event sink must never fail the model call
        log.exception("model_call event sink failed")
    return event
