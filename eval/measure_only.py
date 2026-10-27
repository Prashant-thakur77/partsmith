"""Phase 1 gate bench: photo → millimetres only (no agent, no model, no keys).

Runs `services.metrology.measure.measure_photo` with the deterministic `ThresholdSegmenter` on

(a) the SYNTHETIC bench (`data/synthetic/bench`, generated from a seed if missing; exact ground truth),
(b) reference objects vs their published specs: synthetic renders now, real photos from
    `data/real/reference_objects/<object>/*.jpg` when they exist (reported separately, never merged),
(c) real parts with `data/real/<part>/gt.yaml` (`gt_source: ruler`, ±0.5 mm) — "pending" while there are none.

Measured dimensions are matched to ground truth by name (length, width, side-view thickness) and holes by nearest
centre (synthetic) or nearest diameter (ruler GT has no centres). Writes `eval/reports/<date>/measure_only.{json,md}`
with N, confidence intervals and the ground-truth source on every table, plus a failure list. The exit gate (mean abs
error ≤ 0.4 mm on the synthetic bench and on the reference objects) is printed as PASS/FAIL.

    uv run python -m eval.measure_only            # n=60 synthetic + 20 reference renders
    uv run python -m eval.measure_only --n 200 --jobs 8
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import os
import sys
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import yaml
from partsmith_schemas.common import DataOrigin
from partsmith_schemas.measurement import Measurements
from scipy.optimize import linear_sum_assignment

from .metrics import error_stats, pass_at, rate

REPO = Path(__file__).resolve().parents[1]
BENCH_DIR = REPO / "data" / "synthetic" / "bench"
BENCH_MANIFEST = REPO / "data" / "synthetic" / "bench_manifest.json"
REAL_DIR = REPO / "data" / "real"
REPORTS_DIR = REPO / "eval" / "reports"
GATE_MEAN_MM = 0.4
DEFAULT_SEED = 7

SRC_SYNTH = "synthetic"
SRC_REF_SYNTH = "reference_objects_synthetic"
SRC_REF_REAL = "reference_objects_real"
SRC_REAL = "real_parts_ruler"
GT_SOURCE_LABEL = {
    SRC_SYNTH: "synthetic_exact (template mesh, exact)",
    SRC_REF_SYNTH: "reference_spec (published spec; synthetic render of the nominal model)",
    SRC_REF_REAL: "reference_spec (published spec; real photos)",
    SRC_REAL: "ruler (±0.5 mm)",
}


@dataclass
class DimRow:
    source: str
    sample_id: str
    view: str
    dim: str
    gt_mm: float
    measured_mm: float
    error_mm: float
    accepted: bool  # the capture gate passed (a real user would not have been asked to retake)
    preset: str = ""
    group: str = ""  # family / reference object / part id
    mat_id: str = ""
    tol_mm: float | None = None  # spec tolerance (reference objects) or ruler uncertainty
    range_error_mm: float | None = None  # loose specs: distance to the accepted range
    within_spec: bool | None = None
    profile: str = ""  # synthetic templates: "flat" or "tall features" (see `profile_of`)


@dataclass
class PhotoRow:
    source: str
    sample_id: str
    view: str
    preset: str
    group: str
    detected: bool  # mat found and a part measured
    accepted: bool
    retake_reason: str | None
    n_gt_dims: int
    n_scored: int
    missed: list[str] = field(default_factory=list)
    extra_holes: int = 0
    seconds: float = 0.0
    notes: list[str] = field(default_factory=list)


@dataclass
class PhotoJob:
    source: str
    sample_id: str
    view: str
    image_path: str
    thickness_mm: float | None
    gt: list[dict[str, Any]]  # [{"name", "value_mm", "center_mat_mm"?, "tol_mm"?, "lo_mm"?, "hi_mm"?}]
    preset: str = ""
    group: str = ""
    mat_id: str | None = None
    origin: str = "synthetic"
    match_holes_by: str = "centre"  # or "diameter"
    side_of: str | None = None  # for side views: chain thickness from this sample's top-view width
    profile: str = ""


# ---------------------------------------------------------------- scoring (pure)


def hole_centres_mat(meas: Measurements) -> list[tuple[float, float]]:
    M = np.array(meas.part_to_mat, dtype=np.float64) if meas.part_to_mat else np.eye(3)
    out: list[tuple[float, float]] = []
    for h in meas.holes:
        c = M[:2, :2] @ np.array(h.center_mm, dtype=np.float64) + M[:2, 2]
        out.append((float(c[0]), float(c[1])))
    return out


def match_holes(
    gt: Sequence[Mapping[str, Any]], measured: Sequence[tuple[float, tuple[float, float]]], by: str = "centre"
) -> tuple[list[tuple[int, int]], list[int], list[int]]:
    """Assign measured holes (diameter, mat centre) to GT holes. Centre mode: Hungarian on centre distance, a pair
    counts only within max(2 mm, 0.6 × GT Ø). Diameter mode: Hungarian on |ΔØ| (ruler GT has no centres), pairs
    within 2 mm. Returns (pairs gt_i→meas_j, unmatched GT indices, unmatched measured indices)."""
    if not gt or not measured:
        return [], list(range(len(gt))), list(range(len(measured)))
    C = np.zeros((len(gt), len(measured)))
    gate = np.zeros_like(C)
    for i, g in enumerate(gt):
        for j, (d, c) in enumerate(measured):
            if by == "centre" and g.get("center_mat_mm") is not None:
                gc = g["center_mat_mm"]
                C[i, j] = math.hypot(c[0] - gc[0], c[1] - gc[1])
                gate[i, j] = max(2.0, 0.6 * float(g["value_mm"]))
            else:
                C[i, j] = abs(d - float(g["value_mm"]))
                gate[i, j] = 2.0
    ri, ci = linear_sum_assignment(C)
    pairs = [(int(i), int(j)) for i, j in zip(ri, ci, strict=True) if C[i, j] <= gate[i, j]]
    mg = {i for i, _ in pairs}
    mm = {j for _, j in pairs}
    return pairs, [i for i in range(len(gt)) if i not in mg], [j for j in range(len(measured)) if j not in mm]


def score_measurements(
    meas: Measurements | None, gt: Sequence[Mapping[str, Any]], view: str, match_holes_by: str = "centre"
) -> tuple[list[tuple[Mapping[str, Any], float]], list[str], int]:
    """(GT entry, measured value) pairs, names of GT dims that could not be measured, count of extra holes."""
    if meas is None:
        return [], [str(g["name"]) for g in gt], 0
    pairs: list[tuple[Mapping[str, Any], float]] = []
    missed: list[str] = []
    holes_gt = [g for g in gt if str(g["name"]).startswith("hole_")]
    for g in gt:
        name = str(g["name"])
        if name.startswith("hole_"):
            continue
        val: float | None = None
        if name == "length":
            val = meas.length.value
        elif name == "width":
            val = meas.width.value
        elif name == "thickness" and view == "side" and meas.thickness is not None:
            val = meas.thickness.value
        if val is None:
            missed.append(name)
        else:
            pairs.append((g, float(val)))
    centres = hole_centres_mat(meas)
    measured = [(h.diameter.value, c) for h, c in zip(meas.holes, centres, strict=True)]
    hp, miss_i, extra_j = match_holes(holes_gt, measured, match_holes_by)
    for i, j in hp:
        pairs.append((holes_gt[i], float(measured[j][0])))
    missed += [str(holes_gt[i]["name"]) for i in miss_i]
    return pairs, missed, len(extra_j)


# ---------------------------------------------------------------- running one photo


def _segmenter() -> Any:
    from services.metrology.segment import ThresholdSegmenter

    return ThresholdSegmenter()


def run_photo(job: PhotoJob) -> tuple[PhotoRow, list[DimRow], float | None]:
    """Measure one photo and score it. Returns (photo row, dim rows, measured top-view width for chaining)."""
    from services.metrology.measure import measure_photo

    t0 = time.perf_counter()
    data = Path(job.image_path).read_bytes()
    try:
        out = measure_photo(
            data,
            job.view,
            segmenter=_segmenter(),
            thickness_mm=job.thickness_mm,
            origin=DataOrigin(job.origin),
            mat_id=job.mat_id,
        )
    except Exception as e:  # a crash is a failure to report, not a reason to stop the bench
        row = PhotoRow(
            job.source,
            job.sample_id,
            job.view,
            job.preset,
            job.group,
            False,
            False,
            f"measure_photo raised {type(e).__name__}: {e}",
            len(job.gt),
            0,
            [str(g["name"]) for g in job.gt],
        )
        return row, [], None
    res = out.result
    meas = res.measurements
    accepted = bool(res.capture.passed) and meas is not None
    pairs, missed, extra = score_measurements(meas, job.gt, job.view, job.match_holes_by)
    dims: list[DimRow] = []
    for g, val in pairs:
        gt_v = float(g["value_mm"])
        lo, hi = g.get("lo_mm"), g.get("hi_mm")
        rng_err = None if lo is None or hi is None else max(float(lo) - val, 0.0, val - float(hi))
        dims.append(
            DimRow(
                source=job.source,
                sample_id=job.sample_id,
                view=job.view,
                dim=str(g["name"]),
                gt_mm=gt_v,
                measured_mm=round(val, 4),
                error_mm=round(val - gt_v, 4),
                accepted=accepted,
                preset=job.preset,
                group=job.group,
                mat_id=(res.calibration.mat_id if res.calibration else job.mat_id or ""),
                tol_mm=g.get("tol_mm"),
                range_error_mm=None if rng_err is None else round(rng_err, 4),
                within_spec=None if lo is None or hi is None else bool(float(lo) <= val <= float(hi)),
                profile=job.profile,
            )
        )
    row = PhotoRow(
        source=job.source,
        sample_id=job.sample_id,
        view=job.view,
        preset=job.preset,
        group=job.group,
        detected=meas is not None,
        accepted=accepted,
        retake_reason=res.capture.retake_reason if not res.capture.passed else None,
        n_gt_dims=len(job.gt),
        n_scored=len(pairs),
        missed=missed,
        extra_holes=extra,
        seconds=round(time.perf_counter() - t0, 2),
        notes=[n for n in out.notes if "intrinsics" in n or "segmentation" in n][:2],
    )
    width = meas.width.value if (meas is not None and job.view == "top") else None
    return row, dims, width


# ---------------------------------------------------------------- job collection


def synthetic_jobs(root: Path, manifest: Mapping[str, Any] | None = None) -> tuple[list[PhotoJob], list[PhotoJob]]:
    """(top jobs, side jobs) for every sample in the bench. Template samples score vs exact GT; reference-object
    renders score vs the published spec."""
    from tools.synth import load_gt, load_sample
    from tools.synth.reference_objects import get_reference_object

    ids = [e["id"] for e in manifest["samples"]] if manifest else None
    tops: list[PhotoJob] = []
    sides: list[PhotoJob] = []
    from tools.synth import list_samples

    for m in list_samples(root):
        if ids is not None and m.id not in ids:
            continue
        assert m.path is not None
        s = load_sample(m.path)
        gt = load_gt(m.path)
        preset = m.augmentations[0] if m.augmentations else ""
        if m.kind == "reference_object":
            ref = get_reference_object(gt.name)
            src, group, profile = SRC_REF_SYNTH, ref.key, ""
            by_view = {
                v: [
                    {"name": d.name, "value_mm": d.nominal_mm, "tol_mm": d.tol_mm, "lo_mm": d.lo_mm, "hi_mm": d.hi_mm}
                    for d in ref.dims_for(v)
                ]
                for v in ("top", "side")
            }
        else:
            src, group = SRC_SYNTH, m.family_hint
            profile = profile_of(float(gt.raw.get("info", {}).get("height_mm", 0.0)), m.user_thickness_mm)
            by_view = {
                v: [{"name": d.name, "value_mm": d.value_mm, "center_mat_mm": d.center_mat_mm} for d in gt.dims_for(v)]
                for v in ("top", "side")
            }

        tops.append(
            PhotoJob(
                src,
                m.id,
                "top",
                str(m.path / "top.jpg"),
                m.user_thickness_mm,
                by_view["top"],
                preset,
                group,
                None,
                "synthetic",
                profile=profile,
            )
        )
        if "side" in s.photos:
            side_gt = by_view["side"]
            if side_gt:
                sides.append(
                    PhotoJob(
                        src,
                        m.id,
                        "side",
                        str(m.path / "side.jpg"),
                        None,
                        side_gt,
                        preset,
                        group,
                        None,
                        "synthetic",
                        side_of=m.id,
                        profile=profile,
                    )
                )
    return tops, sides


TALL_MARGIN_MM = 1.0


def profile_of(height_mm: float, stated_thickness_mm: float | None) -> str:
    """ "flat" when all material is within the user-stated thickness (+1 mm), so the photo's outline lies at the
    stated height; "tall features" otherwise (arms, uprights, knuckles above the plate: their edges sit higher and
    the prism height correction does not cover them)."""
    if stated_thickness_mm is None:
        return "unknown height"
    return "flat" if height_mm <= stated_thickness_mm + TALL_MARGIN_MM else "tall features"


def real_reference_jobs(real_dir: Path) -> list[PhotoJob]:
    """Real photos of reference objects: data/real/reference_objects/<object>/*.jpg ('side' in the file name = side
    view). Scored vs the published spec."""
    from tools.synth.reference_objects import REFERENCE_OBJECTS

    jobs: list[PhotoJob] = []
    base = real_dir / "reference_objects"
    if not base.exists():
        return jobs
    for key, ref in REFERENCE_OBJECTS.items():
        d = base / key
        if not d.exists():
            continue
        for p in sorted(list(d.glob("*.jpg")) + list(d.glob("*.jpeg")) + list(d.glob("*.JPG"))):
            view = "side" if "side" in p.stem.lower() else "top"
            gt = [
                {"name": s.name, "value_mm": s.nominal_mm, "tol_mm": s.tol_mm, "lo_mm": s.lo_mm, "hi_mm": s.hi_mm}
                for s in ref.dims_for(view)  # type: ignore[arg-type]
            ]
            if not gt:
                continue
            thick = ref.user_thickness_mm if view == "top" else ref.dim("width").nominal_mm
            jobs.append(
                PhotoJob(
                    SRC_REF_REAL, f"{key}/{p.name}", view, str(p), thick, gt, "real", key, None, "reference_object"
                )
            )
    return jobs


def real_part_jobs(real_dir: Path) -> list[PhotoJob]:
    """Real parts with ruler ground truth: data/real/<part>/gt.yaml with gt_source: ruler (see eval/REPRODUCE.md)."""
    jobs: list[PhotoJob] = []
    if not real_dir.exists():
        return jobs
    for gt_p in sorted(real_dir.glob("*/gt.yaml")):
        part = gt_p.parent
        if part.name == "reference_objects":
            continue
        raw = yaml.safe_load(gt_p.read_text()) or {}
        if str(raw.get("gt_source", raw.get("source", ""))) != "ruler":
            continue
        dims = raw.get("dims") or {}
        unc = float(raw.get("uncertainty_mm", 0.5))
        thick = raw.get("user_thickness_mm", dims.get("thickness"))
        top_gt: list[dict[str, Any]] = [
            {"name": k, "value_mm": float(dims[k]), "tol_mm": unc} for k in ("length", "width") if k in dims
        ]
        for i, h in enumerate(raw.get("holes") or []):
            top_gt.append({"name": f"hole_{i + 1}.diameter", "value_mm": float(h["diameter"]), "tol_mm": unc})
        if (part / "top.jpg").exists() and top_gt:
            jobs.append(
                PhotoJob(
                    SRC_REAL,
                    part.name,
                    "top",
                    str(part / "top.jpg"),
                    None if thick is None else float(thick),
                    top_gt,
                    "real",
                    part.name,
                    raw.get("mat_id"),
                    "real",
                    "diameter",
                )
            )
        if (part / "side.jpg").exists() and "thickness" in dims:
            jobs.append(
                PhotoJob(
                    SRC_REAL,
                    part.name,
                    "side",
                    str(part / "side.jpg"),
                    None,
                    [{"name": "thickness", "value_mm": float(dims["thickness"]), "tol_mm": unc}],
                    "real",
                    part.name,
                    raw.get("mat_id"),
                    "real",
                    side_of=part.name,
                )
            )
    return jobs


