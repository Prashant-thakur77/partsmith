"""eval.rebake: fresh bakes only, warm-up dropped. The sandbox is faked: this checks the bookkeeping, not CadQuery."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from eval import rebake


@dataclass
class _Out:
    ms: int
    cache_hit: bool = False


def _patch(monkeypatch: pytest.MonkeyPatch, outs: list[_Out]) -> None:
    it = iter(outs)
    monkeypatch.setattr("services.geom_worker.bake.bake", lambda *a, **k: next(it))
    monkeypatch.setattr(rebake, "WarmPool", lambda: type("P", (), {"warm": lambda self: None})())


def test_measure_drops_warmup_and_reports_the_median(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch(monkeypatch, [_Out(900), _Out(800), _Out(10), _Out(20), _Out(30), _Out(40), _Out(50)])
    report: dict[str, Any] = rebake.measure()
    assert report["median_ms"] == 30 and report["n"] == 5 and report["max_ms"] == 50


def test_a_cache_hit_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch(monkeypatch, [_Out(5, cache_hit=True)])
    with pytest.raises(RuntimeError, match="cache"):
        rebake.measure()
