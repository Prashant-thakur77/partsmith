"""Deterministic mocks used when a stage has no key (or PROVIDER_MODE=mock).

The orchestrator plugs domain mocks with `register_mock(stage, handler)`; without one, each stage gets a built-in
fallback: a minimal schema-valid JSON answer (strings say "mock"), a placeholder CadQuery program for `build`,
a background-subtraction mask for `segment`, a labelled placeholder image and a labelled placeholder transcript.
Everything here is labelled mock by the caller (`mode="mock"`).
"""

from __future__ import annotations

import io
import json
from typing import Any

import numpy as np

from . import jsonschema_lite, media
from .base import MockHandler, ModelRequest, ProviderError

_handlers: dict[str, MockHandler] = {}

MOCK_TEXT_NOTE = "deterministic mock — no model was called"

MOCK_BUILD_PROGRAM = """```python
# MOCK placeholder program (deterministic mock, no model was called). Edit PARAMS only.
import cadquery as cq

PARAMS = {  # name: (default, min, max, step, unit, affects_fit, label)
    "length": (40.0, 10.0, 120.0, 0.5, "mm", True, "Length"),
    "width": (20.0, 5.0, 80.0, 0.5, "mm", True, "Width"),
    "thickness": (3.0, 1.2, 10.0, 0.1, "mm", True, "Thickness"),
}


def build(p):
    return cq.Workplane("XY").box(p["length"], p["width"], p["thickness"], centered=(True, True, False))


result = build({k: v[0] for k, v in PARAMS.items()})
```"""

MOCK_TRANSCRIPT = "hole thoda bada karo"


def register_mock(stage: str, handler: MockHandler, *, replace: bool = True) -> None:
    """Install a deterministic handler for `stage`. With `replace=False` an existing handler is kept."""
    if replace or stage not in _handlers:
        _handlers[stage] = handler


def unregister_mock(stage: str) -> None:
    _handlers.pop(stage, None)


def clear_mocks() -> None:
    _handlers.clear()


def handler_for(stage: str) -> MockHandler | None:
    return _handlers.get(stage)


def mock_complete(stage: str, req: ModelRequest) -> tuple[str, Any]:
    """Return (text, parsed json or None). Registered handler output is validated against the schema."""
    handler = _handlers.get(stage)
    if handler is not None:
        out = handler(req)
        parsed: Any
        if isinstance(out, (dict, list)):
            text, parsed = json.dumps(out, ensure_ascii=False), out
        else:
            text = str(out)
            parsed = jsonschema_lite.extract_json(text) if req.json_schema is not None else None
    elif req.json_schema is not None:
        parsed = jsonschema_lite.minimal_instance(req.json_schema)
        text = json.dumps(parsed)
    else:
        parsed = None
        text = MOCK_BUILD_PROGRAM if stage == "build" else f"[mock {stage}] {MOCK_TEXT_NOTE}."
    if req.json_schema is not None:
        errors = jsonschema_lite.validate(parsed, req.json_schema)
        if errors:
            raise ProviderError(f"mock for {stage!r} returned schema-invalid output: {'; '.join(errors[:3])}")
    return text, parsed


def mock_segment(image: bytes, prompt: str) -> list[tuple[media.BoolMask, float]]:
    """Largest region that differs from the border colour. Score 0.5 marks it as a mock guess."""

    handler = _handlers.get("segment")
    if handler is not None:
        result: list[tuple[media.BoolMask, float]] = handler(
            ModelRequest(messages=[{"role": "user", "content": prompt}], images=[image])
        )
        return result
    return threshold_segment(media.decode_image_rgb(image))