# ---------------------------------------------------------------- bench data


def ensure_bench(root: Path, *, n: int, n_reference: int, seed: int, jobs: int, regen: bool = False) -> dict[str, Any]:
    """Generate the synthetic bench if it is missing or was made with different settings; return its manifest."""
    from tools.synth import make_dataset

    mpath = root / "manifest.json"
    if mpath.exists() and not regen:
        man: dict[str, Any] = json.loads(mpath.read_text())
        if man.get("seed") == seed and man.get("n") == n and man.get("n_reference") == n_reference:
            missing = [e["id"] for e in man["samples"] if not (root / e["id"] / "gt.yaml").exists()]
            if not missing:
                return man
    print(f"generating synthetic bench: n={n} + {n_reference} reference renders, seed={seed} -> {root}", flush=True)
    return make_dataset(root, n=n, n_reference=n_reference, seed=seed, jobs=jobs, progress=True)


def bench_manifest_summary(man: Mapping[str, Any]) -> dict[str, Any]:
    """What gets committed: settings + per-sample seeds and hashes (the images themselves are gitignored)."""
    return {
        "origin": "synthetic",
        "note": "SYNTHETIC bench; regenerate with: uv run python -m tools.synth --out data/synthetic/bench "
        f"--n {man['n']} --n-reference {man['n_reference']} --seed {man['seed']}",
        **{k: man[k] for k in ("generator", "seed", "n", "n_reference", "presets", "size", "jpeg_quality")},
        "dataset_sha256": man["dataset_sha256"],
        "samples": [
            {"id": e["id"], "seed": e["seed"], "kind": e["kind"], "preset": e["preset"], "files": e["files"]}
            for e in man["samples"]
        ],
        "failures": man.get("failures", []),
    }


