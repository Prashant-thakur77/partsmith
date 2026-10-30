# Decisions (ADR log)

One paragraph each, newest last.

**2026-10-27 — One CPU Python environment, process isolation for untrusted code.** The API, agent, metrology, verifier and
CAD worker share one `uv` environment (cadquery 2.8.0, trimesh 5.2.0, OpenCV 5, numpy 2). They don't conflict; the
numpy<2 conflict is only with SAM 3 open weights, which run on a Modal GPU in their own image. Untrusted LLM-written
CadQuery never runs in the API process: `services/geom_worker/sandbox.py` checks it against an AST allowlist and then runs
it in a child process with CPU, memory and file-size limits, no network and a throwaway working directory.

**2026-10-27 — Screen mat first, plain-paper mat second.** There is no printer, caliper or special paper on the team. The
primary calibration surface is an ArUco marker ring drawn full-screen at 1:1 on a laptop or tablet, scaled with an ID-1 card
(85.60 × 53.98 mm). The plain stage in the middle of the ring is where the part sits; the markers stay visible around it.
The same layouts are exported as a plain-paper A4 PDF. Each mat uses a disjoint marker-id range so detection knows which mat
it is looking at.

**2026-10-27 — Ground truth without a caliper.** Accuracy is reported against three clearly separated sources: synthetic
photos (exact), standardised reference objects (published specs: ID-1 card, SD card, LEGO 2×4 brick, AA cell marked as a
loose spec) and real parts measured with a school ruler (labelled ±0.5 mm). Reports never merge these into one number.

**2026-10-27 — Screen fit check replaces the print as the physical proof.** The model's 1:1 outline is drawn on the
calibrated screen, the real part is laid on it and photographed, and the verifier compares part and outline. Real prints
are optional and never claimed unless they exist.

**2026-10-27 — Zero-key operation.** Every model call goes through `services/agent/providers`. `PROVIDER_MODE=live|mock|replay`;
when a key is missing that provider falls back to a deterministic mock, logged and shown on `/status`. Mocks run the same
code paths (schemas, guards, verifier) so the pipeline is testable end to end; everything they produce is labelled mock.

**2026-10-27 — Own viewer format instead of the tessellation package.** The web viewer reads `view.json` (triangles plus
B-rep edge polylines that we discretise from OCCT edges in the worker). This keeps CAD-grade edges without adding a second
tessellation stack to the worker image.

**2026-10-27 — Stage routing and fallback chains.** One table (`services/agent/providers/routing.py`) maps each stage to an
ordered provider chain; the first provider with a key wins. understand → Muse Spark 1.3; plan/build/fix → Muse Spark Open
(Baseten → Fireworks → Together → Spark 1.3); judge + capture triage → Muse Glimmer 30B on Modal (→ Together); voice/variant →
Spark 1.3; steer plan → Muse Wonder; segment → SAM 3.1 API (→ SAM 3 open on Modal); image → Muse Image; transcribe → Muse Voice
Transcribe. `OPEN_WEIGHTS_ONLY=1` restricts every chain to open-weight models. The Baseten model id comes from `models.list()`.

**2026-10-27 — Replays are keyed by a request hash without volatile fields.** `PROVIDER_RECORD=1` stores each live
request/response under `$PARTSMITH_HOME/recordings/<hash>.json`; the hash excludes the provider, timestamps and mock-only
context, so a recorded run replays even if a fallback provider answered. Missing recordings fall back to mock with a warning.
Masks travel between the Modal SAM 3 app and the API in one run-length wire format (`providers/media.py`).

**2026-10-27 — Fork-per-job warm CAD worker, single-threaded OCCT.** A warm parent imports CadQuery once and forks a fresh,
rlimited, network-isolated child per job (netns when unprivileged user namespaces exist, socket patch otherwise), so a knob
rebuild costs ~0.1–1 s instead of a 1–2 s cold import. Forking after OCCT has started its thread pool deadlocks, so the warm-up
and all meshing run single-threaded with an absolute chord tolerance. `mem_mb` is added on top of the warm baseline.

