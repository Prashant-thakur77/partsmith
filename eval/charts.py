"""Tiny dependency-free SVG charts for bench reports: convergence curves and error histograms.

Plain SVG strings with a light/dark-safe palette (currentColor for ink). Every chart states N in its title.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from html import escape

PALETTE = ("#2563eb", "#dc2626", "#16a34a", "#9333ea", "#ea580c", "#0891b2", "#4b5563", "#ca8a04", "#db2777")
W, H = 640, 340
ML, MR, MT, MB = 56, 150, 36, 44


def _nice_max(v: float) -> float:
    if not math.isfinite(v) or v <= 0:
        return 1.0
    e = 10 ** math.floor(math.log10(v))
    for m in (1, 2, 2.5, 5, 10):
        if v <= m * e:
            return float(m * e)
    return float(10 * e)


def _frame(
    title: str, x_label: str, y_label: str, y_max: float, x_ticks: Sequence[tuple[float, str]], sx: float, sy: float
) -> list[str]:
    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" '
        'font-family="system-ui, sans-serif" font-size="11" fill="currentColor">',
        f'<text x="{ML}" y="20" font-size="13" font-weight="600">{escape(title)}</text>',
        f'<line x1="{ML}" y1="{H - MB}" x2="{W - MR}" y2="{H - MB}" stroke="currentColor" stroke-opacity="0.5"/>',
        f'<line x1="{ML}" y1="{MT}" x2="{ML}" y2="{H - MB}" stroke="currentColor" stroke-opacity="0.5"/>',
    ]
    for i in range(5):
        v = y_max * i / 4
        y = H - MB - v * sy
        out.append(
            f'<line x1="{ML}" y1="{y:.1f}" x2="{W - MR}" y2="{y:.1f}" stroke="currentColor" stroke-opacity="0.1"/>'
        )
        out.append(f'<text x="{ML - 6}" y="{y + 4:.1f}" text-anchor="end">{v:g}</text>')
    for xv, lab in x_ticks:
        x = ML + xv * sx
        out.append(f'<text x="{x:.1f}" y="{H - MB + 16}" text-anchor="middle">{escape(lab)}</text>')
    out.append(f'<text x="{(ML + W - MR) / 2:.1f}" y="{H - 8}" text-anchor="middle">{escape(x_label)}</text>')
    out.append(
        f'<text x="14" y="{(MT + H - MB) / 2:.1f}" text-anchor="middle" '
        f'transform="rotate(-90 14 {(MT + H - MB) / 2:.1f})">{escape(y_label)}</text>'
    )
    return out


def convergence_svg(
    curves: Mapping[str, Sequence[float | None]],
    title: str,
    *,
    y_label: str = "median max error (mm)",
    threshold: float | None = 0.5,
) -> str:
    """One polyline per series: value per iteration (1-based); None = no data at that iteration."""
    n_it = max((len(c) for c in curves.values()), default=1) or 1
    vals = [v for c in curves.values() for v in c if v is not None and math.isfinite(v)]
    y_max = _nice_max(max([*vals, threshold or 0.0], default=1.0))
    sx = (W - ML - MR) / max(n_it - 1, 1)
    sy = (H - MT - MB) / y_max
    ticks = [(float(i), str(i + 1)) for i in range(n_it)]
    out = _frame(title, "iteration", y_label, y_max, ticks, sx, sy)
    if threshold is not None:
        y = H - MB - threshold * sy
        out.append(f'<line x1="{ML}" y1="{y:.1f}" x2="{W - MR}" y2="{y:.1f}" stroke="#16a34a" stroke-dasharray="4 3"/>')
        out.append(f'<text x="{W - MR + 4}" y="{y + 4:.1f}" fill="#16a34a">{threshold:g} mm</text>')
    for k, (name, c) in enumerate(curves.items()):
        col = PALETTE[k % len(PALETTE)]
        pts = [
            (ML + i * sx, H - MB - min(v, y_max) * sy) for i, v in enumerate(c) if v is not None and math.isfinite(v)
        ]
        if len(pts) > 1:
            out.append(
                f'<polyline fill="none" stroke="{col}" stroke-width="2" points="'
                + " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)
                + '"/>'
            )
        for x, y in pts:
            out.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="2.5" fill="{col}"/>')
        ly = MT + 14 * k + 6
        out.append(f'<rect x="{W - MR + 10}" y="{ly - 8}" width="10" height="3" fill="{col}"/>')
        out.append(f'<text x="{W - MR + 24}" y="{ly - 3}">{escape(name)}</text>')
    out.append("</svg>")
    return "\n".join(out)


def histogram_svg(
    series: Mapping[str, Sequence[float]], title: str, *, bin_mm: float = 0.1, max_mm: float = 2.0
) -> str:
    """Grouped histogram of absolute errors; the last bin collects everything ≥ max_mm."""
    nb = round(max_mm / bin_mm) + 1
    counts: dict[str, list[int]] = {}
    for name, xs in series.items():
        c = [0] * nb
        for x in xs:
            if not math.isfinite(x):
                continue
            c[min(int(abs(x) / bin_mm), nb - 1)] += 1
        counts[name] = c
    y_max = _nice_max(max((max(c) for c in counts.values() if c), default=1))
    sx = (W - ML - MR) / nb
    sy = (H - MT - MB) / y_max
    step = max(1, nb // 10)
    ticks = [(i + 0.5, f"{i * bin_mm:g}" if i < nb - 1 else f"≥{max_mm:g}") for i in range(0, nb, step)]
    out = _frame(title, "absolute error (mm)", "dimensions", y_max, ticks, sx, sy)
    k_n = max(len(counts), 1)
    for k, (name, c) in enumerate(counts.items()):
        col = PALETTE[k % len(PALETTE)]
        bw = sx / k_n * 0.9
        for i, n in enumerate(c):
            if n:
                x = ML + i * sx + k * bw
                out.append(
                    f'<rect x="{x:.1f}" y="{H - MB - n * sy:.1f}" width="{bw:.1f}" height="{n * sy:.1f}" '
                    f'fill="{col}" fill-opacity="0.8"/>'
                )
        ly = MT + 14 * k + 6
        out.append(f'<rect x="{W - MR + 10}" y="{ly - 8}" width="10" height="8" fill="{col}"/>')
        out.append(f'<text x="{W - MR + 24}" y="{ly}">{escape(name)} (N={sum(c)})</text>')
    out.append("</svg>")
    return "\n".join(out)