# ---------------------------------------------------------------- run


def _run_all(jobs_list: Sequence[PhotoJob], n_jobs: int) -> list[tuple[PhotoRow, list[DimRow], float | None]]:
    if n_jobs <= 1 or len(jobs_list) <= 1:
        return [run_photo(j) for j in jobs_list]
    with ProcessPoolExecutor(max_workers=n_jobs) as ex:
        return list(ex.map(run_photo, jobs_list, chunksize=1))


def run_bench(
    *,
    bench_dir: Path = BENCH_DIR,
    real_dir: Path = REAL_DIR,
    n: int = 60,
    n_reference: int = 20,
    seed: int = DEFAULT_SEED,
    jobs: int = 4,
    regen: bool = False,
    write_manifest: Path | None = BENCH_MANIFEST,
    log: Callable[[str], None] = print,
) -> dict[str, Any]:
    """Run every source and return the report dict (not yet written)."""
    t0 = time.perf_counter()
    man = ensure_bench(bench_dir, n=n, n_reference=n_reference, seed=seed, jobs=jobs, regen=regen)
    if write_manifest is not None:
        write_manifest.parent.mkdir(parents=True, exist_ok=True)
        write_manifest.write_text(json.dumps(bench_manifest_summary(man), indent=1) + "\n")
    s_tops, s_sides = synthetic_jobs(bench_dir, man)
    r_jobs = real_reference_jobs(real_dir)
    p_jobs = real_part_jobs(real_dir)
    tops = s_tops + [j for j in r_jobs + p_jobs if j.view == "top"]
    sides = s_sides + [j for j in r_jobs + p_jobs if j.view == "side"]
    log(f"measuring {len(tops)} top + {len(sides)} side photos with {jobs} worker(s)")
    results = _run_all(tops, jobs)
    width_of = {(r.source, r.sample_id): w for r, _, w in results}
    for j in sides:  # side views: the top face is the part's width as measured in the top view
        if j.side_of is not None and j.thickness_mm is None:
            j.thickness_mm = width_of.get((j.source, j.side_of))
    results += _run_all(sides, jobs)
    photos = [r for r, _, _ in results]
    dims = [d for _, ds, _ in results for d in ds]
    report = build_report(photos, dims, man, seed=seed)
    report["runtime_s"] = round(time.perf_counter() - t0, 1)
    return report


