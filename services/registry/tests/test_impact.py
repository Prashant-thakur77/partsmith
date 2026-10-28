"""Job impact numbers: computed only from events and the baked mesh; null when the data is missing."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from services.registry import impact


def _ev(t: str, ts: float, kind: str = "") -> SimpleNamespace:
    return SimpleNamespace(t=t, ts=ts, kind=kind)


def test_minutes_from_upload_to_the_first_print_file() -> None:
    evs = [_ev("stage", 1010.0), _ev("artifact", 1100.0, "photo"), _ev("artifact", 1300.0, "stl"),
           _ev("artifact", 1400.0, "step")]  # fmt: skip
    m = impact.minutes_to_file(1000.0, evs)
    assert m is not None and m["minutes"] == pytest.approx(5.0) and m["kind"] == "stl" and not m["waited_for_answer"]
    assert impact.minutes_to_file(1000.0, [_ev("artifact", 1100.0, "photo")]) is None
    waited = impact.minutes_to_file(1000.0, [_ev("answer", 1050.0), _ev("artifact", 1060.0, "threemf")])
    assert waited is not None and waited["waited_for_answer"]
    # a creation time after the file (clock skew) falls back to the first event
    skew = impact.minutes_to_file(5000.0, [_ev("stage", 1000.0), _ev("artifact", 1060.0, "stl")])
    assert skew is not None and skew["minutes"] == pytest.approx(1.0)


def test_filament_prefers_bake_facts_then_mesh_volume() -> None:
    f = impact.filament({"mass_g_pla": 2.48, "volume_mm3": 2000.0}, 999.0)
    assert f is not None and f["grams"] == 2.48 and f["source"].startswith("bake facts")
    f = impact.filament(None, 2000.0)
    assert f is not None and f["grams"] == pytest.approx(2.48) and f["source"].startswith("verified mesh")
    assert impact.filament(None, None) is None and impact.filament({}, 0.0) is None


def test_job_impact_costs_are_labelled_estimates(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PARTSMITH_PLA_INR_PER_KG", "1000")
    out = impact.job_impact(job_id="j1", created_at=0.0, events=[], facts={"mass_g_pla": 10.0, "print_minutes_est": 12.5},
                            volume_mm3=None, replay=True)  # fmt: skip
    assert out["label"] == "estimate" and out["minutes_to_file"] is None
    inr = next(c for c in out["cost"] if c["currency"] == "INR")
    assert inr == {"currency": "INR", "amount": 10.0, "price_per_kg": 1000.0}
    assert out["print_minutes_est"] == 12.5 and any("replay" in n for n in out["notes"])
    assert any("1000 INR/kg" in a for a in out["assumptions"])
    empty = impact.job_impact(job_id="j2", created_at=0.0, events=[], facts=None, volume_mm3=None)
    assert empty["filament"] is None and empty["cost"] == [] and empty["print_minutes_est"] is None
