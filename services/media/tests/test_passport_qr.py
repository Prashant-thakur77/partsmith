"""Passport QR codes (reportlab's encoder) and the repair card's passport block (no network)."""

from __future__ import annotations

import io
import re

import numpy as np
from PIL import Image

from services.media import passport_qr, repair_card

URL = "https://partsmith.example/p/7KQ3MZ"


def test_png_decodes_back_to_the_url() -> None:
    import cv2

    img = np.array(Image.open(io.BytesIO(passport_qr.png(URL, module_px=8))).convert("L"))
    text, _, _ = cv2.QRCodeDetector().detectAndDecode(img)
    assert text == URL


def test_svg_has_quiet_zone_title_and_one_path() -> None:
    m = passport_qr.matrix(URL)
    svg = passport_qr.svg(URL, title='Passport <7KQ3MZ> & "x"')
    n = len(m) + 2 * passport_qr.QUIET
    assert f'viewBox="0 0 {n} {n}"' in svg and svg.count("<path") == 1
    assert "<title>Passport &lt;7KQ3MZ&gt; &amp; &quot;x&quot;</title>" in svg
    assert m[0][:7] == [True] * 7  # a finder pattern in the corner


def _card(passport_id: str = "", passport_url: str = "") -> repair_card.RepairCardData:
    return repair_card.RepairCardData(title="Cupboard latch", family="latch", job_id="j_1", passport_id=passport_id,
                                      passport_url=passport_url)  # fmt: skip


def test_repair_card_carries_the_qr_the_id_and_the_reprint_line() -> None:
    plain = repair_card.make_repair_card(_card()).decode("latin-1")
    pdf = repair_card.make_repair_card(_card(passport_id="7KQ3MZ", passport_url=URL)).decode("latin-1")
    assert "7KQ3MZ" in pdf and URL in pdf and "Repair passport" in pdf
    assert "Broke again? Scan to reprint" in pdf and "clearance comes with it." in pdf
    assert "Broke again" not in plain and "7KQ3MZ" not in plain
    # the QR is drawn as filled rectangles, one per dark run of modules
    runs = sum(len(passport_qr._runs(row)) for row in passport_qr.matrix(URL))
    rects = len(re.findall(r" re f\b", pdf)) - len(re.findall(r" re f\b", plain))
    assert runs > 50 and rects >= runs


def test_long_card_moves_the_passport_to_a_second_page() -> None:
    card = _card(passport_id="7KQ3MZ", passport_url=URL)
    card.notes = [f"note {i}" for i in range(6)]
    card.key_dims = [repair_card.KeyDim(f"dim {i}", 1.0 + i) for i in range(40)]
    pdf = repair_card.make_repair_card(card).decode("latin-1")
    assert pdf.count("/Type /Page\n") + pdf.count("/Type /Page ") >= 2 or "/Count 2" in pdf
    assert "Broke again? Scan to reprint" in pdf
