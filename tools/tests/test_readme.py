"""README generator: every Meta tooling site is found in the code, and the generated blocks render."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from tools import readme


def test_every_meta_site_is_found() -> None:
    table = readme.meta_table()
    assert table.count("\n") == len(readme.USES) + 1
    for u in readme.USES:
        assert f"**{u.model}**" in table
        assert "|" not in u.role  # a pipe would split the markdown row


def test_evidence_block_names_its_sources() -> None:
    block = readme.evidence()
    assert block.startswith("| Check | Result | Source |")
    assert "Real repairs logged" in block


def test_evidence_shows_verified_parts_that_miss_the_ground_truth(monkeypatch: pytest.MonkeyPatch) -> None:
    rep = {
        "mode": "mock",
        "tables": {"synthetic": {"status": "ok", "headline": {"config": "PS", "verified_but_off": "1/2"}}},
    }
    monkeypatch.setattr(readme, "_load", lambda name: rep if name == "report.json" else None)
    row = next(r for r in readme.evidence().splitlines() if "ground truth" in r)
    assert "Verified synthetic parts (mock providers)" in row and "| 1/2 (config PS) |" in row


def test_render_only_touches_marked_blocks() -> None:
    text = "intro\n" + "".join(f"<!-- BEGIN:{n} -->\nSTALE_BODY\n<!-- END:{n} -->\nkeep {n}\n" for n in readme.BLOCKS)
    out = readme.render(text)
    assert out.startswith("intro\n")
    assert all(f"keep {n}\n" in out for n in readme.BLOCKS)
    assert "STALE_BODY" not in out


def test_render_requires_every_block() -> None:
    with pytest.raises(LookupError):
        readme.render("no blocks here")


# --- first screen -----------------------------------------------------------------------------------------------------

REPORT_MOCK = {
    "mode": "mock",
    "generated_at": "2026-10-28T16:03:49+00:00",
    "git_sha": "1c91d0f00cd68f47d8c5c4fd3e268a3598866335",
    "tables": {
        "synthetic": {
            "status": "ok",
            "headline": {"config": "PS", "median_abs_err_mm": 0.3, "verified_but_off": "0/2", "n": 6},
            "rows": [{"config": "PS", "usd_per_job": 0.0, "provider_modes": "mock"}],
        },
        "reference_objects": {"status": "ok", "headline": {"config": "PS", "verified_but_off": "0/1"}},
        "real_ruler": {"status": "pending", "n": 0},
        "control": {"status": "ok", "headline": {"correct": 6, "n": 6}},
        "redteam": {"status": "ok", "headline": {"correct": 9, "n": 10}},
    },
    "measure_only": {"sections": {"reference_objects_real": {"n_photos": 0}, "real_parts_ruler": {"n_photos": 0}}},
}
BYPASS = {"suite": "lying-brain (scripted)", "attempts": 17, "blocked": 16}


def _fixtures(monkeypatch: pytest.MonkeyPatch, report: dict[str, Any] | None, **extra: dict[str, Any]) -> None:
    files = {"report.json": report, "bypass.json": BYPASS, **extra}
    monkeypatch.setattr(readme, "_load", lambda name: files.get(name))


def test_status_line_is_derived_from_the_report_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    _fixtures(monkeypatch, REPORT_MOCK, **{"impact.json": {"n_sessions": 0}})
    s = readme.status_line()
    assert s.startswith("> **Status: mock providers** · bench report 2026-10-28 at commit `1c91d0f`")
    assert "real photos measured: 0" in s and "deterministic mock models on synthetic photos" in s
    assert "live runs are pending" in s

    live = {
        **REPORT_MOCK,
        "mode": "live",
        "measure_only": {"sections": {"reference_objects_real": {"n_photos": 12}, "real_parts_ruler": {"n_photos": 3}}},
        "tables": {**REPORT_MOCK["tables"], "real_ruler": {"status": "ok", "n": 3}},  # type: ignore[dict-item]
    }
    _fixtures(monkeypatch, live)
    s = readme.status_line()
    assert "Status: live providers" in s and "real photos measured: 15" in s and "ruler ground truth: 3" in s
    assert "mock models" not in s
    assert "Some stages ran as labelled mocks" in s  # the fixture row still says provider_modes = mock

    _fixtures(monkeypatch, None)
    assert "no bench report yet" in readme.status_line()


def test_headline_has_four_numbers_each_with_a_source(monkeypatch: pytest.MonkeyPatch) -> None:
    _fixtures(monkeypatch, REPORT_MOCK)
    rows = readme.headline().splitlines()[2:]
    assert len(rows) == 4
    assert rows[0].startswith("| **16/17** |") and "bypass.json" in rows[0]
    assert "**0/2** synthetic · **0/1** reference objects" in rows[1]
    assert "**6/6** control · **9/10** red-team" in rows[2]
    assert rows[3].startswith("| **0.3 mm** |") and "n = 6" in rows[3]
    assert all("mock providers" in r for r in rows[1:])

    _fixtures(monkeypatch, {}, **{"bypass.json": None})  # type: ignore[arg-type]
    assert all(r.startswith("| pending |") for r in readme.headline().splitlines()[2:])


def test_links_render_coming_until_a_url_is_filled(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    f = tmp_path / "links.json"
    monkeypatch.setattr(readme, "LINKS", f)
    f.write_text(json.dumps({"live_site": "", "video": "", "judges": "", "sample": ""}))
    row = readme.links_row()
    assert row.count("_(coming)_") == 4 and "[Docs](docs/README.md)" in row

    f.write_text(json.dumps({"live_site": "https://example.org/", "video": "https://video.example/x"}))
    row = readme.links_row()
    assert "**[Live site](https://example.org/)**" in row and "**[Video](https://video.example/x)**" in row
    assert "[Judges page](https://example.org/judges)" in row and "[Try a sample](https://example.org/jobs/demo)" in row
    assert "(coming)" not in row

    f.write_text(json.dumps({"video": "javascript:alert(1)"}))
    with pytest.raises(ValueError):
        readme.links_row()


def test_committed_links_file_has_every_slot() -> None:
    data = json.loads(readme.LINKS.read_text())
    assert {k for k, _ in readme.LINK_SLOTS} <= set(data)


def test_bench_shows_usd_per_job_and_never_a_fake_zero_for_mock_rows() -> None:
    assert readme._cell({"usd_per_job": 0.0, "provider_modes": "mock"}, "usd_per_job") == "—"
    assert readme._cell({"usd_per_job": 0.0123, "provider_modes": "live"}, "usd_per_job") == "$0.0123"
    assert readme._cell({"usd_per_job": None, "provider_modes": "live"}, "usd_per_job") == "—"


# --- built during the hackathon -----------------------------------------------------------------------------------------

GIT_LOG = "\n".join(
    [
        "@@\x1faaaaaaa\x1f2026-10-25T09:00:00-04:00\x1fchore: before the start",
        "",
        "10\t0\tREADME.md",
        "@@\x1fbbbbbbb\x1f2026-10-26T13:00:00-04:00\x1ffeat: scaffold | first",
        "",
        "120\t0\tservices/agent/jobs.py",
        "40\t2\tapps/web/src/app/page.tsx",
        "900\t0\tdata/replays/x.json",
        "-\t-\tdata/samples/a/top.jpg",
        "300\t0\tpnpm-lock.yaml",
        " create mode 100644 services/agent/jobs.py",
        " create mode 100644 data/replays/x.json",
        "@@\x1fccccccc\x1f2026-10-27T08:00:00-04:00\x1ffeat(eval): bench",
        "",
        "50\t5\teval/run.py",
        "7000\t0\teval/reports/latest/report.json",
        " create mode 100644 eval/run.py",
    ]
)


def test_built_block_counts_commits_and_lines_per_area_from_git(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(readme, "_git", lambda *args: GIT_LOG)
    block = readme.built()
    assert "**2 commits** between 2026-10-26 13:00 ET and 2026-10-27 08:00 ET" in block
    assert "Commits dated before the start: **1**" in block and "`aaaaaaa`" in block
    rows = {r.split(" | ")[0]: r for r in block.splitlines() if r.startswith("| ")}
    assert "| `services/` (Python backend) | 1 | 120 | 0 | 2026-10-26 | 2026-10-26 |" in block
    assert "| `apps/web/` (web app) | 0 | 40 | 0 |" in block
    assert "| `eval/` (benches and reports) | 1 | 50 | 7,000 |" in block  # reports count as data, not code
    assert "| `data/` (samples, replays) | 1 | 0 | 900 |" in block
    # the lockfile is not code, and README.md from the commit before the start is not counted
    assert "| root files | 0 | 0 | 300 |" in block
    assert "| **Total** | **3** | **210** | **8,200** |" in block
    assert "feat: scaffold / first" in block  # a pipe in a subject would break the table
    assert "chore: before the start |" not in block
    assert any(k.startswith("| 2026-10-27 08:00 ET") for k in rows)


def test_built_block_survives_a_missing_git(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*args: str) -> str:
        raise OSError("no git")

    monkeypatch.setattr(readme, "_git", boom)
    assert "git history unavailable" in readme.built()


def test_readme_pipeline_diagram_matches_the_architecture_doc() -> None:
    def mermaid(text: str) -> str:
        return text.split("```mermaid", 1)[1].split("```", 1)[0]

    root = readme.ROOT
    assert mermaid((root / "README.md").read_text()) == mermaid((root / "docs" / "ARCHITECTURE.md").read_text())
