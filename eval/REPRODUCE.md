# Reproducing the PartSmith benches

Every number in the README, the video and the site comes from a script in `eval/` run on stored data. Each table
names its ground-truth source; the sources are never merged:

| Source | Ground truth | Where |
|---|---|---|
| synthetic bench | exact (rendered from the CAD mesh with a known camera) | `data/synthetic/bench/` (re-rendered from a seed) |
| reference objects | published specs (ID-1 card, SD card, LEGO 2×4, AA cell — AA is a loose spec) | synthetic renders in the bench; real photos in `data/real/reference_objects/<object>/*.jpg` |
| real parts | school ruler, ±0.5 mm (never called caliper accuracy) | `data/real/<part>/gt.yaml` with `gt_source: ruler` |
| public photos | published spec, pasted at known size (never counted as real photos measured) | `data/public_photos/` (composites generated from `manifest.yaml`) |

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

### Photo day (real parts, in order)

```bash
make real-intake FROM=<folder of phone photos>   # <part>_top.jpg / <part>_side.jpg / <part>_context.jpg, or parts.csv
                                                 # (file,part,view); writes data/real/<part>/ + gt.yaml templates
# fill every gt.yaml with the ruler readings (gt_source: ruler, uncertainty_mm, dims, holes)
make real-check                                  # offline: gt.yaml rules + the /fix capture gate on every photo
uv run python -m eval.splits assign              # after gt.yaml is final: the held-out hash covers its bytes
PROVIDER_MODE=live uv run python -m eval.run --live --suite real_ruler --suite reference_objects --max-usd 10
make bench                                       # rebuild every table from the stored runs
```

`tools/real_check.py` explains both subcommands (`--json`, `--no-part-check`, `--dry-run`, `--reencode`, `--force`).
Intake strips location, dates and device EXIF fields, keeps the orientation and focal-length tags and does not
re-encode JPEG pixels; it never overwrites a `gt.yaml`. `make real-check` exits 1 when any folder is unusable.

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

## Control and red-team suites

`eval/run.py` also runs two expected-outcome suites with the headline config (PS): `control` (6 intact template parts,
normal photos → must be accepted; reports the false-rejection rate) and `redteam` (10 photos that must be rejected by
the capture gate — naming the acceptable checks — or refused: empty mat, a re-photographed screen, a hand in frame, a
partial mat, a foreign marker board, a clay figurine, a silicone gasket, two parts, a part on the markers, a helmet
buckle). Each table gives the share handled as expected with a Wilson 95 % CI. The photos are rendered into
`data/synthetic/suites/` (seed 11) when missing.

## Public photos (no phone photos of real parts exist yet)

Neither check below is a phone capture of a laptop-screen mat, and neither adds to "real photos measured".

**Real-camera scale check** (`eval/public_scale.py`, no model, no cost). Public real camera photos of printed marker
boards. A homography is fitted to the outer markers' corners with the product's own code
(`calibrate.fit_plane_homography`, its detector settings and sub-pixel corners) and predicts the inner markers' corners.
The error is on the board plane, with the board's long side = 100, so the same number is the % of span and the mm over
a 100 mm span on our mat. CI: bootstrap over held-out markers. The boards' printed size is unknown, so nothing here is
an absolute length. When a board's outer markers reject its documented layout (under 90 % of their corners fit), the
photo leaves the headline; the report keeps it as written and with the gap ratio fitted on outer markers only.
Photos and the source list stay in the gitignored `var/public_photos/`; `--download` refetches them from that list.

```bash
uv run python -m eval.public_scale    # eval/reports/latest/public_scale.{json,md}
```

**`public_photos` suite** (`tools/public_photos.py`). Each object is cut out of a public photograph by code (threshold
or GrabCut, no model) and pasted on our rendered screen mat. The object's pixels are real; the mat, the camera and the
light on the mat are rendered, and the flat cut-out sits on the plane at the stated thickness, with no walls or shadow.

