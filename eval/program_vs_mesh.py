"""Program vs mesh: what happens to the rest of a part when you change one dimension.

For each family template (and, with a registry present, each published part) we make a typical variant two ways:

(a) knob edit: change the one parameter in the part program and rebuild ("M4 hole", "+0.3 mm clearance",
    "+5 mm length");
(b) mesh scaling: scale the whole solid uniformly until the target dimension has the requested value. This is what you
    can do to an STL without its program. The scaled solid is built in the same sandbox, so both variants are measured
    the same way.

Both variants are measured with `services.verifier.solid_features` (holes, plate thickness, walls, bbox) and with the
part's declared interfaces, and compared with the unmodified part. "Collateral error" is the change in dimensions the
intent should have left alone:

- hole intents ("M4 hole", "+0.3 mm clearance"): hole spacing, the position and diameter of the other holes, plate
  thickness, outline length/width/height;
- "+5 mm length": hole diameters, plate thickness, width and height (hole spacing is reported, not counted: a longer
  part may legitimately spread its holes).

Pure code, no model calls. Writes `eval/reports/latest/program_vs_mesh.{json,md}` with a one-line headline.

    uv run python -m eval.program_vs_mesh [--no-registry] [--jobs 4]
"""

from __future__ import annotations

import argparse
import ast
import json
import math
import sys
from collections.abc import Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
from scipy.optimize import linear_sum_assignment

from services.geom_worker.program import defaults as program_defaults
from services.geom_worker.program import module_literals, parse_params
from services.geom_worker.sandbox import ExecResult, WarmPool, run_program
from services.verifier.functional import SCREWS

REPO = Path(__file__).resolve().parents[1]
OUT_DIR = REPO / "eval" / "reports" / "latest"
M4_NORMAL_MM = SCREWS["M4"][2]
CLEARANCE_MM = 0.3
LENGTH_MM = 5.0
HOLE_KEYS = ("hole_1.diameter", "bore.diameter", "pin.diameter", "cable.diameter")


@dataclass
class Part:
    name: str
    source: str  # "template" | "registry"
    code: str
    defaults: dict[str, float]
    measure_map: dict[str, str]


@dataclass
class Measured:
    holes: list[tuple[float, float, float]]  # (x, y, diameter)
    interfaces: dict[str, float]
    plate_mm: float | None
    min_wall_mm: float | None
    size_mm: tuple[float, float, float]


@dataclass
class Row:
    part: str
    source: str
    intent: str
    way: str  # "knob edit" | "mesh scaling"
    param: str
    target_mm: float
    achieved_mm: float | None
    scale: float | None
    collateral_mm: float | None
    metrics: dict[str, float | None] = field(default_factory=dict)
    error: str | None = None


# ----------------------------------------------------------------------------------------------- building


def scaled_program(code: str, factor: float) -> str:
    """The same part program, scaled uniformly about its origin (the mounting face stays on Z = 0)."""
    tree = ast.parse(code)
    body = []
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "result" for t in node.targets):
            continue
        if isinstance(node, ast.FunctionDef) and node.name in ("build", "interfaces"):
            node.name = node.name + "_unscaled"
        body.append(node)
    tree.body = body
    src = ast.unparse(tree)
    f = repr(float(factor))
    src += (
        f"\n\n\ndef build(p):\n    return cq.Workplane('XY').add(build_unscaled(p).val().scale({f}))\n"
        f"\n\ndef interfaces(p):\n"
        f"    return [dict(i, at=[c * {f} for c in i['at']], mates=i.get('mates', [])) for i in interfaces_unscaled(p)]\n"
        if "def interfaces" in code
        else f"\n\n\ndef build(p):\n    return cq.Workplane('XY').add(build_unscaled(p).val().scale({f}))\n"
    )
    src += "\n\nresult = build({k: v[0] for k, v in PARAMS.items()})\n"
    return src


def measure(r: ExecResult) -> Measured:
    f = r.features or {}
    holes = [(h["center_mm"][0], h["center_mm"][1], h["diameter_mm"]) for h in f.get("holes", [])]
    itf = {str(i["id"]): float(i["gap_mm"]) for i in f.get("interfaces", []) if i.get("gap_mm") is not None}
    s = f.get("size_mm") or [0.0, 0.0, 0.0]
    return Measured(holes, itf, f.get("plate_thickness_mm"), f.get("min_wall_mm"), (s[0], s[1], s[2]))


def _match(a: Sequence[tuple[float, float, float]], b: Sequence[tuple[float, float, float]]) -> list[tuple[int, int]]:
    if not a or not b:
        return []
    ca, cb = np.array([h[:2] for h in a]), np.array([h[:2] for h in b])
    cost = np.linalg.norm(ca[:, None] - cb[None], axis=2)
    r, c = linear_sum_assignment(cost)
    return [(int(i), int(j)) for i, j in zip(r, c, strict=True)]


