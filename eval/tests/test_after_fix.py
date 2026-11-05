"""The paired after-fix report: the sample choice is fixed, and the tables count what the stored scores say."""

from __future__ import annotations

import gzip
import json
from pathlib import Path

import pytest

from eval import after_fix


def _score(sid: str, *, passed: bool, verified: bool, err: float, usd: float = 0.2) -> dict[str, object]:
    return {
        "sample_id": sid,
        "pass_0_5": passed,
        "verified": verified,
        "usd": usd,
        "dims": [{"name": "length", "error_mm": err}],
    }


def _write(root: Path, sid: str, score: dict[str, object], mask: str) -> None:
    folder = root / sid
    folder.mkdir(parents=True)
    (folder / "score.json").write_text(json.dumps(score))
    with gzip.open(folder / "run.jsonl.gz", "wt", encoding="utf-8") as fh:
        fh.write(json.dumps({"msg": f"Measured 4 sizes (mask: {mask})"}) + "\n")


def test_samples_are_the_same_each_time_and_come_from_stored_runs() -> None:
    first = after_fix.samples()
    assert first == after_fix.samples()
    assert len(first) == after_fix.N
    assert all((after_fix.BEFORE / s / "score.json").exists() for s in first)


def test_side_counts_verified_but_off_and_takes_the_median_per_size() -> None:
    rows = [
        _score("a", passed=True, verified=True, err=0.1),
        _score("b", passed=False, verified=True, err=0.9),
        _score("c", passed=False, verified=False, err=0.3),
    ]
    side = after_fix._side(rows)
    assert side == {"n": 3, "median_error_mm": 0.3, "pass_0_5": 1, "verified": 2, "verified_but_off": 1, "usd": 0.6}


def test_mask_of_reads_the_runs_own_line_and_says_when_there_is_none(tmp_path: Path) -> None:
    _write(tmp_path, "a", _score("a", passed=True, verified=True, err=0.1), "sam-3.1")
    assert after_fix.mask_of(tmp_path / "a") == "sam-3.1"
    assert after_fix.mask_of(tmp_path / "missing") == "no log"


def test_report_pairs_only_finished_runs_and_lists_the_rest(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    before, after = tmp_path / "before", tmp_path / "after"
    _write(before, "a", _score("a", passed=True, verified=True, err=0.1), "threshold")
    _write(before, "b", _score("b", passed=False, verified=False, err=0.8), "threshold")
    _write(before, "c", _score("c", passed=False, verified=False, err=0.8), "threshold")
    _write(after, "a", _score("a", passed=False, verified=True, err=0.7), "sam-3.1")
    _write(after, "b", _score("b", passed=True, verified=True, err=0.2), "threshold")
    monkeypatch.setattr(after_fix, "BEFORE", before)
    monkeypatch.setattr(after_fix, "DATA", tmp_path / "data" / "synthetic")
    monkeypatch.setattr(after_fix, "REPORT", tmp_path / "after_fix.json")
    monkeypatch.setattr(after_fix, "samples", lambda: ["a", "b", "c"])
    doc = after_fix.report(after)
    assert doc["paired"] == 2
    assert doc["not_run"] == ["c"]
    assert doc["discordant"] == {"before_only": 1, "after_only": 1}
    assert doc["masks"]["after"] == {"sam-3.1": 1, "threshold": 1}
    assert doc["after"]["verified_but_off"] == 1
    assert json.loads((tmp_path / "after_fix.json").read_text())["paired"] == 2
