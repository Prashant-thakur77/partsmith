"""Coupon fit learning: bounded update rule, convergence, per-device keys and no effect on measured dimensions."""

from __future__ import annotations

import pytest

from services.registry import fit_learning as FL
from services.registry import presets
from services.registry.store import get_registry
from services.registry.tests.fixtures import make_part

PLA = presets.BY_ID["pla-fdm-0.4"]
DEVICE = "device-test-0001"


def _report(fit: str, amount: str | None = None, *, preset: str = PLA.id, session: str = DEVICE,
            features: int = 1) -> FL.LearnedClearance:  # fmt: skip
    req = FL.CouponReportRequest(
        preset=preset,
        session=session,
        features=[FL.CouponFeatureReport(feature=f"hole_{i}", fit=fit, amount=amount) for i in range(features)],
    )
    return FL.record(get_registry(), req)[1]


def test_proposal_steps_and_bounds() -> None:
    lo, hi = presets.clearance_range(PLA)
    assert (lo, hi) == (0.0, 0.45)
    assert FL.proposal(0.20, "tight", None, PLA) == pytest.approx(0.25)
    assert FL.proposal(0.20, "tight", "barely", PLA) == pytest.approx(0.225)
    assert FL.proposal(0.20, "tight", "very", PLA) == pytest.approx(0.30)
    assert FL.proposal(0.20, "loose", None, PLA) == pytest.approx(0.15)
    assert FL.proposal(0.20, "ok", "very", PLA) == pytest.approx(0.20)
    assert FL.proposal(0.44, "tight", "very", PLA) == hi  # clamped
    assert FL.proposal(0.01, "loose", "very", PLA) == lo
    resin = presets.BY_ID["resin-sla"]
    assert presets.clearance_range(resin) == (0.0, 0.35)


def test_no_reports_means_the_documented_preset() -> None:
    lc = FL.learned(get_registry(), PLA.id, DEVICE)
    assert lc.source == "preset" and lc.clearance_mm == PLA.delta_mm and lc.reports == 0
    assert "starting point" in lc.label
    assert FL.learned(get_registry(), PLA.id, None).source == "preset"
    with pytest.raises(KeyError):
        FL.learned(get_registry(), "nylon", DEVICE)


def test_reports_move_the_clearance_and_are_labelled() -> None:
    lc = _report("tight", features=2)
    assert lc.source == "learned" and lc.clearance_mm == pytest.approx(0.25)
    assert lc.reports == 1 and lc.feature_reports == 2 and lc.label == "learned from 1 coupon report"
    lc = _report("tight")
    # second report starts from 0.25 → proposes 0.30; median(0.25, 0.25, 0.30) = 0.25
    assert lc.clearance_mm == pytest.approx(0.25) and lc.label == "learned from 2 coupon reports"
    assert lc.recent[0].base_mm == pytest.approx(0.25) and lc.recent[0].proposal_mm == pytest.approx(0.30)


def test_keys_are_per_device_and_preset() -> None:
    _report("tight", "very")
    assert FL.learned(get_registry(), PLA.id, "another-device-01").source == "preset"
    assert FL.learned(get_registry(), "petg-fdm-0.4", DEVICE).source == "preset"
    # the raw device id is not stored
    rows = get_registry().coupon_reports(PLA.id, FL.device_key(DEVICE))
    assert rows and DEVICE not in FL.device_key(DEVICE)


def test_never_leaves_the_range() -> None:
    lo, hi = presets.clearance_range(PLA)
    for _ in range(25):
        lc = _report("tight", "very")
        assert lo <= lc.clearance_mm <= hi
    assert lc.clearance_mm == pytest.approx(hi)
    for _ in range(40):
        lc = _report("loose", "very", session="device-test-0002")
        assert lo <= lc.clearance_mm <= hi
    assert lc.clearance_mm == pytest.approx(lo)


@pytest.mark.parametrize("true_mm", [0.05, 0.20, 0.35])
def test_converges_to_a_printer_that_needs_a_given_clearance(true_mm: float) -> None:
    """Simulated printer: a coupon hole fits when the clearance is within ±0.03 mm of what it really needs."""
    session = f"sim-{int(true_mm * 1000):04d}-device"
    lc = FL.learned(get_registry(), PLA.id, session)
    for _ in range(20):
        c = lc.clearance_mm
        fit = "tight" if c < true_mm - 0.03 else "loose" if c > true_mm + 0.03 else "ok"
        amount = "very" if abs(c - true_mm) > 0.12 else None
        lc = _report(fit, amount, session=session)
    assert abs(lc.clearance_mm - true_mm) <= 0.05


def test_learned_clearance_changes_only_fit_knobs() -> None:
    """Measured dimensions (outer diameter, height) never move; only the internal-fit knob gets the clearance."""
    part = make_part("spacer")
    base_vals, _ = presets.apply(PLA.id, part.params, part.defaults)
    learned_vals, changes = presets.apply(PLA.id, part.params, part.defaults, delta_mm=0.35)
    assert [c["param"] for c in changes] == ["bore_d"]
    assert learned_vals["bore_d"] == pytest.approx(part.defaults["bore_d"] + 0.35)
    for k, v in part.defaults.items():
        if k != "bore_d":
            assert learned_vals[k] == v == base_vals[k]
    # out-of-range learned values are clamped to the preset's range before they reach a knob
    clamped, _ = presets.apply(PLA.id, part.params, part.defaults, delta_mm=5.0)
    assert clamped["bore_d"] == pytest.approx(part.defaults["bore_d"] + presets.clearance_range(PLA)[1])
