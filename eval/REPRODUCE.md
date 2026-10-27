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
uv run python -m eval.measure_only                 # 60 synthetic parts + 20 reference renders + 6 rejections, seed 7
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

Expected rejections: white-on-light photos (`gt.yaml` `expect.capture_gate: reject`) are not scored; a rejection by
the contrast check counts as correct, an accepted one is listed as a "missed rejection" failure.

The synthetic section splits the top view into flat parts and parts with tall features (anything taller than the
stated thickness + 1 mm): a single top photo cannot resolve heights above the stated thickness, so the second group
shows the limit of the measurement, not of the model; the full-loop bench scores the final model instead.

What the bench passes to `measure_photo` comes from `meta.json` only: `thickness_mm` = the user's thickness (top) or
the measured top width (side), `stated_thickness_mm` = the user's thickness (side views), `profile="round"` for an
AA cell (top view) and for wheels / knobs / spacers laid on their side (side view).

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

## Full loop — PartSmith-Bench (`eval/run.py`)

```bash
make bench                                  # = uv run python -m eval.run --from-runs   (no keys, minutes)
make bench-live                             # = uv run python -m eval.run --live        (real providers)
uv run python -m eval.run --configs B1,PS --limit 12 --jobs 4     # fresh mock runs of a subset
uv run python -m eval.run --from-runs --check-regression          # CI: exit 1 when worse than the baseline
uv run python -m eval.run --from-runs --write-baseline            # store eval/baseline_metrics.json
```

Every run goes through `services.agent.service.start_fix_job(photos, JobInput, sync=True)` like a user's job
(jobs live in `var/bench/`, packaging and lessons are off). Answers are non-interactive: the thickness comes from
`meta.json` `user_thickness_mm`, every other question takes its default. The scorer is the only code that reads
`gt.yaml`: it re-runs the job's FINAL part program in the sandbox and measures it exactly like the ground truth
(`tools.synth.geometry`: min-area-rectangle length/width, overall thickness, see-through hole diameters matched by
nearest diameter). Per run it stores `eval/runs/<mode>/<suite>/<config>/<sample>/score.json` (+ `run.jsonl.gz`,
`part_py.txt`, and `overlay.png` for failed PS runs); `--from-runs` rebuilds every table from those files.

Configs change one thing at a time:

| config | what changes |
|---|---|
| B0 | single shot, the models get no mat-calibrated numbers (sizes guessed from the raw photo at an assumed 30 cm / 26 mm lens) |
| B1 | single shot with the mat measurements (no fix loop, no judge) |
| B2 | full loop, the fixer sees the overlay images but no residual numbers |
| PS | the full PartSmith loop |
| PS-noTemplate / PS-noJudge / PS-noHeightCorr | PS without the template library / the judge / the parallax correction |
| PS-open, PS-open-all | provider routing (`OPEN_WEIGHTS_ONLY=1` for -all); live only — with mocks they equal PS |

Report: `eval/reports/<date>/report.{json,md}` (+ `charts/*.svg`, `gallery/*.png`) and `eval/reports/latest/report.json`,
the payload served at `GET /api/v1/bench`. Each table carries N, the 95 % CIs (bootstrap over samples for mean
errors, Wilson for rates), the ground-truth source and a headline (PS on the held-out split). Paired exact McNemar
B1 vs PS on pass@0.5. In mock mode every table is titled "pipeline check — deterministic mock providers, NOT model
performance": the baselines still run their real code paths, but every model answer is the deterministic mock's.
`--live` refuses unless the build stage has a live provider (see `make smoke`).

## Splits

`eval/splits.lock` freezes the synthetic bench definition (seed, sizes, dataset sha256) and will hold the real-part
dev / held-out split and its hash once the real parts are collected. Held-out parts are only touched by `make bench`.

Real parts follow the dev / held-out lists in `eval/splits.lock`; a part in neither list is "unassigned" and never
reaches a table. The synthetic bench and the reference objects are never used for tuning, so they count as held out
(the demo set in `data/synthetic/samples/` is the synthetic dev set).
