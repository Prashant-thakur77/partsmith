"""SYNTHETIC orbit clips: a phone walking 120–180° around the part on the mat, as an H.264 MP4, with exact per-frame GT.

The camera path is smooth (azimuth sweep, tilt 20–55° from straight down, slant distance 200–320 mm) with hand shake
(band-limited jitter on every pose parameter) and motion blur along each frame's image motion. Every frame is a full
`render.render_photo` with the clip's look, so the presets (glare, moiré, low light, …) apply to video too. Phone video
is denoised in-camera, so sensor noise is lower than in stills. Per-frame K, R, t go to `gt_frames.json` (scorers only).
"""

from __future__ import annotations

import dataclasses
import math
import shutil
import subprocess
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
from numpy.typing import NDArray

from services.metrology import testing as T
from services.metrology.calibrate import intrinsics_from_focal35

from .render import I64, Look, render_photo

F64 = NDArray[np.float64]
U8 = NDArray[np.uint8]

ORBIT_SIZE = (1920, 1080)
ORBIT_FPS = 15
SHUTTER = 0.5  # fraction of the frame interval the shutter is open (motion blur length)


@dataclass(frozen=True)
class OrbitPlan:
    duration_s: float
    fps: int
    sweep_deg: float
    start_az_deg: float
    tilt_deg: tuple[float, float]  # start, end
    distance_mm: tuple[float, float]  # slant distance start, end
    focal35_mm: float
    size: tuple[int, int] = ORBIT_SIZE

    @property
    def n_frames(self) -> int:
        return round(self.duration_s * self.fps)


def sample_plan(rng: np.random.Generator, *, size: tuple[int, int] = ORBIT_SIZE, fps: int = ORBIT_FPS) -> OrbitPlan:
    u = rng.uniform
    return OrbitPlan(
        duration_s=round(float(u(6.0, 8.0)), 2),
        fps=fps,
        sweep_deg=float(u(120.0, 180.0)) * (1 if u() < 0.5 else -1),
        start_az_deg=float(u(0.0, 360.0)),
        tilt_deg=(float(u(20.0, 38.0)), float(u(35.0, 55.0))),
        distance_mm=(float(u(220.0, 320.0)), float(u(200.0, 300.0))),
        focal35_mm=float(u(24.0, 28.0)),
        size=size,
    )


def _smooth_noise(rng: np.random.Generator, n: int, amp: float, corr_frames: float) -> F64:
    """Band-limited jitter (hand shake): white noise low-passed over `corr_frames`, scaled to rms `amp`."""
    x = rng.standard_normal(n + 40)
    k = max(1, int(corr_frames))
    y = np.convolve(x, np.hanning(2 * k + 1), mode="same")[20 : 20 + n]
    sd = float(np.std(y)) or 1.0
    return np.asarray(y / sd * amp, dtype=np.float64)


def orbit_cameras(plan: OrbitPlan, target_mm: tuple[float, float], rng: np.random.Generator) -> list[T.Camera]:
    """One camera per frame looking at `target_mm` (mat frame) along the planned arc, with hand shake."""
    n = plan.n_frames
    s = np.linspace(0.0, 1.0, n)
    ease = 0.5 - 0.5 * np.cos(np.pi * s)  # walk starts and ends gently
    az = plan.start_az_deg + plan.sweep_deg * ease + _smooth_noise(rng, n, 0.8, 4)
    tilt = plan.tilt_deg[0] + (plan.tilt_deg[1] - plan.tilt_deg[0]) * ease + _smooth_noise(rng, n, 1.0, 5)
    dist = plan.distance_mm[0] + (plan.distance_mm[1] - plan.distance_mm[0]) * ease + _smooth_noise(rng, n, 4.0, 6)
    roll_j = _smooth_noise(rng, n, 1.5, 4)
    tx, ty = _smooth_noise(rng, n, 2.0, 6), _smooth_noise(rng, n, 2.0, 6)
    K = intrinsics_from_focal35(plan.focal35_mm, plan.size)
    cams: list[T.Camera] = []
    for i in range(n):
        tl = float(np.clip(tilt[i], 5.0, 60.0))
        # the phone is held level: image x runs across the walking direction, image "up" points away from the user
        cams.append(
            T.camera_above(
                (target_mm[0] + tx[i], target_mm[1] + ty[i]),
                height_mm=float(dist[i]) * math.cos(math.radians(tl)),
                tilt_deg=tl,
                azimuth_deg=float(az[i]),
                roll_deg=float(az[i]) + 90.0 + float(roll_j[i]),
                f_px=float(K[0, 0]),
                size=plan.size,
            )
        )
    return cams