def threshold_segment(rgb: Any) -> list[tuple[media.BoolMask, float]]:
    """Background subtraction on an RGB array: largest region unlike the border colour, holes filled."""
    import cv2

    gray = cv2.cvtColor(np.ascontiguousarray(rgb, dtype=np.uint8), cv2.COLOR_RGB2GRAY).astype(np.int16)
    border = np.concatenate([gray[0], gray[-1], gray[:, 0], gray[:, -1]])
    background = int(np.median(border))
    diff = np.abs(gray - background).astype(np.uint8)
    if int(diff.max()) < 12:
        return []
    _, fg = cv2.threshold(diff, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    fg = cv2.morphologyEx(fg, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    n, labels, stats, _ = cv2.connectedComponentsWithStats(fg, connectivity=8)
    if n <= 1:
        return []
    biggest = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    mask = labels == biggest
    filled = np.zeros_like(fg)
    contours, _ = cv2.findContours(mask.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    cv2.drawContours(filled, contours, -1, 255, thickness=-1)
    return [(filled > 0, 0.5)]


def flood_segment(
    rgb: Any,
    points_pos: list[tuple[float, float]],
    points_neg: list[tuple[float, float]],
    box: tuple[float, float, float, float] | None,
    tolerance: int = 14,
) -> list[tuple[media.BoolMask, float]]:
    """Point-prompt stand-in: flood fill from each positive point (similar grey levels), minus the regions grown from
    negative points, clipped to the box. Holes in a part flood to the hole; the part body floods to the body."""
    import cv2

    gray = cv2.cvtColor(np.ascontiguousarray(rgb, dtype=np.uint8), cv2.COLOR_RGB2GRAY)
    h, w = gray.shape

    def grow(x: float, y: float) -> media.BoolMask:
        xi, yi = min(max(round(x), 0), w - 1), min(max(round(y), 0), h - 1)
        ff = np.zeros((h + 2, w + 2), np.uint8)
        flags = 8 | cv2.FLOODFILL_MASK_ONLY | cv2.FLOODFILL_FIXED_RANGE | (255 << 8)
        cv2.floodFill(gray.copy(), ff, (xi, yi), 0, (tolerance,), (tolerance,), flags)
        return ff[1:-1, 1:-1] > 0

    mask = np.zeros((h, w), dtype=bool)
    for x, y in points_pos:
        mask |= grow(x, y)
    for x, y in points_neg:
        mask &= ~grow(x, y)
    if box is not None:
        x1, y1, x2, y2 = (round(v) for v in box)
        clip = np.zeros_like(mask)
        clip[max(0, y1) : max(0, y2) + 1, max(0, x1) : max(0, x2) + 1] = True
        mask &= clip
    return [(mask, 0.5)] if mask.any() else []


def _font(size: int) -> Any:
    from PIL import ImageFont

    for name in ("DejaVuSans-Bold.ttf", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default(size=size)


def label_image(img: Any, text: str) -> Any:
    """Draw a high-contrast banner with `text` across the top of a PIL image (returns RGB)."""
    from PIL import ImageDraw

    out = img.convert("RGB")
    draw = ImageDraw.Draw(out)
    size = max(14, out.width // 32)
    font = _font(size)
    pad = size // 2
    box = draw.textbbox((0, 0), text, font=font)
    draw.rectangle((0, 0, out.width, box[3] - box[1] + 2 * pad), fill=(180, 20, 20))
    draw.text((pad, pad - box[1]), text, fill=(255, 255, 255), font=font)
    return out


def mock_image(prompt: str, references: list[bytes]) -> tuple[bytes, str]:
    from PIL import Image

    handler = _handlers.get("image")
    if handler is not None:
        data: bytes = handler(ModelRequest(messages=[{"role": "user", "content": prompt}], images=list(references)))
        return data, media.sniff_image_mime(data)
    if references:
        img = Image.open(io.BytesIO(references[0])).convert("RGB")
    else:
        img = Image.new("RGB", (768, 512), (200, 200, 200))
    out = label_image(img, "MOCK IMAGE — not AI-generated")
    buf = io.BytesIO()
    out.save(buf, format="PNG")
    return buf.getvalue(), "image/png"


def mock_transcript(audio: bytes, mime: str, language_hint: str | None) -> str:
    handler = _handlers.get("transcribe")
    if handler is not None:
        req = ModelRequest(
            messages=[],
            mock_context={"audio_sha256": media.sha256(audio), "mime": mime, "language_hint": language_hint},
        )
        return str(handler(req))
    return MOCK_TRANSCRIPT


_mock_images: dict[str, bytes] = {}


def remember_mock_image(data: bytes) -> str:
    """Store a mock image so `edit_image` can continue from it (the mock stand-in for a stored response id)."""
    rid = f"mock-img-{media.sha256(data)[:16]}"
    _mock_images[rid] = data
    return rid


def recall_mock_image(response_id: str) -> bytes | None:
    return _mock_images.get(response_id)
