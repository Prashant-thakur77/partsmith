"""Real-camera scale check: fit on outer markers only, score inner markers. Boards rendered here; no network."""

from __future__ import annotations

import json
from pathlib import Path

import cv2
import numpy as np
import pytest

from eval import public_scale as P
from services.metrology.calibrate import apply_h

DICT_NAME = "DICT_6X6_250"
GRID = P.Board("t-grid", "grid", (5, 7), 100.0, 20.0, DICT_NAME)
CHECKER = P.Board("t-check", "checker", (5, 7), 0.04, 0.02, DICT_NAME)


def _dict() -> cv2.aruco.Dictionary:
    return P.load_dictionary(DICT_NAME)


def _ideal_corners(layout: dict[int, np.ndarray], H: np.ndarray) -> dict[int, np.ndarray]:
    return {i: apply_h(H, c) for i, c in layout.items()}


H_PLANE_TO_IMG = np.array([[5.0, 0.8, 120.0], [-0.4, 5.2, 90.0], [1e-4, 2e-4, 1.0]])


def test_outer_ring_is_the_board_edge() -> None:
    assert len(P.outer_ids(P.board_layout(GRID, _dict()))) == 20  # 5×7 grid: 15 inner markers held out
    assert len(P.outer_ids(P.board_layout(CHECKER, _dict()))) == 10  # 17 markers: 7 inner


def test_the_long_side_of_the_board_is_the_span() -> None:
    pts = np.concatenate(list(P.board_layout(GRID, _dict()).values()))
    assert np.ptp(pts[:, 1]) == pytest.approx(P.SPAN)


def test_a_perfect_plane_predicts_the_held_out_corners_exactly() -> None:
    layout = P.board_layout(GRID, _dict())
    r = P.score_photo(_ideal_corners(layout, H_PLANE_TO_IMG), layout)
    assert r["status"] == "ok" and r["held_out_corners"] == 60 and r["fit_markers"] == 20
    assert r["mean_err_pct"] < 1e-3


def test_held_out_corners_cannot_influence_the_fit() -> None:
    layout = P.board_layout(GRID, _dict())
    corners = _ideal_corners(layout, H_PLANE_TO_IMG)
    inner = sorted(set(layout) - P.outer_ids(layout))
    corners[inner[0]] = corners[inner[0]] + 25.0  # px
    r = P.score_photo(corners, layout)
    assert r["fit_mean_err_pct"] < 1e-3  # the fit is untouched; only that marker is wrong
    errs = [max(m) for m in r["errors_pct_by_marker"]]
    assert max(errs) > 1.0 and sorted(errs)[-2] < 1e-3


def test_a_bent_plane_shows_up_on_the_held_out_corners() -> None:
    layout = P.board_layout(GRID, _dict())
    corners = _ideal_corners(layout, H_PLANE_TO_IMG)
    centre = np.mean(np.concatenate(list(corners.values())), axis=0)
    # barrel-like distortion: the middle of the board moves relative to its edge
    bent = {i: c + 2e-3 * (c - centre) * np.linalg.norm(c - centre, axis=1, keepdims=True) for i, c in corners.items()}
    assert P.score_photo(bent, layout)["mean_err_pct"] > 0.1


def test_detection_on_a_rendered_board_uses_the_product_detector() -> None:
    d = _dict()
    board = cv2.aruco.GridBoard((5, 7), 100.0, 20.0, d)
    img = cv2.cvtColor(board.generateImage((660, 900), marginSize=40), cv2.COLOR_GRAY2BGR)
    rep = P.analyse_photo(np.asarray(img, dtype=np.uint8), GRID, d)
    assert rep["markers_detected"] == 35 and rep["layout_confirmed_by_outer_markers"] is True
    assert rep["mean_err_pct"] < 0.1


def test_a_layout_its_outer_markers_reject_is_flagged_and_refitted_on_outer_markers() -> None:
    d = _dict()
    truth = P.board_layout(GRID, d)  # gap ratio 0.2
    wrong = P.Board("t", "grid", (5, 7), 100.0, 10.0, DICT_NAME)
    H = np.array([[5.0, 0.0, 100.0], [0.0, 5.0, 100.0], [0.0, 0.0, 1.0]])
    corners = _ideal_corners(truth, H)
    assert P.fit_gap_ratio(corners, wrong, d) == pytest.approx(0.2)
    q = P.score_photo(corners, P.board_layout(wrong, d))
    assert q["fit_inlier_corners"] / q["fit_corners"] < P.MIN_LAYOUT_INLIER_SHARE


def test_summary_counts_and_interval() -> None:
    photos = [{"photo_id": "a", "status": "ok", "errors_pct_by_marker": [[0.1, 0.1, 0.2, 0.2], [0.3, 0.3, 0.4, 0.4]]}]
    s = P.summarise(photos)
    assert s["n_corners"] == 8 and s["n_markers"] == 2 and s["n_photos"] == 1
    assert s["ci95_pct"][0] <= s["mean_err_pct"] <= s["ci95_pct"][1]
    assert s["mean_err_mm_over_100mm"] == s["mean_err_pct"]  # span 100 → the same number
    assert P.summarise([])["status"] == "pending"


def test_report_says_what_it_does_not_measure_and_counts_no_real_photos(tmp_path: Path) -> None:
    rep = P.build_report(tmp_path)  # no photos here
    assert rep["counts_as_real_photos_measured"] == 0
    assert "phone photographing a laptop screen" in rep["scope"] and "printed size is unknown" in rep["scope"]
    assert rep["summary"]["status"] == "pending"
    json.dumps(rep)
