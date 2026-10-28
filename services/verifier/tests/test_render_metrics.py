from __future__ import annotations

import cv2
import numpy as np
import pytest
import trimesh

from services.verifier import metrics as M
from services.verifier.render import (
    Frame,
    circle_polygon,
    placement_matrix,
    rasterize_polygon,
    rasterize_triangles,
    silhouette,
    silhouette_camera,
)


def _square_mesh(size: float = 10.0) -> tuple[np.ndarray, np.ndarray]:
    """Two overlapping copies of a square (overlaps must not cancel) at z = 0 and z = 1."""
    s = size / 2
    v = np.array([[-s, -s, 0], [s, -s, 0], [s, s, 0], [-s, s, 0]] * 2, dtype=float)
    v[4:, 2] = 1.0
    f = np.array([[0, 1, 2], [0, 2, 3], [4, 5, 6], [4, 6, 7], [0, 1, 3]])
    return v, f


def test_frame_round_trip() -> None:
    fr = Frame(20.0, -5.0, 7.0, 400, 300)
    pts = np.array([[-5.0, 7.0], [1.234, -3.21]])
    assert np.allclose(fr.to_mm(fr.to_px(pts)), pts)
    assert fr.to_px(np.array([-5.0 + 0.025, 7.0 - 0.025])) == pytest.approx([0.0, 0.0])  # first pixel centre


def test_overlapping_triangles_do_not_cancel() -> None:
    v, f = _square_mesh()
    fr = Frame.around(v[:, :2], 20.0, margin_mm=1.0)
    mask = silhouette(v, f, "top", fr)
    area_mm2 = mask.sum() / 20.0**2
    assert area_mm2 == pytest.approx(100.0, rel=0.01)
    # A single fillPoly over all triangles would leave holes where they overlap.
    tris = fr.to_px(v[:, :2])[f]
    wrong = np.zeros(fr.shape, np.uint8)
    cv2.fillPoly(wrong, [np.round(t).astype(np.int32) for t in tris], 255)
    assert (wrong > 0).sum() < mask.sum() * 0.9


def test_supersampling_removes_half_pixel_growth() -> None:
    tri = np.array([[[10.3, 10.3], [19.7, 10.3], [19.7, 19.7]], [[10.3, 10.3], [19.7, 19.7], [10.3, 19.7]]])
    coarse = rasterize_triangles(tri, 40, 40, supersample=1).sum()
    fine = rasterize_triangles(tri, 40, 40, supersample=4).sum()
    exact = 9.4 * 9.4
    assert abs(fine - exact) < abs(coarse - exact)


def test_views_project_the_right_axes() -> None:
    box = trimesh.creation.box(extents=(10.0, 20.0, 4.0))
    box.apply_translation((0, 0, 2.0))
    v, f = np.asarray(box.vertices), np.asarray(box.faces)
    fr = Frame.around(np.array([[-15, -15], [15, 15]]), 10.0)
    for view, (w_mm, h_mm) in {"top": (10, 20), "side_xz": (10, 4), "side_yz": (20, 4)}.items():
        rows, cols = np.nonzero(silhouette(v, f, view, fr))
        assert (cols.max() - cols.min() + 1) / 10 == pytest.approx(w_mm, abs=0.15), view
        assert (rows.max() - rows.min() + 1) / 10 == pytest.approx(h_mm, abs=0.15), view


def test_polygon_with_hole_mask() -> None:
    outer = np.array([[-10, -5], [10, -5], [10, 5], [-10, 5]], float)
    hole = circle_polygon((0.0, 0.0), 4.0)
    fr = Frame.around(outer, 20.0)
    m = rasterize_polygon(outer, [hole], fr)
    assert m.sum() / 400 == pytest.approx(200 - np.pi * 4, rel=0.005)


