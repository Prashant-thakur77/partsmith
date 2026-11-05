"""Regenerate the script-owned blocks of README.md. Nothing in these blocks is typed by hand:

- `links`: the link row (live site, video, judges page, sample), read from `docs/links.json`; empty URLs render "(coming)";
- `status` and `headline`: provider mode, report date and commit, and four headline numbers, read from
  `eval/reports/latest/*.json`;
- `meta-tooling`: the Meta model table, with file:line found in the code;
- `bench` and `evidence`: the result tables, read from `eval/reports/latest/`;
- `built`: the commits made since the hackathon start and the lines added per area, read from `git log`.

Run: `uv run python -m tools.readme` (also part of `make bench`). Blocks live between `<!-- BEGIN:<name> -->` and
`<!-- END:<name> -->` markers; everything else in README.md is left alone.
"""

from __future__ import annotations

import json
import re
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "README.md"
REPORT = ROOT / "eval" / "reports" / "latest" / "report.json"
LINKS = ROOT / "docs" / "links.json"

ET = ZoneInfo("America/New_York")
HACKATHON_START = datetime(2026, 10, 26, 12, 0, tzinfo=ET)
# Top-level areas for the "built during the hackathon" table, matched by path prefix in this order.
AREAS: tuple[tuple[str, str], ...] = (
    ("services/", "services/ (Python backend)"),
    ("apps/web/", "apps/web/ (web app)"),
    ("eval/", "eval/ (benches and reports)"),
    ("packages/", "packages/ (typed contracts)"),
    ("tools/", "tools/ (synthetic data, mats, generators)"),
    ("infra/", "infra/ (Modal, deploy)"),
    ("docs/", "docs/"),
    ("data/", "data/ (samples, replays)"),
)
OTHER_AREA = "root files"
# Lines count as hand-made code/docs only for these file types, outside data and generated outputs.
CODE_SUFFIXES = (".py", ".ts", ".tsx", ".js", ".mjs", ".cjs", ".css", ".md", ".sh", ".toml", ".yml", ".yaml", ".txt")
CODE_NAMES = ("Makefile", "Dockerfile")
NOT_CODE_PREFIXES = ("data/", "eval/reports/", "eval/runs/", "packages/schemas/json/")
GENERATED_FILES = ("apps/web/src/lib/schemas.ts", "pnpm-lock.yaml", "uv.lock")


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
        "Asked first for the part mask on every photo, with point-prompted cuts for holes and slots and video tracking of a "
        "walk-around clip. When it returns no confident mask, code's threshold segmenter measures instead, and each run logs "
        "which one was used: on rendered and pasted photos the fallback has measured most runs (see Mask sources under Results)",
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
        "and points at the features it hears about (frame and pixel), kept only if they land on the part. Turns a "
        "reviewer's notes into family rules the person ticks before they are kept, judges when Glimmer is not deployed, "
        "and turns a typed or spoken description with numbers into one template part whose numbers code then measures",
        (
            ("services/agent/orchestrator.py", r'self\.call\("understand"'),
            ("services/registry/describe.py", r'providers\.complete\("describe_plan"'),
            ("services/review/rules.py", r'providers\.complete\("review_rules"'),
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
        "Independent judge: vetoes plus an advisory 1–5 scorecard (outline, features, printability, fit), shown the "
        "photos, the model's silhouettes, a shaded 3D view and crops zoomed on the verifier's worst spots. It can "
        "block, never pass",
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


def _is_mock(row: dict[str, Any]) -> bool:
    return str(row.get("provider_modes", "")) == "mock"


def _cell(row: dict[str, Any], col: str) -> str:
    if col == "usd_per_job":  # a mock row costs nothing because nothing was called: show "—", never a fake $0
        v = row.get(col)
        return "—" if v is None or _is_mock(row) else f"${float(v):.4f}"
    return _fmt(row.get(col))


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
        "public_photos": "Public photos of real objects, pasted on a rendered mat (vs published spec; not phone photos, "
        "not counted as real photos measured)",
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
        "usd_per_job",
    ]
    for key, title in names.items():
        t = {**rep.get("tables", {}), **rep.get("separate_tables", {})}.get(key)
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
            out.append("| " + " | ".join(_cell(r, c) for c in cols) + " |")
        if any(_is_mock(r) for r in t.get("rows", [])):
            out.append("\n_usd_per_job is — on mock rows: mock providers make no paid calls._")
        if t.get("note"):
            out.append(f"\n_{t['note']}_")
    out += public_evidence()
    mo = rep.get("measure_only")
    if isinstance(mo, dict) and mo.get("summary"):
        out.append("\n**Measurement only (photo → mm, no CAD loop)**\n")
        out.append("```\n" + str(mo["summary"]).strip() + "\n```")
    return "\n".join(out)


