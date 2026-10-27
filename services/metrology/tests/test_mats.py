import json
from itertools import combinations
from pathlib import Path

import cv2
import numpy as np
import pytest

from services.metrology import mats
from services.metrology.calibrate import detect_mat

REPO = Path(__file__).resolve().parents[3]


def test_registry_ids_are_disjoint_and_in_dictionary() -> None:
    all_ids = [i for m in mats.all_mats() for i in m.ids]
    assert len(all_ids) == len(set(all_ids))
    assert max(all_ids) < 100  # DICT_5X5_100
    assert {m.mat_id for m in mats.all_mats()} == {"screen-s", "screen-m", "screen-l", "paper-a4"}
    for m in mats.all_mats():
        assert m.dictionary == "DICT_5X5_100"


@pytest.mark.parametrize("mat", mats.all_mats(), ids=lambda m: m.mat_id)
def test_geometry_is_sane(mat: mats.MatSpec) -> None:
    s = mat.marker_size_mm
    rects = [mats.Rect(mk.x_mm, mk.y_mm, s, s) for mk in mat.markers]
    for r in rects:  # inside the mat with a quiet zone of at least one cell
        assert r.x_mm >= mat.cell_mm - 1e-9 and r.y_mm >= mat.cell_mm - 1e-9
        assert r.x2_mm <= mat.width_mm - mat.cell_mm + 1e-9 and r.y2_mm <= mat.height_mm - mat.cell_mm + 1e-9
        # stage does not overlap any marker
        st = mat.stage
        assert r.x2_mm <= st.x_mm or r.x_mm >= st.x2_mm or r.y2_mm <= st.y_mm or r.y_mm >= st.y2_mm
    for a, b in combinations(rects, 2):  # neighbours at least one cell apart
        gap = max(b.x_mm - a.x2_mm, a.x_mm - b.x2_mm, b.y_mm - a.y2_mm, a.y_mm - b.y2_mm)
        assert gap >= mat.cell_mm
    assert mat.stage.w_mm > 50 and mat.stage.h_mm > 25
    if mat.kind.value == "screen":
        assert mat.min_screen_mm[0] >= mat.width_mm and mat.min_screen_mm[1] >= mat.height_mm


def test_lookup_identify_and_corners() -> None:
    m = mats.get_mat("screen-m")
    assert mats.identify([m.ids[0], m.ids[3], 999]).mat_id == "screen-m"
    assert mats.identify([0, 1, 30]).mat_id == "screen-s"  # majority wins
    with pytest.raises(ValueError):
        mats.identify([99, 98])
    with pytest.raises(KeyError, match="closest"):
        mats.get_mat("screen-xl")
    c = mats.marker_corners_mm(m.ids[0])
    mk = m.markers[0]
    s = m.marker_size_mm
    np.testing.assert_allclose(
        c, [[mk.x_mm, mk.y_mm], [mk.x_mm + s, mk.y_mm], [mk.x_mm + s, mk.y_mm + s], [mk.x_mm, mk.y_mm + s]]
    )


@pytest.mark.parametrize("mat_id", ["screen-s", "screen-m", "screen-l", "paper-a4"])
def test_layout_json_shape(mat_id: str) -> None:
    lay = mats.layout_json(mat_id)
    assert set(lay) == {
        "mat_id",
        "kind",
        "title",
        "width_mm",
        "height_mm",
        "dictionary",
        "stage",
        "markers",
        "min_screen_mm",
    }
    assert set(lay["stage"]) == {"x_mm", "y_mm", "w_mm", "h_mm"}
    assert set(lay["min_screen_mm"]) == {"w", "h"}
    for mk in lay["markers"]:
        bits = np.array(mk["bits"])
        assert bits.shape == (7, 7)
        assert set(np.unique(bits)) <= {0, 1}
        assert (
            not bits[0].any() and not bits[-1].any() and not bits[:, 0].any() and not bits[:, -1].any()
        )  # black border
        # bits round-trip through the dictionary (1 = white)
        img = np.kron(bits * 255, np.ones((10, 10))).astype(np.uint8)
        img = np.asarray(cv2.copyMakeBorder(img, 20, 20, 20, 20, cv2.BORDER_CONSTANT, value=255), dtype=np.uint8)
        _, ids, _ = cv2.aruco.ArucoDetector(mats.aruco_dictionary()).detectMarkers(img)
        assert ids is not None and int(ids.ravel()[0]) == mk["id"]


def test_web_layout_files_are_current() -> None:
    d = REPO / "apps" / "web" / "public" / "mats"
    index = json.loads((d / "index.json").read_text())
    assert [e["mat_id"] for e in index] == [m.mat_id for m in mats.all_mats()]
    for m in mats.all_mats():
        assert json.loads((d / f"{m.mat_id}.json").read_text()) == mats.layout_json(m.mat_id)


def test_render_mat_is_detectable_and_exact() -> None:
    ppm = 6.0
    img = mats.render_mat("screen-m", ppm)
    m = mats.get_mat("screen-m")
    assert img.shape == (round(m.height_mm * ppm), round(m.width_mm * ppm))
    det = detect_mat(np.asarray(cv2.cvtColor(img, cv2.COLOR_GRAY2BGR), dtype=np.uint8))
    assert det.mat.mat_id == "screen-m" and det.n_markers == len(m.markers)
    # pixel centre convention: mat mm = (px + 0.5) / ppm
    expected = det.mat_pts * ppm - 0.5
    assert np.sqrt(np.mean(np.sum((det.img_pts - expected) ** 2, axis=1))) < 0.1


def test_fitting_mats() -> None:
    assert [m.mat_id for m in mats.fitting_mats(140, 65)] == ["screen-s"]
    assert mats.fitting_mats(300, 190)[0].mat_id == "screen-m"
    assert mats.fitting_mats(350, 200)[0].mat_id == "screen-l"
    assert mats.fitting_mats(100, 50) == []