**2026-10-27 — Verifier raster and alignment rules.** Silhouettes are rasterised per triangle at 4× supersampling (OpenCV's
fill grows shapes by ~0.5 px). Model-to-photo alignment is a rigid 2-D search that may mirror (a part lying upside down shows
its mirror image) but never scales — rescaling to force a fit would hide real errors. Minimum wall thickness is the 2nd
percentile of inward ray casts from the B-rep surface.

**2026-10-27 — Fix-loop guards and search policy.** Each round may move a length by at most 20 % of its value (min 0.5 mm, max
2 mm), a topology knob by ±1 and an angle by ±10°; unknown parameters are rejected with the closest names; edits that rescale the
whole outline are refused. Every round restarts from the best round so far (ranked: verified, then fewer failing P0 tests, then
smaller max error). After two rounds without improvement the strategy switches: template → free code (extrude the measured
outline) → ask the human. Measured values always overwrite what the model says about them.

**2026-10-27 — Pass rule per view.** IoU is scale-dependent: a 1.5 mm-thick side profile with 0.1 mm edge error scores IoU ≈ 0.88,
so the IoU ≥ 0.97 gate applies to the top view and to any view whose silhouette is at least 10 mm wide; thinner views are gated on
Hausdorff ≤ 0.5 mm plus a thickness test (±0.3 mm). Views with a known camera pose are compared in the photo frame (model rendered
with the real K, R, t), which handles parallax and see-through holes in thick parts exactly.

**2026-10-27 — Registry publishing and seeding.** The registry is seeded only by running committed samples through the real
pipeline (`services/registry/seed.py`); origin stays `synthetic` on every seeded part. Verified runs publish; best-effort runs
publish only when their max error is ≤ 2.0 mm and keep the "best effort" status on their page. Every seeded run is also exported
as a labelled replay for the judge path. Steer factory lanes build a template at planned parameters and check it against its own
rendered silhouette — a synthetic self-check, labelled as such; approval publishes with origin `synthetic`.

**2026-10-27 — Thumbnails, uploads and MCP placement.** Part thumbnails are rendered on CPU (z-buffered triangles, Lambert shading,
B-rep edges from view.json; transparent background, 1× and 2×) at publish time — no GL in the server. Uploaded JPEGs keep their
pixels byte-for-byte; only the EXIF GPS block and XMP are stripped (camera focal length stays, the metrology needs it). The MCP
server is mounted on the API app at `/mcp` (stateless streamable HTTP) and also runs over stdio (`python -m services.mcp --stdio`).

**2026-10-27 — Bench mechanics.** `eval/run.py` drives the real job service (`sync=True`, non-interactive) for each suite and
config; bench jobs live under `$PARTSMITH_HOME/bench` so they never appear in the app or the registry. Ablations are `RunOptions`
switches (`single_shot`, `mat_scale`, `numeric_feedback`, `templates`, `judge`, `height_correction`) whose defaults are the product
behaviour. Only the scorer reads `gt.yaml`; it re-executes the final `part.py` in the sandbox and measures it the way the ground
truth was measured. Mean-error CIs use a cluster bootstrap over parts (dimensions of one part are correlated). Mock-mode tables are
always titled "pipeline check — deterministic mock providers, NOT model performance".

**2026-10-27 — IoU gate only where IoU is meaningful.** For an L × L silhouette with uniform boundary error e, IoU ≈ 1 − 4e/L,
so IoU ≥ 0.97 at e = 0.1 mm needs L ≳ 13 mm; on an 8 mm spacer it rejects a model that is within 0.2 mm everywhere. The IoU ≥ 0.97
gate therefore applies only to views whose silhouette short side is ≥ 20 mm. Smaller views are gated on Hausdorff ≤ 0.5 mm and
mean contour distance ≤ 0.15 mm, both scale-free, plus their part tests. IoU is still reported for every view.

**2026-10-28 — Agentic stages keep the conversation on our side.** `run_agent` drives Responses function tools (Spark 1.3 /
Wonder) and chat tools (Spark Open, Glimmer) with `store=False`: instructions, tools and reasoning are resent each turn, only the
last few tool images stay inline, and images in tool outputs travel as `input_image` parts (chat path: a following user message).
Tools are our own metrology and verifier functions, so the model operates the instrument but code still decides `verified`.

