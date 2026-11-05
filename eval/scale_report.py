"""Build eval/reports/latest/scale.json from the stored scale runs (eval/runs/live_scale). No model calls.

    uv run python -m eval.scale_report [--runs eval/runs/live_scale] [--out eval/reports/latest/scale.json]

Tables come from the bench's own `build_tables` code. These runs stay apart from the frozen bench in eval/runs/live, and the
real-photo counters stay 0: nothing here is a phone capture.
"""

from __future__ import annotations

import argparse
import datetime as dt
import gzip
import json
import re
import statistics
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import numpy as np

from . import run as bench
from .stats import bootstrap_ci, mcnemar_paired, wilson_ci

REPO = Path(__file__).resolve().parents[1]
RUNS = REPO / "eval" / "runs" / "live_scale"
OUT = REPO / "eval" / "reports" / "latest" / "scale.json"
PLANNED = {
    "synthetic/PS": 200,
    "synthetic/B1": 100,
    "broken/PS": 30,
    "reference_objects/PS": 60,
    "control_top/PS": 40,
    "control_side/PS": 40,
    "redteam/PS": 40,
}


def rate(k: int, n: int) -> dict[str, Any]:
    lo, hi = wilson_ci(k, n) if n else (float("nan"), float("nan"))
    return {"k": k, "n": n, "rate": round(k / n, 4) if n else None, "ci95": [round(lo, 4), round(hi, 4)] if n else None}


def load_scores(root: Path) -> list[dict[str, Any]]:
    return [json.loads(p.read_text()) for p in sorted(root.glob("*/*/*/score.json"))]


def worst_dim(score: Mapping[str, Any]) -> str:
    """The scored dimension furthest from ground truth, for naming what a verified part got wrong."""
    dims = bench.scored_dims(score)
    return str(max(dims, key=lambda d: abs(float(d["error_mm"])))["name"]) if dims else ""


