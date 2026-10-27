"""Bench aggregates (PLAN Appendix D): per-dimension absolute errors, pass@tol, CIs, IoU/Hausdorff summaries.

Pure numpy. Every function takes plain numbers so it can be checked by hand; reports carry N and the ground-truth
source next to every number. P90 uses numpy's default linear interpolation between order statistics.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass

import numpy as np
from numpy.typing import ArrayLike

from .stats import bootstrap_ci, mcnemar_exact, mcnemar_paired, wilson_ci

TOLS_MM = (0.3, 0.5)


@dataclass(frozen=True)
class ErrorStats:
    """Absolute-error summary of N dimension measurements (mm)."""

    n: int
    mean_mm: float
    mean_ci95_mm: tuple[float, float]
    median_mm: float
    p90_mm: float
    max_mm: float
    within_0_3: float  # share of |error| ≤ 0.3 mm
    within_0_3_ci95: tuple[float, float]
    within_0_5: float
    within_0_5_ci95: tuple[float, float]
    signed_mean_mm: float  # bias

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _nan_stats() -> ErrorStats:
    nan = math.nan
    return ErrorStats(0, nan, (nan, nan), nan, nan, nan, nan, (nan, nan), nan, (nan, nan), nan)


def within(abs_err: ArrayLike, tol_mm: float) -> tuple[int, int]:
    """(count with |e| ≤ tol, n). A tiny epsilon keeps values printed as exactly the tolerance inside it."""
    a = np.abs(np.asarray(abs_err, dtype=np.float64).ravel())
    return int(np.count_nonzero(a <= tol_mm + 1e-9)), len(a)


def error_stats(errors_mm: ArrayLike, *, seed: int = 0, n_boot: int = 2000) -> ErrorStats:
    """Summary of signed errors (measured − truth). Mean has a seeded bootstrap CI; the within-tolerance shares have
    Wilson CIs."""
    e = np.asarray(errors_mm, dtype=np.float64).ravel()
    e = e[np.isfinite(e)]
    if len(e) == 0:
        return _nan_stats()
    a = np.abs(e)
    k3, n = within(a, 0.3)
    k5, _ = within(a, 0.5)
    return ErrorStats(
        n=n,
        mean_mm=float(a.mean()),
        mean_ci95_mm=bootstrap_ci(a, seed=seed, n_boot=n_boot),
        median_mm=float(np.median(a)),
        p90_mm=float(np.percentile(a, 90)),
        max_mm=float(a.max()),
        within_0_3=k3 / n,
        within_0_3_ci95=wilson_ci(k3, n),
        within_0_5=k5 / n,
        within_0_5_ci95=wilson_ci(k5, n),
        signed_mean_mm=float(e.mean()),
    )


@dataclass(frozen=True)
class RateStats:
    k: int
    n: int
    rate: float
    ci95: tuple[float, float]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def rate(k: int, n: int) -> RateStats:
    return RateStats(k, n, (k / n) if n else math.nan, wilson_ci(k, n))


def pass_at(per_item_abs_errors: Iterable[Sequence[float]], tol_mm: float) -> RateStats:
    """pass@tol: share of items (photos/parts) whose EVERY named dimension is within tol. Items with no scored
    dimension are not counted (report them as failures separately)."""
    k = n = 0
    for errs in per_item_abs_errors:
        if len(errs) == 0:
            continue
        n += 1
        k += int(all(abs(x) <= tol_mm + 1e-9 for x in errs))
    return rate(k, n)


@dataclass(frozen=True)
class Summary:
    """mean/median/P90/max of a per-item metric (IoU, Hausdorff mm, ...) with a bootstrap CI of the mean."""

    n: int
    mean: float
    mean_ci95: tuple[float, float]
    median: float
    p90: float
    min: float
    max: float

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def summarize(values: ArrayLike, *, seed: int = 0) -> Summary:
    v = np.asarray(values, dtype=np.float64).ravel()
    v = v[np.isfinite(v)]
    if len(v) == 0:
        nan = math.nan
        return Summary(0, nan, (nan, nan), nan, nan, nan, nan)
    return Summary(
        n=len(v),
        mean=float(v.mean()),
        mean_ci95=bootstrap_ci(v, seed=seed),
        median=float(np.median(v)),
        p90=float(np.percentile(v, 90)),
        min=float(v.min()),
        max=float(v.max()),
    )


def iou_summary(ious: ArrayLike, *, seed: int = 0) -> Summary:
    """Silhouette IoU per view/item (0..1)."""
    return summarize(ious, seed=seed)


def hausdorff_summary(hausdorff_mm: ArrayLike, *, seed: int = 0) -> Summary:
    """Hausdorff (or HD95) distance per view/item in mm."""
    return summarize(hausdorff_mm, seed=seed)


def group_errors(rows: Iterable[Mapping[str, object]], key: str, err_key: str = "error_mm") -> dict[str, list[float]]:
    """Signed errors grouped by `row[key]` (rows without a finite error are skipped)."""
    out: dict[str, list[float]] = {}
    for r in rows:
        e = r.get(err_key)
        if not isinstance(e, int | float) or not math.isfinite(float(e)):
            continue
        out.setdefault(str(r.get(key)), []).append(float(e))
    return out


__all__ = [
    "TOLS_MM",
    "ErrorStats",
    "RateStats",
    "Summary",
    "bootstrap_ci",
    "error_stats",
    "group_errors",
    "hausdorff_summary",
    "iou_summary",
    "mcnemar_exact",
    "mcnemar_paired",
    "pass_at",
    "rate",
    "summarize",
    "wilson_ci",
    "within",
]