**2026-10-28 — Cited values and generated pixels are gated by code.** A Wonder spec lookup value is accepted only if a web search
actually ran, the cited URL is one the search returned, the name was requested, and the value converts to mm; it becomes
`Source.cited` and never overrides a measured value. Muse Image reconstructions get the original pixels pasted back outside the
broken region (intact area identical by construction) and then pass the metrology gate (markers ≤ 1 px, intact IoU ≥ 0.98)
before the completion enters the outline as inferred.

**2026-10-28 — Every photo decode applies EXIF orientation itself.** The browser draws a phone photo rotated by its EXIF
Orientation tag and sends tap points in those pixels, so the server must see the same frame. Whether a decoder honours the tag
depends on library, flags and version (OpenCV 5 `IMREAD_COLOR` does; `IMREAD_UNCHANGED` and plain Pillow do not), so photo
decodes go through `services/common/images.py::decode_bgr` (decode with the tag ignored, then apply it ourselves, the same
transform as Pillow's `exif_transpose`); the provider helpers (`image_size`, `decode_image_rgb`, `fit_image`) and `fit_png`
apply it too, and images sent to models are re-encoded upright. Upload hygiene keeps the tag on JPEG (pixels untouched),
saves PNG/WebP upright, and re-encodes a JPEG upright only when its EXIF block cannot be kept.

**2026-10-28 — One export gate for every download, shown before the click.** `/parts/{slug}/bake?download=1` now goes through
the same `gate.decide_part` as `bundle.zip` (verified ships, best effort needs `ack=1`, failed is refused; `format=view`
and `format=glb` previews stay open for the embed and AR viewers), so the bake route is no longer a way around the bundle gate. Part detail carries the
decision as `ship`, the same shape job publish returns. Fit presets on unpublished jobs (`/jobs/{id}/bake?preset=`,
`/jobs/{id}/presets`) reuse the part rule (`round2.preset_values`) on the job's current values, so the web never copies it.

**2026-10-28 — Mock agent turns say they are mock.** The deterministic fix-agent policy names itself (`"model": "mock fix
agent"`) and `run_agent` stamps the driver's `mode` on `thought` and `tool_call` events, so a mock trace can never pass for a
model's reasoning. `FitCheckResult.hausdorff_mm`/`mean_mm` are `null` (not NaN) when nothing could be compared.

**2026-10-28 — Two objects on the mat stop the job; glare does not count as an object.** `single_part` joins the
measurement-stopping checks (with contrast, coverage, markers, scale, reprojection). Before, it only logged a warning, and the
red-team "two parts" photo went on to verify a model of one of them. Counting pieces now skips a piece that holds none of the
part and whose colour is the stage colour washed towards white (≥ 15 % of the way, ≤ 12 RGB off that line): a reflection,
not a second object. On the 112 one-part synthetic photos (control, demo samples, bench) no photo fails `single_part`;
red-team 10/10, control 6/6 (mock). A second white object beside a part on a light stage would also read as glare; white
parts already need the dark stage.

**2026-10-28 — Reference objects are named from their sample, never from the model.** A reference object's title and slug
come from the sample's own metadata ("Full-size SD card"), not from the job's PartSpec title, which a model (or the mock)
wrote ("battery compartment cover"). Committed replays re-encode `install_card` and `reconstruction` images as JPEG like the
other display-only images (the 19 replays: 112 MB → 58 MB).

**2026-10-28 — Broken parts: the break is located by evidence, never copied, and never counted in the error.** Four rules
for the broken-region path. (1) `BrokenRegion.kind = "height"` covers a part whose top is missing: the model only says so,
code takes the break height from the side photo and leaves everything above it out of the side and walk-around views (the
top view is compared in full); before, such a break was not located at all and the fix loop shrank the replacement to the
stump. (2) Mirror completion snaps an axis within 2° of the part frame, and also mirrors end to end when the outline is
still ≥ 0.8 IoU symmetric that way: a piece missing from the middle of an end is its own mirror image about the long axis.
(3) A broken part never switches to free code from the measured outline (that extrudes the break into the replacement);
the template keeps probing. (4) A length/width test is informational when the break reaches that end or side of the
footprint's rectangle, and the residual behind every informational test is reported apart ("NOT verified") and left out
of the max error and the fixer's input. Distances next to the excluded region are measured from the kept contour points to
the other boundary as a whole (a point beside the region was matched to the far end of the clipped curve, a phantom error
of several mm on the cover tab), and the rectified side view gets one band per region piece, not one band from the first
to the last. The mock also counts hinge tongues on the outline's ends. Thresholds are unchanged.

**2026-10-28 — A claimed break is an attack surface, and "verified but off" is reported.** The model writes
`broken_region`, and the verifier leaves that region out of the comparison, so the lying-brain suite now includes a model
that declares a break (one end, half the part, a box around all of it) to excuse a part 6 mm too long: it stays best
effort (`eval.bypass`, 17/17). The bench tables gain `verified_but_off`: runs the verifier passed that are more than
0.5 mm off the ground truth, shown next to the verified rate so a high verified rate cannot hide wrong parts.

**2026-10-28 — Printable files are gated at every URL.** Content-addressed links (`/blobs/<key>`, `/bakes/<key>/<file>`)
for STL, 3MF, STEP and zip go through the same export gate as the bake and bundle routes (verified ships, best effort needs
`ack=1`, failed or unowned answers 409 `not_shippable`). A key maps back to its job or part through a small append-only
claim list written when a job or part bakes, with run-log and bake-manifest lookups as fallbacks; when several owners share
the same bytes the most permissive decision wins (those bytes are already downloadable through that owner's gated route).
Previews (GLB, images, JSON, code) and the fit-test coupon stay open.

**2026-10-28 — Public deploy: one API container in replay mode.** The API ships as one container (in-process jobs, one
uvicorn worker) that defaults to `PROVIDER_MODE=replay`, bakes in the stored replays and samples, and refuses to start
without `PARTSMITH_ADMIN_TOKEN`. The web origin proxies `/api/v1`, `/mcp` and SSE, so the public site is one URL and the
API needs no CORS. `make deploy-check` validates the deploy files statically; images are built only on the deploy host.

**2026-10-28 — "Open in slicer".** Deep links only where the slicer documents a URL scheme that accepts a file URL (Bambu
Studio, OrcaSlicer); PrusaSlicer gets the download plus a one-line instruction. The export gate applies unchanged.

**2026-10-28 — The fit-test coupon learns only the clearance.** Per printer + material preset and per device (a hash of a
random browser id; no accounts), each coupon report moves the clearance in effect by ±0.05 mm (×0.5 "barely", ×2 "very",
"ok" = 0), clamped to the preset's delta ± 0.25 mm and never below 0; the learned value is the median of the newest 15
proposals. The median resists one wrong report, the window follows a new spool, and the clamp keeps a bad run from producing
an absurd hole. The server computes the starting clearance, never the client, and measured dimensions are never touched.

**2026-10-28 — Impact numbers are computed estimates or nothing.** Minutes come from job event timestamps, grams from the
baked mesh volume (100 % infill upper bound), cost from a stated, env-configurable spool price; all are labelled "estimate"
and missing data shows nothing. When the buy-or-print card exists its code-computed numbers take precedence, so the page
shows one set of figures. The workspace viewer, error chart and Agent tab load on demand behind sized placeholders.

**2026-10-28 — Realtime voice is relayed by the API, never called from the browser.** The browser streams 16 kHz PCM
(AudioWorklet plus our own box-filter resampler) to `WS /api/v1/jobs/{id}/voice/live`; the API relays it to Muse Voice
Transcribe realtime (ENDPOINTING, keywords = the job's knob labels, language bias English + Hindi), so the key never reaches
the browser and every session still emits a `model_call`. Each final utterance goes through the same mapping and guards as
the typed and recorded-clip edits: the model proposes, the knob ranges clamp, the user sees the from→to diff. Sessions are
capped at 60 s and about 2.1 MB, with an Origin allow-list because WebSockets bypass CORS. Without a key the session replays
a scripted Hinglish utterance that moves exactly one knob of the current job, always labelled MOCK; the recorded-clip path
stays as the fallback.

**2026-10-28 — A thick part seen only from the top is bounded, not observed; unchecked knobs are labelled.** The AA cell
was verified while 0.56 mm short: a 14.5 mm extrusion of the full-height reading and the real cylinder (whose terminal sits
at mid-height) cast the same top silhouette, so model and photo agreed end to end to 0.005 mm. The metrology now records
`Measured.bound_mm` (full-height reading, mat-plane reading) for thick top views. When neither a side view nor walk-around
frames show the heights and the model is an extruded outline (not a family template), the verifier adds P0 tests
`bbox.x.height` / `bbox.y.height`: the model must be within ±0.3 mm of both the full-height and the half-height reading. The
fix loop then stops early and asks for a side photo, since no model edit can settle it. `Verification.unchecked` lists
every knob no test compared with an observed value, labelled inferred. Thresholds are unchanged. A 16 mm control knob that
fell back to free code moves to best effort (true error 0.48 mm): we accept that false reject rather than verify a shape
the photo cannot show.

**2026-10-28 — Buy-or-print and the narrated walk-around are cited or checked by code.** Offers, shops and OEM names are
kept only with a URL the search returned and a quote that shows the price; every drop is listed. The print side (grams,
minutes, cost) is computed by code from the mesh with stated spool prices. Spark's narrated (time, pixel) points are kept
only when they fall on the part in their own decoded frame and on its measured footprint; each becomes a SAM point prompt.
The narration's words steer the understand stage and never set a number.

**2026-10-28 — A broken end of unknown length is stated by the user, never guessed.** When a located break reaches an end
of the footprint, no mirror can restore the length and the photo shows only the broken piece. If the template has a length
knob, the job takes the original length from the user's own words: the intent ("it was 51 mm long", parsed by code,
unit-aware), one question ("How long was it before it broke?"), or, with a tapped broken edge, only the missing piece beyond
the tap. "skip" keeps the length inferred; values outside the knob's range or clearly shorter than the broken piece are
refused. A stated value is `user_stated` with the user's uncertainty (±0.5 mm ruler, ±1 mm for "about"), sets and locks the
knob, and is listed in `unchecked` as stated, not observed. The verifier leaves the strip it adds beyond the broken end out
of every comparison and out of the max error; a P0 test checks only that the model is the stated length, so it can block a
part, never pass one. Thresholds are unchanged. Latch demo (mock): a stated 51.3 mm takes the max error from 1.40 to
0.75 mm; it stays best effort because the corner break also hides the width.

**2026-10-28 — SAM point prompts carry negatives; mask confidence widens ±σ and asks for a retake.** Every point prompt
sends the mat-marker centres in its crop, the user's `exclude` taps and, when the gate flagged glare, the brightest blown-out
blob on the part as negative points. A mask's confidence c widens every value measured from it, σ × (1 + 2(1 − c)); below
c = 0.5 a feature is not used and the job asks for a retake in plain words, and an unsure outline asks whether to retake
the top photo (default continue). Both constants are stated choices, not fitted to ground truth. Mock masks carry a labelled
edge-contrast proxy and are tagged `mock-flood` / `mock-threshold`, never `sam-3.1`. σ is reported uncertainty only; the
verifier never reads it.

**2026-10-28 — "Where each value came from" and the fail → fix strip read only the job's own record.** The viewer can tint
every size, feature value and rebuilt region by its source (measured, pointed by Spark, stated by the user, cited, inferred,
AI-completed), each with a text label, icon and pattern so colour is never the only cue; selecting one shows value ± σ,
the evidence note, the residuals that compared the model with it and the overlay it came from. The strip above the job
shows each fix round's max error, the knobs changed and the verdict, parsed from the run's events. Per-view verdicts per
round are not emitted as structured data yet, so the strip shows per-view Hausdorff against the limit and says so.

**2026-10-29 — "Fits where it goes" is measured by code and never sets verified.** The optional mating photo is taken on
the same mat and passes the same capture gate. Each mate (socket, shaft or pin, slot or panel edge) is located by the
user's tap, or Spark points at it (pixels only, kept only on the mat's stage); a SAM point prompt cuts it and code measures
it in mm: a see-through socket gets a lens fit that solves the plate height, a shaft lying on its side gets its round
section solved from both edges and the camera pose, slots and panel edges are measured between their long sides. Where the
photo cannot tell how high an edge stands, the reading assumes an edge 0–3 mm above the mat and ±σ covers it (a stated
choice). Each mate meets one feature measured on the CAD solid (a declared interface, else the closest hole, the narrowest
outer width or the plate thickness; the verdict names which), classified with the functional probes' clearance classes
at c and c ± σ, plus "after printing on <preset>" with the preset's or the device's learned clearance. The result is P1
tests and one reason line; "does not fit" adds a warning to the export gate's reason without changing the decision,
because `verified` stays a statement about matching the broken part. Synthetic mates: all six within σ of ground truth.

**2026-10-29 — Repair passport: a 6-symbol id that brings a part back from one scan.** Every published part and every job
gets a Crockford base32 id (30 bits of a sha256, case-insensitive, O read as 0 and I/L as 1): a part's id comes from its
publish identity and version (same part → same id, new version → new id; older ids still resolve, marked superseded), a
job's from its job id; no personal data goes in. `/p/{id}` and the repair card's QR resolve it to a reprint through the
ordinary gated bake, with a preset and this device's learned coupon clearance. The physical mark (`passport=1`, off by
default; pipeline, publish, bundles and benches never set it) is debossed only, 0.4 mm deep, by trusted code after the
program ran, on the largest upward face with 25 × 8 mm free of edges, holes and interfaces and ≥ 0.8 mm of material
under it; the bounding box, every hole, the plate thickness and interface gaps are re-checked to 0.001 mm and any change
undoes the mark. Raised text is never used: it would move a measured outer face.

