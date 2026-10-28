from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest
from partsmith_schemas.common import Measured, Source
from partsmith_schemas.measurement import Measurements
from partsmith_schemas.partspec import BaseProfile, BrokenRegion, Family, PartSpec

from services.geom_worker.sandbox import ExecResult, WarmPool, run_program
from services.verifier.align import Rigid2D
from services.verifier.camera import CameraView
from services.verifier.synthetic import mat_placement, synthetic_camera_view, synthetic_top_measurement
from services.verifier.verify import PhotoMask, broken_region, verify

W, H = 1600, 1200
K = np.array([[1500.0, 0, W / 2], [0, 1500.0, H / 2], [0, 0, 1.0]])
A = mat_placement(100.0, 150.0, 25.0)
SAMPLES = Path(__file__).resolve().parents[3] / "data" / "synthetic" / "samples"


def look_at(cam_mm: np.ndarray, target_mm: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Camera rotation and translation (mat -> camera) looking from `cam_mm` at `target_mm` (mat z into the table)."""
    z = target_mm - cam_mm
    z /= np.linalg.norm(z)
    x = np.cross(z, np.array([0.0, 0.0, -1.0]))
    if np.linalg.norm(x) < 1e-6:
        x = np.array([1.0, 0.0, 0.0])
    x /= np.linalg.norm(x)
    y = np.cross(z, x)
    R = np.stack([x, y, z])
    return R, -R @ cam_mm


def orbit_views(r: ExecResult, n: int = 4, tilt_deg: float = 40.0, dist: float = 220.0) -> dict[str, CameraView]:
    target = np.array([100.0, 150.0, 0.0])
    out = {}
    for i in range(n):
        az = np.radians(360.0 * i / n + 10)
        el = np.radians(90.0 - tilt_deg)
        c = target + dist * np.array([np.cos(az) * np.cos(el), np.sin(az) * np.cos(el), -np.sin(el)])
        R, t = look_at(c, target)
        _, cam = synthetic_camera_view(r, K=K, R=R, t_mm=t, image_size=(W, H), part_to_mat=A)
        out[f"orbit_{i}"] = replace(cam, part_to_mat=A)  # one clip, one part frame
    return out


@pytest.fixture(scope="module")
def plate(vpool: WarmPool, plate_code: str) -> Iterator[ExecResult]:
    r = run_program(plate_code, {"thickness": 6.0}, pool=vpool, outputs=())
    r.cleanup()
    yield r


def test_orbit_frames_are_compared_and_catch_a_wrong_height(
    vpool: WarmPool, plate_code: str, plate: ExecResult
) -> None:
    meas, photo = synthetic_top_measurement(plate)
    frames = orbit_views(plate)
    out = verify(plate, {"top": meas}, None, photo_masks={"top": photo}, camera_views=frames)
    v = out.verification
    orbit = next(m for m in v.views if m.view == "orbit")
    assert v.verified, v.reasons
    assert orbit.hausdorff_mm < 0.3 and set(frames) <= set(out.views)
    assert any(s.startswith("orbit (4 frames") for s in v.reasons)
    assert "residual_orbit.png" in out.overlays

    tall = run_program(plate_code, {"thickness": 8.0}, pool=vpool, outputs=())  # 2 mm too tall
    tall.cleanup()
    bad = verify(tall, {"top": meas}, None, photo_masks={"top": photo}, camera_views=frames)
    top = next(m for m in bad.verification.views if m.view == "top")
    orbit_bad = next(m for m in bad.verification.views if m.view == "orbit")
    assert top.hausdorff_mm < 0.5  # from straight above a 2 mm height error is invisible...
    assert orbit_bad.hausdorff_mm > 0.5 and not bad.verification.verified  # ...the walk-around frames see it
    assert any("frame(s) fail" in s for s in bad.verification.reasons)


BROKEN_PLATE = """
import cadquery as cq

PARAMS = {"cut": (1.0, 0.0, 1.0, 1, "", False, "Corner broken off")}


def build(p):
    b = cq.Workplane("XY").rect(40, 20).extrude(3).faces(">Z").workplane().pushPoints([(-10, 0), (10, 0)]).hole(4.2)
    if p["cut"] > 0.5:
        b = b.cut(cq.Workplane("XY").polyline([(12, 3), (21, -6), (21, 11), (12, 11)]).close().extrude(10, both=True))
    return b


result = build({k: v[0] for k, v in PARAMS.items()})
"""


def _spec(meas: Measurements, polygon: list[tuple[float, float]]) -> PartSpec:
    return PartSpec(
        family=Family.cover, base_profile=BaseProfile(kind="polyline", points_mm=meas.outline_mm),
        thickness=Measured(value=3.0, source=Source.user_stated),
        broken_region=BrokenRegion(polygon_mm=polygon, strategy="mirror"),
    )  # fmt: skip


def test_broken_region_is_left_out_and_dimension_tests_become_informational(vpool: WarmPool) -> None:
    broken = run_program(BROKEN_PLATE, {"cut": 1}, pool=vpool, outputs=())
    intact = run_program(BROKEN_PLATE, {"cut": 0}, pool=vpool, outputs=())
    broken.cleanup()
    intact.cleanup()
    meas, photo = synthetic_top_measurement(broken, pose=replace_pose())
    # The completed outline (what a mirror completion would write): the photo's outline plus the missing corner.
    patch = [(12.0, 3.0), (21.0, -6.0), (21.0, 11.0), (12.0, 11.0)]
    T = pose_matrix()
    patch_part = [tuple(np.asarray(p) @ T[:2, :2].T + T[:2, 2]) for p in patch]

    plain = verify(intact, {"top": meas}, None, photo_masks={"top": photo}).verification
    assert not plain.verified  # the photo shows the broken corner

    out = verify(intact, {"top": meas}, _spec(meas, patch_part), photo_masks={"top": photo})
    v = out.verification
    assert v.verified, v.reasons
    assert v.views[0].hausdorff_mm < 0.3
    assert out.broken["region_mm2"] > 20 and out.broken["excluded_mm2"]["top"] > out.broken["region_mm2"]
    assert "bbox.x" in out.broken["informational_tests"]
    t = next(t for t in v.tests if t.id == "bbox.x")
    assert t.priority == "P1" and "broken region" in t.description
    holes = [t for t in v.tests if t.id.endswith(".diameter")]
    assert holes and all(t.priority == "P0" for t in holes)  # holes far from the break stay blocking
    assert any("inferred, not verified against the photo" in s for s in v.reasons)


def test_broken_region_from_a_completed_outline() -> None:
    outline = [(-20.0, -10.0), (20.0, -10.0), (20.0, 10.0), (-20.0, 10.0)]
    top = Measurements(
        view="top", origin="synthetic", outline_mm=outline, length=Measured(value=40.0), width=Measured(value=20.0),
        area_mm2=800.0,
    )  # fmt: skip
    completed = [(-20.0, -10.0), (25.0, -10.0), (25.0, 10.0), (-20.0, 10.0)]
    spec = PartSpec(family=Family.cover, base_profile=BaseProfile(kind="rect", points_mm=[(0, 0)]),
                    thickness=Measured(value=3.0), broken_region=BrokenRegion(polygon_mm=completed, strategy="mirror"))  # fmt: skip
    region, _ = broken_region(spec, top)
    assert region is not None and region.area == pytest.approx(100.0, rel=0.02)
    empty = spec.model_copy(update={"broken_region": BrokenRegion(polygon_mm=[], strategy="mirror")})
    none, info2 = broken_region(empty, top)
    assert none is None and "not located" in info2["statement"]


def replace_pose() -> Rigid2D:
    return Rigid2D(12.0, 0.8, -0.4, False)


def pose_matrix() -> np.ndarray:
    return np.asarray(replace_pose().matrix(), dtype=np.float64)


@pytest.mark.slow
def test_orbit_clip_sample_blocks_a_wrong_height(vpool: WarmPool) -> None:
    """End to end on a committed walk-around clip: metrology's orbit frames reach the verifier."""
    import yaml

    from services.agent.orchestrator import photo_field
    from services.agent.templates import get_template
    from services.metrology.measure import measure_photo
    from services.metrology.orbit import measure_orbit
    from services.metrology.segment import ThresholdSegmenter

    d = SAMPLES / "demo-knob"
    meta = json.loads((d / "meta.json").read_text())
    gt = yaml.safe_load((d / "gt.yaml").read_text())  # ground truth: used by this test only
    t = get_template(gt["template"])
    params = {k: v for k, v in gt["params"].items() if k in t.defaults}
    h = float(meta["user_thickness_mm"])
    mo = measure_photo((d / "top.jpg").read_bytes(), "top", segmenter=ThresholdSegmenter(), thickness_mm=h)
    assert mo.result.measurements is not None and mo.detection is not None and mo.photo_mask is not None
    assert mo.K is not None and mo.R is not None and mo.t_mm is not None and mo.part_to_mat is not None
    hh, ww = mo.photo_mask.shape
    top_cam = CameraView(
        K=mo.K, R=mo.R, t_mm=mo.t_mm, image_mask=mo.photo_mask, image_field=photo_field(mo),
        part_to_mat=mo.part_to_mat, px_per_mm_local=float(mo.top_px_per_mm or 4.0), image_size=(ww, hh),
        dist=mo.detection.dist, top_height_mm=h, H_ground=mo.detection.H,
    )  # fmt: skip
    orb = measure_orbit((d / "orbit.mp4").read_bytes(), None, segmenter=ThresholdSegmenter())
    assert orb.part_to_mat is not None and len(orb.frames) >= 4
    cams = {"top": top_cam, **{f"orbit_{i}": CameraView(**f.camera_view_kwargs(orb.part_to_mat))
                               for i, f in enumerate(orb.frames)}}  # fmt: skip
    meas = {"top": mo.result.measurements}
    for height, should_pass in ((params["height"], True), (params["height"] + 2.0, False)):
        r = run_program(t.code, {**params, "height": height}, pool=vpool, outputs=())
        r.cleanup()
        v = verify(r, meas, None, camera_views=cams).verification
        orbit = next(m for m in v.views if m.view == "orbit")
        assert (orbit.hausdorff_mm <= 0.5) is should_pass, v.reasons
        if not should_pass:
            assert not v.verified


def test_broken_sample_verifies_outside_the_break(vpool: WarmPool) -> None:
    import yaml

    from services.agent.templates import get_template
    from services.metrology.measure import measure_photo
    from services.metrology.segment import ThresholdSegmenter

    d = SAMPLES / "demo-broken-latch-corner"
    meta = json.loads((d / "meta.json").read_text())
    gt = yaml.safe_load((d / "gt.yaml").read_text())  # ground truth: used by this test only
    t = get_template(gt["template"])
    params = {k: v for k, v in gt["params"].items() if k in t.defaults}
    mo = measure_photo((d / "top.jpg").read_bytes(), "top", segmenter=ThresholdSegmenter(),
                       thickness_mm=float(meta["user_thickness_mm"]))  # fmt: skip
    m = mo.result.measurements
    assert m is not None
    inv = np.linalg.inv(np.asarray(m.part_to_mat))
    removed = np.asarray(gt["broken"]["removed_footprint_mat_mm"]) @ inv[:2, :2].T + inv[:2, 2]
    r = run_program(t.code, params, pool=vpool, outputs=())  # the intact replacement
    r.cleanup()
    plain = verify(r, {"top": m}, None).verification
    out = verify(r, {"top": m}, _spec(m, [tuple(p) for p in removed]))
    v = out.verification
    assert plain.views[0].hausdorff_mm > 2.0  # the photo shows the broken corner
    assert v.views[0].hausdorff_mm < 0.5 and v.views[0].mean_mm < 0.15
    assert {"bbox.x", "bbox.y"} <= set(out.broken["informational_tests"])
    assert all(t.priority == "P1" for t in v.tests if t.id in ("bbox.x", "bbox.y"))
    # their residuals compare the intact model with the broken photo: reported apart, never in the max error
    assert not any(r.feature_id == "outline" for r in v.residuals)
    assert {r["quantity"] for r in out.broken["informational_residuals"]} == {"length", "width"}


POST_PLATE = """
import cadquery as cq

PARAMS = {
    "post_h": (17.0, 1.0, 40.0, 0.1, "mm", True, "Post height above the plate"),
    "post_x": (12.0, -15.0, 15.0, 0.1, "mm", True, "Post position"),
}


def build(p):
    plate = cq.Workplane("XY").rect(40, 20).extrude(3)
    post = cq.Workplane("XY").workplane(offset=3).center(p["post_x"], 0).rect(8, 8).extrude(p["post_h"])
    return plate.union(post)


result = build({k: v[0] for k, v in PARAMS.items()})
"""


def _side_measurement(r: ExecResult, ppm: float = 20.0) -> tuple[Measurements, PhotoMask]:
    """Rectified side "photo" of a model (side_xz silhouette, exact): the short side is its height."""
    from services.verifier.render import Frame, project, silhouette

    assert r.mesh is not None
    v, f = r.mesh.vertices, r.mesh.faces
    pose = Rigid2D(5.0, 2.0, -1.0, False)
    frame = Frame.around(pose.apply(project(v, "side_xz")), ppm, margin_mm=4.0)
    mask = silhouette(v, f, "side_xz", frame, transform=pose.matrix())
    lo, hi = v.min(axis=0), v.max(axis=0)
    length, height = float(hi[0] - lo[0]), float(hi[2] - lo[2])
    meas = Measurements(
        view="side", origin="synthetic", outline_mm=[(-length / 2, -height / 2), (length / 2, -height / 2),
                                                     (length / 2, height / 2), (-length / 2, height / 2)],
        length=Measured(value=length), width=Measured(value=height), area_mm2=float(mask.sum()) / ppm**2,
    )  # fmt: skip
    return meas, PhotoMask(mask, frame)


def test_a_missing_top_is_left_out_of_the_side_view_only(vpool: WarmPool) -> None:
    """The top of the post snapped off: the side photo shows a 15 mm stump of a 20 mm part. The intact model is
    compared below the break; the side height becomes informational and leaves the max error; an intact model with
    the post in the wrong place still fails."""

    def build(post_h: float, post_x: float = 12.0) -> ExecResult:
        r = run_program(POST_PLATE, {"post_h": post_h, "post_x": post_x}, pool=vpool, outputs=())
        r.cleanup()
        return r

    broken, intact, wrong = build(12.0), build(17.0), build(17.0, 4.0)
    top_m, top_p = synthetic_top_measurement(broken, pose=replace_pose())
    side_m, side_p = _side_measurement(broken)
    meas, masks = {"top": top_m, "side": side_m}, {"top": top_p, "side": side_p}
    spec = PartSpec(
        family=Family.hook, base_profile=BaseProfile(kind="polyline", points_mm=top_m.outline_mm),
        thickness=Measured(value=3.0, source=Source.user_stated),
        broken_region=BrokenRegion(polygon_mm=[], strategy="template", kind="height"),
    )  # fmt: skip

    plain = verify(intact, meas, None, photo_masks=masks).verification
    side_plain = next(m for m in plain.views if m.view == "side")
    assert side_plain.hausdorff_mm > 4.0 and not plain.verified  # the photo shows the stump

    out = verify(intact, meas, spec, photo_masks=masks)
    v = out.verification
    assert v.verified, v.reasons
    assert out.broken["kind"] == "height" and out.broken["break_height_mm"] == pytest.approx(15.0, abs=0.1)
    assert "side.thickness" in out.broken["informational_tests"] and "top" not in out.broken["excluded_mm2"]
    assert not any(r.feature_id == "side" for r in v.residuals)  # 20 mm model vs 15 mm stump: not a residual
    (row,) = out.broken["informational_residuals"]
    assert row["model_mm"] == pytest.approx(20.0, abs=0.2) and row["measured_mm"] == pytest.approx(15.0, abs=0.1)
    assert v.max_error_mm is not None and v.max_error_mm < 0.5
    assert any("top of the part is broken off" in s for s in v.reasons)

    bad = verify(wrong, meas, spec, photo_masks=masks).verification
    assert not bad.verified  # below the break and from above, the misplaced post is still seen


def test_a_notch_in_an_end_makes_only_the_length_informational() -> None:
    """A piece missing from the middle of an end: the length is measured on the broken end, the width is not."""
    from shapely.geometry import box

    from services.verifier.part_tests import evaluate_tests, generate_tests
    from services.verifier.verify import _broken_tests

    outline = [(-20.0, -10.0), (20.0, -10.0), (20.0, -4.0), (14.0, -4.0), (14.0, 4.0), (20.0, 4.0), (20.0, 10.0),
               (-20.0, 10.0)]  # fmt: skip
    top = Measurements(view="top", origin="synthetic", outline_mm=outline, length=Measured(value=40.0),
                       width=Measured(value=20.0), area_mm2=752.0)  # fmt: skip
    tests = evaluate_tests(generate_tests(None, {"top": top}), {"bbox.x": 40.0, "bbox.y": 20.0})
    out, informational = _broken_tests(tests, box(14.0, -4.0, 20.0, 4.0), {"top": top})
    assert informational == ["bbox.x"]
    assert next(t for t in out if t.id == "bbox.y").priority == "P0"
