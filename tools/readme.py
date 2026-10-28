"""Regenerate the script-owned blocks of README.md: the Meta tooling table (file:line found in the code, never typed by hand)
and the headline bench tables (read from eval/reports/latest/report.json).

Run: `uv run python -m tools.readme` (also part of `make bench`). Blocks live between `<!-- BEGIN:<name> -->` and
`<!-- END:<name> -->` markers; everything else in README.md is left alone.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "README.md"
REPORT = ROOT / "eval" / "reports" / "latest" / "report.json"


@dataclass(frozen=True)
class Use:
    model: str
    kind: str  # "Meta Model API" | "open weights"
    role: str
    sites: tuple[tuple[str, str], ...]  # (file, regex) — first match gives the line


USES: tuple[Use, ...] = (
    Use(
        "SAM 3.1",
        "Meta Model API",
        "The measuring instrument: text-prompted part masks, point-prompted feature cuts (holes, slots, tapped points) and "
        "video tracking of a walk-around clip. Code turns every mask into millimetres",
        (
            ("services/agent/providers/routing.py", r"SAM_31 = Route"),
            ("services/metrology/segment.py", r"class ProviderSegmenter"),
            ("services/agent/evidence.py", r'getattr\(providers, "segment_points"'),
            ("services/agent/evidence.py", r'getattr\(providers, "segment_video"'),
        ),
    ),
    Use(
        "Muse Spark 1.3",
        "Meta Model API",
        "Understand stage: family, features, broken region, unknowns (strict PartSpec JSON), and the pixel it saw each "
        "hole or slot at, which SAM 3.1 then cuts and code measures. Watches and listens to a narrated walk-around clip "
        "and points at the features it hears about (frame and pixel), kept only if they land on the part",
        (
            ("services/agent/orchestrator.py", r'self\.call\("understand"'),
            ("services/agent/evidence.py", r"def feature_points"),
            ("services/agent/evidence.py", r"providers\.narrate_video\("),
        ),
    ),
    Use(
        "Muse Spark Open",
        "open weights (Baseten / Fireworks / Together)",
        "CadQuery builder, and the fix agent that operates PartSmith's own tools (inspect residuals, measure, segment, "
        "render, run tests, set knobs) until the verifier agrees",
        (
            ("services/agent/orchestrator.py", r'self\.call\("build"'),
            ("services/agent/agent_loop.py", r"run_agent\(STAGE, req, TOOLS"),
        ),
    ),
    Use(
        "Muse Glimmer 30B",
        "open weights (llama.cpp on a Modal GPU)",
        "Independent veto-only judge, shown side-by-side photo and model crops zoomed on the verifier's worst spots",
        (
            ("services/agent/orchestrator.py", r"evidence\.hotspot_crops\(rnd\)"),
            ("infra/modal/glimmer.py", r"^app = "),
        ),
    ),
    Use(
        "Muse Wonder",
        "Meta Model API",
        "Finds a published spec for the named appliance with web search. Code accepts a value only if a search really "
        "ran and its URL is one the search returned; cited values fill unknowns and never override a measurement. "
        "Also finds the original part's price with search grounding for the buy-or-print card (a price is kept only "
        "with its source link and a quote showing it) and plans part families for the factory",
        (
            ("services/agent/evidence.py", r'getattr\(providers, "lookup_spec"'),
            ("services/agent/providers/buy.py", r"def buy_lookup"),
            ("services/agent/providers/spec.py", r"def accept_values"),
            ("services/registry/steer.py", r'providers\.complete\("steer_plan"'),
        ),
    ),
    Use(
        "Muse Image",
        "Meta Model API",
        "Completes the broken region of the photo (accepted only if markers and the intact part are unchanged), an "
        "in-place repair preview and an install card (both labelled AI images)",
        (
            ("services/agent/evidence.py", r'getattr\(providers, "reconstruct"'),
            ("services/metrology/recon_gate.py", r"def gate_reconstruction"),
            ("services/media/preview.py", r"providers\.generate_image\("),
        ),
    ),
    Use(
        "Muse Voice Transcribe",
        "Meta Model API",
        'Hindi/English voice edits ("make the hole a bit bigger") mapped to knob changes, live while you talk (realtime '
        "stream relayed by the API, knob names as keywords) or from a recorded clip, and spoken answers",
        (
            ("services/media/voice.py", r"providers\.transcribe\("),
            ("services/api/voice_live.py", r"providers\.transcribe_stream\("),
        ),
    ),
    Use(
        "SAM 3 (open weights)",
        "open weights (Modal GPU)",
        "All-open-weights segmentation path and bench",
        (("infra/modal/sam3.py", r"^app = "),),
    ),
)


def _locate(path: str, pattern: str) -> str:
    text = (ROOT / path).read_text(encoding="utf-8").splitlines()
    rx = re.compile(pattern)
    for i, line in enumerate(text, 1):
        if rx.search(line):
            return f"[`{path}:{i}`]({path}#L{i})"
    raise LookupError(f"{pattern!r} not found in {path} — update tools/readme.py")


def meta_table() -> str:
    rows = ["| Meta model | How we run it | Role | Where |", "|---|---|---|---|"]
    for u in USES:
        rows.append(f"| **{u.model}** | {u.kind} | {u.role} | {' · '.join(_locate(f, p) for f, p in u.sites)} |")
    return "\n".join(rows)


def _fmt(v: Any) -> str:
    if v is None:
        return "—"
    if isinstance(v, float):
        return f"{v:.3f}".rstrip("0").rstrip(".") if abs(v) < 100 else f"{v:.0f}"
    return str(v)


def bench_tables() -> str:
    if not REPORT.exists():
        return "_Bench pending: run `make bench`._"
    rep = json.loads(REPORT.read_text())
    out = [
        f"Generated {rep.get('generated_at', '?')} at commit `{rep.get('git_sha', '?')}` · mode **{rep.get('mode', '?')}**."
    ]
    if rep.get("mode") == "mock":
        out.append(
            "\n> **These rows come from deterministic mock providers (no API keys yet).** They check that the pipeline, verifier "
            "and scorer work end to end; they do **not** measure any model. Live numbers replace them after `make live`."
        )
    names = {
        "synthetic": "Synthetic bench (exact ground truth)",
        "reference_objects": "Reference objects (vs published specs)",
        "real_ruler": "Real broken parts (vs school ruler, ±0.5 mm)",
    }
    cols = [
        "config",
        "n",
        "median_abs_err_mm",
        "mean_abs_err_mm",
        "mean_ci95",
        "pass@0.5",
        "verified_rate",
        "verified_but_off",
        "median_iters",
    ]
    for key, title in names.items():
        t = rep.get("tables", {}).get(key)
        out.append(f"\n**{title}**")
        if not t or t.get("status") != "ok":
            out.append(f"\n_Pending — {(t or {}).get('note') or 'no data yet'}._")
            continue
        photos = t.get("photos") or ("real photos" if key == "real_ruler" else "synthetic renders")
        out.append(
            f"\nN = {t.get('n')} · photos: {photos} · ground truth: `{t.get('ground_truth')}` · CI: {t.get('ci')}\n"
        )
        out.append("| " + " | ".join(cols) + " |")
        out.append("|" + "---|" * len(cols))
        for r in t.get("rows", []):
            out.append("| " + " | ".join(_fmt(r.get(c)) for c in cols) + " |")
        if t.get("note"):
            out.append(f"\n_{t['note']}_")
    mo = rep.get("measure_only")
    if isinstance(mo, dict) and mo.get("summary"):
        out.append("\n**Measurement only (photo → mm, no CAD loop)**\n")
        out.append("```\n" + str(mo["summary"]).strip() + "\n```")
    return "\n".join(out)


def _load(name: str) -> dict[str, Any] | None:
    f = REPORT.parent / name
    return json.loads(f.read_text()) if f.exists() else None


def evidence() -> str:
    """The trust checks: suites with expected outcomes, mesh-vs-program edits, lying-model attacks, the impact log."""
    out = ["| Check | Result | Source |", "|---|---|---|"]
    rep = _load("report.json") or {}
    mock = " (mock providers)" if rep.get("mode") == "mock" else ""
    for key, what in (
        ("control", "Intact parts, normal photos → accepted"),
        ("redteam", "Photos that must be rejected or refused"),
    ):
        h = (rep.get("tables", {}).get(key) or {}).get("headline")
        if h:
            out.append(
                f"| {what}{mock} | {h['correct']}/{h['n']} handled as expected, 95 % CI {h['ci95']} | "
                f"`eval/reports/latest/report.json` → `tables.{key}` |"
            )
    for key, what in (("synthetic", "synthetic parts"), ("reference_objects", "reference objects")):
        t = rep.get("tables", {}).get(key) or {}
        h = t.get("headline") or {}
        if t.get("status") == "ok" and h.get("verified_but_off"):
            out.append(
                f"| Verified {what}{mock} that are > 0.5 mm off the ground truth | {h['verified_but_off']} "
                f"(config {h['config']}) | `eval/reports/latest/report.json` → `tables.{key}` |"
            )
    pvm = (_load("program_vs_mesh.json") or {}).get("summary")
    if pvm:
        out.append(
            f"| Edit a hole: scale the mesh vs change the program's knob ({pvm['parts']} parts, {pvm['rows']} edits) | "
            f"hole spacing moved {pvm['mesh_hole_spacing_shift_median_mm']} mm (median) with mesh scaling, "
            f"{pvm['knob_hole_spacing_shift_median_mm']} mm with the knob | `eval/reports/latest/program_vs_mesh.md` |"
        )
    byp = _load("bypass.json")
    if byp:
        out.append(
            f"| A model that lies or cheats (says verified, edits the record, loosens limits, rescales to fit, fakes a break, smuggles imports, exports without consent) | "
            f"{byp['blocked']}/{byp['attempts']} attempts blocked by code | `eval/reports/latest/bypass.json` |"
        )
    imp = _load("impact.json") or {}
    if imp.get("status") == "ok":
        out.append(f"| Real repairs logged | {imp.get('n_sessions')} sessions | `eval/reports/latest/impact.json` |")
    else:
        out.append(
            f"| Real repairs logged | pending: {imp.get('note', 'no sessions yet')} | `data/impact/sessions.yaml` |"
        )
    return "\n".join(out)


BLOCKS = {"meta-tooling": meta_table, "bench": bench_tables, "evidence": evidence}


def render(text: str) -> str:
    for name, fn in BLOCKS.items():
        rx = re.compile(rf"(<!-- BEGIN:{name} -->).*?(<!-- END:{name} -->)", re.S)
        if not rx.search(text):
            raise LookupError(f"README.md has no {name} block")
        body = fn()
        m = rx.search(text)
        assert m is not None
        text = text[: m.start()] + m.group(1) + "\n" + body + "\n" + m.group(2) + text[m.end() :]
    return text


def main() -> None:
    README.write_text(render(README.read_text(encoding="utf-8")), encoding="utf-8")
    print(f"updated {README.relative_to(ROOT)}: {', '.join(BLOCKS)}")


if __name__ == "__main__":
    main()
