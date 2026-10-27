# Self-hosted open weights on Modal

Two optional Modal apps power PartSmith's open-weights path. Neither is needed to run PartSmith: without their URLs the
stages that use them run as deterministic mocks (shown on `/status` and by `make smoke`).

| App | File | Serves | Used by stage | Env var in `.env` |
|---|---|---|---|---|
| `partsmith-glimmer` | `glimmer.py` | Muse Glimmer 30B, GGUF Q4_K_M + vision projector, llama.cpp OpenAI-compatible server | `judge`, `capture_triage` (and `understand` with `OPEN_WEIGHTS_ONLY=1`) | `GLIMMER_BASE_URL`, `GLIMMER_API_KEY` |
| `partsmith-sam3` | `sam3.py` | SAM 3 open weights (`facebook/sam3` image model), `POST /segment`, `GET /health` | `segment` with `OPEN_WEIGHTS_ONLY=1`, or as fallback when `MODEL_API_KEY` is missing | `SAM3_OPEN_URL`, `SAM3_OPEN_API_KEY` |

## Deploy

```bash
pip install modal            # or: uv tool install modal
modal token new              # opens the browser once; writes ~/.modal.toml

# Muse Glimmer 30B (weights are public, no Hugging Face token needed)
export GLIMMER_API_KEY=$(openssl rand -hex 24)
modal secret create glimmer GLIMMER_API_KEY=$GLIMMER_API_KEY
modal run infra/modal/glimmer.py::download     # optional: pre-fill the weights volume (~18.5 GB, once)
modal run infra/modal/glimmer.py               # ephemeral test: /health + one question about a red square image
modal deploy infra/modal/glimmer.py            # prints the server URL
#   → .env: GLIMMER_BASE_URL=<printed URL>   GLIMMER_API_KEY=<same value as the secret>

# SAM 3 open weights (checkpoint is gated: request access to facebook/sam3 on Hugging Face first)
modal secret create huggingface HF_TOKEN=hf_...
export SAM3_OPEN_API_KEY=$(openssl rand -hex 24)
modal secret create partsmith-sam3 SAM3_OPEN_API_KEY=$SAM3_OPEN_API_KEY
modal run infra/modal/sam3.py                  # ephemeral test: /health + one /segment call
modal deploy infra/modal/sam3.py               # prints the web endpoint URL
#   → .env: SAM3_OPEN_URL=<printed URL>   SAM3_OPEN_API_KEY=<same value as the secret>

make smoke                                     # both rows should turn ✅
```

`GLIMMER_BASE_URL` may be given with or without the trailing `/v1`. Set `OPEN_WEIGHTS_ONLY=1` to route every stage
to open-weight models (Muse Spark Open builder on Baseten/Fireworks/Together, Glimmer, SAM 3 on Modal).

## Hardware and cost

- **Glimmer:** L40S by default (48 GB). Q4_K_M weights (~17 GB) plus the mmproj (~1.4 GB) also fit a 24 GB L4, but
  decode speed is bound by memory bandwidth and an L4 has roughly a third of an L40S's, so judge calls take about three
  times longer. `GLIMMER_GPU=L4 modal deploy infra/modal/glimmer.py` trades latency for cost. Context is 131,072
  tokens split across 2 parallel slots (65,536 per request; reasoning tokens count against it).
- **SAM 3:** an L4 is enough for single images (`SAM3_GPU` to change).
- Both apps **scale to zero**: no container, no charge while idle. A cold start loads weights from a Modal Volume
  (`partsmith-glimmer-weights`, `partsmith-hf-cache`); the very first start also downloads them. Requests during a
  Glimmer cold start get HTTP 503 until a replica is ready; PartSmith retries 503 with backoff, and `make smoke` waits
  up to `--cold-start-s` (default 300 s).
- GPU time is billed per second by Modal; see https://modal.com/pricing for current rates (an L40S costs more per
  hour than an L4). PartSmith records self-hosted calls as $0 per token in `model_call` events, because the cost is
  GPU time on the Modal dashboard rather than tokens.

## Security

- Glimmer: the endpoint is public, but every inference route requires `Authorization: Bearer $GLIMMER_API_KEY`
  (llama.cpp `--api-key`); `/health` and `/v1/models` stay open.
- SAM 3: `/segment` requires `Authorization: Bearer $SAM3_OPEN_API_KEY`; `/health` is open.
- Keys live in Modal secrets and in your local `.env` only. Never commit them.

## Not deployed by default

Nothing here is deployed automatically. Pin `GLIMMER_REVISION` (Hugging Face commit of the GGUF repo) after the first
successful deploy so cold starts always load the same files.
