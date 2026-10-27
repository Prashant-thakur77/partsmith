"""Registry thumbnails: a shaded isometric PNG of a part, rendered on the CPU (no GL).

Input is the worker's `view.json` (triangles, per-vertex normals, B-rep edge polylines in mm). The renderer is a small
vectorised z-buffer: every triangle is split into pixel fragments, the nearest fragment wins per pixel, and its
barycentric weights interpolate the vertex normals for smooth Lambert shading. Visible B-rep edges (depth-tested
against the z-buffer) are drawn as crisp dark lines. The background is transparent, so the same PNG reads on light and
dark pages. Everything is rendered at 2x the output size and area-downsampled for anti-aliasing.
"""

from __future__ import annotations

import io
from collections.abc import Mapping
from typing import Any

import cv2
import numpy as np
import numpy.typing as npt
from PIL import Image

from services.common import blobs

FloatArray = npt.NDArray[np.float64]

SIZE_1X = (640, 480)
PAD_FRAC = 0.09  # empty margin on each side, as a fraction of the image size
BASE_RGB = np.array([0.60, 0.615, 0.635])  # mid-grey plastic
EDGE_RGB = (34, 36, 40)
AZIMUTH_DEG = -50.0  # camera position angle in the XY plane, from +X towards +Y
ELEVATION_DEG = 32.0
_MAX_FRAGMENTS = 3_000_000  # fragments per vectorised chunk (bounded memory)


def _camera() -> tuple[FloatArray, FloatArray, FloatArray]:
    """Orthographic camera basis (right, up, forward) in the CAD frame (Z up)."""
    az, el = np.radians(AZIMUTH_DEG), np.radians(ELEVATION_DEG)
    eye = np.array([np.cos(el) * np.cos(az), np.cos(el) * np.sin(az), np.sin(el)])
    fwd = -eye
    right = np.cross(fwd, np.array([0.0, 0.0, 1.0]))
    right /= np.linalg.norm(right)
    up = np.cross(right, fwd)
    return right, up, fwd


def _lights(right: FloatArray, up: FloatArray, fwd: FloatArray) -> list[tuple[FloatArray, float]]:
    """Camera-relative lights: a key from the upper left, a soft fill from the right and a faint top light."""

    def unit(v: FloatArray) -> FloatArray:
        return v / np.linalg.norm(v)

    return [
        (unit(-0.45 * right + 0.65 * up - 0.75 * fwd), 0.62),
        (unit(0.70 * right - 0.10 * up - 0.55 * fwd), 0.22),
        (unit(0.0 * right + 1.0 * up - 0.2 * fwd), 0.10),
    ]


