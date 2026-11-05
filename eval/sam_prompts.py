"""Does naming the part's colour make SAM 3.1 answer, and do its masks measure as well as the threshold mask?

Written before the live run. Each photo goes through three paths with no threshold fallback in the two model paths:

- threshold: the deterministic segmenter;
- old ladder: "plastic part", "broken plastic piece";
- new ladder: "<colour> plastic part" first, colour read by code from the threshold mask, then the old ladder.

Recorded per photo: did a mask clear the score floor, its score and phrase, calls made, IoU with the threshold mask, IoU
with the renderer's exact mask where one exists (fresh renders), and each path's length, width and hole diameter errors
from `measure_photo` against ground truth.

Photos: data/synthetic/samples, suites/control, suites/redteam where a part is in frame, bench, data/public_photos, and
fresh renders with exact masks (new seed). All are rendered or pasted on a rendered mat, so this says nothing about real
phone photos.

Decision rule, fixed here: if the new ladder's masks are within 0.05 mm of the threshold masks on paired median absolute
error, SAM stays the measuring mask whenever it clears the floor. If they are worse, the threshold stays the measuring mask
and SAM becomes an independent cross-check whose disagreement is shown. Either way `mask_source` names what measured.

One run, no re-runs to improve a number; the spend is capped and photos past the cap are reported as skipped.

    uv run python -m eval.sam_prompts render      # fresh renders with exact masks into var/sam_prompts
    PROVIDER_MODE=live uv run python -m eval.sam_prompts run --max-usd 8
    uv run python -m eval.sam_prompts report      # eval/reports/latest/sam_prompts.json from the stored rows
"""

from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import threading
import time
from collections.abc import Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from functools import partial
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
WORK = REPO / "var" / "sam_prompts"
FRESH = WORK / "fresh"
ROWS = WORK / "rows.jsonl"
REPORT = REPO / "eval" / "reports" / "latest" / "sam_prompts.json"
FRESH_SEED = 20261107
N_FRESH = 14
PART_IN_FRAME = ("rt-flexible-object", "rt-hand-in-frame", "rt-organic-object", "rt-safety-part", "rt-two-parts")
PROMPT = "plastic part"
WITHIN_MM = 0.05


@dataclass
class Photo:
    suite: str
    id: str
    path: Path
    gt: list[dict[str, Any]] = field(default_factory=list)
    thickness_mm: float | None = None
    by: str = "centre"
    round_part: bool = False
    exact_mask: Path | None = None


class Budget:
    """Live SAM calls, cached by image and phrase so the two ladders share an identical call, stopped at a spend cap."""

    def __init__(self, segment: Any, usd_per_call: float, max_usd: float) -> None:
        self.segment = segment
        self.usd_per_call = usd_per_call
        self.max_usd = max_usd
        self.calls = 0
        self.lock = threading.Lock()
        self.cache: dict[tuple[str, str], Any] = {}

    @property
    def usd(self) -> float:
        return self.calls * self.usd_per_call

    def spent_out(self) -> bool:
        return self.usd >= self.max_usd

    def __call__(self, png: bytes, prompt: str) -> Any:
        key = (hashlib.sha256(png).hexdigest(), prompt)
        with self.lock:
            if key in self.cache:
                return self.cache[key]
            self.calls += 1
        out = self.segment(png, prompt)
        with self.lock:
            self.cache[key] = out
        return out


def errors_by_dim(meas: Any, gt: Sequence[Mapping[str, Any]], by: str) -> dict[str, float]:
    """Absolute error per ground-truth dimension that was measured; a dimension that set the paste scale never counts."""
    from .measure_only import score_measurements

    held = [g for g in gt if not g.get("set_by_construction")]
    pairs, _missed, _extra = score_measurements(meas, held, "top", by)
    return {str(g["name"]): round(abs(float(v) - float(g["value_mm"])), 4) for g, v in pairs}