def collateral(
    base: Measured, var: Measured, intent: str, targets: set[int], also_intended: frozenset[str] = frozenset()
) -> dict[str, float | None]:
    """Changes (mm) in dimensions the intent should have left alone. `targets`: base hole indices being edited;
    `also_intended`: outline dimensions the edited parameter controls by declaration (e.g. width of a round part)."""
    m: dict[str, float | None] = {}
    pairs = _match(base.holes, var.holes)
    bmap = dict(pairs)
    spacing = 0.0
    for i in range(len(base.holes)):
        for j in range(i + 1, len(base.holes)):
            if i in bmap and j in bmap:
                db = math.dist(base.holes[i][:2], base.holes[j][:2])
                dv = math.dist(var.holes[bmap[i]][:2], var.holes[bmap[j]][:2])
                spacing = max(spacing, abs(dv - db))
    m["hole_spacing_shift_mm"] = spacing if len(base.holes) > 1 else None
    others = [abs(var.holes[j][2] - base.holes[i][2]) for i, j in pairs if i not in targets or intent == "length"]
    m["other_hole_d_change_mm"] = max(others) if others else None
    moved = [math.dist(var.holes[j][:2], base.holes[i][:2]) for i, j in pairs if i in targets]
    m["edited_hole_moved_mm"] = max(moved) if moved else None
    m["hole_count_change"] = float(abs(len(var.holes) - len(base.holes)))
    m["plate_thickness_change_mm"] = (
        abs(var.plate_mm - base.plate_mm) if var.plate_mm is not None and base.plate_mm is not None else None
    )
    m["min_wall_change_mm"] = (
        abs(var.min_wall_mm - base.min_wall_mm)
        if var.min_wall_mm is not None and base.min_wall_mm is not None
        else None
    )
    m["length_change_mm"] = abs(var.size_mm[0] - base.size_mm[0])
    m["width_change_mm"] = abs(var.size_mm[1] - base.size_mm[1])
    m["height_change_mm"] = abs(var.size_mm[2] - base.size_mm[2])
    keep = [
        "other_hole_d_change_mm",
        "plate_thickness_change_mm",
        "width_change_mm",
        "height_change_mm",
        "hole_count_change",
    ]
    if intent != "length":
        keep += ["hole_spacing_shift_mm", "length_change_mm", "edited_hole_moved_mm"]
    keep = [k for k in keep if k.split("_change")[0] not in also_intended]
    vals = [v for k in keep if (v := m.get(k)) is not None]
    m["collateral_mm"] = max(vals) if vals else None
    return m


# ----------------------------------------------------------------------------------------------- intents


@dataclass
class Intent:
    key: str  # "m4_hole" | "clearance" | "length"
    label: str
    param: str
    target_param: float  # value for the knob edit
    measure_key: str  # "hole" or "interface:<id>" or "length"


def intents_for(part: Part, base: Measured) -> list[Intent]:
    specs = {s.name: s for s in parse_params(part.code)}
    out: list[Intent] = []
    hole_param = next((part.measure_map[k] for k in ("hole_1.diameter",) if k in part.measure_map), None)
    if hole_param is None:
        hole_param = next((n for n in ("hole_d", "hole_1_d", "pivot_d") if n in specs), None)
    if hole_param and base.holes:
        s = specs[hole_param]
        if s.min <= M4_NORMAL_MM <= s.max and abs(part.defaults[hole_param] - M4_NORMAL_MM) > 0.05:
            out.append(Intent("m4_hole", f"M4 hole (Ø{M4_NORMAL_MM} mm)", hole_param, M4_NORMAL_MM, "hole"))
    clear = next((part.measure_map[k] for k in HOLE_KEYS if k in part.measure_map), hole_param)
    if clear and clear in specs:
        s = specs[clear]
        target = part.defaults[clear] + CLEARANCE_MM
        if target <= s.max:
            itf = {"bore_d": "shaft_bore", "pin_d": "pin_hole", "cable_d": "cable_channel"}.get(clear)
            key = f"interface:{itf}" if itf and itf in base.interfaces else "hole"
            if key == "hole" and not base.holes:
                key = ""
            if key:
                out.append(Intent("clearance", f"+{CLEARANCE_MM} mm clearance ({clear})", clear, target, key))
    lp = part.measure_map.get("length")
    if lp and lp in specs and part.defaults[lp] + LENGTH_MM <= specs[lp].max:
        out.append(Intent("length", f"+{LENGTH_MM:g} mm length", lp, part.defaults[lp] + LENGTH_MM, "length"))
    return out


