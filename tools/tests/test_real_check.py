"""Photo-day tooling, proven on the tracked synthetic samples before any real photo exists (temp dirs only)."""

from __future__ import annotations

import io
import json
from pathlib import Path

import cv2
import numpy as np
import pytest
import yaml
from PIL import Image

from services.common.images import exif_orientation
from services.metrology.calibrate import exif_focal35_mm
from tools import real_check as RC

SAMPLES = Path(__file__).resolve().parents[2] / "data" / "synthetic" / "samples"
GPS_IFD = 0x8825


def with_exif(jpeg: bytes, *, orientation: int = 6, focal35: int = 26) -> bytes:
    """The same JPEG with a phone-like EXIF block spliced in (no re-encode): GPS, make, date, orientation, focal."""
    ex = Image.Exif()
    ex[RC.ORIENTATION_TAG] = orientation
    ex[0x010F] = "PhoneMaker"  # Make
    ex[0x0132] = "2026:11:04 10:00:00"  # DateTime
    ex.get_ifd(RC.EXIF_IFD).update({0xA405: focal35, 0x920A: 4.25, 0xA431: "SERIAL123"})
    ex.get_ifd(GPS_IFD).update({1: "N", 2: (12.0, 58.0, 0.0)})
    payload = b"Exif\x00\x00" + ex.tobytes()
    app1 = b"\xff\xe1" + (len(payload) + 2).to_bytes(2, "big") + payload
    return b"\xff\xd8" + app1 + jpeg[2:]


def raw_pixels(data: bytes) -> np.ndarray:
    """Stored pixels, orientation NOT applied (to compare scans byte-for-byte after a lossless strip)."""
    img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR | cv2.IMREAD_IGNORE_ORIENTATION)
    assert img is not None
    return img


def gt_of(sample: str) -> str:
    """A ruler-style gt.yaml with the synthetic sample's own top-view values (rounded like a ruler reading)."""
    raw = yaml.safe_load((SAMPLES / sample / "gt.yaml").read_text())
    meta = json.loads((SAMPLES / sample / "meta.json").read_text())
    top = {d["name"]: d["value_mm"] for d in raw["dims"] if d["view"] == "top"}
    side = [d["value_mm"] for d in raw["dims"] if d["view"] == "side" and d["name"] == "thickness"]
    dims = {"length": round(top["length"], 1), "width": round(top["width"], 1)}
    if side:
        dims["thickness"] = round(side[0], 1)
    holes = [{"diameter": round(v, 1)} for k, v in top.items() if k.startswith("hole_")]
    doc = {"gt_source": "ruler", "uncertainty_mm": 0.5, "user_thickness_mm": meta["user_thickness_mm"], "dims": dims,
           "holes": holes}  # fmt: skip
    return yaml.safe_dump(doc, sort_keys=False)


@pytest.fixture
def exports(tmp_path: Path) -> Path:
    """A loose folder like a phone export: named photos, one with phone EXIF, a HEIC, an unnamed file."""
    src = tmp_path / "exports"
    src.mkdir()
    (src / "l-bracket_top.jpg").write_bytes(with_exif((SAMPLES / "demo-l-bracket" / "top.jpg").read_bytes()))
    (src / "l-bracket_side.jpg").write_bytes((SAMPLES / "demo-l-bracket" / "side.jpg").read_bytes())
    (src / "id1_card_top_1.jpg").write_bytes((SAMPLES / "demo-ref-id1-card" / "top.jpg").read_bytes())
    (src / "knob_top.heic").write_bytes(b"\x00\x00\x00\x18ftypheic\x00\x00\x00\x00mif1heic")
    (src / "IMG_1234.jpg").write_bytes((SAMPLES / "demo-knob" / "top.jpg").read_bytes())
    return src


def test_intake_lays_out_parts_and_strips_private_exif_losslessly(exports: Path, tmp_path: Path) -> None:
    root = tmp_path / "real"
    rep = RC.intake(exports, root)
    by = {(i.part, i.view): i for i in rep.items}
    assert by[("l-bracket", "top")].action == "written" and by[("l-bracket", "top")].note == "lossless"
    assert by[("knob", "top")].action == "error" and "HEIC" in by[("knob", "top")].note
    assert rep.unmatched == ["IMG_1234.jpg"] and not rep.ok
    assert (root / "reference_objects" / "id1_card" / "top_1.jpg").is_file()
    assert sorted(p.name for p in (root / "l-bracket").iterdir()) == ["gt.yaml", "side.jpg", "top.jpg"]

    src = (exports / "l-bracket_top.jpg").read_bytes()
    out = (root / "l-bracket" / "top.jpg").read_bytes()
    with Image.open(io.BytesIO(out)) as im:
        ex = im.getexif()
        assert GPS_IFD not in ex and 0x010F not in ex and 0x0132 not in ex
        assert 0xA431 not in ex.get_ifd(RC.EXIF_IFD)
    assert exif_orientation(out) == 6  # kept: every decode applies it, like the /fix upload
    assert exif_focal35_mm(out) == 26.0  # kept: camera intrinsics are estimated from it
    assert np.array_equal(raw_pixels(out), raw_pixels(src))  # same scans, no re-encode
    assert b"PhoneMaker" not in out and b"SERIAL123" not in out

    tmpl = yaml.safe_load((root / "l-bracket" / "gt.yaml").read_text())
    assert tmpl["gt_source"] == "ruler" and tmpl["dims"]["length"] == "TODO"


