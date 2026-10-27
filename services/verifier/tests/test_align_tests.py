from __future__ import annotations

import numpy as np
import pytest
from partsmith_schemas.common import Measured, Source
from partsmith_schemas.measurement import Hole, Measurements, ViewKind
from partsmith_schemas.partspec import BaseProfile, Family, PartSpec, ThroughHole

from services.verifier.align import Rigid2D, align
from services.verifier.part_tests import evaluate_tests, generate_tests
from services.verifier.render import Frame, circle_polygon, rasterize_polygon

L_SHAPE = np.array([[0, 0], [30, 0], [30, 8], [8, 8], [8, 20], [0, 20]], float)


@pytest.mark.parametrize(
    "truth",
    [Rigid2D(0, 0, 0), Rigid2D(37.0, 4.0, -2.5), Rigid2D(-120.0, -3.0, 1.0), Rigid2D(65.0, 2.0, 2.0, mirror=True)],
)
def test_align_recovers_rigid_pose(truth: Rigid2D) -> None:
    model = L_SHAPE - L_SHAPE.mean(axis=0)
    hole = circle_polygon((5.0, -3.0), 3.0)
    mf = Frame.around(model, 20.0)
    m_mask = rasterize_polygon(model, [hole], mf)
    photo = truth.apply(model)
    pf = Frame.around(photo, 20.0)
    p_mask = rasterize_polygon(photo, [truth.apply(hole)], pf)
    res = align(m_mask, mf, p_mask, pf)
    assert res.transform.mirror == truth.mirror
    probe = np.array([[10.0, 5.0], [-7.0, 3.0]])
    assert np.abs(res.transform.apply(probe) - truth.apply(probe)).max() < 0.05
    assert res.cost_mm < 0.05


def test_align_never_scales() -> None:
    model = L_SHAPE - L_SHAPE.mean(axis=0)
    mf = Frame.around(model, 20.0)
    big = model * 1.05
    pf = Frame.around(big, 20.0)
    res = align(rasterize_polygon(model, [], mf), mf, rasterize_polygon(big, [], pf), pf)
    M = res.transform.matrix()
    assert np.linalg.det(M[:2, :2]) == pytest.approx(1.0, abs=1e-9)


def _measured(v: float, source: Source = Source.measured) -> Measured:
    return Measured(value=v, source=source, sigma_mm=0.05)


def _top(**kw: object) -> Measurements:
    base: dict[str, object] = dict(
        view=ViewKind.top,
        origin="synthetic",
        outline_mm=[(0, 0), (1, 0), (1, 1)],
        length=_measured(40.0),
        width=_measured(20.0),
        area_mm2=800.0,
        holes=[Hole(id="hole_1", center_mm=(-10.0, 0.0), diameter=_measured(4.2))],
    )
    base.update(kw)
    return Measurements.model_validate(base)


def test_generated_tests_and_evaluation() -> None:
    spec = PartSpec(
        family=Family.clip,
        base_profile=BaseProfile(kind="rect", points_mm=[(0, 0)]),
        thickness=_measured(3.0, Source.user_stated),
        features=[ThroughHole(id="hole_9", center_mm=(5.0, 0.0), diameter=_measured(3.0, Source.inferred))],
    )
    tests = generate_tests(spec, {"top": _top()})
    ids = [t.id for t in tests]
    assert ids[:2] == ["hole_1.diameter", "hole_1.center"]
    assert "hole_9.diameter" not in ids  # inferred values never become tests
    assert {"bbox.x", "bbox.y", "thickness", "valid", "single_solid", "watertight", "volume", "min_wall"} <= set(ids)
    values = {
        "hole:hole_1.diameter": 4.30,
        "hole:hole_1.center_offset": 0.5,
        "bbox.x": 40.2,
        "bbox.y": 20.5,
        "thickness": 3.0,
        "valid": True,
        "single_solid": True,
        "watertight": True,
        "volume": 100.0,
        "min_wall": 0.7,
    }
    res = {t.id: t for t in evaluate_tests(tests, values)}
    assert res["hole_1.diameter"].passed
    assert not res["hole_1.center"].passed and res["hole_1.center"].priority == "P1"
    assert res["bbox.x"].passed and not res["bbox.y"].passed
    assert not res["min_wall"].passed and res["volume"].passed and res["valid"].passed


def test_missing_model_value_fails() -> None:
    tests = generate_tests(None, {"top": _top()})
    res = {t.id: t for t in evaluate_tests(tests, {})}
    assert not res["hole_1.diameter"].passed and "not found" in res["hole_1.diameter"].description
