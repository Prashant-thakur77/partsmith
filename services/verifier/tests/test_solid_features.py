from __future__ import annotations

import pytest

from services.geom_worker.sandbox import WarmPool, run_program
from services.verifier.solid_features import SolidFeatures


def _features(pool: WarmPool, code: str) -> SolidFeatures:
    r = run_program(code, pool=pool, outputs=())
    r.cleanup()
    assert r.ok, r.error
    assert r.features is not None
    return SolidFeatures.from_dict(r.features)


def test_through_blind_and_fillet_are_told_apart(vpool: WarmPool) -> None:
    code = (
        "import cadquery as cq\n"
        "def build(p):\n"
        "    b = cq.Workplane('XY').box(40, 20, 6, centered=(True, True, False)).edges('|Z').fillet(3)\n"
        "    b = b.faces('>Z').workplane().pushPoints([(-10, 0)]).hole(5.0)\n"
        "    b = b.faces('>Z').workplane().pushPoints([(10, 0)]).hole(3.0, depth=4.0)\n"
        "    pocket = cq.Workplane('XY').workplane(offset=3).center(0, 0).rect(6, 30).extrude(5)\n"
        "    return b.cut(pocket)\n"
        "result = build({})\n"
    )
    f = _features(vpool, code)
    holes = sorted(f.holes, key=lambda h: h.center_mm[0])
    assert len(holes) == 2  # the outer corner fillets are convex: not holes
    thru, blind = holes
    assert thru.diameter_mm == pytest.approx(5.0) and thru.through
    assert thru.center_mm == pytest.approx((-10.0, 0.0), abs=1e-6)
    assert blind.diameter_mm == pytest.approx(3.0) and not blind.through
    assert blind.depth_mm == pytest.approx(4.0, abs=1e-3)
    assert f.plate_thickness_mm == pytest.approx(6.0, abs=0.02)
    assert f.min_wall_mm is not None and 1.5 <= f.min_wall_mm <= 3.1  # 2 mm floor under the blind hole
    assert f.size_mm == pytest.approx((40.0, 20.0, 6.0), abs=1e-6)


def test_d_bore_counts_as_hole(vpool: WarmPool) -> None:
    code = (
        "import cadquery as cq\n"
        "def build(p):\n"
        "    b = cq.Workplane('XY').circle(10).extrude(8)\n"
        "    bore = cq.Workplane('XY').workplane(offset=-1).circle(3).extrude(10)\n"
        "    keep = cq.Workplane('XY').workplane(offset=-2).center(-0.75, 0).rect(4.5, 8).extrude(14)\n"
        "    return b.cut(bore.intersect(keep))\n"
        "result = build({})\n"
    )
    f = _features(vpool, code)
    assert len(f.holes) == 1
    h = f.holes[0]
    assert h.diameter_mm == pytest.approx(6.0) and h.through
    assert 200 < h.coverage_deg < 300


def test_thin_wall_is_measured(vpool: WarmPool) -> None:
    code = "import cadquery as cq\nresult = cq.Workplane('XY').box(30, 30, 0.6, centered=(True, True, False))\n"
    f = _features(vpool, code)
    assert f.min_wall_mm == pytest.approx(0.6, abs=0.01)
    assert f.plate_thickness_mm == pytest.approx(0.6, abs=0.01)