def test_intake_never_overwrites_gt_yaml_and_skips_what_it_already_has(exports: Path, tmp_path: Path) -> None:
    root = tmp_path / "real"
    RC.intake(exports, root)
    gt = root / "l-bracket" / "gt.yaml"
    gt.write_text(gt_of("demo-l-bracket"))
    before = gt.read_text()
    again = RC.intake(exports, root, force=True)
    assert gt.read_text() == before and str(gt) in again.kept_gt and not again.templates
    ref = next(i for i in again.items if i.part == "id1_card")
    assert ref.action == "skipped" and ref.note == "already imported"  # same bytes already there, even with --force
    plain = RC.intake(exports, root)
    assert {i.action for i in plain.items if i.part == "l-bracket"} == {"skipped"}
    assert len(list((root / "reference_objects" / "id1_card").glob("*.jpg"))) == 1


def test_intake_reads_parts_csv_and_reencodes_upright_on_request(tmp_path: Path) -> None:
    src = tmp_path / "exports"
    src.mkdir()
    (src / "IMG_0001.jpg").write_bytes(with_exif((SAMPLES / "demo-knob" / "top.jpg").read_bytes(), orientation=6))
    (src / "IMG_0002.jpg").write_bytes((SAMPLES / "demo-knob" / "side.jpg").read_bytes())
    (src / "parts.csv").write_text("file,part,view\nIMG_0001.jpg,Oven Knob,top\nIMG_0002.jpg,oven knob,side\n")
    root = tmp_path / "real"
    rep = RC.intake(src, root, reencode=True)
    assert rep.ok and {i.dest for i in rep.items} == {str(root / "oven-knob" / f"{v}.jpg") for v in ("top", "side")}
    out = (root / "oven-knob" / "top.jpg").read_bytes()
    with Image.open(io.BytesIO(out)) as im:
        assert im.format == "JPEG" and im.size == (1500, 2000)  # 2000 x 1500 stored, rotated upright
        assert GPS_IFD not in im.getexif()
    assert exif_orientation(out) == 1 and exif_focal35_mm(out) == 26.0


def test_check_passes_a_good_part_and_flags_what_to_fix(exports: Path, tmp_path: Path) -> None:
    root = tmp_path / "real"
    RC.intake(exports, root)
    (root / "l-bracket" / "gt.yaml").write_text(gt_of("demo-l-bracket"))
    bad = root / "no-mat"
    bad.mkdir()
    cv2.imwrite(str(bad / "top.jpg"), np.full((900, 1200, 3), 128, np.uint8))  # no markers at all
    (bad / "gt.yaml").write_text(RC.GT_TEMPLATE.format(part="no-mat"))

    reps = {r.name: r for r in RC.check_all(root, part_check=False)}
    good = reps["l-bracket"]
    assert good.usable and good.gt_ok, good.issues
    top = next(p for p in good.photos if p.view == "top")
    assert top.gate_passed and top.markers == top.markers_total == 24 and top.exif_orientation == 6
    assert top.tilt_deg is not None and top.tilt_deg < 15
    assert reps["reference_objects/id1_card"].usable

    nomat = reps["no-mat"]
    assert not nomat.usable and nomat.gt_ok is False
    msgs = [(i.level, i.where, i.message, i.fix) for i in nomat.issues]
    assert any(lv == "error" and w == "top" and "markers" in m and f == "retake top" for lv, w, m, f in msgs)
    assert any(lv == "error" and w == "gt.yaml" and "TODO" in m for lv, w, m, _ in msgs)

    table = RC.render_table(list(reps.values()))
    assert "UNUSABLE" in table and "24/24" in table and "retake top" in table


