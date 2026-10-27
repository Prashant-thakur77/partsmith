from __future__ import annotations

from eval.bypass import ATTACKS, run_suite
from services.geom_worker.sandbox import WarmPool


def test_every_lying_brain_attempt_is_blocked_by_code() -> None:
    pool = WarmPool(size=1)
    try:
        rep = run_suite(pool)
    finally:
        pool.close()
    assert rep["attempts"] == len(ATTACKS) >= 12
    failed = [r for r in rep["rows"] if not r["blocked"]]
    assert not failed, failed
    assert {r["blocked_by"] for r in rep["rows"]} >= {"can_ship", "guards", "policy"}