def collect() -> list[Photo]:
    import yaml

    from .measure_only import synthetic_jobs

    photos: list[Photo] = []

    def from_jobs(root: Path, suite: str) -> None:
        tops, _sides = synthetic_jobs(root)
        for j in tops:
            exact = WORK / "masks" / f"{j.sample_id}.png" if suite == "fresh" else None
            photos.append(
                Photo(
                    suite,
                    j.sample_id,
                    Path(j.image_path),
                    list(j.gt),
                    j.thickness_mm,
                    j.match_holes_by,
                    j.shape == "round",
                    exact,
                )
            )

    from_jobs(REPO / "data/synthetic/samples", "samples")
    from_jobs(REPO / "data/synthetic/suites/control", "control")
    from_jobs(REPO / "data/synthetic/bench", "bench")
    if FRESH.exists():
        from_jobs(FRESH, "fresh")
    for case in PART_IN_FRAME:
        photos.append(Photo("redteam", case, REPO / "data/synthetic/suites/redteam" / case / "top.jpg"))
    for folder in sorted((REPO / "data/public_photos/samples").iterdir()):
        if (folder / "top.jpg").exists():
            gt = yaml.safe_load((folder / "gt.yaml").read_text())
            meta = json.loads((folder / "meta.json").read_text())
            photos.append(
                Photo(
                    "public",
                    folder.name,
                    folder / "top.jpg",
                    list(gt["dims"]),
                    float(meta["user_thickness_mm"]),
                    "diameter",
                )
            )
    return photos


class Fixed:
    """A segmenter that returns a mask already computed, so `measure_photo` measures exactly that mask."""

    def __init__(self, result: Any) -> None:
        self.result = result

    def segment(self, img: Any, prompt: str = PROMPT, *, context: Any = None) -> Any:
        return self.result


def measured(photo: Photo, data: bytes, seg: Any) -> dict[str, Any]:
    from partsmith_schemas import DataOrigin

    from services.metrology.measure import measure_photo

    res = measure_photo(
        data, "top", segmenter=Fixed(seg), thickness_mm=photo.thickness_mm, origin=DataOrigin.synthetic,
        profile="round" if photo.round_part else "prism",
    ).result  # fmt: skip
    meas = res.measurements
    return {
        "accepted": bool(res.capture.passed) and meas is not None,
        "errors": errors_by_dim(meas, photo.gt, photo.by) if meas is not None else {},
        "failed_checks": [c.name for c in res.capture.checks if c.severity == "fail"],
    }


def ladder_row(
    photo: Photo, data: bytes, img: Any, ctx: Any, call: Budget, thr: Any, exact: Any, coloured: bool
) -> dict[str, Any]:
    from services.metrology.segment import ProviderSegmenter, mask_iou

    t0 = time.perf_counter()
    res = ProviderSegmenter(call=call, fallback=None, colour_prompt=coloured).segment(img, PROMPT, context=ctx)
    row: dict[str, Any] = {
        "mask": bool(res.mask.any()),
        "score": round(float(res.score), 4),
        "phrase": res.prompt,
        "attempts": res.attempts,
        "seconds": round(time.perf_counter() - t0, 1),
    }
    if res.mask.any():
        row["iou_threshold"] = round(float(mask_iou(res.mask, thr.mask)), 4) if thr.mask.any() else None
        if exact is not None:
            row["iou_exact"] = round(float(mask_iou(res.mask, exact)), 4)
        row.update(measured(photo, data, res))
    return row


def run_one(photo: Photo, call: Budget) -> dict[str, Any]:
    import cv2

    from services.metrology.calibrate import MatNotFoundError, detect_mat
    from services.metrology.measure import decode_image
    from services.metrology.segment import SegContext, ThresholdSegmenter, colour_word, mask_iou

    row: dict[str, Any] = {"suite": photo.suite, "id": photo.id}
    if call.spent_out():
        return {**row, "skipped": "spend cap reached"}
    data = photo.path.read_bytes()
    img = decode_image(data)
    try:
        ctx = SegContext(detect_mat(img))
    except MatNotFoundError as exc:
        return {**row, "skipped": f"no mat found: {exc}"[:120]}
    thr = ThresholdSegmenter().segment(img, PROMPT, context=ctx)
    exact = None
    if photo.exact_mask is not None and photo.exact_mask.exists():
        gray: Any = cv2.imread(str(photo.exact_mask), cv2.IMREAD_GRAYSCALE)
        exact = gray >= 128
    row["colour"] = colour_word(img, thr.mask)
    row["threshold"] = {"mask": bool(thr.mask.any()), **measured(photo, data, thr)}
    if exact is not None and thr.mask.any():
        row["threshold"]["iou_exact"] = round(float(mask_iou(thr.mask, exact)), 4)
    try:
        row["old"] = ladder_row(photo, data, img, ctx, call, thr, exact, False)
        row["new"] = ladder_row(photo, data, img, ctx, call, thr, exact, True)
    except Exception as exc:  # a failure is a result of this photo
        row["error"] = f"{type(exc).__name__}: {exc}"[:200]
    return row


