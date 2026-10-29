"""Full-loop bench: scoring, tables, regression check, charts (pure parts) and one tiny end-to-end run (slow, mocks)."""

import json
import math
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

import pytest

from eval import charts
from eval import run as R
from eval.stats import cluster_bootstrap_mean


def _score(
    cfg: str,
    sid: str,
    *,
    errs: list[float],
    passed: bool,
    verified: bool = False,
    split: str = "held_out",
    suite: str = "synthetic",
    conv: list[float] | None = None,
) -> dict[str, Any]:
    return {
        "suite": suite,
        "config": cfg,
        "sample_id": sid,
        "split": split,
        "mode": "mock",
        "status": "best_effort",
        "verified": verified,
        "valid": True,
        "pass_0_5": passed,
        "pass_0_3": passed,
        "iterations": 3,
        "wall_s": 10.0,
        "usd": 0.0,
        "tokens_in": 0,
        "tokens_out": 0,
        "provider_modes": ["mock"],
        "dims": [{"name": f"d{i}", "gt_mm": 10.0, "model_mm": 10.0 + e, "error_mm": e} for i, e in enumerate(errs)],
        "convergence": [{"iter": i + 1, "max_error_mm": v} for i, v in enumerate(conv or [])],
    }


def test_compare_by_name_and_hole_diameter() -> None:
    gt = [
        {"name": "length", "value_mm": 40.0},
        {"name": "width", "value_mm": 20.0},
        {"name": "hole_1.diameter", "value_mm": 4.0},
        {"name": "hole_2.diameter", "value_mm": 6.0},
        {"name": "thickness", "value_mm": 3.0, "lo_mm": 2.9, "hi_mm": 3.1},
    ]
    out = R.compare(gt, {"length": 40.2, "width": 19.9, "thickness": 3.05}, [5.8, 4.1, 9.0])
    got = {d["name"]: d["error_mm"] for d in out["dims"]}
    assert got == pytest.approx(
        {"length": 0.2, "width": -0.1, "thickness": 0.05, "hole_1.diameter": 0.1, "hole_2.diameter": -0.2}
    )
    assert out["missed"] == [] and out["extra_holes"] == 1 and out["pass_0_5"] and out["pass_0_3"]
    assert next(d for d in out["dims"] if d["name"] == "thickness")["within_spec"] is True
    miss = R.compare(gt, {"length": 40.0, "width": 20.0, "thickness": 3.0}, [4.0])
    assert miss["missed"] == ["hole_2.diameter"] and not miss["pass_0_5"]  # a missing feature fails pass@


def test_split_and_pick() -> None:
    lock = {"real_parts": {"dev": ["p01"], "held_out": ["p02"]}}
    assert R.split_of("synthetic", "x", lock) == "held_out"
    assert R.split_of("real_ruler", "p01", lock) == "dev" and R.split_of("real_ruler", "p02", lock) == "held_out"
    assert R.split_of("real_ruler", "p99", lock) == "unassigned"
    items = [f"s{i}" for i in range(10)]
    assert R.pick(items, 3, 7) == R.pick(items, 3, 7) and len(R.pick(items, 3, 7)) == 3
    assert R.pick(items, None, 7) == items and R.pick(items, 0, 1) == items


def test_job_summary_from_events() -> None:
    ev = [
        {
            "t": "model_call",
            "stage": "build",
            "provider": "mock",
            "model": "m",
            "mode": "mock",
            "tokens_in": 10,
            "tokens_out": 5,
            "usd": 0.01,
            "ms": 3,
        },
        {"t": "metric", "iter": 1, "name": "max_error_mm", "value": 1.2},
        {"t": "metric", "iter": 2, "name": "max_error_mm", "value": 0.4},
        {"t": "done", "status": "verified", "verified": True, "summary": {"iterations": 2, "strategy": "template"}},
    ]
    s = R.job_summary(ev)
    assert s["status"] == "verified" and s["verified"] and s["iterations"] == 2 and s["iterations_to_converge"] == 2
    assert (s["tokens_in"], s["tokens_out"], s["usd"]) == (10, 5, 0.01) and s["provider_modes"] == ["mock"]
    assert [c["max_error_mm"] for c in s["convergence"]] == [1.2, 0.4]


