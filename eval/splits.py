"""Assign real parts (data/real/<part>/gt.yaml) to the dev or held-out split and freeze the held-out hash.

Run: `uv run python -m eval.splits assign [--dev 10] [--seed 7]`. Rules:
- parts already in a split never move (a frozen held-out set stays frozen);
- new parts fill `dev` up to `--dev` first, in a seeded random order, the rest go to `held_out`;
- `held_out_sha256` = sha256 over the sorted held-out part ids and the bytes of each part's gt.yaml, so any later edit of a
  held-out ground truth is detectable (`check`).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SPLITS_LOCK = ROOT / "eval" / "splits.lock"
REAL_DIR = ROOT / "data" / "real"


def real_parts(real_dir: Path = REAL_DIR) -> list[str]:
    return sorted(p.parent.name for p in real_dir.glob("*/gt.yaml") if p.parent.name != "reference_objects")


def held_out_hash(ids: list[str], real_dir: Path = REAL_DIR) -> str | None:
    if not ids:
        return None
    h = hashlib.sha256()
    for pid in sorted(ids):
        h.update(pid.encode())
        h.update((real_dir / pid / "gt.yaml").read_bytes())
    return h.hexdigest()


def assign(
    lock: dict[str, Any], parts: list[str], *, n_dev: int, seed: int, real_dir: Path = REAL_DIR
) -> dict[str, Any]:
    rp = lock.setdefault("real_parts", {"gt_source": "ruler", "dev": [], "held_out": [], "held_out_sha256": None})
    dev, held = list(rp.get("dev", [])), list(rp.get("held_out", []))
    new = [p for p in parts if p not in dev and p not in held]
    random.Random(seed).shuffle(new)
    for pid in new:
        (dev if len(dev) < n_dev else held).append(pid)
    rp.update(dev=sorted(dev), held_out=sorted(held), held_out_sha256=held_out_hash(held, real_dir))
    rp["status"] = f"{len(dev)} dev / {len(held)} held-out real parts (ruler ground truth)"
    return lock


def check(lock: dict[str, Any], real_dir: Path = REAL_DIR) -> list[str]:
    """Problems with the frozen split: missing parts or edited held-out ground truth."""
    rp = lock.get("real_parts", {})
    held = list(rp.get("held_out", []))
    problems = [f"held-out part {p} has no gt.yaml" for p in held if not (real_dir / p / "gt.yaml").exists()]
    if not problems and rp.get("held_out_sha256") and held_out_hash(held, real_dir) != rp["held_out_sha256"]:
        problems.append("held-out ground truth changed since the split was frozen")
    return problems


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("assign", help="add new real parts to dev/held-out and freeze the held-out hash")
    a.add_argument("--dev", type=int, default=10)
    a.add_argument("--seed", type=int, default=7)
    sub.add_parser("check", help="verify the frozen held-out set")
    args = ap.parse_args(argv)
    lock = json.loads(SPLITS_LOCK.read_text())
    if args.cmd == "assign":
        lock = assign(lock, real_parts(), n_dev=args.dev, seed=args.seed)
        SPLITS_LOCK.write_text(json.dumps(lock, indent=2) + "\n")
        print(lock["real_parts"]["status"])
        return 0
    problems = check(lock)
    print("\n".join(problems) or "real-part split OK")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