def _rasterize(
    tri_px: FloatArray, tri_z: FloatArray, width: int, height: int
) -> tuple[npt.NDArray[np.int32], FloatArray, FloatArray, FloatArray]:
    """Scanline z-buffer. Returns (triangle id per pixel or -1, depth, barycentric b1, b2).

    Every (triangle, pixel row) pair becomes one span of pixel centres; spans expand to fragments in bounded chunks
    and the nearest fragment per pixel wins. Fully vectorised, so long thin fan triangles cost no more than their area.
    """
    n_pix = width * height
    tri_id = np.full(n_pix, -1, np.int32)
    zbuf = np.full(n_pix, np.inf)
    b1buf = np.zeros(n_pix)
    b2buf = np.zeros(n_pix)
    a = tri_px[:, 0]
    e1 = tri_px[:, 1] - a
    e2 = tri_px[:, 2] - a
    det = e1[:, 0] * e2[:, 1] - e1[:, 1] * e2[:, 0]
    ys = tri_px[:, :, 1]
    r0 = np.clip(np.ceil(ys.min(axis=1) - 0.5), 0, height).astype(np.int64)
    r1 = np.clip(np.floor(ys.max(axis=1) - 0.5), -1, height - 1).astype(np.int64)
    usable = (np.abs(det) > 1e-9) & (r1 >= r0)
    tris = np.flatnonzero(usable)
    if tris.size == 0:
        shape = (height, width)
        return tri_id.reshape(shape), zbuf.reshape(shape), b1buf.reshape(shape), b2buf.reshape(shape)
    nrows = r1[tris] - r0[tris] + 1
    pair_t = np.repeat(tris, nrows)
    starts = np.cumsum(nrows) - nrows
    pair_r = r0[pair_t] + (np.arange(pair_t.size) - np.repeat(starts, nrows))
    yc = pair_r + 0.5
    xl = np.full(pair_t.size, np.inf)
    xr = np.full(pair_t.size, -np.inf)
    for i, j in ((0, 1), (1, 2), (2, 0)):
        p, q = tri_px[pair_t, i], tri_px[pair_t, j]
        dy = q[:, 1] - p[:, 1]
        hit = ((p[:, 1] - yc) * (q[:, 1] - yc) <= 0) & (np.abs(dy) > 1e-12)
        x = p[:, 0] + (yc - p[:, 1]) * np.divide(q[:, 0] - p[:, 0], dy, out=np.zeros_like(dy), where=hit)
        xl = np.where(hit, np.minimum(xl, x), xl)
        xr = np.where(hit, np.maximum(xr, x), xr)
    c0 = np.clip(np.ceil(xl - 0.5), 0, width).astype(np.int64)
    c1 = np.clip(np.floor(xr - 0.5), -1, width - 1).astype(np.int64)
    count = np.maximum(c1 - c0 + 1, 0)
    keep_pairs = count > 0
    pair_t, pair_r, c0, count = pair_t[keep_pairs], pair_r[keep_pairs], c0[keep_pairs], count[keep_pairs]
    csum = np.cumsum(count)
    lo = 0
    while lo < pair_t.size:
        base = csum[lo - 1] if lo > 0 else 0
        hi = int(np.searchsorted(csum, base + _MAX_FRAGMENTS, side="right"))
        hi = max(hi, lo + 1)
        sl = slice(lo, hi)
        cnt = count[sl]
        total = int(cnt.sum())
        rep = np.repeat(np.arange(lo, hi), cnt)
        off = np.arange(total) - np.repeat(np.cumsum(cnt) - cnt, cnt)
        t = pair_t[rep]
        col = c0[rep] + off
        row = pair_r[rep]
        cx = col + 0.5 - a[t, 0]
        cy = row + 0.5 - a[t, 1]
        d = det[t]
        b1 = (cx * e2[t, 1] - cy * e2[t, 0]) / d
        b2 = (e1[t, 0] * cy - e1[t, 1] * cx) / d
        z = tri_z[t, 0] + b1 * (tri_z[t, 1] - tri_z[t, 0]) + b2 * (tri_z[t, 2] - tri_z[t, 0])
        pix = row * width + col
        order = np.lexsort((z, pix))
        pix_s = pix[order]
        first = np.ones(pix_s.size, bool)
        first[1:] = pix_s[1:] != pix_s[:-1]
        win = order[first]
        win = win[z[win] < zbuf[pix[win]]]
        zbuf[pix[win]] = z[win]
        tri_id[pix[win]] = t[win]
        b1buf[pix[win]] = b1[win]
        b2buf[pix[win]] = b2[win]
        lo = hi
    shape = (height, width)
    return tri_id.reshape(shape), zbuf.reshape(shape), b1buf.reshape(shape), b2buf.reshape(shape)


def _mesh(view: Mapping[str, Any]) -> tuple[FloatArray, npt.NDArray[np.int64], FloatArray | None]:
    m = view["mesh"]
    v = np.asarray(m["positions"], dtype=np.float64).reshape(-1, 3)
    f = np.asarray(m["indices"], dtype=np.int64).reshape(-1, 3)
    n = np.asarray(m.get("normals") or [], dtype=np.float64)
    normals = n.reshape(-1, 3) if n.size == v.size else None
    return v, f, normals


def render_rgba(view: Mapping[str, Any], width: int, height: int, *, supersample: int = 2) -> npt.NDArray[np.uint8]:
    """Render `view.json` to an RGBA uint8 image (transparent background)."""
    verts, faces, vnormals = _mesh(view)
    if len(faces) == 0:
        raise ValueError("view.json has no triangles")
    ss = max(1, int(supersample))
    W, H = width * ss, height * ss
    right, up, fwd = _camera()
    sx, sy, sz = verts @ right, verts @ up, verts @ fwd
    lo = np.array([sx.min(), sy.min()])
    hi = np.array([sx.max(), sy.max()])
    extent = np.maximum(hi - lo, 1e-6)
    scale = float(min(W * (1 - 2 * PAD_FRAC) / extent[0], H * (1 - 2 * PAD_FRAC) / extent[1]))
    centre = (lo + hi) / 2
    px = (sx - centre[0]) * scale + W / 2
    py = H / 2 - (sy - centre[1]) * scale
    xy = np.stack([px, py], axis=1)
    tri_id, zbuf, b1, b2 = _rasterize(xy[faces], sz[faces], W, H)
    covered = tri_id >= 0

    # per-pixel normal: interpolate vertex normals, fall back to the face normal; face the camera
    tri = verts[faces]
    fn = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    fn /= np.maximum(np.linalg.norm(fn, axis=1, keepdims=True), 1e-12)
    ids = tri_id[covered]
    if vnormals is not None:
        vn = vnormals[faces[ids]]
        w1, w2 = b1[covered][:, None], b2[covered][:, None]
        n = vn[:, 0] * (1 - w1 - w2) + vn[:, 1] * w1 + vn[:, 2] * w2
        bad = np.linalg.norm(n, axis=1) < 1e-6
        n[bad] = fn[ids[bad]]
    else:
        n = fn[ids]
    n /= np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-12)
    n[(n @ fwd) > 0] *= -1.0
    intensity = np.full(len(n), 0.30)
    for direction, weight in _lights(right, up, fwd):
        intensity += weight * np.clip(n @ direction, 0.0, 1.0)
    # gentle depth cue: nearer surfaces slightly brighter
    z = zbuf[covered]
    zr = (z - z.min()) / max(float(np.ptp(z)), 1e-6)
    intensity *= 1.04 - 0.08 * zr
    rgb = np.clip(BASE_RGB[None, :] * intensity[:, None], 0.0, 1.0)

    img = np.zeros((H, W, 4), np.uint8)
    img[covered, :3] = np.round(rgb * 255).astype(np.uint8)
    img[covered, 3] = 255

    _draw_edges(img, view, right, up, fwd, centre, scale, zbuf, extent)
    if ss > 1:
        img = _downsample(img, width, height)
    return img


