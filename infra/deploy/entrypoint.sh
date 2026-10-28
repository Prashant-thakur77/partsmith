#!/bin/sh
# Container entrypoint: refuse to start a public API with open admin routes, seed the registry once, serve.
set -eu

if [ -z "${PARTSMITH_ADMIN_TOKEN:-}" ] && [ "${PARTSMITH_ALLOW_OPEN_ADMIN:-0}" != "1" ]; then
  echo "PARTSMITH_ADMIN_TOKEN is empty: admin routes would be open to anyone. Set it (openssl rand -hex 24)," >&2
  echo "or PARTSMITH_ALLOW_OPEN_ADMIN=1 for a private test." >&2
  exit 64
fi

# First boot on an empty /data: build the demo parts from the committed synthetic samples (mock providers, labelled).
if [ "${PARTSMITH_SEED_ON_START:-1}" = "1" ]; then
  python -m services.cli seed --if-empty || echo "seed failed; the API starts with an empty registry" >&2
fi

# One worker process: jobs, their SSE streams and the CAD worker pool live in this process.
exec uvicorn services.api.main:app --host 0.0.0.0 --port "${PORT:-8000}" --workers 1 \
  --proxy-headers --forwarded-allow-ips "${FORWARDED_ALLOW_IPS:-*}" --timeout-keep-alive 75
