"""Camera intrinsics from ≥ 10 photos of any PartSmith mat (marker corners as a planar target).

    uv run python -m tools.calib.calibrate_camera photos/*.jpg --out var/calib/pixel7-main.json

Take the photos at the zoom you will measure with, from different angles (straight down and tilted 20–40° in several
directions) and distances, with the mat filling a good part of the frame. Output JSON: `{K, dist, rms_px, image_size,
n_images, mat_ids, per_view_rms_px}`. `measure_photo(..., K=..., dist=...)` takes the result.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path

import cv2
import numpy as np
from numpy.typing import NDArray

from services.metrology.calibrate import MatNotFoundError, detect_mat

MIN_IMAGES = 10
MIN_MARKERS_PER_VIEW = 4


@dataclass
class CameraCalibration:
    K: list[list[float]]
    dist: list[float]
    rms_px: float
    image_size: tuple[int, int]
    n_images: int
    mat_ids: list[str]
    per_view_rms_px: list[float]


def calibrate_from_images(images: list[NDArray[np.uint8]], *, min_images: int = MIN_IMAGES) -> CameraCalibration:
    """`cv2.calibrateCamera` on marker corners (z = 0). Views with fewer than four markers are skipped.
    Raises `ValueError` when fewer than `min_images` usable views remain or the sizes differ."""
    obj_pts: list[NDArray[np.float32]] = []
    img_pts: list[NDArray[np.float32]] = []
    mats: set[str] = set()
    size: tuple[int, int] | None = None
    for img in images:
        h, w = img.shape[:2]
        if size is None:
            size = (w, h)
        elif size != (w, h):
            raise ValueError("all calibration photos must have the same size (same camera, zoom and orientation)")
        try:
            det = detect_mat(img)
        except MatNotFoundError:
            continue
        if det.n_markers < MIN_MARKERS_PER_VIEW:
            continue
        mats.add(det.mat.mat_id)
        obj_pts.append(np.c_[det.mat_pts, np.zeros(len(det.mat_pts))].astype(np.float32).reshape(-1, 1, 3))
        img_pts.append(det.corners_px.reshape(-1, 1, 2).astype(np.float32))
    if size is None or len(obj_pts) < min_images:
        raise ValueError(f"need at least {min_images} photos with ≥ {MIN_MARKERS_PER_VIEW} markers; got {len(obj_pts)}")
    flags = cv2.CALIB_FIX_K3
    rms, K, dist, rvecs, tvecs = cv2.calibrateCamera(obj_pts, img_pts, size, None, None, flags=flags)
    per_view = []
    for o, i, r, t in zip(obj_pts, img_pts, rvecs, tvecs, strict=True):
        proj, _ = cv2.projectPoints(o, r, t, K, dist)
        per_view.append(float(np.sqrt(np.mean(np.sum((proj - i) ** 2, axis=2)))))
    return CameraCalibration(
        K=np.asarray(K, dtype=np.float64).tolist(),
        dist=[float(x) for x in np.asarray(dist).ravel()],
        rms_px=float(rms),
        image_size=size,
        n_images=len(obj_pts),
        mat_ids=sorted(mats),
        per_view_rms_px=per_view,
    )


def load_intrinsics(path: str | Path) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    """(K, dist) from a calibration JSON written by this tool."""
    d = json.loads(Path(path).read_text())
    return np.asarray(d["K"], dtype=np.float64), np.asarray(d["dist"], dtype=np.float64)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("photos", nargs="+", type=Path)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args(argv)
    imgs = []
    for p in args.photos:
        im = cv2.imread(str(p), cv2.IMREAD_COLOR)
        if im is None:
            print(f"skip {p}: not an image")
            continue
        imgs.append(np.asarray(im, dtype=np.uint8))
    cal = calibrate_from_images(imgs)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(asdict(cal), indent=2) + "\n")
    print(f"wrote {args.out}: f = {cal.K[0][0]:.1f} px, rms {cal.rms_px:.3f} px over {cal.n_images} views")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
