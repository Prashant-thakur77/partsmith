"""Every number the film says or shows, read from the repository at build time (never typed by hand).

    python3 video/facts.py  ->  ~/Videos/partsmith/build/facts.json

Sources: the stored battery-cover run (data/replays), the bench report and its siblings (eval/reports/latest), git.
The one outside number (e-waste) is kept in OUTSIDE with the report it comes from and is shown with that report's name.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORK = os.path.expanduser("~/Videos/partsmith")
OUT = f"{WORK}/build/facts.json"
RUN = "j_261029_daf26965"  # the stored live battery-cover run the film walks through
OUTSIDE = {
    "ewaste_bn_kg": 62,
    "ewaste_year": 2022,
    "ewaste_source": "Global E-waste Monitor 2024 (UN)",
    "ewaste_url": "https://www.unitar.org/about/news-stories/press/global-e-waste-monitor-2024-electronic-waste-rising-five-times-faster-documented-e-waste-recycling",
    "printers_text": "Over 1 million",
    "printers_period": "Q1 2025",
    "printers_source": "CONTEXT, entry-level 3D printers (under $2,500)",
    "printers_url": "https://www.tctmagazine.com/additive-manufacturing-3d-printing-news/tariffs-fears-push-entry-level-3d-printer-shipments-in-q1-to-1-million/",
    "others_source": "Category summary from public reviews and product docs, Nov 2026 (including All3DP's AI generator tests)",
    "others_url": "https://all3dp.com/1/do-free-text-to-3d-model-generators-really-work-we-tested-3-of-them",
    "repair_law": "EU Directive 2024/1799",
    "repair_url": "https://cm.twobirds.com/en/insights/2024/germany/recht-auf-reparatur-richtlinie-veroeffentlicht-auswirkungen-fuer-wirtschaftsakteure-in-der-eu",
}


def load(path: str) -> dict:
    return json.load(open(f"{ROOT}/{path}"))


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()


def stored_run() -> dict:
    """The run the film shows: errors per round from its own log, cost and print estimate from its own files."""
    path = f"data/replays/{RUN}"
    events = [json.loads(line) for line in open(f"{ROOT}/{path}/run.jsonl")]
    errors = [round(e["hausdorff_mm"], 2) for e in events if e.get("t") == "iteration"]
    first_fix = next(e for e in events if e.get("t") == "iteration" and e.get("iter") == 2)
    tongue = next(x for x in first_fix["edits"] if x["param"] == "tongue_count")
    summary = load(f"{path}/summary.json")
    pla = load(f"{path}/buy_or_print.json")["prints"][0]
    return {
        "id": RUN,
        "params": [line.strip() for line in open(f"{ROOT}/{path}/part.py") if re.match(r'\s+"(length|width|thickness|tongue_count|latch_height|corner_radius)": \(', line)],
        "title": summary["title"],
        "origin": summary["origin"],
        "mode": summary["provider_mode"],
        "verified": summary["verified"],
        "errors": errors,
        "rounds": len(errors),
        "tongues_from": int(tongue["from"]),
        "tongues_to": int(tongue["to"]),
        "usd": summary["cost_usd"],
        "print_minutes": pla["print_minutes"],
        "grams": pla["grams"],
        "inr": pla["filament_cost"]["INR"],
    }


def verified_audit(report: dict) -> dict:
    """Every verified part in every stored PS run, checked against ground truth on every dimension."""
    verified = [row for suite in report["runs"].values() for row in suite.get("PS", []) if row.get("verified")]
    off = [row for row in verified if (row.get("max_abs_err_mm") or 0) > 0.5]
    return {
        "verified": len(verified),
        "within": len(verified) - len(off),
        "off": len(off),
        "off_height": sum("thickness" in (row.get("failure") or "") for row in off),
    }


def tests() -> dict:
    """Passing suites from the last `make proof` run. A suite with a failure, or one that did not run, stays out of the film."""
    path = f"{ROOT}/eval/reports/latest/tests.json"
    gates = json.load(open(path))["gates"] if os.path.exists(path) else {}
    return {k: {"passed": g["passed"]} for k, g in gates.items() if g.get("status") == "passed" and g.get("passed")}


def main() -> None:
    report = load("eval/reports/latest/report.json")
    bypass = load("eval/reports/latest/bypass.json")
    thresholds = load("eval/reports/latest/provenance.json")["thresholds"]
    weights = load("eval/reports/latest/open_weights.json")
    links = load("docs/links.json")
    tables = report["tables"]
    syn = next(r for r in tables["synthetic"]["rows"] if r["config"] == "PS")
    single = next(r for r in tables["synthetic"]["rows"] if r["config"] == "B1")
    mesh = load("eval/reports/latest/program_vs_mesh.json")["summary"]
    facts = {
        "run": stored_run(),
        "limit_mm": thresholds["HAUSDORFF_PASS_MM"],
        "attempts": bypass["attempts"],
        "blocked": bypass["blocked"],
        "synthetic_n": syn["n"],
        "synthetic_verified": round(syn["verified_rate"] * syn["n"]),
        "synthetic_median_mm": syn["median_abs_err_mm"],
        "b1_median_mm": single["median_abs_err_mm"],
        "mesh_shift_mm": round(mesh["mesh_hole_spacing_shift_median_mm"], 2),
        "knob_shift_mm": round(mesh["knob_hole_spacing_shift_median_mm"], 2),
        "mesh_parts": mesh["parts"],
        "audit": verified_audit(report),
        "control": [tables["control"]["headline"]["correct"], tables["control"]["headline"]["n"]],
        "redteam": [tables["redteam"]["headline"]["correct"], tables["redteam"]["headline"]["n"]],
        "real_parts": tables["real_ruler"].get("n") or 0,
        "open_share_pct": round(weights["builder"]["share_tokens_open_weights"] * 100),
        "open_calls": weights["builder"]["calls_on_open_weights"],
        "builder_calls": weights["builder"]["calls"],
        "meta": meta_models(weights),
        "report_date": report["generated_at"][:10],
        "git_sha": git("rev-parse", "--short", "HEAD"),
        "first_commit": git("log", "--reverse", "--format=%ad", "--date=short").split()[0],
        "commits": int(git("rev-list", "--count", "HEAD")),
        "tests": tests(),
        "public": public_photos(report),
        "scale": scale_eval(),
        "time": time_saved(report),
        "marker_scale": public_scale(),
        "site": links.get("live_site") or "",
        "video": links.get("video") or "",
        **OUTSIDE,
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(facts, open(OUT, "w"), indent=1)
    print(json.dumps(facts, indent=1))


def scale_eval() -> dict:
    """The large live evaluation (eval/reports/latest/scale.json): fresh renders, plan fixed first, nothing rerun."""
    s = load("eval/reports/latest/scale.json")
    live = {k: v for k, v in s["models"].items() if "(live)" in k}
    ps = next(r for r in s["tables"]["synthetic"]["rows"] if r["config"] == "PS")
    off, pair, red = s["verified_but_off"], s["paired_b1_vs_ps"], s["tables"]["redteam"]["headline"]
    return {
        "done": s["stop"]["done"],
        "calls": sum(v["calls"] for v in live.values()),
        "sam_calls": sum(v["calls"] for k, v in live.items() if "sam" in k),
        "spark_calls": sum(v["calls"] for k, v in live.items() if "spark-1.3" in k),
        "open_calls": sum(v["calls"] for k, v in live.items() if "spark-open" in k),
        "pairs": pair["n_pairs"],
        "ps_pass": pair["ps_pass"],
        "b1_pass": pair["b1_pass"],
        "p": round(pair["p_value"], 3),
        "top_off": off["top_only"]["k"],
        "top_n": off["top_only"]["n"],
        "side_off": off["top_and_side"]["k"],
        "side_n": off["top_and_side"]["n"],
        "median_mm": ps["median_abs_err_mm"],
        "n": ps["n"],
        "minutes": round(ps["median_wall_s"] / 60),
        "usd_per_job": ps["usd_per_job"],
        "red_ok": red["correct"],
        "red_n": red["n"],
    }


def meta_models(weights: dict) -> list[dict]:
    """The Meta models, with their live call counts in the large evaluation where it logged them."""
    calls = scale_eval()

    return [
        {"name": "SAM 3.1", "job": "Asked first for the part mask; code falls back if unsure", "calls": calls["sam_calls"]},
        {"name": "Muse Spark 1.3", "job": "Names the part, finds the break, points at each hole", "calls": calls["spark_calls"]},
        {"name": "Muse Spark Open", "job": "Open weights: writes and fixes the CadQuery program", "calls": calls["open_calls"]},
        {"name": "Muse Wonder", "job": "Finds a published spec; code keeps only cited values", "calls": None},
        {"name": "Muse Image", "job": "In-place repair preview, always labelled AI", "calls": None},
        {"name": "Voice Transcribe", "job": "Hindi and English voice edits, mapped to knobs", "calls": None},
    ]


def time_saved(report: dict) -> dict:
    """Measured times: the stored run's photo-to-file time, median per job from the bench, and a fresh re-bake on a stored program."""
    path = f"data/replays/{RUN}"
    events = [json.loads(line) for line in open(f"{ROOT}/{path}/run.jsonl")]
    first_file = next(e["ts"] for e in events if e.get("t") == "artifact" and e.get("kind") == "threemf")
    synthetic = next(r for r in load("eval/reports/latest/scale.json")["tables"]["synthetic"]["rows"] if r["config"] == "PS")
    public = next(r for r in report["separate_tables"]["public_photos"]["rows"] if r["config"] == "PS")
    return {
        "run_minutes": round((first_file - load(f"{path}/summary.json")["created_at"]) / 60, 1),
        "synthetic_minutes": round(synthetic["median_wall_s"] / 60),
        "public_minutes": round(public["median_wall_s"] / 60, 1),
        "synthetic_usd": synthetic["usd_per_job"],
        "public_usd": public["usd_per_job"],
        "rebake_ms": rebake_ms(),
    }


