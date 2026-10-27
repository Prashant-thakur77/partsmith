"""Overlay drawing shared by the measurement and fit-check images: calm colours, anti-aliased lines, pill labels."""

from __future__ import annotations

import io
import math
from dataclasses import dataclass, field

import cv2
import numpy as np
from numpy.typing import NDArray
from PIL import Image, ImageDraw, ImageFont

F64 = NDArray[np.float64]
U8 = NDArray[np.uint8]
BGR = tuple[int, int, int]

TEAL: BGR = (143, 157, 42)  # mask tint  #2A9D8F
INK: BGR = (95, 58, 31)  # dimension lines  #1F3A5F
MARKER: BGR = (68, 125, 58)  # detected markers  #3A7D44
AGREE: BGR = (91, 158, 46)  # fit check agreement  #2E9E5B
AMBER: BGR = (59, 162, 233)  # #E9A23B
RED: BGR = (91, 73, 209)  # #D1495B
PAPER: BGR = (250, 248, 246)


_FONT_CANDIDATES = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/TTF/DejaVuSans.ttf",
    "/Library/Fonts/Arial.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "C:/Windows/Fonts/arial.ttf",
    "DejaVuSans.ttf",
)


def _font(size: int) -> tuple[ImageFont.FreeTypeFont | ImageFont.ImageFont, bool]:
    """A scalable font with tabular digits and the Ø glyph if the system has one; else Pillow's default (no Ø)."""
    for path in _FONT_CANDIDATES:
        try:
            return ImageFont.truetype(path, size), True
        except OSError:
            continue
    try:
        return ImageFont.load_default(size=size), False
    except Exception:  # very old Pillow without the scalable default font
        return ImageFont.load_default(), False


def _rgb(c: BGR) -> tuple[int, int, int]:
    return c[2], c[1], c[0]


@dataclass
class _Label:
    text: str
    at: tuple[float, float]
    color: BGR
    bg: BGR