def _draw_edges(
    img: npt.NDArray[np.uint8],
    view: Mapping[str, Any],
    right: FloatArray,
    up: FloatArray,
    fwd: FloatArray,
    centre: FloatArray,
    scale: float,
    zbuf: FloatArray,
    extent: FloatArray,
) -> None:
    """Draw the visible parts of the B-rep edges (depth test against the z-buffer, a little tolerance)."""
    H, W = zbuf.shape
    thickness = max(1, round(min(W, H) / 420))
    tol_mm = 2.5 / scale + 0.004 * float(np.linalg.norm(extent))
    far = np.where(np.isfinite(zbuf), zbuf, 1e12).astype(np.float32)
    near = cv2.dilate(far, np.ones((3, 3), np.uint8))  # max over the neighbourhood: forgiving at silhouettes
    for flat in view.get("edges") or []:
        pts = np.asarray(flat, dtype=np.float64).reshape(-1, 3)
        if len(pts) < 2:
            continue
        # resample so each step is about one pixel
        seg = np.linalg.norm(np.diff(pts, axis=0), axis=1)
        t = np.concatenate([[0.0], np.cumsum(seg)])
        if t[-1] <= 0:
            continue
        n = max(2, int(t[-1] * scale) + 1)
        tt = np.linspace(0.0, t[-1], n)
        dense = np.stack([np.interp(tt, t, pts[:, k]) for k in range(3)], axis=1)
        x = (dense @ right - centre[0]) * scale + W / 2
        y = H / 2 - (dense @ up - centre[1]) * scale
        z = dense @ fwd
        xi = np.clip(np.round(x - 0.5).astype(int), 0, W - 1)
        yi = np.clip(np.round(y - 0.5).astype(int), 0, H - 1)
        visible = z <= near[yi, xi] + tol_mm
        run: list[list[float]] = []
        for k in range(n):
            if visible[k]:
                run.append([x[k], y[k]])
            elif run:
                _polyline(img, run, thickness)
                run = []
        if run:
            _polyline(img, run, thickness)


def _polyline(img: npt.NDArray[np.uint8], run: list[list[float]], thickness: int) -> None:
    if len(run) < 2:
        return
    shift = 4
    pts = np.round(np.asarray(run) * (1 << shift)).astype(np.int32).reshape(-1, 1, 2)
    cv2.polylines(img, [pts], False, (*EDGE_RGB, 255), thickness, cv2.LINE_AA, shift)


def _downsample(img: npt.NDArray[np.uint8], width: int, height: int) -> npt.NDArray[np.uint8]:
    """Area downsample with premultiplied alpha (no dark fringes on transparent edges)."""
    f = img.astype(np.float32) / 255.0
    f[..., :3] *= f[..., 3:4]
    small = cv2.resize(f, (width, height), interpolation=cv2.INTER_AREA)
    a = small[..., 3:4]
    small[..., :3] = np.where(a > 1e-6, small[..., :3] / np.maximum(a, 1e-6), 0.0)
    return np.asarray(np.clip(np.round(small * 255.0), 0, 255).astype(np.uint8))


def png_bytes(rgba: npt.NDArray[np.uint8]) -> bytes:
    buf = io.BytesIO()
    Image.fromarray(rgba, "RGBA").save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def render_pair(view: Mapping[str, Any], size: tuple[int, int] = SIZE_1X) -> tuple[bytes, bytes]:
    """(1x PNG, 2x PNG). The 2x image is rendered once (with supersampling) and the 1x is its area downsample."""
    w, h = size
    big = render_rgba(view, 2 * w, 2 * h, supersample=2)
    return png_bytes(_downsample(big, w, h)), png_bytes(big)


def store_pair(view: Mapping[str, Any], size: tuple[int, int] = SIZE_1X) -> tuple[str, str]:
    """Render and store both PNGs in the blob store. Returns (key_1x, key_2x)."""
    one, two = render_pair(view, size)
    return blobs.put(one, ".png"), blobs.put(two, ".png")
