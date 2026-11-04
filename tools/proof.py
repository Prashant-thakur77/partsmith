"""Test evidence: run the real gates, write `eval/reports/latest/tests.json` and the judge-readable `docs/PROOF.md`.

Counts come from machine output (junit xml, the node test runner's summary, exit codes). A gate that did not run this
time says `not run`; nothing is carried over from an earlier run.

    uv run python -m tools.proof                     # backend, web unit, deploy check, types, lint (= make proof)
    uv run python -m tools.proof --browser           # also the browser tests (--workers=2, stopped after 10 minutes)
    uv run python -m tools.proof --skip backend      # any gate by name (it is then labelled `not run`)
    uv run python -m tools.proof --write-only        # only rewrite docs/PROOF.md from tests.json and the reports
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "eval" / "reports" / "latest"
TESTS_JSON = REPORTS / "tests.json"
PROOF_MD = ROOT / "docs" / "PROOF.md"
GATE_TIMEOUT_S = 1500
BROWSER_TIMEOUT_S = 600
NOT_RUN = "not run"

UV = ["uv", "run"]
SIMPLE_GATES: dict[str, tuple[str, list[str]]] = {
    "deploy_check": ("Deploy configuration check", ["make", "deploy-check"]),
    "python_lint": ("Python lint and format (ruff)", ["make", "lint"]),
    "python_types": ("Python types (mypy --strict)", ["make", "typecheck"]),
    "web_types": ("Web types (tsc)", ["pnpm", "-C", "apps/web", "-s", "typecheck"]),
    "web_lint": ("Web lint (eslint)", ["pnpm", "-C", "apps/web", "-s", "lint"]),
}
TEST_GATES = {
    "backend": "Backend unit tests (pytest)",
    "web_unit": "Web unit tests (node --test)",
    "browser": "Browser tests (Playwright)",
}
ALL_GATES = (*TEST_GATES, *SIMPLE_GATES)


def _run(cmd: Sequence[str], *, timeout_s: int, cwd: Path = ROOT) -> tuple[int | None, str, float]:
    """(exit code, or None on timeout; combined output; seconds)."""
    t0 = time.perf_counter()
    try:
        p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout_s, check=False)
    except subprocess.TimeoutExpired as exc:
        out = exc.stdout if isinstance(exc.stdout, str) else ""
        return None, out, time.perf_counter() - t0
    return p.returncode, p.stdout + p.stderr, time.perf_counter() - t0


def parse_junit(xml_text: str) -> dict[str, int]:
    """Totals from a junit xml file (pytest writes one <testsuite> inside <testsuites>)."""
    root = ET.fromstring(xml_text)
    suites = [root] if root.tag == "testsuite" else list(root)
    tests = sum(int(s.get("tests", 0)) for s in suites)
    failed = sum(int(s.get("failures", 0)) + int(s.get("errors", 0)) for s in suites)
    skipped = sum(int(s.get("skipped", 0)) for s in suites)
    return {"tests": tests, "passed": tests - failed - skipped, "failed": failed, "skipped": skipped}


def parse_node_test(output: str) -> dict[str, int] | None:
    """The summary the node test runner prints (`ℹ tests 12`, or `# tests 12` from the TAP reporter)."""
    found: dict[str, int] = {}
    for key in ("tests", "pass", "fail", "skipped", "todo", "cancelled"):
        m = re.findall(rf"^(?:ℹ|#)\s+{key}\s+(\d+)\s*$", output, re.M)
        if m:
            found[key] = int(m[-1])
    if "tests" not in found:
        return None
    return {
        "tests": found["tests"],
        "passed": found.get("pass", 0),
        "failed": found.get("fail", 0) + found.get("cancelled", 0),
        "skipped": found.get("skipped", 0) + found.get("todo", 0),
    }


def parse_playwright(report_json: str) -> dict[str, int] | None:
    """Totals from Playwright's JSON reporter (`stats`)."""
    try:
        st = json.loads(report_json)["stats"]
    except (ValueError, KeyError, TypeError):
        return None
    passed, failed = int(st.get("expected", 0)), int(st.get("unexpected", 0)) + int(st.get("flaky", 0))
    skipped = int(st.get("skipped", 0))
    return {"tests": passed + failed + skipped, "passed": passed, "failed": failed, "skipped": skipped}


def _status(code: int | None, counts: Mapping[str, int] | None = None) -> str:
    if code is None:
        return "timed out"
    if counts is not None and counts.get("failed"):
        return "failed"
    return "passed" if code == 0 else "failed"


def not_run(title: str, why: str = "skipped this time") -> dict[str, Any]:
    return {"title": title, "status": NOT_RUN, "note": why}


