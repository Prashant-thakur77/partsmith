"""Fits where it goes: the measured mate against the model's matching feature on the CAD solid (informational)."""

from __future__ import annotations

from typing import Any, Literal

import pytest
from partsmith_schemas.common import Measured
from partsmith_schemas.measurement import MateKind, MateMeasurement
from partsmith_schemas.verification import Validity, Verification, ViewMetrics

from services.agent.templates import get_template
from services.geom_worker.sandbox import WarmPool, run_program
from services.metrology.calibrate import detect_mat, estimate_pose
from services.metrology.mate import MatePoint, measure_mates
from services.metrology.points import region_grow_points
from services.verifier.mate_fit import (
    TEST_PREFIX,
    PrinterFit,
    as_part_tests,
    check_fit,
    check_fits,
    does_not_fit,
    model_side,
    reason_line,
    reprint,
)
from services.verifier.ship import can_ship
from tools.synth.mating import render_mating

PLA = PrinterFit("pla-fdm-0.4", "PLA · FDM 0.4 mm nozzle", 0.20, "preset")


def _mate(
    kind: MateKind,
    size: float,
    sigma: float = 0.02,
    material: Literal["opening", "material"] = "material",
    shape: Literal["round", "strip", "region"] = "round",
) -> MateMeasurement:
    return MateMeasurement(id="mate_1", kind=kind, point_px=(100.0, 100.0), ok=True, material=material, shape=shape,
                           size=Measured(value=size, sigma_mm=sigma))  # fmt: skip


def _feats(**kw: Any) -> dict[str, Any]:
    base: dict[str, Any] = {"bbox_mm": [-10.0, -10.0, 0.0, 10.0, 10.0, 12.0], "holes": [], "interfaces": [],
                            "plate_thickness_mm": None}  # fmt: skip
    return {**base, **kw}


SHAFT_BORE = {"id": "shaft_bore", "label": "shaft bore", "mate_label": "shaft", "gap_mm": 6.20, "mates": [6.0]}
PANEL_GAP = {"id": "panel_gap", "label": "gap under the hook lip", "mate_label": "panel", "gap_mm": 3.30}


@pytest.mark.parametrize(
    ("shaft", "fit", "passed"),
    [(6.00, "sliding fit", True), (6.15, "press fit", True), (6.32, "does not fit", False), (5.50, "very loose", True)],
)
def test_shaft_in_the_declared_bore_is_classified_by_its_clearance(shaft: float, fit: str, passed: bool) -> None:
    f = check_fit(_mate("mate_peg", shaft, shape="strip"), _feats(interfaces=[SHAFT_BORE]), PLA, has_fit_knobs=True)
    assert f.model_feature_source == "interface" and "shaft_bore" in f.model_feature
    assert f.model_mm == pytest.approx(6.20) and f.clearance_mm == pytest.approx(6.20 - shaft, abs=1e-9)
    assert f.fit == fit and f.passed is passed
    if not passed:
        assert f.text.startswith("does not fit") and "too big" in f.text
    assert f.printed is not None and f.printed.internal
    assert f.printed.clearance_mm == pytest.approx(6.20 - shaft - 0.20, abs=1e-9)  # the hole prints ~0.2 mm small
    assert f.printed.with_preset_clearance_mm == pytest.approx(6.20 - shaft, abs=1e-9)
    assert "after printing on PLA · FDM 0.4 mm nozzle" in f.printed.text


def test_sigma_spanning_a_class_boundary_is_said() -> None:
    f = check_fit(_mate("mate_peg", 6.12, sigma=0.05), _feats(interfaces=[SHAFT_BORE]))
    assert f.fit == "press fit" and f.fit_low == "press fit" and f.fit_high == "sliding fit"
    assert "within ±σ: press fit to sliding fit" in f.text and f.printed is None


def test_each_mate_kind_meets_the_right_model_feature() -> None:
    feats = _feats(interfaces=[PANEL_GAP], holes=[{"diameter_mm": 8.6, "center_mm": [0, 0], "z_min_mm": 0,
                                                    "z_max_mm": 12, "through": True, "coverage_deg": 360}],
                   plate_thickness_mm=2.5)  # fmt: skip
    socket = check_fit(_mate("mate_hole", 20.5, material="opening"), feats, PLA)
    assert socket.model_feature_source == "outer_size" and socket.model_mm == pytest.approx(20.0)
    assert socket.clearance_mm == pytest.approx(0.5) and socket.fit == "loose fit"
    assert (
        socket.printed is not None and not socket.printed.internal and socket.printed.clearance_mm == pytest.approx(0.5)
    )
    panel = check_fit(_mate("mate_slot", 3.0, shape="strip"), feats, PLA)
    assert panel.model_feature_source == "interface" and panel.clearance_mm == pytest.approx(0.3)
    slot = check_fit(_mate("mate_slot", 2.4, material="opening", shape="strip"), feats, PLA)
    assert slot.model_feature_source == "plate_thickness" and not slot.passed and "too small" in slot.text
    peg = check_fit(_mate("mate_peg", 8.4), _feats(holes=feats["holes"]), PLA)
    assert peg.model_feature_source == "nearest_hole" and peg.fit == "sliding fit"
    assert "closest in size" in peg.model_feature_note
    none = check_fit(_mate("mate_peg", 8.4), _feats(), PLA)
    assert none.model_feature_source == "none" and none.clearance_mm is None and "no bore" in none.text
    assert model_side(_mate("mate_slot", 3.0), _feats()) is None


