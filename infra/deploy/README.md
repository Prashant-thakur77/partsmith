# Deploying PartSmith (public demo)

> **Owner's go-ahead first.** Deploying makes the project public. Nothing here has been deployed; these files only
> prepare it. Run `make deploy-check` before and after any edit to them (static checks only: it builds no image).

The public site runs with **zero model keys**: `PROVIDER_MODE=replay` serves recorded calls and runs anything not
recorded as a labelled deterministic mock. The committed replays (`data/replays`), demo samples
(`data/synthetic/samples`) and bench reports (`eval/reports`, including the lying-model evidence on `/judges`) are
part of the API image, so `/judges`, "Try a sample" (`/jobs/demo`) and the registry work on first boot.

**The submission runs on one AWS server:** API, web app and an HTTPS front with Docker Compose. See
[aws/README.md](aws/README.md). The Modal and Vercel paths below remain optional.

| Piece | Where | Files |
|---|---|---|
| API (FastAPI + SSE + MCP + sandboxed CadQuery worker) | Modal **or** any VM with Docker | `Dockerfile`, `Dockerfile.dockerignore`, `entrypoint.sh`, `modal_app.py`, `api.env.example` |
| Web (Next.js) | Vercel, project root `apps/web` | `web.env.example` |

The browser only talks to the web origin: the web app proxies `/api/v1/*`, `/mcp` and the job event stream to the
API, so the API needs no CORS for the site and one URL is enough to share.

## Before either path

1. Pick the two host names (e.g. the Vercel URL and the API URL).
2. `openssl rand -hex 24` → the admin token. The API refuses to start without `PARTSMITH_ADMIN_TOKEN`.
3. Optional: `uv run python -m eval.bypass` so `/judges` shows the latest lying-model evidence, then
   `make deploy-check`.

## (a) API on Modal

Needs the Modal CLI (`uv tool install modal`, then `modal token new`). The image is built from `pyproject.toml` +
`uv.lock` with Modal's `Image.uv_sync` (recent Modal client required).

```bash
modal secret create partsmith-api \
  PARTSMITH_ADMIN_TOKEN=<token> \
  PARTSMITH_CORS_ORIGINS=https://<web host> \
  PARTSMITH_WEB_URL=https://<web host> \
  PARTSMITH_PUBLIC_URL=https://<web host> \
  PARTSMITH_MCP_ALLOWED_HOSTS=<web host>,<workspace>--partsmith-api-api.modal.run
modal run infra/deploy/modal_app.py::seed        # once: demo parts into the partsmith-data Volume
modal deploy infra/deploy/modal_app.py            # prints https://<workspace>--partsmith-api-api.modal.run
curl https://<workspace>--partsmith-api-api.modal.run/api/v1/health
```

One container at most (`max_containers=1`): jobs and their event streams live in its memory. It scales to zero after
15 idle minutes; the first request after that waits for a cold start. Runtime data persists on the `partsmith-data`
Volume.

## (a') API on any VM with Docker

```bash
cp infra/deploy/api.env.example ~/partsmith-api.env     # outside the repo; fill in the REQUIRED lines
docker build -f infra/deploy/Dockerfile -t partsmith-api .
docker volume create partsmith-data
docker run -d --name partsmith-api --restart unless-stopped \
  --env-file ~/partsmith-api.env -v partsmith-data:/data -p 8000:8000 partsmith-api
docker logs -f partsmith-api                              # first boot seeds the demo parts, then serves
curl http://localhost:8000/api/v1/health
```

Put HTTPS in front (Caddy: `caddy reverse-proxy --from api.example.com --to localhost:8000`). Keep response
buffering off for `/api/v1/jobs/*/events` (Caddy does by default; nginx: `proxy_buffering off`). A 2 vCPU / 4 GB
machine is enough for the demo; `PARTSMITH_GEOM_WORKERS=1` keeps memory near 1.5 GB.

`~/partsmith-api.env` holds the admin token: keep it out of the repository.

## (b) Web on Vercel

1. New Project → import the repository → **Root Directory: `apps/web`** (Vercel detects Next.js and the pnpm
   workspace; leave the build and install commands on their defaults).
2. Environment variables (Production and Preview), from `web.env.example`:
   - `NEXT_PUBLIC_API_URL` = the API origin from (a) or (a'), no trailing slash, no `/api/v1`;
   - `NEXT_PUBLIC_SITE_URL` = the Vercel URL (or the custom domain);
   - optional `NEXT_PUBLIC_REPO_URL`, `NEXT_PUBLIC_VOTE_URL`.
3. Deploy. The API URL is read at build time for the proxy rules, so **redeploy the web after changing it**.
4. Back on the API, make sure `PARTSMITH_CORS_ORIGINS`, `PARTSMITH_WEB_URL` and `PARTSMITH_MCP_ALLOWED_HOSTS`
   name the final web host.

## After deploying: the incognito check

- `/` → "Try a sample" → a synthetic sample runs and is labelled synthetic + mock.
- `/judges` → replay plays; "A lying model, caught" shows two overlays and "Export blocked".
- `/models` says replay/mock for every stage (no keys on the server).
- A best-effort part's STL/3MF/STEP answers `409 needs_ack` without `ack=1`, from every route.
- `/llms.txt` and `/mcp` answer on the web origin.

## Going live later

Only with the owner's go-ahead (it spends credits): add the model keys to the secret or `api.env`, set
`PROVIDER_MODE=` (empty = live where a key exists) and keep `PROVIDER_FALLBACK_TO_MOCK=1` so a failed provider
degrades to a labelled mock instead of an error page.

**Visitors' uploads in live mode.** Photos, clips and voice notes go to Meta's model API (GPS is stripped first). While
the account uses Meta's free credits, Meta's billing page says that content may be used to improve its products; `/fix`
tells visitors so and asks them to leave faces and anything private out of frame. Set a usage alert on the Meta billing
page and keep `PARTSMITH_BUY_LOOKUP=0` if the public site should not run a web search per job.