def _stats(errs: Iterable[float], seed: int) -> dict[str, Any]:
    return error_stats(list(errs), seed=seed).to_dict()


def _section(source: str, photos: list[PhotoRow], dims: list[DimRow], seed: int) -> dict[str, Any]:
    ph = [p for p in photos if p.source == source]
    dm = [d for d in dims if d.source == source]
    acc = [d for d in dm if d.accepted]
    out: dict[str, Any] = {
        "gt_source": GT_SOURCE_LABEL[source],
        "n_photos": len(ph),
        "n_detected": sum(p.detected for p in ph),
        "capture_gate_pass": rate(sum(p.accepted for p in ph), len(ph)).to_dict(),
        "accepted": _stats((d.error_mm for d in acc), seed),
        "all_detected": _stats((d.error_mm for d in dm), seed),
    }
    if source in (SRC_REF_SYNTH, SRC_REF_REAL, SRC_REAL):
        ws = [d for d in acc if d.within_spec is not None]
        out["within_spec_accepted"] = rate(sum(bool(d.within_spec) for d in ws), len(ws)).to_dict()
        rng_e = [d.range_error_mm for d in acc if d.range_error_mm is not None]
        out["range_error_accepted"] = _stats(rng_e, seed)
    per_photo: dict[tuple[str, str], list[float]] = {}
    for d in acc:
        per_photo.setdefault((d.sample_id, d.view), []).append(abs(d.error_mm))
    complete = [
        per_photo.get((p.sample_id, p.view), [])
        for p in ph
        if p.accepted and not p.missed and p.n_scored == p.n_gt_dims
    ]
    incomplete = sum(1 for p in ph if p.accepted and (p.missed or p.n_scored != p.n_gt_dims))
    for tol in (0.3, 0.5):
        r = pass_at(complete + [[math.inf]] * incomplete, tol)
        out[f"pass_at_{tol}"] = r.to_dict()

    def by(key: Callable[[DimRow], str]) -> dict[str, Any]:
        groups: dict[str, list[float]] = {}
        for d in acc:
            groups.setdefault(key(d), []).append(d.error_mm)
        return {k: _stats(v, seed) for k, v in sorted(groups.items())}

    out["by_dim"] = by(lambda d: "hole Ø" if d.dim.startswith("hole_") else f"{d.view}:{d.dim}")
    out["by_preset"] = by(lambda d: d.preset)
    out["by_group"] = by(lambda d: d.group)
    out["by_mat"] = by(lambda d: d.mat_id)
    if source == SRC_SYNTH:
        out["by_profile"] = by(lambda d: f"{d.view}: {d.profile}")
    return out


