"""Photo-like SYNTHETIC renders of a part on a calibration mat (virtual screen or plain paper), with exact geometry.

The mat, its surroundings, lighting and camera effects are painted on top of the exact projective model in
`services.metrology.testing` (same K, R, t; the part silhouette is the exact anti-aliased coverage of the triangle mesh),
so the ground truth stays exact while the picture looks like a phone photo: backlit screen with a colour cast, a
visible pixel grid (it aliases into moiré like a real screen does), bezel and laptop body; or paper with fibre texture,
a lamp gradient and soft shadows; a Lambert + specular plastic part with a contact shadow; vignetting, defocus, sensor
noise and JPEG. Every image is labelled synthetic by the caller.

Frames: mat frame x right, y down, z into the table (a part sits at z ∈ [−h, 0]); camera frame as OpenCV.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal

import cv2
import numpy as np
from numpy.typing import NDArray

from services.metrology import testing as T
from services.metrology.mats import get_mat

F64 = NDArray[np.float64]
F32 = NDArray[np.float32]
I64 = NDArray[np.int64]
U8 = NDArray[np.uint8]
BGR = tuple[float, float, float]
Surface = Literal["screen", "paper"]

A4_MM = (210.0, 297.0)


@dataclass
class Look:
    """Everything about the appearance of one photo (sampled from a seed by `dataset.sample_look`)."""

    surface: Surface
    white_bgr: BGR = (236.0, 232.0, 226.0)
    black_bgr: BGR = (30.0, 28.0, 28.0)
    # screen
    screen_margin_mm: float = 6.0  # app background around the mat
    bezel_mm: float = 9.0
    bezel_bgr: BGR = (22.0, 21.0, 21.0)
    body_mm: float = 30.0
    body_bgr: BGR = (168.0, 166.0, 162.0)
    pixel_pitch_mm: float = 0.17
    grid_amp: float = 0.04  # relative darkening of the gaps between screen pixels
    backlight_var: float = 0.03
    # paper
    paper_texture: float = 4.0  # grey levels of fibre texture
    lamp_gradient: float = 0.12  # relative brightness drop across the page
    lamp_dir_deg: float = 30.0
    # table
    table_bgr: BGR = (70.0, 92.0, 120.0)
    stage_bgr: BGR | None = None  # screen mats only: the dark stage colour (None = the light stage, same as white)
    # part
    part_bgr: BGR = (60.0, 70.0, 85.0)
    face_bgr: F64 | None = None  # optional per-face albedo (n_faces, 3), overrides part_bgr
    light_dir: tuple[float, float, float] = (0.3, -0.2, -1.0)  # towards the light, mat frame (z<0 = up)
    ambient: float = 0.42
    diffuse: float = 0.62
    specular: float = 0.18
    shininess: float = 24.0
    shadow_strength: float = 0.25
    shadow_soft_mm: float = 2.0
    contact_strength: float = 0.12
    # camera / photo
    vignette: float = 0.12
    exposure: float = 1.0
    wb_gain: tuple[float, float, float] = (1.0, 1.0, 1.0)  # B, G, R multipliers
    glare: tuple[float, float, float, float, float] | None = None  # (u_mm, v_mm, length_mm, width_mm, angle_deg)
    glare_strength: float = 0.0
    moire_amp: float = 0.0  # extra interference fringes (grey levels)
    moire_period_px: float = 9.0
    moire_angle_deg: float = 25.0
    blur_px: float = 0.5
    noise_read: float = 1.2
    noise_shot: float = 0.06  # variance per grey level
    notes: list[str] = field(default_factory=list)


@dataclass
class Render:
    image: U8
    alpha: F32  # exact part coverage
    camera: T.Camera


# ---------------------------------------------------------------- geometry helpers


def mat_coords(cam: T.Camera) -> tuple[F32, F32]:
    """Mat-plane (z = 0) coordinates in mm of every pixel centre."""
    w, h = cam.size
    Hinv = np.linalg.inv(cam.H_mat_to_img(0.0))
    xs = np.arange(w, dtype=np.float64)
    ys = np.arange(h, dtype=np.float64)
    X, Y = np.meshgrid(xs, ys)
    den = Hinv[2, 0] * X + Hinv[2, 1] * Y + Hinv[2, 2]
    u = (Hinv[0, 0] * X + Hinv[0, 1] * Y + Hinv[0, 2]) / den
    v = (Hinv[1, 0] * X + Hinv[1, 1] * Y + Hinv[1, 2]) / den
    return u.astype(np.float32), v.astype(np.float32)


def rect_coverage(u: F32, v: F32, x0: float, y0: float, x1: float, y1: float, px_per_mm: float) -> F32:
    """Soft (≈ 1 px ramp) coverage of an axis-aligned mat rectangle; for decorative regions, not for measured edges."""
    d = np.minimum(np.minimum(u - x0, x1 - u), np.minimum(v - y0, y1 - v))
    return np.asarray(np.clip(0.5 + d * px_per_mm, 0.0, 1.0), dtype=np.float32)


def value_noise(shape: tuple[int, int], cell_px: float, rng: np.random.Generator) -> F32:
    """Smooth random field in [-1, 1] (bicubic-upsampled lattice noise)."""
    h, w = shape
    gh, gw = max(2, int(h / cell_px) + 3), max(2, int(w / cell_px) + 3)
    g = rng.uniform(-1, 1, (gh, gw)).astype(np.float32)
    up = cv2.resize(g, (int(gw * cell_px), int(gh * cell_px)), interpolation=cv2.INTER_CUBIC)
    return np.asarray(up[:h, :w], dtype=np.float32)


def sample_texture(tex: F32, u: F32, v: F32, origin_mm: tuple[float, float], px_per_mm: float) -> F32:
    """Look up a texture laid on the mat plane (texel (0, 0) centre at `origin_mm`)."""
    mx = ((u - origin_mm[0]) * px_per_mm).astype(np.float32)
    my = ((v - origin_mm[1]) * px_per_mm).astype(np.float32)
    return np.asarray(cv2.remap(tex, mx, my, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT), dtype=np.float32)


def local_px_per_mm(cam: T.Camera) -> float:
    return float(cam.K[0, 0] / max(cam.height_mm, 1.0))


# ---------------------------------------------------------------- surface (mat + surroundings)


def render_surface(mat_id: str, cam: T.Camera, look: Look, rng: np.random.Generator) -> tuple[F32, F32, F32]:
    """The mat, its screen/page and the table, as float32 BGR. Also returns the per-pixel mat coordinates."""
    mat = get_mat(mat_id)
    w, h = cam.size
    ppm = local_px_per_mm(cam)
    u, v = mat_coords(cam)
    if look.surface == "screen":
        margin = look.screen_margin_mm
        base = T.render_mat_view(
            mat_id,
            cam,
            white_bgr=_i3(look.white_bgr),
            black_bgr=_i3(look.black_bgr),
            surround_bgr=_i3(look.bezel_bgr),
            screen_margin_mm=margin,
            stage_bgr=None if look.stage_bgr is None else _i3(look.stage_bgr),
        ).astype(np.float32)
        # Backlight: a smooth non-uniformity across the panel plus the pixel grid (sampled at pixel centres, so it
        # aliases into moiré exactly as a phone camera sees a screen; the box filter of a sensor pixel damps it).
        content = rect_coverage(u, v, -margin, -margin, mat.width_mm + margin, mat.height_mm + margin, ppm)
        bl = 1.0 + look.backlight_var * value_noise((h, w), max(w, h) / 3.0, rng)
        pitch = look.pixel_pitch_mm
        mm_per_px = 1.0 / ppm
        damp = abs(math.sin(math.pi * mm_per_px / pitch) / (math.pi * mm_per_px / pitch))
        gx = 0.5 + 0.5 * np.cos(2 * np.pi * u / pitch)
        gy = 0.5 + 0.5 * np.cos(2 * np.pi * v / pitch)
        grid = 1.0 - look.grid_amp * damp * (1.0 - gx * gy)
        mod = np.where(content > 0, bl * grid, 1.0).astype(np.float32)
        img = base * mod[..., None]
        # bezel -> laptop body -> table
        b0 = margin + look.bezel_mm
        in_bezel = rect_coverage(u, v, -b0, -b0, mat.width_mm + b0, mat.height_mm + b0, ppm)
        b1 = b0 + look.body_mm
        in_body = rect_coverage(u, v, -b1, -b1, mat.width_mm + b1, mat.height_mm + b1, ppm)
        body = np.array(look.body_bgr, np.float32) * (1.0 + 0.03 * value_noise((h, w), 40.0, rng))[..., None]
        table = _table(u, v, look, rng)
        outer = body * in_body[..., None] + table * (1 - in_body[..., None])
        img = img * in_bezel[..., None] + outer * (1 - in_bezel[..., None])
    else:
        ox, oy = mat.page_offset_mm
        base = T.render_mat_view(
            mat_id,
            cam,
            white_bgr=_i3(look.white_bgr),
            black_bgr=_i3(look.black_bgr),
            surround_bgr=_i3(look.white_bgr),
            screen_margin_mm=min(ox, oy),
        ).astype(np.float32)
        page = rect_coverage(u, v, -ox, -oy, A4_MM[0] - ox, A4_MM[1] - oy, ppm)
        # paper fibre texture attached to the page (two scales), and a lamp gradient across it
        tex_ppm = 6.0
        tw, th = int(A4_MM[0] * tex_ppm) + 4, int(A4_MM[1] * tex_ppm) + 4
        fib = 0.65 * rng.normal(0, 1, (th, tw)).astype(np.float32) + 0.8 * value_noise((th, tw), 14.0, rng)
        fib = np.asarray(cv2.GaussianBlur(fib, (0, 0), 0.7), dtype=np.float32)
        tex = sample_texture(fib, u, v, (-ox, -oy), tex_ppm) * look.paper_texture
        a = math.radians(look.lamp_dir_deg)
        s = ((u - mat.width_mm / 2) * math.cos(a) + (v - mat.height_mm / 2) * math.sin(a)) / max(A4_MM)
        lamp = 1.0 - look.lamp_gradient * (s + 0.5)
        paper = (base + tex[..., None]) * lamp[..., None]
        table = _table(u, v, look, rng)
        img = paper * page[..., None] + table * (1 - page[..., None])
    return img.astype(np.float32), u, v


def _table(u: F32, v: F32, look: Look, rng: np.random.Generator) -> F32:
    """Wood-ish desk: low-frequency grain along one direction plus fine noise."""
    h, w = u.shape
    grain = np.sin(u * 0.35 + 2.0 * value_noise((h, w), 120.0, rng)) * 0.04
    fine = 0.03 * value_noise((h, w), 6.0, rng)
    m = 1.0 + grain + fine
    return (np.array(look.table_bgr, np.float32)[None, None, :] * m[..., None]).astype(np.float32)


def _i3(c: BGR) -> tuple[int, int, int]:
    return (round(c[0]), round(c[1]), round(c[2]))


# ---------------------------------------------------------------- shadows


def shadow_map(vertices_mat: F64, faces: I64, u: F32, v: F32, look: Look, *, res_px_per_mm: float = 4.0) -> F32:
    """Soft shadow of the part on the mat plane (0..1): a directional shadow from `light_dir` blurred by the light's
    size, plus a tight contact shadow right at the footprint."""
    V = np.asarray(vertices_mat, dtype=np.float64)
    L = np.asarray(look.light_dir, dtype=np.float64)
    L = L / np.linalg.norm(L)
    hgt = -V[:, 2]  # height above the mat
    # project each vertex along the light onto z = 0: p - h * (l_xy / -l_z)
    proj = V[:, :2] + hgt[:, None] * (L[:2] / max(-L[2], 0.2))[None, :]
    foot = V[:, :2]
    lo = np.minimum(proj.min(0), foot.min(0)) - 4 * look.shadow_soft_mm - 3
    hi = np.maximum(proj.max(0), foot.max(0)) + 4 * look.shadow_soft_mm + 3
    gw, gh = int((hi[0] - lo[0]) * res_px_per_mm) + 1, int((hi[1] - lo[1]) * res_px_per_mm) + 1

    def raster(p2: F64) -> F32:
        px = (p2 - lo) * res_px_per_mm - 0.5
        m = T.rasterize((gh, gw), [[px[f]] for f in faces])
        return m.astype(np.float32) / 255.0

    cast = cv2.GaussianBlur(raster(proj), (0, 0), max(look.shadow_soft_mm * res_px_per_mm, 0.5))
    contact = cv2.GaussianBlur(raster(foot), (0, 0), 0.8 * res_px_per_mm)
    s = np.clip(look.shadow_strength * cast + look.contact_strength * contact, 0, 0.9).astype(np.float32)
    return sample_texture_border0(s, u, v, (float(lo[0]), float(lo[1])), res_px_per_mm)


def sample_texture_border0(tex: F32, u: F32, v: F32, origin_mm: tuple[float, float], ppm: float) -> F32:
    mx = ((u - origin_mm[0]) * ppm - 0.5).astype(np.float32)
    my = ((v - origin_mm[1]) * ppm - 0.5).astype(np.float32)
    return np.asarray(
        cv2.remap(tex, mx, my, cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=0.0), dtype=np.float32
    )


# ---------------------------------------------------------------- part shading


def face_normals(vertices: F64, faces: I64) -> F64:
    a, b, c = vertices[faces[:, 0]], vertices[faces[:, 1]], vertices[faces[:, 2]]
    n = np.cross(b - a, c - a)
    ln = np.linalg.norm(n, axis=1, keepdims=True)
    return np.asarray(n / np.maximum(ln, 1e-12), dtype=np.float64)


def shade_part(vertices_mat: F64, faces: I64, cam: T.Camera, look: Look, *, ss: int = 3) -> tuple[F32, F32]:
    """Painter-sorted, back-face-culled, flat-shaded (Lambert + Blinn-Phong) part colours.

    Returns (premultiplied BGR, coverage) at image resolution. Used for colour only: the compositing alpha is the exact
    coverage from `testing.mesh_coverage`, so shading never moves an edge.
    """
    w, h = cam.size
    V = np.asarray(vertices_mat, dtype=np.float64)
    F = np.asarray(faces, dtype=np.int64)
    Kss = T._ss_K(cam.K, ss)
    Xc = V @ cam.R.T + cam.t
    uv = Xc @ Kss.T
    uv = uv[:, :2] / uv[:, 2:3]
    n = face_normals(V, F)
    cen = V[F].mean(axis=1)
    to_cam = cam.center_mm[None, :] - cen
    to_cam /= np.linalg.norm(to_cam, axis=1, keepdims=True)
    vis = np.einsum("ij,ij->i", n, to_cam) > 0
    L = np.asarray(look.light_dir, dtype=np.float64)
    L = L / np.linalg.norm(L)
    ndl = np.clip(n @ L, 0, 1)
    Hh = to_cam + L[None, :]
    Hh /= np.linalg.norm(Hh, axis=1, keepdims=True)
    spec = np.clip(np.einsum("ij,ij->i", n, Hh), 0, 1) ** look.shininess
    alb = (
        np.asarray(look.face_bgr, dtype=np.float64)
        if look.face_bgr is not None
        else np.tile(np.asarray(look.part_bgr, dtype=np.float64), (len(F), 1))
    )
    col = alb * (look.ambient + look.diffuse * ndl)[:, None] + 255.0 * look.specular * spec[:, None]
    col = np.clip(col, 0, 255)
    depth = Xc[F, 2].mean(axis=1)
    order = np.flatnonzero(vis)
    order = order[np.argsort(-depth[order], kind="stable")]  # far first
    x0 = max(math.floor(uv[:, 0].min() / ss) - 2, 0)
    y0 = max(math.floor(uv[:, 1].min() / ss) - 2, 0)
    x1 = min(math.ceil(uv[:, 0].max() / ss) + 3, w)
    y1 = min(math.ceil(uv[:, 1].max() / ss) + 3, h)
    prem = np.zeros((h, w, 3), np.float32)
    cov = np.zeros((h, w), np.float32)
    if x1 <= x0 or y1 <= y0 or len(order) == 0:
        return prem, cov
    canvas = np.zeros(((y1 - y0) * ss, (x1 - x0) * ss, 3), np.uint8)
    drawn = np.zeros(canvas.shape[:2], np.uint8)
    off = np.array([x0 * ss, y0 * ss], dtype=np.float64)
    pts = np.round((uv - off) * 16).astype(np.int32)
    for i in order:
        tri = pts[F[i]].reshape(-1, 1, 2)
        c = col[i]
        cv2.fillConvexPoly(canvas, tri, (float(c[0]), float(c[1]), float(c[2])), cv2.LINE_8, shift=4)
        cv2.fillConvexPoly(drawn, tri, 255, cv2.LINE_8, shift=4)
    size = (x1 - x0, y1 - y0)
    d = drawn.astype(np.float32) / 255.0
    prem[y0:y1, x0:x1] = cv2.resize(canvas.astype(np.float32) * d[..., None], size, interpolation=cv2.INTER_AREA)
    cov[y0:y1, x0:x1] = cv2.resize(d, size, interpolation=cv2.INTER_AREA)
    return prem, cov


# ---------------------------------------------------------------- photo effects


def add_glare_streak(img: F32, u: F32, v: F32, look: Look) -> F32:
    """Reflection of a window/lamp on the screen glass: a soft elongated bright band fixed on the screen plane."""
    if look.glare is None or look.glare_strength <= 0:
        return img
    gu, gv, length, width, ang = look.glare
    a = math.radians(ang)
    du, dv = u - gu, v - gv
    along = du * math.cos(a) + dv * math.sin(a)
    across = -du * math.sin(a) + dv * math.cos(a)
    g = np.exp(-0.5 * (across / (width / 2.0)) ** 2) * np.exp(-0.5 * (along / (length / 2.0)) ** 4)
    g = (look.glare_strength * g).astype(np.float32)[..., None]
    return img * (1 - g) + 255.0 * g


def finish_photo(img: F32, look: Look, rng: np.random.Generator) -> U8:
    """Camera pipeline: white balance + exposure, vignetting, defocus, sensor noise."""
    h, w = img.shape[:2]
    out = img * np.asarray(look.wb_gain, np.float32)[None, None, :] * look.exposure
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    r2 = ((xx - w / 2) ** 2 + (yy - h / 2) ** 2) / ((w / 2) ** 2 + (h / 2) ** 2)
    out = out * (1.0 - look.vignette * r2)[..., None]
    if look.blur_px > 0:
        out = cv2.GaussianBlur(out, (0, 0), look.blur_px)
    var = look.noise_read**2 + look.noise_shot * np.clip(out, 0, 255)
    out = out + rng.standard_normal(out.shape).astype(np.float32) * np.sqrt(var).astype(np.float32)
    return np.asarray(np.clip(np.round(out), 0, 255), dtype=np.uint8)


SurfaceFn = Callable[[T.Camera, Look, np.random.Generator], tuple[F32, F32, F32]]
OverlayFn = Callable[[F32, F32, F32], F32]


def render_photo(
    mat_id: str,
    cam: T.Camera,
    vertices_mat: F64,
    faces: I64,
    look: Look,
    rng: np.random.Generator,
    *,
    surface: SurfaceFn | None = None,
    overlay: OverlayFn | None = None,
) -> Render:
    """One synthetic photo: surface, glare, shadow, exactly-covered shaded part, camera effects.

    `surface` replaces the mat rendering (red-team boards); `overlay(img, u, v)` paints on top of the part before the
    camera effects (a hand in frame). An empty `faces` array renders the mat alone."""
    surf, u, v = surface(cam, look, rng) if surface is not None else render_surface(mat_id, cam, look, rng)
    surf = add_glare_streak(surf, u, v, look)
    if look.moire_amp > 0:  # interference fringes live on the screen, not on the part sitting on it
        h, w = surf.shape[:2]
        yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
        a = math.radians(look.moire_angle_deg)
        wave = look.moire_amp * np.sin(2 * np.pi * (xx * math.cos(a) + yy * math.sin(a)) / look.moire_period_px)
        surf = surf + wave[..., None]
    w_img, h_img = cam.size
    if len(faces) == 0:
        img = np.asarray(surf, dtype=np.float32)
        alpha = np.zeros((h_img, w_img), np.float32)
    else:
        sh = shadow_map(vertices_mat, faces, u, v, look)
        surf = surf * (1.0 - sh[..., None])
        alpha = T.mesh_coverage(vertices_mat, faces, cam)
        prem, cov = shade_part(vertices_mat, faces, cam, look)
        colour = np.divide(prem, cov[..., None], out=np.zeros_like(prem), where=cov[..., None] > 1e-3)
        gap = (alpha > 0) & (cov <= 1e-3)
        if gap.any():  # rare sliver pixels the painter missed: borrow the neighbourhood colour
            k = (0, 0)
            num = cv2.GaussianBlur(prem, k, 2.0)
            den = cv2.GaussianBlur(cov, k, 2.0)
            fill = np.divide(num, den[..., None], out=np.zeros_like(num), where=den[..., None] > 1e-4)
            colour[gap] = fill[gap]
        img = np.asarray(surf * (1 - alpha[..., None]) + colour * alpha[..., None], dtype=np.float32)
    if overlay is not None:
        img = overlay(img, u, v)
    return Render(image=finish_photo(img, look, rng), alpha=alpha, camera=cam)
