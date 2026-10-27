# PartSmith web

Next.js 15 (App Router) · React 19 · TypeScript strict · Tailwind 4 · Radix · react-three-fiber · TanStack Query · Zod.

```bash
pnpm install                 # from the repo root (pnpm workspace)
pnpm -C apps/web dev         # http://localhost:3000, proxies /api/v1/* to $API_URL (default http://localhost:8000)
pnpm -C apps/web typecheck   # tsc --noEmit (includes the schema drift check in src/lib/schema-compat.ts)
pnpm -C apps/web lint
pnpm -C apps/web build
pnpm -C apps/web e2e         # build + Playwright: every page × desktop/mobile × light/dark, axe, screenshots
pnpm -C apps/web schemas     # regenerate src/lib/schemas.ts from the Pydantic contracts
pnpm -C apps/web mats        # regenerate public/mats/*.json from the metrology mat registry
```

- `src/lib/api.ts` is the only way the UI talks to the backend; every response is validated by `src/lib/api-types.ts`.
- No page ships invented numbers. When the API is down, pages show an offline state; mocks, replays and synthetic data are labelled.
- E2E fixtures live in `e2e/fixtures/` (route-mocked in tests only). `e2e/fixtures/generate.py` rebuilds their geometry and images
  from the real family templates: `uv run python apps/web/e2e/fixtures/generate.py` from the repo root.
- Screenshots land in `e2e/screenshots/<project>/` (gitignored).
- Live suite (opt-in, not in CI): with the API on :8000 (seeded registry) and the web app on :3000,
  `pnpm -C apps/web e2e:live` checks every read endpoint against the Zod contract, runs demo → workspace → verdict →
  knob re-bake → export, a photo fix with answered questions, edit, preview and fit outline, a steer approval, and takes
  real-data screenshots into `e2e/screenshots/live-*`.
- SSE: `src/app/api/v1/jobs/[id]/events/route.ts` streams job events unbuffered; everything else under `/api/v1` and
  `/mcp` is a fallback rewrite to `API_URL`.

Env: `API_URL` (server-side proxy target), `NEXT_PUBLIC_SITE_URL` (absolute URLs in llms.txt/OG), `NEXT_PUBLIC_MCP_URL`
(MCP endpoint shown in agent docs; defaults to `<origin>/mcp`), `NEXT_PUBLIC_REPO_URL` (source link on /judges).
