"""Failure taxonomy, provenance, open-weights evidence, impact log and the control / red-team tables."""

import datetime as dt
from pathlib import Path
from typing import Any

import pytest
import yaml

from eval import impact, open_weights, provenance, taxonomy
from eval import run as R


def _s(**kw: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "suite": "synthetic",
        "config": "PS",
        "sample_id": "a",
        "status": "best_effort",
        "valid": True,
        "pass_0_5": False,
        "missed": [],
        "extra_holes": 0,
        "verified": False,
    }
    return {**base, **kw}


@pytest.mark.parametrize(
    ("score", "events", "cat"),
    [
        (_s(pass_0_5=True), [], None),
        (_s(status="refused"), [], "refused"),
        (_s(), [{"t": "log", "msg": "stopping the loop: wall-clock cap reached (900 s)"}], "timeout"),
        (_s(status="failed", failed_checks=["markers"]), [], "scale_fail"),
        (_s(status="failed", failed_checks=["coverage"], retake_reason="No part found on the stage"), [], "seg_fail"),
        (_s(status="failed", failed_checks=["contrast"]), [], "seg_fail"),
        (_s(status="failed", failed_checks=["moire"]), [], "capture_reject"),
        (_s(valid=False), [], "codegen_error"),
        (_s(missed=["hole_1.diameter"]), [], "topology_wrong"),
        (_s(), [{"t": "stage", "stage": "judge", "label": "Judge vetoes: hole: missing (blocking)"}], "judge_veto"),
        (_s(), [], "dim_off"),
    ],
)
def test_taxonomy_rules(score: dict[str, Any], events: list[dict[str, Any]], cat: str | None) -> None:
    assert taxonomy.classify(score, events) == cat


def test_taxonomy_counts_fixed_order() -> None:
    c = taxonomy.counts(["dim_off", None, "dim_off", "refused"])
    assert list(c) == list(taxonomy.CATEGORIES) and c["dim_off"] == 2 and c["refused"] == 1 and c["seg_fail"] == 0
    assert set(taxonomy.CATEGORIES) == set(taxonomy.DESCRIPTIONS)


def test_provenance_and_open_weights() -> None:
    calls: list[dict[str, Any]] = [
        {
            "stage": "build",
            "provider": "mock",
            "model": "meta-models/muse-spark-open",
            "mode": "mock",
            "tokens_in": 100,
            "tokens_out": 50,
        },
        {
            "stage": "fix",
            "provider": "meta",
            "model": "muse-spark-1.3",
            "mode": "live",
            "tokens_in": 30,
            "tokens_out": 20,
        },
        {"stage": "judge", "provider": "together", "model": "unknown", "mode": "live"},
    ]
    p = provenance.build(report="test", mode="mock", model_calls=calls, seeds={"x": 1})
    assert p["stages"]["build"][0]["tokens_in"] == 100 and p["thresholds"]["HAUSDORFF_PASS_MM"] > 0
    assert p["generator_versions"]["tools.synth"] and "synthetic_bench" in p["datasets"]
    ow = open_weights.build(calls, {"synthetic": [{"config": "PS"}]})
    # the mock build call shows the routing but is not evidence: only the live fix call (closed model) counts
    assert ow["builder"]["tokens"] == 50 and ow["builder"]["tokens_on_open_weights"] == 0 and ow["mock_calls"] == 1
    assert ow["builder"]["share_tokens_open_weights"] == pytest.approx(0.0)
    assert ow["stages"]["build"]["models"][0]["open_weights"] is True
    assert ow["stages"]["judge"]["models"][0]["open_weights"] is True  # by endpoint when the model is unknown
    assert ow["open_configs"] == "pending live run"
    ow2 = open_weights.build([], {"synthetic": [{"config": "PS-open-all", "n": 3}]})
    assert (
        ow2["open_configs"]["synthetic"][0]["config"] == "PS-open-all"
        and ow2["builder"]["share_tokens_open_weights"] is None
    )


