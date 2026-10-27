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
