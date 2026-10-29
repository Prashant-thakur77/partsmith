"""SYNTHETIC "where it fits" photos: a socket, a shaft, a slot or a panel edge on the mat, with exact ground truth.

Each scene is rendered with the exact projective model in `services.metrology.testing` (same K, R, t as the
metrology; anti-aliased coverage of the true geometry), plus mild blur, noise and JPEG. The tap pixel is the feature's
centre projected at its own height, as a user would tap it. Every photo is labelled synthetic by the caller.

    uv run python -m tools.synth.mating --out data/synthetic/mating     # writes <kind>/mating.jpg + gt.json
"""

from __future__ import annotations

import argparse
import json
import math
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

import cv2
import numpy as np
from numpy.typing import NDArray

from services.metrology import testing as T
from services.metrology.mats import get_mat

F64 = NDArray[np.float64]
I64 = NDArray[np.int64]
U8 = NDArray[np.uint8]
MateScene = Literal["socket", "shaft", "slot", "panel"]
SCENES: tuple[MateScene, ...] = ("socket", "shaft", "slot", "panel")
MATE_KIND: dict[MateScene, str] = {
    "socket": "mate_hole",
    "shaft": "mate_peg",
    "slot": "mate_slot",
    "panel": "mate_slot",
}
MATE_BGR = (70, 82, 96)


@dataclass(frozen=True)
class MatingGT:
    scene: MateScene
    kind: str  # the tap kind a user would pick
    size_mm: float  # exact: socket / shaft diameter, slot / panel-edge width
    material: str  # "opening" | "material"
    tap_px: tuple[float, float]
    mat_id: str
    camera_height_mm: float
    tilt_deg: float
    origin: str = "synthetic"


def cylinder_lying(
    d_mm: float, length_mm: float, centre: tuple[float, float], yaw_deg: float = 0.0, n: int = 360
) -> tuple[F64, I64]:
    """Triangle mesh of a round shaft lying on the mat (mat frame: z into the table, so it spans z ∈ [−d, 0])."""
    a = np.linspace(0, 2 * np.pi, n, endpoint=False)
    r = d_mm / 2
    ring = np.c_[r * np.cos(a), -r - r * np.sin(a)]  # (across, z): touches z = 0 at the bottom
    xs = (-length_mm / 2, length_mm / 2)
    c, s = math.cos(math.radians(yaw_deg)), math.sin(math.radians(yaw_deg))
    verts = []
    for x in xs:
        for yy, zz in ring:
            verts.append([centre[0] + c * x - s * yy, centre[1] + s * x + c * yy, zz])
    verts.append([centre[0] + c * xs[0], centre[1] + s * xs[0], -r])
    verts.append([centre[0] + c * xs[1], centre[1] + s * xs[1], -r])
    faces = []
    for i in range(n):
        j = (i + 1) % n
        faces += [[i, j, n + j], [i, n + j, n + i], [2 * n, j, i], [2 * n + 1, n + i, n + j]]
    return np.asarray(verts, dtype=np.float64), np.asarray(faces, dtype=np.int64)


def _finish(img: U8, seed: int) -> U8:
    out = T.blur(img, 0.7)
    out = T.add_noise(out, 2.0, seed=seed)
    return T.jpeg(out, 92)


def render_mating(
    scene: MateScene,
    size_mm: float,
    *,
    mat_id: str = "screen-l",
    height_mm: float = 320.0,
    tilt_deg: float = 12.0,
    azimuth_deg: float = 30.0,
    offset_mm: tuple[float, float] = (12.0, -6.0),
    seed: int = 0,
    image_size: tuple[int, int] = (2000, 1500),
) -> tuple[U8, MatingGT, T.Camera]:
    """One synthetic mating photo with its exact ground truth and the camera (for tests that pass K)."""
    st = get_mat(mat_id).stage
    centre = (st.x_mm + st.w_mm / 2, st.y_mm + st.h_mm / 2)
    cam = T.camera_above(centre, height_mm=height_mm, tilt_deg=tilt_deg, azimuth_deg=azimuth_deg,
                         f_px=1.25 * image_size[0], size=image_size)  # fmt: skip
    fx, fy = centre[0] + offset_mm[0], centre[1] + offset_mm[1]
    part: T.PrismPart | tuple[F64, I64]
    if scene == "socket":
        plate_h = 2.0
        part = T.PrismPart(T.rounded_rect_poly(fx, fy, 44, 34, 3), [T.circle_poly(fx, fy, size_mm)], plate_h,
                           MATE_BGR, (50, 58, 68))  # fmt: skip
        tap_z, material = -plate_h / 2, "opening"
    elif scene == "slot":
        plate_h = 2.0
        part = T.PrismPart(T.rounded_rect_poly(fx, fy, 50, 30, 3), [T.rect_poly(fx, fy, 22, size_mm, 15.0)], plate_h,
                           MATE_BGR, (50, 58, 68))  # fmt: skip
        tap_z, material = -plate_h / 2, "opening"
    elif scene == "panel":
        edge_h = 2.0  # a panel offcut standing on its edge, 2 mm tall: its top edge is the width the clip holds
        part = T.PrismPart(T.rect_poly(fx, fy, 50, size_mm, 15.0), [], edge_h, MATE_BGR, (50, 58, 68))
        tap_z, material = -edge_h, "material"
    else:
        part = cylinder_lying(size_mm, 44.0, (fx, fy), yaw_deg=20.0)
        tap_z, material = -size_mm, "material"
    sc = T.render_scene(mat_id, cam.K, cam.R, cam.t, cam.size, part, part_bgr=MATE_BGR)
    u, v = cam.project(np.array([[fx, fy, tap_z]]))[0]
    gt = MatingGT(scene, MATE_KIND[scene], float(size_mm), material, (float(u), float(v)), mat_id, height_mm, tilt_deg)
    return _finish(sc.image, seed), gt, cam


def write_set(out: Path, sizes: Sequence[tuple[MateScene, float]] = (("socket", 8.0), ("shaft", 6.0), ("slot", 3.0),
                                                                     ("panel", 3.0))) -> list[dict[str, object]]:  # fmt: skip
    """Write `<scene>/mating.jpg` and `<scene>/gt.json` (exact, synthetic) for each (scene, size)."""
    rows = []
    for i, (scene, size) in enumerate(sizes):
        img, gt, _ = render_mating(scene, size, seed=i)
        d = out / scene
        d.mkdir(parents=True, exist_ok=True)
        ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 95])
        if not ok:
            raise RuntimeError("JPEG encode failed")
        (d / "mating.jpg").write_bytes(buf.tobytes())
        row = asdict(gt)
        (d / "gt.json").write_text(json.dumps(row, indent=1) + "\n")
        rows.append(row)
    return rows


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m tools.synth.mating", description="Render SYNTHETIC mating photos.")
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args(argv)
    for row in write_set(a.out):
        print(f"{row['scene']}: {row['kind']} {row['size_mm']} mm -> {a.out / str(row['scene'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
