"""make proof: counts come from machine output, and a gate that did not run says so."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from tools import proof as P

JUNIT = '<testsuites><testsuite tests="10" failures="1" errors="1" skipped="2"/></testsuites>'


def test_junit_counts() -> None:
    assert P.parse_junit(JUNIT) == {"tests": 10, "passed": 6, "failed": 2, "skipped": 2}


def test_node_runner_summary_both_formats() -> None:
    spec = "✔ a (1ms)\nℹ tests 12\nℹ suites 0\nℹ pass 11\nℹ fail 1\nℹ cancelled 0\nℹ skipped 0\nℹ todo 0\n"
    assert P.parse_node_test(spec) == {"tests": 12, "passed": 11, "failed": 1, "skipped": 0}
    assert P.parse_node_test("# tests 3\n# pass 3\n# fail 0\n") == {"tests": 3, "passed": 3, "failed": 0, "skipped": 0}
    assert P.parse_node_test("the runner crashed") is None


def test_playwright_stats() -> None:
    rep = json.dumps({"stats": {"expected": 5, "unexpected": 1, "flaky": 1, "skipped": 2}})
    assert P.parse_playwright(rep) == {"tests": 9, "passed": 5, "failed": 2, "skipped": 2}
    assert P.parse_playwright("{}") is None


def test_status_never_says_passed_on_a_timeout_or_failed_count() -> None:
    assert P._status(None) == "timed out"
    assert P._status(1) == "failed"
    assert P._status(0, {"failed": 1}) == "failed"
    assert P._status(0, {"failed": 0}) == "passed"


def test_a_skipped_gate_is_labelled_and_runs_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    ran: list[str] = []

    def fake_simple(name: str) -> dict[str, Any]:
        ran.append(name)
        return {"title": name, "status": "passed"}

    monkeypatch.setattr(P, "run_simple", fake_simple)
    monkeypatch.setattr(P, "run_backend", lambda: {"title": "b", "status": "passed", "tests": 1, "passed": 1})
    monkeypatch.setattr(P, "run_web_unit", lambda: {"title": "w", "status": "passed", "tests": 1, "passed": 1})
    tests = P.collect(skip=["deploy_check"])
    g = tests["gates"]
    assert g["deploy_check"]["status"] == P.NOT_RUN and g["browser"]["status"] == P.NOT_RUN
    assert "tests" not in g["browser"] and "deploy_check" not in ran


def _reports(tmp: Path) -> None:
    (tmp / "report.json").write_text(
        json.dumps(
            {
                "mode": "live",
                "measure_only": {"sections": {}},
                "tables": {
                    "synthetic": {"status": "ok", "headline": {"n": 12, "median_abs_err_mm": 0.1, "pass_at_0_5": 0.25, "verified_but_off": "1/2"}},
                    "real_ruler": {"status": "pending", "n": 0},
                },
                "separate_tables": {
                    "public_photos": {"status": "ok", "n": 9, "headline": {"n": 9, "median_abs_err_mm": 0.4, "pass_at_0_5": 1 / 3, "verified_but_off": "0/3"}},
                },
            }
        )
    )  # fmt: skip
    (tmp / "impact.json").write_text(json.dumps({"n_sessions": 0}))


def test_proof_page_says_what_was_not_tested(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _reports(tmp_path)
    monkeypatch.setattr(P, "REPORTS", tmp_path)
    monkeypatch.setattr(P, "review_counts", lambda: {"person_reviewed_with_judge": 0, "test_decisions_excluded": 4})
    tests: dict[str, Any] = {
        "generated_at": "2026-11-05T00:00:00+00:00",
        "git": {"sha": "abc", "dirty": True},
        "gates": {
            "backend": {"title": "Backend", "status": "passed", "tests": 7, "passed": 6, "failed": 0, "skipped": 1, "command": "make test"},
            "browser": P.not_run("Browser", "not part of this run"),
        },
    }  # fmt: skip
    md = P.render_proof(tests)
    assert "## What has not been tested" in md
    assert "Real phone photos of a part on a laptop-screen mat: **0** measured" in md
    assert "Real prints or repairs logged: **0**" in md
    assert "reviewed by a person: **0** (4 scripted" in md
    assert "| Backend | passed | 6/7 passed, 1 skipped | `make test` |" in md
    assert "| Browser | not run | – |" in md
    assert "3/9" in md and "pending: nothing has run" in md and "plus uncommitted changes" in md


def test_public_photo_table_cannot_raise_the_real_photo_count(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _reports(tmp_path)
    monkeypatch.setattr(P, "REPORTS", tmp_path)
    monkeypatch.setattr(P, "review_counts", lambda: {"person_reviewed_with_judge": 0, "test_decisions_excluded": 0})
    c = P.not_tested_counts()
    assert c["real_phone_photos_measured"] == 0 and c["real_parts_with_ruler_ground_truth"] == 0


def test_what_the_scale_exclusion_hides_is_stated(tmp_path: Path) -> None:
    run = tmp_path / "a"
    run.mkdir()
    dims = [{"name": "length", "error_mm": -13.5, "set_by_construction": True}, {"name": "width", "error_mm": 0.1}]
    (run / "score.json").write_text(json.dumps({"sample_id": "a", "dims": dims}))
    assert "13.5 mm (a)" in P.excluded_scale_errors(tmp_path)
    assert P.excluded_scale_errors(tmp_path / "none") == ""
