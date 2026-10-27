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
