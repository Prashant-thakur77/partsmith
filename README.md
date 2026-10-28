# PartSmith

**Snap a broken part. Get a replacement that has been checked against your photo, in millimetres.**

A cupboard latch snaps, a battery cover goes missing, a cable clip cracks. The appliance still works, but the plastic piece
is not sold on its own, so the whole thing goes in the bin. A 3D print would fix it, but it has to be modelled to within half
a millimetre or it will not fit. That takes a caliper, CAD skills and an hour, which most people do not have.

PartSmith turns your laptop screen into a calibrated measuring mat. You lay the part on it and take a photo (or walk around
it with a short video). Meta's models look, point, cut out and write CadQuery. Deterministic code measures, renders the model
from the photo's own camera and decides whether it matches. The result is a parametric part you can print, re-size with
named knobs, or send to a print shop, and it joins an open registry that people and coding agents can search over REST and
MCP.

No printer, caliper or special paper needed. **The model proposes; code decides.**

Entry for the Meta Global AI Developer Hackathon (Indie Developer track, problem statement: Push the Frontier).

## 30-second judge path

| | |
|---|---|
| Watch a stored run, step by step | `/judges` in the web app (replays are labelled "replay") |
| Watch a lying model get caught | `/judges` → *A lying model, caught*: a scripted model says "VERIFIED", the verifier's overlay shows its real error and the export is blocked |
| Run it yourself with no keys | `make setup && make dev` → <http://localhost:3000> → **Fix a part → Try a sample** |
| Which model ran where, live or mock | `/models` (per stage, with open-weights badges) |
| Numbers and how they were made | [Results](#results) · `/results` · [`eval/REPRODUCE.md`](eval/REPRODUCE.md) |
| For agents | `/agents`, `/llms.txt`, MCP at `/mcp` |

## Why trust a model-made part?

A language model can write a CAD file that looks right and is 2 mm off. For a replacement part, that is useless. PartSmith
never trusts what a model says about itself:

| A model proposes … | … and code decides | Where |
|---|---|---|
| SAM 3.1 returns a mask | ArUco pose, parallax correction and sub-pixel edge fitting turn it into mm with an uncertainty per value; the capture gate rejects blurred, tilted, glary or multi-part photos | `services/metrology` |
| Muse Spark names a feature and the pixel it is at | SAM 3.1 cuts that point out, code fits the circle or slot in mm | `services/metrology/points.py` |
| Muse Spark Open writes and edits CadQuery | It runs in a sandbox (AST allowlist, rlimits, no network); guards cap each edit and refuse uniform rescaling | `services/geom_worker`, `services/agent/guards.py` |
| The fix agent says "done" | The verifier re-renders from the photo's camera and re-measures model and photo with the same code; only it sets `verified` | `services/verifier` |
| Muse Wonder quotes a spec | Accepted only if a web search ran and the URL came back from it; cited values never override a measurement | `services/agent/providers/spec.py` |
| Muse Image completes the broken region | Accepted only if every mat marker re-detects in place and the intact part is unchanged | `services/metrology/recon_gate.py` |
| Muse Glimmer judges the result | Veto only: it can block a pass, never grant one | `services/agent/orchestrator.py` |
| Muse Spark points at features while you narrate a clip | A point is kept only if it lands on the part in its own frame and on the measured footprint; the words steer, never set a number | `services/metrology/narration.py` |
| A search finds the original part's price | Kept only with the source link the search returned and a quote that shows the price; grams, print time and cost come from the mesh | `services/agent/providers/buy.py`, `services/agent/buy_or_print.py` |
| A tall part is seen only from above | The photo bounds its length and width instead of fixing them; without a side view or clip, code refuses to verify an extruded guess, and every knob nothing checked is listed as inferred | `services/verifier/verify.py` |
| Anyone asks to download | Every download URL gives a best-effort part only after an explicit "I understand" and refuses a failed one | `services/verifier/ship.py`, `services/registry/gate.py` |

The table below shows these checks being attacked (all numbers are written by scripts):

<!-- BEGIN:evidence -->
| Check | Result | Source |
|---|---|---|
| Intact parts, normal photos → accepted (mock providers) | 6/6 handled as expected, 95 % CI [0.61, 1.00] | `eval/reports/latest/report.json` → `tables.control` |
| Photos that must be rejected or refused (mock providers) | 10/10 handled as expected, 95 % CI [0.72, 1.00] | `eval/reports/latest/report.json` → `tables.redteam` |
| Verified synthetic parts (mock providers) that are > 0.5 mm off the ground truth | 0/2 (config PS) | `eval/reports/latest/report.json` → `tables.synthetic` |
| Verified reference objects (mock providers) that are > 0.5 mm off the ground truth | 0/1 (config PS) | `eval/reports/latest/report.json` → `tables.reference_objects` |
| Edit a hole: scale the mesh vs change the program's knob (17 parts, 88 edits) | hole spacing moved 2.771 mm (median) with mesh scaling, 0.0 mm with the knob | `eval/reports/latest/program_vs_mesh.md` |
| A model that lies or cheats (says verified, edits the record, loosens limits, rescales to fit, fakes a break, smuggles imports, exports without consent) | 17/17 attempts blocked by code | `eval/reports/latest/bypass.json` |
| Real repairs logged | pending: no sessions logged yet (data/impact/sessions.yaml) | `data/impact/sessions.yaml` |
<!-- END:evidence -->

## Meta models, and where each one works

Every model call goes through [`services/agent/providers`](services/agent/providers) and is logged as a `model_call` event (provider,
model, tokens, ms, $). Agent stages also log their reasoning summaries, every tool call and where they are looking, and the
workspace shows them live. This table's file:line links are generated from the code by `tools/readme.py`.

<!-- BEGIN:meta-tooling -->
| Meta model | How we run it | Role | Where |
|---|---|---|---|
| **SAM 3.1** | Meta Model API | The measuring instrument: text-prompted part masks, point-prompted feature cuts (holes, slots, tapped points) and video tracking of a walk-around clip. Code turns every mask into millimetres | [`services/agent/providers/routing.py:104`](services/agent/providers/routing.py#L104) · [`services/metrology/segment.py:664`](services/metrology/segment.py#L664) · [`services/agent/evidence.py:91`](services/agent/evidence.py#L91) · [`services/agent/evidence.py:158`](services/agent/evidence.py#L158) |
| **Muse Spark 1.3** | Meta Model API | Understand stage: family, features, broken region, unknowns (strict PartSpec JSON), and the pixel it saw each hole or slot at, which SAM 3.1 then cuts and code measures. Watches and listens to a narrated walk-around clip and points at the features it hears about (frame and pixel), kept only if they land on the part | [`services/agent/orchestrator.py:1004`](services/agent/orchestrator.py#L1004) · [`services/agent/evidence.py:57`](services/agent/evidence.py#L57) · [`services/agent/evidence.py:233`](services/agent/evidence.py#L233) |
| **Muse Spark Open** | open weights (Baseten / Fireworks / Together) | CadQuery builder, and the fix agent that operates PartSmith's own tools (inspect residuals, measure, segment, render, run tests, set knobs) until the verifier agrees | [`services/agent/orchestrator.py:1317`](services/agent/orchestrator.py#L1317) · [`services/agent/agent_loop.py:458`](services/agent/agent_loop.py#L458) |
| **Muse Glimmer 30B** | open weights (llama.cpp on a Modal GPU) | Independent veto-only judge, shown side-by-side photo and model crops zoomed on the verifier's worst spots | [`services/agent/orchestrator.py:1832`](services/agent/orchestrator.py#L1832) · [`infra/modal/glimmer.py:51`](infra/modal/glimmer.py#L51) |
| **Muse Wonder** | Meta Model API | Finds a published spec for the named appliance with web search. Code accepts a value only if a search really ran and its URL is one the search returned; cited values fill unknowns and never override a measurement. Also finds the original part's price with search grounding for the buy-or-print card (a price is kept only with its source link and a quote showing it) and plans part families for the factory | [`services/agent/evidence.py:317`](services/agent/evidence.py#L317) · [`services/agent/providers/buy.py:294`](services/agent/providers/buy.py#L294) · [`services/agent/providers/spec.py:140`](services/agent/providers/spec.py#L140) · [`services/registry/steer.py:545`](services/registry/steer.py#L545) |
| **Muse Image** | Meta Model API | Completes the broken region of the photo (accepted only if markers and the intact part are unchanged), an in-place repair preview and an install card (both labelled AI images) | [`services/agent/evidence.py:449`](services/agent/evidence.py#L449) · [`services/metrology/recon_gate.py:205`](services/metrology/recon_gate.py#L205) · [`services/media/preview.py:78`](services/media/preview.py#L78) |
| **Muse Voice Transcribe** | Meta Model API | Hindi/English voice edits ("make the hole a bit bigger") mapped to knob changes, live while you talk (realtime stream relayed by the API, knob names as keywords) or from a recorded clip, and spoken answers | [`services/media/voice.py:452`](services/media/voice.py#L452) · [`services/api/voice_live.py:139`](services/api/voice_live.py#L139) |
| **SAM 3 (open weights)** | open weights (Modal GPU) | All-open-weights segmentation path and bench | [`infra/modal/sam3.py:47`](infra/modal/sam3.py#L47) |
<!-- END:meta-tooling -->

With `OPEN_WEIGHTS_ONLY=1` every stage runs on open weights (Muse Spark Open, Muse Glimmer 30B, SAM 3 on a Modal GPU); stages
with no open-weights model (Muse Image, Muse Wonder spec search, Voice) fall back to a labelled deterministic mock, and the run
says so.

**Written but not claimed:** iterative Muse Image edits (`edit_image`) exist in the provider layer but are not wired into
the product yet, so they are not counted above.

## How it works

```
 photo or walk-around clip on the screen mat
   │
   ├─▶ capture gate (markers, blur, tilt, glare, one part only) ── reject with a plain-words reason
   ▼
 ArUco pose ─▶ SAM 3.1 mask (+ point cuts for holes, + video tracking for heights) ─▶ millimetres, each with ±σ and a source
   │                                                         (measured · stated by you · cited · inferred)
   ▼
 Muse Spark: PartSpec ─▶ Muse Spark Open: CadQuery ─▶ sandbox ─▶ verifier: render with the photo's camera,
       ▲                          ▲                               edges, Hausdorff mm, feature residuals, part tests
       │ questions                └── fix agent operates the tools (≤ 6 committed rounds) ◀──┘
   the human                                                                  │
                                         Muse Glimmer (veto only) ◀───────────┘
                                                │
                     Verified (code-decided) ───┴─── honest best effort (needs your OK) ─── failed (no export)
                                                │
          STL · 3MF · STEP · part.py · 1:1 screen fit check · install card · zip · registry (REST + MCP)
```

- **Screen mat.** The web app draws a ring of ArUco markers at true 1:1 scale on a laptop or tablet. You calibrate the scale once
  by matching an ID-1 bank card (85.60 × 53.98 mm). A plain-paper A4 mat PDF works too. Open the capture page on your phone with
  the QR code; the laptop follows the job live.
- **Measurement.** Sub-pixel marker corners → homography and camera pose → SAM 3.1 mask → contour in mm with exact parallax
  correction for the part's thickness, circle/slot fitting, see-through hole fitting for thick parts, and an uncertainty per
  value. A 5–10 s walk-around clip gives heights a single top photo cannot.
- **Broken parts.** The broken region is masked out of the comparison: the part is verified on its intact region only, and the
  missing piece comes from the template, your stated size, a cited spec or a gated Muse Image completion, each labelled.
- **Agent loop.** The fix agent can inspect residuals, measure a feature, cut out a point, render a candidate, run the part
  tests and set knobs. Rendering is free; committing a change costs one of six rounds and passes the same guards.
- **Verified** means: all P0 part tests pass, Hausdorff ≤ 0.5 mm on every view, IoU ≥ 0.97 on views large enough for IoU to
  mean something, and no veto from the independent judge. Only the verifier can set it.
- **Screen fit check.** Before printing, the model's 1:1 outline is drawn on the calibrated screen. You lay the real part on it
  and photograph it, and the same verifier says pass or fail with an overlay.

## Results

Every number here is written by `make bench` (`tools/readme.py` reads `eval/reports/latest/`). Ground-truth sources are never
mixed: synthetic photos (exact), standard reference objects (published specs), real broken parts (school ruler, ±0.5 mm).

<!-- BEGIN:bench -->
Generated 2026-10-28T16:03:49+00:00 at commit `1c91d0f00cd68f47d8c5c4fd3e268a3598866335` · mode **mock**.

> **These rows come from deterministic mock providers (no API keys yet).** They check that the pipeline, verifier and scorer work end to end; they do **not** measure any model. Live numbers replace them after `make live`.

**Synthetic bench (exact ground truth)**

N = 6 · photos: synthetic renders · ground truth: `synthetic_exact` · CI: 95 %: bootstrap over samples (2000 resamples, seeded) for mean errors; Wilson for rates

| config | n | median_abs_err_mm | mean_abs_err_mm | mean_ci95 | pass@0.5 | verified_rate | verified_but_off | median_iters |
|---|---|---|---|---|---|---|---|---|
| B0 | 6 | 1.05 | 2.43 | [1.132, 3.602] | 0.167 | 0 | 0/0 | 1 |
| B1 | 6 | 0.3 | 0.49 | [0.247, 0.739] | 0.333 | 0.167 | 0/1 | 1 |
| B2 | 6 | 0.3 | 0.515 | [0.150, 0.986] | 0.333 | 0.333 | 0/2 | 2 |
| PS | 6 | 0.3 | 0.515 | [0.150, 0.986] | 0.333 | 0.333 | 0/2 | 2 |
| PS-noTemplate | 6 | 0.14 | 2.319 | [0.685, 4.351] | 0.167 | 0.167 | 0/1 | 1 |
| PS-noJudge | 6 | 0.3 | 0.515 | [0.150, 0.986] | 0.333 | 0.333 | 0/2 | 2 |
| PS-noHeightCorr | 6 | 0.4 | 0.605 | [0.333, 0.941] | 0.167 | 0 | 0/0 | 4 |

_synthetic: seeded subset of 6/60 bench samples (seed 7); headline = PS on the held-out split (6 samples); MOCK providers: these numbers check the pipeline, they do not measure any model_

**Reference objects (vs published specs)**

N = 4 · photos: synthetic renders · ground truth: `reference_spec` · CI: 95 %: bootstrap over samples (2000 resamples, seeded) for mean errors; Wilson for rates

| config | n | median_abs_err_mm | mean_abs_err_mm | mean_ci95 | pass@0.5 | verified_rate | verified_but_off | median_iters |
|---|---|---|---|---|---|---|---|---|
| B0 | 4 | 0.268 | 1.116 | [0.216, 2.498] | 0.25 | 0 | 0/0 | 1 |
| B1 | 4 | 0.131 | 0.453 | [0.125, 0.890] | 0.5 | 0 | 0/0 | 1 |
| B2 | 4 | 0.05 | 0.121 | [0.039, 0.290] | 0.75 | 0.25 | 0/1 | 1.5 |
| PS | 4 | 0.05 | 0.121 | [0.039, 0.290] | 0.75 | 0.25 | 0/1 | 1.5 |
| PS-noTemplate | 4 | 0.131 | 0.175 | [0.066, 0.307] | 0.75 | 0.25 | 0/1 | 1.5 |
| PS-noJudge | 4 | 0.05 | 0.121 | [0.039, 0.290] | 0.75 | 0.25 | 0/1 | 1.5 |
| PS-noHeightCorr | 4 | 0.259 | 0.527 | [0.241, 0.890] | 0.25 | 0 | 0/0 | 3.5 |

_reference_objects: 4 synthetic renders; real photos pending (data/real/reference_objects/); headline = PS on the held-out split (4 samples); MOCK providers: these numbers check the pipeline, they do not measure any model_

**Real broken parts (vs school ruler, ±0.5 mm)**

_Pending — real_ruler: no real parts with ruler ground truth yet (data/real/<part>/gt.yaml)._

**Measurement only (photo → mm, no CAD loop)**

```
synthetic                        photos 120 accepted  97  dims N=228  mean 0.468 [0.370, 0.580]  median 0.200  P90 1.039  max 5.316  ≤0.5 77 %
  top view, flat parts                   dims N= 82  mean 0.226 [0.181, 0.273]  median 0.165  P90 0.544
  top view, parts with tall features     dims N= 98  mean 0.494 [0.324, 0.690]  median 0.129  P90 1.378
  expected rejections (white part on light stage): 5/6 correctly rejected
reference_objects_synthetic      photos  30 accepted  21  dims N= 35  mean 0.178 [0.114, 0.264]  median 0.087  P90 0.307  max 1.312  ≤0.5 91 %
reference_objects_real           pending (no photos)
real_parts_ruler                 pending (no photos)
EXIT GATE (mean ≤ 0.4 mm): synthetic 0.468 FAIL · reference objects [reference_objects_synthetic] 0.178 PASS → FAIL
```
<!-- END:bench -->

## Run it

```bash
make setup        # uv sync (Python 3.12) + pnpm install + generated types
make dev          # seeds the registry from the bundled samples, starts API :8000 and web :3000
make test         # unit tests, no network, no keys
make bench        # rebuilds every results table from stored runs (no keys needed)
make smoke        # one call per provider: ✅ live · ⚠️ key missing (mock) · ❌ failed
make live         # smoke, then re-run the benches on live models
```

With no keys every model stage runs as a deterministic mock, and the app says so on every page. Add keys to `.env` (see
`.env.example`) and run `make live`. Self-hosting Glimmer and SAM 3 on Modal: [`infra/modal/README.md`](infra/modal/README.md).

## Pages

| Page | What it is for |
|---|---|
| `/fix` | Upload photos or a clip (or scan the QR on your phone), narrate the clip, tap holes or the broken edge, describe the part in English or Hinglish |
| `/jobs/{id}` | Live workspace: photos, 3D model, error per view, the agent's thoughts and tool calls, knobs, live Hindi/English voice edits, a buy-or-print card, exports with "open in slicer", and a fit-test coupon that learns your printer's clearance |
| `/jobs/{id}/fit` | 1:1 screen fit check |
| `/parts` | The registry: verified parametric parts with knobs, fit presets per printer and material, share cards |
| `/requests` | Parts people need that nobody has made yet; vote on them |
| `/factory` | Muse Wonder plans part families; a human approves before anything is published |
| `/lessons` | What the agent learned from failures, promoted only with evidence |
| `/shop` | Batch jobs for a print shop, with a job-sheet PDF |
| `/results`, `/models`, `/judges` | Benchmarks, per-stage model routing, stored replays and a lying model being caught |

## For agents and developers

- REST: `/api/v1` ([docs/API.md](docs/API.md), OpenAPI at `/api/v1/openapi.json`)
- MCP: `uv run python -m services.mcp --stdio`, or streamable HTTP at `/mcp` — tools `search_parts`, `get_part`, `get_variant`,
  `bake`, `find_matching`, `list_families`, `measure_photo`, `start_fix_job`, `get_job`, `report_need`
  ([services/mcp/README.md](services/mcp/README.md))
- Agent rules: never rescale a part to force a fit — change the right knob; if no part matches, say so and call `report_need`;
  report which dimensions were measured and which were assumed.

## Limitations (honest)

- No live model call has been made yet (no API keys at the time of writing). All current results use deterministic mocks and
  synthetic photos, and are labelled that way.
- A single top photo cannot resolve heights above the stated plate thickness; the walk-around clip and side photo handle it,
  but raw top-view measurements of tall features are biased (see the measurement-only table).
- White or light-grey parts need the dark screen stage; the capture gate asks for it.
- Flexible parts (rubber seals, gaskets) and free-form objects (figurines, sculptures) are refused with a reason: a rigid
  parametric model cannot replace them.
- Real reference-object photos and real broken parts are pending; those tables say "pending" until they exist.
- No physical print results yet; the physical proof is the screen fit check. Prints are optional and will only be reported if
  made.

## Repository map

| Path | What |
|---|---|
| `services/metrology` | mats, card scale, capture gate, pose, segmentation, point cuts, walk-around clips, mm features, fit check |
| `services/geom_worker` | sandboxed CadQuery execution, exporters, bake cache |
| `services/verifier` | camera-frame comparison, metrics, part tests, the pass rule |
| `services/agent` | orchestrator, fix agent and its tools, providers, templates, prompts, jobs and replays |
| `services/api`, `services/mcp`, `services/registry` | REST + SSE, MCP, registry, factory |
| `apps/web` | Next.js app |
| `tools/synth`, `eval` | synthetic photo generator with exact ground truth, benches, suites and reports |
| `docs/` | architecture, API, decisions, progress |

## Built during the hackathon

All code in this repository was written during the hackathon (from Oct 26 2026, 12:00 PM ET); see the commit history.

## Credits

<!-- Prashant writes this section. -->

## License

MIT for the code. Registry parts: CC BY 4.0.
