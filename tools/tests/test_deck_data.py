"""The deck's data generator: pure helpers only, no network."""

from __future__ import annotations

from typing import Any

from tools import deck_data


def test_minutes_to_file_uses_the_first_3mf_export() -> None:
    events = [
        {"t": "stage", "ts": 100.0},
        {"t": "artifact", "kind": "stl", "ts": 150.0},
        {"t": "artifact", "kind": "threemf", "ts": 400.0},
        {"t": "artifact", "kind": "threemf", "ts": 900.0},
    ]
    assert deck_data.minutes_to_file(events, created_at=100.0) == 5.0


def test_mesh_encoding_round_trips_its_counts() -> None:
    blob = deck_data.encode_mesh([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]], [[0, 1, 2]])
    assert deck_data.decode_counts(blob) == (3, 1)
    assert len(blob) == 8 + 3 * 12 + 12


def test_rounds_keep_the_runs_own_numbers() -> None:
    events: list[dict[str, Any]] = [
        {"t": "log"},
        {
            "t": "iteration",
            "iter": 2,
            "hausdorff_mm": 0.5106,
            "iou": 0.98138,
            "edits": [{"param": "length", "from": 45.3, "to": 45.0, "reason": "x"}],
            "analysis": "a",
        },
    ]
    assert deck_data.rounds(events) == [
        {
            "round": 2,
            "error_mm": 0.51,
            "iou": 0.981,
            "edits": [{"param": "length", "from": 45.3, "to": 45.0}],
            "analysis": "a",
        }
    ]
