"""The committed demo set (data/synthetic/samples) obeys the folder contract: every sample is complete and matches
the manifest, so the demo runner, the registry seed and the benches can rely on it."""

import json
from pathlib import Path

import cv2
import numpy as np
import pytest
import yaml

from tools.synth.dataset import sha256_file
from tools.synth.demo import DEMO, DEMO_BROKEN, DEMO_ORBIT

ROOT = Path(__file__).resolve().parents[3] / "data" / "synthetic" / "samples"
META_KEYS = {
    "id",
    "title",
    "kind",
    "origin",
    "mat_id",
    "family_hint",
    "intent",
    "user_thickness_mm",
    "difficulty",
    "augmentations",
    "seed",
}
SAMPLE_DIRS = sorted(p for p in ROOT.iterdir() if p.is_dir()) if ROOT.exists() else []


def test_set_matches_the_demo_definition_and_manifest() -> None:
    names = [p.name for p in SAMPLE_DIRS]
    assert names == sorted(d[0] for d in DEMO), "committed folders differ from tools/synth/demo.py"
    assert not [p.name for p in ROOT.iterdir() if p.name.startswith(".")], "leftover staging folders"
    man = json.loads((ROOT / "manifest.json").read_text())
    assert sorted(e["id"] for e in man["samples"]) == names
    total = sum(f.stat().st_size for p in SAMPLE_DIRS for f in p.iterdir())
    assert total < 40e6  # the committed demo folder stays small


@pytest.mark.parametrize("folder", SAMPLE_DIRS, ids=lambda p: p.name)
def test_sample_folder_is_complete(folder: Path) -> None:
    meta = json.loads((folder / "meta.json").read_text())
    assert set(meta) == META_KEYS and meta["id"] == folder.name and meta["origin"] == "synthetic"
    assert meta["kind"] in ("template", "reference_object")
    gt = yaml.safe_load((folder / "gt.yaml").read_text())
    assert gt["gt_source"] == "synthetic_exact" and gt["sample_id"] == folder.name and gt["dims"]
    views = set(gt["views"])
    assert "top" in views
    for v in ("top", "side"):
        assert (folder / f"{v}.jpg").exists() == (v in views), v
        if v in views:
            img = cv2.imdecode(np.frombuffer((folder / f"{v}.jpg").read_bytes(), np.uint8), cv2.IMREAD_COLOR)
            assert img is not None and img.shape[1] == 2000
    orbit = folder.name in DEMO_ORBIT
    assert ("orbit" in views) == orbit and (folder / "orbit.mp4").exists() == orbit
    assert (folder / "gt_frames.json").exists() == orbit
    if orbit:
        frames = json.loads((folder / "gt_frames.json").read_text())["frames"]
        assert len(frames) == gt["views"]["orbit"]["n_frames"] and (folder / "orbit.mp4").stat().st_size > 100_000
    assert ("broken" in gt) == (folder.name in DEMO_BROKEN)
    if folder.name in DEMO_BROKEN:
        assert "broken" in meta["intent"] and gt["broken"]["kind"] == DEMO_BROKEN[folder.name]
    man = {e["id"]: e for e in json.loads((ROOT / "manifest.json").read_text())["samples"]}
    files = {p.name for p in folder.iterdir() if p.is_file()}
    assert set(man[folder.name]["files"]) == files
    assert all(sha256_file(folder / n) == h for n, h in man[folder.name]["files"].items())
