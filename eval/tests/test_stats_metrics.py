"""Bench statistics checked against hand-computed values."""

import math

import numpy as np
import pytest

from eval.metrics import error_stats, group_errors, hausdorff_summary, iou_summary, pass_at, rate, within
from eval.stats import binom_two_sided_p, bootstrap_ci, mcnemar_exact, mcnemar_paired, wilson_ci


def test_wilson_known_values() -> None:
    # k=0, n=10: upper = z²/(n+z²) = 3.8415/13.8415
    lo, hi = wilson_ci(0, 10)
    assert lo == 0.0 and hi == pytest.approx(3.841459 / 13.841459, abs=1e-6)
    lo, hi = wilson_ci(5, 10)
    assert (lo, hi) == pytest.approx((0.236593, 0.763407), abs=1e-5)
    lo, hi = wilson_ci(10, 10)
    assert hi == pytest.approx(1.0) and lo == pytest.approx(10 / 13.841459, abs=1e-6)
    assert all(math.isnan(x) for x in wilson_ci(0, 0))
    with pytest.raises(ValueError):
        wilson_ci(3, 2)


def test_bootstrap_is_seeded_and_brackets_the_mean() -> None:
    x = np.array([0.1, 0.2, 0.25, 0.4, 0.9, 0.05, 0.3])
    a = bootstrap_ci(x, seed=3)
    assert a == bootstrap_ci(x, seed=3)
    assert a != bootstrap_ci(x, seed=4)
    assert a[0] < x.mean() < a[1]
    assert bootstrap_ci([0.7]) == (0.7, 0.7)
    assert all(math.isnan(v) for v in bootstrap_ci([]))
    med = bootstrap_ci(x, lambda v: float(np.median(v)), seed=1)
    assert med[0] <= float(np.median(x)) <= med[1]


def test_mcnemar_exact() -> None:
    assert mcnemar_exact(0, 5) == pytest.approx(2 / 32)
    assert mcnemar_exact(1, 9) == pytest.approx(2 * (1 + 10) / 1024)
    assert mcnemar_exact(4, 4) == 1.0 and mcnemar_exact(0, 0) == 1.0
    assert binom_two_sided_p(3, 3) == pytest.approx(0.25)
    b, c, p = mcnemar_paired([True, True, False, True, False], [False, True, False, False, True])
    assert (b, c) == (2, 1) and p == pytest.approx(1.0)
    with pytest.raises(ValueError):
        mcnemar_paired([True], [True, False])


def test_error_stats_by_hand() -> None:
    s = error_stats([0.1, -0.2, 0.4, -0.6, 1.0])
    assert s.n == 5
    assert s.mean_mm == pytest.approx(0.46)
    assert s.median_mm == pytest.approx(0.4)
    assert s.p90_mm == pytest.approx(0.84)  # linear: 0.6 + 0.6·(1.0 − 0.6)
    assert s.max_mm == pytest.approx(1.0)
    assert s.within_0_3 == pytest.approx(0.4) and s.within_0_5 == pytest.approx(0.6)
    assert s.signed_mean_mm == pytest.approx(0.14)
    assert s.within_0_5_ci95 == pytest.approx(wilson_ci(3, 5))
    assert s.mean_ci95_mm[0] <= 0.46 <= s.mean_ci95_mm[1]
    empty = error_stats([math.nan])
    assert empty.n == 0 and math.isnan(empty.mean_mm)
    assert within([0.3, 0.30000000001, 0.31], 0.3) == (2, 3)


def test_pass_at_and_rates() -> None:
    r = pass_at([[0.1, 0.2], [0.1, 0.6], [], [0.5]], 0.5)
    assert (r.k, r.n) == (2, 3) and r.rate == pytest.approx(2 / 3)
    assert pass_at([[0.1, 0.2], [0.1, 0.6]], 0.3).k == 1
    assert rate(0, 0).n == 0 and math.isnan(rate(0, 0).rate)


def test_summaries_and_grouping() -> None:
    s = iou_summary([0.9, 0.95, 1.0])
    assert s.n == 3 and s.mean == pytest.approx(0.95) and s.min == 0.9 and s.max == 1.0
    h = hausdorff_summary([0.1, 0.3, math.inf])
    assert h.n == 2 and h.max == pytest.approx(0.3)
    g = group_errors([{"k": "a", "error_mm": 0.1}, {"k": "a", "error_mm": -0.3}, {"k": "b", "error_mm": None}], "k")
    assert g == {"a": [0.1, -0.3]}
