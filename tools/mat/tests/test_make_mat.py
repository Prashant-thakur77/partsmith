import json
import re
from pathlib import Path

import pytest

from services.metrology.mats import all_mats, layout_json
from services.metrology.testing import rounded_rect_poly
from tools.mat.make_mat import main, mat_pdf, write_web_layouts
from tools.mat.template_pdf import template_pdf


def _pages(pdf: bytes) -> int:
    return len(re.findall(rb"/Type\s*/Page[^s]", pdf))


def test_mat_pdf() -> None:
    pdf = mat_pdf("paper-a4")
    assert pdf.startswith(b"%PDF") and _pages(pdf) == 1
    assert b"595.2756" in pdf  # A4 width in points (210 mm)
    with pytest.raises(ValueError):
        mat_pdf("screen-l")  # wider than A4


def test_web_layouts(tmp_path: Path) -> None:
    files = write_web_layouts(tmp_path)
    assert {f.name for f in files} == {f"{m.mat_id}.json" for m in all_mats()} | {"index.json"}
    for m in all_mats():
        assert json.loads((tmp_path / f"{m.mat_id}.json").read_text()) == layout_json(m.mat_id)
    idx = json.loads((tmp_path / "index.json").read_text())
    assert idx[0]["url"] == "/mats/screen-s.json"


def test_cli(tmp_path: Path) -> None:
    out = tmp_path / "mat.pdf"
    assert main(["--pdf", str(out), "--web", "--web-dir", str(tmp_path / "web")]) == 0
    assert out.read_bytes().startswith(b"%PDF") and (tmp_path / "web" / "index.json").exists()
    with pytest.raises(SystemExit):
        main([])


def test_template_single_page_and_tiled() -> None:
    small = rounded_rect_poly(0, 0, 40, 20, 3).tolist()
    pdf = template_pdf(
        small,
        [{"center_mm": [8, 0], "diameter_mm": 6}],
        [{"label": "40.00 mm", "from_mm": [-20, -15], "to_mm": [20, -15], "value_mm": 40}],
        "Latch",
        ["synthetic test part"],
    )
    assert pdf.startswith(b"%PDF") and _pages(pdf) == 1
    big = rounded_rect_poly(0, 0, 300, 240, 10).tolist()
    assert _pages(template_pdf(big, [], [], "Big panel", None)) == 4  # 2 × 2 tiles
    with pytest.raises(ValueError):
        template_pdf([[0, 0], [1, 1]], [], [], "x", None)
