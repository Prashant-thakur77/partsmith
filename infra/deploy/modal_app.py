"""PartSmith API on Modal: the FastAPI app (REST + SSE + MCP) and the sandboxed CadQuery worker in one CPU container.

Public default: no model keys, PROVIDER_MODE=replay (recorded calls, labelled deterministic mocks otherwise).

    modal secret create partsmith-api PARTSMITH_ADMIN_TOKEN=$(openssl rand -hex 24) \
        PARTSMITH_CORS_ORIGINS=https://<web host> PARTSMITH_WEB_URL=https://<web host> \
        PARTSMITH_MCP_ALLOWED_HOSTS=<web host>
    modal run infra/deploy/modal_app.py::seed      # once: demo parts into the partsmith-data volume
    modal deploy infra/deploy/modal_app.py          # prints https://<workspace>--partsmith-api-api.modal.run

The same files as the Docker image go in (code, committed replays, demo samples, bench reports); runtime data lives
on the `partsmith-data` Volume at /data. One container at most: jobs and their SSE streams live in its memory.
"""

from pathlib import Path

import modal

REPO = Path(__file__).resolve().parents[2]
ROOT = "/app"  # the repo layout inside the container (services/common/paths.py derives REPO_ROOT from it)
MINUTES = 60
IGNORE = ["**/__pycache__", "**/*.pyc", "**/tests", "**/.env", "**/.env.*"]
SOURCES = (  # keep in step with infra/deploy/Dockerfile (make deploy-check compares them)
    "services",
    "packages/schemas",
    "tools",
    "eval/reports",
    "data/replays",
    "data/synthetic/samples",
)
ENV = {
    "PYTHONPATH": f"{ROOT}:{ROOT}/packages/schemas",
    "PYTHONUNBUFFERED": "1",
    "PYTHONDONTWRITEBYTECODE": "1",
    "PARTSMITH_HOME": "/data",
    "PROVIDER_MODE": "replay",
    "PARTSMITH_GEOM_WORKERS": "1",
    "PARTSMITH_MCP_READ_ONLY": "1",
    "PARTSMITH_RATE_LIMIT": "60",
}

image = (
    modal.Image.debian_slim(python_version="3.12")
    # the OCP (CadQuery) and VTK wheels need only the system OpenGL and X11 client libraries
    .apt_install("libgl1", "libx11-6", "libexpat1")
    .uv_sync(uv_project_dir=str(REPO), extras=["sam"], frozen=True)
    .env(ENV)
    .workdir(ROOT)
)
for rel in SOURCES:
    image = image.add_local_dir(REPO / rel, f"{ROOT}/{rel}", ignore=IGNORE)

data = modal.Volume.from_name("partsmith-data", create_if_missing=True)
secret = modal.Secret.from_name("partsmith-api")  # PARTSMITH_ADMIN_TOKEN (required) + the public URLs
app = modal.App("partsmith-api")


@app.function(
    image=image,
    volumes={"/data": data},
    secrets=[secret],
    cpu=2.0,
    memory=4096,
    max_containers=1,  # in-process job manager: never split jobs across containers
    scaledown_window=15 * MINUTES,
    timeout=60 * MINUTES,
)
@modal.concurrent(max_inputs=64)
@modal.asgi_app()
def api():  # type: ignore[no-untyped-def]
    import os

    if not os.environ.get("PARTSMITH_ADMIN_TOKEN"):
        raise RuntimeError("PARTSMITH_ADMIN_TOKEN is missing from the partsmith-api secret: admin routes would be open")
    from services.api.main import app as fastapi_app

    return fastapi_app


@app.function(image=image, volumes={"/data": data}, secrets=[secret], cpu=2.0, memory=4096, timeout=60 * MINUTES)
def seed() -> None:
    """Build the demo parts from the committed synthetic samples (mock providers, labelled) into the Volume."""
    import subprocess
    import sys

    subprocess.run([sys.executable, "-m", "services.cli", "seed", "--if-empty"], cwd=ROOT, check=True)
    data.commit()
