"""SYNTHETIC sample generation: determinism, folder contract, and render → measure → close to the exact GT."""

import io
import json
from pathlib import Path

import pytest
from PIL import Image

from services.metrology.measure import measure_photo
from services.metrology.segment import ThresholdSegmenter
from tools.synth import (
    PRESETS,
    SampleSpec,
    dataset_specs,
    generate_sample,
    list_samples,
    load_gt,
    load_sample,
    make_dataset,
)
from tools.synth.dataset import ruler_thickness, sample_params

SMALL = (1200, 900)
META_KEYS = {
    "id",
    "title",
    "kind",
    "origin",
    "mat_id",
    "family_hint",
    "intent",
    "user_thickness_mm",
    "difficulty",
    "augmentations",
    "seed",
}


def test_generation_is_deterministic(tmp_path: Path) -> None:
    spec = SampleSpec("template", "cupboard_latch", "clean", size=SMALL, views=("top",))
    a = generate_sample(spec, tmp_path / "a", seed=5)
    b = generate_sample(spec, tmp_path / "b", seed=5)
    for name in ("top.jpg", "meta.json", "gt.yaml"):
        assert (a / name).read_bytes() == (b / name).read_bytes(), name
    c = generate_sample(spec, tmp_path / "c", seed=6)
    assert (c / "top.jpg").read_bytes() != (a / "top.jpg").read_bytes()


def test_folder_contract_and_no_gt_leak(tmp_path: Path) -> None:
    folder = generate_sample(SampleSpec("template", "clip", "paper", size=SMALL), tmp_path, seed=3)
    meta = json.loads((folder / "meta.json").read_text())
    assert set(meta) == META_KEYS
    assert meta["origin"] == "synthetic" and meta["kind"] == "template" and meta["mat_id"] == "paper-a4"
    assert meta["family_hint"] == "clip" and meta["difficulty"] == "easy"
    s = load_sample(folder)
    assert set(s.photos) == {"top", "side"} and s.meta.id == folder.name
    gt = load_gt(folder)
    assert gt.gt_source == "synthetic_exact" and gt.raw["template"] == "clip"
    # what an agent sees (meta + photos) carries no exact dimension
    assert "length" not in (folder / "meta.json").read_text()
    names = {d.name for d in gt.dims}
    assert {"length", "width", "thickness"} <= names and any(n.startswith("hole_") for n in names)
    assert gt.raw["params"]["length"] > 0 and set(gt.raw["views"]) == {"top", "side"}
    cam = gt.raw["views"]["top"]["camera"]
    assert len(cam["K"]) == 3 and len(cam["R"]) == 3 and len(cam["t_mm"]) == 3
    assert 220.0 <= cam["height_mm"] <= 430.0 and cam["tilt_deg"] <= 8.5
    # a phone-like EXIF focal length is embedded, and the photo says it is synthetic
    with Image.open(io.BytesIO(s.photos["top"])) as im:
        exif = im.getexif()
        assert exif.get_ifd(0x8769).get(0xA405) == cam["exif_focal35_mm"]
        assert "SYNTHETIC" in str(exif.get(0x010E))
        assert im.size == SMALL
    assert [m.id for m in list_samples(tmp_path)] == [folder.name]


def test_reference_object_sample(tmp_path: Path) -> None:
    folder = generate_sample(SampleSpec("reference_object", "aa_cell", "clean", size=SMALL), tmp_path, seed=1)
    s = load_sample(folder)
    assert set(s.photos) == {"top"}  # a battery lying down has no separate side view
    gt = load_gt(folder)
    assert gt.raw["spec"]["loose"] is True and gt.kind == "reference_object"
    assert gt.dim("length", "top").value_mm == pytest.approx(50.5, abs=0.01)  # type: ignore[union-attr]
    assert gt.dim("width", "top").value_mm == pytest.approx(14.5, abs=0.01)  # type: ignore[union-attr]


def test_dataset_specs_cover_templates_and_presets() -> None:
    from services.agent.templates import list_templates

    specs = dataset_specs(40, 7, n_reference=8)
    assert specs == dataset_specs(40, 7, n_reference=8)
    names = {s.name for s, _ in specs if s.kind == "template"}
    assert names == {t.name for t in list_templates()}
    assert {s.preset for s, _ in specs if s.kind == "template"} == set(PRESETS)
    refs = [s.name for s, _ in specs if s.kind == "reference_object"]
    assert len(refs) == 8 and len(set(refs)) == 4
    assert len({seed for _, seed in specs}) == len(specs)
    with pytest.raises(ValueError):
        dataset_specs(2, 1, ["sunny"])


def test_sample_params_stay_in_range() -> None:
    import numpy as np

    from services.agent.templates import get_template

    t = get_template("hinge_leaf")
    for seed in range(5):
        p = sample_params("hinge_leaf", np.random.default_rng(seed))
        for spec in t.params:
            assert spec.min <= p[spec.name] <= spec.max
    assert ruler_thickness(1.6) == 1.5 and ruler_thickness(0.2) == 0.5 and ruler_thickness(2.8) == 3.0


def test_make_dataset_manifest(tmp_path: Path) -> None:
    man = make_dataset(tmp_path, n=1, seed=3, presets=["clean"], size=(800, 600))
    assert len(man["samples"]) == 1 and not man["failures"]
    entry = man["samples"][0]
    assert set(entry["files"]) >= {"top.jpg", "meta.json", "gt.yaml"}
    assert json.loads((tmp_path / "manifest.json").read_text())["dataset_sha256"] == man["dataset_sha256"]


# a true prism (vertical walls, flat bottom) with a through hole: the metrology's height model holds exactly
WASHER = {"outer_d": 20.0, "height": 4.0, "bore_d": 6.0, "chamfer": 0.0, "flat_count": 0.0, "flat_depth": 0.8}


@pytest.mark.parametrize(
    ("kind", "name", "mat", "params"),
    [
        ("reference_object", "id1_card", "screen-m", None),
        ("template", "spacer", "screen-l", WASHER),
        ("reference_object", "sd_card", "paper-a4", None),
    ],
)
def test_render_then_measure_is_close_to_exact_gt(
    tmp_path: Path, kind: str, name: str, mat: str, params: dict[str, float] | None
) -> None:
    """Clean preset, prismatic part: the metrology recovers the exact GT within 0.3 mm (holes matched by centre)."""
    spec = SampleSpec(kind, name, "clean", params=params, mat_id=mat, size=(2400, 1800), views=("top",))  # type: ignore[arg-type]
    folder = generate_sample(spec, tmp_path, seed=11)
    s, gt = load_sample(folder), load_gt(folder)
    out = measure_photo(s.photos["top"], "top", segmenter=ThresholdSegmenter(), thickness_mm=s.meta.user_thickness_mm)
    m = out.result.measurements
    assert out.result.capture.passed, out.result.capture.retake_reason
    assert m is not None
    assert m.length.value == pytest.approx(gt.dim("length").value_mm, abs=0.3)  # type: ignore[union-attr]
    assert m.width.value == pytest.approx(gt.dim("width").value_mm, abs=0.3)  # type: ignore[union-attr]
    from eval.measure_only import score_measurements

    gts = [{"name": d.name, "value_mm": d.value_mm, "center_mat_mm": d.center_mat_mm} for d in gt.dims_for("top")]
    pairs, missed, extra = score_measurements(m, gts, "top")
    assert not missed and extra == 0
    assert len(pairs) == len(gts) and (params is None or len(gts) == 3)
    for g, val in pairs:
        assert abs(val - g["value_mm"]) < 0.3, g["name"]
