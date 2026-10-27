from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from services.agent import providers
from services.agent.providers import clients, mocks, retry

KEY_VARS = (
    "PROVIDER_MODE",
    "PROVIDER_RECORD",
    "OPEN_WEIGHTS_ONLY",
    "PROVIDER_FALLBACK_TO_MOCK",
    "MODEL_API_KEY",
    "BASETEN_API_KEY",
    "FIREWORKS_API_KEY",
    "TOGETHER_API_KEY",
    "GLIMMER_BASE_URL",
    "SAM3_OPEN_URL",
)


@pytest.fixture(autouse=True)
def zero_keys(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[None]:
    """Media tests run with no keys and no network: every provider stage is in mock mode."""
    for name in KEY_VARS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("PARTSMITH_ENV_FILE", str(tmp_path / "no.env"))
    monkeypatch.setenv("PARTSMITH_HOME", str(tmp_path / "home"))
    monkeypatch.setattr(retry, "sleep", lambda s: None)
    providers.reset_state()
    mocks.clear_mocks()

    def no_ws(url: str, **kw: object) -> object:
        raise AssertionError(f"test tried to open a real WebSocket to {url}")

    clients.set_ws_connect(no_ws)
    yield
    providers.reset_state()
    mocks.clear_mocks()
    clients.set_http_transport(None)
