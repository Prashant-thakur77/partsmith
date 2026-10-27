"""Calibration mat registry: rings of ArUco markers around a plain stage where the part sits.

Every mat uses its own block of marker ids from `DICT_5X5_100`, so a photo identifies its mat from the ids it sees.
Mat frame: x right, y down, origin at the mat's top-left corner, millimetres. Marker corners are listed TL, TR, BR, BL,
the same order the OpenCV detector returns them in.

Sizes were chosen so a marker spans ≥ 60 image px at typical phone distances (150–400 mm, ~26 mm-equivalent lens) and
neighbouring markers are at least one marker cell apart. The ring is sparse on purpose: the part may cover a few markers
and two markers are enough for a homography.
"""

from __future__ import annotations

import difflib
import math
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from functools import cache
from typing import Any

import cv2
import numpy as np
from numpy.typing import NDArray
from partsmith_schemas.measurement import MatKind

DICTIONARY_NAME = "DICT_5X5_100"
MARKER_BITS = 5  # payload bits per side; the drawn grid is 7×7 with the black border
GRID_CELLS = MARKER_BITS + 2

ID1_CARD_MM = (85.60, 53.98)

# Stage fills the screen mat can show (sRGB hex). Light suits dark and coloured parts; dark suits white, grey and beige
# parts. The marker ring always stays black on white. Dark is a deep grey, not black: a glossy screen showing black
# mirrors the room and the phone, which a grey's own light partly masks.
STAGE_COLOURS: dict[str, str] = {"light": "#FFFFFF", "dark": "#303030"}
DEFAULT_STAGE = "light"


@dataclass(frozen=True)
class Rect:
    """Axis-aligned rectangle in mat millimetres."""

    x_mm: float
    y_mm: float
    w_mm: float
    h_mm: float

    @property
    def x2_mm(self) -> float:
        return self.x_mm + self.w_mm

    @property
    def y2_mm(self) -> float:
        return self.y_mm + self.h_mm

    def corners(self) -> NDArray[np.float64]:
        """TL, TR, BR, BL corners (mm)."""
        return np.array(
            [[self.x_mm, self.y_mm], [self.x2_mm, self.y_mm], [self.x2_mm, self.y2_mm], [self.x_mm, self.y2_mm]],
            dtype=np.float64,
        )

    def inset(self, d_mm: float) -> Rect:
        return Rect(self.x_mm + d_mm, self.y_mm + d_mm, self.w_mm - 2 * d_mm, self.h_mm - 2 * d_mm)

    def contains(self, pts_mm: NDArray[np.float64]) -> NDArray[np.bool_]:
        p = np.asarray(pts_mm, dtype=np.float64).reshape(-1, 2)
        return (p[:, 0] >= self.x_mm) & (p[:, 0] <= self.x2_mm) & (p[:, 1] >= self.y_mm) & (p[:, 1] <= self.y2_mm)


@dataclass(frozen=True)
class MarkerPlacement:
    id: int
    x_mm: float  # top-left corner of the marker's outer black border
    y_mm: float


@dataclass(frozen=True)
class MatSpec:
    """One calibration mat. All lengths in millimetres, mat frame."""

    mat_id: str
    kind: MatKind
    title: str
    width_mm: float
    height_mm: float
    marker_size_mm: float
    markers: tuple[MarkerPlacement, ...]
    stage: Rect
    min_screen_mm: tuple[float, float]  # screen mats: smallest viewport that shows the whole mat; paper: page size
    page_offset_mm: tuple[float, float] = (0.0, 0.0)  # paper only: mat origin on the printed page
    dictionary: str = DICTIONARY_NAME

    @property
    def ids(self) -> tuple[int, ...]:
        return tuple(m.id for m in self.markers)

    @property
    def cell_mm(self) -> float:
        return self.marker_size_mm / GRID_CELLS

    @property
    def bounds(self) -> Rect:
        return Rect(0.0, 0.0, self.width_mm, self.height_mm)

    def placement(self, marker_id: int) -> MarkerPlacement:
        for m in self.markers:
            if m.id == marker_id:
                return m
        raise KeyError(f"marker {marker_id} is not on mat {self.mat_id}")

    def marker_corners_mm(self, marker_id: int) -> NDArray[np.float64]:
        m = self.placement(marker_id)
        return Rect(m.x_mm, m.y_mm, self.marker_size_mm, self.marker_size_mm).corners()

    def ring_rect(self) -> Rect:
        """Bounding box of the marker ring (outer edge of the markers)."""
        xs = [m.x_mm for m in self.markers]
        ys = [m.y_mm for m in self.markers]
        return Rect(min(xs), min(ys), max(xs) + self.marker_size_mm - min(xs), max(ys) + self.marker_size_mm - min(ys))


