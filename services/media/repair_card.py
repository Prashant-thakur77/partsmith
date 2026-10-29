"""Printable repair card (A5 or A4 PDF): what the part is, its key dimensions, how it was verified, how to print it.

Every number on the card is passed in by the caller (measurements, `Verification` from the verifier). Missing values
print as "not measured" / "not verified" — the card never fills gaps. The Verified badge appears only when
`verification.verified` is True, which only the deterministic verifier can set.

With a passport id the card ends with a "Repair passport" block: a QR code to `/p/{id}` (reportlab's QR encoder, see
`passport_qr.py`), the id in text and how to use it, so a part that breaks again is reprinted from one scan.
"""

from __future__ import annotations

import io
from collections.abc import Sequence
from dataclasses import dataclass, field

from partsmith_schemas.verification import Verification
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, A5
from reportlab.lib.units import mm
from reportlab.pdfgen.canvas import Canvas

from services.media.passport_qr import draw as qr_passport

PAGE_SIZES = {"A5": A5, "A4": A4}


@dataclass
class KeyDim:
    label: str
    value_mm: float | None
    source: str = "measured"  # measured | user_stated | inferred
    sigma_mm: float | None = None


@dataclass
class PrintSettings:
    """Suggested slicer settings (recommendations, not measurements)."""

    material: str = "PLA"
    nozzle_mm: float = 0.4
    layer_height_mm: float = 0.2
    walls: int = 4
    infill_percent: int = 40
    supports: bool | None = None  # None = not analysed
    orientation: str = ""


@dataclass
class RepairCardData:
    title: str
    family: str
    slug: str = ""
    url_text: str = ""  # plain URL text (no QR code)
    key_dims: Sequence[KeyDim] = field(default_factory=list)
    verification: Verification | None = None
    print_settings: PrintSettings | None = None
    origin: str = "real"  # DataOrigin value; synthetic/replay are labelled on the card
    provider_mode: str = "live"  # live | mock | replay | mixed
    notes: Sequence[str] = field(default_factory=list)
    job_id: str = ""
    passport_id: str = ""  # repair passport id (services/registry/passport.py); empty = no passport block
    passport_url: str = ""  # absolute URL of /p/{id} the QR code encodes


PASSPORT_LINE = "Broke again? Scan to reprint \u2014 your printer's clearance comes with it."


def _fmt_mm(v: float | None, digits: int = 2) -> str:
    return "not measured" if v is None else f"{v:.{digits}f} mm"


def verification_lines(v: Verification | None) -> tuple[str, list[str]]:
    """(badge, detail lines) — derived only from the Verification record."""
    if v is None:
        return "NOT VERIFIED", ["No verification record."]
    badge = {"verified": "VERIFIED", "best_effort": "BEST EFFORT", "failed": "FAILED"}[v.status]
    if v.status == "verified" and not v.verified:
        badge = "NOT VERIFIED"
    lines = [
        f"Max error: {_fmt_mm(v.max_error_mm)}  (pass: <= {v.thresholds.hausdorff_mm:g} mm, IoU >= {v.thresholds.iou:g})"
    ]
    for view in v.views:
        lines.append(
            f"{view.view}: IoU {view.iou:.3f}, Hausdorff {view.hausdorff_mm:.2f} mm, mean {view.mean_mm:.2f} mm"
        )
    if v.tests:
        passed = sum(1 for t in v.tests if t.passed)
        lines.append(f"Part tests: {passed}/{len(v.tests)} passed")
    blocking = [veto for veto in v.vetoes if veto.severity == "blocking"]
    if blocking:
        lines.append(f"Judge vetoes: {len(blocking)} blocking")
    lines += [f"- {r}" for r in v.reasons[:3]]
    return badge, lines


