"""1:1 paper template of a part outline: outline, holes with centre crosses, dimension lines and a 50 mm scale bar.

Parts larger than one A4 page are tiled across several pages with a 10 mm overlap and shared alignment crosses.
Coordinates are the PART frame (mm, Y up).
"""

from __future__ import annotations

import io
import math
from collections.abc import Sequence
from typing import Any

from reportlab.lib.units import mm
from reportlab.pdfgen import canvas as rl_canvas

from .make_mat import A4_MM, RULER_MM, draw_ruler

MARGIN_MM = 12.0
HEADER_MM = 26.0
OVERLAP_MM = 10.0
PAD_MM = 8.0


def _bounds(
    outline: Sequence[Sequence[float]], holes: Sequence[dict[str, Any]], dims: Sequence[dict[str, Any]]
) -> tuple[float, float, float, float]:
    xs = [float(p[0]) for p in outline]
    ys = [float(p[1]) for p in outline]
    for h in holes:
        r = float(h["diameter_mm"]) / 2
        xs += [h["center_mm"][0] - r, h["center_mm"][0] + r]
        ys += [h["center_mm"][1] - r, h["center_mm"][1] + r]
    for d in dims:
        for k in ("from_mm", "to_mm"):
            xs.append(float(d[k][0]))
            ys.append(float(d[k][1]))
    return min(xs) - PAD_MM, min(ys) - PAD_MM, max(xs) + PAD_MM, max(ys) + PAD_MM