def test_tables_headline_mock_label_and_mcnemar() -> None:
    scores = [
        _score("B1", "a", errs=[0.1, 0.2], passed=True),
        _score("PS", "a", errs=[0.1, 0.1], passed=True),
        _score("B1", "b", errs=[0.9], passed=False),
        _score("PS", "b", errs=[0.3], passed=True),
        _score("PS", "c", errs=[0.2], passed=True, split="dev", suite="real_ruler"),
    ]
    t = R.build_tables(scores, "mock", ["synthetic: seeded subset"])
    syn = t["synthetic"]
    assert syn["status"] == "ok" and syn["n"] == 2 and syn["ground_truth"] == "synthetic_exact"
    assert R.MOCK_TITLE in syn["title"] and "MOCK" in syn["note"]
    ps = next(r for r in syn["rows"] if r["config"] == "PS")
    assert ps["pass@0.5"] == 1.0 and ps["median_abs_err_mm"] == pytest.approx(0.1)
    assert syn["headline"]["config"] == "PS" and syn["median_abs_err_mm"] == ps["median_abs_err_mm"]
    assert syn["mcnemar_B1_vs_PS"] == {"n_pairs": 2, "b1_only": 0, "ps_only": 1, "p_value": 1.0, "metric": "pass@0.5"}
    assert t["real_ruler"]["status"] == "pending"  # dev runs never make a headline
    assert t["reference_objects"]["status"] == "pending" and t["reference_objects"]["ground_truth"] == "reference_spec"
    live = R.build_tables(scores, "live", [])
    assert R.MOCK_TITLE not in live["synthetic"]["title"]


def test_verified_but_off_counts_verified_runs_that_miss_the_ground_truth() -> None:
    runs = [
        _score("PS", "a", errs=[0.1], passed=True, verified=True),
        _score("PS", "b", errs=[0.6], passed=False, verified=True),  # the verifier passed it, the ruler does not
        _score("PS", "c", errs=[2.0], passed=False),
    ]
    assert R.config_row("PS", runs)["verified_but_off"] == "1/2"
    syn = R.build_tables(runs, "mock", [])["synthetic"]
    assert "verified_but_off" in syn["columns"] and syn["headline"]["verified_but_off"] == "1/2"


def test_every_table_ground_truth_is_a_schema_value() -> None:
    """`/bench` tables carry `ground_truth`; each value must be a GroundTruthSource the web schema knows."""
    from partsmith_schemas import GroundTruthSource

    assert set(R.GROUND_TRUTH) == set(R.ALL_SUITES)
    for suite, gt in R.GROUND_TRUTH.items():
        assert GroundTruthSource(gt).value == gt, suite
    for suite in R.GATE_SUITES:
        assert R.GROUND_TRUTH[suite] == GroundTruthSource.expected_outcome
        assert R.gate_table(suite, [], "mock")["ground_truth"] == "expected_outcome"


def test_regression_check() -> None:
    rep: dict[str, Any] = {
        "mode": "mock",
        "generated_at": "x",
        "tables": R.build_tables(
            [_score("PS", "a", errs=[0.1], passed=True), _score("PS", "b", errs=[0.2], passed=True)], "mock", []
        ),
    }
    base = R.baseline_from(rep)
    assert R.check_regression(rep, base) == []
    worse = json.loads(json.dumps(base))
    worse["tables"]["synthetic"]["PS"]["pass@0.5"] = 1.0
    rep["tables"]["synthetic"]["rows"][0]["pass@0.5"] = 0.5
    bad = R.check_regression(rep, worse)
    assert len(bad) == 1 and "pass@0.5" in bad[0]
    assert R.check_regression(rep, {**worse, "mode": "live"}) == []  # unlike modes are not compared


def test_cluster_bootstrap_and_charts() -> None:
    lo, hi = cluster_bootstrap_mean([[0.1, 0.1], [0.5], [0.3, 0.2, 0.4]], seed=1)
    assert lo <= (0.1 + 0.1 + 0.5 + 0.3 + 0.2 + 0.4) / 6 <= hi
    assert cluster_bootstrap_mean([[0.2, 0.4]]) == pytest.approx((0.3, 0.3))
    assert all(math.isnan(x) for x in cluster_bootstrap_mean([[]]))
    svg = charts.convergence_svg({"PS (N=2)": [1.0, 0.6, None, 0.3], "B1": [0.9]}, "conv")
    ET.fromstring(svg)
    assert "PS (N=2)" in svg and "polyline" in svg
    h = charts.histogram_svg({"PS": [0.05, 0.12, 3.0, math.nan]}, "hist")
    ET.fromstring(h)
    assert "N=3" in h


