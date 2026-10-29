# PartSmith

**Photo of a broken part → a measured, verified, printable replacement — no caliper; your laptop screen is the ruler.**

<!-- BEGIN:links -->
Live site _(coming)_ · Video _(coming)_ · Judges page _(coming)_ · Try a sample _(coming)_ · [Results](#results) · [Reproduce](eval/REPRODUCE.md) · [Docs](docs/README.md)
<!-- END:links -->

[![Replay of a stored PartSmith run with mock providers (synthetic L-bracket): the error chart steps down from the first build to within the limit and the run ends VERIFIED; then the job page opens the fail → fix rounds' overlays and shows the 3D model](docs/media/hero.gif)](docs/media/hero.gif)

<sub>Recorded from the web app in replay mode with mock providers (`make media`); the numbers are the stored run's own.</sub>

<!-- BEGIN:status -->
> **Status: live providers** · bench report 2026-10-29 at commit `304f933` plus uncommitted changes · real photos measured: 0 · real parts with ruler ground truth: 0 · real repairs logged: 0
>
> Numbers below come from live model calls on synthetic photos. Some stages ran as labelled mocks: see `provider_modes` in `eval/reports/latest/report.json`. Real-photo results are pending and say so in their tables.
<!-- END:status -->

<!-- BEGIN:headline -->
| Number | What it counts | Source |
|---|---|---|
| **17/17** | lying-model attacks blocked by code; suite: lying-brain (scripted mock attacks; no model calls) | `eval/reports/latest/bypass.json` |
| **0/2** synthetic · **0/4** reference objects | verified parts that are > 0.5 mm off the ground truth (off / verified) | `eval/reports/latest/report.json` → `tables.*.headline.verified_but_off` |
| **6/6** control · **10/10** red-team | intact photos accepted · bad or unsuitable photos rejected or refused | `eval/reports/latest/report.json` → `tables.control`, `tables.redteam` |
| **0.1 mm** | median absolute error per dimension, synthetic photos, config PS, n = 12 | `eval/reports/latest/report.json` → `tables.synthetic.headline` |
<!-- END:headline -->

**The model proposes; code decides.** Entry for the Meta Global AI Developer Hackathon (Indie Developer track, problem
statement: Push the Frontier).

## The problem

A cupboard latch snaps, a battery cover goes missing, a cable clip cracks. The appliance still works, but the plastic piece
is not sold on its own, so the whole thing goes in the bin. A 3D print would fix it, but it has to be modelled to within half
a millimetre or it will not fit. That takes a caliper, CAD skills and an hour, which most people do not have.

PartSmith turns your laptop screen into a calibrated measuring mat. You lay the part on it and take a photo (or walk around
it with a short video). Meta's models look, point, cut out and write CadQuery. Deterministic code measures, renders the model
from the photo's own camera and decides whether it matches. The result is a parametric part you can print, re-size with
named knobs, or send to a print shop, and it joins an open registry that people and coding agents can search over REST and
MCP. No printer, caliper or special paper needed.

## 30-second judge path

| | |
|---|---|
| Watch a stored run, step by step | `/judges` in the web app (replays are labelled "replay") |
| Watch a lying model get caught | `/judges` → *A lying model, caught*: a scripted model says "VERIFIED", the verifier's overlay shows its real error and the export is blocked |
| See the same refusal in your terminal | `make lie`: the scripted model's claim, the verifier's real max error against the limit and `export BLOCKED (<reason>)`. `eval.bypass --demo` exits 3 when the export is refused; for this demo the non-zero exit is the success case, and `make lie` reports it as OK |
| Run it yourself with no keys | `make setup && make dev` → <http://localhost:3000> → **Fix a part → Try a sample** |
| Which model ran where, live or mock | `/models` (per stage, with open-weights badges) |
| Numbers and how they were made | [Results](#results) · `/results` · [`eval/REPRODUCE.md`](eval/REPRODUCE.md) |
| What a model wrote vs what we wrote | [Model-written vs hand-written](#model-written-vs-hand-written) · [Built during the hackathon](#built-during-the-hackathon) |
| For agents | `/agents`, `/llms.txt`, MCP at `/mcp` |

[![Four screens from the web app in replay mode with mock providers: (a) a lying model caught, the export blocked; (b) Colour by source on the job page; (c) the impact panel and buy-or-print card; (d) the walk-around clip and voice note slots on the fix page](docs/media/grid.png)](docs/media/grid.png)

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
| Intact parts, normal photos → accepted | 6/6 handled as expected, 95 % CI [0.61, 1.00] | `eval/reports/latest/report.json` → `tables.control` |
| Photos that must be rejected or refused | 10/10 handled as expected, 95 % CI [0.72, 1.00] | `eval/reports/latest/report.json` → `tables.redteam` |
| Verified synthetic parts that are > 0.5 mm off the ground truth | 0/2 (config PS) | `eval/reports/latest/report.json` → `tables.synthetic` |
| Verified reference objects that are > 0.5 mm off the ground truth | 0/4 (config PS) | `eval/reports/latest/report.json` → `tables.reference_objects` |
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
| **SAM 3.1** | Meta Model API | The measuring instrument: text-prompted part masks, point-prompted feature cuts (holes, slots, tapped points) and video tracking of a walk-around clip. Code turns every mask into millimetres | [`services/agent/providers/routing.py:108`](services/agent/providers/routing.py#L108) · [`services/metrology/segment.py:664`](services/metrology/segment.py#L664) · [`services/agent/evidence.py:166`](services/agent/evidence.py#L166) · [`services/agent/evidence.py:239`](services/agent/evidence.py#L239) |
| **Muse Spark 1.3** | Meta Model API | Understand stage: family, features, broken region, unknowns (strict PartSpec JSON), and the pixel it saw each hole or slot at, which SAM 3.1 then cuts and code measures. Watches and listens to a narrated walk-around clip and points at the features it hears about (frame and pixel), kept only if they land on the part | [`services/agent/orchestrator.py:1097`](services/agent/orchestrator.py#L1097) · [`services/agent/evidence.py:57`](services/agent/evidence.py#L57) · [`services/agent/evidence.py:314`](services/agent/evidence.py#L314) |
| **Muse Spark Open** | open weights (Baseten / Fireworks / Together) | CadQuery builder, and the fix agent that operates PartSmith's own tools (inspect residuals, measure, segment, render, run tests, set knobs) until the verifier agrees | [`services/agent/orchestrator.py:1548`](services/agent/orchestrator.py#L1548) · [`services/agent/agent_loop.py:471`](services/agent/agent_loop.py#L471) |
| **Muse Glimmer 30B** | open weights (llama.cpp on a Modal GPU) | Independent veto-only judge, shown side-by-side photo and model crops zoomed on the verifier's worst spots | [`services/agent/orchestrator.py:2174`](services/agent/orchestrator.py#L2174) · [`infra/modal/glimmer.py:51`](infra/modal/glimmer.py#L51) |
| **Muse Wonder** | Meta Model API | Finds a published spec for the named appliance with web search. Code accepts a value only if a search really ran and its URL is one the search returned; cited values fill unknowns and never override a measurement. Also finds the original part's price with search grounding for the buy-or-print card (a price is kept only with its source link and a quote showing it) and plans part families for the factory | [`services/agent/evidence.py:398`](services/agent/evidence.py#L398) · [`services/agent/providers/buy.py:294`](services/agent/providers/buy.py#L294) · [`services/agent/providers/spec.py:140`](services/agent/providers/spec.py#L140) · [`services/registry/steer.py:545`](services/registry/steer.py#L545) |
| **Muse Image** | Meta Model API | Completes the broken region of the photo (accepted only if markers and the intact part are unchanged), an in-place repair preview and an install card (both labelled AI images) | [`services/agent/evidence.py:569`](services/agent/evidence.py#L569) · [`services/metrology/recon_gate.py:205`](services/metrology/recon_gate.py#L205) · [`services/media/preview.py:78`](services/media/preview.py#L78) |
| **Muse Voice Transcribe** | Meta Model API | Hindi/English voice edits ("make the hole a bit bigger") mapped to knob changes, live while you talk (realtime stream relayed by the API, knob names as keywords) or from a recorded clip, and spoken answers | [`services/media/voice.py:452`](services/media/voice.py#L452) · [`services/api/voice_live.py:139`](services/api/voice_live.py#L139) |
| **SAM 3 (open weights)** | open weights (Modal GPU) | All-open-weights segmentation path and bench | [`infra/modal/sam3.py:47`](infra/modal/sam3.py#L47) |
<!-- END:meta-tooling -->

With `OPEN_WEIGHTS_ONLY=1` every stage runs on open weights (Muse Spark Open, Muse Glimmer 30B, SAM 3 on a Modal GPU); stages
with no open-weights model (Muse Image, Muse Wonder spec search, Voice) fall back to a labelled deterministic mock, and the run
says so.

**Written but not claimed:** iterative Muse Image edits (`edit_image`) exist in the provider layer but are not wired into
the product yet, so they are not counted above.

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

```mermaid
flowchart TD
    photo["Photo or walk-around clip<br/>on the screen mat"] --> gate{"Capture gate (code)<br/>markers · blur · tilt · glare · one part"}
    gate -->|"fails"| retake["Retake, with a plain-words reason"]
    gate -->|"passes"| metro["Metrology (code): ArUco pose + SAM 3.1 masks<br/>→ millimetres, each with ±σ and a source"]
    metro --> understand["Understand: Muse Spark<br/>→ PartSpec JSON: family, features, break, unknowns"]
    understand -->|"unknowns"| ask["Ask the human"]
    ask --> plan
    understand --> plan["Plan: family template or free code"]
    plan --> build["Build: Muse Spark Open<br/>writes a CadQuery program"]
    build --> sandbox["Sandbox (code)<br/>AST allowlist · rlimits · no network"]
    sandbox --> verifier{"Verifier (code)<br/>render from the photo's camera,<br/>Hausdorff mm, IoU, part tests"}
    verifier -->|"misfit"| fix["Fix agent: Muse Spark Open<br/>operates PartSmith's tools, bounded rounds"]
    fix -->|"guarded knob and code edits"| sandbox
    verifier -->|"passes"| judge["Muse Glimmer judge<br/>veto only"]
    verifier -->|"rounds used up"| exportgate
    judge --> exportgate{"Export gate (code)"}
    exportgate -->|"verified"| out["STL · 3MF · STEP · part.py<br/>screen fit check · install card"]
    exportgate -->|"best effort"| ack["Download only after an explicit OK"]
    exportgate -->|"failed"| noexport["No export"]
    ack --> out
    out --> registry[("Registry<br/>REST + MCP")]

    clip["Narrated walk-around clip"] -.->|"Muse Spark points at features · SAM 3.1 tracks heights"| metro
    image["Muse Image completes the broken region"] -.->|"completion gate: markers and intact part unchanged"| understand
    wonder["Muse Wonder: cited spec values"] -.->|"only URLs the search returned · never overrides a measurement"| understand
    buy["Muse Wonder: price of the original part"] -.->|"buy-or-print card · grams and cost from the mesh"| out
    voice["Muse Voice Transcribe: Hindi/English edits"] -.->|"clamped knob edits → re-bake in the sandbox"| sandbox
```

Solid arrows are the main pipeline; dotted arrows are side paths whose output code accepts only after a check. Boxes that
name a model are model calls; boxes marked "(code)" are deterministic, hand-written checks. The same diagram, with the runtime layout, is in
[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

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

## Model-written vs hand-written

At run time the models write **data**: specs, programs, points, tool calls, citations and images. They never write or run
the code that judges that data. Everything a model produces lands in the job's run directory
(`$PARTSMITH_HOME/runs/<job>/`) as a labelled file or event, next to the code's verdict.

| Written by a model at run time | Model | Where it lands |
|---|---|---|
| PartSpec JSON: family, features, broken region, unknowns (code then fills in measured values and their sources) | Muse Spark | `partspec.json` |
| Feature points: the pixel each hole or slot is at, and the frame and pixel tied to words in a narrated clip | Muse Spark | `run.jsonl` (`focus` events), then SAM 3.1 cuts and code measures |
| CadQuery programs (`PARAMS` + `build(p)`) and each fix round's edits | Muse Spark Open | `part.py`, `run.jsonl` |
| The fix agent's tool calls (inspect residuals, measure, segment, render, run tests, set knobs) and reasoning summaries | Muse Spark Open | `run.jsonl` (`tool_call`, `thought` events) |
| Masks of the part and of tapped points; video tracks | SAM 3.1 | `run.jsonl` artifacts |
| Cited spec values and prices, with the search URLs | Muse Wonder | `run.jsonl`, the buy-or-print card |
| Completion of the broken region, repair preview, install card (labelled AI images) | Muse Image | `run.jsonl` artifacts |
| Veto notes | Muse Glimmer | `verification.json` → `vetoes` |
| Transcripts of voice edits | Muse Voice Transcribe | `run.jsonl` |

| Hand-written, deterministic code | Where |
|---|---|
| Metrology: mats, pose, capture gate, mask → mm, circle and slot fits, uncertainty per value | [`services/metrology`](services/metrology) |
| Verifier: render from the photo's camera, metrics, part tests, the pass rule; the only writer of `verified` and `verification.json` | [`services/verifier`](services/verifier) |
| Guards on model output: edit caps, no uniform rescale, knob ranges; acceptance checks for points, citations and completions | [`services/agent/guards.py`](services/agent/guards.py) · [`services/agent/evidence.py`](services/agent/evidence.py) · [`services/agent/providers/spec.py`](services/agent/providers/spec.py) · [`services/metrology/recon_gate.py`](services/metrology/recon_gate.py) |
| Sandbox for model-written CadQuery | [`services/geom_worker`](services/geom_worker) |
| Export gate | [`services/verifier/ship.py`](services/verifier/ship.py) · [`services/registry/gate.py`](services/registry/gate.py) |
| Orchestrator, jobs, family templates, prompts, the labelled mock brain used with no keys | [`services/agent`](services/agent) |
| Registry, REST API, MCP server | [`services/registry`](services/registry) · [`services/api`](services/api) · [`services/mcp`](services/mcp) |
| Web app | [`apps/web`](apps/web) |
| Benches, scorers, lying-model suite, synthetic photo generator | [`eval`](eval) · [`tools/synth`](tools/synth) |

## Results

Every number here is written by `make bench` (`tools/readme.py` reads `eval/reports/latest/`). Ground-truth sources are never
mixed: synthetic photos (exact), standard reference objects (published specs), real broken parts (school ruler, ±0.5 mm).

<!-- BEGIN:bench -->
Generated 2026-10-29T20:43:37+00:00 at commit `304f9333bc2a5f23791c8529d43a990ad18c1c5f` · mode **live**.

**Synthetic bench (exact ground truth)**

N = 12 · photos: synthetic renders · ground truth: `synthetic_exact` · CI: 95 %: bootstrap over samples (2000 resamples, seeded) for mean errors; Wilson for rates

| config | n | median_abs_err_mm | mean_abs_err_mm | mean_ci95 | pass@0.5 | verified_rate | verified_but_off | median_iters | usd_per_job |
|---|---|---|---|---|---|---|---|---|---|
| B1 | 12 | 0.18 | 0.856 | [0.313, 1.674] | 0.083 | 0.083 | 0/1 | 1 | $0.0681 |
| PS | 12 | 0.1 | 0.604 | [0.221, 1.196] | 0.25 | 0.167 | 0/2 | 6 | $0.2091 |
| PS-noTemplate | 12 | 0.23 | 0.914 | [0.481, 1.574] | 0.083 | 0.167 | 1/2 | 4.5 | $0.2130 |

_headline = PS on the held-out split (12 samples)_

**Reference objects (vs published specs)**

N = 8 · photos: synthetic renders · ground truth: `reference_spec` · CI: 95 %: bootstrap over samples (2000 resamples, seeded) for mean errors; Wilson for rates

| config | n | median_abs_err_mm | mean_abs_err_mm | mean_ci95 | pass@0.5 | verified_rate | verified_but_off | median_iters | usd_per_job |
|---|---|---|---|---|---|---|---|---|---|
| B1 | 8 | 0.04 | 0.142 | [0.027, 0.330] | 0.75 | 0.25 | 0/2 | 1 | $0.0492 |
| PS | 8 | 0.05 | 0.155 | [0.052, 0.303] | 0.75 | 0.5 | 0/4 | 2.5 | $0.1631 |
| PS-noTemplate | 8 | 0.066 | 0.159 | [0.049, 0.336] | 0.75 | 0.5 | 0/4 | 2.5 | $0.2073 |

_headline = PS on the held-out split (8 samples)_

**Real broken parts (vs school ruler, ±0.5 mm)**

_Pending — no real parts with ruler ground truth yet (data/real/<part>/gt.yaml, see eval/REPRODUCE.md)._

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

- The status line at the top says whether the current numbers come from mock or live providers. With mock providers they
  check the pipeline, verifier and scorer; they do not measure any model. Every table repeats the label.
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
| `services/verifier` | camera-frame comparison, metrics, part tests, the pass rule, the export gate |
| `services/agent` | orchestrator, fix agent and its tools, providers, templates, prompts, jobs and replays |
| `services/api`, `services/mcp`, `services/registry` | REST + SSE, MCP, registry, factory |
| `apps/web` | Next.js app |
| `tools/synth`, `eval` | synthetic photo generator with exact ground truth, benches, suites and reports |
| `tools/readme.py` | writes every generated block of this README |
| `docs/` | architecture, API, decisions, progress: see the [docs index](docs/README.md) |

## Built during the hackathon

All code in this repository was written during the hackathon (from Oct 26 2026, 12:00 PM ET). This table and the commit list
are computed from `git log`, so they stay true as the history grows.

<!-- BEGIN:built -->
**44 commits** between 2026-10-27 05:59 ET and 2026-10-29 14:08 ET; the hackathon started 2026-10-26 12:00 ET. Commits dated before the start: **0**.

| Area | Files added | Lines added: code and docs | Lines added: data, reports, lockfiles, generated | First commit | Last commit |
|---|---|---|---|---|---|
| `services/` (Python backend) | 250 | 51,245 | 0 | 2026-10-27 | 2026-10-29 |
| `apps/web/` (web app) | 244 | 24,967 | 2,384 | 2026-10-27 | 2026-10-29 |
| `eval/` (benches and reports) | 325 | 5,299 | 65,426 | 2026-10-27 | 2026-10-29 |
| `packages/` (typed contracts) | 11 | 1,360 | 5,504 | 2026-10-27 | 2026-10-29 |
| `tools/` (synthetic data, mats, generators) | 32 | 5,156 | 0 | 2026-10-27 | 2026-10-29 |
| `infra/` (Modal, deploy) | 12 | 1,014 | 86 | 2026-10-27 | 2026-10-29 |
| `docs/` | 16 | 1,439 | 7 | 2026-10-27 | 2026-10-29 |
| `data/` (samples, replays) | 4,134 | 0 | 633,853 | 2026-10-27 | 2026-10-29 |
| root files | 15 | 1,245 | 8,271 | 2026-10-27 | 2026-10-29 |
| **Total** | **5,039** | **91,725** | **715,531** | | |

<details><summary>Every commit since the start, oldest first</summary>

| Date | Commit | Subject |
|---|---|---|
| 2026-10-27 05:59 ET | `ec85b78` | chore: scaffold monorepo, typed contracts, job state machine and registry store |
| 2026-10-27 06:27 ET | `c2d834e` | feat(providers): zero-key provider layer, media clients, Modal infra and smoke test |
| 2026-10-27 06:36 ET | `1ebe4ff` | feat(metrology): screen/paper mats, card scale, capture gate, parallax-corrected measurement, screen fit check |
| 2026-10-27 06:41 ET | `07f8bcc` | feat(geometry): sandboxed CadQuery worker, deterministic verifier and 10 family templates |
| 2026-10-27 06:44 ET | `7391a0d` | feat(web): Next.js app with design system, screen mat, card calibration, job workspace and registry pages |
| 2026-10-27 07:17 ET | `2a07432` | feat(agent): bounded fix loop with code-decided verification, deterministic mock brain, service facade and CLI |
| 2026-10-27 07:18 ET | `4a173f6` | feat(synth,eval): synthetic photo generator with exact ground truth, reference objects and measure-only bench |
| 2026-10-27 07:19 ET | `88b0991` | feat(api,mcp,registry): REST API with SSE, MCP server, registry operations, Steer factory, seeding and thumbnails |
| 2026-10-27 07:28 ET | `3237b2f` | feat(verifier): camera-frame comparison, like-for-like part tests and per-view gates |
| 2026-10-27 07:57 ET | `6f7f5fb` | feat(eval): full-loop bench with baselines, ablations, reports and regression check |
| 2026-10-27 08:01 ET | `527018d` | feat(metrology): see-through hole fitting, shadow suppression, dark stage contrast gate, thin side views, round profiles |
| 2026-10-27 08:03 ET | `0827de1` | docs(readme): judge-facing README with script-generated Meta tooling table and bench tables |
| 2026-10-27 08:24 ET | `0da1e26` | feat(synth,eval): dark screen stage, white-on-light rejection cases, round profiles and flat/tall split in the measure bench |
| 2026-10-27 08:28 ET | `ddd4526` | feat(web): integrate with the live API, SSE pass-through, dark stage, live Playwright suite |
| 2026-10-27 08:34 ET | `a705786` | fix(api): integration bugs found by the live web suite |
| 2026-10-27 08:50 ET | `c605235` | feat(metrology): robust dark-stage segmentation, stricter shadow model, honest side-view ranges |
| 2026-10-27 08:51 ET | `36eda42` | feat(agent): camera-frame verification in the loop, retake handling, stronger deterministic fixer |
| 2026-10-27 08:59 ET | `e3238b5` | feat(registry): dedupe publishing by program identity; repo-wide strict typing |
| 2026-10-27 09:10 ET | `0b37762` | fix(verifier): model re-measured with metrology's own footprint code; round views verified in the photo frame |
| 2026-10-27 09:30 ET | `cb9d823` | fix(verifier): compare sub-pixel edges, not the binary mask's blur halo; scale-aware IoU gate |
| 2026-10-27 09:38 ET | `7cbb37c` | feat(web): polish pass — part-cropped photo panel, server-rendered registry, lazy 3D, keyboard and screen-reader paths |
| 2026-10-27 09:49 ET | `1d815f4` | feat(agent): region-aware fixing, new template knobs and boss detection for free code |
| 2026-10-27 10:04 ET | `0910de1` | feat(eval,replays): fresh mock bench, seeded registry replays for the judge path |
| 2026-10-27 10:05 ET | `426c1bf` | feat(eval): real-part split freezing and photo-source labels on every results table |
| 2026-10-27 10:14 ET | `c591933` | perf(web): mobile Lighthouse 95+ — zod/mini contract checks, lean UI primitives, server-rendered sections, subset fonts |
| 2026-10-27 10:18 ET | `1da606f` | docs: quality scorecard, handoff, progress log and FAQ for the zero-key build |
| 2026-10-27 10:26 ET | `5c301cc` | feat(templates): hinge knuckle placement and hook hole-row knobs; pattern knobs probed first |
| 2026-10-27 10:46 ET | `732ee27` | feat(schemas): round-2 contracts — cited values with citations, thought/tool_call/focus events, orbit view, new artifact kinds |
| 2026-10-27 13:47 ET | `11c3ed1` | feat(metrology): SAM point-prompt feature fits, walk-around orbit measurement, Muse Image reconstruction gate |
| 2026-10-27 13:47 ET | `25042a8` | feat(providers): Spark/Wonder tool-calling loop, SAM 3.1 point and video prompts, cited spec lookup, Muse Image edits, realtime voice |
| 2026-10-27 13:53 ET | `66078af` | feat(verifier): functional probe tests, single export gate with a lying-brain suite, measured program-vs-mesh |
| 2026-10-27 14:03 ET | `fc0cf16` | feat(api,registry): product catalogue, export gate on every download, bundles, presets, requests, lessons, batches, usage |
| 2026-10-27 14:26 ET | `ef58595` | feat(agent): Spark drives the instrument — agentic fixer over our metrology and verifier tools, plus points, orbit, cited specs and gated completions |
| 2026-10-27 14:44 ET | `51174b5` | feat(synth,eval): walk-around clips, broken parts, control and red-team suites, failure taxonomy, provenance, impact and open-weights reports |
| 2026-10-27 15:00 ET | `cc3fed8` | feat(verifier): walk-around frames verify heights; broken parts verified on the intact region only |
| 2026-10-27 15:14 ET | `061ce7c` | feat(agent,api): refuse flexible and organic objects; fix uploads accept a walk-around clip and tapped feature points |
| 2026-10-27 15:22 ET | `4d7ab79` | fix(metrology): robust walk-around height, plausibility checks on Muse Image completions, single-part capture check |
| 2026-10-27 18:34 ET | `b3da84b` | feat: round-2 web, gated exports everywhere, two-part rejection, fresh evidence and judge-first README |
| 2026-10-27 20:21 ET | `1c91d0f` | feat(verifier,agent): broken parts locate the break and never copy it; fake-break attack; verified-but-off column |
| 2026-10-28 12:13 ET | `a1cc532` | feat: round 3 — bounded top views, buy-or-print, narrated walk-around, live voice, coupon learning, lie caught, deploy files |
| 2026-10-28 13:53 ET | `d7586ff` | feat: stated lengths, SAM negatives and confidence, value sources in 3D, fail-to-fix strip, judge-first README |
| 2026-10-28 14:36 ET | `7055646` | feat(web): README hero media from the real app; fix /fix clip crash and a stuck 3D camera |
| 2026-10-29 07:23 ET | `95790e6` | feat: first live runs, fits-where-it-goes, repair passport, live fixes |
| 2026-10-29 14:08 ET | `304f933` | feat: live lessons round 2, slow-route fallback, second live seed |

</details>

_Generated from `git log --numstat --summary` by `tools/readme.py` (author dates, Eastern Time). Lines added are summed over commits, so a file rewritten twice counts twice. A commit made after the last regeneration appears at the next `make bench`._
<!-- END:built -->

## Credits

<!-- Prashant writes this section. -->

## License

MIT for the code. Registry parts: CC BY 4.0.
