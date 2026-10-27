"""The small committed demo set (`data/synthetic/samples/`): every family template at least once, screen and paper
mats, two hard cases, and the four reference objects. All SYNTHETIC. Regenerate with
`uv run python -m tools.synth --demo --out data/synthetic/samples`."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .dataset import SampleSpec, generate_sample, sha256_file

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
    ("demo-ref-id1-card", "reference_object", "id1_card", "clean", "screen-m", 201),
    ("demo-ref-sd-card", "reference_object", "sd_card", "clean", "screen-m", 202),
    ("demo-ref-lego-2x4", "reference_object", "lego_2x4", "paper", "paper-a4", 203),
    ("demo-ref-aa-cell", "reference_object", "aa_cell", "clean", "screen-m", 204),
)


def demo_specs() -> list[tuple[SampleSpec, int]]:
    return [
        (SampleSpec(kind, name, preset, mat_id=mat, size=DEMO_SIZE, jpeg_quality=DEMO_QUALITY, sample_id=sid), seed)  # type: ignore[arg-type]
        for sid, kind, name, preset, mat, seed in DEMO
    ]


def make_demo_set(out_root: str | Path) -> dict[str, Any]:
    """Render the demo set and write `out_root/manifest.json`."""
    root = Path(out_root)
    root.mkdir(parents=True, exist_ok=True)
    entries = []
    for spec, seed in demo_specs():
        folder = generate_sample(spec, root, seed=seed)
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