def _ring(
    first_id: int, width_mm: float, height_mm: float, size_mm: float, margin_mm: float, nx: int, ny: int
) -> tuple[MarkerPlacement, ...]:
    """Markers evenly spaced around the border, clockwise from the top-left corner."""
    xs = np.linspace(margin_mm, width_mm - margin_mm - size_mm, nx)
    ys = np.linspace(margin_mm, height_mm - margin_mm - size_mm, ny)
    pos: list[tuple[float, float]] = [(float(x), float(ys[0])) for x in xs]
    pos += [(float(xs[-1]), float(y)) for y in ys[1:-1]]
    pos += [(float(x), float(ys[-1])) for x in xs[::-1]]
    pos += [(float(xs[0]), float(y)) for y in ys[-2:0:-1]]
    return tuple(MarkerPlacement(first_id + i, round(x, 4), round(y, 4)) for i, (x, y) in enumerate(pos))


def _screen_mat(
    mat_id: str,
    title: str,
    first_id: int,
    w: float,
    h: float,
    size: float,
    margin: float,
    nx: int,
    ny: int,
    inset: float,
    min_screen: tuple[float, float],
    kind: MatKind = MatKind.screen,
    page_offset: tuple[float, float] = (0.0, 0.0),
) -> MatSpec:
    edge = margin + size + inset
    return MatSpec(
        mat_id=mat_id,
        kind=kind,
        title=title,
        width_mm=w,
        height_mm=h,
        marker_size_mm=size,
        markers=_ring(first_id, w, h, size, margin, nx, ny),
        stage=Rect(edge, edge, w - 2 * edge, h - 2 * edge),
        min_screen_mm=min_screen,
        page_offset_mm=page_offset,
    )


_MATS: tuple[MatSpec, ...] = (
    _screen_mat("screen-s", "Phone screen mat", 0, 120.0, 54.0, 8.0, 2.0, 8, 4, 3.0, (124.0, 58.0)),
    _screen_mat(
        "screen-m", "Tablet / 13-inch laptop screen mat", 25, 210.0, 130.0, 14.0, 3.0, 8, 6, 4.0, (214.0, 134.0)
    ),
    _screen_mat("screen-l", "15-inch laptop screen mat", 50, 320.0, 180.0, 18.0, 3.0, 9, 5, 5.0, (324.0, 184.0)),
    _screen_mat(
        "paper-a4",
        "Plain-paper A4 mat",
        75,
        190.0,
        245.0,
        20.0,
        3.0,
        6,
        7,
        5.0,
        (210.0, 297.0),
        kind=MatKind.paper,
        page_offset=(10.0, 10.0),
    ),
)
_BY_ID = {m.mat_id: m for m in _MATS}
_MAT_OF_MARKER = {mk.id: m.mat_id for m in _MATS for mk in m.markers}


def all_mats() -> tuple[MatSpec, ...]:
    return _MATS


def get_mat(mat_id: str) -> MatSpec:
    """Look a mat up by id. Unknown ids raise `KeyError` naming the closest matches."""
    try:
        return _BY_ID[mat_id]
    except KeyError:
        close = difflib.get_close_matches(mat_id, list(_BY_ID), n=3, cutoff=0.3)
        raise KeyError(f"unknown mat {mat_id!r}; closest: {close or list(_BY_ID)}") from None


def identify(ids: Iterable[int]) -> MatSpec:
    """The mat that owns most of the detected marker ids. Raises `ValueError` when no id belongs to any mat."""
    votes = Counter(_MAT_OF_MARKER[i] for i in (int(x) for x in ids) if i in _MAT_OF_MARKER)
    if not votes:
        raise ValueError("none of the detected markers belong to a PartSmith mat")
    return _BY_ID[votes.most_common(1)[0][0]]


def mat_of_marker(marker_id: int) -> str | None:
    return _MAT_OF_MARKER.get(int(marker_id))


def marker_corners_mm(marker_id: int) -> NDArray[np.float64]:
    """TL, TR, BR, BL corners (mat mm) of a marker id on whichever mat owns it."""
    mat_id = _MAT_OF_MARKER.get(int(marker_id))
    if mat_id is None:
        raise KeyError(f"marker {marker_id} is not on any mat")
    return _BY_ID[mat_id].marker_corners_mm(int(marker_id))