def _rate(rows: Sequence[Mapping[str, Any]], path: str) -> dict[str, Any]:
    from .stats import wilson_ci

    n = len(rows)
    k = sum(bool(r.get(path, {}).get("mask")) for r in rows)
    lo, hi = wilson_ci(k, n) if n else (float("nan"), float("nan"))
    return {"k": k, "n": n, "rate": round(k / n, 4) if n else None, "ci95": [round(lo, 3), round(hi, 3)]}


def _median_ci(values: Sequence[float]) -> dict[str, Any]:
    from .stats import bootstrap_ci

    if not values:
        return {"n": 0, "median": None, "ci95": None}
    lo, hi = bootstrap_ci(values, lambda a: float(statistics.median(a.tolist())), seed=7)
    return {"n": len(values), "median": round(statistics.median(values), 4), "ci95": [round(lo, 4), round(hi, 4)]}


def paired_errors(
    rows: Sequence[Mapping[str, Any]], path: str, dims: tuple[str, ...]
) -> tuple[list[float], list[float]]:
    """(model path errors, threshold errors) on the dimensions both paths measured, photos both paths accepted."""
    a: list[float] = []
    b: list[float] = []
    for r in rows:
        model, thr = r.get(path, {}), r.get("threshold", {})
        if not (model.get("accepted") and thr.get("accepted")):
            continue
        for d, v in model.get("errors", {}).items():
            base = d.split("_")[0]
            if base in dims and d in thr.get("errors", {}):
                a.append(float(v))
                b.append(float(thr["errors"][d]))
    return a, b


def summarise(rows: Sequence[Mapping[str, Any]], usd: float | None = None) -> dict[str, Any]:
    from .stats import mcnemar_paired

    done = [r for r in rows if "new" in r and "old" in r]
    suites = sorted({str(r["suite"]) for r in done})
    by_suite = {
        s: {
            "old": _rate([r for r in done if r["suite"] == s], "old"),
            "new": _rate([r for r in done if r["suite"] == s], "new"),
        }
        for s in suites
    }
    b, c, p = (
        mcnemar_paired([bool(r["old"]["mask"]) for r in done], [bool(r["new"]["mask"]) for r in done])
        if done
        else (0, 0, 1.0)
    )
    measures: dict[str, Any] = {}
    for dims, name in ((("length", "width"), "length_width"), (("hole",), "hole_diameter")):
        for path in ("old", "new"):
            model, thr = paired_errors(done, path, dims)
            gap = (statistics.median(model) - statistics.median(thr)) if model else None
            measures[f"{path}_{name}"] = {
                "sam": _median_ci(model),
                "threshold": _median_ci(thr),
                "sam_minus_threshold_median_mm": None if gap is None else round(gap, 4),
            }
    accepted = {path: sum(bool(r.get(path, {}).get("accepted")) for r in done) for path in ("threshold", "old", "new")}
    new_gap = measures["new_length_width"]["sam_minus_threshold_median_mm"]
    with_mask = [r for r in done if r["new"]["mask"]]
    ious = [float(r["new"]["iou_threshold"]) for r in with_mask if r["new"].get("iou_threshold") is not None]
    return {
        "scope": "Rendered photos and public photos pasted on a rendered mat. Real phone photos are untested.",
        "photos": len(rows),
        "scored": len(done),
        "skipped": sorted({str(r.get("skipped")) for r in rows if r.get("skipped")}),
        "errors": [r["id"] for r in rows if r.get("error")],
        "mask_rate": {
            "old": _rate(done, "old"),
            "new": _rate(done, "new"),
            "mcnemar": {"old_only": b, "new_only": c, "p": round(p, 6)},
        },
        "mask_rate_by_suite": by_suite,
        "iou_new_vs_threshold": _median_ci(
            [float(r["new"]["iou_threshold"]) for r in done if r["new"].get("iou_threshold") is not None]
        ),
        "iou_new_vs_exact": _median_ci(
            [float(r["new"]["iou_exact"]) for r in done if r["new"].get("iou_exact") is not None]
        ),
        "iou_threshold_vs_exact": _median_ci(
            [float(r["threshold"]["iou_exact"]) for r in done if r.get("threshold", {}).get("iou_exact") is not None]
        ),
        "new_score": _median_ci([float(r["new"]["score"]) for r in done if r["new"]["mask"]]),
        "measures_paired": measures,
        "accepted_by_capture_gate": accepted,
        "new_mask_rejected_where_threshold_accepted": sum(
            bool(r["threshold"].get("accepted")) and not r["new"].get("accepted") for r in with_mask
        ),
        "iou_new_vs_threshold_below_0_9": {
            "k": sum(i < 0.9 for i in ious),
            "n": len(ious),
            "min": min(ious, default=None),
        },
        "colours": {w: sum(r.get("colour") == w for r in done) for w in sorted({str(r.get("colour")) for r in done})},
        "new_mask_by_colour": {
            w: _rate([r for r in done if str(r.get("colour")) == w], "new")
            for w in sorted({str(r.get("colour")) for r in done})
        },
        "rule": f"SAM stays the measuring mask if its paired median length/width error is within {WITHIN_MM} mm of the threshold's",
        "within_rule": None if new_gap is None else bool(new_gap <= WITHIN_MM),
        **({} if usd is None else {"usd": round(usd, 4)}),
    }