def _targets(base: Measured, knob: Measured) -> set[int]:
    """Base holes whose diameter the knob edit changed (the holes the intent is about)."""
    return {i for i, j in _match(base.holes, knob.holes) if abs(knob.holes[j][2] - base.holes[i][2]) > 1e-3}


def _value(m: Measured, key: str, targets: set[int], base: Measured) -> float | None:
    if key == "length":
        return m.size_mm[0]
    if key.startswith("interface:"):
        return m.interfaces.get(key.split(":", 1)[1])
    if not targets:
        return None
    pairs = dict(_match(base.holes, m.holes))
    i = min(targets)
    return m.holes[pairs[i]][2] if i in pairs else None


def run_part(part: Part, pool: WarmPool) -> list[Row]:
    def build(code: str, params: Mapping[str, float]) -> ExecResult:
        r = run_program(code, params, pool=pool, outputs=(), timeout_s=30)
        r.cleanup()
        return r

    base_r = build(part.code, part.defaults)
    if not base_r.ok:
        return [
            Row(
                part.name,
                part.source,
                "-",
                "-",
                "-",
                0,
                None,
                None,
                None,
                error=base_r.error.short() if base_r.error else "build failed",
            )
        ]
    base = measure(base_r)
    rows: list[Row] = []
    for it in intents_for(part, base):
        knob_r = build(part.code, {**part.defaults, it.param: it.target_param})
        if not knob_r.ok:
            rows.append(
                Row(
                    part.name,
                    part.source,
                    it.label,
                    "knob edit",
                    it.param,
                    it.target_param,
                    None,
                    None,
                    None,
                    error=knob_r.error.short() if knob_r.error else "build failed",
                )
            )
            continue
        knob = measure(knob_r)
        targets = _targets(base, knob) if it.key != "length" else set()
        intent = "length" if it.key == "length" else "hole"
        also = frozenset(k for k, v in part.measure_map.items() if v == it.param and k in ("length", "width"))
        target_dim = _value(knob, it.measure_key, targets, base)
        base_dim = _value(base, it.measure_key, targets, base)
        rows.append(
            Row(
                part.name,
                part.source,
                it.label,
                "knob edit",
                it.param,
                it.target_param,
                target_dim,
                None,
                **_coll(base, knob, intent, targets, also),
            )
        )
        if target_dim is None or not base_dim:
            continue
        factor = target_dim / base_dim
        mesh_r = build(scaled_program(part.code, factor), part.defaults)
        if not mesh_r.ok:
            rows.append(
                Row(
                    part.name,
                    part.source,
                    it.label,
                    "mesh scaling",
                    it.param,
                    target_dim,
                    None,
                    factor,
                    None,
                    error=mesh_r.error.short() if mesh_r.error else "build failed",
                )
            )
            continue
        mesh = measure(mesh_r)
        mesh_targets = targets
        rows.append(
            Row(
                part.name,
                part.source,
                it.label,
                "mesh scaling",
                it.param,
                target_dim,
                _value(mesh, it.measure_key, mesh_targets, base),
                factor,
                **_coll(base, mesh, intent, mesh_targets, also),
            )
        )
    return rows


def _coll(base: Measured, var: Measured, intent: str, targets: set[int], also: frozenset[str]) -> dict[str, Any]:
    m = collateral(base, var, intent, targets, also)
    return {"collateral_mm": m.pop("collateral_mm"), "metrics": m}


# ----------------------------------------------------------------------------------------------- parts + report


def template_parts() -> list[Part]:
    from services.agent.templates import list_templates

    return [Part(t.name, "template", t.code, dict(t.defaults), dict(t.measure_map)) for t in list_templates()]


def registry_parts(limit: int = 200) -> list[Part]:
    """Published parts (if a registry exists under $PARTSMITH_HOME)."""
    try:
        from services.registry.store import get_registry

        parts, _ = get_registry().search("", limit=limit)
    except Exception:
        return []
    out = []
    for p in parts:
        try:
            mm = module_literals(p.code, ("MEASURE_MAP",)).get("MEASURE_MAP") or {}
            out.append(
                Part(p.slug, "registry", p.code, program_defaults(p.code), {str(k): str(v) for k, v in mm.items()})
            )
        except (SyntaxError, ValueError):
            continue
    return out


