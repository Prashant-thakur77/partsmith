"""See the fix: the replacement part shown in place in the user's photo.

Live (or replay): Muse Image with two reference images (the photo and the model render).
Mock: a deterministic composite — the render alpha-blended over the photo — stamped
"MOCK PREVIEW — not AI-generated" so it can never be mistaken for a generated image.
"""

from __future__ import annotations

import io
from dataclasses import dataclass

import numpy as np
from PIL import Image

from services.agent import providers
from services.agent.providers.mocks import label_image

MOCK_LABEL = "MOCK PREVIEW — not AI-generated"
AI_LABEL = "AI preview"
RENDER_OPACITY = 0.75


@dataclass
class PreviewResult:
    image: bytes
    mime: str
    mode: str  # live | replay | mock
    label: str
    prompt: str
    provider: str = ""
    model: str = ""
    usd: float = 0.0


def build_prompt(prompt_hint: str = "", material: str = "PLA") -> str:
    hint = f" {prompt_hint.strip()}" if prompt_hint.strip() else ""
    return (
        "Photorealistic preview. The first image is a photo of a broken plastic part; the second image is a render "
        f"of the 3D-printed replacement, printed in {material}. Show the replacement installed in place of the broken "
        "part, keeping the first photo's framing, lighting and background. Do not change the part's shape, holes or "
        f"proportions from the render.{hint}"
    )


def _render_alpha(render: Image.Image) -> np.ndarray:
    """Alpha from the render: its own alpha channel if present, else everything that isn't near-white background."""
    if render.mode in ("RGBA", "LA") or "transparency" in render.info:
        alpha: np.ndarray = np.asarray(render.convert("RGBA"))[..., 3].astype(np.float32) / 255.0
        return alpha
    rgb = np.asarray(render.convert("RGB")).astype(np.int16)
    corners = np.stack([rgb[0, 0], rgb[0, -1], rgb[-1, 0], rgb[-1, -1]])
    background = np.median(corners, axis=0)
    distance = np.abs(rgb - background).max(axis=2)
    mask: np.ndarray = (distance > 24).astype(np.float32)
    return mask


def composite(photo_png: bytes, render_png: bytes, opacity: float = RENDER_OPACITY) -> bytes:
    """Deterministic mock preview: render scaled to the photo, alpha-blended on top, then labelled."""
    photo = Image.open(io.BytesIO(photo_png)).convert("RGB")
    with Image.open(io.BytesIO(render_png)) as raw:
        render = raw.resize(photo.size, Image.Resampling.BILINEAR)
    alpha = _render_alpha(render)[..., None] * opacity
    base = np.asarray(photo).astype(np.float32)
    top = np.asarray(render.convert("RGB")).astype(np.float32)
    blended = (base * (1 - alpha) + top * alpha).clip(0, 255).astype(np.uint8)
    out = label_image(Image.fromarray(blended), MOCK_LABEL)
    buf = io.BytesIO()
    out.save(buf, format="PNG")
    return buf.getvalue()


def see_the_fix(photo_png: bytes, render_png: bytes, prompt_hint: str = "", material: str = "PLA") -> PreviewResult:
    """Generate the in-place preview (Muse Image when the image stage is live/replay, labelled composite otherwise)."""
    prompt = build_prompt(prompt_hint, material)
    if providers.stage_mode("image") != "mock":
        res = providers.generate_image(prompt, [photo_png, render_png])
        if res.mode != "mock":
            return PreviewResult(res.data, res.mime, res.mode, AI_LABEL, prompt, res.provider, res.model, res.usd)
    return PreviewResult(composite(photo_png, render_png), "image/png", "mock", MOCK_LABEL, prompt, "mock", "composite")
