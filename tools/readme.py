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
        "Text-prompted masks of the part — the pixels the verifier measures in mm",
        (
            ("services/agent/providers/routing.py", r"SAM_31 = Route"),
            ("services/metrology/segment.py", r"class ProviderSegmenter"),
        ),
    ),
    Use(
        "Muse Spark 1.3",
        "Meta Model API",
        "Understand stage: names features, family, broken region, unknowns (strict PartSpec JSON)",
        (("services/agent/orchestrator.py", r'self\.call\("understand"'),),
    ),
    Use(
        "Muse Spark Open",
        "open weights (Baseten / Fireworks / Together)",
        "Planner, CadQuery builder and fixer in the verify loop",
        (
            ("services/agent/orchestrator.py", r'self\.call\("build"'),
            ("services/agent/orchestrator.py", r'self\.call\("fix"'),
        ),
    ),
    Use(
        "Muse Glimmer 30B",
        "open weights (llama.cpp on a Modal GPU)",
        "Independent veto-only judge and capture triage",
        (("services/agent/orchestrator.py", r'schema_name="judge"'), ("infra/modal/glimmer.py", r"^app = ")),
    ),
    Use(
        "Muse Voice Transcribe",
        "Meta Model API",
        "Hindi/English voice edits and spoken answers",
        (("services/media/voice.py", r"providers\.transcribe\("),),
    ),
    Use(
        "Muse Image",
        "Meta Model API",
        '"See the fix" in-place preview (labelled AI preview)',
        (("services/media/preview.py", r"providers\.generate_image\("),),
    ),
    Use(
        "Muse Wonder",
        "Meta Model API",
        "Steer factory planner: plans a family of parts for the registry",
        (("services/registry/steer.py", r'providers\.complete\("steer_plan"'),),
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


BLOCKS = {"meta-tooling": meta_table, "bench": bench_tables}


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
