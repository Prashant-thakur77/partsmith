"""Late-bound dependencies, so tests can swap the agent service for a fake (`monkeypatch.setattr(deps, "service", ...)`)."""

from __future__ import annotations

import importlib
from typing import Any

from services.api.errors import ApiError


def service() -> Any:
    """The agent service facade (`services/agent/service.py`). 503 when it is not installed."""
    try:
        return importlib.import_module("services.agent.service")
    except ImportError as exc:
        raise ApiError(503, "agent_unavailable", "the agent service is not available in this build") from exc