def test_camera_silhouette_matches_orthographic_from_far_away() -> None:
    v, f = _square_mesh()
    K = np.array([[5000.0, 0, 500], [0, 5000.0, 500], [0, 0, 1]])
    R = np.eye(3)
    t = np.array([0.0, 0.0, 1000.0])  # camera 1 m above the mat looking down (+z into the table)
    P = placement_matrix(0.0, 0.0, 0.0)
    mask = silhouette_camera(v, f, K, R, t, 1000, 1000, placement=P)
    # 10 mm at 1000 mm with f = 5000 px -> 50 px per side
    assert mask.sum() == pytest.approx(50 * 50, rel=0.06)


def test_iou_and_distances_of_shifted_squares() -> None:
    fr = Frame(20.0, -20.0, 20.0, 800, 800)
    a = rasterize_polygon(np.array([[-10, -10], [10, -10], [10, 10], [-10, 10]], float), [], fr)
    b = rasterize_polygon(np.array([[-9.7, -10], [10.3, -10], [10.3, 10], [-9.7, 10]], float), [], fr)
    assert M.iou(a, a) == 1.0
    assert M.iou(a, b) == pytest.approx(19.7 / 20.3, abs=0.005)
    d = M.mask_contour_distances(b, a, fr)
    assert d.hausdorff_mm == pytest.approx(0.3, abs=0.06)
    assert d.mean_mm < d.hausdorff_mm
    over, under = M.over_under_mm2(a, b, fr)
    assert over == pytest.approx(6.0, abs=0.3) and under == pytest.approx(6.0, abs=0.3)


def test_contour_points_are_resampled() -> None:
    fr = Frame(10.0, -20.0, 20.0, 400, 400)
    m = rasterize_polygon(np.array([[-10, -10], [10, -10], [10, 10], [-10, 10]], float), [], fr)
    pts = M.contour_points_mm(m, fr, spacing_mm=0.05)
    gaps = np.linalg.norm(np.diff(pts, axis=0), axis=1)
    assert np.percentile(gaps, 99) <= 0.0501


def test_residual_heatmap_is_png() -> None:
    fr = Frame(20.0, -20.0, 20.0, 800, 800)
    a = rasterize_polygon(np.array([[-10, -10], [10, -10], [10, 10], [-10, 10]], float), [], fr)
    b = rasterize_polygon(np.array([[-9, -10], [11, -10], [11, 10], [-9, 10]], float), [], fr)
    d = M.mask_contour_distances(b, a, fr)
    png = M.residual_heatmap(a, b, fr, distances=d, title="top")
    img = cv2.imdecode(np.frombuffer(png, np.uint8), cv2.IMREAD_COLOR)
    assert img is not None and img.shape[2] == 3
    # Both over (vermillion) and under (blue) colours are present.
    assert np.any(np.all(img == M.COLOR_OVER, axis=2)) and np.any(np.all(img == M.COLOR_UNDER, axis=2))


def test_kept_contour_points_are_measured_to_the_whole_other_boundary() -> None:
    """Near an excluded (broken) region the two boundaries are clipped at slightly different places; a kept point
    must be matched to the other boundary where it continues into the region, not to the far end of its clipped
    piece (that turned a perfect fit into a multi-mm 'error' next to the region)."""
    x = np.linspace(0.0, 10.0, 201)
    line = np.c_[x, np.zeros_like(x)]
    model_kept, photo_kept = line[x <= 6.0], line[x <= 3.0]
    clipped = M.contour_distances_mm(model_kept, photo_kept)
    assert clipped.hausdorff_mm == pytest.approx(3.0, abs=0.06)
    whole = M.contour_distances_mm(model_kept, photo_kept, line, line)
    assert whole.hausdorff_mm < 1e-9
    # a real error on a kept point is still seen
    bent = model_kept.copy()
    bent[-1, 1] = 0.8
    assert M.contour_distances_mm(bent, photo_kept, line, line).hausdorff_mm == pytest.approx(0.8, abs=1e-6)
