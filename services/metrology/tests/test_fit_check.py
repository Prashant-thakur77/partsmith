import math

import numpy as np
import pytest
from partsmith_schemas import FitCheckResult
from shapely.geometry import Polygon

from services.metrology import testing as T
from services.metrology.fit_check import (
    FIT_OUTLINE_RGB,
    compare_to_outline,
    fit_check,
    fit_outline_for,
)

MAT = "screen-m"
OUTLINE_PART = T.rounded_rect_poly(0, 0, 40, 20, 3)
HOLES_PART = [{"center_mm": [8.0, 0.0], "diameter_mm": 6.0}]
BGR = (FIT_OUTLINE_RGB[2], FIT_OUTLINE_RGB[1], FIT_OUTLINE_RGB[0])


def test_fit_outline_for_centres_on_stage() -> None:
    fo = fit_outline_for(OUTLINE_PART, HOLES_PART, MAT)
    assert set(fo) == {"mat_id", "outline_mm", "holes", "dims", "placement"}
    o = np.array(fo["outline_mm"])
    assert o.mean(axis=0) == pytest.approx([105.0, 65.0], abs=0.05)  # screen-m stage centre
    assert fo["placement"] == {"cx_mm": 105.0, "cy_mm": 65.0, "theta_deg": 0.0}
    assert fo["holes"][0]["center_mm"] == [113.0, 65.0]  # part +X → mat +x, part Y up → mat y down
    assert fo["dims"][0]["value_mm"] == pytest.approx(40.0) and fo["dims"][1]["value_mm"] == pytest.approx(20.0)
    assert fo["dims"][2]["label"] == "Ø6.00"
    # paper mat stage is portrait: the long side turns 90°
    fp = fit_outline_for(OUTLINE_PART, [], "paper-a4")
    assert fp["placement"]["theta_deg"] == pytest.approx(90.0)
    op = np.array(fp["outline_mm"])
    assert np.ptp(op[:, 1]) == pytest.approx(40.0, abs=0.01)
    with pytest.raises(ValueError, match="larger mat"):
        fit_outline_for(T.rect_poly(0, 0, 150, 20), [], "screen-s")


def _photo(grow: float, shift: tuple[float, float] = (0.6, 0.4), light: bool = True) -> tuple[np.ndarray, dict]:  # type: ignore[type-arg]
    fo = fit_outline_for(OUTLINE_PART, HOLES_PART, MAT)
    ring = np.array(fo["outline_mm"])
    hc = fo["holes"][0]["center_mm"]
    pl = fo["placement"]
    real = T.rounded_rect_poly(0, 0, 40 + 2 * grow, 20 + 2 * grow, 3 + grow) * [1, -1] + [
        pl["cx_mm"] + shift[0],
        pl["cy_mm"] + shift[1],
    ]
    hole = T.circle_poly(hc[0] + shift[0], hc[1] + shift[1], 6.0)
    part = T.PrismPart(real, [hole], thickness_mm=3.0)
    if light:
        part.top_bgr, part.side_bgr = (200, 200, 205), (170, 170, 175)
    cam = T.camera_above((105, 65), height_mm=260, tilt_deg=8, azimuth_deg=60)

    def under(img: np.ndarray, c: T.Camera) -> np.ndarray:
        img = T.draw_outline_on_mat(img, c, ring, BGR, 0.4)
        return T.draw_outline_on_mat(img, c, T.circle_poly(hc[0], hc[1], 6.0, 180), BGR, 0.4)

    sc = T.render_scene(MAT, cam.K, cam.R, cam.t, cam.size, part, under=under)
    return sc.image, fo


def test_matching_part_passes() -> None:
    img, fo = _photo(0.0)
    out = fit_check(img, MAT, fo["outline_mm"], fo["holes"], thickness_mm=3.0)
    r = out.result
    assert isinstance(r, FitCheckResult)
    assert r.passed, r.reasons
    assert r.iou > 0.98 and out.hd95_mm < 0.15 and r.hausdorff_mm < 0.3
    assert math.hypot(*out.placement_shift_mm) == pytest.approx(math.hypot(0.6, 0.4), abs=0.1)
    assert out.holes[0].measured_diameter_mm == pytest.approx(6.0, abs=0.15)
    assert out.overlay_png[:4] == b"\x89PNG"
    assert r.overlay_url == "" and r.capture.passed


def test_oversized_part_fails_with_reasons() -> None:
    img, fo = _photo(0.6, light=False)
    out = fit_check(img, MAT, fo["outline_mm"], fo["holes"], thickness_mm=3.0)
    r = out.result
    assert not r.passed
    assert 0.45 < out.hd95_mm < 0.8
    assert out.worst_signed_mm > 0  # the part is larger than the outline
    assert any("larger than the model" in s for s in r.reasons)


def test_compare_to_outline_registration() -> None:
    target = Polygon(T.rect_poly(100, 60, 40, 20), [T.circle_poly(108, 60, 6)])
    moved = Polygon(
        T.rect_poly(101.5, 59.2, 40, 20, 2.0), [T.circle_poly(109.5, 59.2 + 8 * math.sin(math.radians(2)), 6)]
    )
    cmp = compare_to_outline(moved, target)
    assert cmp["hd95_mm"] < 0.1 and cmp["iou"] > 0.99
    assert cmp["rot_deg"] == pytest.approx(-2.0, abs=0.1)
    raw = compare_to_outline(moved, target, register=False)
    assert raw["hausdorff_mm"] > 0.5  # centroids aligned, 2° rotation left


def test_no_part() -> None:
    cam = T.camera_above((105, 65), height_mm=260, tilt_deg=8)
    sc = T.render_part_scene(MAT, cam, None)
    fo = fit_outline_for(OUTLINE_PART, HOLES_PART, MAT)
    out = fit_check(sc.image, MAT, fo["outline_mm"], fo["holes"])
    assert not out.result.passed and out.result.reasons
