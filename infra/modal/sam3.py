"""SAM 3 open weights on a Modal GPU, for PartSmith's all-open-weights mode.

    modal secret create huggingface HF_TOKEN=hf_...               # read token with access to gated facebook/sam3
    modal secret create partsmith-sam3 SAM3_OPEN_API_KEY=$(openssl rand -hex 24)
    modal run infra/modal/sam3.py                                 # ephemeral app + /health + one /segment call
    modal deploy infra/modal/sam3.py                              # prints the URL → SAM3_OPEN_URL

API (mirrors what `services.agent.providers.segment` returns; client in `services/agent/providers/sam_open.py`):
    GET  /health  -> {"ok": true, "model": "sam3", "gpu": str}
    POST /segment {"image_b64": str, "prompt": "<one noun phrase>", "threshold": 0.5}
         -> {"width", "height", "model", "ms",
             "masks": [{"score", "box_xyxy": [x1, y1, x2, y2], "rle": {"size": [h, w], "counts": [...]}}]}
    POST /segment_video {"video_b64": str (MP4), "prompt": "<one noun phrase>", "fps": float}
         -> {"width", "height", "model": "sam3.1", "ms",
             "frames": [{"frame_idx", "t_s", "masks": [{"object_id", "score", "rle"}]}]}   (SAM 3.1 multiplex tracker)
    `rle`: uncompressed row-major run lengths starting with a run of False; masks are full-frame (h x w of the input).
    Requests need `Authorization: Bearer $SAM3_OPEN_API_KEY`.

The image model downloads the `facebook/sam3` checkpoint (gated: request access on Hugging Face first). It predicts at
1008 x 1008, so the caller re-runs on a crop for sub-millimetre edges. An L4 is enough for single images.
"""

import os  # no `from __future__ import annotations`: FastAPI must resolve the local request model

import modal

MINUTES = 60
SAM3_COMMIT = "f1647e8"  # facebookresearch/sam3, pinned
GPU = os.environ.get("SAM3_GPU", "L4")
HF_CACHE = "/hf-cache"

image = (
    modal.Image.debian_slim(python_version="3.12")
    .apt_install("git", "libgl1", "libglib2.0-0")
    .uv_pip_install("torch==2.10.0", "torchvision", index_url="https://download.pytorch.org/whl/cu128")
    .uv_pip_install(
        "numpy<2",
        "pillow",
        "pycocotools",
        "huggingface_hub[hf_xet]",
        "fastapi[standard]",
        f"git+https://github.com/facebookresearch/sam3.git@{SAM3_COMMIT}",
    )
    .env({"HF_HUB_CACHE": HF_CACHE, "HF_XET_HIGH_PERFORMANCE": "1"})
)
cache = modal.Volume.from_name("partsmith-hf-cache", create_if_missing=True)
app = modal.App("partsmith-sam3")


def rle_encode(mask) -> dict:
    """Uncompressed row-major run lengths, first run counts False pixels (may be 0)."""
    import numpy as np

    flat = np.ascontiguousarray(mask, dtype=bool).ravel()
    h, w = int(mask.shape[0]), int(mask.shape[1])
    if flat.size == 0:
        return {"size": [h, w], "counts": []}
    change = np.flatnonzero(flat[1:] != flat[:-1]) + 1
    counts = np.diff(np.concatenate(([0], change, [flat.size]))).tolist()
    if flat[0]:
        counts = [0, *counts]
    return {"size": [h, w], "counts": [int(c) for c in counts]}


