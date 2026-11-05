"""The SAM prompt comparison's bookkeeping: no network."""

from __future__ import annotations

from typing import Any, ClassVar

from eval import sam_prompts as S


def _row(suite: str, old: bool, new: bool, sam_err: float, thr_err: float, colour: str = "orange") -> dict[str, Any]:
    new_row: dict[str, Any] = {"mask": new, "score": 0.75 if new else 0.0}
    if new:
        new_row.update(accepted=True, errors={"length": sam_err, "width": sam_err}, iou_threshold=0.97)
    old_row: dict[str, Any] = {"mask": old, "score": 0.9 if old else 0.0}
    if old:
        old_row.update(accepted=True, errors={"length": sam_err}, iou_threshold=0.9)
    return {
        "suite": suite,
        "id": f"{suite}-{sam_err}",
        "colour": colour,
        "threshold": {"mask": True, "accepted": True, "errors": {"length": thr_err, "width": thr_err}},
        "old": old_row,
        "new": new_row,
    }


def test_budget_shares_identical_calls_and_stops_at_the_cap() -> None:
    made: list[str] = []

    def seg(png: bytes, prompt: str) -> list[Any]:
        made.append(prompt)
        return []

    b = S.Budget(seg, 0.5, 1.0)
    b(b"a", "x")
    b(b"a", "x")
    assert made == ["x"] and b.calls == 1 and not b.spent_out()
    b(b"a", "y")
    assert b.usd == 1.0 and b.spent_out()


def test_skipped_photo_past_the_cap_makes_no_call() -> None:
    b = S.Budget(lambda p, q: [], 1.0, 0.0)
    row = S.run_one(S.Photo("samples", "x", S.REPO / "does-not-matter.jpg"), b)
    assert row["skipped"] == "spend cap reached" and b.calls == 0


def test_summary_rates_pairs_and_rule() -> None:
    rows = [
        _row("samples", False, True, 0.1, 0.08),
        _row("samples", True, True, 0.2, 0.1),
        _row("public", False, False, 0.0, 0.1),
    ]
    rows.append({"suite": "bench", "id": "z", "skipped": "no mat found"})
    s = S.summarise(rows, usd=1.25)
    assert s["photos"] == 4 and s["scored"] == 3 and s["usd"] == 1.25
    assert s["mask_rate"]["old"]["k"] == 1 and s["mask_rate"]["new"]["k"] == 2
    assert s["mask_rate"]["mcnemar"]["new_only"] == 1 and s["mask_rate"]["mcnemar"]["old_only"] == 0
    assert s["mask_rate_by_suite"]["samples"]["new"]["k"] == 2
    assert s["measures_paired"]["new_length_width"]["sam"]["n"] == 4
    assert s["measures_paired"]["new_length_width"]["sam_minus_threshold_median_mm"] == 0.06
    assert s["within_rule"] is False
    assert "Real phone photos are untested" in s["scope"]


def test_set_by_construction_dimensions_never_count() -> None:
    class M:
        class Value:
            def __init__(self, value: float) -> None:
                self.value = value

        length = Value(50.0)
        width = Value(14.0)
        thickness = None
        holes: ClassVar[list[Any]] = []
        part_to_mat = None

    gt = [{"name": "length", "value_mm": 50.5, "set_by_construction": True}, {"name": "width", "value_mm": 14.5}]
    assert S.errors_by_dim(M(), gt, "diameter") == {"width": 0.5}


def test_compact_keeps_results_and_drops_attempt_lists() -> None:
    row = {
        "id": "x",
        "new": {"mask": True, "attempts": [{"prompt": "a"}, {"prompt": "b"}]},
        "old": {"mask": False, "attempts": []},
    }
    out = S.compact(row)
    assert out["new"] == {"mask": True, "calls": 2} and out["old"] == {"mask": False, "calls": 0}
    assert "attempts" in row["new"]