@cache
def aruco_dictionary() -> cv2.aruco.Dictionary:
    return cv2.aruco.getPredefinedDictionary(getattr(cv2.aruco, DICTIONARY_NAME))


@cache
def marker_bits(marker_id: int) -> NDArray[np.uint8]:
    """7×7 grid including the black border, row-major, 1 = white."""
    img = cv2.aruco.generateImageMarker(aruco_dictionary(), int(marker_id), GRID_CELLS)
    return (img > 127).astype(np.uint8)


def aruco_board(mat: MatSpec) -> cv2.aruco.Board:
    """OpenCV board object (z = 0 plane) — used to recover missed markers."""
    obj = [np.c_[mat.marker_corners_mm(i), np.zeros(4)].astype(np.float32) for i in mat.ids]
    return cv2.aruco.Board(obj, aruco_dictionary(), np.array(mat.ids, dtype=np.int32))


def _overlap(edges_px: NDArray[np.float64], n_px: int, offset: int) -> NDArray[np.float64]:
    """Coverage of pixels [offset, offset+n_px) by each interval [edges[i], edges[i+1]] → (len(edges)-1, n_px)."""
    j = np.arange(offset, offset + n_px, dtype=np.float64)
    lo = np.maximum(j[None, :], edges_px[:-1, None])
    hi = np.minimum(j[None, :] + 1.0, edges_px[1:, None])
    return np.asarray(np.clip(hi - lo, 0.0, 1.0), dtype=np.float64)


def render_mat(mat_id: str, px_per_mm: float) -> NDArray[np.uint8]:
    """Greyscale mat image (white background, black marker cells) with exact area anti-aliasing.

    Pixel (row i, col j) covers mat mm [j, j+1)/px_per_mm × [i, i+1)/px_per_mm, so its centre is at ((j+0.5), (i+0.5))/px_per_mm.
    """
    mat = get_mat(mat_id)
    w_px, h_px = math.ceil(mat.width_mm * px_per_mm), math.ceil(mat.height_mm * px_per_mm)
    dark = np.zeros((h_px, w_px), dtype=np.float64)
    for mk in mat.markers:
        black = (1 - marker_bits(mk.id)).astype(np.float64)
        ex = np.asarray((mk.x_mm + np.arange(GRID_CELLS + 1) * mat.cell_mm) * px_per_mm, dtype=np.float64)
        ey = np.asarray((mk.y_mm + np.arange(GRID_CELLS + 1) * mat.cell_mm) * px_per_mm, dtype=np.float64)
        x0, x1 = max(math.floor(ex[0]), 0), min(math.ceil(ex[-1]), w_px)
        y0, y1 = max(math.floor(ey[0]), 0), min(math.ceil(ey[-1]), h_px)
        ox = _overlap(ex, x1 - x0, x0)
        oy = _overlap(ey, y1 - y0, y0)
        dark[y0:y1, x0:x1] += oy.T @ black @ ox
    return np.round(255.0 * (1.0 - np.clip(dark, 0.0, 1.0))).astype(np.uint8)


def layout_json(mat_id: str) -> dict[str, Any]:
    """`MatLayout` (docs/API.md): what the web screen-mat page and the PDF generator draw."""
    mat = get_mat(mat_id)
    return {
        "mat_id": mat.mat_id,
        "kind": mat.kind.value,
        "title": mat.title,
        "width_mm": mat.width_mm,
        "height_mm": mat.height_mm,
        "dictionary": mat.dictionary,
        "stage": {"x_mm": mat.stage.x_mm, "y_mm": mat.stage.y_mm, "w_mm": mat.stage.w_mm, "h_mm": mat.stage.h_mm},
        "markers": [
            {
                "id": mk.id,
                "x_mm": mk.x_mm,
                "y_mm": mk.y_mm,
                "size_mm": mat.marker_size_mm,
                "bits": marker_bits(mk.id).tolist(),
            }
            for mk in mat.markers
        ],
        "min_screen_mm": {"w": mat.min_screen_mm[0], "h": mat.min_screen_mm[1]},
    }


def fitting_mats(viewport_w_mm: float, viewport_h_mm: float) -> list[MatSpec]:
    """Screen mats that fit a viewport (either orientation), largest stage first."""
    vw, vh = max(viewport_w_mm, viewport_h_mm), min(viewport_w_mm, viewport_h_mm)
    ok = [m for m in _MATS if m.kind == MatKind.screen and m.min_screen_mm[0] <= vw and m.min_screen_mm[1] <= vh]
    return sorted(ok, key=lambda m: -m.stage.w_mm * m.stage.h_mm)