def test_markdown_and_report_shape(tmp_path: Path) -> None:
    rep = R.build_report([_score("PS", "a", errs=[0.1], passed=True, conv=[0.8, 0.1])], "mock", [], tmp_path)
    assert set(rep) >= {"generated_at", "git_sha", "mode", "tables", "runs", "failures", "measure_only", "charts"}
    assert set(rep["tables"]) == set(R.ALL_SUITES) and rep["runs"]["synthetic"]["PS"][0]["sample_id"] == "a"
    md = R.to_markdown(rep)
    assert "NOT MODEL PERFORMANCE" in md and "**pending**" in md
    mo = R.latest_measure_only()
    assert mo is None or ("EXIT GATE" in mo["summary"] and "sections" in mo)  # tools/readme.py reads `summary`
    for c in rep["charts"]:
        ET.fromstring((tmp_path / c).read_text())


@pytest.mark.slow
def test_one_real_run_end_to_end(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """One mock PS run on a demo sample through start_fix_job, scored from gt.yaml, stored and reloaded."""
    monkeypatch.setattr(R, "RUNS_DIR", tmp_path / "runs")
    monkeypatch.setattr(R, "BENCH_HOME", tmp_path / "home")
    sample = R.REPO / "data" / "synthetic" / "samples" / "demo-cupboard-latch"
    task = R.Task(
        "synthetic",
        "PS",
        "demo-cupboard-latch",
        str(sample),
        "dev",
        "template",
        "",
        "clean",
        None,
        "mock",
        str(tmp_path / "runs" / "mock" / "synthetic" / "PS" / "demo-cupboard-latch"),
    )
    (s,) = R.run_tasks([task], jobs=1, live=False, log=lambda *_: None)
    assert s["status"] in ("verified", "best_effort") and s["valid"] and s["provider_modes"] == ["mock"]
    assert {d["name"] for d in s["dims"]} >= {"length", "width", "thickness"}
    mode, stored = R.load_runs()
    assert mode == "mock" and stored[0]["sample_id"] == "demo-cupboard-latch"
    assert (Path(task.out_dir) / "run.jsonl.gz").exists()


def test_the_spend_cap_stops_starting_runs_and_skips_later_configs(monkeypatch: pytest.MonkeyPatch) -> None:
    from concurrent.futures import ThreadPoolExecutor

    class OneThread(ThreadPoolExecutor):
        def __init__(self, max_workers: int, mp_context: Any = None, initializer: Any = None, initargs: Any = ()):
            super().__init__(max_workers=1)

    def fake_run(t: R.Task) -> dict[str, Any]:
        time.sleep(0.01)
        return {"sample_id": t.sample_id, "config": t.config, "usd": 0.6}

    monkeypatch.setattr(R, "run_task", fake_run)
    monkeypatch.setattr(R, "ProcessPoolExecutor", OneThread)
    tasks = [R.Task("synthetic", c, f"s{i}", "", "held_out", "template") for c in ("PS", "B1") for i in range(6)]
    logs: list[str] = []
    got = R.run_tasks(tasks, jobs=1, live=True, log=logs.append, max_usd=1.0)
    # $0.60 + $0.60 crosses the cap: at most the one run already started finishes, nothing of B1 starts
    assert 2 <= len(got) <= 3 and {r["config"] for r in got} == {"PS"}
    assert [r["sample_id"] for r in got] == sorted(r["sample_id"] for r in got)
    assert any("B1" in line and "not started" in line for line in logs)


def test_reports_are_strict_json_with_unknown_rates_as_null(tmp_path: Path) -> None:
    rep = {"tables": {"control": {"rate": math.nan, "ci": [math.nan, math.inf], "n": 0}}, "mode": "mock"}
    assert R.json_safe(rep) == {"tables": {"control": {"rate": None, "ci": [None, None], "n": 0}}, "mode": "mock"}
    json.dumps(R.json_safe(rep), allow_nan=False)  # raises on any NaN left behind


def test_a_report_rebuilt_from_stored_runs_names_the_commit_the_runs_were_made_at() -> None:
    a = {"git": {"sha": "aaa", "dirty": False}}
    b = {"git": {"sha": "aaa", "dirty": True}}
    assert R.runs_git([a, b]) == {"sha": "aaa", "dirty": True, "source": "runs"}
    mixed = R.runs_git([a, {"git": {"sha": "bbb", "dirty": False}}])
    assert mixed["source"] == "current tree"
    assert R.runs_git([a, {}])["source"] == "current tree"  # a run stored before runs were stamped