def rebake_ms() -> int | None:
    """A real re-bake of the stored program at a new knob value, timed by the API; kept from the last run when the API is down."""
    keep = f"{WORK}/build/rebake.json"
    if os.path.exists(keep):  # one measurement per film, so the voice and the picture never disagree
        return json.load(open(keep))
    try:
        url = f"http://127.0.0.1:8766/api/v1/parts/battery-cover-45mm/bake?format=stl&length={40 + (time.time() % 40):.1f}"
        with urllib.request.urlopen(url, timeout=60) as r:
            got = json.load(r)
        if not got.get("cache_hit"):
            json.dump(got["ms"], open(keep, "w"))
    except (OSError, ValueError, KeyError):
        pass
    return json.load(open(keep)) if os.path.exists(keep) else None


def public_photos(report: dict) -> dict:
    """The public-photo suite: real photographs of real objects, pasted on a rendered mat. Not phone captures."""
    table = report["separate_tables"]["public_photos"]
    head = table["headline"]
    return {"median_mm": round(head["median_abs_err_mm"], 2), "n": head["n"]}


def public_scale() -> dict:
    """How well the plane fit from the markers holds on real camera photos of printed boards, per 100 mm of span."""
    s = load("eval/reports/latest/public_scale.json")["summary"]
    return {"pct": s["mean_err_pct"], "mm_per_100": round(s["mean_err_pct"], 2), "photos": s["n_photos"], "corners": s["n_corners"]}


if __name__ == "__main__":
    main()