Circularity rule: the paste scale comes from one published dimension (the long side, or for a second object in the same
photograph the first object's long side). In `gt.yaml` that dimension is `set_by_construction`: it is shown but left out
of every error, pass rate and chart. Width and hole diameters are held out. The job gets the thickness and a neutral
intent that does not name the object; the object is still visible in the photo, so a model can recognise it. The
measure-only report has no model at all.

```bash
uv run python -m tools.public_photos build --preview var/preview.png   # composites from data/public_photos/manifest.yaml
uv run python -m eval.public_photos                                    # measure only: public_photos_measure.{json,md}
make smoke
PROVIDER_MODE=live uv run python -m eval.run --live --suite public_photos --configs PS --jobs 2 --max-usd 5 \
  --out var/public_photos/live_report   # keeps the full report in eval/reports/latest/ intact
make bench                              # rebuilds every table from stored runs, public_photos as its own table
```

`--max-usd` stops starting runs once finished runs reach the cap; running ones finish. The manifest lists every candidate
photo that was looked at and left out, with the reason. Masks were checked by eye against the object's edge; the first
pass, with cast shadows in some masks, is kept as `public_photos_measure_first_pass.json`. Runs of this suite stay out of
`open_weights.json`, and its failures sort last in the failure gallery, so the other suites' figures do not move. Its
table sits under `separate_tables` in `report.json`, not `tables`.

## Test evidence

`make proof` (`tools/proof.py`) runs the gates and writes `eval/reports/latest/tests.json` and `docs/PROOF.md` from junit
xml, the node runner's summary and exit codes. `ARGS=--browser` adds the browser tests with `--workers=2` and a 10 minute
limit; `ARGS="--skip backend"` skips a gate. A gate that did not run says `not run`; no count is carried over.

## Failure taxonomy, provenance, open weights, impact

- Every failed run gets one category, by the first matching rule: refused → timeout → scale_fail → seg_fail →
  capture_reject → codegen_error → topology_wrong → judge_veto → dim_off (`eval/taxonomy.py`). The report counts them
  per suite and config (`failure_taxonomy`). Red-team misses are reported by the red-team table instead.
- `provenance.json` (next to each report; `measure_only.provenance.json` for the measurement bench): models, providers
  and modes per stage from the runs' events, git sha, verifier and capture-gate thresholds read from the code, seeds,
  dataset hashes, generator and template versions.
- `open_weights.json` (`eval/reports/latest/`): per stage which model and provider served it and whether it is open
  weights (from the routing table), calls and tokens, the share of builder tokens on open weights (live and replay
  calls only — mock calls show routing, not usage), and the PS-open / PS-open-all rows once a live run exists
  ("pending live run" until then).
- `uv run python -m eval.impact` → `impact.{json,md}` from `data/impact/sessions.yaml` (real repair sessions entered by
  hand: price + source URL or "not stocked", run id → time to verified, fit result, printed grams; ₹/g stated in the
  file). "pending" while the log is empty.

## Splits

`eval/splits.lock` freezes the synthetic bench definition (seed, sizes, dataset sha256) and will hold the real-part
dev / held-out split and its hash once the real parts are collected. Held-out parts are only touched by `make bench`.

Real parts follow the dev / held-out lists in `eval/splits.lock`; a part in neither list is "unassigned" and never
reaches a table. The synthetic bench and the reference objects are never used for tuning, so they count as held out
(the demo set in `data/synthetic/samples/` is the synthetic dev set).

## Knob-change time

`make rebake` times fresh bakes of the stored battery cover in a warm sandbox worker, each at a length no earlier bake used,
and writes `eval/reports/latest/rebake.json`. No model call. The first two bakes wake the worker and are dropped from the
median. The times come from the machine that ran it.

## Scale evaluation

`eval/SCALE_PLAN.md` fixes the sizes, seeds, configs and success rules before any run. The stored results are under
`eval/runs/live_scale/`, apart from the frozen bench in `eval/runs/live/`, and the summary is `eval/reports/latest/scale.json`.

```sh
uv run python -m eval.scale_report                 # rebuild scale.json from the stored runs (no keys, no model calls)
uv run python -m eval.scale_data --jobs 8          # re-render the datasets (seed 20261105) into var/scale_data
PROVIDER_MODE=live uv run python -m eval.scale_run # re-run the full-loop suites with live models; costs real credits
PROVIDER_MODE=live uv run python -m eval.scale_stages sam|wonder|voice
```

These are live model calls on rendered photos with exact ground truth. They are not phone captures and never count as real photos measured.

## SAM 3.1 prompts

Whether naming the part's colour makes SAM 3.1 answer, and whether its masks measure as well as the threshold mask. The measures
and the decision rule are in the docstring of `eval/sam_prompts.py`, written before the run. It needs a Meta key, costs about
$1.35 for 147 photos, and refuses to run twice over the same rows file, so a number is never re-rolled. Photos are rendered or
pasted on a rendered mat; none is a phone capture.

```sh
uv run python -m eval.sam_prompts render                    # 14 fresh renders with exact masks, into var/sam_prompts
PROVIDER_MODE=live uv run python -m eval.sam_prompts run --max-usd 8
uv run python -m eval.sam_prompts report                    # rebuilds eval/reports/latest/sam_prompts.json; no model calls
```

