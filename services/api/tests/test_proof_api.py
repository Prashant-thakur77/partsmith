"""`/proof`: every number is read from a report file, and a missing report gives an empty section rather than a made-up value."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from services.api import proof


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(proof.router)
    return TestClient(app)


REPORT: dict[str, Any] = {
    "generated_at": "2026-11-04T21:00:00+00:00",
    "label": "live providers",
    "tables": {
        "synthetic": {
            "rows": [
                {"config": "B1", "n": 12, "median_abs_err_mm": 0.18, "verified_rate": 0.083, "verified_but_off": "0/1"},
                {
                    "config": "PS",
                    "n": 12,
                    "median_abs_err_mm": 0.1,
                    "mean_ci95": "[0.2, 1.2]",
                    "verified_rate": 0.167,
                    "verified_but_off": "0/2",
                },
            ]
        },
        "control": {"headline": {"correct": 6, "n": 6, "ci95": "[0.61, 1.00]"}},
        "redteam": {"headline": {"correct": 10, "n": 10, "ci95": "[0.72, 1.00]"}},
        "real_ruler": {"status": "pending", "n": 0},
    },
    "separate_tables": {
        "public_photos": {
            "rows": [
                {
                    "config": "PS",
                    "n": 16,
                    "median_abs_err_mm": 0.308,
                    "mean_ci95": "[0.3, 0.8]",
                    "verified_rate": 0.375,
                    "verified_but_off": "2/6",
                }
            ]
        }
    },
    "runs": {
        "synthetic": {"PS": [{"verified": True, "max_abs_err_mm": 0.1}, {"verified": False, "max_abs_err_mm": 3.0}]},
        "control": {"PS": [{"verified": True, "max_abs_err_mm": 7.9}, {"verified": True, "max_abs_err_mm": 0.2}]},
    },
}


@pytest.fixture
def reports(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(proof, "REPORTS", tmp_path)
    return tmp_path


def _write(root: Path, name: str, data: dict[str, Any]) -> None:
    (root / name).write_text(json.dumps(data))


def test_empty_reports_give_empty_sections_not_numbers(reports: Path) -> None:
    body = _client().get("/api/v1/proof").json()
    assert body["errors"] == [] and body["outcomes"] == [] and body["instruments"] == []
    assert body["tests"]["gates"] == [] and body["scale"] is None and body["audit"] == []
    assert body["not_tested"]["real_phone_photos_measured"] == 0


def test_suites_carry_their_numbers_sources_and_commands(reports: Path) -> None:
    _write(reports, "report.json", REPORT)
    _write(reports, "bypass.json", {"attempts": 17, "blocked": 17})
    _write(
        reports,
        "public_scale.json",
        {
            "summary": {
                "n_corners": 48,
                "n_photos": 2,
                "mean_err_pct": 0.138,
                "ci95_pct": [0.108, 0.178],
                "mean_err_mm_over_100mm": 0.138,
            }
        },
    )
    _write(
        reports,
        "program_vs_mesh.json",
        {
            "summary": {
                "parts": 17,
                "rows": 88,
                "mesh_hole_spacing_shift_median_mm": 2.771,
                "knob_hole_spacing_shift_median_mm": 0.0,
                "mesh_hole_spacing_shift_mm": 13.871,
                "knob_hole_spacing_shift_mm": 3.1,
            }
        },
    )
    body = _client().get("/api/v1/proof").json()
    by = {e["id"]: e for e in body["errors"] + body["outcomes"] + body["instruments"]}
    assert (
        by["synthetic"]["headline"] == "0.1 mm" and by["synthetic"]["n"] == 12 and by["synthetic"]["ci"] == "[0.2, 1.2]"
    )
    assert by["public_photos"]["headline"] == "0.31 mm" and "not phone captures" in by["public_photos"]["label"]
    assert by["single_vs_loop"]["headline"] == "0.18 → 0.1 mm"
    assert by["bypass"]["headline"] == "17/17 blocked"
    assert by["redteam"]["headline"] == "10/10 correct" and by["redteam"]["ci"] == "[0.72, 1.00]"
    assert by["public_scale"]["headline"] == "0.14 %" and by["public_scale"]["ci"] == "[0.108, 0.178] %"
    assert by["program_vs_mesh"]["headline"] == "2.77 mm against 0 mm"
    for entry in by.values():
        assert entry["source"].startswith("eval/reports/latest/") and entry["command"] and entry["ground_truth"]


def test_the_audit_shows_verified_parts_that_were_off(reports: Path) -> None:
    _write(reports, "report.json", REPORT)
    audit = {a["suite"]: a for a in _client().get("/api/v1/proof").json()["audit"]}
    assert audit["Intact parts, top photo only"] == {
        "suite": "Intact parts, top photo only",
        "runs": 2,
        "verified": 2,
        "within": 1,
        "off": 1,
    }
    assert audit["Rendered parts"]["off"] == 0


def test_gates_keep_their_real_status(reports: Path) -> None:
    _write(reports, "tests.json", {"generated_at": "now", "git": {"sha": "abc"}, "gates": {
        "backend": {"title": "Backend", "status": "passed", "tests": 5, "passed": 5, "failed": 0, "skipped": 0, "command": "make test"},
        "browser": {"title": "Browser", "status": "not run"},
    }})  # fmt: skip
    t = _client().get("/api/v1/proof").json()["tests"]
    assert [g["status"] for g in t["gates"]] == ["passed", "not run"]
    assert t["gates"][1]["passed"] is None and t["source"].endswith("tests.json")


def test_real_counters_read_the_report_and_scale_appears_when_it_exists(reports: Path) -> None:
    report = {
        **REPORT,
        "tables": {**REPORT["tables"], "real_ruler": {"status": "ok", "n": 3}},
        "measure_only": {"sections": {"real_parts_ruler": {"n_photos": 4}}},
    }
    _write(reports, "report.json", report)
    _write(reports, "impact.json", {"n_sessions": 2})
    _write(reports, "scale.json", {"runs": {"synthetic/PS": 10}, "planned": {"synthetic/PS": 200}, "secret_extra": 1})
    body = _client().get("/api/v1/proof").json()
    assert body["not_tested"]["real_parts_with_ruler_ground_truth"] == 3
    assert body["not_tested"]["real_phone_photos_measured"] == 4
    assert body["not_tested"]["real_prints_or_repairs_logged"] == 2
    assert body["scale"]["runs"] == {"synthetic/PS": 10} and "secret_extra" not in body["scale"]
    assert body["scale"]["source"].endswith("scale.json")
