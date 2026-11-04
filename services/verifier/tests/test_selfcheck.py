from __future__ import annotations

import pytest

from services.geom_worker.sandbox import WarmPool
from services.verifier.selfcheck import SELF_HAUSDORFF_MAX_MM, format_table, run


@pytest.mark.slow
def test_phase2_exit_gate(vpool: WarmPool) -> None:
    """Self-consistency < 0.15 mm and +/-1 mm perturbations detected with the right sign."""
    rows = run(vpool)
    table = format_table(rows)
    assert len(rows) == 10, table
    for r in rows:
        assert r.self_hausdorff_mm < SELF_HAUSDORFF_MAX_MM, table
        assert r.plus_delta_mm is not None and r.plus_delta_mm > 0.5, table
        assert r.minus_delta_mm is not None and r.minus_delta_mm < -0.5, table
        assert r.self_verified and not r.perturbed_verified, table
