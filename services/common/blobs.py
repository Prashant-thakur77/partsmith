"""Content-addressed blob store (local disk by default). Keys are sha256 hex of the bytes."""

from __future__ import annotations

import hashlib
import mimetypes
from pathlib import Path

from .paths import REPO_ROOT, blobs_dir

REPLAY_BLOBS = REPO_ROOT / "data" / "replays" / "_blobs"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def put(data: bytes, ext: str = "") -> str:
    """Store bytes and return their sha256. `ext` (e.g. ".png") is kept so files are servable with a content type."""
    sha = sha256_bytes(data)
    path = _path(sha, ext)
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_bytes(data)
        tmp.replace(path)
    return sha + ext


def get(key: str) -> bytes:
    return locate(key).read_bytes()


def locate(key: str) -> Path:
    """Path of a blob: the runtime store first, then the committed replay store (data/replays/_blobs)."""
    sha, ext = _split(key)
    primary = _path(sha, ext)
    if not primary.exists():
        fallback = REPLAY_BLOBS / sha[:2] / (sha + ext)
        if fallback.exists():
            return fallback
    return primary


def exists(key: str) -> bool:
    return locate(key).exists()


def content_type(key: str) -> str:
    _, ext = _split(key)
    return mimetypes.guess_type("x" + ext)[0] or "application/octet-stream"


def copy_to_replays(key: str) -> None:
    """Make a blob available to committed replays (judge path works on a fresh clone)."""
    sha, ext = _split(key)
    src = locate(key)
    dest = REPLAY_BLOBS / sha[:2] / (sha + ext)
    if src.exists() and not dest.exists():
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(src.read_bytes())


def url(key: str) -> str:
    return f"/api/v1/blobs/{key}"


def _split(key: str) -> tuple[str, str]:
    if "." in key:
        sha, ext = key.split(".", 1)
        return sha, "." + ext
    return key, ""


def _path(sha: str, ext: str) -> Path:
    if len(sha) != 64 or any(c not in "0123456789abcdef" for c in sha):
        raise ValueError(f"not a sha256 key: {sha!r}")
    return blobs_dir() / sha[:2] / (sha + ext)
