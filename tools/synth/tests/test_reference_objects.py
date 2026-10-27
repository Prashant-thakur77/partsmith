"""Reference-object spec tables and their exact models."""

import pytest

from tools.synth import geometry as G
from tools.synth.reference_objects import REFERENCE_OBJECTS, SpecDim, get_reference_object


def test_published_numbers() -> None:
    card = get_reference_object("id1_card")
    assert (card.dim("length").nominal_mm, card.dim("width").nominal_mm, card.dim("thickness").nominal_mm) == (
        85.60,
        53.98,
        0.76,
    )
    sd = get_reference_object("sd_card")
    assert (sd.dim("length").nominal_mm, sd.dim("width").nominal_mm, sd.dim("thickness").nominal_mm) == (
        32.0,
        24.0,
        2.1,
    )
    lego = get_reference_object("lego_2x4")
    assert (lego.dim("length").nominal_mm, lego.dim("width").nominal_mm) == (31.8, 15.8)
    assert lego.dim("thickness").nominal_mm == pytest.approx(9.6 + 1.7)  # side view includes the studs
    aa = get_reference_object("aa_cell")
    assert aa.loose and not card.loose
    assert (aa.dim("width").lo_mm, aa.dim("width").hi_mm) == (13.5, 14.5)
    assert (aa.dim("length").lo_mm, aa.dim("length").hi_mm) == (49.2, 50.5)
    for ref in REFERENCE_OBJECTS.values():
        for d in ref.dims:
            assert d.lo_mm <= d.nominal_mm <= d.hi_mm


def test_spec_errors() -> None:
    d = SpecDim("width", 14.5, 13.5, 14.5, "top")
    assert d.error(14.2) == pytest.approx(-0.3)
    assert d.range_error(14.2) == 0.0 and d.within_spec(14.2)
    assert d.range_error(14.8) == pytest.approx(0.3) and not d.within_spec(14.8)
    assert d.range_error(13.0) == pytest.approx(0.5)
    assert d.tol_mm == pytest.approx(1.0)
    with pytest.raises(KeyError):
        get_reference_object("credit_card")


@pytest.mark.parametrize("key", list(REFERENCE_OBJECTS))
def test_models_match_their_spec(key: str) -> None:
    ref = REFERENCE_OBJECTS[key]
    pm = G.build_mesh(ref.code)
    top = G.top_dims(pm)
    for d in ref.dims_for("top"):
        assert top[d.name] == pytest.approx(d.nominal_mm, abs=0.01), d.name
    if ref.side_view:
        assert G.side_dims(pm)["thickness"] == pytest.approx(ref.dim("thickness").nominal_mm, abs=0.01)
    assert pm.vertices[:, 2].min() == pytest.approx(0.0, abs=0.01)  # resting on the mat (tessellation sag only)