def test_tests_are_p1_and_the_reason_says_it_in_plain_words() -> None:
    fits = check_fits([_mate("mate_peg", 6.32)], _feats(interfaces=[SHAFT_BORE]), PLA)
    tests = as_part_tests(fits)
    assert [t.id for t in tests] == [f"{TEST_PREFIX}mate_1"] and tests[0].priority == "P1" and not tests[0].passed
    assert tests[0].value == pytest.approx(-0.12) and tests[0].expected == 0.0
    line = reason_line(fits)
    assert line is not None and line.startswith("Does not fit where it goes") and "does not change verified" in line
    assert does_not_fit(tests) == tests
    ok = check_fits([_mate("mate_peg", 6.0)], _feats(interfaces=[SHAFT_BORE]), PLA)
    assert (reason_line(ok) or "").startswith("Fits where it goes") and not does_not_fit(as_part_tests(ok))
    assert reason_line([]) is None


def test_learned_clearance_only_changes_the_printer_note() -> None:
    fits = check_fits([_mate("mate_peg", 6.0)], _feats(interfaces=[SHAFT_BORE]), PLA, has_fit_knobs=True)
    learned = PrinterFit("pla-fdm-0.4", "PLA · FDM 0.4 mm nozzle", 0.10, "learned", "learned from 3 coupon reports")
    (g,) = reprint(fits, learned, has_fit_knobs=True)
    assert g.clearance_mm == fits[0].clearance_mm and g.mate_mm == fits[0].mate_mm
    assert g.printed is not None and g.printed.clearance_mm == pytest.approx(0.10)
    assert g.printed.clearance_source == "learned" and "learned from 3 coupon reports" in g.printed.text


def _verified(tests: list[Any]) -> Verification:
    return Verification(
        verified=True, status="verified", views=[ViewMetrics(view="top", iou=0.99, hausdorff_mm=0.2, hd95_mm=0.1,
                                                             mean_mm=0.05)],
        tests=tests, validity=Validity(is_valid=True, single_solid=True, watertight=True, volume_mm3=100.0,
                                       bbox_mm=(10.0, 10.0, 5.0)),
        hashes={"code_sha256": "a", "mesh_sha256": "b"},
    )  # fmt: skip


def test_export_gate_warns_but_never_blocks_a_verified_part() -> None:
    bad = as_part_tests(check_fits([_mate("mate_peg", 6.32)], _feats(interfaces=[SHAFT_BORE]), PLA))
    d = can_ship(_verified(bad), job_status="done")
    assert d.ok and not d.requires_ack
    assert "does not fit where it goes" in d.reason and "0.12 mm too big" in d.reason
    good = as_part_tests(check_fits([_mate("mate_peg", 6.0)], _feats(interfaces=[SHAFT_BORE]), PLA))
    assert "does not fit" not in can_ship(_verified(good), job_status="done").reason
    assert (
        can_ship(_verified([]), job_status="done").reason
        == "verified: every measured dimension and view is within tolerance"
    )
    be = _verified(bad).model_copy(update={"verified": False, "status": "best_effort", "views": []})
    d2 = can_ship(be, job_status="done")
    assert not d2.ok and d2.requires_ack and "does not fit where it goes" in d2.reason


@pytest.fixture(scope="module")
def pool() -> Any:
    p = WarmPool(size=1)
    p.warm()
    yield p
    p.close()


@pytest.mark.parametrize(("bore", "fit"), [(6.20, "sliding fit"), (5.90, "does not fit"), (6.50, "loose fit")])
def test_synthetic_shaft_photo_against_a_real_knob_solid(pool: WarmPool, bore: float, fit: str) -> None:
    """A 6.00 mm shaft lying on the mat (SYNTHETIC render, exact) against the knob template's measured bore."""
    img, gt, _ = render_mating("shaft", 6.0)
    det = detect_mat(img)
    (m,) = measure_mates(img, det, estimate_pose(det), [MatePoint("mate_1", "mate_peg", gt.tap_px)],
                         region_grow_points(), mask_source="mock-points")  # fmt: skip
    t = get_template("knob")
    r = run_program(t.code, {**t.defaults, "bore_d": bore}, pool=pool, outputs=(), features=True)
    r.cleanup()
    assert r.ok and r.features is not None
    f = check_fit(m, r.features, PLA, has_fit_knobs=True)
    assert f.model_feature_source == "interface" and f.model_mm == pytest.approx(bore, abs=0.02)
    assert f.fit == fit and f.passed is (fit != "does not fit")
