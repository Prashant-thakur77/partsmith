"""The judge's shaded view: a picture only (no measurement), but it must show faces apart and survive odd input."""

from __future__ import annotations

import cv2
import numpy as np

from services.verifier.shade import shaded_png


def _box(x: float, y: float, z: float) -> tuple[np.ndarray, np.ndarray]:
    v = np.array([[i * x, j * y, k * z] for i in (0, 1) for j in (0, 1) for k in (0, 1)], np.float64)
    # outward-wound triangles of an axis-aligned box (vertex index = 4i + 2j + k)
    f = np.array(
        [
            [0, 1, 3], [0, 3, 2], [4, 6, 7], [4, 7, 5],  # x = 0, x = x
            [0, 4, 5], [0, 5, 1], [2, 3, 7], [2, 7, 6],  # y = 0, y = y
            [0, 2, 6], [0, 6, 4], [1, 5, 7], [1, 7, 3],  # z = 0, z = z
        ],
        np.int64,
    )  # fmt: skip
    return v, f


def test_a_box_shows_three_differently_lit_faces() -> None:
    v, f = _box(40.0, 20.0, 10.0)
    png = shaded_png(v, f, size_px=200)
    assert png is not None and png[:8] == b"\x89PNG\r\n\x1a\n"
    img = cv2.imdecode(np.frombuffer(png, np.uint8), cv2.IMREAD_COLOR)
    assert img is not None and img.shape == (200, 200, 3)
    fg = img[(img != 255).any(axis=2)]
    shades = {tuple(int(c) // 8 for c in px) for px in fg}
    assert len(fg) > 200 * 200 * 0.15 and len(shades) >= 3  # top, front and side faces are told apart


def test_empty_or_degenerate_mesh_gives_none() -> None:
    assert shaded_png(np.zeros((0, 3)), np.zeros((0, 3), np.int64)) is None
    v = np.zeros((3, 3))
    assert shaded_png(v, np.array([[0, 1, 2]], np.int64)) is None
