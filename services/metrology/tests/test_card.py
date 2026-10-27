import pytest

from services.metrology import card


def test_exact_card_match() -> None:
    s = 5.0
    cal = card.card_px_per_mm(card.ID1_W_MM * s, card.ID1_H_MM * s, device_pixel_ratio=2.0)
    assert cal.ok and not cal.warnings
    assert cal.css_px_per_mm == pytest.approx(s, rel=1e-12)
    assert cal.device_px_per_mm == pytest.approx(10.0)
    assert cal.aspect_error == pytest.approx(0.0, abs=1e-12)
    # portrait rectangle gives the same answer
    assert card.card_px_per_mm(card.ID1_H_MM * s, card.ID1_W_MM * s).css_px_per_mm == pytest.approx(s)
    # ~0.25 mm per edge over an 86 mm card: a few tenths of a percent
    assert 0.001 < cal.sigma_rel < 0.006
    assert cal.sigma_mm(50.0) == pytest.approx(50.0 * cal.sigma_rel)


def test_aspect_and_bounds_warnings() -> None:
    warn = card.card_px_per_mm(85.6 * 5, 53.98 * 5 * 0.975)
    assert warn.ok and warn.warnings and "short side" in warn.warnings[0]
    bad = card.card_px_per_mm(85.6 * 5, 53.98 * 5 * 0.9)
    assert not bad.ok
    tiny = card.card_px_per_mm(85.6, 53.98)  # 1 px/mm: browser zoomed out
    assert not tiny.ok and "zoom" in tiny.warnings[0]
    with pytest.raises(ValueError):
        card.card_px_per_mm(0, 10)


def test_sizes_and_ruler() -> None:
    assert card.mat_size_css(210, 130, 4.0) == (840, 520)
    assert card.viewport_mm(1440, 900, 5.0) == (288, 180)
    assert card.ruler_scale_correction(49.5) == pytest.approx(0.99)
    with pytest.raises(ValueError, match="100 %"):
        card.ruler_scale_correction(45.0)
