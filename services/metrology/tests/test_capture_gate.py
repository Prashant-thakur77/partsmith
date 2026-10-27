from dataclasses import replace

import numpy as np
import pytest
from partsmith_schemas.measurement import CaptureCheck, CaptureReport

from services.metrology import testing as T
from services.metrology.calibrate import MatDetection, detect_mat
from services.metrology.capture_gate import run_gate

MAT = "screen-m"
CENTRE = (105.0, 65.0)
PART = T.PrismPart(T.rect_poly(105, 65, 40, 20, 10), [], thickness_mm=3.0)


@pytest.fixture(scope="module")
def good() -> T.Scene:
    cam = T.camera_above(CENTRE, height_mm=260, tilt_deg=8, azimuth_deg=30)
    return T.render_part_scene(MAT, cam, PART)


def _checks(
    img: np.ndarray, mask: np.ndarray | None = None, det: MatDetection | None = None
) -> tuple[CaptureReport, dict[str, CaptureCheck]]:
    d = det if det is not None else detect_mat(img)
    rep = run_gate(img, d, mask)
    return rep, {c.name: c for c in rep.checks}


def test_good_photo_passes(good: T.Scene) -> None:
    rep, c = _checks(T.add_noise(good.image, 2.0), good.mask)
    assert rep.passed and rep.retake_reason is None
    assert all(x.severity == "ok" for x in rep.checks), [(x.name, x.reason) for x in rep.checks if x.severity != "ok"]
    assert set(c) == {
        "markers",
        "reprojection",
        "blur",
        "coverage",
        "contrast",
        "tilt",
        "exposure",
        "glare",
        "moire",
        "scale",
    }
    for x in rep.checks:
        assert x.reason.endswith(".")


def test_blur_fails(good: T.Scene) -> None:
    ppm = good.camera.K[0, 0] / good.camera.height_mm
    rep, c = _checks(T.blur(good.image, 0.35 * ppm), good.mask)
    assert not rep.passed and c["blur"].severity == "fail"
    assert "blurry" in (rep.retake_reason or "")
    _, c2 = _checks(T.blur(good.image, 0.18 * ppm), good.mask)
    assert c2["blur"].severity == "warn"


def test_tilt(good: T.Scene) -> None:
    for tilt, sev in ((20, "warn"), (30, "fail")):
        cam = T.camera_above(CENTRE, height_mm=260, tilt_deg=tilt, azimuth_deg=0)
        sc = T.render_part_scene(MAT, cam, PART)
        _, c = _checks(sc.image, sc.mask)
        assert c["tilt"].severity == sev
        assert c["tilt"].value == pytest.approx(tilt, abs=0.3)


def test_coverage_part_touching_markers() -> None:
    edge = T.PrismPart(T.rect_poly(40, 30, 40, 20), [], 3.0)  # overlaps the stage border
    cam = T.camera_above(CENTRE, height_mm=260, tilt_deg=5)
    sc = T.render_part_scene(MAT, cam, edge)
    rep, c = _checks(sc.image, sc.mask)
    assert c["coverage"].severity == "fail" and not rep.passed
    _, c0 = _checks(sc.image, None)
    assert c0["coverage"].severity == "ok"  # not checked without a mask


def test_exposure_clipped_part(good: T.Scene) -> None:
    img = good.image.copy()
    img[good.mask] = 255
    _rep, c = _checks(img, good.mask)
    assert c["exposure"].severity == "fail" and "blown out" in c["exposure"].reason


def test_glare_on_markers_and_part(good: T.Scene) -> None:
    cam = good.camera
    c_px = cam.project(np.array([[40.0, 12.0, 0.0]]))[0]
    img = T.add_glare(good.image, (float(c_px[0]), float(c_px[1])), 190)
    _rep, c = _checks(img, good.mask, det=detect_mat(good.image))
    assert c["glare"].severity == "fail" and "glare covers" in c["glare"].reason
    assert c["glare"].value is not None and c["glare"].value >= 3
    p_px = cam.project(np.array([[105.0, 65.0, 0.0]]))[0]
    img2 = T.add_glare(good.image, (float(p_px[0]), float(p_px[1])), 40)
    _, c2 = _checks(img2, good.mask)
    assert c2["glare"].severity == "fail" and "the part" in c2["glare"].reason


def test_moire(good: T.Scene) -> None:
    det = detect_mat(good.image)
    _, c = _checks(T.add_noise(T.add_moire(good.image, 9.0, 30.0, 9.0), 2.0), good.mask, det=det)
    assert c["moire"].severity == "fail"
    _, c2 = _checks(T.add_noise(T.add_moire(good.image, 7.0, 75.0, 4.0), 2.0), good.mask, det=det)
    assert c2["moire"].severity == "warn"


def test_scale_mismatch(good: T.Scene) -> None:
    det = detect_mat(good.image)
    wrong = replace(det, mat=replace(det.mat, marker_size_mm=det.mat.marker_size_mm * 1.05))
    _, c = _checks(good.image, good.mask, det=wrong)
    assert c["scale"].severity == "fail"


def test_no_mat() -> None:
    img = np.full((480, 640, 3), 128, np.uint8)
    rep = run_gate(img, None)
    assert not rep.passed
    names = {c.name: c.severity for c in rep.checks}
    assert names["markers"] == "fail" and names["tilt"] == "fail"
    assert rep.retake_reason and "markers" in rep.retake_reason
