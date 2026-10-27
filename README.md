# PartSmith

**Snap a broken part. Get a verified, printable replacement.**

PartSmith turns phone photos of a broken plastic part into a parametric CAD program that has been checked against the photo in
millimetres. You lay the part on your laptop or tablet screen (it becomes a calibrated measuring mat), take a photo, and an agent
writes CadQuery. Deterministic code renders the model from the photo's own camera pose, compares it with the part, and the agent
fixes the model until the error is under half a millimetre. Every verified part joins an open registry that people and coding
agents can search, re-size and download over REST and MCP.

No printer, caliper or special paper needed. The model proposes; code decides.

Entry for the Meta Global AI Developer Hackathon (Indie Developer track, problem statement: Push the Frontier).

## 30-second judge path

| | |
|---|---|
| Watch a stored run, step by step | `/judges` in the web app (replays are labelled "replay") |
| Run it yourself with no keys | `make setup && make dev` → <http://localhost:3000> → **Fix a part → Try a synthetic sample** |
| Which model ran where | `/status` (mock / live per stage, open-weights badges) |
| Numbers and how they were made | [Results](#results) · `/bench` · [`eval/REPRODUCE.md`](eval/REPRODUCE.md) |
| For agents | `/agents`, `/llms.txt`, MCP at `/mcp` |

## Meta models, and where each one works

Every model call goes through [`services/agent/providers`](services/agent/providers) and is logged as a `model_call` event (provider,
model, tokens, ms, $). This table's file:line links are generated from the code by `tools/readme.py`.

<!-- BEGIN:meta-tooling -->
| Meta model | How we run it | Role | Where |
|---|---|---|---|
| **SAM 3.1** | Meta Model API | Text-prompted masks of the part — the pixels the verifier measures in mm | [`services/agent/providers/routing.py:96`](services/agent/providers/routing.py#L96) · [`services/metrology/segment.py:599`](services/metrology/segment.py#L599) |
| **Muse Spark 1.3** | Meta Model API | Understand stage: names features, family, broken region, unknowns (strict PartSpec JSON) | [`services/agent/orchestrator.py:947`](services/agent/orchestrator.py#L947) |
| **Muse Spark Open** | open weights (Baseten / Fireworks / Together) | Planner, CadQuery builder and fixer in the verify loop | [`services/agent/orchestrator.py:1246`](services/agent/orchestrator.py#L1246) · [`services/agent/orchestrator.py:1500`](services/agent/orchestrator.py#L1500) |
| **Muse Glimmer 30B** | open weights (llama.cpp on a Modal GPU) | Independent veto-only judge and capture triage | [`services/agent/orchestrator.py:1663`](services/agent/orchestrator.py#L1663) · [`infra/modal/glimmer.py:51`](infra/modal/glimmer.py#L51) |
| **Muse Voice Transcribe** | Meta Model API | Hindi/English voice edits and spoken answers | [`services/media/voice.py:452`](services/media/voice.py#L452) |
| **Muse Image** | Meta Model API | "See the fix" in-place preview (labelled AI preview) | [`services/media/preview.py:78`](services/media/preview.py#L78) |
| **Muse Wonder** | Meta Model API | Steer factory planner: plans a family of parts for the registry | [`services/registry/steer.py:545`](services/registry/steer.py#L545) |
| **SAM 3 (open weights)** | open weights (Modal GPU) | All-open-weights segmentation path and bench | [`infra/modal/sam3.py:44`](infra/modal/sam3.py#L44) |
<!-- END:meta-tooling -->

Model names show up in the trace, on `/status` and in every run log. With `OPEN_WEIGHTS_ONLY=1` every stage runs on open weights
(Muse Spark Open, Muse Glimmer 30B, SAM 3 on a Modal GPU).

## How it works

```
 photo on the screen mat ─▶ capture gate ─▶ ArUco pose + SAM mask ─▶ millimetres (parallax-corrected, ±σ, measured/stated/inferred)
                                                                              │
              ┌───────────────────────────────────────────────────────────────┘
              ▼
   Muse Spark: PartSpec ─▶ Muse Spark Open: CadQuery ─▶ sandbox ─▶ verifier: render with the photo's camera,
         ▲                         ▲                                IoU, Hausdorff mm, feature residuals, part tests
         │ questions               └──────── bounded fix (≤ 6 rounds) ◀───────┘
     the human                                                       │
                                  Muse Glimmer judge (veto only) ◀───┘ ─▶ Verified (code-decided) or honest best effort
                                                                      ─▶ STL · 3MF · STEP · part.py · 1:1 template · registry
```

- **Screen mat.** The web app draws a ring of ArUco markers at true 1:1 scale on a laptop or tablet. You calibrate the scale once
  by matching an ID-1 bank card (85.60 × 53.98 mm). A plain-paper A4 mat PDF works too.
- **Measurement.** Sub-pixel marker corners → homography and camera pose → SAM 3.1 mask → contour in mm with exact parallax
  correction for the part's thickness, circle/slot fitting, see-through hole fitting for thick parts, and an uncertainty per value.
- **Agent loop.** The model writes a CadQuery program with typed knobs. It runs in a sandbox (AST allowlist, rlimits, no network).
  The verifier renders it with the photo's real camera and measures model and photo with the same code. The fixer gets the numeric
  residual table. Guards clamp every edit and refuse to rescale the outline to force a fit.
- **Verified** means: all P0 part tests pass, Hausdorff ≤ 0.5 mm and IoU ≥ 0.97 on the top view, thin side profiles within
  ±0.3 mm, and no blocking veto from the independent judge. Only the verifier can set it.
- **Screen fit check.** Before printing anything, the model's 1:1 outline is drawn on the calibrated screen. You lay the real part
  on it and photograph it, and the same verifier says pass or fail with an overlay.

## Results

Every number here is written by `make bench` (`tools/readme.py` reads `eval/reports/latest/report.json`). Ground-truth sources are
never mixed: synthetic photos (exact), standard reference objects (published specs), real broken parts (school ruler, ±0.5 mm).

<!-- BEGIN:bench -->
Generated 2026-10-27T13:57:10+00:00 at commit `1d815f4f2af784c32734c83f50ff91c25ab02907` · mode **mock**.

> **These rows come from deterministic mock providers (no API keys yet).** They check that the pipeline, verifier and scorer work end to end; they do **not** measure any model. Live numbers replace them after `make live`.

**Synthetic bench (exact ground truth)**

N = 6 · ground truth: `synthetic_exact` · CI: 95 %: bootstrap over samples (2000 resamples, seeded) for mean errors; Wilson for rates

| config | n | median_abs_err_mm | mean_abs_err_mm | mean_ci95 | pass@0.5 | verified_rate | median_iters |
|---|---|---|---|---|---|---|---|
| B0 | 6 | 0.6 | 2.34 | [1.089, 3.539] | 0.167 | 0 | 1 |
| B1 | 6 | 0.3 | 0.45 | [0.203, 0.730] | 0.5 | 0.167 | 1 |
| B2 | 6 | 0.15 | 0.514 | [0.165, 0.851] | 0.5 | 0.333 | 5 |
| PS | 6 | 0.15 | 0.482 | [0.147, 0.844] | 0.5 | 0.333 | 4 |
| PS-noTemplate | 6 | 0.131 | 2.337 | [0.685, 4.379] | 0.167 | 0.167 | 3 |
| PS-noJudge | 6 | 0.15 | 0.466 | [0.147, 0.793] | 0.5 | 0.333 | 4 |
| PS-noHeightCorr | 6 | 0.3 | 0.52 | [0.239, 0.900] | 0.167 | 0 | 6 |

_headline = PS on the held-out split (6 samples); MOCK providers: these numbers check the pipeline, they do not measure any model_

**Reference objects (vs published specs)**

N = 4 · ground truth: `reference_spec` · CI: 95 %: bootstrap over samples (2000 resamples, seeded) for mean errors; Wilson for rates

| config | n | median_abs_err_mm | mean_abs_err_mm | mean_ci95 | pass@0.5 | verified_rate | median_iters |
|---|---|---|---|---|---|---|---|
| B0 | 4 | 3.4 | 4.584 | [3.589, 5.330] | 0 | 0 | 1 |
| B1 | 4 | 0.131 | 0.453 | [0.125, 0.890] | 0.5 | 0.25 | 1 |
| B2 | 4 | 0.075 | 0.153 | [0.063, 0.307] | 0.75 | 0.25 | 3 |
| PS | 4 | 0.1 | 0.439 | [0.066, 0.923] | 0.5 | 0.5 | 2.5 |
| PS-noTemplate | 4 | 0.131 | 0.175 | [0.066, 0.307] | 0.75 | 0.5 | 2.5 |
| PS-noJudge | 4 | 0.1 | 0.439 | [0.066, 0.923] | 0.5 | 0.5 | 2.5 |
| PS-noHeightCorr | 4 | 0.353 | 0.685 | [0.264, 1.284] | 0.25 | 0 | 4.5 |

_headline = PS on the held-out split (4 samples); MOCK providers: these numbers check the pipeline, they do not measure any model_

**Real broken parts (vs school ruler, ±0.5 mm)**

_Pending — no real parts with ruler ground truth yet (data/real/<part>/gt.yaml, see eval/REPRODUCE.md)._

**Measurement only (photo → mm, no CAD loop)**

```
synthetic                        photos 120 accepted  98  dims N=229  mean 0.466 [0.368, 0.581]  median 0.199  P90 1.033  max 5.316  ≤0.5 77 %
  top view, flat parts                   dims N= 82  mean 0.226 [0.181, 0.273]  median 0.165  P90 0.544
  top view, parts with tall features     dims N= 98  mean 0.494 [0.324, 0.690]  median 0.129  P90 1.378
  expected rejections (white part on light stage): 5/6 correctly rejected
reference_objects_synthetic      photos  30 accepted  22  dims N= 37  mean 0.170 [0.107, 0.255]  median 0.081  P90 0.303  max 1.312  ≤0.5 92 %
reference_objects_real           pending (no photos)
real_parts_ruler                 pending (no photos)
EXIT GATE (mean ≤ 0.4 mm): synthetic 0.466 FAIL · reference objects [reference_objects_synthetic] 0.170 PASS → FAIL
```
<!-- END:bench -->

## Run it

```bash
make setup        # uv sync (Python 3.12) + pnpm install + generated types
make dev          # seeds the registry from the bundled synthetic samples, starts API :8000 and web :3000
make test         # unit tests, no network, no keys
make bench        # rebuilds every results table from stored runs (no keys needed)
make smoke        # one call per provider: ✅ live · ⚠️ key missing (mock) · ❌ failed
```

With no keys every model stage runs as a deterministic mock, and the app says so on every page. Add keys to `.env` (see
`.env.example`) and run `make live` to switch to live models and re-run the benches. Self-hosting Glimmer and SAM 3 on Modal:
[`infra/modal/README.md`](infra/modal/README.md).

## For agents and developers

- REST: `/api/v1` ([docs/API.md](docs/API.md), OpenAPI at `/api/v1/openapi.json`)
- MCP: `uv run python -m services.mcp --stdio`, or streamable HTTP at `/mcp` — tools `search_parts`, `get_part`, `get_variant`,
  `bake`, `find_matching`, `list_families`, `measure_photo`, `start_fix_job`, `get_job`, `report_need`
  ([services/mcp/README.md](services/mcp/README.md))
- Agent rules: never rescale a part to force a fit — change the right knob; if no part matches, say so and call `report_need`;
  report which dimensions were measured and which were assumed.

## Limitations (honest)

- No live model call has been made yet (no API keys at the time of writing); all current results use deterministic mocks and
  synthetic photos, and are labelled that way.
- A single top photo cannot resolve heights above the stated plate thickness; the side photo and camera-frame verification
  handle it in the loop, but raw top-view measurements of tall features are biased (see the measurement-only table).
- White or light-grey parts need the dark screen stage; the capture gate asks for it.
- Real reference-object photos and real broken parts are pending; the real-part tables say "pending" until they exist.
- No physical print results yet; the physical proof is the screen fit check. Prints are optional and will only be reported if made.

## Repository map

| Path | What |
|---|---|
| `services/metrology` | mats, card scale, capture gate, pose, segmentation, mm features, screen fit check |
| `services/geom_worker` | sandboxed CadQuery execution, exporters, bake cache |
| `services/verifier` | silhouettes, metrics, part tests, the pass rule |
| `services/agent` | orchestrator, providers, templates, prompts, jobs and replays |
| `services/api`, `services/mcp`, `services/registry` | REST + SSE, MCP, registry, Steer factory |
| `apps/web` | Next.js app |
| `tools/synth`, `eval` | synthetic photo generator with exact ground truth, benches and reports |
| `docs/` | architecture, API, decisions, progress |

## Built during the hackathon

All code in this repository was written during the hackathon (from Oct 26 2026, 12:00 PM ET); see the commit history.

## Credits

<!-- Prashant writes this section. -->

## License

MIT for the code. Registry parts: CC BY 4.0.