**2026-10-29 — Live lesson: code overrides a planner that picks free code for a broken or tall part.** On the first live
run of the broken latch, the understand stage named the latch template but the live planner chose free code from the
outline, and all four free-code programs produced no solid, so the job failed. Two code rules now apply. When the planner
picks free code but the PartSpec names a template of the same family and the part is broken (an extruded outline would
copy the break) or taller than its plate, code uses that template and logs why. When free code never produces a valid
solid, the loop switches to the family's template instead of failing. Benches already showed the template library
verifying far more often than free code (PS vs PS-noTemplate).

**2026-10-29 — Live lessons, round 2: code checks what the live models got wrong on the first seed.** Each rule came
from a recorded live run and has a test built from that run's numbers.
(1) Reference checks: `JobInput.purpose = "reference_check"` is set only by server code (bundled reference samples in
`sample_job_input`, eval's real reference photos); the public `/jobs/fix` form never accepts it. The understand prompt
then says the object is a measurement check of a known rigid object and that nothing will be printed. A model refusal
on such a job is logged and ignored; code's own refused classes still apply. The export gate's decision is unchanged,
but `ship.json` is labelled ("measurement check of a reference object, not a replacement part"). Live, Spark had
refused the AA cell and SD card.
(2) A model-proposed outline break stays only when something besides the model backs it: a broken-edge tap, damage
words in the request or narration ("missing", "cracked", "corner", "tip", …; "broken" alone does not count, because
every repair request says it), or an asymmetric outline (mirror score < 0.97) while no side photo shows features above
the plate. A tall feature seen from above in perspective makes an intact outline asymmetric. Otherwise code drops the
region, logs why and keeps the model's region in `break_check.json`. An unsupported region would take the outline out
of every test it spans. Live, the intact L-bracket's upright leg read as a broken flange. Height breaks are unchanged.
(3) When the planner picks free code, code uses the PartSpec's hinted template whenever it belongs to the part's family
and the measured size fits its ranges, not only for broken or tall parts. Free code stays the fallback after rounds
without progress, except for broken or tall parts.
(4) In template mode the builder only fills PARAMS: code runs the template's own source with the builder's values for
the shared knobs. Live, the builder twice returned new geometry under the template label, which the verifier would
have treated as the known template form.
(5) Free code that comes out hollow where no photo looks (the plate-thickness P0 test below half the expected value on a
full-height solid) is rebuilt once with code's finding as feedback. The build prompt (v2) asks for a solid body. Live,
the LEGO brick was hollowed out and failed by 7.9 mm.
(6) The fixer is told which pass rule fails. Small silhouettes are gated on mean edge distance, not IoU, and the fixer
used to see only IoU and Hausdorff.
(7) A pointed hole that the outline pass missed is not accepted as a measured through-hole when it was measured only
from its top-opening rim, at a spot where metrology flagged a bore it cannot see through; the hidden-hole question
stays.

**2026-10-29 — A slow provider goes to the back of its chain for a while.** The fallback chains used to move on only
when a provider failed. During the second live seed, the shared Baseten hackathon deployment of Spark Open slowed from a
median of 8 s per fixer turn (first seed) to 28 s, and one turn took 318 s. The battery cover hit the job's 900 s
wall-clock cap and ended best effort; the first seed had verified it. Now a text route whose last 6 calls average more
than 40 s for a stage is tried after the other ready routes for that stage, for 15 minutes, then gets a fresh window.
Windows are per stage: a first version pooled all text calls and demoted Spark 1.3 because of its understand calls, which
read two photos and take 36–55 s by nature. For plan, build and fix that
fallback is Muse Spark 1.3 on the Meta API, at the same token price. A turn already streaming is not cut off: that would
throw away the agent's progress in its run. Only the order changes, and every `model_call` event still names the model
that served the call.

**2026-10-29 — A hole found only from a model's point must be a clean circle on the part.** A point-prompted hole that
matches no outline hole has nothing to cross-check it. It is now added only when its circle fit has rms/r ≤ 0.10 and at
most 10 % of the circle lies outside the measured outline; otherwise it is noted and left out. In the second live seed
of the broken latch, the SAM point mask spread over the plate around the countersunk pivot. The fit came back Ø25.9 mm
(rms/r 0.21) on a part 17 mm wide, and that P0 test made the job 20 mm off.

**2026-10-29 — Through-holes a model mask closed come back from the colour threshold.** A text-prompted mask can close a
narrow or countersunk through-hole; the colour threshold, which only asks "is this the mat colour", still sees the mat
through it. For thick parts measured with a model mask, the threshold's openings are used when both masks agree on the
part (filled IoU ≥ 0.9). Each opening must be enclosed by the model mask, at least 0.25 mm², at most 15 % of the part and
compact like a lens. The see-through cylinder fit then decides what each opening is. Thin parts keep the model mask as it
is, because there is no fit to check an opening. In the live broken latch, SAM 3.1 closed the countersunk pivot and the
verifier held the model's real pivot hole against a solid photo (8.6 mm). Replaying the recorded SAM answers with the
threshold openings, the outline gains the hole and the top-view distance there drops to 2.5 mm; a live rerun is pending.

**2026-10-30 — Live benches run with a spend cap.** `eval.run --max-usd` stops starting runs once the finished ones
cost that much (running ones finish, later configs are skipped, the log says how many were left out). The first live
bench ran in two invocations, so the gate suites were not repeated under every ablation: synthetic and reference renders
under PS, B1 and PS-noTemplate, then control and red-team under PS only. `--from-runs --mode live` builds one report
from both. The README status line says when a report came from a working tree with uncommitted changes.

**2026-10-30 — Bench reports are strict JSON and name the code their runs came from.** Non-finite numbers (a rate over
zero runs) are written as `null`, and the writer refuses `NaN`. Each stored run records the commit and dirty flag of the
tree it ran in. A report rebuilt with `--from-runs` takes them from the runs when they agree, and otherwise names the
current tree and says so (`git_source`). Before this, rebuilding the first live bench after a commit stamped it with the
rebuild's commit, not the one the runs were made at.

**2026-10-30 — A person reviews every finished job; "improve" is a linked reviewer round.** Finished jobs stay
immutable, so sending one back starts a new fix job (`input.parent_job`, `input.review_round`) on the same photos. It
measures again (same photos, same mat frame), skips understand / ask / plan by loading the parent's PartSpec, template
and stated values, rebuilds the parent's program as round 1, and runs at least one fix round even when the parent
verified, because a person said something is wrong. Pins are normalised points on the rectified top photo, resolved to
mat and part mm inside the reviewer round. The fixer gets one line per pin with code's local mismatch there (within
3 mm, larger of the two edge distances) and a photo | model crop with the pin drawn as a numbered ring, since marks drawn
on an image point a vision model at the right spot. Each pin's mismatch before → after is stored. Review state lives
in `$PARTSMITH_HOME/reviews/`, so committed replays can be reviewed without being written.

