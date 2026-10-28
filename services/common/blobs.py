"""Content-addressed blob store (local disk by default). Keys are sha256 hex of the bytes.

Printable files (STL, 3MF, STEP, and zips that contain them) are gated by the export gate when served: a small owner
index (`claim` / `owners`) records which job or registry part handed a key out, so the API can find the verification
record that decides whether the file may leave. Previews (GLB, images, JSON, code) are not gated.
"""

from __future__ import annotations

import hashlib
import mimetypes
from pathlib import Path

from .paths import REPO_ROOT, blobs_dir

REPLAY_BLOBS = REPO_ROOT / "data" / "replays" / "_blobs"
PRINTABLE_EXTS = frozenset({".stl", ".3mf", ".step", ".stp", ".zip"})
OWNERS_DIR = "_owners"


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


def is_printable(key: str) -> bool:
    """True for keys whose extension is a printable model file (or a zip that may contain one)."""
    _, ext = _split(key)
    return ext.lower() in PRINTABLE_EXTS


def _owners_path(key: str) -> Path:
    sha, _ = _split(key)
    _path(sha, "")  # validates the key
    return blobs_dir() / OWNERS_DIR / sha[:2] / f"{sha}.txt"


def claim(key: str, owner: str) -> None:
    """Record that `owner` (`"job:<id>"` or `"part:<slug>"`) handed out `key` (a blob key, or a bake cache key —
    any sha256 hex). Idempotent; an append-only text file per key, so concurrent claims cannot lose each other."""
    if not owner or "\n" in owner:
        raise ValueError(f"bad owner {owner!r}")
    if owner in owners(key):
        return
    path = _owners_path(key)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(owner + "\n")


def owners(key: str) -> list[str]:
    """Owners claimed for `key`, oldest first, without duplicates (empty when nobody claimed it)."""
    path = _owners_path(key)
    if not path.exists():
        return []
    seen: dict[str, None] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            seen.setdefault(line.strip(), None)
    return list(seen)


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
