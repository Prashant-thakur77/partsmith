"""Muse Glimmer 30B on a Modal GPU: llama.cpp's OpenAI-compatible server, GGUF Q4_K_M + vision projector.

PartSmith uses it as the independent judge and for capture triage (open weights, different family from the builder).

    modal secret create glimmer GLIMMER_API_KEY=$(openssl rand -hex 24)
    modal run infra/modal/glimmer.py::download      # optional: pre-fill the weights volume (~18.5 GB)
    modal run infra/modal/glimmer.py                # ephemeral server + one hello-with-image call
    modal deploy infra/modal/glimmer.py             # prints the URL → GLIMMER_BASE_URL (and the key → GLIMMER_API_KEY)

GPU: L40S by default (48 GB). The Q4_K_M weights (~17 GB) plus the mmproj (~1.4 GB) also fit a 24 GB L4, but decode
is memory-bandwidth bound and an L4 has roughly a third of the L40S bandwidth, so judge calls (hundreds to a couple of
thousand reasoning tokens) take about three times longer. Deploy with `GLIMMER_GPU=L4` to trade latency for cost.
Scale-to-zero: no container runs (and nothing is billed) while idle; the first request after idle waits for a cold start.
"""

from __future__ import annotations

import json
import os
import struct
import subprocess
import time
import urllib.error
import urllib.request
import zlib

import modal

MINUTES = 60
PORT = 8000
MODEL_REPO = "meta-models/Muse-Glimmer-30B-GGUF"
MODEL_REVISION = os.environ.get("GLIMMER_REVISION", "main")  # pin to a commit sha once the first deploy works
MODEL_FILE = "Muse-Glimmer-30B-KQuant-17GB-Q4_K_M.gguf"
MMPROJ_FILE = "mmproj-Muse-Glimmer-30B-Q4_K_M.gguf"
SERVED_NAME = "muse-glimmer"  # the `model` PartSmith sends
GPU = os.environ.get("GLIMMER_GPU", "L40S")
N_SLOTS = 2  # concurrent requests per container
CTX_TOTAL = 131072  # split across slots: 65536 tokens per request (reasoning counts against it)
LLAMA_CPP_IMAGE = "ghcr.io/ggml-org/llama.cpp:server-cuda-b10355"  # a release with Muse Glimmer support

WEIGHTS = "/models"
volume = modal.Volume.from_name("partsmith-glimmer-weights", create_if_missing=True)

image = (
    modal.Image.from_registry(LLAMA_CPP_IMAGE, add_python="3.12")
    .entrypoint([])
    .uv_pip_install("huggingface_hub[hf_xet]>=0.34,<2")
    .env({"HF_XET_HIGH_PERFORMANCE": "1"})
)

app = modal.App("partsmith-glimmer")


def fetch_weights() -> tuple[str, str]:
    """Download the GGUF + mmproj into the volume once; later cold starts read them from the volume."""
    from huggingface_hub import hf_hub_download

    paths = []
    for filename in (MODEL_FILE, MMPROJ_FILE):
        target = os.path.join(WEIGHTS, filename)
        if not os.path.exists(target):
            hf_hub_download(MODEL_REPO, filename, revision=MODEL_REVISION, local_dir=WEIGHTS)
        paths.append(target)
    return paths[0], paths[1]


@app.function(image=image, volumes={WEIGHTS: volume}, timeout=60 * MINUTES)
def download() -> None:
    model, mmproj = fetch_weights()
    volume.commit()
    for p in (model, mmproj):
        print(f"{p}: {os.path.getsize(p) / 1e9:.2f} GB")


