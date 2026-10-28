"""A broken end of unknown length: the user states it, the verifier treats it as stated, not observed."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
from partsmith_schemas.common import Measured, Source
from partsmith_schemas.measurement import Measurements
from partsmith_schemas.partspec import BaseProfile, BrokenRegion, Family, PartSpec
from partsmith_schemas.verification import ParamSpec, PartTest
from shapely.geometry import Polygon, box

from services.geom_worker.sandbox import WarmPool, run_program
from services.verifier.part_tests import unchecked_values
from services.verifier.verify import break_ends, stated_extension, verify

SAMPLES = Path(__file__).resolve().parents[3] / "data" / "synthetic" / "samples"


def _rect_top(length: float = 40.0, width: float = 20.0) -> Measurements:
    hx, hy = length / 2, width / 2
    return Measurements(
        view="top", origin="synthetic", outline_mm=[(-hx, -hy), (hx, -hy), (hx, hy), (-hx, hy)],
        length=Measured(value=length), width=Measured(value=width), area_mm2=length * width,
    )  # fmt: skip


def _spec(top: Measurements, region: list[tuple[float, float]]) -> PartSpec:
    return PartSpec(
        family=Family.latch, base_profile=BaseProfile(kind="polyline", points_mm=top.outline_mm),
        thickness=Measured(value=5.0, source=Source.user_stated),
        broken_region=BrokenRegion(polygon_mm=region, strategy="mirror"),
    )  # fmt: skip


def test_break_ends_and_the_stated_strip() -> None:
    top = _rect_top()
    corner = _spec(top, [(16.0, 4.0), (20.0, 4.0), (20.0, 10.0), (16.0, 10.0)])
    ends = break_ends(corner, top)
    assert ends is not None and ends.length == (False, True) and ends.spans_length and ends.spans_width
    strip = stated_extension(ends, 45.0)
    assert strip is not None and strip.bounds[0] == pytest.approx(19.0) and strip.bounds[2] == pytest.approx(26.0)
    assert stated_extension(ends, 39.0) is None  # nothing beyond the photo's outline to leave out
    notch = _spec(top, [(-3.0, 6.0), (3.0, 6.0), (3.0, 10.0), (-3.0, 10.0)])  # mid-edge: the length is measured
    e2 = break_ends(notch, top)
    assert e2 is not None and not e2.spans_length
    assert break_ends(None, top) is None


def test_stated_knob_is_listed_as_user_stated_not_verified() -> None:
    params = [ParamSpec(name="length", default=45, min=25, max=90, step=0.1, label="Length"),
              ParamSpec(name="width", default=14, min=9, max=30, step=0.1, label="Width")]  # fmt: skip
    tests = [PartTest(id="bbox.x", description="", value=51.3, expected=47.6, tol=0.3, passed=False, priority="P1")]
    said = {"length": Measured(value=51.3, source=Source.user_stated, sigma_mm=0.5)}
    out = unchecked_values(params, {"length": 51.3, "width": 18.0}, {"length": "length", "width": "width"}, tests,
                           ["top"], stated=said)  # fmt: skip
    by = {u.param: u for u in out}
    assert by["length"].source == Source.user_stated and "stated by the user" in by["length"].note
    assert by["width"].source == Source.inferred
    # the model no longer holds the stated value: no claim that it is the user's number
    moved = unchecked_values(params, {"length": 48.0}, {"length": "length"}, tests, ["top"], stated=said)
    assert next(u for u in moved if u.param == "length").source == Source.inferred


def test_latch_sample_stated_length(vpool: WarmPool) -> None:
    """The latch's corner is cracked off and the break shortens it: a mirror completion cannot restore the length, so
    the completed region stops at the photo's broken end. The intact replacement then sticks out past it and fails;
    with the original length stated, the strip beyond the end is left out and the part verifies on the intact region,
    while the length itself stays stated (P0 consistency test only, NOT verified, not in the max error)."""
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
    removed = Polygon(np.asarray(gt["broken"]["removed_footprint_mat_mm"]) @ inv[:2, :2].T + inv[:2, 2])
    x0, y0, x1, y1 = Polygon(m.outline_mm).bounds
    clipped = removed.intersection(box(x0, y0 - 5, x1, y1 + 5))  # what a mirror completion can restore
    spec = _spec(m, [tuple(p) for p in np.asarray(clipped.exterior.coords)[:-1]])
    true_len = float(params["length"])
    r = run_program(t.code, params, pool=vpool, outputs=())
    short = run_program(t.code, {**params, "length": true_len - 2.0}, pool=vpool, outputs=())
    r.cleanup()
    short.cleanup()

    plain = verify(r, {"top": m}, spec).verification
    assert not plain.verified and plain.views[0].hausdorff_mm > 1.0  # the replacement sticks out past the break

    said = Measured(value=true_len, source=Source.user_stated, sigma_mm=0.5)
    out = verify(r, {"top": m}, spec, stated={"length": said})
    v = out.verification
    assert v.views[0].hausdorff_mm < 0.5, v.reasons
    st = next(x for x in v.tests if x.id == "bbox.x.stated")
    assert st.priority == "P0" and st.passed
    assert next(x for x in v.tests if x.id == "bbox.x").priority == "P1"  # still informational
    assert not any(r_.feature_id == "outline" and r_.quantity == "length" for r_ in v.residuals)
    assert v.max_error_mm is not None and v.max_error_mm < 0.5  # the stated length is not in the max error
    assert plain.max_error_mm is not None and plain.max_error_mm > 1.0
    assert any("stated by the user, not observed" in s for s in v.reasons)
    assert out.broken["stated"]["length"]["source"] == "user_stated"
    # the intact region decides, as before: the view passes and no length/width test blocks (in this rectified
    # comparison without the camera, the pivot hole reads 0.2 mm small, a separate P0 failure)
    assert v.views[0].mean_mm < 0.15
    assert not [x.id for x in v.tests if x.priority == "P0" and not x.passed and x.id.startswith("bbox")]

    # A stated value never passes a part by itself: a model that is not the stated length is blocked.
    bad = verify(short, {"top": m}, spec, stated={"length": said}).verification
    assert not bad.verified
    assert not next(x for x in bad.tests if x.id == "bbox.x.stated").passed