def build_report(
    photos: list[PhotoRow], dims: list[DimRow], manifest: Mapping[str, Any] | None, *, seed: int
) -> dict[str, Any]:
    sections = {s: _section(s, photos, dims, seed) for s in (SRC_SYNTH, SRC_REF_SYNTH, SRC_REF_REAL, SRC_REAL)}
    failures = [
        {
            "source": p.source,
            "sample_id": p.sample_id,
            "view": p.view,
            "preset": p.preset,
            "reason": ("mat or part not detected" if not p.detected else "capture gate failed")
            + (f": {p.retake_reason}" if p.retake_reason else ""),
            "missed": p.missed,
        }
        for p in photos
        if not p.accepted
    ] + [
        {
            "source": p.source,
            "sample_id": p.sample_id,
            "view": p.view,
            "preset": p.preset,
            "reason": "dimension(s) not measured" + (f"; {p.extra_holes} spurious hole(s)" if p.extra_holes else ""),
            "missed": p.missed,
        }
        for p in photos
        if p.accepted and (p.missed or p.extra_holes)
    ]
    gate = gate_verdict(sections)
    return {
        "bench": "measure_only",
        "date": dt.date.today().isoformat(),
        "segmenter": "ThresholdSegmenter (deterministic, no model)",
        "gate_threshold_mean_mm": GATE_MEAN_MM,
        "synthetic_manifest": {k: manifest[k] for k in ("seed", "n", "n_reference", "dataset_sha256")}
        if manifest
        else None,
        "sections": sections,
        "gate": gate,
        "failures": failures,
        "photos": [asdict(p) for p in photos],
        "dims": [asdict(d) for d in dims],
    }


