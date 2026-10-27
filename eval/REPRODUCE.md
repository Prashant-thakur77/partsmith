# Reproducing the PartSmith benches

Every number in the README, the video and the site comes from a script in `eval/` run on stored data. Each table
names its ground-truth source; the three sources are never merged:

| Source | Ground truth | Where |
|---|---|---|
| synthetic bench | exact (rendered from the CAD mesh with a known camera) | `data/synthetic/bench/` (re-rendered from a seed) |
| reference objects | published specs (ID-1 card, SD card, LEGO 2×4, AA cell — AA is a loose spec) | synthetic renders in the bench; real photos in `data/real/reference_objects/<object>/*.jpg` |
| real parts | school ruler, ±0.5 mm (never called caliper accuracy) | `data/real/<part>/gt.yaml` with `gt_source: ruler` |

## Phase 1 — measurement only (no keys, no models)

```bash
uv run python -m eval.measure_only                 # 60 synthetic parts + 20 reference renders, seed 7
uv run python -m eval.measure_only --n 200 --jobs 8 # the full synthetic set
```

It renders `data/synthetic/bench/` if it is missing (deterministic from the seed; `data/synthetic/bench_manifest.json`
records the seeds and the sha256 of every file), runs `services.metrology.measure.measure_photo` with the threshold
segmenter on every photo, and writes `eval/reports/<date>/measure_only.{json,md}`:

- per source: photos, capture-gate pass rate (Wilson 95 % CI), absolute error of every named dimension (mean with a
  seeded bootstrap 95 % CI, median, P90, max, share within ±0.3 / ±0.5 mm with Wilson CIs, bias), pass@0.3 / pass@0.5
  per photo, and breakdowns by dimension, profile, preset, family/object and mat;
- the failure list: photos the capture gate rejected (with the retake reason), photos where the mat or part was not
  found, and dimensions that could not be measured (e.g. a hole that was not detected);
- the Phase 1 exit gate: mean abs error ≤ 0.4 mm on accepted photos of the synthetic bench and of the reference
  objects (real photos when there are any, else the synthetic renders — the report says which).

Matching: `length`, `width` (top view) and `thickness` (side view) by name; holes by nearest centre on the mat
(synthetic) or nearest diameter (ruler ground truth has no centres). The side view's top-face height is the width
measured in the top view of the same part, as in the product.

### Real data formats (for when they exist)

`data/real/reference_objects/<id1_card|sd_card|lego_2x4|aa_cell>/*.jpg` — photos on a mat; a file name containing
`side` is scored as a side view.

`data/real/<part_id>/gt.yaml`:

```yaml
gt_source: ruler        # anything else is skipped by this bench
uncertainty_mm: 0.5
user_thickness_mm: 3.0  # optional; else dims.thickness
mat_id: screen-m        # optional
dims: {length: 42.0, width: 18.5, thickness: 3.0}
holes: [{diameter: 4.0}]
```

with `top.jpg` (and optionally `side.jpg`) next to it.

## Splits

`eval/splits.lock` freezes the synthetic bench definition (seed, sizes, dataset sha256) and will hold the real-part
dev / held-out split and its hash once the real parts are collected. Held-out parts are only touched by `make bench`.

## Still to come

The agent-loop benches (`eval/run.py`, `make bench` / `make bench-live`) are added in a later phase; this file will
list their commands here.