def run_backend() -> dict[str, Any]:
    with tempfile.TemporaryDirectory() as d:
        xml = Path(d) / "pytest.xml"
        code, out, secs = _run(
            [*UV, "pytest", "-q", "-m", "not slow and not live", f"--junitxml={xml}"], timeout_s=GATE_TIMEOUT_S
        )
        counts = parse_junit(xml.read_text()) if xml.exists() else None
    res: dict[str, Any] = {"title": TEST_GATES["backend"], "command": "make test", "seconds": round(secs)}
    if counts is None:
        return {**res, "status": "failed" if code is not None else "timed out", "note": out[-300:]}
    return {**res, **counts, "status": _status(code, counts)}


def run_web_unit() -> dict[str, Any]:
    code, out, secs = _run(["pnpm", "-s", "test"], timeout_s=GATE_TIMEOUT_S, cwd=ROOT / "apps" / "web")
    counts = parse_node_test(out)
    res: dict[str, Any] = {
        "title": TEST_GATES["web_unit"],
        "command": "pnpm -s test (in apps/web)",
        "seconds": round(secs),
    }
    if counts is None:
        return {**res, "status": "failed" if code is not None else "timed out", "note": "no test summary in the output"}
    return {**res, **counts, "status": _status(code, counts)}


def run_browser(web_dir: Path | None = None, project: str | None = None) -> dict[str, Any]:
    """Playwright against the build in `web_dir` (default apps/web). It tests whatever that folder last built."""
    cwd = web_dir or ROOT / "apps" / "web"
    only = f" --project={project}" if project else ""
    with tempfile.TemporaryDirectory() as d:
        report = Path(d) / "pw.json"
        cmd = [
            "bash",
            "-c",
            f"PLAYWRIGHT_JSON_OUTPUT_NAME={report} E2E_PORT=3299 pnpm -s exec playwright test --workers=2{only} --reporter=json",
        ]
        code, _, secs = _run(cmd, timeout_s=BROWSER_TIMEOUT_S, cwd=cwd)
        counts = parse_playwright(report.read_text()) if report.exists() else None
    res: dict[str, Any] = {
        "title": TEST_GATES["browser"] + (f", {project} project only" if project else ""),
        "command": f"pnpm -s exec playwright test --workers=2{only} (after next build)",
        "seconds": round(secs),
    }
    if counts is None:
        return {**res, "status": "timed out" if code is None else "failed", "note": "no result report"}
    return {**res, **counts, "status": _status(code, counts)}


def run_simple(name: str) -> dict[str, Any]:
    title, cmd = SIMPLE_GATES[name]
    code, _, secs = _run(cmd, timeout_s=GATE_TIMEOUT_S)
    return {"title": title, "command": " ".join(cmd), "seconds": round(secs), "status": _status(code)}


def git_state() -> dict[str, Any]:
    sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=False
    ).stdout.strip()
    dirty = subprocess.run(
        ["git", "status", "--porcelain"], cwd=ROOT, capture_output=True, text=True, check=False
    ).stdout
    return {"sha": sha, "dirty": bool(dirty.strip())}


def collect(
    *, skip: Sequence[str] = (), browser: bool = False, web_dir: Path | None = None, project: str | None = None
) -> dict[str, Any]:
    gates: dict[str, Any] = {}
    runners: dict[str, Callable[[], dict[str, Any]]] = {
        "backend": run_backend,
        "web_unit": run_web_unit,
        "browser": lambda: run_browser(web_dir, project),
    }
    for name in ALL_GATES:
        title = TEST_GATES.get(name) or SIMPLE_GATES[name][0]
        if name in skip:
            gates[name] = not_run(title)
        elif name == "browser" and not browser:
            gates[name] = not_run(title, "not part of this run: use --browser")
        elif name in runners:
            gates[name] = runners[name]()
        else:
            gates[name] = run_simple(name)
        print(
            f"{name:14s} {gates[name]['status']}", {k: gates[name][k] for k in ("tests", "failed") if k in gates[name]}
        )
    return {"generated_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"), "git": git_state(), "gates": gates}


# ---------------------------------------------------------------- docs/PROOF.md


def _load(name: str) -> dict[str, Any]:
    p = REPORTS / name
    return json.loads(p.read_text()) if p.exists() else {}


def review_counts() -> dict[str, Any]:
    """Person-reviewed rounds from the real review log; a scripted test decision is never a person's."""
    from services.review.store import stats

    s = stats()
    return {"person_reviewed_with_judge": int(s["n"]), "test_decisions_excluded": int(s["tests_excluded"])}


def not_tested_counts() -> dict[str, Any]:
    from tools.readme import _photo_counts

    rep = _load("report.json")
    photos, parts = _photo_counts(rep)
    impact = _load("impact.json")
    return {
        "real_phone_photos_measured": photos,
        "real_parts_with_ruler_ground_truth": parts,
        "real_prints_or_repairs_logged": int(impact.get("n_sessions") or 0),
        **review_counts(),
    }


