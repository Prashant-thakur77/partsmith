from __future__ import annotations

from collections.abc import Iterator

import cv2
import numpy as np
import pytest
from partsmith_schemas.common import DataOrigin, Measured
from partsmith_schemas.measurement import Measurements, ViewKind

from services.geom_worker.sandbox import ExecResult, WarmPool, run_program
from services.verifier.align import Rigid2D
from services.verifier.camera import CameraView, cad_to_mat_from_alignment
from services.verifier.render import placement_matrix
from services.verifier.synthetic import mat_placement, synthetic_camera_view
from services.verifier.verify import verify

W, H = 3000, 4000
K = np.array([[3200.0, 0, W / 2], [0, 3200.0, H / 2], [0, 0, 1.0]])
R, _ = cv2.Rodrigues(np.array([0.30, -0.15, 0.05]))  # a phone held at ~20 deg
T = -R @ np.array([110.0, 160.0, -260.0])  # ~26 cm above the mat
A = mat_placement(100.0, 150.0, 30.0)


@pytest.fixture(scope="module")
def thick(vpool: WarmPool, plate_code: str) -> Iterator[ExecResult]:
    r = run_program(plate_code, {"thickness": 8.0}, pool=vpool, outputs=())
    yield r
    r.cleanup()


def _posed(r: ExecResult, height: float | None) -> tuple[Measurements, CameraView]:
    return synthetic_camera_view(r, K=K, R=R, t_mm=T, image_size=(W, H), part_to_mat=A, top_height_mm=height)


def test_top_placement_matches_the_frame_convention() -> None:
    v = np.array([[0.0, 0, 0], [10, 0, 5]])
    P = cad_to_mat_from_alignment(v, "top", np.eye(3), mat_placement(12.0, 7.0, 25.0))
    assert np.allclose(P, placement_matrix(12.0, 7.0, 25.0))
    Pm = cad_to_mat_from_alignment(v, "top", Rigid2D(10.0, 1.0, 2.0, mirror=True).matrix(), A)
    assert np.linalg.det(Pm[:3, :3]) == pytest.approx(1.0)  # upside down, still a rigid motion
    placed = v @ Pm[:3, :3].T + Pm[:3, 3]
    assert placed[:, 2].max() == pytest.approx(0.0) and placed[:, 2].min() == pytest.approx(-5.0)


def test_thick_part_in_photo_frame(vpool: WarmPool, plate_code: str, thick: ExecResult) -> None:
    meas, cam = _posed(thick, 8.0)
    out = verify(thick, {"top": meas}, None, camera_views={"top": cam})
    v = out.verification
    assert out.views["top"].frame == "camera"
    assert v.verified, v.reasons
    assert v.views[0].hausdorff_mm < 0.15 and v.views[0].iou > 0.99
    assert out.model_values["cad.length"] == pytest.approx(40.0, abs=1e-6)
    assert out.model_values["cad.hole:hole_1.diameter"] == pytest.approx(4.2)
    assert any("like for like" in s for s in v.reasons)
    assert cv2.imdecode(np.frombuffer(out.overlays["residual_top.png"], np.uint8), cv2.IMREAD_COLOR) is not None

    for delta in (1.0, -1.0):
        r = run_program(plate_code, {"thickness": 8.0, "length": 40.0 + delta}, pool=vpool, outputs=())
        r.cleanup()
        pv = verify(r, {"top": meas}, None, camera_views={"top": cam}).verification
        length = next(x for x in pv.residuals if x.quantity == "length")
        assert not pv.verified and length.delta_mm == pytest.approx(delta, abs=0.1)

    r = run_program(plate_code, {"thickness": 8.0, "hole_d": 4.6}, pool=vpool, outputs=())
    r.cleanup()
    hv = verify(r, {"top": meas}, None, camera_views={"top": cam}).verification
    d = [x for x in hv.residuals if x.quantity == "diameter"]
    assert len(d) == 2 and all(x.delta_mm == pytest.approx(0.4, abs=0.08) for x in d)


def test_like_for_like_cancels_parallax(thick: ExecResult) -> None:
    """Without a height correction the photo over-measures the 8 mm part; comparing CAD dims fails, the camera-frame
    like-for-like comparison does not."""
    meas, cam = _posed(thick, None)
    assert meas.length.value > 40.3  # the parallax bias the rectified comparison cannot explain
    rect = verify(thick, {"top": meas}, None).verification
    assert not rect.verified
    posed = verify(thick, {"top": meas}, None, camera_views={"top": cam}).verification
    assert posed.verified, posed.reasons
    length = next(x for x in posed.residuals if x.quantity == "length")
    assert abs(length.delta_mm) < 0.1


