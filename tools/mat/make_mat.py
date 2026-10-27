"""Mat artefacts: the plain-paper A4 mat PDF (vector markers, 50.0 mm check ruler) and the web mat layouts (JSON).

uv run python -m tools.mat.make_mat --pdf var/partsmith-mat-a4.pdf --web
"""

from __future__ import annotations

import argparse
import io
import json
from pathlib import Path

from reportlab.lib.units import mm
from reportlab.pdfgen import canvas as rl_canvas

from services.metrology.mats import all_mats, get_mat, layout_json, marker_bits

REPO_ROOT = Path(__file__).resolve().parents[2]
WEB_MATS_DIR = REPO_ROOT / "apps" / "web" / "public" / "mats"
A4_MM = (210.0, 297.0)
RULER_MM = 50.0


def _draw_marker(
    c: rl_canvas.Canvas, marker_id: int, x_mm: float, y_mm: float, size_mm: float, page_h_mm: float
) -> None:
    """Black cells as merged horizontal runs (fewer seams in the printout). (x, y) = top-left on the page, mm."""
    bits = marker_bits(marker_id)
    n = bits.shape[0]
    cell = size_mm / n
    for r in range(n):
        col = 0
        while col < n:
            if bits[r, col] == 0:
                start = col
                while col < n and bits[r, col] == 0:
                    col += 1
                x0 = x_mm + start * cell
                y_top = y_mm + r * cell
                c.rect(x0 * mm, (page_h_mm - y_top - cell) * mm, (col - start) * cell * mm, cell * mm, stroke=0, fill=1)
            else:
                col += 1


def draw_ruler(c: rl_canvas.Canvas, x_mm: float, y_mm: float, length_mm: float, page_h_mm: float) -> None:
    """A check ruler: baseline with 1 mm ticks (5/10 mm longer), labelled every 10 mm. (x, y) = left end of the baseline."""
    yb = (page_h_mm - y_mm) * mm
    c.setLineWidth(0.15 * mm)
    c.line(x_mm * mm, yb, (x_mm + length_mm) * mm, yb)
    c.setFont("Helvetica", 6)
    for i in range(round(length_mm) + 1):
        t = 3.0 if i % 10 == 0 else 2.0 if i % 5 == 0 else 1.2
        c.line((x_mm + i) * mm, yb, (x_mm + i) * mm, yb + t * mm)
        if i % 10 == 0:
            c.drawCentredString((x_mm + i) * mm, yb - 2.8 * mm, str(i))


def mat_pdf(mat_id: str = "paper-a4") -> bytes:
    """A4 PDF of a mat at 1:1 with a 50.0 mm check ruler and short instructions."""
    mat = get_mat(mat_id)
    pw, ph = A4_MM
    ox, oy = mat.page_offset_mm
    if mat.width_mm + ox > pw or mat.height_mm + oy > ph - 30:
        raise ValueError(f"mat {mat_id} does not fit an A4 page with the footer")
    buf = io.BytesIO()
    c = rl_canvas.Canvas(buf, pagesize=(pw * mm, ph * mm))
    c.setTitle(f"PartSmith mat {mat_id}")
    c.setAuthor("PartSmith")
    c.setFillGray(0)
    for mk in mat.markers:
        _draw_marker(c, mk.id, ox + mk.x_mm, oy + mk.y_mm, mat.marker_size_mm, ph)
    # Faint corner ticks outside the stage show where the part goes without putting lines on the stage itself.
    c.setStrokeGray(0.75)
    c.setLineWidth(0.2 * mm)
    st = mat.stage
    for x, y, dx, dy in (
        (st.x_mm, st.y_mm, 1, 1),
        (st.x2_mm, st.y_mm, -1, 1),
        (st.x2_mm, st.y2_mm, -1, -1),
        (st.x_mm, st.y2_mm, 1, -1),
    ):
        px, py = ox + x - dx * 1.5, oy + y - dy * 1.5
        c.line(px * mm, (ph - py) * mm, (px + dx * 4) * mm, (ph - py) * mm)
        c.line(px * mm, (ph - py) * mm, px * mm, (ph - py - dy * 4) * mm)
    c.setStrokeGray(0)
    foot = oy + mat.height_mm + 8.0
    draw_ruler(c, 15.0, foot + 6.0, RULER_MM, ph)
    c.setFont("Helvetica", 6.5)
    c.drawString(15.0 * mm, (ph - foot - 12.0) * mm, f"{RULER_MM:.1f} mm check ruler")
    c.setFont("Helvetica-Bold", 9)
    tx = 75.0
    c.drawString(tx * mm, (ph - foot) * mm, f"PartSmith mat · {mat.mat_id}")
    c.setFont("Helvetica", 7.5)
    ids = mat.ids
    lines = [
        "Print at 100 % / Actual size — turn off 'fit to page'. Plain paper is fine.",
        f"Check: the ruler must measure {RULER_MM:.1f} mm. If it doesn't, enter what you measure in the app.",
        "Lay the part flat inside the corner ticks and photograph from straight above, all markers in view.",
        f"Markers {ids[0]}–{ids[-1]} ({mat.dictionary}), {mat.marker_size_mm:.0f} mm.",
    ]
    for i, line in enumerate(lines):
        c.drawString(tx * mm, (ph - foot - 5.0 - 4.2 * i) * mm, line)
    c.showPage()
    c.save()
    return buf.getvalue()


def write_web_layouts(out_dir: Path = WEB_MATS_DIR) -> list[Path]:
    """`<mat_id>.json` (MatLayout) for every mat plus `index.json` (list of all layouts' summaries)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    index = []
    for m in all_mats():
        lay = layout_json(m.mat_id)
        p = out_dir / f"{m.mat_id}.json"
        p.write_text(json.dumps(lay, separators=(",", ":")) + "\n")
        written.append(p)
        index.append(
            {
                "mat_id": m.mat_id,
                "kind": m.kind.value,
                "title": m.title,
                "width_mm": m.width_mm,
                "height_mm": m.height_mm,
                "stage": lay["stage"],
                "min_screen_mm": lay["min_screen_mm"],
                "url": f"/mats/{m.mat_id}.json",
            }
        )
    p = out_dir / "index.json"
    p.write_text(json.dumps(index, indent=2) + "\n")
    written.append(p)
    return written


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pdf", type=Path, help="write the plain-paper mat PDF here")
    ap.add_argument("--mat", default="paper-a4", help="mat id for --pdf (default paper-a4)")
    ap.add_argument("--web", action="store_true", help="write apps/web/public/mats/*.json")
    ap.add_argument("--web-dir", type=Path, default=WEB_MATS_DIR, help=argparse.SUPPRESS)
    args = ap.parse_args(argv)
    if not args.pdf and not args.web:
        ap.error("nothing to do: pass --pdf and/or --web")
    if args.pdf:
        args.pdf.parent.mkdir(parents=True, exist_ok=True)
        args.pdf.write_bytes(mat_pdf(args.mat))
        print(f"wrote {args.pdf}")
    if args.web:
        for p in write_web_layouts(args.web_dir):
            print(f"wrote {p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
