# Scale evaluation plan (written before any run)

Declared 2026-11-05 03:58 IST, before the first model call of this evaluation. Sizes, seeds, configs and success rules below
do not change after results are seen. Nothing here is a phone capture: real-photo counters stay 0.

**Seed:** 20261105 for every dataset (fresh; the frozen 60-sample bench and the dev split are not reused).
**Code:** one snapshot of the working tree, copied to one server before the first run. Product code is not changed mid-run; bugs are listed instead.
**Spend cap:** $90 of live model calls in total, from the runs' own `usd`. No new run starts past $86 plus the cost of runs in flight.
**Time:** no new run starts after 05:40 IST. Whatever is unfinished is reported as not run.
**Order:** all full-loop runs share one seeded shuffle (`random.Random(20261105)`), so a partial stop still leaves an unbiased subset of each suite.
**No re-runs:** each task runs once. Failures, crashes and provider errors stay in the tables.

## Full-loop suites (`eval/scale_run.py`, stored under `eval/runs/live_scale/`, never merged with `eval/runs/live/`)

| Suite | Size | Config | Data | Ground truth |
|---|---|---|---|---|
| `synthetic` | 200 | PS | fresh template renders, all families, all eight bench presets, top + side | exact mesh |
| `synthetic` | first 100 of those by seeded choice | B1 | the same samples, paired | exact mesh |
| `broken` | 30 | PS | template parts with a tip, tab or corner removed, top + side; GT is the intact part | exact mesh |
| `reference_objects` | 60 | PS | fresh renders of the four reference objects | published spec |
| `control_top` | 40 | PS | intact parts, normal photos, top only | expected accept; exact mesh for sizes |
| `control_side` | same 40 parts | PS | the same top photo plus a side photo | expected accept; exact mesh for sizes |
| `redteam` | 40 | PS | the ten red-team cases rendered with four fresh seeds | expected reject or refuse |

Scoring is the existing `eval/run.py` code: `score_model`, `config_row`, `gate_table`, `mcnemar_paired`, Wilson and bootstrap intervals.

**Questions this answers, with the rule fixed now:**
1. Full loop on fresh samples: median error, pass@0.5, verified rate, each with n and CI.
2. Paired B1 vs PS on pass@0.5: exact McNemar. PS is called better only at p < 0.05.
3. Verified but off: among verified parts, the share more than 0.5 mm off on any scored size, top-only vs top + side, on the same 40 parts, with Wilson CIs. The side photo is called helpful only if the top + side share is lower and the intervals do not overlap; otherwise "not shown at this n".
4. Understanding: Muse Spark 1.3's family against the template's family, and on `broken` whether it reports a broken region, read from each PS run's logged PartSpec (this replaces a separate 200-call run: the same calls, already made, on 200+ samples).

## Stage-level suites (`eval/scale_stages.py`, stored under `eval/runs/live_scale/stages/`)

- **SAM 3.1:** 500 top photos from this dataset (all of the above plus extra template renders) through the product's `ProviderSegmenter` with the prompt "plastic part". IoU and symmetric boundary error in mm against the renderer's exact part coverage. Reported as median, P90 and share of IoU ≥ 0.95, overall and per preset.
- **Muse Wonder:** the 30 named parts listed in the script, one lookup each. Counted: lookups where code accepted at least one cited value. A sample of accepted values is checked against the cited page's text by script. A citation is not treated as a verified fact.
- **Voice:** the 40 Hindi, English and mixed knob-edit lines listed in the script, synthesised speech from two narrator voices, through `transcribe_and_map` against the expected edit on the battery cover's knobs, and the same line typed, so transcription errors separate from mapping errors. Right means exactly the expected knob at the expected value ±0.01 mm. Every wrong line is listed. Labelled synthesised speech, not people.

## If budget and time remain

Run the seed path on fresh samples into a separate home folder, publishing only what the existing gate publishes. Otherwise reported as not run.
