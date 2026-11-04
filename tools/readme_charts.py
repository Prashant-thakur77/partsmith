"""README charts as plain SVG, drawn from the bench reports and the stored battery-cover run (`tools/readme.py` calls this).

No number is typed here. A solid surface keeps each chart readable on GitHub's light and dark pages; the title names a
single series, and two-series charts carry a legend plus direct labels, so identity is never colour alone.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parents[1]
LATEST = ROOT / "eval" / "reports" / "latest"
OUT = ROOT / "docs" / "media" / "charts"
RUN = ROOT / "data" / "replays" / "j_261029_daf26965" / "run.jsonl"

SURFACE, INK, MUTED, GRID = "#fdfcf9", "#1c2230", "#5b6170", "#e4dfd4"
BASE, OURS = "#2f6f9f", "#c2410c"  # validated together against SURFACE (lightness, chroma, colour-blind separation)
GOOD, OFF, OTHER = "#2e7d4f", "#b7791f", "#cfc8ba"
FONT = "system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif"
W = 760


def _load(name: str) -> dict[str, Any]:
    data = json.loads((LATEST / name).read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def _text(
    x: float, y: float, s: object, size: int = 13, fill: str = INK, weight: int = 400, anchor: str = "start"
) -> str:
    return (
        f'<text x="{x:.1f}" y="{y:.1f}" font-size="{size}" fill="{fill}" font-weight="{weight}" '
        f'text-anchor="{anchor}">{escape(str(s))}</text>'
    )


def _bar(x: float, y: float, w: float, h: float, fill: str) -> str:
    """A horizontal bar: rounded at the data end, square on the baseline."""
    w = max(w, 2.0)
    r = min(4.0, w, h / 2)
    return (
        f'<path d="M{x:.1f} {y:.1f}H{x + w - r:.1f}Q{x + w:.1f} {y:.1f} {x + w:.1f} {y + r:.1f}V{y + h - r:.1f}'
        f'Q{x + w:.1f} {y + h:.1f} {x + w - r:.1f} {y + h:.1f}H{x:.1f}Z" fill="{fill}"/>'
    )


def _svg(height: int, title: str, sub: str, source: str, body: list[str]) -> str:
    return "\n".join(
        [
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {height}" width="{W}" height="{height}" '
            f'font-family="{FONT}" role="img" aria-label="{escape(title, {chr(34): "&quot;"})}">',
            f'<rect width="{W}" height="{height}" rx="10" fill="{SURFACE}" stroke="{GRID}"/>',
            _text(24, 32, title, 17, INK, 600),
            _text(24, 52, sub, 13, MUTED),
            *body,
            _text(24, height - 14, source, 11, MUTED),
            "</svg>",
        ]
    )


def rounds_chart() -> str:
    """Error per round of the stored live run, against the pass limit."""
    errors = [
        float(e["hausdorff_mm"])
        for e in map(json.loads, RUN.read_text(encoding="utf-8").splitlines())
        if e.get("t") == "iteration"
    ]
    limit = float(_load("provenance.json")["thresholds"]["HAUSDORFF_PASS_MM"])
    x0, x1, y0, y1 = 70.0, W - 60.0, 80.0, 260.0
    top = max(errors) * 1.15

    def px(i: int) -> float:
        return x0 + (x1 - x0) * (i / max(len(errors) - 1, 1))

    def py(v: float) -> float:
        return y1 - (y1 - y0) * (v / top)

    body = [f'<line x1="{x0}" y1="{y1}" x2="{x1}" y2="{y1}" stroke="{GRID}"/>']
    body.append(
        f'<line x1="{x0}" y1="{py(limit):.1f}" x2="{x1}" y2="{py(limit):.1f}" stroke="{MUTED}" stroke-dasharray="5 4"/>'
    )
    body.append(_text(x0, py(limit) + 16, f"pass limit {limit} mm", 12, MUTED))
    pts = " ".join(f"{px(i):.1f},{py(v):.1f}" for i, v in enumerate(errors))
    body.append(f'<polyline points="{pts}" fill="none" stroke="{OURS}" stroke-width="2"/>')
    names = ["First build"] + [f"Round {i + 2}" for i in range(len(errors) - 1)]
    for i, v in enumerate(errors):
        body.append(
            f'<circle cx="{px(i):.1f}" cy="{py(v):.1f}" r="5" fill="{OURS}" stroke="{SURFACE}" stroke-width="2"/>'
        )
        body.append(
            _text(
                px(i),
                py(v) - 12,
                f"{v:.2f} mm",
                13,
                INK,
                600,
                "middle" if 0 < i < len(errors) - 1 else ("start" if i == 0 else "end"),
            )
        )
        body.append(
            _text(
                px(i),
                y1 + 20,
                names[i],
                12,
                MUTED,
                400,
                "middle" if 0 < i < len(errors) - 1 else ("start" if i == 0 else "end"),
            )
        )
    return _svg(
        320,
        "One stored live run: outline gap per round",
        "Battery cover on a rendered photo. It fails twice, the agent edits the program, code passes it on round 3.",
        "Source: data/replays/j_261029_daf26965/run.jsonl (iteration events) · eval/reports/latest/provenance.json",
        body,
    )


def _pairs(
    rows: list[tuple[str, float, float]], x0: float, x1: float, y: float, top: float, unit: str, a: str, b: str
) -> list[str]:
    out: list[str] = []
    for name, base, ours in rows:
        out.append(_text(24, y + 22, name, 13, INK, 600))
        for label, v, fill, dy in ((a, base, BASE, 0), (b, ours, OURS, 22)):
            out.append(_bar(x0, y + dy, (x1 - x0) * v / top, 18, fill))
            out.append(_text(x0 + (x1 - x0) * v / top + 8, y + dy + 14, f"{label}: {v:g}{unit}", 12, INK))
        y += 58
    return out


def single_vs_loop_chart() -> str:
    """Median error per dimension: one shot at the model against the full loop, suite by suite."""
    rep = _load("report.json")
    rows: list[tuple[str, float, float]] = []
    for key, name in (("synthetic", "Rendered parts"), ("reference_objects", "Reference objects")):
        by = {r["config"]: r for r in rep["tables"][key]["rows"]}
        rows.append(
            (
                f"{name} (n = {by['PS']['n']})",
                float(by["B1"]["median_abs_err_mm"]),
                float(by["PS"]["median_abs_err_mm"]),
            )
        )
    top = max(max(b, o) for _, b, o in rows) * 1.5
    body = _pairs(rows, 210, W - 40, 78, top, " mm", "Single shot", "Full loop")
    return _svg(
        230,
        "Median error per dimension: single shot and full loop",
        "Lower is better. Both use the same measurements; the loop adds the verifier's feedback and the fix agent.",
        "Source: eval/reports/latest/report.json, tables.synthetic and tables.reference_objects, configs B1 and PS",
        body,
    )


def mesh_vs_knob_chart() -> str:
    """Hole-spacing shift when one dimension changes: stretching a mesh against turning a program's knob."""
    s = _load("program_vs_mesh.json")["summary"]
    mesh, knob = float(s["mesh_hole_spacing_shift_median_mm"]), float(s["knob_hole_spacing_shift_median_mm"])
    x0, x1 = 170.0, W - 120.0
    body = [
        _text(24, 100, "Stretch the mesh", 14, INK, 600),
        _bar(x0, 84, x1 - x0, 24, BASE),
        _text(x1 + 8, 102, f"{mesh:g} mm", 14, INK, 600),
        _text(24, 146, "Turn the knob", 14, INK, 600),
        _bar(x0, 130, (x1 - x0) * knob / mesh, 24, OURS),
        _text(x0 + 12, 148, f"{knob:g} mm", 14, INK, 600),
    ]
    return _svg(
        200,
        "Change one dimension: how far do the holes move?",
        f"Median hole-spacing shift over {s['parts']} parts and {s['rows']} edits, built in the sandbox and measured by code.",
        "Source: eval/reports/latest/program_vs_mesh.json (pure code, no models)",
        body,
    )