def make_repair_card(card: RepairCardData, page: str = "A5") -> bytes:
    """Render the card to PDF bytes. Text is stored uncompressed so it stays greppable and accessible."""
    size = PAGE_SIZES[page.upper()]
    width, height = size
    buf = io.BytesIO()
    c = Canvas(buf, pagesize=size, pageCompression=0, invariant=1)
    c.setTitle(f"Repair card - {card.title}")
    margin = 12 * mm
    scale = width / A5[0]
    y = height - margin

    def text(s: str, size_pt: float = 9, bold: bool = False, color: colors.Color = colors.black, dy: float = 0) -> None:
        nonlocal y
        c.setFont("Helvetica-Bold" if bold else "Helvetica", size_pt * scale)
        c.setFillColor(color)
        c.drawString(margin, y, s)
        y -= (dy or size_pt * 1.45) * scale

    labels = []
    if card.origin != "real":
        labels.append(card.origin.upper())
    if card.provider_mode != "live":
        labels.append(f"{card.provider_mode.upper()} MODELS")
    if labels:
        c.setFillColor(colors.HexColor("#b41414"))
        c.rect(0, height - 7 * mm * scale, width, 7 * mm * scale, fill=1, stroke=0)
        c.setFillColor(colors.white)
        c.setFont("Helvetica-Bold", 8 * scale)
        c.drawString(margin, height - 5 * mm * scale, " · ".join(labels) + " — not a real-world measurement")
        y -= 6 * mm * scale

    text("PartSmith repair card", 8, color=colors.grey)
    text(card.title or "Untitled part", 16, bold=True)
    text(f"Family: {card.family}" + (f"    Part: {card.slug}" if card.slug else ""), 9)
    if card.url_text:
        text(card.url_text, 8, color=colors.HexColor("#1d4ed8"))
    y -= 3 * mm

    badge, lines = verification_lines(card.verification)
    badge_color = colors.HexColor("#15803d") if badge == "VERIFIED" else colors.HexColor("#b45309")
    c.setFillColor(badge_color)
    c.roundRect(margin, y - 2 * mm, 40 * mm * scale, 7 * mm * scale, 1.5 * mm, fill=1, stroke=0)
    c.setFillColor(colors.white)
    c.setFont("Helvetica-Bold", 9 * scale)
    c.drawString(margin + 2 * mm, y, badge)
    y -= 8 * mm * scale
    for line in lines:
        text(line, 8)
    y -= 2 * mm

    text("Key dimensions", 10, bold=True)
    if not card.key_dims:
        text("none recorded", 8, color=colors.grey)
    for d in card.key_dims:
        sigma = f" ± {d.sigma_mm:.2f}" if d.sigma_mm is not None and d.value_mm is not None else ""
        text(f"{d.label}: {_fmt_mm(d.value_mm)}{sigma}   [{d.source.replace('_', ' ')}]", 8.5)
    y -= 2 * mm

    text("Print settings (suggested)", 10, bold=True)
    ps = card.print_settings
    if ps is None:
        text("not specified", 8, color=colors.grey)
    else:
        supports = "not analysed" if ps.supports is None else ("yes" if ps.supports else "no")
        text(f"{ps.material}, {ps.nozzle_mm:g} mm nozzle, {ps.layer_height_mm:g} mm layers", 8.5)
        text(f"{ps.walls} walls, {ps.infill_percent}% infill, supports: {supports}", 8.5)
        if ps.orientation:
            text(f"Orientation: {ps.orientation}", 8.5)
    if card.notes:
        y -= 2 * mm
        text("Notes", 10, bold=True)
        for n in card.notes[:6]:
            text(f"- {n}", 8)

    def footer() -> None:
        c.setFont("Helvetica", 7 * scale)
        c.setFillColor(colors.grey)
        line = "All lengths in millimetres. Verified status is decided by PartSmith's deterministic verifier."
        if card.job_id:
            line += f"  Job {card.job_id}"
        c.drawString(margin, margin / 2, line)

    if card.passport_id:
        qr_size = 26 * mm * scale
        block = qr_size + 12 * mm * scale
        if y - block < margin:  # no room left on this page: the passport gets the next one
            footer()
            c.showPage()
            y = height - margin
        y -= 3 * mm
        text("Repair passport", 10, bold=True)
        top = y + 2 * mm * scale
        qr_passport(c, card.passport_url or card.passport_id, margin, top - qr_size, qr_size)
        x = margin + qr_size + 5 * mm * scale
        c.setFillColor(colors.black)
        c.setFont("Courier-Bold", 18 * scale)
        c.drawString(x, top - 8 * mm * scale, card.passport_id)
        c.setFont("Helvetica", 8.5 * scale)
        c.drawString(x, top - 14 * mm * scale, PASSPORT_LINE)
        if card.passport_url:
            c.setFillColor(colors.HexColor("#1d4ed8"))
            c.setFont("Helvetica", 8 * scale)
            c.drawString(x, top - 19 * mm * scale, card.passport_url)
        c.setFillColor(colors.grey)
        c.setFont("Helvetica", 7 * scale)
        c.drawString(x, top - 24 * mm * scale, "Or type the id on the PartSmith site at /p/<id>. No new photos needed.")
    footer()
    c.showPage()
    c.save()
    return buf.getvalue()