@app.cls(
    image=image,
    gpu=GPU,
    volumes={HF_CACHE: cache},
    secrets=[
        modal.Secret.from_name("huggingface", required_keys=["HF_TOKEN"]),
        modal.Secret.from_name("partsmith-sam3", required_keys=["SAM3_OPEN_API_KEY"]),
    ],
    scaledown_window=10 * MINUTES,  # scale to zero after 10 idle minutes
    timeout=20 * MINUTES,  # orbit clips: a few hundred frames through the tracker
    min_containers=0,
)
@modal.concurrent(max_inputs=4)
class Sam3Service:
    @modal.enter()
    def load(self) -> None:
        import torch
        from sam3.model.sam3_image_processor import Sam3Processor
        from sam3.model_builder import build_sam3_image_model

        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.gpu = torch.cuda.get_device_name(0) if self.device == "cuda" else "cpu"
        self.processor = Sam3Processor(build_sam3_image_model(device=self.device), device=self.device)
        self.video_predictor = None  # SAM 3.1 multiplex tracker, loaded on the first /segment_video call
        cache.commit()  # keep the downloaded checkpoint for the next cold start

    def run_video(self, video_b64: str, prompt: str, fps: float) -> dict:
        """Track one noun phrase through an MP4 with the SAM 3.1 multiplex video predictor (gated facebook/sam3.1)."""
        import base64
        import tempfile
        import time

        import numpy as np
        import torch

        t0 = time.perf_counter()
        if self.video_predictor is None:
            from sam3.model_builder import build_sam3_predictor

            # FlashAttention-3 kernels need an H100; everything smaller runs the default attention.
            use_fa3 = "H100" in self.gpu
            self.video_predictor = build_sam3_predictor(version="sam3.1", use_fa3=use_fa3, max_num_objects=16)
            cache.commit()
        predictor = self.video_predictor
        with tempfile.NamedTemporaryFile(suffix=".mp4") as f:
            f.write(base64.b64decode(video_b64))
            f.flush()
            session = predictor.handle_request({"type": "start_session", "resource_path": f.name})["session_id"]
            try:
                with torch.inference_mode():
                    predictor.handle_request(
                        {"type": "add_prompt", "session_id": session, "frame_index": 0, "text": prompt}
                    )
                    frames, size = [], None
                    stream = predictor.handle_stream_request({"type": "propagate_in_video", "session_id": session})
                    for item in stream:
                        out = item["outputs"]
                        masks = np.asarray(out["out_binary_masks"]).astype(bool)
                        if masks.ndim == 4:
                            masks = masks[:, 0]
                        if masks.size:
                            size = masks.shape[-2:]
                        rows = [
                            {"object_id": str(int(o)), "score": float(p), "rle": rle_encode(m)}
                            for o, p, m in zip(out["out_obj_ids"], out["out_probs"], masks, strict=True)
                        ]
                        idx = int(item["frame_index"])
                        frames.append({"frame_idx": idx, "t_s": idx / fps, "masks": rows})
            finally:
                predictor.handle_request({"type": "close_session", "session_id": session})
        frames.sort(key=lambda fr: fr["frame_idx"])
        height, width = (int(size[0]), int(size[1])) if size is not None else (0, 0)
        ms = int((time.perf_counter() - t0) * 1000)
        return {"width": width, "height": height, "model": "sam3.1", "ms": ms, "frames": frames}

    def run_segment(self, image_b64: str, prompt: str, threshold: float) -> dict:
        import base64
        import io
        import time

        import numpy as np
        import torch
        from PIL import Image

        t0 = time.perf_counter()
        img = Image.open(io.BytesIO(base64.b64decode(image_b64))).convert("RGB")
        width, height = img.size
        with torch.inference_mode():
            self.processor.set_confidence_threshold(threshold)
            state = self.processor.set_image(img)
            out = self.processor.set_text_prompt(state=state, prompt=prompt)
        masks = out["masks"].detach().cpu().numpy().astype(bool)  # [N, 1, H, W]
        boxes = out["boxes"].detach().cpu().float().numpy().tolist()
        scores = out["scores"].detach().cpu().float().numpy().tolist()
        items = []
        for m, b, s in zip(masks, boxes, scores, strict=True):
            m = m.reshape(m.shape[-2], m.shape[-1])
            if m.shape != (height, width):  # defensive: always answer in input-pixel coordinates
                m = np.asarray(Image.fromarray(m).resize((width, height), Image.Resampling.NEAREST))
            items.append({"score": float(s), "box_xyxy": [float(v) for v in b], "rle": rle_encode(m)})
        items.sort(key=lambda d: -d["score"])
        return {"width": width, "height": height, "model": "sam3", "ms": int((time.perf_counter() - t0) * 1000), "masks": items}

    @modal.asgi_app()
    def web(self):
        from fastapi import FastAPI, Header, HTTPException
        from pydantic import BaseModel, Field

        api = FastAPI(title="PartSmith SAM 3 (open weights)")
        expected = os.environ["SAM3_OPEN_API_KEY"]

        class SegmentIn(BaseModel):
            image_b64: str = Field(max_length=40_000_000)
            prompt: str = Field(min_length=1, max_length=80)
            threshold: float = Field(0.5, ge=0.0, le=1.0)

        @api.get("/health")
        def health() -> dict:
            return {"ok": True, "model": "sam3", "gpu": self.gpu}

        @api.post("/segment")
        def segment(body: SegmentIn, authorization: str = Header(default="")) -> dict:
            if authorization != f"Bearer {expected}":
                raise HTTPException(status_code=401, detail="missing or wrong bearer token")
            phrase = " ".join(body.prompt.split())
            if "," in phrase:
                raise HTTPException(status_code=400, detail="one noun phrase per request (no commas)")
            try:
                return self.run_segment(body.image_b64, phrase, body.threshold)
            except (ValueError, OSError) as exc:
                raise HTTPException(status_code=400, detail=f"bad image: {exc}") from exc

        class VideoIn(BaseModel):
            video_b64: str = Field(max_length=280_000_000)  # ~200 MB of MP4
            prompt: str = Field(min_length=1, max_length=80)
            fps: float = Field(5.0, gt=0.0, le=60.0)

        @api.post("/segment_video")
        def segment_video(body: VideoIn, authorization: str = Header(default="")) -> dict:
            if authorization != f"Bearer {expected}":
                raise HTTPException(status_code=401, detail="missing or wrong bearer token")
            phrase = " ".join(body.prompt.split())
            if "," in phrase:
                raise HTTPException(status_code=400, detail="one noun phrase per request (no commas)")
            try:
                return self.run_video(body.video_b64, phrase, body.fps)
            except (ValueError, OSError, RuntimeError) as exc:
                raise HTTPException(status_code=400, detail=f"bad video: {exc}") from exc

        return api