def motion_blur(img: U8, velocity_px: tuple[float, float]) -> U8:
    """Linear blur along the frame's image motion (length = |v| × shutter)."""
    vx, vy = velocity_px[0] * SHUTTER, velocity_px[1] * SHUTTER
    length = math.hypot(vx, vy)
    if length < 1.0:
        return img
    n = math.ceil(length) | 1
    k = np.zeros((n, n), np.float32)
    c = n // 2
    for t in np.linspace(-0.5, 0.5, 4 * n):
        k[round(c + t * vy), round(c + t * vx)] += 1.0
    k /= k.sum()
    return np.asarray(cv2.filter2D(img, -1, k, borderType=cv2.BORDER_REFLECT), dtype=np.uint8)


def render_orbit(
    mat_id: str,
    cams: Sequence[T.Camera],
    vertices_mat: F64,
    faces: I64,
    look: Look,
    rng: np.random.Generator,
    target_mm: tuple[float, float],
) -> Iterator[U8]:
    """Frames rendered with the clip's look (per-frame noise, motion blur from the target's image motion). A generator,
    so a clip never sits in memory as a whole."""
    # in-camera video denoising: less sensor noise than a still
    video_look = dataclasses.replace(look, noise_read=look.noise_read * 0.4, noise_shot=look.noise_shot * 0.4)
    tgt = np.array([[target_mm[0], target_mm[1], 0.0]])
    for i, cam in enumerate(cams):
        r = render_photo(mat_id, cam, vertices_mat, faces, video_look, rng)
        a, b = max(i - 1, 0), min(i + 1, len(cams) - 1)
        v = (cams[b].project(tgt)[0] - cams[a].project(tgt)[0]) / max(b - a, 1)
        yield motion_blur(r.image, (float(v[0]), float(v[1])))


def encode_mp4(frames: Iterable[U8], fps: int, size: tuple[int, int], path: Path, *, crf: int = 27) -> str:
    """Stream frames into an MP4. ffmpeg + libx264 (yuv420p, faststart, bit-exact flags) when available, else OpenCV
    (avc1, then mp4v). Returns the encoder used."""
    w, h = size
    ff = shutil.which("ffmpeg")
    it = iter(frames)
    if ff:
        cmd = [
            ff, "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{w}x{h}", "-r", str(fps),
            "-i", "-", "-an", "-c:v", "libx264", "-preset", "medium", "-crf", str(crf), "-pix_fmt", "yuv420p",
            "-movflags", "+faststart", "-map_metadata", "-1", "-fflags", "+bitexact", "-flags:v", "+bitexact",
            str(path),
        ]  # fmt: skip
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
        assert proc.stdin is not None
        n = 0
        for f in it:
            proc.stdin.write(np.ascontiguousarray(f).tobytes())
            n += 1
        proc.stdin.close()
        if proc.wait() == 0 and n and path.exists() and path.stat().st_size > 0:
            return "ffmpeg/libx264"
        raise RuntimeError("ffmpeg failed to encode the clip")
    for fourcc, name in (("avc1", "opencv/avc1"), ("mp4v", "opencv/mp4v")):
        wr = cv2.VideoWriter(str(path), cv2.VideoWriter.fourcc(*fourcc), float(fps), (w, h))
        if not wr.isOpened():
            continue
        for f in it:
            wr.write(np.ascontiguousarray(f))
        wr.release()
        if path.exists() and path.stat().st_size > 0:
            return name
    raise RuntimeError("no MP4 encoder available (ffmpeg or OpenCV)")


def read_frames(path: Path, every: int = 1) -> list[U8]:
    """Decode an MP4 (tests and scorers)."""
    cap = cv2.VideoCapture(str(path))
    out: list[U8] = []
    i = 0
    while True:
        ok, f = cap.read()
        if not ok:
            break
        if i % every == 0:
            out.append(np.asarray(f, dtype=np.uint8))
        i += 1
    cap.release()
    return out
