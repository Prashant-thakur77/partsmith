"""Small, dependency-free statistics for bench reports (pure numpy + math).

- `wilson_ci(k, n)` — Wilson score interval for a rate (well behaved at 0/n and n/n, unlike the normal interval).
- `bootstrap_ci(values, stat, ...)` — percentile bootstrap interval, seeded so reports are reproducible.
- `mcnemar_exact(b, c)` — exact two-sided McNemar test for paired pass/fail (A/B on the same items): under H0 the
  discordant pairs split as Binomial(b + c, 1/2).
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence

import numpy as np
from numpy.typing import ArrayLike, NDArray

Z95 = 1.959963984540054


def wilson_ci(k: int, n: int, z: float = Z95) -> tuple[float, float]:
    """Wilson score interval for k successes out of n. Returns (nan, nan) for n = 0."""
    if n <= 0:
        return (math.nan, math.nan)
    if not 0 <= k <= n:
        raise ValueError(f"k={k} must be within 0..n={n}")
    p = k / n
    z2 = z * z
    den = 1 + z2 / n
    centre = (p + z2 / (2 * n)) / den
    half = z * math.sqrt(p * (1 - p) / n + z2 / (4 * n * n)) / den
    return (max(0.0, centre - half), min(1.0, centre + half))


def bootstrap_ci(
    values: ArrayLike,
    stat: Callable[[NDArray[np.float64]], float] | None = None,
    *,
    n_boot: int = 2000,
    alpha: float = 0.05,
    seed: int = 0,
) -> tuple[float, float]:
    """Percentile bootstrap CI of `stat` (default: mean). Deterministic for a given seed. (nan, nan) when empty;
    a single value gives a zero-width interval."""
    x = np.asarray(values, dtype=np.float64).ravel()
    if len(x) == 0:
        return (math.nan, math.nan)
    f = stat or (lambda a: float(np.mean(a)))
    if len(x) == 1:
        v = float(f(x))
        return (v, v)
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(x), size=(n_boot, len(x)))
    boots = x[idx].mean(axis=1) if stat is None else np.array([f(x[i]) for i in idx])
    lo, hi = np.quantile(boots, [alpha / 2, 1 - alpha / 2])
    return (float(lo), float(hi))


def binom_two_sided_p(k: int, n: int) -> float:
    """Exact two-sided p-value of k successes in n fair-coin trials (doubling the smaller tail, capped at 1)."""
    if n == 0:
        return 1.0
    m = min(k, n - k)
    tail = sum(math.comb(n, i) for i in range(m + 1)) / 2.0**n
    return min(1.0, 2.0 * tail)


def mcnemar_exact(b: int, c: int) -> float:
    """Exact McNemar p-value from the discordant counts: b = A pass / B fail, c = A fail / B pass."""
    if b < 0 or c < 0:
        raise ValueError("counts must be non-negative")
    return binom_two_sided_p(b, b + c)


def mcnemar_paired(a_pass: Sequence[bool], b_pass: Sequence[bool]) -> tuple[int, int, float]:
    """(b, c, p) for two paired pass/fail lists over the same items."""
    if len(a_pass) != len(b_pass):
        raise ValueError("paired lists must have the same length")
    b = sum(1 for x, y in zip(a_pass, b_pass, strict=True) if x and not y)
    c = sum(1 for x, y in zip(a_pass, b_pass, strict=True) if y and not x)
    return b, c, mcnemar_exact(b, c)


__all__ = ["Z95", "binom_two_sided_p", "bootstrap_ci", "mcnemar_exact", "mcnemar_paired", "wilson_ci"]
