## What and why

## How it was checked

- [ ] `make test`, `make lint`, `make typecheck`
- [ ] `pnpm -C apps/web typecheck`, `lint`, `test` (if the web app changed)
- [ ] Tests added or updated
- [ ] New stages emit their events; model calls go through `services/agent/providers`
- [ ] No hand-typed metrics: numbers come from a script, and untested things say so
- [ ] `docs/DECISIONS.md` updated for an architectural choice
