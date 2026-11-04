"""Render the scale evaluation's datasets (eval/SCALE_PLAN.md) into var/scale_data, with each top photo's exact part mask.

    uv run python -m eval.scale_data --jobs 8

The masks are the renderer's own coverage, saved beside the samples and read only by the SAM scorer; agents never see them.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
from collections.abc import Callable
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import yaml

REPO = Path(__file__).resolve().parents[1]
ROOT = REPO / "var" / "scale_data"
SEED = 20261105
N_TEMPLATES, N_PS, N_B1, N_REFERENCE, N_BROKEN, N_CONTROL, REDTEAM_SEEDS, N_SAM = 370, 200, 100, 60, 30, 40, 4, 500


def _with_mask(mask_path: Path, fn: Callable[[], Path]) -> Path:
    """Run a sample render, saving the first render's coverage (the top view) as the sample's exact mask."""
    from tools.synth import dataset as synth_dataset

    dataset: Any = synth_dataset
    orig = dataset.render_photo
    seen: list[Any] = []

    def spy(*args: Any, **kwargs: Any) -> Any:
        r = orig(*args, **kwargs)
        seen.append(r)
        return r

    dataset.render_photo = spy
    try:
        out = fn()
    finally:
        dataset.render_photo = orig
    if seen:
        mask_path.parent.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(mask_path), np.clip(seen[0].alpha * 255.0, 0, 255).astype(np.uint8))
    return out


def render_one(item: tuple[str, Any, int]) -> dict[str, Any]:
    """One sample. A sample that cannot be rendered is reported, not hidden."""
    from tools.synth import generate_sample
    from tools.synth.dataset import default_sample_id

    suite, spec, seed = item
    sid = spec.sample_id or default_sample_id(spec, seed)
    try:
        folder = _with_mask(
            ROOT / "masks" / suite / f"{sid}.png", lambda: generate_sample(spec, ROOT / suite, seed=seed)
        )
    except Exception as exc:  # a template and break that cannot be combined is a dataset note
        return {"suite": suite, "id": sid, "error": f"{type(exc).__name__}: {exc}"[:200]}
    if suite.startswith("control"):
        from tools.synth.suites import Expect

        raw = yaml.safe_load((folder / "gt.yaml").read_text())
        raw["expect"] = Expect("accept", (), "intact part, normal photo").to_dict()
        (folder / "gt.yaml").write_text(yaml.safe_dump(raw, sort_keys=False, width=120, default_flow_style=None))
    return {"suite": suite, "id": folder.name, "preset": spec.preset, "template": spec.name, "kind": spec.kind}


def redteam_one(item: tuple[Any, int, int]) -> dict[str, Any]:
    from tools.synth.suites import render_redteam_case

    case, k, seed = item
    folder = render_redteam_case(case, ROOT / "redteam" / f"k{k}", seed=seed)
    return {
        "suite": "redteam",
        "id": f"{case.id}-k{k}",
        "dir": str(folder.relative_to(ROOT)),
        "preset": "redteam",
        "kind": "redteam",
    }


def plan() -> tuple[list[tuple[str, Any, int]], list[tuple[Any, int, int]]]:
    from services.agent.templates import list_templates
    from tools.synth.dataset import dataset_specs
    from tools.synth.suites import REDTEAM, control_specs

    items: list[tuple[str, Any, int]] = []
    specs = dataset_specs(N_TEMPLATES, SEED, n_reference=N_REFERENCE)
    templates = [(s, sd) for s, sd in specs if s.kind == "template"]
    references = [(s, sd) for s, sd in specs if s.kind == "reference_object"]
    items += [("synthetic", s, sd) for s, sd in templates[:N_PS]]
    items += [("extra", s, sd) for s, sd in templates[N_PS:]]
    items += [("reference_objects", s, sd) for s, sd in references]
    names = sorted(t.name for t in list_templates())
    kinds = ("tip", "tab", "corner")
    for i in range(N_BROKEN):
        spec = dataclasses.replace(
            templates[i][0], name=names[i % len(names)], preset="clean", broken=kinds[i % 3], sample_id=None
        )
        items.append(("broken", spec, SEED % 1000 + 1000 + i))
    for spec, sd in control_specs(N_CONTROL, SEED):
        items.append(("control_top", spec, sd))
        items.append(("control_side", dataclasses.replace(spec, views=("top", "side")), sd))
    red = [(c, k, SEED + 100 * k + i) for k in range(REDTEAM_SEEDS) for i, c in enumerate(REDTEAM)]
    return items, red


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--jobs", type=int, default=8)
    a = ap.parse_args()
    items, red = plan()
    ROOT.mkdir(parents=True, exist_ok=True)
    with ProcessPoolExecutor(max_workers=a.jobs) as ex:
        rows = list(ex.map(render_one, items, chunksize=2))
        rows += list(ex.map(redteam_one, red))
    (ROOT / "manifest.json").write_text(json.dumps({"seed": SEED, "samples": rows}, indent=1))
    errors = [r for r in rows if r.get("error")]
    print(f"rendered {len(rows) - len(errors)}, could not render {len(errors)}")
    for e in errors[:20]:
        print(" ", e["suite"], e["id"], e["error"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