def _gate_row(g: Mapping[str, Any]) -> str:
    count = (
        f"{g['passed']}/{g['tests']} passed"
        + (f", {g['failed']} failed" if g.get("failed") else "")
        + (f", {g['skipped']} skipped" if g.get("skipped") else "")
        if "tests" in g
        else "–"
    )
    return f"| {g['title']} | {g['status']} | {count} | `{g.get('command', '–')}` |"


def _bench_rows(rep: Mapping[str, Any]) -> list[str]:
    what = {
        "synthetic": ("Full loop on rendered test photos", "exact: the mesh the photo was rendered from"),
        "reference_objects": ("Full loop on rendered standard objects", "published spec"),
        "real_ruler": ("Full loop on real broken parts", "school ruler, ±0.5 mm"),
        "public_photos": (
            "Full loop on public photos pasted on a rendered mat",
            "published spec, pasted at known size",
        ),
    }
    rows = []
    for key, (label, gt) in what.items():
        t = {**(rep.get("tables") or {}), **(rep.get("separate_tables") or {})}.get(key) or {}
        if t.get("status") != "ok":
            rows.append(f"| {label} | 0 | {gt} | pending: nothing has run |")
            continue
        h = t["headline"]
        pass_at = h.get("pass_at_0_5")
        passed = "?" if pass_at is None else round(float(pass_at) * int(h["n"]))
        sizes = "all held-out sizes" if key == "public_photos" else "all sizes"
        rows.append(
            f"| {label} | {h['n']} | {gt} | median abs error {h['median_abs_err_mm']} mm; {sizes} within 0.5 mm on "
            f"{passed}/{h['n']}; verified-but-off {h['verified_but_off']} ({rep.get('mode')} providers) |"
        )
    for key, label in (
        ("control", "Intact parts must be accepted"),
        ("redteam", "Bad photos must be rejected or refused"),
    ):
        h = ((rep.get("tables") or {}).get(key) or {}).get("headline") or {}
        if "correct" in h:
            rows.append(
                f"| {label} | {h['n']} | expected outcome per case | {h['correct']}/{h['n']} handled as expected |"
            )
    return rows


def excluded_scale_errors(runs_dir: Path = ROOT / "eval" / "runs" / "live" / "public_photos" / "PS") -> str:
    """What leaving the scale dimension out hides: the final model's largest error on it, from the stored runs."""
    worst: tuple[float, str] | None = None
    for p in sorted(runs_dir.glob("*/score.json")):
        score = json.loads(p.read_text())
        for d in score.get("dims") or []:
            if d.get("set_by_construction") and (worst is None or abs(float(d["error_mm"])) > worst[0]):
                worst = (abs(float(d["error_mm"])), str(score["sample_id"]))
    if worst is None:
        return ""
    return (
        f"In the full loop, the largest error of a final model on the excluded scale dimension was {worst[0]:g} mm "
        f"({worst[1]}). Those rows stay in each run's `score.json` under `eval/runs/live/public_photos/`."
    )