@dataclass
class Canvas:
    """A downscaled copy of the photo to draw on. All coordinates passed in are ORIGINAL image pixels."""

    image: U8
    scale: float
    origin: tuple[int, int] = (0, 0)  # top-left of the crop, original px
    labels: list[_Label] = field(default_factory=list)

    @classmethod
    def from_image(cls, img: U8, max_side: int = 1600, crop: tuple[float, float, float, float] | None = None) -> Canvas:
        """`crop` = (x0, y0, x1, y1) in original px; clipped to the image."""
        H, W = img.shape[:2]
        x0, y0, x1, y1 = 0, 0, W, H
        if crop is not None:
            x0, y0 = max(int(crop[0]), 0), max(int(crop[1]), 0)
            x1, y1 = min(math.ceil(crop[2]), W), min(math.ceil(crop[3]), H)
            if x1 - x0 < 16 or y1 - y0 < 16:
                x0, y0, x1, y1 = 0, 0, W, H
        im: U8 = img[y0:y1, x0:x1]
        h, w = im.shape[:2]
        # Downscale big photos; enlarge small crops (up to 2.5×) so lines and labels stay legible.
        s = min(max_side / max(h, w), max(1.0, min(2.5, 1000 / max(h, w))))
        if im.ndim != 3:
            im = np.asarray(cv2.cvtColor(im, cv2.COLOR_GRAY2BGR), dtype=np.uint8)
        if s != 1.0:
            interp = cv2.INTER_AREA if s < 1.0 else cv2.INTER_CUBIC
            im = np.asarray(cv2.resize(im, (round(w * s), round(h * s)), interpolation=interp), dtype=np.uint8)
        return cls(np.ascontiguousarray(im.copy()), s, (x0, y0))

    def top_label(self, text: str, color: BGR = INK) -> None:
        """A label centred near the top edge of the canvas."""
        h, w = self.image.shape[:2]
        self.labels.append(_Label(text, (w / 2, max(18.0, h * 0.04)), color, PAPER))

    @property
    def lw(self) -> int:
        return max(1, int(max(self.image.shape[:2]) / 700 + 0.5))

    def _p(self, pts: F64) -> NDArray[np.int32]:
        p = (np.asarray(pts, dtype=np.float64).reshape(-1, 2) - self.origin + 0.5) * self.scale - 0.5
        return np.round(p * 16).astype(np.int32)

    def tint(self, mask: NDArray[np.bool_], color: BGR = TEAL, alpha: float = 0.35) -> None:
        h, w = self.image.shape[:2]
        x0, y0 = self.origin
        sub = mask[y0 : y0 + round(h / self.scale), x0 : x0 + round(w / self.scale)]
        m = cv2.resize(sub.astype(np.float32), (w, h), interpolation=cv2.INTER_AREA)[..., None] * alpha
        self.image = np.clip(self.image * (1 - m) + np.array(color, np.float32) * m, 0, 255).astype(np.uint8)

    def poly(self, pts: F64, color: BGR, closed: bool = True, width: int | None = None) -> None:
        cv2.polylines(self.image, [self._p(pts)], closed, color, width or self.lw, cv2.LINE_AA, shift=4)

    def fill(self, pts: F64, color: BGR, alpha: float = 0.5) -> None:
        layer = self.image.copy()
        cv2.fillPoly(layer, [self._p(pts)], color, cv2.LINE_AA, shift=4)
        self.image = np.asarray(cv2.addWeighted(layer, alpha, self.image, 1 - alpha, 0), dtype=np.uint8)

    def line(self, a: F64, b: F64, color: BGR, width: int | None = None) -> None:
        self.poly(np.array([a, b]), color, closed=False, width=width)

    def dot(self, p: F64, color: BGR, r_px: float | None = None) -> None:
        c = self._p(np.asarray(p))[0]
        r = round((r_px or 2.5 * self.lw) * 16)
        cv2.circle(self.image, (int(c[0]), int(c[1])), r, color, -1, cv2.LINE_AA, shift=4)

    def label(self, text: str, at: F64, color: BGR = INK, bg: BGR = PAPER) -> None:
        p = (np.asarray(at, dtype=np.float64).reshape(2) - self.origin + 0.5) * self.scale - 0.5
        self.labels.append(_Label(text, (float(p[0]), float(p[1])), color, bg))

    def dimension(self, a: F64, b: F64, text: str, offset_dir: F64, offset_px: float, color: BGR = INK) -> None:
        """Dimension line between a and b (original px), offset sideways by `offset_px` (canvas px) with extension lines."""
        a, b = np.asarray(a, float), np.asarray(b, float)
        d = np.asarray(offset_dir, float)
        d = d / max(np.linalg.norm(d), 1e-9)
        off = d * offset_px / self.scale
        a2, b2 = a + off, b + off
        self.line(a + off * 0.15, a2 + off * 0.15, color, 1)
        self.line(b + off * 0.15, b2 + off * 0.15, color, 1)
        self.line(a2, b2, color)
        u = (b2 - a2) / max(np.linalg.norm(b2 - a2), 1e-9)
        n = np.array([-u[1], u[0]])
        tick = 6.0 / self.scale
        for p in (a2, b2):
            self.line(p - (u + n) * tick * 0.7, p + (u + n) * tick * 0.7, color)
        self.label(text, (a2 + b2) / 2, color)

    def png(self) -> bytes:
        rgb = Image.fromarray(cv2.cvtColor(self.image, cv2.COLOR_BGR2RGB))
        if self.labels:
            draw = ImageDraw.Draw(rgb, "RGBA")
            size = max(12, round(max(rgb.size) / 70))
            font, full = _font(size)
            pad = max(3, size // 4)
            for lb in self.labels:
                text = lb.text if full else lb.text.replace("Ø", "D ").replace("×", "x")
                left, top, right, bottom = draw.textbbox((0, 0), text, font=font)
                tw, th = right - left, bottom - top
                x = lb.at[0] - tw / 2
                y = lb.at[1] - th / 2
                x = min(max(x, pad), rgb.size[0] - tw - pad)
                y = min(max(y, pad), rgb.size[1] - th - pad)
                draw.rounded_rectangle(
                    (x - pad, y - pad, x + tw + pad, y + th + pad),
                    radius=pad + 2,
                    fill=(*_rgb(lb.bg), 235),
                    outline=(*_rgb(lb.color), 255),
                    width=1,
                )
                draw.text((x - left, y - top), text, font=font, fill=(*_rgb(lb.color), 255))
        buf = io.BytesIO()
        rgb.save(buf, format="PNG", optimize=True)
        return buf.getvalue()


def banner(img: U8, text: str, color: BGR = RED, max_side: int = 1600) -> bytes:
    """The photo with one message — used when nothing could be measured."""
    c = Canvas.from_image(img, max_side)
    c.top_label(text, color)
    return c.png()


def circle_pts(cx: float, cy: float, r: float, n: int = 96) -> F64:
    a = np.linspace(0, 2 * math.pi, n, endpoint=False)
    return np.asarray(np.c_[cx + r * np.cos(a), cy + r * np.sin(a)], dtype=np.float64)
