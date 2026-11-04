"""How long a knob change takes once a part program exists: fresh re-bakes of the stored battery cover in a warm worker.

    uv run python -m eval.rebake  ->  eval/reports/latest/rebake.json

This is the wait for the next person who wants the part at another size: no model call, only the sandboxed CadQuery
program at new knob values. Each sample uses a length no earlier sample used, so nothing comes from the bake cache.
"""

from __future__ import annotations

import json
import statistics
import tempfile
from pathlib import Path

from services.geom_worker import bake as geom_bake
from services.geom_worker.sandbox import WarmPool

ROOT = Path(__file__).resolve().parents[1]
RUN = "j_261029_daf26965"
OUT = ROOT / "eval" / "reports" / "latest" / "rebake.json"
LENGTHS_MM = (46.1, 46.7, 47.3, 47.9, 48.5, 49.1, 49.7)
WARMUP = 2  # the first bakes wake the worker; a running server has this behind it already


def measure() -> dict[str, object]:
    code = (ROOT / "data" / "replays" / RUN / "part.py").read_text(encoding="utf-8")
    pool = WarmPool()
    pool.warm()
    samples: list[int] = []
    with tempfile.TemporaryDirectory() as tmp:
        for length in LENGTHS_MM:
            out = geom_bake.bake(code, {"length": length}, ("stl",), pool=pool, root=Path(tmp))
            if out.cache_hit:
                raise RuntimeError("a fresh length came from the cache")
            samples.append(out.ms)
    kept = samples[WARMUP:]
    return {
        "part": "battery cover (stored live run)",
        "run": RUN,
        "formats": ["stl"],
        "n": len(kept),
        "median_ms": statistics.median(kept),
        "max_ms": max(kept),
        "samples_ms": samples,
        "dropped_warmup": WARMUP,
        "note": "fresh bakes in a warm sandbox worker on the build laptop; no model call and no cache hit",
    }


def main() -> None:
    report = measure()
    OUT.write_text(json.dumps(report, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=1))


if __name__ == "__main__":
    main()
