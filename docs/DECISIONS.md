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