**2026-10-30 — Accept is a sign-off, not a verdict.** Only the verifier sets `verified`. An accepted part the verifier
did not pass publishes as "best effort, accepted by a person" (the existing export gate with the person's
acknowledgement). The publish logic moved into `services/api/common.py` so the publish route and accept share it.

**2026-10-30 — The judge also scores, as advice; Spark 1.3 judges until Glimmer is deployed.** Besides vetoes it returns
1–5 for outline, features, printability and fit for use, each with a reason, saved to `judge.json` (not to
`verification.json`). Code drops a malformed or repeated score instead of the reply. In the product path the judge chain
is Glimmer first, then Muse Spark 1.3 on the Meta API, so the scorecard is a real model's opinion before Modal is up; the
open-weights path stays Glimmer only. `/review` reports agreement with the reviewer (judge OK = no blocking veto and no
score below 3; person OK = accept) and Cohen's κ with the reviewer count, because raw agreement overstates a judge.

**2026-10-30 — Reviewer notes become family rules only with a person's tick.** Every note and reject reason is kept as
a lesson candidate with its evidence (jobs, pin, before/after mm). On accept, Muse Spark drafts one general rule per
note (or skips a one-off); the reviewer edits and ticks them, and only ticked rules are promoted. Promoted rules now
reach the fixer as well as the builder, scoped to the family, and each job records which rules it was given, so
`/lessons` can show how later reviews of those jobs went. Rules injected everywhere without a check tend to lock in
their own mistakes; scoping, evidence and the track record are how a bad rule gets noticed and retired.

