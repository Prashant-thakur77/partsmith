"""QR codes for repair passports, from reportlab's own QR encoder (no extra dependency): the module matrix, an SVG, a
PNG and a drawing on a reportlab canvas (the repair card)."""

from __future__ import annotations

import io
from typing import Any

QUIET = 4  # modules of white border (the QR standard's quiet zone)
EC_LEVEL = "M"  # ~15 % of the code can be damaged (a scuffed print) and it still scans


def matrix(text: str) -> list[list[bool]]:
    """Rows of dark (True) / light modules, without the quiet zone."""
    from reportlab.graphics.barcode import qrencoder

    qr = qrencoder.QRCode(None, getattr(qrencoder.QRErrorCorrectLevel, EC_LEVEL))
    qr.addData(text)
    qr.make()
    n = qr.getModuleCount()
    return [[bool(qr.isDark(r, c)) for c in range(n)] for r in range(n)]


def _runs(row: list[bool]) -> list[tuple[int, int]]:
    """(start, length) of each run of dark modules in a row."""
    out: list[tuple[int, int]] = []
    c = 0
    while c < len(row):
        if row[c]:
            start = c
            while c < len(row) and row[c]:
                c += 1
            out.append((start, c - start))
        else:
            c += 1
    return out


def svg(text: str, *, module_px: int = 8, title: str = "") -> str:
    m = matrix(text)
    n = len(m) + 2 * QUIET
    path = "".join(f"M{c + QUIET} {r + QUIET}h{ln}v1h-{ln}z" for r, row in enumerate(m) for c, ln in _runs(row))
    label = f"<title>{_esc(title or text)}</title>"
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {n} {n}" width="{n * module_px}" '
        f'height="{n * module_px}" shape-rendering="crispEdges" role="img">{label}'
        f'<rect width="{n}" height="{n}" fill="#fff"/><path d="{path}" fill="#000"/></svg>'
    )


def png(text: str, *, module_px: int = 10) -> bytes:
    from PIL import Image

    m = matrix(text)
    n = len(m) + 2 * QUIET
    img = Image.new("1", (n, n), 1)
    px = img.load()
    assert px is not None
    for r, row in enumerate(m):
        for c, dark in enumerate(row):
            if dark:
                px[c + QUIET, r + QUIET] = 0
    img = img.resize((n * module_px, n * module_px), Image.Resampling.NEAREST)
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def draw(canvas: Any, text: str, x: float, y: float, size: float) -> int:
    """Draw the code (quiet zone included) with its lower-left corner at (x, y), `size` points wide. Returns the
    number of dark runs drawn (each one rectangle)."""
    m = matrix(text)
    n = len(m) + 2 * QUIET
    unit = size / n
    canvas.saveState()
    canvas.setFillColorRGB(1, 1, 1)
    canvas.rect(x, y, size, size, fill=1, stroke=0)
    canvas.setFillColorRGB(0, 0, 0)
    drawn = 0
    for r, row in enumerate(m):
        for c, ln in _runs(row):
            canvas.rect(x + (c + QUIET) * unit, y + size - (r + QUIET + 1) * unit, ln * unit, unit, fill=1, stroke=0)
            drawn += 1
    canvas.restoreState()
    return drawn


def _esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
