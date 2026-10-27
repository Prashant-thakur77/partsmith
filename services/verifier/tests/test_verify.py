from __future__ import annotations

from collections.abc import Iterator

import cv2
import numpy as np
import pytest
from partsmith_schemas.common import DataOrigin
from partsmith_schemas.verification import JudgeVeto

from services.geom_worker.sandbox import ExecResult, WarmPool, run_program
from services.verifier.synthetic import synthetic_top_measurement
from services.verifier.verify import photo_mask_from_measurements, verify


@pytest.fixture(scope="module")
def base(vpool: WarmPool, plate_code: str) -> Iterator[ExecResult]:
    r = run_program(plate_code, pool=vpool, outputs=())
    yield r
    r.cleanup()


def _run(pool: WarmPool, code: str, **params: float) -> ExecResult:
    r = run_program(code, params, pool=pool, outputs=())
    r.cleanup()
    return r


def test_model_against_its_own_silhouette_is_verified(base: ExecResult) -> None:
    meas, photo = synthetic_top_measurement(base)
    out = verify(base, {"top": meas}, None, photo_masks={"top": photo})
    v = out.verification
    assert v.verified and v.status == "verified", v.reasons
    assert v.views[0].hausdorff_mm < 0.15 and v.views[0].iou > 0.99
    assert v.origin == DataOrigin.synthetic
    assert v.versions["cadquery"] == "2.8.0" and v.versions["verifier"]
    assert {"code_sha256", "mesh_sha256", "params_sha256", "measurements_sha256"} <= set(v.hashes)
    assert v.reasons[0].startswith("Verified")
    png = out.overlays["residual_top.png"]
    assert cv2.imdecode(np.frombuffer(png, np.uint8), cv2.IMREAD_COLOR) is not None
    # residuals are sorted by |delta|
    deltas = [abs(r.delta_mm) for r in v.residuals]
    assert deltas == sorted(deltas, reverse=True)


@pytest.mark.parametrize("delta", [1.0, -1.0])
def test_length_change_is_detected_with_sign(vpool: WarmPool, plate_code: str, base: ExecResult, delta: float) -> None:
    meas, photo = synthetic_top_measurement(base)
    r = _run(vpool, plate_code, length=40.0 + delta)
    v = verify(r, {"top": meas}, None, photo_masks={"top": photo}).verification
    assert not v.verified and v.status == "best_effort"
    length = next(x for x in v.residuals if x.quantity == "length")
    assert length.delta_mm == pytest.approx(delta, abs=0.1)
    assert not length.passed
    assert any("length" in s for s in v.reasons)


def test_hole_diameter_residual(vpool: WarmPool, plate_code: str, base: ExecResult) -> None:
    meas, photo = synthetic_top_measurement(base)
    r = _run(vpool, plate_code, hole_d=3.8)
    v = verify(r, {"top": meas}, None, photo_masks={"top": photo}).verification
    d = [x for x in v.residuals if x.quantity == "diameter"]
    assert len(d) == 2 and all(x.delta_mm == pytest.approx(-0.4, abs=0.06) for x in d)
    assert not v.verified  # hole tests are P0
    assert v.residuals[0].quantity == "diameter"  # the largest residual comes first


def test_missing_hole_is_reported(vpool: WarmPool, plate_code: str, base: ExecResult) -> None:
    meas, photo = synthetic_top_measurement(base)
    r = _run(vpool, plate_code, hole_count=1)
    v = verify(r, {"top": meas}, None, photo_masks={"top": photo}).verification
    assert not v.verified
    assert any("no matching hole" in s for s in v.reasons)


def test_outline_only_measurements_work_without_mask(base: ExecResult) -> None:
    meas, _ = synthetic_top_measurement(base)
    pm = photo_mask_from_measurements(meas)
    assert pm.mask.any()
    v = verify(base, {"top": meas}, None).verification
    assert v.views[0].iou > 0.98 and v.views[0].hausdorff_mm < 0.3


def test_blocking_veto_blocks(base: ExecResult) -> None:
    meas, photo = synthetic_top_measurement(base)
    veto = JudgeVeto(feature="hook_1", issue="hook faces the wrong way", severity="blocking")
    v = verify(base, {"top": meas}, None, photo_masks={"top": photo}, vetoes=[veto]).verification
    assert not v.verified and v.status == "best_effort"
    assert any("veto" in s for s in v.reasons)
    minor = JudgeVeto(feature="hook_1", issue="cosmetic", severity="minor")
    assert verify(base, {"top": meas}, None, photo_masks={"top": photo}, vetoes=[minor]).verification.verified


def test_failed_program_is_failed(vpool: WarmPool, base: ExecResult) -> None:
    meas, _ = synthetic_top_measurement(base)
    r = run_program("import os\n", pool=vpool)
    v = verify(r, {"top": meas}, None).verification
    assert v.status == "failed" and not v.verified
    assert "policy" in v.reasons[0]


def test_no_views_means_not_verified(base: ExecResult) -> None:
    v = verify(base, {}, None).verification
    assert not v.verified and any("No measured" in s for s in v.reasons)


def test_side_view_is_compared(vpool: WarmPool, base: ExecResult) -> None:
    from partsmith_schemas.common import Measured
    from partsmith_schemas.measurement import Measurements, ViewKind

    meas, photo = synthetic_top_measurement(base)
    side = Measurements(
        view=ViewKind.side,
        origin=DataOrigin.synthetic,
        outline_mm=[(-20, 0), (20, 0), (20, 3), (-20, 3)],
        length=Measured(value=40.0),
        width=Measured(value=3.0),
        area_mm2=120.0,
    )
    v = verify(base, {"top": meas, "side": side}, None, photo_masks={"top": photo}).verification
    sv = next(x for x in v.views if x.view == "side")
    assert sv.iou > 0.97 and sv.hausdorff_mm < 0.15