def compact(row: Mapping[str, Any]) -> dict[str, Any]:
    """One photo's row for the committed report: everything but each ladder's per-phrase attempts."""
    out = dict(row)
    for path in ("old", "new"):
        if path in out:
            ladder = dict(out[path])
            ladder["calls"] = len(ladder.pop("attempts", []))
            out[path] = ladder
    return out


def cmd_render() -> int:
    from tools.synth import generate_sample
    from tools.synth.dataset import dataset_specs, default_sample_id

    from .scale_data import _with_mask

    specs = [(s, sd) for s, sd in dataset_specs(N_FRESH, FRESH_SEED, n_reference=0) if s.kind == "template"][:N_FRESH]
    FRESH.mkdir(parents=True, exist_ok=True)
    (WORK / "masks").mkdir(parents=True, exist_ok=True)

    def render(spec: Any, seed: int) -> Path:
        return Path(generate_sample(spec, FRESH, seed=seed))

    for spec, sd in specs:
        sid = spec.sample_id or default_sample_id(spec, sd)
        folder = _with_mask(WORK / "masks" / f"{sid}.png", partial(render, spec, sd))
        print("rendered", folder.name, flush=True)
    return 0


def cmd_run(max_usd: float, workers: int) -> int:
    from services.agent import providers
    from services.agent.providers import pricing

    if ROWS.exists():
        raise SystemExit(f"{ROWS} exists: one run only, so a number is never re-rolled")
    call = Budget(providers.segment, pricing.segment_cost_usd("meta", 1), max_usd)
    photos = collect()
    print(f"{len(photos)} photos", flush=True)
    WORK.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=workers) as ex, ROWS.open("w") as f:
        for r in ex.map(lambda p: run_one(p, call), photos):
            rows.append(r)
            f.write(json.dumps(r) + "\n")
            f.flush()
            if len(rows) % 10 == 0:
                print(f"{len(rows)}/{len(photos)} ${call.usd:.2f}", flush=True)
    (WORK / "usd.json").write_text(json.dumps({"usd": call.usd, "calls": call.calls}))
    print(f"done ${call.usd:.3f} {call.calls} calls", flush=True)
    return cmd_report()


def cmd_report() -> int:
    if ROWS.exists():
        rows = [json.loads(line) for line in ROWS.read_text().splitlines()]
        usd = json.loads((WORK / "usd.json").read_text())["usd"]
    else:  # a fresh checkout: the committed report holds its own rows
        stored = json.loads(REPORT.read_text())
        rows, usd = stored["rows"], stored.get("usd")
    out = summarise(rows, usd)
    print(json.dumps(out, indent=1))
    REPORT.write_text(json.dumps({**out, "rows": [compact(r) for r in rows]}, indent=0) + "\n")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("cmd", choices=("render", "run", "report"))
    ap.add_argument("--max-usd", type=float, default=8.0)
    ap.add_argument("--workers", type=int, default=6)
    a = ap.parse_args(argv)
    if a.cmd == "render":
        return cmd_render()
    if a.cmd == "run":
        return cmd_run(a.max_usd, a.workers)
    return cmd_report()


if __name__ == "__main__":
    raise SystemExit(main())
