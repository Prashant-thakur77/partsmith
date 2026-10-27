"""Screen scale calibration with an ID-1 card (ISO/IEC 7810: 85.60 × 53.98 mm), and the paper-mat 50 mm ruler correction.

The browser shows a rectangle the user drags until it matches a bank/ID card held against the screen. From its size in CSS
pixels we get CSS px per mm, which the screen-mat page uses to draw the mat at 1:1. Device pixels = CSS px × devicePixelRatio.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

ID1_W_MM = 85.60
ID1_H_MM = 53.98

# Plausible CSS px per mm. CSS reference pixel is 1/96 in (3.78 px/mm); real screens with OS scaling land between ~3 and ~7.5.
CSS_PX_PER_MM_MIN = 2.5
CSS_PX_PER_MM_MAX = 9.0
DEVICE_PX_PER_MM_MAX = 30.0
# How well a person lines a card edge up with a drawn edge, per edge (mm, 1σ). Two edges per axis.
EDGE_MATCH_SIGMA_MM = 0.25
ASPECT_WARN = 0.015  # 1.5 % aspect mismatch: the user matched one side but not the other
ASPECT_FAIL = 0.04


@dataclass(frozen=True)
class CardCalibration:
    css_px_per_mm: float
    device_px_per_mm: float
    device_pixel_ratio: float
    aspect_error: float  # (w/h) / (85.60/53.98) - 1
    sigma_rel: float  # relative 1σ scale uncertainty
    ok: bool
    warnings: list[str] = field(default_factory=list)

    def sigma_mm(self, length_mm: float) -> float:
        """1σ error this scale adds to a length measured on the screen mat."""
        return abs(length_mm) * self.sigma_rel


def card_px_per_mm(rect_w_css: float, rect_h_css: float, device_pixel_ratio: float = 1.0) -> CardCalibration:
    """Scale from a rectangle (CSS px) matched to an ID-1 card. Orientation-agnostic (portrait or landscape).

    Least squares over both sides: s = (w·W + h·H) / (W² + H²). The uncertainty combines edge alignment (two edges per
    side, `EDGE_MATCH_SIGMA_MM` each) with half a CSS pixel of quantisation per edge.
    """
    if rect_w_css <= 0 or rect_h_css <= 0 or device_pixel_ratio <= 0:
        raise ValueError("rectangle size and devicePixelRatio must be positive")
    w, h = max(rect_w_css, rect_h_css), min(rect_w_css, rect_h_css)
    s = (w * ID1_W_MM + h * ID1_H_MM) / (ID1_W_MM**2 + ID1_H_MM**2)
    aspect_error = (w / h) / (ID1_W_MM / ID1_H_MM) - 1.0
    per_edge_px = math.hypot(EDGE_MATCH_SIGMA_MM * s, 0.5 / math.sqrt(3))
    # σ of s from the two side estimates (each side: 2 edges), combined as in the LS weights.
    sig_w = math.sqrt(2) * per_edge_px / ID1_W_MM
    sig_h = math.sqrt(2) * per_edge_px / ID1_H_MM
    ww, wh = ID1_W_MM**2, ID1_H_MM**2
    sigma_s = math.sqrt((ww * sig_w) ** 2 + (wh * sig_h) ** 2) / (ww + wh)
    warnings: list[str] = []
    ok = True
    if not CSS_PX_PER_MM_MIN <= s <= CSS_PX_PER_MM_MAX:
        ok = False
        warnings.append(
            f"{s:.2f} CSS px/mm is outside the plausible range {CSS_PX_PER_MM_MIN}–{CSS_PX_PER_MM_MAX}; "
            "check the browser zoom is 100 % and redo the card match."
        )
    if s * device_pixel_ratio > DEVICE_PX_PER_MM_MAX:
        ok = False
        warnings.append("devicePixelRatio looks wrong for this screen; reload the page and redo the card match.")
    if abs(aspect_error) > ASPECT_FAIL:
        ok = False
        warnings.append(
            f"The rectangle's shape is {aspect_error * 100:+.1f} % off a card's; match both the long and the short side."
        )
    elif abs(aspect_error) > ASPECT_WARN:
        warnings.append(
            f"The rectangle's shape is {aspect_error * 100:+.1f} % off a card's; re-check the short side for best accuracy."
        )
    return CardCalibration(
        css_px_per_mm=s,
        device_px_per_mm=s * device_pixel_ratio,
        device_pixel_ratio=device_pixel_ratio,
        aspect_error=aspect_error,
        sigma_rel=sigma_s / s,
        ok=ok,
        warnings=warnings,
    )


def mat_size_css(width_mm: float, height_mm: float, css_px_per_mm: float) -> tuple[float, float]:
    """CSS size at which a mat must be drawn to appear at 1:1."""
    return width_mm * css_px_per_mm, height_mm * css_px_per_mm


def viewport_mm(viewport_w_css: float, viewport_h_css: float, css_px_per_mm: float) -> tuple[float, float]:
    """Physical size of the browser viewport."""
    return viewport_w_css / css_px_per_mm, viewport_h_css / css_px_per_mm


def ruler_scale_correction(observed_mm: float, nominal_mm: float = 50.0) -> float:
    """Paper mat check: the user measures the printed 50.0 mm ruler. Returns the factor that multiplies every mat
    coordinate (true mm = nominal mm × factor). Raises if the print is so far off that it was clearly not printed at 100 %."""
    if observed_mm <= 0:
        raise ValueError("observed length must be positive")
    factor = observed_mm / nominal_mm
    if abs(factor - 1.0) > 0.08:
        raise ValueError(
            f"The ruler measures {observed_mm:.1f} mm instead of {nominal_mm:.1f} mm; reprint at 100 % / Actual size."
        )
    return factor
