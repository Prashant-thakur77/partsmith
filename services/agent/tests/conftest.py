"""Agent tests run with no keys and no network: every model stage is a deterministic mock (PROVIDER_MODE=mock),
runtime data lives in a temporary PARTSMITH_HOME shared by this package's tests (slow fixtures reuse finished jobs)."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from services.agent import providers, service
from services.agent.jobs import JobManager
from services.agent.providers import mocks

KEY_VARS = (
    "MODEL_API_KEY", "META_API_KEY", "BASETEN_API_KEY", "FIREWORKS_API_KEY", "TOGETHER_API_KEY", "GLIMMER_BASE_URL",
    "SAM3_OPEN_URL", "PROVIDER_RECORD", "OPEN_WEIGHTS_ONLY", "PROVIDER_FALLBACK_TO_MOCK", "DATABASE_URL",
)


@pytest.fixture(scope="package", autouse=True)
def agent_home(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Path]:
    mp = pytest.MonkeyPatch()
    home = tmp_path_factory.mktemp("agent_home")
    for name in KEY_VARS:
        mp.delenv(name, raising=False)
    mp.setenv("PROVIDER_MODE", "mock")
    mp.setenv("PARTSMITH_ENV_FILE", str(home / "no.env"))
    mp.setenv("PARTSMITH_HOME", str(home))
    _reset_singletons(home)
    yield home
    service.reset_manager(None)
    mp.undo()
    _reset_singletons(None)


def _reset_singletons(home: Path | None) -> None:
    from services.registry import store

    store._registry = None
    providers.reset_state()
    mocks.clear_mocks()
    service.reset_manager(JobManager(root=home / "runs") if home is not None else None)


@pytest.fixture(autouse=True)
def clean_mocks() -> Iterator[None]:
    """Each test starts from the domain mocks only (tests may register their own on top)."""
    mocks.clear_mocks()
    yield
    mocks.clear_mocks()
