"""Client construction with injection points so tests never touch the network.

`set_client_factory(fn)` replaces the OpenAI-SDK client builder; `set_http_transport(t)` makes every raw HTTP call
(voice transcription, self-hosted SAM 3) go through an `httpx` transport such as `httpx.MockTransport`.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from typing import Any

import httpx

ClientFactory = Callable[[str, str, float], Any]  # (base_url, api_key, timeout_s) -> OpenAI-compatible client


def openai_client(base_url: str, api_key: str, timeout_s: float) -> Any:
    from openai import OpenAI

    # Retries are handled by providers.retry so every attempt is visible and keys are never logged by us.
    return OpenAI(base_url=base_url, api_key=api_key, timeout=timeout_s, max_retries=0)


_factory: ClientFactory = openai_client
_cache: dict[tuple[str, str, float], Any] = {}
_transport: httpx.BaseTransport | None = None


def set_client_factory(factory: ClientFactory | None) -> None:
    """Install a fake client builder (tests) or restore the real one (None)."""
    global _factory
    _factory = factory or openai_client
    _cache.clear()


def get_client(base_url: str, api_key: str, timeout_s: float) -> Any:
    key = (base_url, hashlib.sha256(api_key.encode()).hexdigest(), timeout_s)
    if key not in _cache:
        _cache[key] = _factory(base_url, api_key, timeout_s)
    return _cache[key]


def set_http_transport(transport: httpx.BaseTransport | None) -> None:
    global _transport
    _transport = transport


def http_client(timeout_s: float) -> httpx.Client:
    return httpx.Client(transport=_transport, timeout=timeout_s, follow_redirects=True)


def field(obj: Any, name: str, default: Any = None) -> Any:
    """Read `name` from an SDK object or a plain dict."""
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)
