"""CLI: render a SYNTHETIC dataset or the committed demo set.

uv run python -m tools.synth --out data/synthetic/bench --n 200 --seed 7 [--n-reference 20] [--jobs 4]
uv run python -m tools.synth --demo --out data/synthetic/samples
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from .dataset import BENCH_PRESETS, PRESETS, make_dataset
from .demo import make_demo_set


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m tools.synth", description="Render SYNTHETIC samples with exact GT.")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--n", type=int, default=200, help="template samples")
    ap.add_argument("--n-reference", type=int, default=0, help="reference-object samples")
    ap.add_argument("--n-reject", type=int, default=0, help="white-on-light photos the capture gate should reject")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--presets", default=",".join(BENCH_PRESETS), help=f"comma list from {', '.join(PRESETS)}")
    ap.add_argument("--size", default="3000x2250", help="photo size WxH")
    ap.add_argument("--quality", type=int, default=90, help="JPEG quality")
    ap.add_argument("--jobs", type=int, default=1, help="parallel render processes")
    ap.add_argument("--manifest", type=Path, default=None, help="also copy manifest.json here")
    ap.add_argument("--demo", action="store_true", help="render the committed demo set instead")
    a = ap.parse_args(argv)
    if a.demo:
        man = make_demo_set(a.out)
        print(f"demo set: {len(man['samples'])} samples -> {a.out}")
        return 0
    w, h = (int(x) for x in a.size.lower().split("x"))
    man = make_dataset(
        a.out,
        n=a.n,
        seed=a.seed,
        presets=[p.strip() for p in a.presets.split(",") if p.strip()],
        n_reference=a.n_reference,
        n_reject=a.n_reject,
        size=(w, h),
        jpeg_quality=a.quality,
        jobs=a.jobs,
        progress=True,
    )
    if a.manifest is not None:
        a.manifest.write_text(json.dumps(man, indent=1) + "\n")
    print(f"{len(man['samples'])} samples, {len(man['failures'])} failures, sha256 {man['dataset_sha256'][:16]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