def render_proof(tests: Mapping[str, Any]) -> str:
    rep, scale, measure, byp = (
        _load("report.json"),
        _load("public_scale.json"),
        _load("public_photos_measure.json"),
        _load("bypass.json"),
    )
    missing = not_tested_counts()
    git = tests.get("git") or {}
    L = [
        "# What was tested, and what was not",
        "",
        "Generated by `make proof` (`tools/proof.py`) from `eval/reports/latest/tests.json` and the bench reports. Do not edit by hand.",
        "",
        f"Test run: {tests.get('generated_at', NOT_RUN)} at commit `{str(git.get('sha', '?'))[:10]}`"
        + (" plus uncommitted changes." if git.get("dirty") else "."),
        "",
        "## Test suites and gates",
        "",
        "A gate marked `not run` did not run this time; no count is carried over from an earlier run.",
        "",
        "| Gate | Status | Count | Command |",
        "|---|---|---|---|",
    ]
    L += [_gate_row(g) for g in (tests.get("gates") or {}).values()]
    L += [
        "",
        "## Benches",
        "",
        "Each row has its own ground truth. They are never merged. Rebuild with `make bench`; see `eval/REPRODUCE.md`.",
        "",
        "| What | N | Ground truth | Result |",
        "|---|---:|---|---|",
    ]
    L += _bench_rows(rep)
    if byp:
        L.append(
            f"| A model that lies or cheats | {byp['attempts']} | code decides, attempt by attempt | {byp['blocked']}/{byp['attempts']} blocked (`make lie` shows one) |"
        )
    h = (measure.get("summary") or {}).get("held_out") or {}
    if h.get("n_dims"):
        s = measure["summary"]
        L.append(
            f"| Public photos, measure only, no model | {s['n_photos']} | published spec, pasted at known size | capture gate "
            f"{s['capture_gate_passed']}/{s['n_photos']}; held-out dimensions mean abs {h['mean_abs_mm']} mm, 95 % CI "
            f"{h['ci95_mm'][0]} to {h['ci95_mm'][1]}, n = {h['n_dims']} |"
        )
    sc = scale.get("summary") or {}
    if sc.get("status") == "ok":
        L.append(
            f"| Flat-plane marker fit on real camera photos of printed boards | {sc['n_photos']} | documented board layout, "
            f"held-out inner corners | {sc['mean_err_pct']} % of span, 95 % CI {sc['ci95_pct'][0]} to {sc['ci95_pct'][1]}, "
            f"n = {sc['n_corners']} corners; {sc['mean_err_mm_over_100mm']} mm over a 100 mm span |"
        )
    L += ["", "## How to read the public-photo rows", ""]
    if measure:
        L += [str(measure.get("scope", "")), ""]
    if scale:
        L += [str(scale.get("scope", "")), ""]
        if scale.get("layout_finding"):
            L += [str(scale["layout_finding"]) + ".", ""]
    hidden = excluded_scale_errors()
    if hidden:
        L += [hidden, ""]
    first = _load("public_photos_measure_first_pass.json")
    fh = (first.get("summary") or {}).get("held_out") or {}
    if fh.get("n_dims"):
        L += [
            f"The first measure-only pass had a mean abs error of {fh['mean_abs_mm']} mm (n = {fh['n_dims']}) with cast "
            "shadows inside some cut-outs. The masks were then fixed by eye against the object's edge, and the numbers "
            "above are from after that fix. The first pass is kept in `eval/reports/latest/public_photos_measure_first_pass.json`.",
            "",
        ]
    L += [
        "## What has not been tested",
        "",
        f"- Real phone photos of a part on a laptop-screen mat: **{missing['real_phone_photos_measured']}** measured.",
        f"- Real broken parts with ruler ground truth: **{missing['real_parts_with_ruler_ground_truth']}**.",
        f"- Real prints or repairs logged: **{missing['real_prints_or_repairs_logged']}**.",
        f"- Judge decisions reviewed by a person: **{missing['person_reviewed_with_judge']}** "
        f"({missing['test_decisions_excluded']} scripted test decisions are left out of that count).",
        "- A phone photographing a laptop screen, end to end, on real hardware: moiré, glare and screen scale are only "
        "tested on rendered photos.",
        "- Whether a printed replacement fits: nothing here prints anything.",
        "",
        "## Reproduce",
        "",
        "```bash",
        "make proof                                # the gates above, then this page",
        "make bench                                # every bench table, from stored runs, no keys",
        "uv run python -m eval.public_scale        # the marker-fit check (needs the photos in var/public_photos/)",
        "uv run python -m eval.public_photos       # public photos, measure only, no model",
        "PROVIDER_MODE=live uv run python -m eval.run --live --suite public_photos --configs PS --jobs 2 --max-usd 5 --out var/public_photos/live_report",
        "```",
        "",
    ]
    return "\n".join(L)


def write_proof(tests: Mapping[str, Any]) -> None:
    PROOF_MD.write_text(render_proof(tests), encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m tools.proof", description=__doc__.split("\n\n")[0])
    ap.add_argument("--browser", action="store_true", help="also run the browser tests (--workers=2, 10 minute limit)")
    ap.add_argument("--browser-dir", type=Path, default=None, help="run them in this built copy of apps/web")
    ap.add_argument("--browser-project", default=None, help="only this Playwright project (labelled as such)")
    ap.add_argument("--skip", action="append", default=[], choices=ALL_GATES, help="repeatable; labelled `not run`")
    ap.add_argument("--write-only", action="store_true", help="only rewrite docs/PROOF.md")
    a = ap.parse_args(argv)
    if a.write_only:
        tests = json.loads(TESTS_JSON.read_text()) if TESTS_JSON.exists() else {}
    else:
        tests = collect(skip=a.skip, browser=a.browser, web_dir=a.browser_dir, project=a.browser_project)
        TESTS_JSON.parent.mkdir(parents=True, exist_ok=True)
        TESTS_JSON.write_text(json.dumps(tests, indent=1) + "\n")
    write_proof(tests)
    print(f"wrote {PROOF_MD.relative_to(ROOT)}" + ("" if a.write_only else f", {TESTS_JSON.relative_to(ROOT)}"))
    failed = [k for k, g in (tests.get("gates") or {}).items() if g["status"] in ("failed", "timed out")]
    if failed:
        print(f"failed: {', '.join(failed)}", file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
