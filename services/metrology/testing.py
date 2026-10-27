"""Synthetic photos of parts on a mat, with exact ground truth (public: tests and the synthetic data generator use it).

A scene is a mat texture (exact area anti-aliasing) warped into a pinhole camera with known K, R, t, plus a part rendered
from its true 3D geometry (prisms with vertical walls, or any triangle mesh) with anti-aliased coverage. Everything is
labelled synthetic by the caller; nothing here pretends to be a real photo.

Frames: mat frame x right, y down, z into the table (a part of thickness h occupies z ∈ [−h, 0]); camera x right,
y down, z forward (OpenCV).
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

import cv2
import numpy as np
from numpy.typing import NDArray

from .mats import get_mat, render_mat

F64 = NDArray[np.float64]
F32 = NDArray[np.float32]
U8 = NDArray[np.uint8]
BGR = tuple[int, int, int]


@dataclass(frozen=True)
class Camera:
    K: F64
    R: F64  # mat -> camera
    t: F64
    size: tuple[int, int]  # (w, h)

    @property
    def center_mm(self) -> F64:
        return np.asarray(-self.R.T @ self.t, dtype=np.float64)

    @property
    def height_mm(self) -> float:
        return float(-self.center_mm[2])

    def project(self, X_mm: F64) -> F64:
        X = np.asarray(X_mm, dtype=np.float64).reshape(-1, 3)
        Xc = X @ self.R.T + self.t
        uv = Xc @ self.K.T
        return np.asarray(uv[:, :2] / uv[:, 2:3], dtype=np.float64)

    def H_mat_to_img(self, height_mm: float = 0.0) -> F64:
        """Homography mat (x, y) mm on the plane `height_mm` above the mat → image px."""
        M = self.K @ np.c_[self.R[:, 0], self.R[:, 1], self.t - height_mm * self.R[:, 2]]
        return np.asarray(M / M[2, 2], dtype=np.float64)


def make_K(f_px: float, size: tuple[int, int]) -> F64:
    w, h = size
    return np.array([[f_px, 0, (w - 1) / 2.0], [0, f_px, (h - 1) / 2.0], [0, 0, 1.0]])


def camera_above(
    target_mm: tuple[float, float],
    *,
    height_mm: float,
    tilt_deg: float = 0.0,
    azimuth_deg: float = 0.0,
    roll_deg: float = 0.0,
    f_px: float = 1500.0,
    size: tuple[int, int] = (1600, 1200),
) -> Camera:
    """Camera `height_mm` above the mat whose optical axis hits `target_mm`, tilted `tilt_deg` from straight down.

    `azimuth_deg` is the direction the camera looks along (0 = towards +x), `roll_deg` turns the image.
    """
    tl, az, rl = (math.radians(a) for a in (tilt_deg, azimuth_deg, roll_deg))
    d = np.array([math.sin(tl) * math.cos(az), math.sin(tl) * math.sin(az), math.cos(tl)])
    C = np.array([target_mm[0], target_mm[1], 0.0]) - (height_mm / math.cos(tl)) * d
    ex = np.array([math.cos(rl), math.sin(rl), 0.0])
    xc = ex - (ex @ d) * d
    xc /= np.linalg.norm(xc)
    yc = np.cross(d, xc)
    R = np.stack([xc, yc, d])
    return Camera(K=make_K(f_px, size), R=R, t=-R @ C, size=size)


# ---------------------------------------------------------------- parts


@dataclass
class PrismPart:
    """Extruded footprint (vertical walls) lying on the mat. Polygons are in mat mm."""

    outline_mm: F64
    holes_mm: list[F64] = field(default_factory=list)
    thickness_mm: float = 3.0
    top_bgr: BGR = (60, 70, 85)
    side_bgr: BGR = (40, 46, 56)
    base_mm: float = 0.0  # height of the prism's bottom face above the mat (overhangs, raised ribs)


def rect_poly(cx: float, cy: float, w: float, h: float, theta_deg: float = 0.0) -> F64:
    c, s = math.cos(math.radians(theta_deg)), math.sin(math.radians(theta_deg))
    pts = np.array([[-w / 2, -h / 2], [w / 2, -h / 2], [w / 2, h / 2], [-w / 2, h / 2]])
    return np.asarray(pts @ np.array([[c, s], [-s, c]]) + [cx, cy], dtype=np.float64)


def circle_poly(cx: float, cy: float, d: float, n: int = 720) -> F64:
    a = np.linspace(0, 2 * np.pi, n, endpoint=False)
    return np.asarray(np.c_[cx + d / 2 * np.cos(a), cy + d / 2 * np.sin(a)], dtype=np.float64)


def rounded_rect_poly(cx: float, cy: float, w: float, h: float, r: float, theta_deg: float = 0.0, n: int = 48) -> F64:
    pts: list[list[float]] = []
    for qx, qy, a0 in ((1, 1, 0.0), (-1, 1, 90.0), (-1, -1, 180.0), (1, -1, 270.0)):
        ox, oy = qx * (w / 2 - r), qy * (h / 2 - r)
        for a in np.radians(np.linspace(a0, a0 + 90.0, n)):
            pts.append([ox + r * math.cos(a), oy + r * math.sin(a)])
    p = np.array(pts)
    c, s = math.cos(math.radians(theta_deg)), math.sin(math.radians(theta_deg))
    return np.asarray(p @ np.array([[c, s], [-s, c]]) + [cx, cy], dtype=np.float64)


def slot_poly(cx: float, cy: float, length: float, width: float, theta_deg: float = 0.0, n: int = 90) -> F64:
    """Stadium (obround) of overall `length` × `width`."""
    r = width / 2
    a1 = np.radians(np.linspace(-90, 90, n))
    a2 = np.radians(np.linspace(90, 270, n))
    half = length / 2 - r
    p = np.r_[np.c_[half + r * np.cos(a1), r * np.sin(a1)], np.c_[-half + r * np.cos(a2), r * np.sin(a2)]]
    c, s = math.cos(math.radians(theta_deg)), math.sin(math.radians(theta_deg))
    return np.asarray(p @ np.array([[c, s], [-s, c]]) + [cx, cy], dtype=np.float64)


# ---------------------------------------------------------------- coverage rendering


def _ss_K(K: F64, ss: int) -> F64:
    S = np.array([[ss, 0, (ss - 1) / 2.0], [0, ss, (ss - 1) / 2.0], [0, 0, 1.0]])
    return S @ K


def rasterize(shape: tuple[int, int], groups: Sequence[Sequence[F64]]) -> NDArray[np.uint8]:
    """Exact point-sampled scanline fill: a pixel is set when its centre lies inside.

    Each group is a list of rings filled with the even-odd rule (outer + holes); groups are unioned. Unlike
    `cv2.fillPoly` (which rounds vertices and fills boundary pixels inclusively, inflating shapes by half a pixel),
    this keeps sub-pixel vertex positions, so supersampled coverage is unbiased.
    """
    h, w = shape
    xs_all: list[F64] = []
    rows_all: list[NDArray[np.int64]] = []
    gid_all: list[NDArray[np.int64]] = []
    for g, rings in enumerate(groups):
        for r in rings:
            p = np.asarray(r, dtype=np.float64).reshape(-1, 2)
            if len(p) < 3:
                continue
            q = np.roll(p, -1, axis=0)
            y0, y1 = p[:, 1], q[:, 1]
            ylo, yhi = np.minimum(y0, y1), np.maximum(y0, y1)
            r0 = np.clip(np.ceil(ylo), 0, h).astype(np.int64)
            r1 = np.clip(np.ceil(yhi), 0, h).astype(np.int64)  # rows r0 .. r1-1 satisfy ylo <= row < yhi
            cnt = r1 - r0
            keep = cnt > 0
            if not keep.any():
                continue
            e = np.flatnonzero(keep)
            cnt = cnt[e]
            edge = np.repeat(e, cnt)
            start = np.repeat(np.cumsum(cnt) - cnt, cnt)
            rows = np.repeat(r0[e], cnt) + (np.arange(cnt.sum()) - start)
            ya, yb, xa, xb = p[edge, 1], q[edge, 1], p[edge, 0], q[edge, 0]
            x = xa + (rows - ya) * (xb - xa) / (yb - ya)
            xs_all.append(x)
            rows_all.append(rows)
            gid_all.append(np.full(len(rows), g, dtype=np.int64))
    out = np.zeros(shape, np.uint8)
    if not xs_all:
        return out
    xs, rows, gid = np.concatenate(xs_all), np.concatenate(rows_all), np.concatenate(gid_all)
    order = np.lexsort((xs, rows, gid))
    xs, rows = xs[order], rows[order]
    xa, xb, rr = xs[0::2], xs[1::2], rows[0::2]
    ca = np.clip(np.ceil(xa), 0, w).astype(np.int64)
    cb = np.clip(np.ceil(xb), 0, w).astype(np.int64)
    diff = np.zeros((h, w + 1), np.int32)
    np.add.at(diff, (rr, ca), 1)
    np.add.at(diff, (rr, cb), -1)
    out[np.cumsum(diff, axis=1)[:, :w] > 0] = 255
    return out


def _fill_union(
    shape: tuple[int, int], polys: Sequence[Sequence[F64]], convex: Sequence[F64], off: tuple[float, float]
) -> NDArray[np.uint8]:
    """Union of polygons-with-holes (each a list of rings, even-odd) and simple polygons, offset by `off`."""
    o = np.array(off)
    groups = [[np.asarray(r) - o for r in grp] for grp in polys] + [[np.asarray(c) - o] for c in convex]
    return rasterize(shape, groups)


def prism_coverage(part: PrismPart, cam: Camera, ss: int = 4) -> tuple[F32, F32]:
    """Anti-aliased coverage of the whole part and of its top face (float32, full frame, 0..1)."""
    return prisms_coverage([part], cam, ss)


def prisms_coverage(parts: Sequence[PrismPart], cam: Camera, ss: int = 4) -> tuple[F32, F32]:
    """Coverage of a union of prisms (an L-bracket = plate + flange, a plate with a raised rib) and of their top faces."""
    w, h = cam.size
    Kss = _ss_K(cam.K, ss)
    camss = Camera(Kss, cam.R, cam.t, (w * ss, h * ss))

    def proj(r: F64, z: float) -> F64:
        return camss.project(np.c_[r, np.full(len(r), z)])

    faces: list[list[F64]] = []
    tops: list[list[F64]] = []
    walls: list[F64] = []
    for part in parts:
        z_bot, z_top = -part.base_mm, -(part.base_mm + part.thickness_mm)
        rings = [
            np.asarray(part.outline_mm, dtype=np.float64),
            *[np.asarray(r, dtype=np.float64) for r in part.holes_mm],
        ]
        top = [proj(r, z_top) for r in rings]
        bot = [proj(r, z_bot) for r in rings]
        faces += [top, bot]
        tops.append(top)
        for t_r, b_r in zip(top, bot, strict=True):
            n = len(t_r)
            for i in range(n):
                k = (i + 1) % n
                walls.append(np.array([b_r[i], b_r[k], t_r[k], t_r[i]]))
    allp = np.concatenate([r for f in faces for r in f])
    x0 = max(math.floor(allp[:, 0].min() / ss) - 2, 0)
    y0 = max(math.floor(allp[:, 1].min() / ss) - 2, 0)
    x1 = min(math.ceil(allp[:, 0].max() / ss) + 3, w)
    y1 = min(math.ceil(allp[:, 1].max() / ss) + 3, h)
    a_all = np.zeros((h, w), np.float32)
    a_top = np.zeros((h, w), np.float32)
    if x1 <= x0 or y1 <= y0:
        return a_all, a_top
    roi = ((y1 - y0) * ss, (x1 - x0) * ss)
    off = (float(x0 * ss), float(y0 * ss))
    m_all = _fill_union(roi, faces, walls, off)
    m_top = _fill_union(roi, tops, [], off)
    a_all[y0:y1, x0:x1] = cv2.resize(m_all.astype(np.float32) / 255, (x1 - x0, y1 - y0), interpolation=cv2.INTER_AREA)
    a_top[y0:y1, x0:x1] = cv2.resize(m_top.astype(np.float32) / 255, (x1 - x0, y1 - y0), interpolation=cv2.INTER_AREA)
    return a_all, np.minimum(a_top, a_all)


def mesh_coverage(vertices_mm: F64, faces: NDArray[np.int64], cam: Camera, ss: int = 4) -> F32:
    """Anti-aliased silhouette coverage of a triangle mesh given in MAT coordinates (z into the table)."""
    w, h = cam.size
    camss = Camera(_ss_K(cam.K, ss), cam.R, cam.t, (w * ss, h * ss))
    uv = camss.project(vertices_mm)
    x0 = max(math.floor(uv[:, 0].min() / ss) - 2, 0)
    y0 = max(math.floor(uv[:, 1].min() / ss) - 2, 0)
    x1 = min(math.ceil(uv[:, 0].max() / ss) + 3, w)
    y1 = min(math.ceil(uv[:, 1].max() / ss) + 3, h)
    out = np.zeros((h, w), np.float32)
    if x1 <= x0 or y1 <= y0:
        return out
    tris = [uv[f] for f in np.asarray(faces)]
    m = _fill_union(((y1 - y0) * ss, (x1 - x0) * ss), [], tris, (float(x0 * ss), float(y0 * ss)))
    out[y0:y1, x0:x1] = cv2.resize(m.astype(np.float32) / 255, (x1 - x0, y1 - y0), interpolation=cv2.INTER_AREA)
    return out


# ---------------------------------------------------------------- mat view


def render_mat_view(
    mat_id: str,
    cam: Camera,
    *,
    ss: int = 2,
    white_bgr: BGR = (232, 228, 224),
    black_bgr: BGR = (28, 26, 26),
    surround_bgr: BGR = (48, 46, 44),
    screen_margin_mm: float = 4.0,
    texture_px_per_mm: float | None = None,
    stage_bgr: BGR | None = None,
) -> U8:
    """The mat (plus a white margin standing for the rest of the screen / page) seen by `cam`; `surround_bgr` elsewhere.

    `stage_bgr` fills the plain stage with another colour (e.g. the screen mat's dark stage, `mats.STAGE_COLOURS`)."""
    mat = get_mat(mat_id)
    w, h = cam.size
    if texture_px_per_mm is None:
        res = cam.K[0, 0] / max(cam.height_mm, 1.0)
        texture_px_per_mm = float(np.clip(math.ceil(1.6 * ss * res), 8, 24))
    ppm = texture_px_per_mm
    tex = render_mat(mat_id, ppm)
    m_px = round(screen_margin_mm * ppm)
    m_mm = m_px / ppm
    canvas = np.full((tex.shape[0] + 2 * m_px, tex.shape[1] + 2 * m_px), 255, np.uint8)
    canvas[m_px : m_px + tex.shape[0], m_px : m_px + tex.shape[1]] = tex
    S = np.array([[1 / ppm, 0, 0.5 / ppm - m_mm], [0, 1 / ppm, 0.5 / ppm - m_mm], [0, 0, 1.0]])
    Kss = _ss_K(cam.K, ss)
    M = Camera(Kss, cam.R, cam.t, (w * ss, h * ss)).H_mat_to_img() @ S
    val = cv2.warpPerspective(canvas, M, (w * ss, h * ss), flags=cv2.INTER_LINEAR, borderValue=0)
    cover = cv2.warpPerspective(np.full(canvas.shape, 255, np.uint8), M, (w * ss, h * ss), flags=cv2.INTER_LINEAR)
    val_f = cv2.resize(val.astype(np.float32) / 255, (w, h), interpolation=cv2.INTER_AREA)
    cov_f = cv2.resize(cover.astype(np.float32) / 255, (w, h), interpolation=cv2.INTER_AREA)
    lum = np.divide(val_f, cov_f, out=np.zeros_like(val_f), where=cov_f > 1e-6)
    wb, bb, sb = (np.array(c, np.float32) for c in (white_bgr, black_bgr, surround_bgr))
    mat_rgb = bb[None, None, :] + (wb - bb)[None, None, :] * lum[..., None]
    if stage_bgr is not None:
        st = mat.stage
        sc = np.zeros(canvas.shape, np.float32)
        ex = np.asarray([(st.x_mm + m_mm) * ppm, (st.x2_mm + m_mm) * ppm], dtype=np.float64)
        ey = np.asarray([(st.y_mm + m_mm) * ppm, (st.y2_mm + m_mm) * ppm], dtype=np.float64)
        ox = _overlap_1d(ex, canvas.shape[1])
        oy = _overlap_1d(ey, canvas.shape[0])
        sc[:] = np.outer(oy, ox)
        sw = cv2.warpPerspective(sc, M, (w * ss, h * ss), flags=cv2.INTER_LINEAR, borderValue=0)
        sw_f = cv2.resize(sw, (w, h), interpolation=cv2.INTER_AREA)
        a = np.divide(sw_f, cov_f, out=np.zeros_like(sw_f), where=cov_f > 1e-6)[..., None]
        mat_rgb = mat_rgb * (1 - a) + np.array(stage_bgr, np.float32)[None, None, :] * a
    out = mat_rgb * cov_f[..., None] + sb[None, None, :] * (1 - cov_f[..., None])
    return np.clip(np.round(out), 0, 255).astype(np.uint8)


def _overlap_1d(edges_px: F64, n: int) -> F64:
    j = np.arange(n, dtype=np.float64)
    return np.asarray(np.clip(np.minimum(j + 1, edges_px[1]) - np.maximum(j, edges_px[0]), 0.0, 1.0), dtype=np.float64)


def cast_shadow(
    footprint_mm: F64, direction_deg: float, length_mm: float, strength: float, soft_mm: float
) -> Callable[[U8, Camera], U8]:
    """An `under=` hook: a soft shadow on the mat plane, the footprint swept `length_mm` along `direction_deg` and
    darkened by `strength` (same chroma — what a lamp does to paper or a screen)."""

    def draw(img: U8, cam: Camera) -> U8:
        w, h = cam.size
        a = math.radians(direction_deg)
        d = np.array([math.cos(a), math.sin(a)]) * length_mm
        fp = np.asarray(footprint_mm, dtype=np.float64)
        groups = [[fp + d * t] for t in np.linspace(0.0, 1.0, 12)]
        proj = [[cam.project(np.c_[g[0], np.zeros(len(g[0]))])] for g in groups]
        m = rasterize((h, w), proj).astype(np.float32) / 255.0
        ppm = cam.K[0, 0] / max(cam.height_mm, 1.0)
        m = np.asarray(cv2.GaussianBlur(m, (0, 0), max(soft_mm * ppm / 2.0, 0.5)), dtype=np.float32)
        out = img.astype(np.float32) * (1.0 - strength * m[..., None])
        return np.clip(np.round(out), 0, 255).astype(np.uint8)

    return draw


@dataclass
class Scene:
    image: U8
    camera: Camera
    alpha: F32  # part coverage (0..1), full frame
    alpha_top: F32
    mat_id: str
    part: PrismPart | None = None

    @property
    def mask(self) -> NDArray[np.bool_]:
        return self.alpha >= 0.5


CoverageFn = Callable[[Camera], tuple[F32, F32]]


def render_scene(
    mat_id: str,
    K: F64,
    R: F64,
    t: F64,
    size: tuple[int, int],
    part: PrismPart | list[PrismPart] | CoverageFn | tuple[F64, NDArray[np.int64]] | None = None,
    *,
    part_bgr: BGR = (60, 70, 85),
    ss: int = 2,
    under: Callable[[U8, Camera], U8] | None = None,
    **mat_kwargs: object,
) -> Scene:
    """Render a mat photo. `part` is a `PrismPart`, a `(vertices_mm, faces)` mesh in mat coordinates, or any callable
    returning `(alpha_all, alpha_top)` for a camera. `under` draws on the mat before the part is composited (e.g. the
    fit-check outline shown on the screen)."""
    cam = Camera(np.asarray(K, np.float64), np.asarray(R, np.float64), np.asarray(t, np.float64).ravel(), size)
    mat_img = render_mat_view(mat_id, cam, ss=ss, **mat_kwargs)  # type: ignore[arg-type]
    if under is not None:
        mat_img = under(mat_img, cam)
    img = mat_img.astype(np.float32)
    w, h = size
    a_all = np.zeros((h, w), np.float32)
    a_top = np.zeros((h, w), np.float32)
    top_c = np.array(part_bgr, np.float32)
    side_c = top_c * 0.7
    prism = None
    if isinstance(part, PrismPart):
        prism = part
        a_all, a_top = prism_coverage(part, cam)
        top_c, side_c = np.array(part.top_bgr, np.float32), np.array(part.side_bgr, np.float32)
    elif isinstance(part, list):
        a_all, a_top = prisms_coverage(part, cam)
        top_c, side_c = np.array(part[0].top_bgr, np.float32), np.array(part[0].side_bgr, np.float32)
    elif isinstance(part, tuple):
        a_all = mesh_coverage(part[0], part[1], cam)
        a_top = a_all
    elif part is not None:
        a_all, a_top = part(cam)
    side = np.clip(a_all - a_top, 0, 1)[..., None]
    img = img * (1 - a_all[..., None]) + side_c * side + top_c * a_top[..., None]
    return Scene(np.clip(np.round(img), 0, 255).astype(np.uint8), cam, a_all, a_top, mat_id, prism)


def render_part_scene(mat_id: str, cam: Camera, part: PrismPart | None, **kw: object) -> Scene:
    return render_scene(mat_id, cam.K, cam.R, cam.t, cam.size, part, **kw)  # type: ignore[arg-type]


# ---------------------------------------------------------------- augmentations


def add_glare(img: U8, center_px: tuple[float, float], radius_px: float, strength: float = 1.0) -> U8:
    """Specular screen glare: a soft, saturated, texture-free blob."""
    h, w = img.shape[:2]
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    r2 = ((xx - center_px[0]) ** 2 + (yy - center_px[1]) ** 2) / (radius_px**2)
    a = np.clip(strength * (1.6 - r2), 0, 1)[..., None]
    out = img.astype(np.float32) * (1 - a) + 255.0 * a
    return np.asarray(np.clip(out, 0, 255), dtype=np.uint8)


def add_moire(
    img: U8, period_px: float, angle_deg: float = 30.0, amplitude: float = 12.0, mask: NDArray[np.bool_] | None = None
) -> U8:
    """Periodic interference fringes as seen when photographing a screen."""
    h, w = img.shape[:2]
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    a = math.radians(angle_deg)
    wave = amplitude * np.sin(2 * np.pi * (xx * math.cos(a) + yy * math.sin(a)) / period_px)
    if mask is not None:
        wave = wave * mask
    out = img.astype(np.float32) + wave[..., None]
    return np.asarray(np.clip(out, 0, 255), dtype=np.uint8)


def blur(img: U8, sigma_px: float) -> U8:
    return np.asarray(cv2.GaussianBlur(img, (0, 0), sigma_px), dtype=np.uint8)


def add_noise(img: U8, sigma: float, seed: int = 0) -> U8:
    rng = np.random.default_rng(seed)
    out = img.astype(np.float32) + rng.normal(0, sigma, img.shape).astype(np.float32)
    return np.clip(np.round(out), 0, 255).astype(np.uint8)


def jpeg(img: U8, quality: int = 90) -> U8:
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, quality])
    if not ok:
        raise RuntimeError("JPEG encode failed")
    out = cv2.imdecode(buf, cv2.IMREAD_COLOR)
    if out is None:
        raise RuntimeError("JPEG decode failed")
    return np.asarray(out, dtype=np.uint8)