def template_pdf(
    outline_mm: Sequence[Sequence[float]],
    holes: Sequence[dict[str, Any]] | None = None,
    dims: Sequence[dict[str, Any]] | None = None,
    title: str = "PartSmith template",
    notes: Sequence[str] | str | None = None,
) -> bytes:
    """Render the template. `holes`: `{"center_mm": [x, y], "diameter_mm": d}`; `dims`: `{"label", "from_mm", "to_mm",
    "value_mm"}` (dimension line endpoints, drawn as given)."""
    if len(outline_mm) < 3:
        raise ValueError("outline needs at least three points")
    holes = list(holes or [])
    dims = list(dims or [])
    note_lines = [notes] if isinstance(notes, str) else list(notes or [])
    pw, ph = A4_MM
    area_w = pw - 2 * MARGIN_MM
    area_h = ph - 2 * MARGIN_MM - HEADER_MM
    x0, y0, x1, y1 = _bounds(outline_mm, holes, dims)
    bw, bh = x1 - x0, y1 - y0
    step_w, step_h = area_w - OVERLAP_MM, area_h - OVERLAP_MM
    nx = 1 if bw <= area_w else math.ceil((bw - OVERLAP_MM) / step_w)
    ny = 1 if bh <= area_h else math.ceil((bh - OVERLAP_MM) / step_h)
    tiled = nx * ny > 1
    if not tiled:  # centre on the page
        x0 -= (area_w - bw) / 2
        y0 -= (area_h - bh) / 2

    buf = io.BytesIO()
    c = rl_canvas.Canvas(buf, pagesize=(pw * mm, ph * mm))
    c.setTitle(title)
    c.setAuthor("PartSmith")
    for row in range(ny):  # row 0 = top of the part
        for col in range(nx):
            wx0 = x0 + col * step_w
            wy1 = y1 - row * step_h if tiled else y0 + area_h
            wy0 = wy1 - area_h

            def P(x: float, y: float, wx0: float = wx0, wy0: float = wy0) -> tuple[float, float]:
                return (MARGIN_MM + (x - wx0)) * mm, (MARGIN_MM + (y - wy0)) * mm

            # header
            c.setFillGray(0)
            c.setFont("Helvetica-Bold", 11)
            c.drawString(MARGIN_MM * mm, (ph - MARGIN_MM - 5) * mm, title[:90])
            c.setFont("Helvetica", 7.5)
            sub = "1:1 template — print at 100 % / Actual size."
            if tiled:
                sub += f" Tile {row + 1}.{col + 1} of {ny}×{nx}; overlap {OVERLAP_MM:.0f} mm — align the + crosses."
            c.drawString(MARGIN_MM * mm, (ph - MARGIN_MM - 10) * mm, sub)
            for i, line in enumerate(note_lines[:2] if (row, col) == (0, 0) else []):
                c.drawString(MARGIN_MM * mm, (ph - MARGIN_MM - 14.5 - 4 * i) * mm, line[:120])
            draw_ruler(c, pw - MARGIN_MM - RULER_MM - 2, MARGIN_MM + 9, RULER_MM, ph)
            c.drawRightString((pw - MARGIN_MM - 2) * mm, (ph - MARGIN_MM - 13.5) * mm, f"{RULER_MM:.0f} mm scale bar")

            c.saveState()
            path = c.beginPath()
            path.rect(MARGIN_MM * mm, MARGIN_MM * mm, area_w * mm, area_h * mm)
            c.clipPath(path, stroke=0, fill=0)
            # outline
            c.setStrokeGray(0)
            c.setLineWidth(0.3 * mm)
            p = c.beginPath()
            p.moveTo(*P(*outline_mm[0][:2]))
            for q in outline_mm[1:]:
                p.lineTo(*P(*q[:2]))
            p.close()
            c.drawPath(p, stroke=1, fill=0)
            # holes with centre crosses
            c.setLineWidth(0.2 * mm)
            for h in holes:
                hx, hy = float(h["center_mm"][0]), float(h["center_mm"][1])
                r = float(h["diameter_mm"]) / 2
                cx, cy = P(hx, hy)
                c.circle(cx, cy, r * mm, stroke=1, fill=0)
                arm = max(r + 2.0, 3.0)
                c.line(*P(hx - arm, hy), *P(hx + arm, hy))
                c.line(*P(hx, hy - arm), *P(hx, hy + arm))
                c.setFont("Helvetica", 6.5)
                c.drawString(*P(hx + r + 1.0, hy + r + 0.5), f"Ø{float(h['diameter_mm']):.2f}")
            # dimension lines
            c.setStrokeColorRGB(0.12, 0.23, 0.37)
            c.setFillColorRGB(0.12, 0.23, 0.37)
            for d in dims:
                ax, ay = (float(v) for v in d["from_mm"][:2])
                bx, by = (float(v) for v in d["to_mm"][:2])
                c.setLineWidth(0.15 * mm)
                c.line(*P(ax, ay), *P(bx, by))
                L = math.hypot(bx - ax, by - ay) or 1.0
                ux, uy = (bx - ax) / L, (by - ay) / L
                nx_, ny_ = -uy, ux
                for ex, ey in ((ax, ay), (bx, by)):
                    c.line(*P(ex - nx_ * 1.5, ey - ny_ * 1.5), *P(ex + nx_ * 1.5, ey + ny_ * 1.5))
                c.setFont("Helvetica", 7)
                mx, my = P((ax + bx) / 2 + nx_ * 1.2, (ay + by) / 2 + ny_ * 1.2)
                c.saveState()
                c.translate(mx, my)
                ang = math.degrees(math.atan2(uy, ux))
                if ang > 90 or ang < -90:
                    ang += 180
                c.rotate(ang)
                c.drawCentredString(0, 0, str(d.get("label") or f"{float(d['value_mm']):.2f} mm"))
                c.restoreState()
            c.setStrokeGray(0)
            c.setFillGray(0)
            # alignment crosses on the overlap lines (shared world positions between neighbouring tiles)
            if tiled:
                c.setLineWidth(0.15 * mm)
                xs = [x0 + k * step_w + OVERLAP_MM / 2 for k in range(1, nx)]
                ys = [y1 - k * step_h - OVERLAP_MM / 2 for k in range(1, ny)]
                for gx in xs:
                    for gy in [wy0 + area_h * 0.25, wy0 + area_h * 0.75]:
                        _cross(c, P, gx, gy)
                for gy in ys:
                    for gx in [wx0 + area_w * 0.25, wx0 + area_w * 0.75]:
                        _cross(c, P, gx, gy)
            c.restoreState()
            c.setLineWidth(0.1 * mm)
            c.setStrokeGray(0.7)
            c.rect(MARGIN_MM * mm, MARGIN_MM * mm, area_w * mm, area_h * mm, stroke=1, fill=0)
            c.setStrokeGray(0)
            c.showPage()
    c.save()
    return buf.getvalue()


def _cross(c: rl_canvas.Canvas, P: Any, x: float, y: float) -> None:
    cx, cy = P(x, y)
    c.circle(cx, cy, 2.0 * mm, stroke=1, fill=0)
    c.line(*P(x - 3.5, y), *P(x + 3.5, y))
    c.line(*P(x, y - 3.5), *P(x, y + 3.5))
