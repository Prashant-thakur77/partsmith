import cv2
import numpy as np
from shapely.geometry import Polygon

from services.metrology import testing as T
from services.metrology.calibrate import detect_mat, rectify
from services.metrology.mats import get_mat
from services.metrology.recon_gate import _stage_mask, gate_reconstruction

MAT = get_mat("screen-m")
CAM = T.camera_above((105, 65), height_mm=260, tilt_deg=8, azimuth_deg=30)
FULL = T.rect_poly(105, 65, 40, 20, 10)
NOTCH = T.rect_poly(122, 68, 10, 12, 10)
BROKEN = np.asarray(Polygon(FULL).difference(Polygon(NOTCH)).exterior.coords)[:-1]


def _rect(poly: np.ndarray):
    sc = T.render_part_scene("screen-m", CAM, T.PrismPart(poly, [], 0.5))
    return rectify(sc.image, detect_mat(sc.image).H, 6.0, MAT.bounds)


ORIG = _rect(BROKEN)
DONE = _rect(FULL)
KEEP = (cv2.cvtColor(ORIG.image, cv2.COLOR_BGR2GRAY) < 150) & _stage_mask(
    ORIG.image.shape[:2], MAT, 6.0, ORIG.origin_mm, 0.5
)


def test_good_completion_passes_and_is_inferred() -> None:
    g = gate_reconstruction(ORIG, DONE.image, KEEP, MAT)
    assert g.ok, g.reason
    assert g.marker_shift_px is not None and g.marker_shift_px < 0.1 and g.markers_compared >= 20
    assert g.intact_iou > 0.99
    true_area = Polygon(FULL).area - Polygon(BROKEN).area
    assert g.completion_area is not None and abs(g.completion_area.value - true_area) < 3.0
    assert g.completion_area.source.value == "inferred"
    assert g.completion_outline_mm and Polygon(g.completion_outline_mm[0]).intersects(Polygon(NOTCH))


def test_warped_image_fails_on_markers() -> None:
    g = gate_reconstruction(ORIG, np.roll(DONE.image, 2, axis=1), KEEP, MAT)
    assert not g.ok and "markers moved" in g.reason


def test_changed_intact_part_fails() -> None:
    recoloured = np.where(KEEP[..., None], (DONE.image * 0.6).astype(np.uint8), DONE.image)
    g = gate_reconstruction(ORIG, recoloured, KEEP, MAT)
    assert not g.ok and "changed colour" in g.reason
    eroded = cv2.erode(KEEP.astype(np.uint8), np.ones((9, 9), np.uint8)) > 0
    shrunk = np.where((KEEP & ~eroded)[..., None], np.array([230, 228, 224], np.uint8), DONE.image)
    g2 = gate_reconstruction(ORIG, shrunk, KEEP, MAT)
    assert not g2.ok and "changed shape" in g2.reason


def test_resized_and_misshaped_outputs() -> None:
    h, w = ORIG.image.shape[:2]
    small = cv2.resize(DONE.image, (w // 2, h // 2), interpolation=cv2.INTER_AREA)
    g = gate_reconstruction(ORIG, small, KEEP, MAT)
    assert g.marker_shift_px is not None  # resized back before comparing
    square = cv2.resize(DONE.image, (w, w))
    assert not gate_reconstruction(ORIG, square, KEEP, MAT).ok


def _px(pt_mm: tuple[float, float]) -> tuple[int, int]:
    p = ORIG.mm_to_px(np.array([pt_mm]))[0]
    return round(p[0]), round(p[1])


def test_junk_patch_with_marker_fragment_is_rejected() -> None:
    """What a mock image model produced: a whitish patch over the break carrying a fragment of a marker."""
    for offset in (0, 8):  # the dark cells touching the part, or floating in the patch
        junk = ORIG.image.copy()
        x0, y0 = _px((117, 62))
        x1, y1 = _px((128, 74))
        junk[y0:y1, x0:x1] = (226, 226, 226)
        cell = 9  # ≈ 1.5 mm cells at 6 px/mm, black-and-white like a marker
        for i in range(4):
            for j in range(4):
                if (i + j) % 2 == 0:
                    ys, xs = y0 + offset + i * cell, x0 + offset + j * cell
                    junk[ys : ys + cell, xs : xs + cell] = 25
        g = gate_reconstruction(ORIG, junk, KEEP, MAT)
        assert not g.ok, g.reason
        assert any(w in g.reason for w in ("marker", "colour", "ragged", "changed outside", "no part material"))


def test_wrong_colour_and_oversized_completions_are_rejected() -> None:
    red = DONE.image.copy()
    new = (cv2.cvtColor(DONE.image, cv2.COLOR_BGR2GRAY) < 150) & ~KEEP
    red[new] = (40, 40, 200)
    g = gate_reconstruction(ORIG, red, KEEP, MAT)
    assert not g.ok and "colour does not match" in g.reason
    expected = [tuple(p) for p in NOTCH.tolist()]
    big = DONE.image.copy()
    blob = np.zeros(KEEP.shape, np.uint8)
    cv2.circle(blob, _px((128, 70)), int(14 * 6.0), 1, -1)
    big[(blob > 0) & ~KEEP] = DONE.image[KEEP][0]
    g2 = gate_reconstruction(ORIG, big, KEEP, MAT, expected_mm=expected)
    assert not g2.ok and ("larger than the broken region" in g2.reason or "outside the broken region" in g2.reason)
    ok = gate_reconstruction(ORIG, DONE.image, KEEP, MAT, expected_mm=expected)
    assert ok.ok, ok.reason


def test_spike_that_does_not_continue_the_outline_is_rejected() -> None:
    spike = ORIG.image.copy()
    colour = ORIG.image[KEEP][len(ORIG.image[KEEP]) // 2]
    a, b = _px((105, 65)), _px((105, 95))  # a thin bar sticking straight out of the part's side
    cv2.line(spike, a, b, tuple(int(c) for c in colour), thickness=18)
    g = gate_reconstruction(ORIG, spike, KEEP, MAT)
    assert not g.ok and "does not continue the part" in g.reason
