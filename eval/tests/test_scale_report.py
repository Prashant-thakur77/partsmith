"""The scale report's arithmetic on stored scores. No network, no models."""

from __future__ import annotations

import json
from pathlib import Path

from eval import scale_report as R


def _score(root: Path, scale: str, cfg: str, sid: str, **kw: object) -> None:
    d = root / scale / cfg / sid
    d.mkdir(parents=True)
    base = {
        "scale_suite": scale,
        "config": cfg,
        "sample_id": sid,
        "suite": "control",
        "kind": "template",
        "usd": 0.1,
        "wall_s": 10.0,
        "status": "done",
    }
    (d / "score.json").write_text(json.dumps({**base, **kw}))


def test_verified_but_off_counts_only_verified_parts() -> None:
    scores: list[dict[str, object]] = [
        {"verified": True, "max_abs_err_mm": 0.2},
        {"verified": True, "max_abs_err_mm": 0.9, "failure": "worst thickness -0.90 mm"},
        {"verified": False, "max_abs_err_mm": 9.0},
    ]
    got = R.verified_but_off(scores)
    assert (got["k"], got["n"], got["off_in_height"], got["of_runs"]) == (1, 2, 1, 3)


def test_paired_uses_only_samples_with_both_configs(tmp_path: Path) -> None:
    _score(tmp_path, "synthetic", "PS", "a", pass_0_5=True)
    _score(tmp_path, "synthetic", "B1", "a", pass_0_5=False)
    _score(tmp_path, "synthetic", "PS", "b", pass_0_5=True)
    got = R.paired(R.load_scores(tmp_path))
    assert got is not None
    assert (got["n_pairs"], got["ps_only"], got["b1_only"], got["ps_pass"], got["b1_pass"]) == (1, 1, 0, 1, 0)


def test_side_photo_is_called_helpful_only_when_intervals_separate() -> None:
    top = [{"scale_suite": "control_top", "verified": True, "max_abs_err_mm": 2.0} for _ in range(3)]
    side = [{"scale_suite": "control_side", "verified": True, "max_abs_err_mm": 0.1} for _ in range(3)]
    assert R.side_question(top + side)["helpful_shown"] is False
    assert R.side_question(top * 20 + side * 20)["helpful_shown"] is True


def test_voice_and_wonder_summaries_keep_the_wrong_ones(tmp_path: Path) -> None:
    voice = tmp_path / "voice.json"
    voice.write_text(json.dumps({"speech": "synthesised", "rows": [
        {"line": "x", "language": "hindi", "typed": {"right": True}, "spoken": {"right": False, "transcript": "y", "edits": [], "expected": {}}},
        {"line": "z", "language": "english", "typed": {"right": True}, "spoken": {"right": True}},
    ]}))  # fmt: skip
    got = R.voice_summary(voice)
    assert got is not None
    assert got["spoken"]["k"] == 1 and got["typed"]["k"] == 2 and [w["line"] for w in got["wrong_spoken"]] == ["x"]
    wonder = tmp_path / "wonder.json"
    wonder.write_text(
        json.dumps(
            {
                "rows": [{"values": [{}], "usd": 0.1}, {"values": [], "error": "e"}],
                "page_check": [{"number_on_page": None}],
            }
        )
    )
    w = R.wonder_summary(wonder)
    assert w is not None
    assert w["accepted_with_citation"]["k"] == 1 and w["errors"] == 1 and w["page_check"]["page_unreadable"] == 1


def test_a_report_builds_from_stored_scores_and_never_counts_real_photos(tmp_path: Path) -> None:
    _score(
        tmp_path,
        "control_top",
        "PS",
        "a",
        verified=True,
        max_abs_err_mm=0.2,
        pass_0_5=True,
        expected_outcome="accept",
        outcome="accept",
        outcome_correct=True,
    )
    rep = R.build(tmp_path)
    assert rep["counts_as_real_photos_measured"] == 0
    assert rep["runs"] == {"control_top/PS": 1}
    assert rep["not_run"]["synthetic/PS"] == 200
    assert rep["verified_but_off"]["top_only"]["n"] == 1
