import io

import numpy as np
import pytest
from PIL import Image

from services.metrology import testing as T
from services.metrology.calibrate import (
    MatNotFoundError,
    apply_h,
    detect_mat,
    estimate_focal_px,
    estimate_pose,
    exif_focal35_mm,
    height_scale,
    intrinsics_from_focal35,
    plane_homography,
    rectify,
)
from services.metrology.mats import get_mat


def _stage_centre(mat_id: str) -> tuple[float, float]:
    st = get_mat(mat_id).stage
    return st.x_mm + st.w_mm / 2, st.y_mm + st.h_mm / 2


@pytest.mark.parametrize(
    ("mat_id", "height"), [("screen-s", 170.0), ("screen-m", 260.0), ("screen-l", 360.0), ("paper-a4", 340.0)]
)
def test_detection_accuracy(mat_id: str, height: float) -> None:
    cam = T.camera_above(_stage_centre(mat_id), height_mm=height, tilt_deg=12, azimuth_deg=40)
    sc = T.render_part_scene(mat_id, cam, None)
    det = detect_mat(sc.image)
    assert det.mat.mat_id == mat_id
    assert det.n_markers == len(det.mat.markers)
    truth = cam.project(np.c_[det.mat_pts, np.zeros(len(det.mat_pts))])
    err = np.linalg.norm(truth - det.img_pts, axis=1)
    assert np.sqrt(np.mean(err**2)) < 0.15  # sub-pixel, unbiased corners
    assert np.linalg.norm(np.mean(truth - det.img_pts, axis=0)) < 0.03
    assert det.reproj_px_rms < 0.2 and det.reproj_mm_rms < 0.03
    # pose with known K
    pose = estimate_pose(det, cam.K)
    assert pose.intrinsics_source == "calibrated"
    assert pose.camera_height_mm == pytest.approx(height, rel=0.003)
    assert pose.tilt_deg == pytest.approx(12.0, abs=0.1)
    # pose with K estimated from the homography alone
    est = estimate_pose(det)
    assert est.intrinsics_source == "estimated"
    assert est.K[0, 0] == pytest.approx(cam.K[0, 0], rel=0.01)
    assert est.camera_height_mm == pytest.approx(height, rel=0.01)


def test_focal_unobservable_when_fronto_parallel() -> None:
    cam = T.camera_above(_stage_centre("screen-m"), height_mm=260, tilt_deg=0)
    det = detect_mat(T.render_part_scene("screen-m", cam, None).image)
    assert estimate_focal_px(det.H, det.image_size) is None
    pose = estimate_pose(det)  # falls back to a 26 mm-equivalent default
    np.testing.assert_allclose(pose.K, intrinsics_from_focal35(26.0, det.image_size))
    assert pose.tilt_deg < 0.2


def test_plane_homography_exact_for_raised_points() -> None:
    cam = T.camera_above((100, 60), height_mm=250, tilt_deg=15, azimuth_deg=120)
    det = detect_mat(T.render_part_scene("screen-m", cam, None).image)
    pose = estimate_pose(det, cam.K)
    h = 9.0
    pts = np.array([[60.0, 40.0], [150.0, 90.0], [100.0, 65.0], [30.0, 100.0]])
    img = cam.project(np.c_[pts, np.full(len(pts), -h)])  # mat z points into the table
    for H in (plane_homography(pose, h, det.H), plane_homography(pose, h)):
        np.testing.assert_allclose(apply_h(H, img), pts, atol=0.03)
    # the mat-plane homography reads raised points too far from the nadir
    assert np.max(np.linalg.norm(apply_h(det.H, img) - pts, axis=1)) > 1.0
    assert height_scale(250.0, 10.0) == pytest.approx(0.96)
    with pytest.raises(ValueError):
        height_scale(5.0, 10.0)


def test_rectify_maps_mat_mm_to_pixels() -> None:
    cam = T.camera_above((105, 65), height_mm=250, tilt_deg=10, azimuth_deg=30)
    sc = T.render_part_scene("screen-m", cam, None)
    det = detect_mat(sc.image)
    mat = det.mat
    rect = rectify(sc.image, det.H, 8.0, mat.bounds)
    ref = T.render_mat_view("screen-m", T.camera_above((105, 65), height_mm=250))  # just for shape sanity
    assert ref.ndim == 3
    assert rect.image.shape[:2] == (round(mat.height_mm * 8), round(mat.width_mm * 8))
    # marker cells land where the layout says: sample the centre of a black border cell and a stage pixel
    mk = mat.markers[0]
    px = rect.mm_to_px(np.array([[mk.x_mm + mat.cell_mm / 2, mk.y_mm + mat.cell_mm / 2]]))[0]
    assert rect.image[round(px[1]), round(px[0])].mean() < 80
    st = rect.mm_to_px(np.array([[mat.stage.x_mm + 30, mat.stage.y_mm + 30]]))[0]
    assert rect.image[round(st[1]), round(st[0])].mean() > 200
    np.testing.assert_allclose(rect.px_to_mm(rect.mm_to_px(np.array([[12.3, 45.6]]))), [[12.3, 45.6]])
    with pytest.raises(ValueError):
        rectify(sc.image, det.H, 8.0)


def test_no_mat_raises() -> None:
    blank = np.full((400, 600, 3), 200, np.uint8)
    with pytest.raises(MatNotFoundError):
        detect_mat(blank)


def test_exif_focal() -> None:
    im = Image.new("RGB", (64, 48), (128, 128, 128))
    exif = Image.Exif()
    exif[0x8769] = {0xA405: 26}
    buf = io.BytesIO()
    im.save(buf, format="JPEG", exif=exif)
    assert exif_focal35_mm(buf.getvalue()) == 26.0
    plain = io.BytesIO()
    im.save(plain, format="PNG")
    assert exif_focal35_mm(plain.getvalue()) is None
    K = intrinsics_from_focal35(26.0, (4000, 3000))
    assert K[0, 0] == pytest.approx(26.0 * 5000 / np.hypot(36, 24))


def test_distortion_round_trip() -> None:
    cam = T.camera_above((105, 65), height_mm=250, tilt_deg=10)
    sc = T.render_part_scene("screen-m", cam, None)
    dist = np.array([0.05, -0.02, 0.0, 0.0, 0.0])
    det = detect_mat(sc.image, K=cam.K, dist=dist)
    p = np.array([[100.0, 200.0], [800.0, 600.0]])
    np.testing.assert_allclose(det.undistort(det.distort(p)), p, atol=1e-3)