def _side(length: float, height: float) -> Measurements:
    return Measurements(
        view=ViewKind.side, origin=DataOrigin.synthetic,
        outline_mm=[(-length / 2, 0), (length / 2, 0), (length / 2, height), (-length / 2, height)],
        length=Measured(value=length), width=Measured(value=height), area_mm2=length * height,
    )  # fmt: skip


@pytest.fixture(scope="module")
def thin(vpool: WarmPool, plate_code: str) -> Iterator[ExecResult]:
    r = run_program(plate_code, {"thickness": 1.5}, pool=vpool, outputs=())
    yield r
    r.cleanup()


def test_thin_side_view_is_gated_on_hausdorff_and_thickness(thin: ExecResult) -> None:
    out = verify(thin, {"side": _side(40.0, 1.6)}, None)
    v = out.verification
    sv = v.views[0]
    assert sv.iou < 0.97 and sv.hausdorff_mm < 0.5  # a 0.1 mm error on a 1.5 mm profile
    assert out.view_gates["side"] == ["hausdorff", "thickness_test"]
    assert v.verified, v.reasons
    assert any("not gated" in s for s in v.reasons)
    t = next(x for x in v.tests if x.id == "side.thickness")
    assert t.passed and t.value == pytest.approx(1.5)

    bad = verify(thin, {"side": _side(40.0, 2.0)}, None).verification
    assert not bad.verified
    assert not next(x for x in bad.tests if x.id == "side.thickness").passed


def test_wide_side_view_still_gates_iou(vpool: WarmPool) -> None:
    code = "import cadquery as cq\nresult = cq.Workplane('XY').box(40, 20, 12, centered=(True, True, False))\n"
    r = run_program(code, pool=vpool, outputs=())
    r.cleanup()
    out = verify(r, {"side": _side(40.4, 12.28)}, None)
    v = out.verification
    assert out.view_gates["side"] == ["hausdorff", "iou"]
    assert v.views[0].iou < 0.97 and v.views[0].hausdorff_mm < 0.5
    assert next(x for x in v.tests if x.id == "side.thickness").passed
    assert not v.verified


def test_see_through_bore_of_a_tall_part_is_found(vpool: WarmPool) -> None:
    """A 10 mm tall spacer: its bore shows the mat only through a lens; both sides must still find hole_1."""
    from services.agent.templates import get_template

    t = get_template("spacer")
    r = run_program(t.code, t.defaults, pool=vpool, outputs=())
    r.cleanup()
    # 50 mm from the camera nadir the bore's top and bottom openings shift ~1.8 mm apart in the photo.
    meas, cam = synthetic_camera_view(
        r, K=K, R=R, t_mm=T, image_size=(W, H), part_to_mat=mat_placement(80.0, 130.0, 30.0), top_height_mm=10.0
    )
    assert len(meas.holes) == 1
    v = verify(r, {"top": meas}, None, camera_views={"top": cam}).verification
    test = next(x for x in v.tests if x.id == "hole_1.diameter")
    assert test.passed and test.value is not None, v.reasons
    assert v.verified, v.reasons


def test_tall_thin_side_view_keeps_the_height_correction(vpool: WarmPool) -> None:
    """A 2.5 mm plate lying on its 25 mm edge: the corrected side outline keeps only a small share of the photo's
    outline, which the metrology accepts for side views; the model side must do the same."""
    code = "import cadquery as cq\nresult = cq.Workplane('XY').box(40, 25, 2.5, centered=(True, True, False))\n"
    r = run_program(code, pool=vpool, outputs=())
    r.cleanup()
    meas, cam = synthetic_camera_view(
        r, K=K, R=R, t_mm=T, image_size=(W, H), part_to_mat=A, view="side", projection="side_xz", top_height_mm=25.0
    )
    assert meas.width.value == pytest.approx(2.5, abs=0.3)
    out = verify(r, {"side": meas}, None, camera_views={"side": cam})
    st = next(x for x in out.verification.tests if x.id == "side.thickness")
    assert st.passed and st.value == pytest.approx(2.5, abs=0.3), out.verification.reasons
    assert out.views["side"].frame == "camera"
