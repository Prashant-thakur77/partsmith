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
