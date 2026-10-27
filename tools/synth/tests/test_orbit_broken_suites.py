"""Orbit clips, broken parts and red-team / control suites (all SYNTHETIC)."""

import dataclasses
import json
import shutil
from pathlib import Path

import numpy as np
import pytest

from services.metrology.mats import get_mat
from services.metrology.measure import measure_photo
from services.metrology.segment import ThresholdSegmenter
from tools.synth import SampleSpec, dataset_specs, generate_sample, load_gt, load_sample
from tools.synth import broken as B
from tools.synth import geometry as G
from tools.synth import orbit as O
from tools.synth.dataset import sample_look
from tools.synth.suites import REDTEAM, Expect, expected, figurine_mesh, orient_outward, render_redteam_case, ring_mesh

WASHER = {"outer_d": 20.0, "height": 4.0, "bore_d": 6.0, "chamfer": 0.0, "flat_count": 0.0, "flat_depth": 0.8}


def test_orbit_path_and_tiny_clip(tmp_path: Path) -> None:
    rng = np.random.default_rng(3)
    plan = dataclasses.replace(O.sample_plan(rng), duration_s=1.0, fps=6, size=(320, 180))
    assert plan.n_frames == 6
    mat = get_mat("screen-m")
    tgt = (mat.stage.x_mm + 60.0, mat.stage.y_mm + 40.0)
    cams = O.orbit_cameras(plan, tgt, rng)
    assert len(cams) == 6
    tilts = [float(np.degrees(np.arccos(c.R[2, 2]))) for c in cams]
    assert all(5.0 <= t <= 60.0 for t in tilts)
    for c in cams:  # the part stays in frame
        x, y = c.project(np.array([[tgt[0], tgt[1], 0.0]]))[0]
        assert 0 < x < 320 and 0 < y < 180
    pm = G.build_mesh(
        __import__("services.agent.templates", fromlist=["get_template"]).get_template("spacer").code, WASHER
    )
    pl = G.Placement(tgt, 0.0)
    look = sample_look("clean", "screen", "screen-m", rng)
    frames = O.render_orbit("screen-m", cams, pl.apply(pm.vertices), pm.faces, look, rng, tgt)
    enc = O.encode_mp4(frames, plan.fps, plan.size, tmp_path / "o.mp4")
    assert enc in ("ffmpeg/libx264", "opencv/avc1", "opencv/mp4v")
    back = O.read_frames(tmp_path / "o.mp4")
    assert len(back) == 6 and back[0].shape == (180, 320, 3)


def test_motion_blur_noop_and_smear() -> None:
    img = np.zeros((40, 40, 3), np.uint8)
    img[20, 20] = 255
    assert O.motion_blur(img, (0.3, 0.2)) is img
    sm = O.motion_blur(img, (12.0, 0.0))
    assert sm[20, 20].max() < 255 and sm[20, 23].max() > 0 and sm[23, 20].max() == 0


@pytest.mark.parametrize("kind", B.BREAK_KINDS)
def test_breaks_remove_material(kind: str) -> None:
    from services.agent.templates import get_template

    name = {"tip": "hook", "tab": "battery_cover", "corner": "cupboard_latch"}[kind]
    t = get_template(name)
    intact = G.build_mesh(t.code, t.defaults)
    brk = B.plan_break(kind, intact, np.random.default_rng(1))
    broken = B.broken_mesh(t.code, dict(intact.params), brk)
    hull_i = G.min_area_rect(intact.vertices[:, :2])
    assert broken.vertices.shape[0] > 0
    if kind == "tip":
        assert broken.height_mm < intact.height_mm - 1.0
    removed = B.removed_footprint(intact, brk)
    assert removed.area > 0 and 0 < B.area_ratio(removed, intact) < 1
    assert hull_i[0] > 0
    with pytest.raises(ValueError):
        B.plan_break("melted", intact, np.random.default_rng(1))


def test_broken_sample_gt_is_the_intact_part(tmp_path: Path) -> None:
    spec = SampleSpec("template", "battery_cover", "clean", views=("top",), size=(1200, 900), broken="tab")
    f = generate_sample(spec, tmp_path, seed=6)
    gt, s = load_gt(f), load_sample(f)
    assert "broken" in s.meta.intent and "broken:tab" in s.meta.augmentations and s.meta.kind == "template"
    b = gt.raw["broken"]
    assert b["kind"] == "tab" and b["removed_area_ratio"] > 0.01 and b["removed_footprint_mat_mm"]
    intact = G.build_mesh(
        __import__("services.agent.templates", fromlist=["get_template"]).get_template("battery_cover").code,
        gt.raw["params"],
    )
    assert gt.dim("length").value_mm == pytest.approx(G.top_dims(intact)["length"], abs=1e-3)
    with pytest.raises(ValueError):
        generate_sample(SampleSpec("reference_object", "id1_card", broken="tab", size=(800, 600)), tmp_path, seed=1)


def test_orbit_subset_never_changes_the_bench() -> None:
    base = dataset_specs(30, 7, n_reference=4, n_reject=2)
    more = dataset_specs(30, 7, n_reference=4, n_reject=2, n_orbit=3)
    assert more[: len(base)] == base
    assert all("orbit" in s.views for s, _ in more[len(base) :])


def test_redteam_cases_and_meshes() -> None:
    assert len(REDTEAM) == 10 and len({c.id for c in REDTEAM}) == 10
    assert {c.expect.outcome for c in REDTEAM} == {"reject", "refuse"}
    for v, f, centre in (
        (*figurine_mesh(np.random.default_rng(0)), lambda c: np.array([[0.0, 0.0, 7.0]])),
        (*ring_mesh(), None),
    ):
        assert v[:, 2].min() == pytest.approx(0.0, abs=1e-9) and f.max() < len(v)
        if centre is not None:
            f2 = orient_outward(v, f, centre)
            a, b, c = v[f2[:, 0]], v[f2[:, 1]], v[f2[:, 2]]
            n = np.cross(b - a, c - a)
            assert (np.einsum("ij,ij->i", n, (a + b + c) / 3 - np.array([0.0, 0.0, 7.0])) >= 0).all()
    assert expected({"expect": {"outcome": "refuse"}}) == Expect("refuse")
    assert expected({"expect": {"capture_gate": "reject", "check": "contrast"}}).checks == ("contrast",)
    assert expected({}).outcome == "accept"


@pytest.mark.parametrize(("case_id", "check"), [("rt-no-part", "coverage"), ("rt-wrong-mat", "markers")])
def test_redteam_photos_trip_the_gate(tmp_path: Path, case_id: str, check: str) -> None:
    case = next(c for c in REDTEAM if c.id == case_id)
    f = render_redteam_case(case, tmp_path, seed=3, size=(1600, 1200))
    s = load_sample(f)
    raw = json.loads((f / "meta.json").read_text())
    assert raw["kind"] == "redteam" and raw["origin"] == "synthetic"
    out = measure_photo(s.photos["top"], "top", segmenter=ThresholdSegmenter(), thickness_mm=3.0)
    assert not out.result.capture.passed
    assert check in [c.name for c in out.result.capture.checks if c.severity == "fail"]
    shutil.rmtree(f)