def verified_counts(rep: dict[str, Any]) -> list[tuple[str, int, int, int]]:
    """(suite, verified and within the limit, verified but off, not verified) for the PS runs of each scored suite."""
    names = {
        "synthetic": "Rendered parts",
        "reference_objects": "Reference objects",
        "control": "Intact parts (top photo only)",
        "public_photos": "Public photos, pasted",
    }
    out = []
    for key, name in names.items():
        runs = (rep.get("runs") or {}).get(key, {}).get("PS") or []
        verified = [r for r in runs if r.get("verified")]
        off = sum((r.get("max_abs_err_mm") or 0) > 0.5 for r in verified)
        out.append((f"{name} (n = {len(runs)})", len(verified) - off, off, len(runs) - len(verified)))
    return out


def suites_chart() -> str:
    """Every PS run by suite: verified and right, verified but off on some dimension, not verified."""
    rows = verified_counts(_load("report.json"))
    x0, x1 = 275.0, W - 30.0
    top = max(a + b + c for _, a, b, c in rows)
    body, y = [], 92.0
    for colour, label, lx in (
        (GOOD, "Verified, within 0.5 mm on every size", 24),
        (OFF, "Verified, but over 0.5 mm off", 290),
        (OTHER, "Not verified", 510),
    ):
        body.append(f'<rect x="{lx}" y="64" width="12" height="12" rx="2" fill="{colour}"/>')
        body.append(_text(lx + 18, 75, label, 12, INK))
    for name, a, b, c in rows:
        body.append(_text(24, y + 17, name, 13, INK, 600))
        x = x0
        for v, colour in ((a, GOOD), (b, OFF), (c, OTHER)):
            if v:
                w = (x1 - x0) * v / top
                body.append(
                    f'<rect x="{x:.1f}" y="{y}" width="{max(w - 2, 2):.1f}" height="24" rx="3" fill="{colour}"/>'
                )
                body.append(
                    _text(x + max(w - 2, 2) / 2, y + 17, v, 12, "#ffffff" if colour != OTHER else INK, 600, "middle")
                )
                x += w
        y += 36
    return _svg(
        int(y) + 34,
        "Every full-loop run, suite by suite",
        "Most hard photos end as best effort. Verified is not a promise on sizes a photo cannot see, such as height from above.",
        "Source: eval/reports/latest/report.json, runs.*.PS (verified, max_abs_err_mm)",
        body,
    )


def bench_charts() -> list[str]:
    """The bench's own charts from the newest dated report, given a solid surface so they read on any page."""
    dated = sorted(p for p in LATEST.parent.iterdir() if p.is_dir() and (p / "charts").is_dir() and p.name != "latest")
    names = []
    for src in sorted((dated[-1] / "charts").glob("*.svg")) if dated else []:
        svg = src.read_text(encoding="utf-8")
        head, rest = svg.split(">", 1)
        svg = f'{head} color="{INK}"><rect width="100%" height="100%" fill="{SURFACE}"/>{rest}'
        (OUT / src.name).write_text(svg, encoding="utf-8")
        names.append(src.name)
    return names


def write_all() -> list[str]:
    OUT.mkdir(parents=True, exist_ok=True)
    charts = {
        "rounds.svg": rounds_chart,
        "single_vs_loop.svg": single_vs_loop_chart,
        "mesh_vs_knob.svg": mesh_vs_knob_chart,
        "suites.svg": suites_chart,
    }
    for name, fn in charts.items():
        (OUT / name).write_text(fn() + "\n", encoding="utf-8")
    return [*charts, *bench_charts()]


if __name__ == "__main__":
    print("\n".join(write_all()))