@app.local_entrypoint()
def main(prompt: str = "dark square") -> None:
    import base64
    import json
    import struct
    import urllib.request
    import zlib

    size, row = 256, []
    for y in range(256):
        line = b"\x00" + b"".join(b"\x14\x14\x14" if 64 <= x < 192 and 64 <= y < 192 else b"\xeb\xeb\xeb" for x in range(size))
        row.append(line)

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    png = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(b"".join(row)))
        + chunk(b"IEND", b"")
    )
    url = Sam3Service().web.get_web_url()
    print(f"SAM 3 URL: {url}   (SAM3_OPEN_URL={url})")
    with urllib.request.urlopen(f"{url}/health", timeout=600) as r:
        print("/health:", r.read().decode())
    key = os.environ.get("SAM3_OPEN_API_KEY", "")
    if not key:
        print("Set SAM3_OPEN_API_KEY locally (same value as the Modal secret) to run a /segment call.")
        return
    req = urllib.request.Request(
        f"{url}/segment",
        data=json.dumps({"image_b64": base64.b64encode(png).decode(), "prompt": prompt}).encode(),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
    )
    with urllib.request.urlopen(req, timeout=600) as r:
        out = json.loads(r.read())
    print(f"{len(out['masks'])} mask(s) in {out['ms']} ms; scores {[round(m['score'], 3) for m in out['masks']]}")
