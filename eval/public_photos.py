"""Measure-only pass over the `public_photos` samples: photo → mm with the threshold segmenter, no model, no cost.

The photos are composites (`tools/public_photos.py`): a real object cut out of a public photograph and pasted on our
rendered screen mat. Ground truth is the published spec. Only dimensions that did not set the paste scale count. The
report also gives the same dimension read straight from the cut-out, before the mat: the part of the error that comes
from the source photograph and the mask rather than from the measuring path.

    uv run python -m eval.public_photos    # writes eval/reports/latest/public_photos_measure.{json,md}
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import yaml

from tools import public_photos as PP

from .measure_only import score_measurements
from .metrics import error_stats, rate
from .stats import cluster_bootstrap_mean

REPO = Path(__file__).resolve().parents[1]
REPORT_DIR = REPO / "eval" / "reports" / "latest"

SCOPE = (
    "Composites, not phone captures: a real object cut out of a public photograph by code and pasted on our rendered "
    "screen mat at a scale set from one published dimension (the long side). That dimension is marked "
    "set_by_construction and excluded from every error. The mat, the camera and the light on the mat are rendered, "
    "the cut-out is flat, has no walls and casts no shadow. Counted as 0 real photos measured. It says nothing about a "
    "phone photographing a laptop screen."
)


def measure_sample(folder: Path) -> dict[str, Any]:
    """One sample through `measure_photo` with the threshold segmenter; the job input is what a user would type."""
    from services.metrology.measure import measure_photo
    from services.metrology.segment import ThresholdSegmenter

    meta = json.loads((folder / "meta.json").read_text())
    gt = yaml.safe_load((folder / "gt.yaml").read_text())
    rows = list(gt["dims"])
    out: dict[str, Any] = {
        "sample_id": meta["id"],
        "object": gt["object"],
        "photo_id": gt["photo_id"],
        "scale_set_by": gt["scale_set_by"],
    }
    try:
        res = measure_photo(
            (folder / "top.jpg").read_bytes(),
            "top",
            segmenter=ThresholdSegmenter(),
            thickness_mm=float(meta["user_thickness_mm"]),
        ).result
    except Exception as exc:  # a crash is a failure to report
        return {**out, "accepted": False, "reason": f"{type(exc).__name__}: {exc}"[:200], "dims": [], "missed": []}
    meas = res.measurements
    pairs, missed, extra = score_measurements(meas, rows, "top", "diameter")
    dims = []
    for g, val in pairs:
        row = {
            "name": str(g["name"]),
            "gt_mm": float(g["value_mm"]),
            "measured_mm": round(float(val), 4),
            "error_mm": round(float(val) - float(g["value_mm"]), 4),
        }
        if g.get("set_by_construction"):
            row["set_by_construction"] = True
        elif str(g["name"]) == "width":
            row["cutout_error_mm"] = round(float(gt["cutout"]["short_mm"]) - float(g["value_mm"]), 4)
        elif str(g["name"]) == "length":
            row["cutout_error_mm"] = round(float(gt["cutout"]["long_mm"]) - float(g["value_mm"]), 4)
        dims.append(row)
    return {
        **out,
        "accepted": bool(res.capture.passed) and meas is not None,
        "reason": "" if res.capture.passed else str(res.capture.retake_reason),
        "dims": dims,
        "missed": missed,
        "extra_holes": extra,
    }


def held_out(row: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [d for d in row["dims"] if not d.get("set_by_construction")]


def _stats(rows: Sequence[Mapping[str, Any]], key: str = "error_mm") -> dict[str, Any]:
    groups = [[abs(float(d[key])) for d in held_out(r) if key in d] for r in rows]
    errs = [float(d[key]) for r in rows for d in held_out(r) if key in d]
    if not errs:
        return {"n_dims": 0}
    st = error_stats(errs)
    lo, hi = cluster_bootstrap_mean(groups)
    return {
        "n_dims": st.n,
        "mean_abs_mm": round(st.mean_mm, 3),
        "ci95_mm": [round(lo, 3), round(hi, 3)],
        "median_abs_mm": round(st.median_mm, 3),
        "p90_abs_mm": round(st.p90_mm, 3),
        "max_abs_mm": round(st.max_mm, 3),
        "bias_mm": round(st.signed_mean_mm, 3),
        "within_0_5": sum(abs(e) <= 0.5 for e in errs),
    }


def summarise(rows: Sequence[Mapping[str, Any]], selection: Mapping[str, Any]) -> dict[str, Any]:
    accepted = [r for r in rows if r["accepted"]]
    gate = rate(len(accepted), len(rows))
    passed = sum(
        bool(held_out(r)) and all(abs(d["error_mm"]) <= 0.5 for d in held_out(r)) and not r["missed"] for r in accepted
    )
    p5 = rate(passed, len(accepted))
    objects = sorted({str(r["object"]) for r in rows})
    return {
        "n_photos": len(rows),
        "objects": {o: sum(r["object"] == o for r in rows) for o in objects},
        "n_source_photos": len({r["photo_id"] for r in rows}),
        "capture_gate_passed": len(accepted),
        "capture_gate_ci95": [round(gate.ci95[0], 3), round(gate.ci95[1], 3)],
        "held_out": _stats(accepted),
        "cutout_only": _stats(accepted, "cutout_error_mm"),
        "pass_at_0_5": passed,
        "pass_at_0_5_of": len(accepted),
        "pass_at_0_5_ci95": [round(p5.ci95[0], 3), round(p5.ci95[1], 3)],
        "by_object": {o: _stats([r for r in accepted if r["object"] == o]) for o in objects},
        "candidates_rejected": len(selection.get("rejected") or []),
    }


def to_markdown(rep: Mapping[str, Any]) -> str:
    s = rep["summary"]
    h = s["held_out"]
    L = ["# Public photos: measure only (no model)", "", rep["scope"], ""]
    if h.get("n_dims"):
        L += [
            f"{s['n_photos']} composites from {s['n_source_photos']} public photographs; capture gate passed "
            f"{s['capture_gate_passed']}/{s['n_photos']}. Held-out dimensions on accepted photos: mean abs error "
            f"**{h['mean_abs_mm']} mm** (95 % CI {h['ci95_mm'][0]} to {h['ci95_mm'][1]}, bootstrap over samples), median "
            f"{h['median_abs_mm']}, max {h['max_abs_mm']}, n = {h['n_dims']}; every held-out dimension within 0.5 mm on "
            f"{s['pass_at_0_5']}/{s['pass_at_0_5_of']} photos.",
            "",
            "| object | photos | held-out dims | mean abs mm | max abs mm | within 0.5 mm |",
            "|---|---:|---:|---:|---:|---:|",
        ]
        for o, st in s["by_object"].items():
            L.append(
                f"| {o} | {s['objects'][o]} | {st.get('n_dims', 0)} | {st.get('mean_abs_mm', '-')} | "
                f"{st.get('max_abs_mm', '-')} | {st.get('within_0_5', '-')} |"
            )
        c = s["cutout_only"]
        if c.get("n_dims"):
            L += [
                "",
                f"Read straight from the cut-out, before the mat: mean abs {c['mean_abs_mm']} mm (n = {c['n_dims']}).",
            ]
    L += [
        "",
        "| sample | object | gate | dimension | published mm | measured mm | error mm | counted |",
        "|---|---|---|---|---:|---:|---:|---|",
    ]
    for r in rep["rows"]:
        for d in r["dims"] or [{}]:
            counted = "no: set by construction" if d.get("set_by_construction") else "yes"
            L.append(
                f"| {r['sample_id']} | {r['object']} | {'pass' if r['accepted'] else 'refused'} | {d.get('name', '-')} | "
                f"{d.get('gt_mm', '-')} | {d.get('measured_mm', '-')} | {d.get('error_mm', '-')} | {counted if d else '-'} |"
            )
    fails = [r for r in rep["rows"] if not r["accepted"] or r["missed"]]
    if fails:
        L += ["", "Failures:"] + [
            f"- {r['sample_id']}: {r['reason'] or 'missed ' + ', '.join(r['missed'])}" for r in fails
        ]
    return "\n".join(L) + "\n"


def build_report() -> dict[str, Any]:
    defs = PP.load_manifest()
    PP.ensure_samples(defs)
    rows = [measure_sample(PP.SAMPLES / d.id) for d in defs]
    selection = yaml.safe_load(PP.MANIFEST.read_text()) or {}
    return {
        "generated_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "source": "public_photo",
        "ground_truth": "published spec, pasted at known size",
        "segmenter": "threshold (no model)",
        "scope": SCOPE,
        "counts_as_real_photos_measured": 0,
        "summary": summarise(rows, selection),
        "rejected": selection.get("rejected") or [],
        "rows": rows,
    }


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m eval.public_photos", description=__doc__.split("\n\n")[0])
    ap.add_argument("--out", type=Path, default=REPORT_DIR)
    a = ap.parse_args(argv)
    rep = build_report()
    a.out.mkdir(parents=True, exist_ok=True)
    (a.out / "public_photos_measure.json").write_text(json.dumps(rep, indent=1) + "\n")
    (a.out / "public_photos_measure.md").write_text(to_markdown(rep))
    s = rep["summary"]
    print(f"public_photos measure-only: gate {s['capture_gate_passed']}/{s['n_photos']}, held-out {s['held_out']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