def test_impact_pending_and_totals(tmp_path: Path) -> None:
    assert impact.totals(impact.load(tmp_path / "missing.yaml"))["status"] == "pending"
    committed = impact.load()  # the committed log must parse (and stays empty until real sessions exist)
    assert committed.currency == "INR"
    p = tmp_path / "s.yaml"
    p.write_text(
        yaml.safe_dump(
            {
                "rupees_per_gram": 1.5,
                "rupees_per_gram_source": "test",
                "sessions": [
                    {
                        "session": "s01",
                        "date": "2026-10-28",
                        "place": "hostel",
                        "part": "latch",
                        "appliance": "cupboard",
                        "replacement_price_inr": 120.0,
                        "price_source": "https://example.invalid/x",
                        "fit_result": "fits",
                        "print_grams": 8.0,
                    },
                    {
                        "session": "s02",
                        "date": "2026-10-29",
                        "place": "shop",
                        "part": "knob",
                        "appliance": "mixer",
                        "price_source": "not stocked",
                        "fit_result": "tight",
                    },
                ],
            }
        )
    )
    t = impact.totals(impact.load(p))
    assert t["n_sessions"] == 2 and t["n_fits"] == 1 and t["n_not_stocked"] == 1
    assert t["print_cost_inr"] == pytest.approx(12.0) and t["saved_inr"] == pytest.approx(108.0)
    assert "s01" in impact.to_markdown(t)
    ev = [{"t": "stage", "ts": 100.0}, {"t": "done", "ts": 160.0, "verified": True}]
    assert impact.time_to_verified_s(ev) == 60.0 and impact.time_to_verified_s(ev[:1]) is None
    assert (
        impact.Session.model_validate(
            {
                "session": "x",
                "date": dt.date(2026, 1, 1),
                "place": "p",
                "part": "q",
                "appliance": "r",
                "price_source": "u",
            }
        ).fit_result
        == "not_tested"
    )


def test_gate_tables_and_taxonomy_in_report(tmp_path: Path) -> None:
    rt = [
        {
            "suite": "redteam",
            "config": "PS",
            "sample_id": "rt-a",
            "expected_outcome": "reject",
            "expected_checks": ["coverage"],
            "outcome": "reject",
            "failed_checks": ["coverage"],
            "outcome_correct": True,
        },
        {
            "suite": "redteam",
            "config": "PS",
            "sample_id": "rt-b",
            "expected_outcome": "refuse",
            "expected_checks": [],
            "outcome": "accept",
            "failed_checks": [],
            "outcome_correct": False,
        },
    ]
    t = R.gate_table("redteam", rt, "mock")
    assert t["status"] == "ok" and t["headline"]["correct"] == 1 and t["headline"]["n"] == 2
    assert t["headline"]["refuse_expected"] == 1 and t["headline"]["refuse_correct"] == 0
    ctl = [
        {
            "suite": "control",
            "config": "PS",
            "sample_id": "c1",
            "expected_outcome": "accept",
            "outcome": "reject",
            "failed_checks": ["blur"],
            "outcome_correct": False,
            "pass_0_5": False,
            "status": "failed",
        }
    ]
    tc = R.gate_table("control", ctl, "mock")
    assert tc["headline"]["false_reject_rate"] == 1.0
    assert R.gate_table("control", [], "mock")["status"] == "pending"
    tax = R.failure_taxonomy([_s(), _s(sample_id="b", pass_0_5=True), *rt, *ctl])
    assert tax["synthetic"]["PS"]["dim_off"] == 1 and tax["synthetic"]["PS"]["runs"] == 2
    assert "redteam" not in tax and tax["control"]["PS"]["capture_reject"] == 1
    rep = R.build_report([_s(), *rt], "mock", [], tmp_path)
    assert rep["tables"]["redteam"]["status"] == "ok" and "Failure taxonomy" in R.to_markdown(rep)


def test_gate_outcome_from_job_status(tmp_path: Path) -> None:
    (tmp_path / "gt.yaml").write_text(yaml.safe_dump({"expect": {"outcome": "reject", "checks": ["coverage"]}}))
    task = R.Task("redteam", "PS", "rt-x", str(tmp_path), "held_out", "redteam")
    ok = R.gate_outcome({"status": "failed", "failed_checks": ["coverage"], "retake_reason": "No part"}, task)
    assert ok["outcome"] == "reject" and ok["outcome_correct"]
    wrong_check = R.gate_outcome({"status": "failed", "failed_checks": ["blur"], "retake_reason": "blurry"}, task)
    assert wrong_check["outcome"] == "reject" and not wrong_check["outcome_correct"]
    built = R.gate_outcome({"status": "failed", "failed_checks": []}, task)  # failed build, not a capture rejection
    assert built["outcome"] == "accept" and not built["outcome_correct"]
    assert R.gate_outcome({"status": "refused"}, task)["outcome"] == "refuse"
    assert R.gate_outcome({"status": "crashed"}, task)["outcome"] == "error"