def encode_png(img: U8) -> bytes:
    ok, buf = cv2.imencode(".png", img)
    if not ok:
        raise RuntimeError("PNG encode failed")
    return bytes(buf.tobytes())


def draw_outline_on_mat(img: U8, cam: Camera, ring_mm: F64, color_bgr: BGR, width_mm: float = 0.4) -> U8:
    """Draw a thin 1:1 outline lying on the mat plane (what the screen fit check shows), anti-aliased."""
    ss = 4
    w, h = cam.size
    Kss = _ss_K(cam.K, ss)
    camss = Camera(Kss, cam.R, cam.t, (w * ss, h * ss))
    r = np.asarray(ring_mm, dtype=np.float64)
    n = len(r)
    quads: list[F64] = []
    for i in range(n):
        p, q = r[i], r[(i + 1) % n]
        d = q - p
        L = float(np.linalg.norm(d))
        if L == 0:
            continue
        nrm = np.array([-d[1], d[0]]) / L * width_mm / 2
        quads.append(np.array([p - nrm, q - nrm, q + nrm, p + nrm]))
    for i in range(n):  # round joins
        quads.append(r[i] + circle_poly(0, 0, width_mm, 12))
    proj = [camss.project(np.c_[qd, np.zeros(len(qd))]) for qd in quads]
    allp = np.concatenate(proj)
    x0 = max(math.floor(allp[:, 0].min() / ss) - 2, 0)
    y0 = max(math.floor(allp[:, 1].min() / ss) - 2, 0)
    x1 = min(math.ceil(allp[:, 0].max() / ss) + 3, w)
    y1 = min(math.ceil(allp[:, 1].max() / ss) + 3, h)
    m = _fill_union(((y1 - y0) * ss, (x1 - x0) * ss), [], proj, (float(x0 * ss), float(y0 * ss)))
    a = cv2.resize(m.astype(np.float32) / 255, (x1 - x0, y1 - y0), interpolation=cv2.INTER_AREA)[..., None]
    out = img.astype(np.float32).copy()
    out[y0:y1, x0:x1] = out[y0:y1, x0:x1] * (1 - a) + np.array(color_bgr, np.float32) * a
    return np.clip(np.round(out), 0, 255).astype(np.uint8)
