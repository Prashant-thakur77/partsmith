# Progress log

Newest entries at the bottom. Each entry: what was done, evidence (command + output), what's next.
A fresh session should read this file, `docs/ARCHITECTURE.md`, `docs/API.md` and `docs/DECISIONS.md`, then continue from "Next".

## 2026-10-27 — Bootstrap (PLAN §0.2)

- `.gitignore` checked before any `git add`: `git status --ignored` lists `.env`, `PLAN.md`, `KICKOFF_PROMPT.md`,
  `docs/REUSE_LOG.md` as ignored; `git check-ignore -v PLAN.md .env` matches both.
- Tools: uv 0.10.9, Node 22, pnpm, gh (logged in), make present; installed modal 1.6.2, gitleaks 8.30.1, Muse Code 1.4.13.
- Repo is local only (no GitHub repo created, nothing pushed) by instruction.
- Contracts written: `packages/schemas/partsmith_schemas`, `docs/ARCHITECTURE.md`, `docs/API.md`, `docs/DECISIONS.md`.

## Work plan (waves)

1. Wave 1 (parallel): metrology + mats · geom worker + verifier + 10 templates · providers + Modal infra + smoke · web app shell.
2. Wave 2: synthetic generator + reference objects · agent loop + jobs + replays + CLI · API + registry + bake cache + MCP.
3. Wave 3: eval benches + reports · web ↔ API integration · screenshots/axe review · QUALITY.md · HANDOFF.md.

## 2026-10-27 — Wave 1 results

- **Spike (PLAN §0.2 step 5):** `spikes/golden_path.py` reproduced on this machine — correct code IoU 0.9995 / Hausdorff 0.125 mm,
  deliberately wrong draft IoU 0.962 / HD95 0.523 mm (synthetic photo).
- **Providers** (`c2d834e`): `uv run pytest services/agent/providers services/media tools/tests` → 69 passed; `make smoke` with zero keys →
  `0 live ✅ · 12 missing ⚠️ (mock) · 0 failed ❌`, exit 0. No live call has been made (no keys).
- **Metrology** (`0002f31`): `uv run pytest services/metrology tools/mat tools/calib` → 69 passed. Synthetic accuracy (not a bench result):
  1 mm and 8 mm plates measured within 0.06 mm with height correction; uncorrected 8 mm plate off by 1.77 mm (the test asserts the
  correction helps by > 4×). Real phone photos and live SAM 3.1 are untested.
- **Geometry** (geom worker, verifier, 10 templates): `uv run pytest services/geom_worker services/verifier services/agent/templates`
  → 114 passed (fast + slow). **Phase 2 exit gate:** `uv run python -m services.verifier.selfcheck` → 10/10 templates pass
  (self-consistency Hausdorff ≤ 0.05 mm vs 0.15 mm limit; ±1 mm length perturbation detected with the right sign, never verified).
  Synthetic measurements derived from each template's own silhouette.
- **Web app** (`apps/web`, Next.js 15 / React 19 / Tailwind 4): `pnpm typecheck`, `pnpm lint` clean; `pnpm build` OK (19 routes);
  Playwright 92 passed / 24 skipped (functional flows run in desktop-light only) with axe (0 serious/critical) on desktop+mobile ×
  light+dark. Built against route-mocked fixtures only — real-backend integration is wave 3.
- **Agent loop** (orchestrator, mock brain, guards, service facade, CLI): `uv run pytest services/agent/tests` → 32 passed (13 slow).
  Mock mode, rendered top-only samples (latch, spacer, cover) verify in 2–3 rounds and replay to identical detail. On the synthetic
  top+side JPEG samples most runs ended best-effort: side-view IoU gate unreachable for thin profiles and see-through holes lost in
  thick parts → camera-frame verification + see-through hole fitting assigned (in progress).
- **Synthetic data + measure-only bench** (`tools/synth`, `eval/{metrics,stats,measure_only}.py`): 35 tests pass. 16 committed demo
  samples (all templates + 4 reference objects, screen + paper mats, 11 MB). **Phase 1 gate (first honest run): FAIL** —
  `uv run python -m eval.measure_only --n 60 --n-reference 20 --seed 7`: synthetic mean abs error 1.503 mm (N=201; flat parts 0.267 mm,
  tall features 1.741 mm; white-part preset 7.45 mm), synthetic reference-object renders 0.346 mm (N=40, PASS). Real reference
  objects and real ruler parts: pending (no photos). Fixes in progress: see-through holes, shadows, dark screen stage for white parts,
  side views of thin parts, round profiles; camera-frame verification for tall features.
- **API + MCP + registry ops** (`services/api`, `services/mcp`, `services/registry`): 47 tests pass. Every route in docs/API.md,
  SSE with replay + `from_seq`, MCP tools over `/mcp` and stdio, Steer factory, seeding with a publish gate, CPU thumbnails.
  First seed run (mock providers, 5 samples): 1 published (best effort 0.354 mm), 4 best effort at 3–17 mm → blocked on the
  metrology/verifier fixes in progress.
- **Full-loop bench** (`eval/run.py`, `make bench`): 70 mock runs in 5 min 21 s, configs B0/B1/B2/PS/PS-noTemplate/PS-noJudge/
  PS-noHeightCorr on synthetic (n=6) + reference-object renders (n=4); real_ruler pending. Mock pipeline check only. First pass:
  PS synthetic verified 1/6, median 0.10 mm but mean 3.6 mm (glare/white-part failures); `--check-regression` wired for CI.
- **Verifier camera-frame comparison** (`3237b2f`): posed 8 mm plate verifies at Hausdorff 0.07 mm; ±1 mm / Ø+0.4 mm still caught.
- **Metrology round 2:** see-through hole fitting (thick-part holes 0/4 → 4/4 found, Ø error ≈ 0.02–0.03 mm on renders), hidden-hole
  notes, shadow suppression, dark screen stage + `contrast` gate check, thin side views, round profiles. Synthetic measure-only bench
  mean 1.503 → 0.628 mm (flat 0.172, tall features 0.984, side thickness 0.731, reference renders 0.194). Phase 1 gate (≤ 0.4 mm)
  still FAIL on synthetic overall: tall features are a single-photo ambiguity, handled in the full loop by camera-frame verification.
