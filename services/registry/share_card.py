"""Per-part share card: a 1200×630 PNG for og:image and chat previews.

Thumbnail on the left; title, the code-decided status ("Verified · 0.31 mm" only when the verifier said so, else "Best
effort · …" or "Not verified"), an origin badge (real photo / synthetic / reference object) and printing facts on the
right. Every number comes from the part record.
"""

from __future__ import annotations

import io
from functools import cache
from typing import Any

from partsmith_schemas import PartRecord
from PIL import Image, ImageDraw, ImageFont

from services.common import blobs
from services.registry.store import ROLE_REFERENCE_TAG

W, H = 1200, 630
BG = (246, 246, 243)
INK = (24, 24, 27)
MUTED = (113, 113, 122)
ACCENT = (234, 88, 12)  # signal orange
GREEN = (21, 128, 61)
AMBER = (180, 83, 9)
GREY = (82, 82, 91)
_cache: dict[tuple[Any, ...], str] = {}


@cache
def _font(size: int, bold: bool = False) -> Any:
    names = (
        ("DejaVuSans-Bold.ttf", "LiberationSans-Bold.ttf") if bold else ("DejaVuSans.ttf", "LiberationSans-Regular.ttf")
    )
    for name in names:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default(size=size)


def status_text(part: PartRecord) -> tuple[str, tuple[int, int, int]]:
    v = part.verification
    if v is not None and v.verified and v.status == "verified":
        return (f"Verified · {v.max_error_mm:.2f} mm" if v.max_error_mm is not None else "Verified"), GREEN
    if v is not None and v.status == "best_effort":
        return (f"Best effort · {v.max_error_mm:.2f} mm" if v.max_error_mm is not None else "Best effort"), AMBER
    return "Not verified", GREY


def origin_text(part: PartRecord) -> str:
    if ROLE_REFERENCE_TAG in part.tags:
        return "Reference object"
    names = {"real": "Real photo", "synthetic": "Synthetic test", "reference_object": "Reference object",
             "replay": "Replay"}  # fmt: skip
    origin = str(part.provenance.origin.value)
    return names.get(origin, origin)


def _wrap(draw: ImageDraw.ImageDraw, text: str, font: Any, width: int, max_lines: int) -> list[str]:
    words, lines, cur = text.split(), [], ""
    for w in words:
        trial = f"{cur} {w}".strip()
        if draw.textlength(trial, font=font) <= width or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = lines[-1].rstrip(".,") + "…"
    return lines


def _pill(draw: ImageDraw.ImageDraw, xy: tuple[int, int], text: str, *, fill: Any, fg: Any, outline: Any = None,
          size: int = 30) -> int:  # fmt: skip
    font = _font(size, bold=True)
    tw = int(draw.textlength(text, font=font))
    x, y = xy
    h = size + 26
    draw.rounded_rectangle((x, y, x + tw + 40, y + h), radius=h // 2, fill=fill, outline=outline, width=3)
    draw.text((x + 20, y + h // 2), text, font=font, fill=fg, anchor="lm")
    return x + tw + 40


def render(part: PartRecord, thumbnail_png: bytes | None, *, url_text: str = "") -> bytes:
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    d.rectangle((0, 0, 14, H), fill=ACCENT)
    if thumbnail_png:
        th = Image.open(io.BytesIO(thumbnail_png)).convert("RGBA")
        th.thumbnail((600, 450), Image.Resampling.LANCZOS)
        img.paste(th, (30 + (600 - th.width) // 2, (H - th.height) // 2), th)
    x0, right = 660, W - 50
    d.text((x0, 60), "PartSmith", font=_font(30, bold=True), fill=ACCENT)
    y = 120
    for line in _wrap(d, part.title, _font(52, bold=True), right - x0, 3):
        d.text((x0, y), line, font=_font(52, bold=True), fill=INK)
        y += 64
    y += 22
    status, color = status_text(part)
    _pill(d, (x0, y), status, fill=color, fg=(255, 255, 255))
    y += 76
    _pill(d, (x0, y), origin_text(part), fill=BG, fg=INK, outline=(161, 161, 170), size=26)
    y += 80
    if part.facts is not None:
        f = part.facts
        d.text((x0, y), f"{f.bbox_mm[0]:.0f} × {f.bbox_mm[1]:.0f} × {f.bbox_mm[2]:.0f} mm · {f.mass_g_pla:.1f} g PLA",
               font=_font(28), fill=MUTED)  # fmt: skip
        y += 40
    knobs = sum(1 for p in part.params)
    topo = sum(1 for p in part.params if p.topology)
    shape = f" · {topo} {'changes' if topo == 1 else 'change'} the shape" if topo else ""
    d.text((x0, y), f"{knobs} knobs{shape}", font=_font(28), fill=MUTED)
    if url_text:
        font = _font(24)
        while len(url_text) > 8 and d.textlength(url_text, font=font) > right - x0 + 20:
            url_text = url_text[:-2].rstrip("…") + "…"
        d.text((x0, H - 60), url_text, font=font, fill=MUTED)
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def card_key(part: PartRecord, thumb_key: str | None, url_text: str) -> str:
    """Blob key of the card (rendered once per part state)."""
    v = part.verification
    k = (part.slug, part.version, part.code_sha, part.title, v.status if v else None, v.max_error_mm if v else None,
         thumb_key, url_text, tuple(part.tags))  # fmt: skip
    if k in _cache and blobs.exists(_cache[k]):
        return _cache[k]
    png = render(part, blobs.get(thumb_key) if thumb_key else None, url_text=url_text)
    _cache[k] = blobs.put(png, ".png")
    return _cache[k]
