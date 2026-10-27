"""Filesystem locations. Runtime data lives under $PARTSMITH_HOME (default <repo>/var, gitignored)."""

from __future__ import annotations

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def home() -> Path:
    root = Path(os.environ.get("PARTSMITH_HOME", REPO_ROOT / "var")).resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def sub(name: str) -> Path:
    p = home() / name
    p.mkdir(parents=True, exist_ok=True)
    return p


def blobs_dir() -> Path:
    return sub("blobs")


def runs_dir() -> Path:
    return sub("runs")


def bakes_dir() -> Path:
    return sub("bakes")
