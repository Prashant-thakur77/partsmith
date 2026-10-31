from __future__ import annotations

from typing import Any

import pytest

from services.agent import providers
from services.agent.providers import BudgetExceeded, ModelRequest, budget

from .conftest import FakeHub, responses_stream

SCHEMA: dict[str, Any] = {"type": "object", "properties": {"n": {"type": "integer"}}, "required": ["n"]}


def _req() -> ModelRequest:
    return ModelRequest(messages=[{"role": "user", "content": "go"}], json_schema=SCHEMA, schema_name="n")


def test_no_cap_by_default() -> None:
    assert budget.cap_usd() is None
    budget.add(5.0, "understand")
    budget.check("understand")  # never raises without a cap
    assert budget.snapshot()["remaining_usd"] is None


@pytest.mark.parametrize("raw", ["0", "-1", "abc", ""])
def test_bad_or_zero_cap_means_no_cap(monkeypatch: pytest.MonkeyPatch, raw: str) -> None:
    monkeypatch.setenv("PARTSMITH_DAILY_USD_CAP", raw)
    assert budget.cap_usd() is None


def test_spend_accumulates_and_persists(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PARTSMITH_DAILY_USD_CAP", "1.00")
    budget.add(0.25, "understand")
    budget.add(0.0, "understand")  # free calls are not counted
    budget.add(0.5, "judge")
    snap = budget.snapshot()
    assert snap["spent_usd"] == pytest.approx(0.75) and snap["calls"] == 2
    assert snap["remaining_usd"] == pytest.approx(0.25)
    assert snap["by_stage"] == {"understand": 0.25, "judge": 0.5}
    budget.check("understand")
    budget.add(0.25, "judge")
    with pytest.raises(BudgetExceeded, match="budget is used up"):
        budget.check("understand")


def test_live_call_counts_and_cap_blocks_next_call(monkeypatch: pytest.MonkeyPatch, hub: FakeHub) -> None:
    monkeypatch.setenv("MODEL_API_KEY", "k-meta-000000")
    hub.handlers[("responses", "api.meta.ai")] = [responses_stream('{"n": 1}', 1000, 1000)]
    out = providers.complete("understand", _req())
    assert budget.spent_today() == pytest.approx(out.usd) and out.usd > 0
    monkeypatch.setenv("PARTSMITH_DAILY_USD_CAP", str(out.usd / 2))
    calls = len(hub.calls_for("responses"))
    with pytest.raises(BudgetExceeded):
        providers.complete("understand", _req())
    assert len(hub.calls_for("responses")) == calls  # the provider was never called


def test_mock_calls_are_free(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PARTSMITH_DAILY_USD_CAP", "0.000001")
    monkeypatch.setenv("PROVIDER_MODE", "mock")
    providers.complete("understand", _req())
    assert budget.spent_today() == 0.0