def test_check_cli_exit_code_and_json(exports: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    root = tmp_path / "real"
    assert RC.main(["check", "--root", str(root)]) == 0  # nothing yet is not an error
    RC.intake(exports, root)
    assert RC.main(["check", "--root", str(root), "--json", "--no-part-check"]) == 1  # gt.yaml still has TODOs
    out = json.loads(capsys.readouterr().out.split("\n", 1)[1])
    assert out["summary"]["unusable"] == ["l-bracket"]
    (root / "l-bracket" / "gt.yaml").write_text(gt_of("demo-l-bracket"))
    assert RC.main(["check", "--root", str(root), "--no-part-check"]) == 0


def test_side_photo_the_job_would_drop_is_a_warning_and_heic_is_named(tmp_path: Path) -> None:
    d = tmp_path / "real" / "battery-cover"
    d.mkdir(parents=True)
    (d / "top.jpg").write_bytes((SAMPLES / "demo-battery-cover" / "top.jpg").read_bytes())
    (d / "side.jpg").write_bytes((SAMPLES / "demo-battery-cover" / "side.jpg").read_bytes())  # screen moiré
    (d / "context.heic").write_bytes(b"\x00\x00\x00\x18ftypheic\x00\x00\x00\x00mif1heic")
    (d / "gt.yaml").write_text(gt_of("demo-battery-cover"))
    rep = RC.check_part(d, part_check=False)
    assert rep.usable, rep.issues
    side = [i for i in rep.issues if i.where == "side" and "capture gate" in i.message]
    assert side and side[0].level == "warn" and "drop" in side[0].message and side[0].fix == "retake side"
    assert any("context.heic" in i.message and "JPEG" in i.fix for i in rep.issues)


def test_part_check_finds_the_part_and_catches_a_gross_ruler_typo(tmp_path: Path) -> None:
    d = tmp_path / "real" / "cupboard-latch"
    d.mkdir(parents=True)
    (d / "top.jpg").write_bytes((SAMPLES / "demo-cupboard-latch" / "top.jpg").read_bytes())
    doc = yaml.safe_load(gt_of("demo-cupboard-latch"))
    (d / "gt.yaml").write_text(yaml.safe_dump(doc))
    ok = RC.check_part(d)
    assert ok.usable and not [i for i in ok.issues if "rough check" in i.message], ok.issues
    assert ok.photos[0].rough_mm["length"] == pytest.approx(doc["dims"]["length"], abs=1.0)
    doc["dims"]["length"] = round(doc["dims"]["length"] / 10, 1)  # cm typed as mm
    (d / "gt.yaml").write_text(yaml.safe_dump(doc))
    typo = RC.check_part(d)
    assert typo.usable  # advisory: the threshold mask is not the product's segmenter
    assert any(i.where == "gt.yaml" and "dims.length" in i.message and "rough" in i.message for i in typo.issues)


@pytest.mark.parametrize(
    ("doc", "level", "needle"),
    [
        ({"gt_source": "caliper"}, "error", "gt_source"),
        ({"uncertainty_mm": None}, "error", "uncertainty_mm must be a positive"),
        ({"dims": {"length": 420.0, "width": 18.5, "thickness": 3.0}}, "warn", "over 300"),
        ({"dims": {"length": 0.4, "width": 0.3, "thickness": 3.0}}, "warn", "under 1"),
        ({"dims": {"length": 18.0, "width": 42.0, "thickness": 3.0}}, "warn", "length is the longer side"),
        ({"dims": {"width": 18.5}}, "error", "dims.length is missing"),
        ({"user_thickness_mm": 6.0}, "warn", "plate cannot be thicker"),
        ({"user_thickness_mm": None}, "warn", "no user_thickness_mm"),
        ({"holes": [{"d": 4.0}]}, "error", "holes[0]"),
        ({"holes": {"diameter": 4.0}}, "error", "holes must be a list"),
        ({"mat_id": "screen-xx"}, "error", "unknown mat"),
    ],
)
def test_gt_yaml_rules(doc: dict[str, object], level: str, needle: str, tmp_path: Path) -> None:
    base: dict[str, object] = {
        "gt_source": "ruler",
        "uncertainty_mm": 0.5,
        "user_thickness_mm": 3.0,
        "dims": {"length": 42.0, "width": 18.5, "thickness": 3.0},
        "holes": [{"diameter": 4.0}],
    }
    p = tmp_path / "gt.yaml"
    p.write_text(yaml.safe_dump(base))
    clean = RC.FolderReport(name="x", kind="part", path=str(tmp_path))
    RC.check_gt(p, clean)
    assert clean.gt_ok and not clean.issues
    p.write_text(yaml.safe_dump({**base, **doc}))
    rep = RC.FolderReport(name="x", kind="part", path=str(tmp_path))
    RC.check_gt(p, rep)
    hits = [i for i in rep.issues if needle in i.message]
    assert hits and hits[0].level == level, rep.issues
    assert rep.gt_ok is (level != "error")