def summarize(rows: Sequence[Row]) -> dict[str, Any]:
    def worst(way: str, metric: str, intents: tuple[str, ...] = ("M4", "+0.3")) -> float | None:
        vals = [
            v
            for r in rows
            if r.way == way and r.intent.startswith(intents) and (v := r.metrics.get(metric)) is not None
        ]
        return round(max(vals), 3) if vals else None

    def med(way: str, metric: str) -> float | None:
        vals = [
            v
            for r in rows
            if r.way == way and r.intent.startswith(("M4", "+0.3")) and (v := r.metrics.get(metric)) is not None
        ]
        return round(float(np.median(vals)), 3) if vals else None

    def all_coll(way: str) -> float | None:
        vals = [r.collateral_mm for r in rows if r.way == way and r.collateral_mm is not None]
        return round(max(vals), 3) if vals else None

    s: dict[str, Any] = {
        "mesh_hole_spacing_shift_mm": worst("mesh scaling", "hole_spacing_shift_mm"),
        "knob_hole_spacing_shift_mm": worst("knob edit", "hole_spacing_shift_mm"),
        "mesh_hole_spacing_shift_median_mm": med("mesh scaling", "hole_spacing_shift_mm"),
        "knob_hole_spacing_shift_median_mm": med("knob edit", "hole_spacing_shift_mm"),
        "mesh_collateral_max_mm": all_coll("mesh scaling"),
        "knob_collateral_max_mm": all_coll("knob edit"),
        "rows": len(rows),
        "parts": len({(r.part, r.source) for r in rows}),
    }
    knob_max = s["knob_hole_spacing_shift_mm"] or 0.0
    s["headline"] = (
        f"Hole edits: mesh scaling shifted hole spacing by {s['mesh_hole_spacing_shift_median_mm']} mm (median, up to "
        f"{s['mesh_hole_spacing_shift_mm']} mm); the knob edit by {s['knob_hole_spacing_shift_median_mm']} mm"
        + (
            f" (up to {knob_max} mm in parts whose program ties hole position to hole size)."
            if knob_max > 0.01
            else "."
        )
    )
    return s


def render_md(summary: Mapping[str, Any], rows: Sequence[Row]) -> str:
    def f(v: float | None, nd: int = 2) -> str:
        return "–" if v is None else f"{v:.{nd}f}"

    lines = [
        "# Program vs mesh: collateral error of one-dimension edits",
        "",
        f"**{summary['headline']}**",
        "",
        "Generated by `eval/program_vs_mesh.py` (pure code, no models). Each variant is built in the sandbox and measured "
        "with the verifier's solid features. Collateral = largest change in a dimension the intent should not touch.",
        "",
        f"Largest collateral change over all variants: mesh scaling {summary['mesh_collateral_max_mm']} mm, knob edit "
        f"{summary['knob_collateral_max_mm']} mm. Non-zero knob-edit values come from the part programs' own design rules "
        "(e.g. screw-hole edge distance grows with the hole size), which are visible in the program; mesh scaling "
        "changes every dimension by the same factor.",
        "",
        "| part | intent | way | target (mm) | achieved (mm) | scale | hole spacing Δ | other hole Ø Δ | plate Δ | "
        "length Δ | width Δ | collateral (mm) |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        m = r.metrics
        lines.append(
            f"| {r.part} | {r.intent} | {r.way} | {f(r.target_mm)} | {f(r.achieved_mm)} | "
            f"{f(r.scale, 4) if r.scale else '–'} | {f(m.get('hole_spacing_shift_mm'))} | "
            f"{f(m.get('other_hole_d_change_mm'))} | {f(m.get('plate_thickness_change_mm'))} | "
            f"{f(m.get('length_change_mm'))} | {f(m.get('width_change_mm'))} | "
            f"{f(r.collateral_mm) if r.error is None else 'error: ' + r.error[:40]} |"
        )
    return "\n".join(lines) + "\n"


def run(parts: Sequence[Part], jobs: int = 2) -> tuple[dict[str, Any], list[Row]]:
    pool = WarmPool(size=jobs)
    try:
        with ThreadPoolExecutor(jobs) as ex:
            rows = [r for rs in ex.map(lambda p: run_part(p, pool), parts) for r in rs]
    finally:
        pool.close()
    return summarize(rows), rows


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    ap.add_argument("--no-registry", action="store_true", help="templates only")
    ap.add_argument("--jobs", type=int, default=2)
    ap.add_argument("--out", type=Path, default=OUT_DIR)
    a = ap.parse_args(argv)
    parts = template_parts() + ([] if a.no_registry else registry_parts())
    summary, rows = run(parts, a.jobs)
    a.out.mkdir(parents=True, exist_ok=True)
    doc = {"summary": summary, "rows": [asdict(r) for r in rows]}
    (a.out / "program_vs_mesh.json").write_text(json.dumps(doc, indent=1) + "\n")
    (a.out / "program_vs_mesh.md").write_text(render_md(summary, rows))
    print(summary["headline"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
