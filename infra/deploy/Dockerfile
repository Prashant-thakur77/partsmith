# PartSmith API + the sandboxed CadQuery geometry worker, in one image. Build from the repo root:
#
#   docker build -f infra/deploy/Dockerfile -t partsmith-api .
#   docker run --rm -p 8000:8000 --env-file infra/deploy/api.env -v partsmith-data:/data partsmith-api
#
# Public default: no model keys and PROVIDER_MODE=replay (recorded calls; labelled deterministic mocks for anything not
# recorded). The committed replays, demo samples and bench reports are baked in, so the judge path works on first boot.
# Runtime data (SQLite registry, blobs, bakes, jobs) lives under PARTSMITH_HOME=/data; mount a volume there.

ARG PYTHON_IMAGE=python:3.12-slim-bookworm

FROM ghcr.io/astral-sh/uv:0.10.9 AS uv

# ---------------------------------------------------------------------------------------------- dependencies (cached)
FROM ${PYTHON_IMAGE} AS deps
COPY --from=uv /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never UV_PROJECT_ENVIRONMENT=/opt/venv
WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
# `sam` = the SAM 3.1 response parser (needed only once live keys are added). Add "--extra storage" for Postgres/R2.
ARG UV_EXTRAS="--extra sam"
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project ${UV_EXTRAS}

# ---------------------------------------------------------------------------------------------- runtime
FROM ${PYTHON_IMAGE}
# The OCP (CadQuery) and VTK wheels bundle their own libraries except the system OpenGL and X11 client libraries;
# tini reaps the geometry worker processes.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgl1 libx11-6 libexpat1 tini \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 partsmith \
    && mkdir -p /data && chown partsmith:partsmith /data

COPY --from=deps /opt/venv /opt/venv
WORKDIR /app
# Code is read-only for the service user; only /data is writable.
COPY services services
COPY packages/schemas packages/schemas
COPY tools tools
COPY eval/reports eval/reports
COPY data/replays data/replays
COPY data/synthetic/samples data/synthetic/samples
COPY --chmod=755 infra/deploy/entrypoint.sh /usr/local/bin/partsmith-entrypoint

ENV PATH=/opt/venv/bin:$PATH \
    PYTHONPATH=/app:/app/packages/schemas \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PARTSMITH_HOME=/data \
    PROVIDER_MODE=replay \
    PARTSMITH_GEOM_WORKERS=1 \
    PORT=8000

USER partsmith
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=120s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\", \"8000\")}/api/v1/health', timeout=4)"
ENTRYPOINT ["tini", "--", "partsmith-entrypoint"]
