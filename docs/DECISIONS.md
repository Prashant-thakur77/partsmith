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