**2026-10-30 — Every review says who made it; test reviews never count as a person's.** A decision is `by: "person"`
(the API: whoever holds the admin token) or `by: "test"` (a scripted or developer-agent check). Test decisions run the
same flow, so the loop can be exercised live, but they cannot promote a rule or publish a part, they are left out of the
judge-vs-person agreement and the rule track records, and the page labels them "test review, not a person". The first
live hinge rounds were made by the developer agent and are labelled that way.

**2026-10-30 — Review chains can be recorded with the replays.** `export_chain` exports every round's job as a replay and
writes the chain to `data/replays/_reviews/`, so a fresh clone or the public replay site shows a real reviewer chain
(round history, pins, before → after). Recorded chains are read only: a new decision on one is saved under
`$PARTSMITH_HOME/reviews/`, which then takes precedence.

**2026-10-30 — The judge sees a shaded 3D view of the model, and the side photo it was promised.** In the third live
reviewer round on the hinge leaf the measurements passed (top 0.38 mm, side 0.27 mm) but the live judge vetoed:
"photo shows rolled cylindrical barrels, model shows only flat tabs". The model had barrels; the judge had only been
shown the model's top silhouette, where a barrel and a flat tab look the same, and its prompt mentioned a side photo
that was never attached. The judge now gets, in a numbered list its prompt names: the top photo, the model's top
silhouette, a shaded 3D view (`services/verifier/shade.py`: orthographic, flat-shaded, painter's order, ~10 ms; a
picture only, nothing is measured from it), the side photo with the model's side silhouette when there is one, and the
worst-spot crops. Re-asked with that evidence, the same live judge scored the round-3 model 5/5/5/5 with no veto
("shaded view confirms knuckles and countersinks"). A veto can still block a pass; it now has the evidence to be right.

**2026-10-30 — The review page answers one question: does what was made match what it should be?** The photo
("Should look like", where pins go) and the 3D model ("Agent made") sit side by side above the fold; a round strip
tells the chain's story (each round's worst gap and decision); a measurement card says pass or fail in words, which
views and must-pass sizes fail, and the verifier's biggest gap is circled on the photo (`images.worst`, the top
view's worst point projected with the same mat transform as the overlay). The decision bar stays at the bottom of the
screen on larger screens; when the code has not passed a part, Improve is the primary action and Accept reads
"Accept anyway". A reviewer can paste a screenshot (Ctrl+V), drop or attach up to 4 pictures; they are cleaned like
photos (GPS removed), stored as blobs and sent to the fixer after the pin crops, named in its notes as references for
shape, not for sizes. The same pass made a browser GET on `/mcp` answer at once with how to connect instead of
holding the request open.