@app.server(
    image=image,
    gpu=GPU,
    port=PORT,
    volumes={WEIGHTS: volume},
    secrets=[modal.Secret.from_name("glimmer", required_keys=["GLIMMER_API_KEY"])],
    min_containers=0,  # scale to zero
    scaledown_window=10 * MINUTES,
    startup_timeout=30 * MINUTES,  # first start downloads ~18.5 GB
    target_concurrency=N_SLOTS,
    exit_grace_period=30,
    unauthenticated=True,  # inference endpoints are guarded by llama.cpp's --api-key; /health stays open
)
class GlimmerServer:
    @modal.enter()
    def start(self) -> None:
        model, mmproj = fetch_weights()
        volume.commit()
        cmd = [
            "/app/llama-server",
            "--model", model,
            "--mmproj", mmproj,
            "--alias", SERVED_NAME,
            "--jinja",
            "--chat-template-kwargs", json.dumps({"reasoning_strength": "low"}),  # default; requests may override
            "--host", "0.0.0.0",
            "--port", str(PORT),
            "--n-gpu-layers", "999",
            "--ctx-size", str(CTX_TOTAL),
            "--parallel", str(N_SLOTS),
            "--api-key", os.environ["GLIMMER_API_KEY"],
            "--metrics",
        ]  # fmt: skip
        self.proc = subprocess.Popen(cmd, start_new_session=True)
        wait_ready(self.proc)

    @modal.exit()
    def stop(self) -> None:
        self.proc.terminate()
        try:
            self.proc.wait(timeout=20)
        except subprocess.TimeoutExpired:
            self.proc.kill()


def wait_ready(proc: subprocess.Popen, timeout_s: float = 25 * MINUTES) -> None:
    """Block until llama-server answers /health with 200 (it returns 503 while the model loads)."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if (code := proc.poll()) is not None:
            raise RuntimeError(f"llama-server exited with code {code}")
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/health", timeout=5) as r:
                if r.status == 200:
                    return
        except (urllib.error.URLError, ConnectionError, TimeoutError):
            pass
        time.sleep(2)
    raise TimeoutError("llama-server did not become healthy in time")


def request_with_retry(req: urllib.request.Request, timeout_s: float) -> bytes:
    """Modal answers 503 while no replica is up (scale from zero); keep asking until the deadline."""
    deadline, delay = time.monotonic() + timeout_s, 2.0
    while True:
        try:
            with urllib.request.urlopen(req, timeout=max(5.0, deadline - time.monotonic())) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code != 503 or time.monotonic() > deadline:
                raise
        time.sleep(delay)
        delay = min(delay * 1.5, 15.0)


def tiny_png(rgb: tuple[int, int, int] = (200, 30, 30), size: int = 64) -> bytes:
    """A solid-colour square as PNG, built with zlib only (the local side has no imaging library)."""
    row = b"\x00" + bytes(rgb) * size
    raw = zlib.compress(row * size)

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    header = struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", raw) + chunk(b"IEND", b"")


@app.local_entrypoint()
def main(question: str = "What colour is this square? Answer in one word.", timeout_s: int = 30 * MINUTES) -> None:
    import base64

    url = GlimmerServer.get_url()
    print(f"Glimmer URL: {url}   (GLIMMER_BASE_URL={url})")
    health = request_with_retry(urllib.request.Request(f"{url}/health"), timeout_s)
    print(f"/health: {health.decode()[:200]}")
    key = os.environ.get("GLIMMER_API_KEY", "")
    if not key:
        print("Set GLIMMER_API_KEY locally (same value as the Modal secret) to run the chat call.")
        return
    data_url = "data:image/png;base64," + base64.b64encode(tiny_png()).decode()
    body = {
        "model": SERVED_NAME,
        "messages": [
            {
                "role": "user",
                "content": [{"type": "text", "text": question}, {"type": "image_url", "image_url": {"url": data_url}}],
            }
        ],
        "chat_template_kwargs": {"reasoning_strength": "low"},
        "max_tokens": 2048,
        "temperature": 0,
    }
    req = urllib.request.Request(
        f"{url}/v1/chat/completions",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
    )
    t0 = time.perf_counter()
    reply = json.loads(request_with_retry(req, timeout_s))
    elapsed = time.perf_counter() - t0
    print(f"reply: {reply['choices'][0]['message'].get('content')!r}")
    print(f"usage: {reply.get('usage')}   latency: {elapsed:.1f} s")