def public_evidence() -> list[str]:
    """The two public-photo checks that run without a model, read from their own reports."""
    out: list[str] = []
    pm = _load("public_photos_measure.json")
    h = ((pm or {}).get("summary") or {}).get("held_out") or {}
    if pm and h.get("n_dims"):
        s = pm["summary"]
        out.append(
            f"\n**Public photos, measure only (no model).** Capture gate passed {s['capture_gate_passed']}/{s['n_photos']}. "
            f"Held-out dimensions: mean abs error {h['mean_abs_mm']} mm (95 % CI {h['ci95_mm'][0]} to {h['ci95_mm'][1]}), "
            f"n = {h['n_dims']}. The dimension that set the paste scale is excluded. "
            "`eval/reports/latest/public_photos_measure.md`"
        )
    ps = _load("public_scale.json")
    sc = (ps or {}).get("summary") or {}
    if ps and sc.get("status") == "ok":
        out.append(
            f"\n**Real-camera scale check (public photos of printed boards).** A flat-plane fit to the outer markers "
            f"predicts the inner corners to {sc['mean_err_pct']} % of span (95 % CI {sc['ci95_pct'][0]} to "
            f"{sc['ci95_pct'][1]}, n = {sc['n_corners']} corners in {sc['n_photos']} photos), "
            f"{sc['mean_err_mm_over_100mm']} mm over a 100 mm span. It says nothing about a phone photographing a laptop "
            "screen. `eval/reports/latest/public_scale.md`"
        )
    return out


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
    for key, what in (("control", "intact parts with only a top photo"), ("public_photos", "public photos")):
        ver = _verified_runs(rep, key)
        if ver:
            out.append(
                f"| Verified {what}{mock} that are > 0.5 mm off the ground truth | {len(_off(ver))}/{len(ver)} (config PS) | "
                f"`eval/reports/latest/report.json` → `runs.{key}.PS` |"
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


# --- first screen: link row, status line, headline numbers ---------------------------------------------------------

LINK_SLOTS: tuple[tuple[str, str], ...] = (
    ("live_site", "Live site"),
    ("video", "Video"),
    ("judges", "Judges page"),
    ("sample", "Try a sample"),
)
DERIVED_PATHS = {"judges": "/judges", "sample": "/jobs/demo"}  # filled from live_site when left empty


def _read_links() -> dict[str, Any]:
    if not LINKS.exists():
        return {}
    data = json.loads(LINKS.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def links_row() -> str:
    """Live site · Video · Judges page · Try a sample, from `docs/links.json`; a slot with no URL says "(coming)"."""
    data = _read_links()
    live = str(data.get("live_site") or "").strip().rstrip("/")
    parts: list[str] = []
    for key, label in LINK_SLOTS:
        url = str(data.get(key) or "").strip()
        if not url and live and key in DERIVED_PATHS:
            url = live + DERIVED_PATHS[key]
        if url and not url.startswith(("https://", "http://")):
            raise ValueError(f"docs/links.json: {key} must be an http(s) URL, got {url!r}")
        parts.append(f"**[{label}]({url})**" if url else f"{label} _(coming)_")
    parts += ["[Results](#results)", "[Reproduce](eval/REPRODUCE.md)", "[Docs](docs/README.md)"]
    return " · ".join(parts)


def _photo_counts(rep: dict[str, Any]) -> tuple[int, int]:
    """(real photos measured, real parts with ruler ground truth) as the latest reports count them."""
    secs = (rep.get("measure_only") or {}).get("sections") or {}
    photos = sum(int((secs.get(k) or {}).get("n_photos") or 0) for k in ("reference_objects_real", "real_parts_ruler"))
    rr = (rep.get("tables") or {}).get("real_ruler") or {}
    parts = int(rr.get("n") or 0) if rr.get("status") == "ok" else 0
    return photos, parts


def _replay_modes() -> tuple[int, int]:
    """(live, total) over the committed demo replays, from each replay's own summary."""
    root = ROOT / "data" / "replays"
    modes = []
    for f in sorted(root.glob("j_*/summary.json")):
        try:
            modes.append(str(json.loads(f.read_text()).get("provider_mode", "")))
        except (OSError, ValueError):
            continue
    return sum(m == "live" for m in modes), len(modes)


def status_line() -> str:
    """Provider mode, report date and commit, real-data counts and a plain honesty sentence, all from the reports."""
    rep = _load("report.json")
    if not rep:
        return "> **Status:** no bench report yet; run `make bench`. No number on this page is final."
    mode = str(rep.get("mode", "?"))
    date = str(rep.get("generated_at", "?"))[:10]
    sha = str(rep.get("git_sha", "?"))[:7]
    dirty = " plus uncommitted changes" if (_load("provenance.json") or {}).get("git_dirty") else ""
    photos, parts = _photo_counts(rep)
    repairs = int((_load("impact.json") or {}).get("n_sessions") or 0)
    head = (
        f"> **Status: {mode} providers** · bench report {date} at commit `{sha}`{dirty} · real photos measured: {photos} · "
        f"real parts with ruler ground truth: {parts} · real repairs logged: {repairs}"
    )
    on = "synthetic photos" if photos == 0 else f"synthetic photos and {photos} real photos"
    live, total = _replay_modes()
    replays = f"{live} of the {total} stored demo replays are live model runs" if total else "no stored replays yet"
    if mode == "mock":
        pending = (
            "a live bench run is pending" if live else "live runs are pending (no live model call has been made yet)"
        )
        body = (
            f"The bench numbers below come from deterministic mock models on {on}; {pending}. They show that the "
            f"pipeline, verifier and scorer work end to end; they do not measure any model. {replays.capitalize()} "
            "(each replay is labelled live or mock)."
        )
    else:
        rows = [r for t in (rep.get("tables") or {}).values() if isinstance(t, dict) for r in t.get("rows") or []]
        mixed = any("mock" in str(r.get("provider_modes", "")) for r in rows)
        body = f"Numbers below come from {mode} model calls on {on}." + (
            " Some stages ran as labelled mocks: see `provider_modes` in `eval/reports/latest/report.json`."
            if mixed
            else ""
        )
    if photos == 0 or parts == 0:
        body += " Real-photo results are pending and say so in their tables."
    if _suite_row(rep, "public_photos"):
        body += " Public photos pasted on a rendered mat have their own table and are not counted as real photos."
    return f"{head}\n>\n> {body}"


def evaluation_line() -> str:
    """The large evaluation in one paragraph above the fold; the table under it is the smaller frozen bench."""
    s = _load("scale.json")
    if not s:
        return ""
    pair = s["paired_b1_vs_ps"]
    calls = sum(m["calls"] for k, m in s["models"].items() if "(live)" in k)
    ps = next(r for r in s["tables"]["synthetic"]["rows"] if r["config"] == "PS")
    return (
        f"**Largest test so far:** {s['stop']['done']} full runs and {calls:,} live model calls on freshly rendered photos, with the rules fixed "
        f"first and nothing rerun. On the same photos, the fix loop got every size within 0.5 mm in {pair['ps_pass']} of {pair['n_pairs']} pairs "
        f"against {pair['b1_pass']} for a single shot (p = {pair['p_value']:.3f}). Median error per size {_fmt(ps['median_abs_err_mm'])} mm, n = {ps['n']} runs. "
        "Real phone photos are not tested yet. [Full tables](#evaluation-at-scale). The table below is the smaller frozen bench."
    )


def headline() -> str:
    """Four numbers above the fold, each with the file it is read from and the provider mode behind it."""
    rep = _load("report.json") or {}
    tables = rep.get("tables") or {}
    tag = "; mock providers" if rep.get("mode") == "mock" else ""
    src = "`eval/reports/latest/report.json`"
    rows = ["| Number | What it counts | Source |", "|---|---|---|"]
    byp = _load("bypass.json")
    if byp:
        rows.append(
            f"| **{byp['blocked']}/{byp['attempts']}** | lying-model attacks blocked by code; suite: {byp.get('suite', '?')} "
            "| `eval/reports/latest/bypass.json` |"
        )
    else:
        rows.append("| pending | lying-model attacks blocked by code | run `uv run python -m eval.bypass` |")
    vbo = [
        f"**{(tables[k].get('headline') or {}).get('verified_but_off')}** {label}"
        for k, label in (("synthetic", "synthetic"), ("reference_objects", "reference objects"))
        if (tables.get(k) or {}).get("status") == "ok" and (tables[k].get("headline") or {}).get("verified_but_off")
    ]
    for key, label in (("control", "intact parts, top photo only"), ("public_photos", "public photos")):
        ver = _verified_runs(rep, key)
        if ver:
            vbo.append(f"**{len(_off(ver))}/{len(ver)}** {label}")
    rows.append(
        f"| {' · '.join(vbo) or 'pending'} | verified parts that are > 0.5 mm off the ground truth on some dimension (off / verified){tag}; "
        f"[every one is listed](#every-verified-part-against-ground-truth) | {src} → `tables.*.headline.verified_but_off`, `runs.*.PS` |"
    )
    suites = [
        f"**{h['correct']}/{h['n']}** {label}"
        for k, label in (("control", "control"), ("redteam", "red-team"))
        if (h := (tables.get(k) or {}).get("headline")) and "correct" in h
    ]
    rows.append(
        f"| {' · '.join(suites) or 'pending'} | intact photos accepted · bad or unsuitable photos rejected or "
        f"refused{tag} | {src} → `tables.control`, `tables.redteam` |"
    )
    syn = tables.get("synthetic") or {}
    h = syn.get("headline") or {}
    if syn.get("status") == "ok" and h.get("median_abs_err_mm") is not None:
        rows.append(
            f"| **{_fmt(h['median_abs_err_mm'])} mm** | median absolute error per dimension, synthetic photos, config "
            f"{h.get('config')}, n = {h.get('n')}{tag} | {src} → `tables.synthetic.headline` |"
        )
    else:
        rows.append(f"| pending | median absolute error, synthetic photos | {src} |")
    return "\n".join(rows)


# --- first screen extras: badges, film slot ----------------------------------------------------------------------------


def _shield(label: str, value: str, colour: str, link: str = "") -> str:
    def enc(s: str) -> str:
        return s.replace("-", "--").replace("_", "__").replace(" ", "%20").replace("/", "%2F")

    img = f"![{label}: {value}](https://img.shields.io/badge/{enc(label)}-{enc(value)}-{colour})"
    return f"[{img}]({link})" if link else img


def badges() -> str:
    """Only true things: the CI workflow, the stack, passing test suites and the open-weights share, from their reports."""
    links = _read_links()
    repo = str(links.get("repo") or "").rstrip("/")
    out = []
    if repo:
        out.append(f"[![CI]({repo}/actions/workflows/ci.yml/badge.svg)]({repo}/actions/workflows/ci.yml)")
    out += [_shield("Python", "3.12", "3776ab"), _shield("Next.js", "15", "1c2230")]
    gates = (_load("tests.json") or {}).get("gates") or {}
    for key, label in (("backend", "backend tests"), ("web_unit", "web unit tests")):
        g = gates.get(key) or {}
        if g.get("status") == "passed" and g.get("passed"):
            out.append(_shield(label, f"{g['passed']} passing", "2e7d4f", "docs/PROOF.md"))
    builder = (_load("open_weights.json") or {}).get("builder") or {}
    if builder.get("calls"):
        share = round(float(builder.get("share_tokens_open_weights") or 0) * 100)
        out.append(
            _shield(
                "builder tokens on open weights", f"{share} percent", "c2410c", "eval/reports/latest/open_weights.json"
            )
        )
    byp = _load("bypass.json") or {}
    if byp.get("attempts"):
        out.append(
            _shield(
                "lying-model attacks blocked",
                f"{byp['blocked']} of {byp['attempts']}",
                "2e7d4f",
                "eval/reports/latest/bypass.json",
            )
        )
    return " ".join(out)


def film() -> str:
    url = str(_read_links().get("video") or "").strip()
    if not url:
        return "_The demo film's link goes here when it is uploaded._"
    thumb = ROOT / "docs" / "media" / "film-thumbnail.png"
    return (
        f"[![Watch the demo film](docs/media/film-thumbnail.png)]({url})"
        if thumb.exists()
        else f"**[Watch the demo film]({url})**"
    )


# --- time, verified audit, thresholds, failures, gates, rubric ----------------------------------------------------------

BATTERY_RUN = "j_261029_daf26965"


def _battery() -> dict[str, Any]:
    """The stored battery-cover run's own timing, errors, cost and print estimate."""
    d = ROOT / "data" / "replays" / BATTERY_RUN
    s = json.loads((d / "summary.json").read_text())
    ev = [json.loads(x) for x in (d / "run.jsonl").read_text().splitlines()]
    first = next(e["ts"] for e in ev if e.get("t") == "artifact" and e.get("kind") == "threemf")
    pla = json.loads((d / "buy_or_print.json").read_text())["prints"][0]
    return {
        "minutes": round((first - s["created_at"]) / 60, 2),
        "errors": [round(e["hausdorff_mm"], 2) for e in ev if e.get("t") == "iteration"],
        "usd": s["cost_usd"],
        "print_minutes": pla["print_minutes"],
        "grams": pla["grams"],
        "inr": pla["filament_cost"]["INR"],
    }


def _suite_row(rep: dict[str, Any], key: str, config: str = "PS") -> dict[str, Any]:
    t = {**(rep.get("tables") or {}), **(rep.get("separate_tables") or {})}.get(key) or {}
    return next((r for r in t.get("rows") or [] if r.get("config") == config), {})


def time_table() -> str:
    """Measured times only; there is no manual baseline in this table because none was measured or found published."""
    rep = _load("report.json") or {}
    b = _battery()
    src = "`eval/reports/latest/report.json`"
    rows = ["| What | Measured | Model cost | Source |", "|---|---|---|---|"]
    rows.append(
        f"| One stored live run, photo to checked file (battery cover) | {b['minutes']} min, no answers needed from a person "
        f"| ${b['usd']:.2f} | `data/replays/{BATTERY_RUN}/` (`run.jsonl`, `summary.json`) |"
    )
    for key, what in (
        ("synthetic", "Median job, hard rendered photos"),
        ("reference_objects", "Median job, reference-object renders"),
        ("public_photos", "Median job, public photos of real objects pasted on a rendered mat"),
    ):
        r = _suite_row(rep, key)
        if r:
            rows.append(
                f"| {what} (n = {r['n']}) | {float(r['median_wall_s']) / 60:.1f} min | ${float(r['usd_per_job']):.2f} per job | {src} → `median_wall_s`, `usd_per_job` |"
            )
    rb = _load("rebake.json") or {}
    if rb.get("median_ms"):
        rows.append(
            f"| The next person changing a knob on that stored program (n = {rb['n']}) | {rb['median_ms']:g} ms median "
            "| no model call | `eval/reports/latest/rebake.json` (`uv run python -m eval.rebake`) |"
        )
    rows.append(
        f"| Printing it, by estimate | about {b['print_minutes']:g} min, {b['grams']:g} g of PLA, ₹{b['inr']:g} of filament "
        f"| not a quote | `data/replays/{BATTERY_RUN}/buy_or_print.json` |"
    )
    return "\n".join(rows)


SUITE_NAMES = {
    "synthetic": "Rendered parts",
    "reference_objects": "Reference objects (renders)",
    "control": "Intact parts, top photo only",
    "public_photos": "Public photos, pasted on a rendered mat",
    "redteam": "Bad or unsuitable photos",
}


def _verified_runs(rep: dict[str, Any], key: str) -> list[dict[str, Any]]:
    return [r for r in ((rep.get("runs") or {}).get(key) or {}).get("PS") or [] if r.get("verified")]


def _off(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [r for r in rows if (r.get("max_abs_err_mm") or 0) > 0.5]


def audit() -> str:
    """Every verified full-loop part, checked against ground truth on every dimension, including the misses."""
    rep = _load("report.json") or {}
    rows = [
        "| Suite | Full-loop runs | Verified | Within 0.5 mm on every size | Off by more than 0.5 mm |",
        "|---|---|---|---|---|",
    ]
    before = [r for k in ("synthetic", "reference_objects", "control", "redteam") for r in _verified_runs(rep, k)]
    for key, name in SUITE_NAMES.items():
        runs = ((rep.get("runs") or {}).get(key) or {}).get("PS") or []
        ver = _verified_runs(rep, key)
        rows.append(f"| {name} | {len(runs)} | {len(ver)} | {len(ver) - len(_off(ver))} | {len(_off(ver))} |")
    pub = _verified_runs(rep, "public_photos")
    height = sum("thickness" in str(r.get("failure")) for r in _off(before))
    lines = [
        "\n".join(rows),
        f"\nBefore the public photos, the full loop verified **{len(before)}** parts, and **{len(_off(before))}** of them were "
        f"more than 0.5 mm off on some dimension. **{height}** of those were in height, on intact parts with only a top photo, "
        f'which cannot see height. The public-photo suite adds **{len(_off(pub))} of {len(pub)}**. So "verified" means the model '
        "matches the photos it was given within the limits below. It is not a promise on sizes those photos cannot see, "
        "and a size no check compared with a photo is listed as inferred.",
        "\n<details><summary>Every verified run</summary>\n",
        "| Suite | Sample | Worst error on any size | Note |",
        "|---|---|---|---|",
    ]
    for key, name in SUITE_NAMES.items():
        for r in _verified_runs(rep, key):
            lines.append(
                f"| {name} | `{r['sample_id']}` | {_fmt(r.get('max_abs_err_mm'))} mm | {r.get('failure') or 'within limit'} |"
            )
    lines.append("\n</details>")
    return "\n".join(lines)


THRESHOLD_MEANINGS = {
    "HAUSDORFF_PASS_MM": "Largest allowed outline gap between model and photo, on every compared view",
    "IOU_PASS": "Smallest allowed overlap (IoU) on views whose short side is at least 20 mm",
    "FEATURE_TOL_MM": "Allowed error on a measured feature such as a hole diameter",
    "BBOX_TOL_MM": "Allowed error on the overall outline length and width",
    "MIN_WALL_MM": "Thinnest wall a printable part may have",
    "BLUR_WARN": "Marker-edge sharpness below this warns",
    "BLUR_FAIL": "Marker-edge sharpness below this rejects the photo",
    "CLIP_HIGH": "Grey level at or above which a pixel counts as blown out",
    "CLIP_LOW": "Grey level at or below which a pixel counts as crushed",
    "CLIP_FLAT_STD": "Local grey-level spread under which a clipped area counts as carrying no texture",
    "CLIP_WARN": "Share of clipped pixels on the stage that warns",
    "CLIP_FAIL": "Share of clipped pixels on the stage that rejects the photo",
    "CONE_CHROMA_TOL": "Colour distance under which a part counts as shadow-coloured",
    "CONE_MIN_RATIO": "Brightness ratio under which a shadow-coloured part cannot be told from its shadow",
    "CONTRAST_FAIL_WEAK": "Share of weak part edges that rejects the photo",
    "CONTRAST_WARN_WEAK": "Share of weak part edges that warns",
    "CONTRAST_MIN_LARGEST_FRACTION": "Share of the part the largest piece must hold, or the mask is fragmented",
    "CONTRAST_MIN_SEPARATION": "Grey-level gap needed between part and stage",
    "CONTRAST_MIN_SOLIDITY": "Smallest solidity for a mask to count as one part",
    "EDGE_MIN_CONTRAST": "Grey-level step for an edge to count as strong",
    "GLARE_FAIL_MARKERS": "Number of glared markers that rejects the photo",
    "GLARE_MARKER_DARK_FRACTION": "Share of a marker's black cells blown out for it to count as glared",
    "GLARE_MIN_BLOB_MM2": "Smallest bright blob that counts as glare on the stage (mm²)",
    "GRID_CELLS": "Cells per side of an ArUco marker",
    "MIN_MARKERS_WARN": "Fewer detected markers than this warns",
    "MIN_PART_AREA_MM2": "Smallest part area accepted (mm²)",
    "MOIRE_FAIL": "Periodic screen pattern strength that rejects the photo (rms grey levels)",
    "MOIRE_WARN": "Periodic screen pattern strength that warns (rms grey levels)",
    "MOIRE_PEAK_RATIO": "Spectral peak over its ring's median for a pattern to count as periodic",
    "PATCH_PX_PER_CELL": "Pixels per marker cell when a marker is rectified for checking",
    "REPROJ_FAIL_PX": "Marker reprojection error that rejects the photo",
    "REPROJ_WARN_PX": "Marker reprojection error that warns",
    "SCALE_FAIL": "Disagreement in marker size across the mat that rejects the photo",
    "SCALE_WARN": "Disagreement in marker size across the mat that warns",
    "SINGLE_PART_MIN_MM2": "Size above which a second object on the stage counts",
    "SINGLE_PART_REL": "Size relative to the largest object above which a second object counts",
    "STAGE_EDGE_MARGIN_MM": "Distance the part must keep from the stage edge",
    "TILT_FAIL_DEG": "Camera tilt that rejects the photo",
    "TILT_WARN_DEG": "Camera tilt that warns",
}


def thresholds() -> str:
    """Every limit the code applies, read from `provenance.json`, with what it means."""
    t = (_load("provenance.json") or {}).get("thresholds") or {}
    gate = t.get("capture_gate") or {}
    rows = ["| Limit | Value | Meaning |", "|---|---|---|"]
    rows += [
        f"| `{k}` | {v} | {THRESHOLD_MEANINGS.get(k, 'see the code')} |"
        for k, v in t.items()
        if not isinstance(v, dict)
    ]
    out = [
        "**Pass rule (`services/verifier`)**\n",
        "\n".join(rows),
        "\n**Capture gate (`services/metrology/capture_gate.py`), checked before any paid call**\n",
    ]
    rows = ["| Limit | Value | Meaning |", "|---|---|---|"]
    rows += [f"| `{k}` | {v} | {THRESHOLD_MEANINGS.get(k, 'see the code')} |" for k, v in gate.items()]
    out.append("\n".join(rows))
    return "\n".join(out)


def failures() -> str:
    """Why the runs that did not pass ended where they did, by suite and config."""
    rep = _load("report.json") or {}
    cats = rep.get("taxonomy_categories") or {}
    tax = rep.get("failure_taxonomy") or {}
    if not tax:
        return "_No failure taxonomy yet._"
    names = list(cats)
    rows = [
        "| Suite | Config | Runs | " + " | ".join(f"`{c}`" for c in names) + " |",
        "|---|---|---|" + "---|" * len(names),
    ]
    for suite, configs in tax.items():
        for cfg, counts in configs.items():
            rows.append(
                f"| {SUITE_NAMES.get(suite, suite)} | {cfg} | {counts.get('runs', 0)} | "
                + " | ".join(str(counts.get(c, 0)) for c in names)
                + " |"
            )
    legend = " · ".join(f"`{k}`: {v}" for k, v in cats.items())
    return "\n".join(rows) + f"\n\n{legend}."


def gates() -> str:
    """The last `make proof` run. A gate that failed or did not run says so."""
    t = _load("tests.json")
    if not t:
        return "_No gate report yet: run `make proof`._"
    rows = ["| Gate | Command | Result | Took |", "|---|---|---|---|"]
    for g in (t.get("gates") or {}).values():
        count = f"{g['passed']} passed" if g.get("passed") else ""
        if g.get("failed"):
            count += f", {g['failed']} failed"
        if g.get("skipped"):
            count += f", {g['skipped']} skipped"
        status = str(g.get("status", "?"))
        rows.append(
            f"| {g.get('title', '?')} | `{g.get('command', 'see docs/PROOF.md')}` | **{status}** {('(' + count + ')') if count else ''} | {g.get('seconds', '?')} s |"
        )
    return (
        f"Last run {str(t.get('generated_at', '?'))[:16]} UTC. Details: [docs/PROOF.md](docs/PROOF.md).\n\n"
        + "\n".join(rows)
    )


def rubric() -> str:
    """The judging criteria and bonus prizes, each with where to check it. Numbers are read from the reports."""
    rep = _load("report.json") or {}
    byp = _load("bypass.json") or {}
    pvm = (_load("program_vs_mesh.json") or {}).get("summary") or {}
    b = _battery()
    w = (_load("open_weights.json") or {}).get("builder") or {}
    pub = _suite_row(rep, "public_photos")
    tests = ((_load("tests.json") or {}).get("gates") or {}).get("backend") or {}
    share = round(float(w.get("share_tokens_open_weights") or 0) * 100)
    rows = [
        "| Criterion | What we claim | Check it here |",
        "|---|---|---|",
        f"| **Impact**: who benefits, could people use it | A broken plastic part stops meaning a thrown-out appliance: no caliper, no CAD, no printer of your own. One stored run takes {b['minutes']} min and about ₹{b['inr']:g} of filament by estimate. Not yet shown: real phone photos and real prints | [The problem](#the-problem-and-who-it-serves), [Time](#how-long-it-takes-and-why-it-works), [Limitations](#limitations), `/requests`, `/shop` |",
        f"| **Use of Meta AI tooling**: beyond a basic integration | SAM 3.1 asked first for the part mask, with a logged code fallback, and video tracking for heights; Muse Spark names features and points at pixels, and SAM 3.1 cuts them; Muse Spark Open writes programs and operates our tools ({w.get('calls_on_open_weights', '?')} of {w.get('calls', '?')} builder calls on open weights); Muse Wonder's citations are checked by code; Muse Image completions must leave the markers and intact part unchanged; Voice Transcribe hears Hindi and English mixed, with knob names as keywords | [Meta models](#what-was-not-possible-before-and-how-metas-models-made-it-possible), `eval/reports/latest/open_weights.json`, `/models` |",
        f"| **Technical depth and execution** | A deterministic verifier is the only writer of `verified`; sandboxed CAD; one export gate; {tests.get('passed', '?')} backend tests; {byp.get('blocked', '?')}/{byp.get('attempts', '?')} lying-model attacks blocked; mesh vs knob measured over {pvm.get('parts', '?')} parts | [Verify it yourself](#verify-it-yourself), [Results](#results), [docs/DECISIONS.md](docs/DECISIONS.md) |",
        "| **Demo**: works, holds up live, good to watch | `/judges` replays a stored live run and shows a lying model being caught, with no login and no keys. The demo film walks the same flow | [Try it](#try-it-in-2-minutes), the link row at the top |",
        f"| **Bonus: open weights** | Muse Spark Open on partner inference writes and fixes every program: {share} % of builder tokens. Muse Glimmer is wired for an own-GPU path but ran as a labelled mock in the stored bench, so it is not claimed | `eval/reports/latest/open_weights.json`, `infra/modal/` |",
        "| **Bonus: agentic** | The fix agent reads residuals, measures, renders candidates, runs tests and sets knobs within bounded rounds, and code judges the result | job page Agent tab, `services/agent/agent_loop.py` |",
        "| **Bonus: creative** | Muse Image completes the broken region under a code gate, previews the repair and draws the install card, always labelled as AI images | `services/metrology/recon_gate.py`, `services/media/preview.py` |",
        "| **Bonus: viral, community vote** | Decided by the post and the gallery, not by this repo | the submission page |",
    ]
    if pub:
        rows.insert(
            4,
            f"| **Technical depth: real objects** | {pub['n']} public photos of real objects, pasted on a rendered mat: median error {_fmt(pub['median_abs_err_mm'])} mm against published sizes. Not phone captures | `eval/reports/latest/report.json` → `separate_tables.public_photos`, `eval/REPRODUCE.md` |",
        )
    return "\n".join(rows)


# --- built during the hackathon (git log) -------------------------------------------------------------------------


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", "-c", "core.quotepath=off", *args], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout


@dataclass
class Commit:
    short: str
    when: datetime
    subject: str
    lines_added: dict[str, list[int]]  # area -> [code/docs lines, data/report/generated lines]
    files_added: dict[str, int]  # area -> new files


def _area(path: str) -> str:
    return next((label for prefix, label in AREAS if path.startswith(prefix)), OTHER_AREA)


def _is_code(path: str) -> bool:
    """Hand-made code or docs (by file type), as opposed to data, bench outputs, lockfiles and generated types."""
    if path.startswith(NOT_CODE_PREFIXES) or path in GENERATED_FILES:
        return False
    name = path.rsplit("/", 1)[-1]
    return name.endswith(CODE_SUFFIXES) or name.startswith(CODE_NAMES)


def _commits() -> list[Commit]:
    """Every commit, oldest first, with lines added (numstat) and files created (summary) per area."""
    out: list[Commit] = []
    raw = _git("log", "--reverse", "--no-renames", "--numstat", "--summary", "--format=@@%x1f%h%x1f%aI%x1f%s")
    for line in raw.splitlines():
        if line.startswith("@@\x1f"):
            _, short, when, subject = line.split("\x1f", 3)
            out.append(Commit(short, datetime.fromisoformat(when), subject, {}, {}))
        elif not out or not line.strip():
            continue
        elif line.startswith(" create mode "):
            area = _area(line.split(" ", 4)[-1])
            out[-1].files_added[area] = out[-1].files_added.get(area, 0) + 1
        elif "\t" in line:
            added, _, path = line.split("\t", 2)
            if added.isdigit():  # binary files show "-"
                counts = out[-1].lines_added.setdefault(_area(path), [0, 0])
                counts[0 if _is_code(path) else 1] += int(added)
    return out


def _et(t: datetime) -> str:
    return t.astimezone(ET).strftime("%Y-%m-%d %H:%M ET")


def built() -> str:
    """Commits since the hackathon start, and files and lines added per top-level area, computed from git."""
    try:
        commits = _commits()
    except (OSError, subprocess.CalledProcessError):
        return "_git history unavailable: run `uv run python -m tools.readme` inside the repository._"
    inside = [c for c in commits if c.when >= HACKATHON_START]
    before = [c for c in commits if c.when < HACKATHON_START]
    if not inside:
        return "_No commits since the hackathon start yet._"
    out = [
        f"**{len(inside)} commits** between {_et(inside[0].when)} and {_et(inside[-1].when)}; the hackathon started "
        f"{_et(HACKATHON_START)}. Commits dated before the start: **{len(before)}**."
    ]
    if before:
        out.append("\nBefore the start (not hackathon work): " + ", ".join(f"`{c.short}`" for c in before) + ".")
    out += [
        "",
        "| Area | Files added | Lines added: code and docs | Lines added: data, reports, lockfiles, generated "
        "| First commit | Last commit |",
        "|---|---|---|---|---|---|",
    ]
    labels = [label for _, label in AREAS] + [OTHER_AREA]
    tot = [0, 0, 0]
    for label in labels:
        touched = [c for c in inside if label in c.lines_added or label in c.files_added]
        if not touched:
            continue
        files = sum(c.files_added.get(label, 0) for c in inside)
        code = sum(c.lines_added.get(label, [0, 0])[0] for c in inside)
        data = sum(c.lines_added.get(label, [0, 0])[1] for c in inside)
        tot = [tot[0] + files, tot[1] + code, tot[2] + data]
        name, _, what = label.partition(" (")
        shown = f"`{name}` ({what}" if what else (f"`{name}`" if name.endswith("/") else name)
        out.append(
            f"| {shown} | {files:,} | {code:,} | {data:,} | {_et(touched[0].when)[:10]} | {_et(touched[-1].when)[:10]} |"
        )
    out.append(f"| **Total** | **{tot[0]:,}** | **{tot[1]:,}** | **{tot[2]:,}** | | |")
    out += ["", "<details><summary>Every commit since the start, oldest first</summary>", ""]
    out += ["| Date | Commit | Subject |", "|---|---|---|"]
    out += [f"| {_et(c.when)} | `{c.short}` | {c.subject.replace('|', '/')} |" for c in inside]
    out += ["", "</details>"]
    out.append(
        "\n_Generated from `git log --numstat --summary` by `tools/readme.py` (author dates, Eastern Time). Lines added "
        "are summed over commits, so a file rewritten twice counts twice. A commit made after the last regeneration "
        "appears at the next `make bench`._"
    )
    return "\n".join(out)


def _rate(x: dict[str, Any]) -> str:
    return f"{x['k']}/{x['n']} ({x['rate'] * 100:.0f} %, 95 % CI {x['ci95'][0] * 100:.0f}-{x['ci95'][1] * 100:.0f})"


def scale() -> str:
    """The large live evaluation: plan fixed first, fresh seeds, every number from eval/reports/latest/scale.json."""
    s = _load("scale.json")
    if not s:
        return "Not run yet."
    done, planned = s["stop"]["done"], sum(s["planned"].values())
    calls = sum(m["calls"] for k, m in s["models"].items() if "(live)" in k)
    tokens = sum(m["tokens"] for k, m in s["models"].items() if "(live)" in k)
    pair = s["paired_b1_vs_ps"]
    off = s["verified_but_off"]
    rows = [
        f"**{done} of {planned} planned full runs** finished before the time limit, on photos rendered from fresh seeds, with the sizes and "
        f"rules fixed first in [`eval/SCALE_PLAN.md`](eval/SCALE_PLAN.md). Runs were shuffled, so each suite is an unbiased subset. "
        f"That took {calls:,} live model calls, {tokens / 1e6:.0f} million tokens and ${s['usd']['total']:.2f}. "
        "**None of these photos is a real phone capture.** Nothing was rerun. Source: `eval/reports/latest/scale.json`.\n",
        "| Suite | Config | n | Median error | Within 0.5 mm on every size | Verified | Verified but off |",
        "|---|---|---|---|---|---|---|",
    ]
    names = {
        "synthetic": "Rendered parts (exact ground truth)",
        "broken": "Broken parts (exact ground truth)",
        "reference_objects": "Reference objects, rendered (published sizes)",
    }
    for key, name in names.items():
        for r in s["tables"][key]["rows"]:
            rows.append(
                f"| {name} | {r['config']} | {r['n']} | {_fmt(r['median_abs_err_mm'])} mm | {r['pass@0.5'] * 100:.0f} % {r['pass@0.5_ci95']} "
                f"| {r['verified_rate'] * 100:.0f} % {r['verified_ci95']} | {r['verified_but_off']} |"
            )
    ctl_t, ctl_s, red = (s["tables"][k]["headline"] for k in ("control_top", "control_side", "redteam"))
    wrong = (
        ", ".join(sorted({str(x.get("case", x)) for x in s["tables"]["redteam"].get("failures", [])}))
        or "see the report"
    )
    rows += [
        "",
        f"**The loop against a single shot, same photos:** {pair['ps_pass']} vs {pair['b1_pass']} of {pair['n_pairs']} pairs had every size within 0.5 mm "
        f"(McNemar exact p = {pair['p_value']:.4f}).",
        "",
        f"**What a side photo does for wrong passes:** verified but more than 0.5 mm off was {_rate(off['top_only'])} with a top photo only, and "
        f"{_rate(off['top_and_side'])} with top and side. Across all full-loop runs it was {_rate(off['all_ps'])}, {off['all_ps']['off_in_height']} of them in height. "
        "A verified part from a top photo alone says nothing about its height.",
        "",
        f"**Expected outcomes:** intact parts handled correctly {ctl_t['correct']}/{ctl_t['n']} (top only) and {ctl_s['correct']}/{ctl_s['n']} (top and side); "
        f"bad or unsuitable photos {red['correct']}/{red['n']} ({wrong}).",
        "",
        f"**Voice edits, synthesised speech, correct edit:** {_rate(s['voice']['spoken'])} spoken and {_rate(s['voice']['typed'])} typed. By language, spoken: "
        + ", ".join(f"{k} {v['spoken']['k']}/{v['spoken']['n']}" for k, v in s["voice"]["by_language"].items())
        + ". Pure Hindi is the weak spot.",
        "",
        f"**Muse Wonder:** code accepted a cited value on {_rate(s['wonder']['accepted_with_citation'])}. A citation is not a verified fact: of the pages checked, "
        f"the number was found on {s['wonder']['page_check']['number_found_on_page']}, and {s['wonder']['page_check']['page_unreadable']} pages could not be read.",
        "",
        "#### Mask sources",
        "",
        f'SAM 3.1 is asked first, and code\'s threshold segmenter takes over when it returns nothing confident. With the prompt "plastic part", SAM returned a usable mask on '
        f"{_rate(s['sam']['mask_returned'])} of rendered top photos. When it did, the median overlap with ground truth was {s['sam']['when_returned']['iou_median']:.2f} and the median boundary "
        f"error {s['sam']['when_returned']['boundary_mean_mm_median']:.2f} mm.",
        "",
        "| Suite | Threshold measured | SAM 3.1 measured | No measurement (rejected) |",
        "|---|---:|---:|---:|",
    ]
    for key, v in s["mask_sources"].items():
        rows.append(f"| {key} | {v.get('threshold', 0)} | {v.get('sam-3.1', 0)} | {v.get('no measure line', 0)} |")
    fix = _load("sam_prompts.json")
    if fix:
        old, new = fix["mask_rate"]["old"], fix["mask_rate"]["new"]
        lw = fix["measures_paired"]["new_length_width"]
        holes = fix["measures_paired"]["new_hole_diameter"]
        pub = fix["mask_rate_by_suite"]["public"]["new"]
        rows += [
            "",
            "**The fix, after that evaluation.** The phrase was the problem: code now reads the part's colour and asks for, say, "
            f'"orange plastic part" first. On {fix["photos"]} photos (`eval/reports/latest/sam_prompts.json`) SAM returned a usable mask on '
            f"{old['k']} before and {new['k']} after. Its median overlap with the exact mask is {fix['iou_new_vs_exact']['median']:.3f}, against "
            f"{fix['iou_threshold_vs_exact']['median']:.3f} for the threshold. It still measures a little worse: median length and width error "
            f"{lw['sam']['median']:.3f} mm against {lw['threshold']['median']:.3f} mm, and hole diameter {holes['sam']['median']:.3f} mm against "
            f"{holes['threshold']['median']:.3f} mm. Public photos of real objects barely moved, {pub['k']} of {pub['n']}. These photos are rendered or "
            "pasted; real phone photos are untested. The evaluation above ran before this change, so its mask counts describe the old prompt.",
        ]
        run = ROOT / "data/replays/j_261105_92a408c2/summary.json"
        if run.exists():
            job = json.loads(run.read_text())
            rows += [
                "",
                f"A live job on the battery cover after the fix measured from SAM's mask and verified at {job['max_error_mm']:.2f} mm in "
                f"{job['iterations']} rounds, for ${job['cost_usd']:.2f}: the stored run is `data/replays/{job['id']}`, and `/jobs/{job['id']}` on the site.",
            ]
        after = ROOT / "eval/reports/latest/after_fix.json"
        if after.exists():
            doc = json.loads(after.read_text())
            was, now = doc["before"], doc["after"]
            sam = doc["masks"]["after"].get("sam-3.1", 0)
            sam_before = doc["masks"]["before"].get("sam-3.1", 0)
            d = doc["discordant"]
            call = (
                "no measured difference"
                if doc["mcnemar_p"] >= 0.05
                else ("better" if d["after_only"] > d["before_only"] else "worse")
            )
            rows += [
                "",
                f"**The same photos, whole jobs.** {doc['paired']} of {doc['planned']} of the evaluation's runs, chosen by a fixed seed before running, finished the "
                f"full loop again with the fix before the stop time (`eval/after_fix.py`, `eval/reports/latest/after_fix.json`). SAM measured {sam} of them, against "
                f"{sam_before} the first time. Every size within 0.5 mm: {now['pass_0_5']} after and {was['pass_0_5']} before. Median error per size "
                f"{now['median_error_mm']} mm after and {was['median_error_mm']} mm before. Verified: {now['verified']} after and {was['verified']} before; "
                f"verified but off: {now['verified_but_off']} after and {was['verified_but_off']} before. The rule fixed before the run reads {call} "
                f"(McNemar p = {doc['mcnemar_p']:.2f}, {d['after_only']} pairs improved and {d['before_only']} got worse), but the direction is "
                f"{'the wrong way' if d['before_only'] > d['after_only'] else 'not against the fix'}, so **a better mask rate is not yet a better whole job**. "
                f"Cost ${now['usd']:.2f}. Not started by the stop time: {len(doc['not_run'])}, in seeded order. "
                f"A first attempt was thrown out and not counted: it was {doc['discarded_attempt']['why']} (${doc['discarded_attempt']['usd']:.2f}).",
            ]
    return "\n".join(rows)


BLOCKS: dict[str, Callable[[], str]] = {
    "links": links_row,
    "status": status_line,
    "evaluation-line": evaluation_line,
    "headline": headline,
    "meta-tooling": meta_table,
    "bench": bench_tables,
    "evidence": evidence,
    "built": built,
    "badges": badges,
    "film": film,
    "time": time_table,
    "audit": audit,
    "scale": scale,
    "thresholds": thresholds,
    "failures": failures,
    "gates": gates,
    "rubric": rubric,
}


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
    from tools import readme_charts

    if (REPORT.parent / "report.json").exists():
        readme_charts.write_all()
    README.write_text(render(README.read_text(encoding="utf-8")), encoding="utf-8")
    print(f"updated {README.relative_to(ROOT)}: {', '.join(BLOCKS)}")


if __name__ == "__main__":
    main()
