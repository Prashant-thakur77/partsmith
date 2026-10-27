from __future__ import annotations

from collections.abc import Iterator

import pytest
from partsmith_schemas.verification import JudgeVeto, Verification

from services.agent.templates import get_template
from services.geom_worker.sandbox import ExecResult, WarmPool, run_program
from services.verifier.functional import fit_class, interface_probe, screw_probe
from services.verifier.ship import can_ship
from services.verifier.synthetic import synthetic_top_measurement
from services.verifier.verify import VerifyOutput, verify


@pytest.mark.parametrize(
    "d, text, ok",
    [
        (3.4, "M3 screw passes (normal fit), 0.20 mm radial clearance", True),
        (3.2, "M3 screw passes (close fit), 0.10 mm radial clearance", True),
        (4.5, "M4 screw passes (normal fit), 0.25 mm radial clearance", True),
        (6.6, "M6 screw passes (normal fit), 0.30 mm radial clearance", True),
        (2.1, "no metric screw from M2 up passes freely", False),
    ],
)
def test_screw_probe(d: float, text: str, ok: bool) -> None:
    p = screw_probe("hole_1", d)
    assert text in p.text and p.passed is ok
    assert p.id == "probe.hole_1.screw"


def test_interface_probe_and_fit_classes() -> None:
    p = interface_probe({"id": "panel_gap", "label": "gap", "mate_label": "panel", "gap_mm": 5.2,
                         "mates": [3.0, 4.0, 5.0, 6.0]})  # fmt: skip
    assert p.passed and p.text == "gap: a 5 mm panel fits, 0.20 mm clearance (sliding fit)"
    assert [fit_class(c) for c in (-0.1, 0.05, 0.2, 0.5, 1.0)] == [
        "does not fit", "press fit", "sliding fit", "loose fit", "very loose",
    ]  # fmt: skip
    none = interface_probe({"id": "x", "label": "gap", "gap_mm": 1.0, "mates": [2.0]})
    assert not none.passed
    unmeasured = interface_probe({"id": "x", "label": "gap", "gap_mm": None, "note": "open on one side"})
    assert not unmeasured.passed and "open on one side" in unmeasured.text


def _verify(pool: WarmPool, name: str, **params: float) -> tuple[ExecResult, VerifyOutput]:
    t = get_template(name)
    base = run_program(t.code, t.defaults, pool=pool, outputs=())
    base.cleanup()
    meas, photo = synthetic_top_measurement(base)
    r = run_program(t.code, {**t.defaults, **params}, pool=pool, outputs=())
    r.cleanup()
    return r, verify(r, {"top": meas}, None, photo_masks={"top": photo})


@pytest.fixture(scope="module")
def clip(vpool: WarmPool) -> Iterator[tuple[ExecResult, VerifyOutput]]:
    yield _verify(vpool, "clip")


def test_clip_probes_are_p1_and_measured(clip: tuple[ExecResult, VerifyOutput]) -> None:
    _, out = clip
    v = out.verification
    probes = {p["id"]: p for p in out.functional["probes"]}
    assert probes["probe.hole_1.screw"]["text"] == "hole_1: M3 screw passes (normal fit), 0.60 mm radial clearance"
    gap = probes["probe.panel_gap"]
    assert gap["value_mm"] == pytest.approx(5.2, abs=1e-3)  # measured on the solid: arm 8 - lip 2.8
    assert gap["passed"] and "5 mm panel fits" in gap["text"]
    assert {p["id"] for p in out.functional["probes"]} >= {"probe.min_feature", "probe.overhang"}
    p1 = [t for t in v.tests if t.id.startswith("probe.")]
    assert p1 and all(t.priority == "P1" for t in p1)
    assert v.verified


def test_failing_probe_never_blocks_verification(vpool: WarmPool) -> None:
    # A spacer with a 1.5 mm bore, checked against its own silhouette: it matches, but no screw passes the bore.
    t = get_template("spacer")
    r = run_program(t.code, {**t.defaults, "bore_d": 1.5}, pool=vpool, outputs=())
    r.cleanup()
    meas, photo = synthetic_top_measurement(r)
    out = verify(r, {"top": meas}, None, photo_masks={"top": photo})
    hole = next(p for p in out.functional["probes"] if p["kind"] == "screw")
    assert not hole["passed"] and "no metric screw" in hole["text"]
    assert out.verification.verified, out.verification.reasons
    assert out.functional["passed"] < out.functional["total"]


def test_can_ship_paths(vpool: WarmPool, clip: tuple[ExecResult, VerifyOutput]) -> None:
    _, out = clip
    v = out.verification
    assert can_ship(v, job_status="done").ok
    assert not can_ship(v, job_status="running").ok
    assert not can_ship(None, job_status="done").ok

    _, off = _verify(vpool, "clip", hole_d=5.2)
    be = off.verification
    assert be.status == "best_effort"
    d = can_ship(be, job_status="done")
    assert not d.ok and d.requires_ack
    assert "hole_1 is 1.0 mm too large" in d.reason and "coupon" in d.reason
    acked = can_ship(be, job_status="done", acknowledged_best_effort=True)
    assert acked.ok and acked.requires_ack


def test_can_ship_rejects_tampered_records(clip: tuple[ExecResult, VerifyOutput], vpool: WarmPool) -> None:
    _, off = _verify(vpool, "clip", hole_d=5.2)
    forged = off.verification.model_copy(update={"verified": True, "status": "verified"})
    d = can_ship(forged, job_status="done")
    assert not d.ok and not d.requires_ack and "disagree" in d.reason

    good = clip[1].verification
    loose = good.model_copy(update={"thresholds": good.thresholds.model_copy(update={"hausdorff_mm": 5.0})})
    assert not can_ship(loose, job_status="done").ok
    vetoed = good.model_copy(update={"vetoes": [JudgeVeto(feature="hook", issue="mirrored", severity="blocking")]})
    assert not can_ship(vetoed, job_status="done").ok
    no_hash = good.model_copy(update={"hashes": {}})
    assert not can_ship(no_hash, job_status="done").ok
    assert not can_ship({"verified": True}, job_status="done").ok  # malformed record
    failed = Verification(verified=False, status="failed", reasons=["policy error"])
    assert not can_ship(failed, job_status="done", acknowledged_best_effort=True).ok
    assert can_ship(good.model_dump(mode="json"), job_status="done").ok  # JSON round trip
