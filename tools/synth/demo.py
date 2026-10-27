"""The small committed demo set (`data/synthetic/samples/`): every family template at least once, screen and paper
mats, hard cases (a light part on the dark stage, a light part on the light stage that the capture gate
should reject, glare), three broken parts (GT = the intact part), walk-around clips on six samples, and the four
reference objects. All SYNTHETIC. Regenerate with
`uv run python -m tools.synth --demo --out data/synthetic/samples`."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .dataset import SampleSpec, sha256_file

DEMO_SIZE = (2000, 1500)
DEMO_QUALITY = 88

# (sample_id, kind, name, preset, mat_id or None, seed)
DEMO: tuple[tuple[str, str, str, str, str | None, int], ...] = (
    ("demo-l-bracket", "template", "l_bracket", "clean", "screen-m", 101),
    ("demo-cable-clip", "template", "cable_clip", "paper", "paper-a4", 102),
    ("demo-caster-wheel", "template", "caster_wheel", "clean", "screen-l", 103),
    ("demo-clip-tilt", "template", "clip", "tilt", "screen-m", 104),
    ("demo-cupboard-latch", "template", "cupboard_latch", "clean", "screen-m", 105),
    ("demo-hinge-leaf", "template", "hinge_leaf", "clean", "screen-l", 106),
    ("demo-hook", "template", "hook", "paper", "paper-a4", 107),
    ("demo-knob", "template", "knob", "clean", "screen-m", 108),
    ("demo-spacer", "template", "spacer", "clean", "screen-s", 109),
    ("demo-battery-cover", "template", "battery_cover", "clean", "screen-m", 110),
    ("demo-hard-white-cover", "template", "battery_cover", "white-part", "screen-m", 111),
    ("demo-hard-glare-clip", "template", "clip", "glare", "screen-m", 112),
    ("demo-hard-white-on-light", "template", "battery_cover", "white-on-light", "screen-m", 113),
    ("demo-broken-hook-tip", "template", "hook", "clean", "screen-m", 121),
    ("demo-broken-cover-tab", "template", "battery_cover", "clean", "screen-m", 122),
    ("demo-broken-latch-corner", "template", "cupboard_latch", "paper", "paper-a4", 123),
    ("demo-ref-id1-card", "reference_object", "id1_card", "clean", "screen-m", 201),
    ("demo-ref-sd-card", "reference_object", "sd_card", "clean", "screen-m", 202),
    ("demo-ref-lego-2x4", "reference_object", "lego_2x4", "paper", "paper-a4", 203),
    ("demo-ref-aa-cell", "reference_object", "aa_cell", "clean", "screen-m", 204),
)
# samples that also get a walk-around clip (orbit.mp4 + gt_frames.json)
DEMO_ORBIT = frozenset(
    {"demo-l-bracket", "demo-caster-wheel", "demo-clip-tilt", "demo-hook", "demo-knob", "demo-broken-hook-tip"}
)
DEMO_BROKEN = {"demo-broken-hook-tip": "tip", "demo-broken-cover-tab": "tab", "demo-broken-latch-corner": "corner"}


def demo_specs() -> list[tuple[SampleSpec, int]]:
    out: list[tuple[SampleSpec, int]] = []
    for sid, kind, name, preset, mat, seed in DEMO:
        views = ("top", "side", "orbit") if sid in DEMO_ORBIT else ("top", "side")
        spec = SampleSpec(
            kind,  # type: ignore[arg-type]
            name,
            preset,
            views=views,
            mat_id=mat,
            size=DEMO_SIZE,
            jpeg_quality=DEMO_QUALITY,
            sample_id=sid,
            broken=DEMO_BROKEN.get(sid),
        )
        out.append((spec, seed))
    return out


def make_demo_set(out_root: str | Path, *, jobs: int = 1) -> dict[str, Any]:
    """Render the demo set (in parallel processes when jobs > 1; same bytes either way) and write
    `out_root/manifest.json`."""
    from .dataset import _generate_one

    root = Path(out_root)
    root.mkdir(parents=True, exist_ok=True)
    specs = demo_specs()
    work = [(spec, seed, str(root)) for spec, seed in specs]
    if jobs > 1:
        from concurrent.futures import ProcessPoolExecutor

        with ProcessPoolExecutor(max_workers=jobs) as ex:
            results = list(ex.map(_generate_one, work, chunksize=1))
    else:
        results = [_generate_one(w) for w in work]
    entries = []
    for (spec, seed), (folder_s, err) in zip(specs, results, strict=True):
        if folder_s is None:
            raise RuntimeError(f"demo sample {spec.sample_id} failed: {err}")
        folder = Path(folder_s)
        entries.append(
            {
                "id": folder.name,
                "kind": spec.kind,
                "name": spec.name,
                "preset": spec.preset,
                "seed": seed,
                "files": {p.name: sha256_file(p) for p in sorted(folder.iterdir()) if p.is_file()},
            }
        )
    man = {
        "origin": "synthetic",
        "set": "demo",
        "size": list(DEMO_SIZE),
        "jpeg_quality": DEMO_QUALITY,
        "samples": entries,
    }
    (root / "manifest.json").write_text(json.dumps(man, indent=1) + "\n")
    return man
