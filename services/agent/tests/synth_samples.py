"""Test helper: render SYNTHETIC mat photos of a template part at known params and write the sample folder format.

The ground truth goes to gt.yaml (only tests read it); the agent sees top.png + meta.json like any user upload.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from services.agent.templates import get_template
from services.geom_worker.sandbox import run_program
from services.metrology import testing as T
from services.metrology.mats import get_mat

MAT = "screen-l"


@dataclass
class SampleSpec:
    id: str
    template: str
    params: dict[str, float]
    thickness_mm: float  # what the user would say ("it's 6 mm thick")
    family_hint: str | None = None
    intent: str = ""
    mat_id: str = MAT
    pose: tuple[float, float, float] = (3.0, -2.0, 20.0)  # dx, dy from the stage centre (mm), rotation (deg)
    part_bgr: tuple[int, int, int] = (60, 70, 85)
    stage_bgr: tuple[int, int, int] | None = None  # None = the light stage
    camera: dict[str, float] = field(default_factory=lambda: {"height_mm": 420.0, "tilt_deg": 4.0, "azimuth_deg": 30.0})


def place(vertices: np.ndarray[Any, Any], cx: float, cy: float, theta_deg: float) -> np.ndarray[Any, Any]:
    """CAD frame (Z up) → mat frame (y down, z into the table): T = translate(cx, cy) · Rz(θ) · diag(1, −1, −1)."""
    c, s = math.cos(math.radians(theta_deg)), math.sin(math.radians(theta_deg))
    x, y, z = vertices[:, 0], -vertices[:, 1], -vertices[:, 2]
    return np.asarray(np.c_[cx + c * x - s * y, cy + s * x + c * y, z], dtype=np.float64)


def render_top(spec: SampleSpec, params: dict[str, float] | None = None) -> bytes:
    t = get_template(spec.template)
    res = run_program(t.code, {**t.defaults, **(params or spec.params)}, outputs=())
    if not res.ok or res.mesh is None:
        raise RuntimeError(f"{spec.template} failed: {res.error}")
    st = get_mat(spec.mat_id).stage
    cx, cy = st.x_mm + st.w_mm / 2, st.y_mm + st.h_mm / 2
    V = place(res.mesh.vertices, cx + spec.pose[0], cy + spec.pose[1], spec.pose[2])
    c = spec.camera
    cam = T.camera_above((cx, cy), height_mm=c["height_mm"], tilt_deg=c["tilt_deg"], azimuth_deg=c["azimuth_deg"])
    sc = T.render_scene(
        spec.mat_id,
        cam.K,
        cam.R,
        cam.t,
        cam.size,
        (V, res.mesh.faces),
        part_bgr=spec.part_bgr,
        stage_bgr=spec.stage_bgr,
    )
    res.cleanup()
    return T.encode_png(sc.image)


def write_sample(spec: SampleSpec, root: Path) -> Path:
    d = root / spec.id
    d.mkdir(parents=True, exist_ok=True)
    (d / "top.png").write_bytes(render_top(spec))
    meta: dict[str, Any] = {
        "id": spec.id,
        "title": f"{get_template(spec.template).title} (test sample)",
        "kind": "template",
        "origin": "synthetic",
        "mat_id": spec.mat_id,
        "family_hint": spec.family_hint,
        "intent": spec.intent,
        "user_thickness_mm": spec.thickness_mm,
        "difficulty": "easy",
        "augmentations": [],
        "seed": 0,
    }
    (d / "meta.json").write_text(json.dumps(meta, indent=2))
    gt = ["gt_source: synthetic_exact", f"template: {spec.template}", "params:"]
    gt += [f"  {k}: {v}" for k, v in spec.params.items()]
    (d / "gt.yaml").write_text("\n".join(gt) + "\n")
    return d


def hex_bgr(h: str) -> tuple[int, int, int]:
    r, g, b = (int(h[i : i + 2], 16) for i in (1, 3, 5))
    return b, g, r


SAMPLES = [
    SampleSpec(
        "latch-01",
        "cupboard_latch",
        {"length": 52.4, "width": 16.3, "thickness": 6.0, "pivot_d": 4.6, "pivot_offset": 10.0},
        6.0,
        family_hint="latch",
        intent="the turn button latch snapped",
    ),
    SampleSpec("spacer-01", "spacer", {"outer_d": 20.4, "bore_d": 8.6, "height": 12.0}, 12.0, family_hint="spacer"),
    SampleSpec(
        "cover-01",
        "battery_cover",
        {"length": 56.3, "width": 32.4, "thickness": 1.6, "corner_radius": 4.5},
        1.6,
        family_hint="cover",
        intent="remote battery cover lost",
    ),
]
