"""Retry with exponential backoff on 429 / 5xx / timeouts / connection errors; everything else fails fast."""

from __future__ import annotations

import random
import time
from collections.abc import Callable

import httpx

from .base import ProviderError
from .clients import field
from .config import log, redact

sleep: Callable[[float], None] = time.sleep  # tests replace this to avoid waiting

RETRYABLE_STATUS = {408, 409, 425, 429, 500, 502, 503, 504, 529}
_HINTS = {
    400: "bad request",
    401: "key not accepted",
    403: "forbidden (key lacks access or region blocked)",
    404: "not found (model id or URL)",
    413: "request body too large",
    429: "rate limited",
    500: "server error",
    502: "bad gateway",
    503: "service unavailable (scaling from zero?)",
    504: "gateway timeout (stream long calls)",
}


def _retry_after(exc: BaseException) -> float | None:
    response = field(exc, "response")
    headers = field(response, "headers") if response is not None else None
    if headers is None:
        return None
    try:
        value = headers.get("retry-after")
        return float(value) if value is not None else None
    except (TypeError, ValueError, AttributeError):
        return None


def classify(exc: BaseException, provider: str) -> ProviderError:
    """Turn any SDK/HTTP exception into a redacted ProviderError with a retryable flag."""
    if isinstance(exc, ProviderError):
        return exc
    status: int | None = None
    retryable = False
    raw_status = field(exc, "status_code")
    if raw_status is None and isinstance(exc, httpx.HTTPStatusError):
        raw_status = exc.response.status_code
    if isinstance(raw_status, int):
        status = raw_status
        retryable = status in RETRYABLE_STATUS
    name = type(exc).__name__
    if status is None and (
        isinstance(exc, (httpx.TimeoutException, httpx.TransportError, TimeoutError, ConnectionError))
        or name in {"APITimeoutError", "APIConnectionError"}
    ):
        retryable = True
    detail = str(exc).splitlines()[0][:300] if str(exc) else name
    hint = _HINTS.get(status or 0, "")
    prefix = f"{provider}: HTTP {status}" + (f" ({hint})" if hint else "") if status else f"{provider}: {name}"
    return ProviderError(redact(f"{prefix}: {detail}"), provider=provider, status=status, retryable=retryable)


def with_retries[T](fn: Callable[[], T], *, provider: str, max_retries: int, base_delay_s: float = 0.8) -> T:
    """Call `fn`, retrying retryable failures up to `max_retries` times with jittered exponential backoff."""
    attempt = 0
    while True:
        try:
            return fn()
        except Exception as exc:
            err = classify(exc, provider)
            if not err.retryable or attempt >= max_retries:
                if err is exc:
                    raise
                raise err from exc
            delay = _retry_after(exc) or min(20.0, base_delay_s * 2**attempt) * (0.75 + random.random() / 2)
            attempt += 1
            log.info("%s (retry %d/%d in %.1fs)", err, attempt, max_retries, delay)
            sleep(min(delay, 30.0))
