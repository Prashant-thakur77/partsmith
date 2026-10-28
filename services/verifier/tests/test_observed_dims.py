"""An observed dimension that is off must never be verified; dimensions nothing observed are labelled inferred."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from partsmith_schemas.common import Measured, Source
from partsmith_schemas.measurement import Measurements
from partsmith_schemas.verification import ParamSpec, PartTest

from services.geom_worker.sandbox import ExecResult, WarmPool, run_program
from services.verifier.part_tests import height_bound_tests, unchecked_values
from services.verifier.synthetic import synthetic_top_measurement
from services.verifier.verify import verify


@pytest.fixture(scope="module")
def short(vpool: WarmPool, plate_code: str) -> Iterator[ExecResult]:
    """The 40 mm test plate built 0.6 mm short."""
    r = run_program(plate_code, {"length": 39.4}, pool=vpool, outputs=())
    yield r
    r.cleanup()


@pytest.fixture(scope="module")
def full(vpool: WarmPool, plate_code: str) -> Iterator[ExecResult]:
    r = run_program(plate_code, pool=vpool, outputs=())
    yield r
    r.cleanup()


def _with_bound(m: Measurements, name: str, lo: float, hi: float) -> Measurements:
    val: Measured = getattr(m, name)
    return m.model_copy(update={name: val.model_copy(update={"bound_mm": (lo, hi)})})


def test_part_0_6_mm_short_against_its_photo_is_not_verified(short: ExecResult, full: ExecResult) -> None:
    meas, photo = synthetic_top_measurement(full)
    v = verify(short, {"top": meas}, None, photo_masks={"top": photo}).verification
    assert not v.verified and v.status == "best_effort"
    length = next(t for t in v.tests if t.id == "bbox.x")
    assert not length.passed and length.value == pytest.approx(39.4, abs=0.1)


def test_measurement_that_shares_the_error_is_caught_by_its_bound(short: ExecResult) -> None:
    """The AA-cell blind spot: the top photo of a thick part reads short when its ends sit lower than the stated
    height, the model is built to that reading and matches the photo exactly. The photo only bounds the length."""
    meas, photo = synthetic_top_measurement(short)
    lo = meas.length.value
    plain = verify(short, {"top": meas}, None, photo_masks={"top": photo}).verification
    assert plain.verified  # nothing in the photo contradicts the short model...
    bounded = _with_bound(meas, "length", lo, lo + 1.2)  # ...but the photo also allows a 0.6 mm longer part
    template = verify(short, {"top": bounded}, None, photo_masks={"top": photo}, known_form=True).verification
    assert template.verified  # a family template's walls stand the stated height by design
    v = verify(short, {"top": bounded}, None, photo_masks={"top": photo}).verification  # an extruded outline
    assert not v.verified and v.status == "best_effort"
    t = next(t for t in v.tests if t.id == "bbox.x.height")
    assert t.priority == "P0" and not t.passed and t.value == pytest.approx(0.6, abs=0.05)
    assert any(x.id == "bbox.x.height" and "side photo" in x.description for x in v.tests)


def test_side_view_replaces_the_height_bound(short: ExecResult) -> None:
    meas, _ = synthetic_top_measurement(short)
    top = _with_bound(meas, "length", meas.length.value, meas.length.value + 1.2)
    side = top.model_copy(update={"view": "side"})
    tests = height_bound_tests({"top": top, "side": side}, {"bbox.x": 39.4}, heights_seen=True)
    assert tests == []


def test_height_bound_tests_pass_for_thin_parts() -> None:
    m = Measured(value=40.0, source=Source.measured, bound_mm=(40.0, 40.3))
    w = Measured(value=20.0, source=Source.measured)
    top = Measurements(view="top", origin="synthetic", outline_mm=[], length=m, width=w, area_mm2=800.0)
    (t,) = height_bound_tests({"top": top}, {"bbox.x": 40.05, "bbox.y": 20.0}, heights_seen=False)
    assert t.id == "bbox.x.height" and t.passed and t.value == pytest.approx(0.1, abs=1e-6)
    inferred = top.model_copy(update={"length": m.model_copy(update={"source": Source.inferred})})
    assert height_bound_tests({"top": inferred}, {"bbox.x": 40.0}, heights_seen=False) == []


def _p0(tid: str) -> PartTest:
    return PartTest(id=tid, description=tid, value=0.0, expected=0.0, tol=0.3, passed=True)


def test_unchecked_values_label_every_knob_no_test_compared() -> None:
    specs = [
        ParamSpec(name="length", default=52, min=26, max=100, step=0.1),
        ParamSpec(name="width", default=30, min=16, max=60, step=0.1),
        ParamSpec(name="thickness", default=1.6, min=1, max=3, step=0.05),
        ParamSpec(name="latch_height", default=3.5, min=2, max=8, step=0.1, label="Latch height"),
        ParamSpec(name="tongue_count", default=2, min=1, max=3, step=1, unit=""),
    ]
    mmap = {"length": "length", "width": "width", "thickness": "thickness"}
    tests = [_p0("bbox.x"), _p0("bbox.y"), _p0("thickness")]
    out = unchecked_values(specs, {"latch_height": 3.5}, mmap, tests, ["top"])
    assert [u.param for u in out] == ["latch_height"]
    u = out[0]
    assert u.source == Source.inferred and u.value == 3.5 and u.label == "Latch height"
    assert "not measured" in u.note and "(top)" in u.note
    # without the thickness test (no thickness stated or measured) the thickness knob is unchecked too
    out2 = unchecked_values(specs, {}, mmap, tests[:2], ["top"])
    assert [u.param for u in out2] == ["thickness", "latch_height"]