def verified_but_off(scores: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Parts the verifier passed that are more than 0.5 mm off ground truth, by the bench's own definition (`config_row`)."""
    ver = [s for s in scores if s.get("verified")]
    off = [s for s in ver if not s.get("pass_0_5")]
    height = [s for s in off if "thickness" in worst_dim(s)]
    return {**rate(len(off), len(ver)), "off_in_height": len(height), "of_runs": len(scores)}


def _events(root: Path, score: Mapping[str, Any]) -> list[dict[str, Any]]:
    path = (
        root / str(score.get("scale_suite")) / str(score.get("config")) / str(score.get("sample_id")) / "run.jsonl.gz"
    )
    if not path.exists():
        return []
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        return [json.loads(line) for line in fh]


def understanding(scores: Sequence[Mapping[str, Any]], root: Path) -> dict[str, Any]:
    """Muse Spark's family and whether a broken region was kept, read from each PS run's log against the sample's template.

    The bench runs without packaging, so the PartSpec itself is not stored. The understand stage's closing label names the
    family, and the job logs "broken region kept" when a broken region survives code's checks.
    """
    from services.agent.templates import get_template

    data = root / "dataset_manifest.json"
    template_of = {r["id"]: r.get("template") for r in json.loads(data.read_text())["samples"]} if data.exists() else {}
    fam_right = fam_n = template_right = template_n = broken_said = broken_n = false_break = intact_n = 0
    for s in scores:
        name = template_of.get(str(s.get("sample_id")))
        if s.get("config") != "PS" or s.get("kind") != "template" or not name:
            continue
        events = _events(root, s)
        label = next(
            (
                str(e.get("label"))
                for e in events
                if e.get("t") == "stage" and e.get("stage") == "understand" and e.get("status") == "ok"
            ),
            "",
        )
        said = label.split(":", 1)[0].strip() if ":" in label else ""
        if said:
            fam_n += 1
            fam_right += said == str(get_template(name).family.value)
        if s.get("template"):
            template_n += 1
            template_right += s.get("template") == name
        kept = any("broken region kept" in str(e.get("msg") or "") for e in events)
        if s.get("scale_suite") == "broken":
            broken_n += 1
            broken_said += kept
        else:
            intact_n += 1
            false_break += kept
    return {
        "family_correct": rate(fam_right, fam_n),
        "template_chosen_correct": rate(template_right, template_n),
        "broken_region_kept_on_broken": rate(broken_said, broken_n),
        "broken_region_kept_on_intact": rate(false_break, intact_n),
        "source": "run logs; a separate 200-call understand stage was not needed",
        "note": "the sample's intent sentence names the part, so family accuracy is not a test of vision alone",
    }


def mask_sources(scores: Sequence[Mapping[str, Any]], root: Path) -> dict[str, dict[str, int]]:
    """Which segmenter measured each run, from its own log line "(mask: ...)", per suite."""
    out: dict[str, dict[str, int]] = {}
    for s in scores:
        suite = str(s.get("scale_suite"))
        row = out.setdefault(suite, {})
        found = None
        for e in _events(root, s):
            m = re.search(r"\(mask: ([^)]+)\)", str(e.get("msg") or e.get("label") or ""))
            if m and str(e.get("msg") or e.get("label") or "").startswith("Measured"):
                found = m.group(1)
                break
        key = found or "no measure line"
        row[key] = row.get(key, 0) + 1
    return out


def model_totals(root: Path) -> dict[str, Any]:
    by: dict[str, dict[str, float]] = {}
    for path in root.glob("*/*/*/run.jsonl.gz"):
        with gzip.open(path, "rt", encoding="utf-8") as fh:
            for line in fh:
                e = json.loads(line)
                if e.get("t") != "model_call":
                    continue
                key = f"{e.get('model')} ({e.get('mode')})"
                row = by.setdefault(key, {"calls": 0, "tokens": 0, "usd": 0.0, "ms": 0})
                row["calls"] += 1
                row["tokens"] += int(e.get("tokens_in") or 0) + int(e.get("tokens_out") or 0)
                row["usd"] += float(e.get("usd") or 0)
                row["ms"] += int(e.get("ms") or 0)
    return {k: {**v, "usd": round(v["usd"], 4)} for k, v in sorted(by.items())}


def sam_summary(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    rows = json.loads(path.read_text())["rows"]
    good = [r for r in rows if r.get("iou") is not None]

    def stats(rs: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
        iou = np.array([r["iou"] for r in rs], dtype=float)
        bd = np.array([r["mean_mm"] for r in rs if r.get("mean_mm") is not None], dtype=float)
        lo, hi = bootstrap_ci(iou, np.median, seed=0) if len(iou) > 1 else (float("nan"), float("nan"))
        return {
            "n": len(rs),
            "iou_median": round(float(np.median(iou)), 4) if len(iou) else None,
            "iou_median_ci95": [round(float(lo), 4), round(float(hi), 4)] if len(iou) > 1 else None,
            "iou_p10": round(float(np.percentile(iou, 10)), 4) if len(iou) else None,
            "iou_at_least_0_95": rate(int((iou >= 0.95).sum()), len(iou)),
            "boundary_mean_mm_median": round(float(np.median(bd)), 3) if len(bd) else None,
            "boundary_mean_mm_p90": round(float(np.percentile(bd, 90)), 3) if len(bd) else None,
        }

    presets = sorted({str(r.get("preset")) for r in good})
    returned = [r for r in good if float(r["iou"]) > 0]
    return {
        "mask_returned": rate(len(returned), len(rows)),
        "when_returned": stats(returned) if returned else None,
        "all_photos": stats(good),
        "errors": len(rows) - len(good),
        "planned": 500,
        "ran": len(rows),
        "calls": sum(int(r.get("calls") or 0) for r in rows),
        "usd": round(sum(float(r.get("usd") or 0) for r in rows), 4),
        "by_preset": {
            p: {
                "photos": sum(str(r.get("preset")) == p for r in good),
                "mask_returned": sum(str(r.get("preset")) == p for r in returned),
            }
            for p in presets
        },
        "by_suite": {
            k: {
                "photos": sum(r.get("suite") == k for r in rows),
                "mask_returned": sum(r.get("suite") == k for r in returned),
            }
            for k in sorted({str(r.get("suite")) for r in rows})
        },
        "note": "IoU 0 here means no mask cleared the product's confidence floor, with the threshold fallback switched off for this test",
    }


def wonder_summary(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    d = json.loads(path.read_text())
    rows = d["rows"]
    checked = d.get("page_check") or []
    return {
        "accepted_with_citation": rate(sum(bool(r.get("values")) for r in rows), len(rows)),
        "errors": sum(bool(r.get("error")) for r in rows),
        "usd": round(sum(float(r.get("usd") or 0) for r in rows), 4),
        "page_check": {
            "number_found_on_page": sum(c.get("number_on_page") is True for c in checked),
            "number_not_found": sum(c.get("number_on_page") is False for c in checked),
            "page_unreadable": sum(c.get("number_on_page") is None for c in checked),
        },
        "note": d.get("note"),
    }


def voice_summary(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    d = json.loads(path.read_text())
    rows = d["rows"]

    def part(key: str, rs: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
        have = [r[key] for r in rs if r.get(key)]
        return rate(sum(bool(x.get("right")) for x in have), len(have))

    langs = sorted({r["language"] for r in rows})
    wrong = [{"line": r["line"], "heard": (r.get("spoken") or {}).get("transcript"), "edits": (r.get("spoken") or {}).get("edits"), "expected": (r.get("spoken") or {}).get("expected")}
             for r in rows if r.get("spoken") and not r["spoken"].get("right")]  # fmt: skip
    return {
        "speech": d.get("speech"),
        "spoken": part("spoken", rows),
        "typed": part("typed", rows),
        "rescored": d.get("rescored"),
        "wrong_typed": [
            {"line": r["line"], "edits": r["typed"].get("edits"), "expected": r["typed"].get("expected")}
            for r in rows
            if r.get("typed") and not r["typed"].get("right")
        ],
        "by_language": {
            la: {
                "spoken": part("spoken", [r for r in rows if r["language"] == la]),
                "typed": part("typed", [r for r in rows if r["language"] == la]),
            }
            for la in langs
        },
        "wrong_spoken": wrong,
    }


def paired(scores: Sequence[Mapping[str, Any]]) -> dict[str, Any] | None:
    syn = [s for s in scores if s.get("scale_suite") == "synthetic"]
    b1 = {s["sample_id"]: bool(s.get("pass_0_5")) for s in syn if s.get("config") == "B1"}
    ps = {s["sample_id"]: bool(s.get("pass_0_5")) for s in syn if s.get("config") == "PS"}
    common = sorted(set(b1) & set(ps))
    if not common:
        return None
    b, c, p = mcnemar_paired([b1[s] for s in common], [ps[s] for s in common])
    return {
        "n_pairs": len(common),
        "metric": "pass@0.5",
        "b1_pass": sum(b1[s] for s in common),
        "ps_pass": sum(ps[s] for s in common),
        "b1_only": b,
        "ps_only": c,
        "p_value": round(p, 6),
    }


def side_question(scores: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    top = [s for s in scores if s.get("scale_suite") == "control_top"]
    side = [s for s in scores if s.get("scale_suite") == "control_side"]
    a, b = verified_but_off(top), verified_but_off(side)
    shown = False
    if a["n"] and b["n"]:
        shown = b["rate"] < a["rate"] and b["ci95"][1] < a["ci95"][0]
    return {
        "top_only": a,
        "top_and_side": b,
        "rule": "helpful only if lower and the intervals do not overlap",
        "helpful_shown": shown,
    }


def build(root: Path = RUNS) -> dict[str, Any]:
    scores = load_scores(root)
    counts: dict[str, int] = {}
    for s in scores:
        key = f"{s.get('scale_suite')}/{s.get('config')}"
        counts[key] = counts.get(key, 0) + 1
    tables: dict[str, Any] = {}
    for scale, suite in (
        ("synthetic", "synthetic"),
        ("broken", "synthetic"),
        ("reference_objects", "reference_objects"),
    ):
        sub = [{**s, "split": "held_out", "suite": suite} for s in scores if s.get("scale_suite") == scale]
        if sub:
            t = bench.build_tables(sub, "live", [])[suite]
            tables[scale] = {
                k: t[k] for k in ("n", "ground_truth", "ci", "rows", "headline", "mcnemar_B1_vs_PS") if k in t
            }
    for scale, suite in (("control_top", "control"), ("control_side", "control"), ("redteam", "redteam")):
        sub = [{**s, "suite": suite} for s in scores if s.get("scale_suite") == scale]
        if sub:
            t = bench.gate_table(suite, sub, "live")
            tables[scale] = {
                "n": t.get("n"),
                "headline": t.get("headline"),
                "wrong": [r for r in t.get("rows", []) if not r.get("correct")],
            }
    stages = root / "stages"
    usd_runs = sum(float(s.get("usd") or 0) for s in scores)
    usd_file = stages / "usd.json"
    usd_stages = json.loads(usd_file.read_text()) if usd_file.exists() else {}
    all_ps = [s for s in scores if s.get("config") == "PS" and s.get("scale_suite") != "redteam"]
    walls = [float(s.get("wall_s") or 0) for s in scores]
    statuses: dict[str, int] = {}
    for s in scores:
        statuses[str(s.get("status"))] = statuses.get(str(s.get("status")), 0) + 1
    return {
        "generated_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "label": "scale evaluation: live model calls on fresh synthetic renders, plan fixed before running (eval/SCALE_PLAN.md)",
        "counts_as_real_photos_measured": 0,
        "tree": sorted({str(s.get("tree")) for s in scores if s.get("tree")}),
        "stop": json.loads((root / "run_end.json").read_text()) if (root / "run_end.json").exists() else None,
        "runs": counts,
        "planned": PLANNED,
        "not_run": {k: max(0, v - counts.get(k, 0)) for k, v in PLANNED.items()},
        "statuses": statuses,
        "usd": {
            "runs": round(usd_runs, 2),
            "stages": usd_stages,
            "total": round(usd_runs + sum(usd_stages.values()), 2),
        },
        "wall_s": {"sum": round(sum(walls), 1), "median": round(statistics.median(walls), 1) if walls else None},
        "models": model_totals(root),
        "tables": tables,
        "paired_b1_vs_ps": paired(scores),
        "verified_but_off": {"all_ps": verified_but_off(all_ps), **side_question(scores)},
        "understanding": understanding(scores, root),
        "mask_sources": mask_sources(scores, root),
        "sam": sam_summary(stages / "sam.json"),
        "wonder": wonder_summary(stages / "wonder.json"),
        "voice": voice_summary(stages / "voice.json"),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=Path, default=RUNS)
    ap.add_argument("--out", type=Path, default=OUT)
    a = ap.parse_args()
    rep = build(a.runs)
    a.out.write_text(json.dumps(bench.json_safe(rep), indent=1) + "\n")
    print(f"wrote {a.out}: {sum(rep['runs'].values())} runs, ${rep['usd']['total']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
