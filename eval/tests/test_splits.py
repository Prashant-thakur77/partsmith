from pathlib import Path
from typing import Any

from eval.splits import assign, check, real_parts


def _part(root: Path, pid: str, length: float) -> None:
    (root / pid).mkdir(parents=True)
    (root / pid / "gt.yaml").write_text(f"gt_source: ruler\ndims: {{length: {length}}}\n")


def test_assign_fills_dev_then_held_out_and_never_moves_parts(tmp_path: Path) -> None:
    for i in range(5):
        _part(tmp_path, f"p{i}", 10 + i)
    lock: dict[str, Any] = {}
    lock = assign(lock, real_parts(tmp_path), n_dev=2, seed=1, real_dir=tmp_path)
    rp = lock["real_parts"]
    assert len(rp["dev"]) == 2 and len(rp["held_out"]) == 3 and rp["held_out_sha256"]
    frozen_dev, frozen_held = list(rp["dev"]), list(rp["held_out"])
    _part(tmp_path, "p9", 30)
    lock = assign(lock, real_parts(tmp_path), n_dev=2, seed=1, real_dir=tmp_path)
    assert lock["real_parts"]["dev"] == frozen_dev
    assert set(frozen_held) < set(lock["real_parts"]["held_out"])
    assert check(lock, tmp_path) == []


def test_check_detects_edited_held_out_ground_truth(tmp_path: Path) -> None:
    for i in range(3):
        _part(tmp_path, f"p{i}", 10 + i)
    lock = assign({}, real_parts(tmp_path), n_dev=0, seed=1, real_dir=tmp_path)
    (tmp_path / "p1" / "gt.yaml").write_text("gt_source: ruler\ndims: {length: 99}\n")
    assert check(lock, tmp_path) == ["held-out ground truth changed since the split was frozen"]


def test_reference_objects_folder_is_not_a_part(tmp_path: Path) -> None:
    _part(tmp_path, "p0", 10)
    (tmp_path / "reference_objects").mkdir()
    (tmp_path / "reference_objects" / "gt.yaml").write_text("x: 1\n")
    assert real_parts(tmp_path) == ["p0"]