def gate_verdict(sections: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    """PASS iff the accepted-photo mean abs error ≤ 0.4 mm on the synthetic bench AND on the reference objects (real
    photos when there are any, else the synthetic renders — the report says which)."""
    syn = sections[SRC_SYNTH]["accepted"]
    ref_src = SRC_REF_REAL if sections[SRC_REF_REAL]["accepted"]["n"] else SRC_REF_SYNTH
    ref = sections[ref_src]["accepted"]

    def ok(s: Mapping[str, Any]) -> bool:
        return bool(s["n"]) and float(s["mean_mm"]) <= GATE_MEAN_MM

    return {
        "synthetic": {"mean_mm": syn["mean_mm"], "n": syn["n"], "pass": ok(syn)},
        "reference_objects": {"source": ref_src, "mean_mm": ref["mean_mm"], "n": ref["n"], "pass": ok(ref)},
        "pass": ok(syn) and ok(ref),
    }


# ---------------------------------------------------------------- markdown


def _f(x: Any, nd: int = 3) -> str:
    if x is None or (isinstance(x, float) and not math.isfinite(x)):
        return "–"
    return f"{x:.{nd}f}"


def _ci(c: Sequence[float], nd: int = 3) -> str:
    return f"[{_f(c[0], nd)}, {_f(c[1], nd)}]"


def _pct(x: float) -> str:
    return "–" if not math.isfinite(x) else f"{100 * x:.0f} %"


def _err_table(title: str, rows: Mapping[str, Mapping[str, Any]]) -> list[str]:
    out = [
        f"| {title} | N | mean abs [95 % CI] | median | P90 | max | ≤0.3 mm | ≤0.5 mm | bias |",
        "|---|---:|---|---:|---:|---:|---:|---:|---:|",
    ]
    for k, s in rows.items():
        if not s["n"]:
            continue
        out.append(
            f"| {k} | {s['n']} | {_f(s['mean_mm'])} {_ci(s['mean_ci95_mm'])} | {_f(s['median_mm'])} | "
            f"{_f(s['p90_mm'])} | {_f(s['max_mm'])} | {_pct(s['within_0_3'])} | {_pct(s['within_0_5'])} | "
            f"{_f(s['signed_mean_mm'])} |"
        )
    return out


def to_markdown(rep: Mapping[str, Any]) -> str:
    L: list[str] = [f"# measure_only bench — {rep['date']}", ""]
    L.append(
        "Photo → millimetres only: `measure_photo` with the deterministic threshold segmenter (no model, no keys). "
        "Errors are |measured − ground truth| in mm. **Accepted** = photos that passed the capture gate (the app "
        "asks for a retake otherwise); rejected photos are listed under failures. Sources are never merged."
    )
    if rep.get("synthetic_manifest"):
        m = rep["synthetic_manifest"]
        L.append("")
        L.append(
            f"Synthetic bench: seed {m['seed']}, n = {m['n']} template samples + {m['n_reference']} "
            f"reference-object renders, dataset sha256 `{m['dataset_sha256'][:16]}…`. All synthetic."
        )
    g = rep["gate"]
    L += ["", "## Phase 1 exit gate (mean abs error ≤ 0.4 mm, accepted photos)", ""]
    L.append(
        f"- synthetic bench: mean {_f(g['synthetic']['mean_mm'])} mm over N = {g['synthetic']['n']} dims → "
        f"**{'PASS' if g['synthetic']['pass'] else 'FAIL'}**"
    )
    r = g["reference_objects"]
    L.append(
        f"- reference objects ({GT_SOURCE_LABEL[r['source']]}): mean {_f(r['mean_mm'])} mm over N = {r['n']} "
        f"dims → **{'PASS' if r['pass'] else 'FAIL'}**"
    )
    L.append(f"- overall: **{'PASS' if g['pass'] else 'FAIL'}**")
    for key, sec in rep["sections"].items():
        L += ["", f"## {key}", "", f"Ground truth: {sec['gt_source']}.", ""]
        if not sec["n_photos"]:
            L.append("**pending** — no photos with this ground truth yet.")
            continue
        cg = sec["capture_gate_pass"]
        L.append(
            f"Photos: {sec['n_photos']} (mat + part detected: {sec['n_detected']}; capture gate passed: "
            f"{cg['k']}/{cg['n']} = {_pct(cg['rate'])} {_ci(cg['ci95'], 2)})."
        )
        L.append("")
        L += _err_table("dims", {"accepted photos": sec["accepted"], "all detected photos": sec["all_detected"]})
        L.append("")
        for tol in (0.3, 0.5):
            p = sec[f"pass_at_{tol}"]
            L.append(
                f"- pass@{tol} mm (every named dim of an accepted photo within {tol} mm; a missed dim fails): "
                f"{p['k']}/{p['n']} = {_pct(p['rate'])} {_ci(p['ci95'], 2)}"
            )
        if "within_spec_accepted" in sec:
            w = sec["within_spec_accepted"]
            L.append(f"- inside the spec's accepted range: {w['k']}/{w['n']} = {_pct(w['rate'])} {_ci(w['ci95'], 2)}")
        for title, k in (
            ("by dimension", "by_dim"),
            ("by profile", "by_profile"),
            ("by preset", "by_preset"),
            ("by family / object", "by_group"),
            ("by mat", "by_mat"),
        ):
            if k in sec:
                L += ["", *_err_table(title, sec[k])]
    L += ["", "## Failures", ""]
    if not rep["failures"]:
        L.append("None.")
    else:
        L += ["| source | sample | view | preset | reason | missed |", "|---|---|---|---|---|---|"]
        for f in rep["failures"]:
            reason = str(f["reason"]).replace("|", "/")
            L.append(
                f"| {f['source']} | {f['sample_id']} | {f['view']} | {f['preset']} | {reason} | "
                f"{', '.join(f['missed'])} |"
            )
    L += ["", f"Runtime: {rep.get('runtime_s', '–')} s. Regenerate: `uv run python -m eval.measure_only`.", ""]
    return "\n".join(L)


def write_report(rep: Mapping[str, Any], out_dir: Path) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    jp, mp = out_dir / "measure_only.json", out_dir / "measure_only.md"
    jp.write_text(json.dumps(rep, indent=1, default=float) + "\n")
    mp.write_text(to_markdown(rep))
    return jp, mp


def summary_lines(rep: Mapping[str, Any]) -> list[str]:
    lines = []
    for key, sec in rep["sections"].items():
        s = sec["accepted"]
        if not sec["n_photos"]:
            lines.append(f"{key:32s} pending (no photos)")
            continue
        cg = sec["capture_gate_pass"]
        lines.append(
            f"{key:32s} photos {sec['n_photos']:3d} accepted {cg['k']:3d}  dims N={s['n']:3d}  "
            f"mean {_f(s['mean_mm'])} {_ci(s['mean_ci95_mm'])}  median {_f(s['median_mm'])}  P90 {_f(s['p90_mm'])}  "
            f"max {_f(s['max_mm'])}  ≤0.5 {_pct(s['within_0_5'])}"
        )
    g = rep["gate"]
    lines.append(
        f"EXIT GATE (mean ≤ {GATE_MEAN_MM} mm): synthetic {_f(g['synthetic']['mean_mm'])} "
        f"{'PASS' if g['synthetic']['pass'] else 'FAIL'} · reference objects [{g['reference_objects']['source']}] "
        f"{_f(g['reference_objects']['mean_mm'])} {'PASS' if g['reference_objects']['pass'] else 'FAIL'} → "
        f"{'PASS' if g['pass'] else 'FAIL'}"
    )
    return lines


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0] if __doc__ else None)
    ap.add_argument("--n", type=int, default=60, help="synthetic template samples (default 60)")
    ap.add_argument("--n-reference", type=int, default=20, help="synthetic reference-object renders (default 20)")
    ap.add_argument("--seed", type=int, default=DEFAULT_SEED)
    ap.add_argument("--bench", type=Path, default=BENCH_DIR)
    ap.add_argument("--real", type=Path, default=REAL_DIR)
    ap.add_argument("--out", type=Path, default=None, help="report dir (default eval/reports/<today>)")
    ap.add_argument("--jobs", type=int, default=min(4, os.cpu_count() or 1))
    ap.add_argument("--regen", action="store_true", help="re-render the synthetic bench")
    ap.add_argument("--strict", action="store_true", help="exit 1 when the gate fails")
    a = ap.parse_args(argv)
    rep = run_bench(
        bench_dir=a.bench, real_dir=a.real, n=a.n, n_reference=a.n_reference, seed=a.seed, jobs=a.jobs, regen=a.regen
    )
    out = a.out or REPORTS_DIR / rep["date"]
    jp, mp = write_report(rep, out)
    for line in summary_lines(rep):
        print(line)
    print(f"wrote {jp.relative_to(REPO) if jp.is_relative_to(REPO) else jp} and {mp.name}")
    return 1 if (a.strict and not rep["gate"]["pass"]) else 0


if __name__ == "__main__":
    sys.exit(main())
