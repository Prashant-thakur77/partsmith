"""Public-photo composites: cut-out, circularity rule, and no source details in tracked data. No network."""

from __future__ import annotations

import re
from pathlib import Path

import cv2
import numpy as np
import pytest
import yaml

from eval import public_photos as E
from tools import public_photos as PP


def _photo(*, w: int = 600, h: int = 450, hole: bool = False) -> np.ndarray:
    """A dark 320 × 240 px card (or a 300 px disc with a 68 px hole) on a light background with a soft shadow."""
    img = np.full((h, w, 3), 205, np.uint8)
    if hole:
        cv2.circle(img, (w // 2, h // 2), 150, (40, 120, 170), -1, cv2.LINE_AA)
        cv2.circle(img, (w // 2, h // 2), 34, (205, 205, 205), -1, cv2.LINE_AA)
    else:
        cv2.rectangle(img, (130 - 12, 105), (130, 345), (150, 150, 150), -1)  # shadow on the left: not the object
        cv2.rectangle(img, (130, 105), (450, 345), (30, 25, 25), -1)
        cv2.rectangle(img, (180, 150), (400, 300), (220, 225, 230), -1)  # a light label, not a hole
    return img


def test_threshold_cut_leaves_the_shadow_out_and_fills_a_light_label() -> None:
    mask = PP.cut_out(_photo(), (20, 20, 580, 430), method="threshold")
    long_px, short_px, _, _ = PP.mask_box(mask)
    assert long_px == pytest.approx(321, abs=4) and short_px == pytest.approx(241, abs=4)
    assert mask[225, 290] == 255  # the label stays part of the object


def test_keep_holes_keeps_the_through_hole_only() -> None:
    mask = PP.cut_out(_photo(hole=True), (20, 20, 580, 430), method="threshold", keep_holes=True)
    assert mask[225, 300] == 0 and mask[225, 400] == 255
    assert PP.mask_box(mask)[0] == pytest.approx(301, abs=4)


def test_the_scale_setting_dimension_is_marked_and_nothing_else() -> None:
    sd = PP.gt_for(PP.OBJECTS["sd_card"], scale_from_self=True)
    assert [r["name"] for r in sd if r.get("set_by_construction")] == ["length"]
    assert [r["name"] for r in PP.scored_rows(sd)] == ["width"]
    # a second object in the photo takes its scale from the first: both its dimensions are held out
    dime = PP.gt_for(PP.OBJECTS["us_dime"], scale_from_self=False)
    assert not [r for r in dime if r.get("set_by_construction")] and len(PP.scored_rows(dime)) == 2
    coin = PP.gt_for(PP.OBJECTS["yen_5"], scale_from_self=True)
    assert [r["name"] for r in PP.scored_rows(coin)] == ["width", "hole_1.diameter"]


def test_source_to_mat_puts_the_long_side_along_the_turn() -> None:
    H = PP.source_to_mat((100.0, 50.0), 0.0, 0.1, (60.0, 40.0, 30.0))
    centre = H @ np.array([100.0, 50.0, 1.0])
    assert centre[:2] == pytest.approx([60.0, 40.0])
    end = H @ np.array([200.0, 50.0, 1.0])
    assert end[:2] - centre[:2] == pytest.approx([10.0 * np.cos(np.radians(30)), 10.0 * np.sin(np.radians(30))])


def test_composite_runs_the_real_measure_path_and_scores_held_out_only(tmp_path: Path) -> None:
    """End to end on a drawn card with an exact 4:3 outline: the width comes back near 24 mm from the mat."""
    photos = tmp_path / "photos"
    photos.mkdir()
    cv2.imwrite(str(photos / "x.png"), _photo())
    sd = PP.SampleDef("t-1", "sd_card", "x.png", 1, (20, 20, 580, 430), 7201, method="threshold")
    gt = PP.build_sample(sd, by_id={"t-1": sd}, photos=photos, out_root=tmp_path / "s")
    assert gt["gt_source"] == PP.GT_SOURCE and gt["source"] == "public_photo"
    assert gt["cutout"]["long_mm"] == pytest.approx(32.0)
    row = E.measure_sample(tmp_path / "s" / "t-1")
    assert row["accepted"], row["reason"]
    by = {d["name"]: d for d in row["dims"]}
    assert by["length"]["set_by_construction"] is True and "set_by_construction" not in by["width"]
    assert abs(by["width"]["error_mm"]) < 0.5
    assert [d["name"] for d in E.held_out(row)] == ["width"]
    exif = (tmp_path / "s" / "t-1" / "top.jpg").read_bytes()
    assert b"COMPOSITE" in exif  # the file itself says what it is


def test_summary_excludes_the_scale_dimension_and_refused_photos() -> None:
    rows = [
        {"object": "a", "photo_id": 1, "accepted": True, "reason": "", "missed": [], "dims": [
            {"name": "length", "error_mm": 9.0, "set_by_construction": True},
            {"name": "width", "error_mm": 0.2, "cutout_error_mm": 0.1},
        ]},
        {"object": "a", "photo_id": 2, "accepted": False, "reason": "x", "missed": [], "dims": [
            {"name": "width", "error_mm": 5.0},
        ]},
    ]  # fmt: skip
    s = E.summarise(rows, {"rejected": [{"object": "a", "reason": "tilted"}]})
    assert s["held_out"]["n_dims"] == 1 and s["held_out"]["mean_abs_mm"] == 0.2
    assert s["capture_gate_passed"] == 1 and s["pass_at_0_5"] == 1 and s["candidates_rejected"] == 1
    assert s["cutout_only"]["mean_abs_mm"] == 0.1


def test_scope_text_states_the_limits() -> None:
    assert "0 real photos measured" in E.SCOPE and "set_by_construction" in E.SCOPE
    assert "phone photographing a laptop screen" in E.SCOPE


def test_tracked_public_photo_files_carry_no_source_details() -> None:
    """Tracked data holds a neutral label, the object and a numeric id; never a URL, a file title or an author."""
    if not PP.MANIFEST.exists():
        pytest.skip("no manifest")
    text = PP.MANIFEST.read_text()
    assert not re.search(r"https?://|author|licen[cs]e|attribution", text, re.I)
    raw = yaml.safe_load(text)
    for s in raw["samples"]:
        assert re.fullmatch(r"p\d+\.jpg", s["photo"]) and isinstance(s["photo_id"], int)
    for p in sorted(PP.PHOTOS.glob("*.jpg")):
        from PIL import Image

        with Image.open(p) as im:
            assert not im.getexif(), f"{p.name} still has metadata"
