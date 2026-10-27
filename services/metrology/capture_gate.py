"""Capture gate: deterministic photo checks before any paid model call (PLAN §5.2).

Each check returns pass/warn/fail with the measured value, its threshold and one actionable sentence for the user.
The report passes when no check fails. Thresholds are named constants; they were set on synthetic renders (see the
tests) and are meant to be re-tuned on real phone photos.
"""

from __future__ import annotations

from typing import Any, Literal, cast

import cv2
import numpy as np
from numpy.typing import NDArray
from partsmith_schemas.measurement import CaptureCheck, CaptureReport

from .calibrate import MatDetection, PoseEstimate, estimate_pose
from .mats import GRID_CELLS, marker_bits

U8 = NDArray[np.uint8]
BoolMask = NDArray[np.bool_]
Severity = Literal["ok", "warn", "fail"]

MIN_MARKERS_WARN = 4
REPROJ_WARN_PX = 1.0
REPROJ_FAIL_PX = 2.0
# Sharpness = var(Laplacian) / var(intensity) on marker patches resampled to 8 px per marker cell (resolution- and
# contrast-normalised). On synthetic renders a crisp mat scores 6–13 at 4–15 px/mm; Gaussian blur of σ = 0.15 mm at the
# mat gives ≈ 4.0 and σ = 0.3 mm ≈ 2.5, independent of the photo's resolution.
BLUR_WARN = 4.0
BLUR_FAIL = 2.5
STAGE_EDGE_MARGIN_MM = 1.0
MIN_PART_AREA_MM2 = 10.0
TILT_WARN_DEG = 15.0
TILT_FAIL_DEG = 25.0
CLIP_WARN = 0.02
CLIP_FAIL = 0.05
GLARE_MARKER_DARK_FRACTION = 0.15  # share of a marker's black cells that are blown out
GLARE_FAIL_MARKERS = 3
GLARE_MIN_BLOB_MM2 = 4.0
MOIRE_PEAK_RATIO = 25.0  # spectral peak over the median of its ring: periodic, not noise
MOIRE_WARN = 2.0  # rms grey levels of the periodic component
MOIRE_FAIL = 5.0
SCALE_WARN = 0.015
SCALE_FAIL = 0.03
PATCH_PX_PER_CELL = 8
# Contrast: share of the outline whose inside/outside colours differ by less than EDGE_MIN_CONTRAST (8-bit units, the
# same order as the segmenter's minimum contrast). Also fail when the part's median colour is that close to the stage,
# when the segmentation fell apart into pieces, or when the mask is implausibly ragged.
EDGE_MIN_CONTRAST = 20.0
CONTRAST_WARN_WEAK = 0.08
CONTRAST_FAIL_WEAK = 0.20
CONTRAST_MIN_SEPARATION = 20.0
CONTRAST_MIN_LARGEST_FRACTION = 0.85
CONTRAST_MIN_SOLIDITY = 0.25
# A part whose colour is the stage colour slightly darkened (white, off-white, light grey on a white stage) cannot be
# told from its own shadow or reliably from the stage.
CONE_CHROMA_TOL = 16.0  # same tolerance the segmenter uses to call a part shadow-coloured
CONE_MIN_RATIO = 0.50  # the segmenter's SHADOW_MIN_RATIO: such parts cannot be told from their own shadow


def _check(
    name: str, sev: Severity, reason: str, value: float | None = None, threshold: float | None = None
) -> CaptureCheck:
    v = None if value is None else round(float(value), 4)
    return CaptureCheck(
        name=cast(Any, name), passed=sev != "fail", severity=sev, value=v, threshold=threshold, reason=reason
    )


def _gray(img: U8) -> U8:
    return img if img.ndim == 2 else np.asarray(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), dtype=np.uint8)


def _poly_mask(shape: tuple[int, int], poly_px: NDArray[np.float64]) -> BoolMask:
    m = np.zeros(shape, np.uint8)
    cv2.fillPoly(m, [np.round(poly_px * 16).astype(np.int32)], 1, cv2.LINE_8, shift=4)
    return m > 0


def _marker_patch(gray: U8, corners_px: NDArray[np.float64]) -> NDArray[np.float32]:
    n = GRID_CELLS * PATCH_PX_PER_CELL
    dst = np.array([[0, 0], [n, 0], [n, n], [0, n]], np.float32) - 0.5
    M = cv2.getPerspectiveTransform(corners_px.astype(np.float32), dst)
    return cv2.warpPerspective(gray, M, (n, n), flags=cv2.INTER_AREA).astype(np.float32)


def sharpness(gray: U8, det: MatDetection) -> float:
    """Median over detected markers of var(Laplacian)/var(I) on resolution-normalised marker patches."""
    vals = []
    for c in det.corners_px:
        p = _marker_patch(gray, c)
        v = float(p.var())
        if v < 25:
            continue
        lap = cv2.Laplacian(p, cv2.CV_32F, ksize=3)
        vals.append(float(lap.var()) / v)
    return float(np.median(vals)) if vals else 0.0


def check_markers(det: MatDetection | None) -> CaptureCheck:
    if det is None:
        return _check(
            "markers",
            "fail",
            "No mat markers found — get the whole mat in the photo and make sure the screen is on.",
            0,
            MIN_MARKERS_WARN,
        )
    n, total = det.n_markers, len(det.mat.markers)
    st = det.mat.stage
    sides = set()
    for i in det.ids:
        x, y = det.mat.marker_corners_mm(int(i)).mean(axis=0)
        if y < st.y_mm:
            sides.add("top")
        if y > st.y2_mm:
            sides.add("bottom")
        if x < st.x_mm:
            sides.add("left")
        if x > st.x2_mm:
            sides.add("right")
    if n < MIN_MARKERS_WARN:
        return _check(
            "markers",
            "warn",
            f"Only {n} of {total} markers are visible — step back so more of the mat is in view.",
            n,
            MIN_MARKERS_WARN,
        )
    if len(sides) < 2:
        return _check(
            "markers",
            "warn",
            "All visible markers are along one edge — centre the mat in the photo.",
            n,
            MIN_MARKERS_WARN,
        )
    return _check("markers", "ok", f"{n} of {total} markers found.", n, MIN_MARKERS_WARN)


def check_reprojection(det: MatDetection | None) -> CaptureCheck:
    if det is None:
        return _check(
            "reprojection", "fail", "The mat could not be located, so scale is unknown — retake with the mat in view."
        )
    e = det.reproj_px_rms
    if e >= REPROJ_FAIL_PX:
        return _check(
            "reprojection",
            "fail",
            f"The markers disagree by {e:.1f} px — lay the screen or paper flat and retake.",
            e,
            REPROJ_WARN_PX,
        )
    if e >= REPROJ_WARN_PX:
        return _check(
            "reprojection",
            "warn",
            f"The markers disagree by {e:.1f} px — make sure the mat is flat and not bent.",
            e,
            REPROJ_WARN_PX,
        )
    return _check("reprojection", "ok", f"Mat fit residual {e:.2f} px.", e, REPROJ_WARN_PX)


def check_blur(gray: U8, det: MatDetection | None) -> CaptureCheck:
    if det is None:
        return _check("blur", "fail", "No markers to judge sharpness on — retake with the mat in view.")
    s = sharpness(gray, det)
    if s < BLUR_FAIL:
        return _check(
            "blur",
            "fail",
            "The photo is blurry — hold the phone still, tap to focus on the part and retake.",
            s,
            BLUR_WARN,
        )
    if s < BLUR_WARN:
        return _check(
            "blur", "warn", "The photo is slightly soft — tap to focus on the part for sharper edges.", s, BLUR_WARN
        )
    return _check("blur", "ok", "Sharp enough.", s, BLUR_WARN)


def check_coverage(det: MatDetection | None, mask: BoolMask | None) -> CaptureCheck:
    if mask is None or det is None:
        return _check("coverage", "ok", "Part position not checked yet (no part mask).")
    if not mask.any():
        return _check(
            "coverage",
            "fail",
            "No part found on the stage — place the part in the plain area inside the markers.",
            0.0,
            MIN_PART_AREA_MM2,
        )
    if mask[0, :].any() or mask[-1, :].any() or mask[:, 0].any() or mask[:, -1].any():
        return _check(
            "coverage", "fail", "The part runs off the edge of the photo — step back so all of it is visible."
        )
    cs, _ = cv2.findContours(mask.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    pts = np.concatenate([c.reshape(-1, 2) for c in cs]).astype(np.float64)
    mm = det.to_mm(pts)
    st = det.mat.stage
    margin = float(
        min(mm[:, 0].min() - st.x_mm, st.x2_mm - mm[:, 0].max(), mm[:, 1].min() - st.y_mm, st.y2_mm - mm[:, 1].max())
    )
    area_mm2 = float(np.count_nonzero(mask)) / det.px_per_mm_at(tuple(mm.mean(axis=0))) ** 2
    if area_mm2 < MIN_PART_AREA_MM2:
        return _check(
            "coverage",
            "fail",
            "The part is too small to measure here — use a smaller mat or move the phone closer.",
            area_mm2,
            MIN_PART_AREA_MM2,
        )
    if area_mm2 > 0.85 * st.w_mm * st.h_mm:
        return _check("coverage", "fail", "The part fills the whole stage — use a larger mat.", area_mm2)
    if margin < STAGE_EDGE_MARGIN_MM:
        return _check(
            "coverage",
            "fail",
            "The part touches the markers — move it into the middle of the plain area.",
            margin,
            STAGE_EDGE_MARGIN_MM,
        )
    return _check(
        "coverage", "ok", f"Part is inside the stage ({margin:.0f} mm clearance).", margin, STAGE_EDGE_MARGIN_MM
    )


def check_tilt(pose: PoseEstimate | None) -> CaptureCheck:
    if pose is None:
        return _check("tilt", "fail", "Camera angle unknown without the mat — retake with the mat in view.")
    t = pose.tilt_deg
    if t > TILT_FAIL_DEG:
        return _check(
            "tilt", "fail", f"The phone is tilted {t:.0f}° — hold it straight above the part.", t, TILT_FAIL_DEG
        )
    if t > TILT_WARN_DEG:
        return _check(
            "tilt",
            "warn",
            f"The phone is tilted {t:.0f}° — straighter above the part is more accurate.",
            t,
            TILT_FAIL_DEG,
        )
    return _check("tilt", "ok", f"Tilt {t:.0f}°.", t, TILT_FAIL_DEG)


def check_exposure(img: U8, det: MatDetection | None, mask: BoolMask | None) -> CaptureCheck:
    img3 = img if img.ndim == 3 else cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    if mask is not None and mask.any():
        px = img3[mask]
        hi = np.any(px >= 253, axis=1)
        lo = np.all(px <= 2, axis=1)
        f = float(np.mean(hi | lo))
        if f > CLIP_FAIL:
            what = "bright" if hi.mean() >= lo.mean() else "dark"
            fix = "lower the screen brightness or move the lamp" if what == "bright" else "add light"
            return _check(
                "exposure", "fail", f"{f * 100:.0f} % of the part is blown out {what} — {fix} and retake.", f, CLIP_FAIL
            )
        if f > CLIP_WARN:
            return _check(
                "exposure", "warn", f"{f * 100:.0f} % of the part is clipped — even lighting will help.", f, CLIP_FAIL
            )
        return _check("exposure", "ok", "Exposure is fine.", f, CLIP_FAIL)
    if det is not None:
        st = _poly_mask(img3.shape[:2], det.to_px(det.mat.stage.corners()))
        f = float(np.mean(np.all(img3[st] >= 253, axis=1))) if st.any() else 0.0
        if f > 0.6:
            return _check("exposure", "warn", "The screen is overexposed — lower its brightness a little.", f, 0.6)
        return _check("exposure", "ok", "Exposure is fine.", f, 0.6)
    return _check("exposure", "ok", "Exposure not checked (no mat).")


def check_glare(img: U8, det: MatDetection | None, mask: BoolMask | None) -> CaptureCheck:
    """Blown-out, texture-free patches on the board: count markers whose black cells are washed out, and look for
    saturated blobs on the stage that are much brighter than the stage itself."""
    if det is None:
        return _check("glare", "ok", "Glare not checked (no mat).")
    gray = _gray(img)
    h, w = gray.shape
    mat = det.mat
    glared = 0
    for mk in mat.markers:
        corners = det.to_px(mat.marker_corners_mm(mk.id))
        if corners[:, 0].min() < 0 or corners[:, 1].min() < 0 or corners[:, 0].max() >= w or corners[:, 1].max() >= h:
            continue
        patch = _marker_patch(gray, corners)
        black = np.kron(1 - marker_bits(mk.id), np.ones((PATCH_PX_PER_CELL, PATCH_PX_PER_CELL), np.uint8)) > 0
        black = cv2.erode(black.astype(np.uint8), np.ones((3, 3), np.uint8)) > 0
        if float(np.mean(patch[black] >= 235)) > GLARE_MARKER_DARK_FRACTION:
            glared += 1
    st_mask = _poly_mask((h, w), det.to_px(mat.stage.corners()))
    blob_on_part = False
    blob_mm2 = 0.0
    if st_mask.any():
        med = float(np.median(gray[st_mask]))
        if med < 240:  # a uniformly bright stage is an exposure question, not glare
            g = gray.astype(np.float32)
            mean = cv2.blur(g, (7, 7))
            std = np.sqrt(np.maximum(cv2.blur(g * g, (7, 7)) - mean * mean, 0))
            sat = (gray >= 250) & (std < 4.0) & st_mask
            n, lab, stats, _ = cv2.connectedComponentsWithStats(sat.astype(np.uint8))
            ppm = det.px_per_mm_at((mat.stage.x_mm + mat.stage.w_mm / 2, mat.stage.y_mm + mat.stage.h_mm / 2))
            for i in range(1, n):
                a = stats[i, cv2.CC_STAT_AREA] / ppm**2
                if a >= GLARE_MIN_BLOB_MM2:
                    blob_mm2 += a
                    if mask is not None and np.any(
                        (cv2.dilate((lab == i).astype(np.uint8), np.ones((5, 5), np.uint8)) > 0) & mask
                    ):
                        blob_on_part = True
    if glared >= GLARE_FAIL_MARKERS or (glared and det.n_markers < MIN_MARKERS_WARN) or blob_on_part:
        where = "the part" if blob_on_part else f"{glared} markers"
        return _check(
            "glare",
            "fail",
            f"Lower the screen brightness or tilt the phone a little — glare covers {where}.",
            glared,
            GLARE_FAIL_MARKERS,
        )
    if glared or blob_mm2 > 0:
        where = f"{glared} marker{'s' if glared != 1 else ''}" if glared else "part of the stage"
        return _check(
            "glare",
            "warn",
            f"Some glare on {where} — dim the screen or turn away from the lamp.",
            glared,
            GLARE_FAIL_MARKERS,
        )
    return _check("glare", "ok", "No glare.", 0, GLARE_FAIL_MARKERS)


def moire_amplitude(
    img: U8, det: MatDetection, mask: BoolMask | None = None, max_side: int = 768
) -> tuple[float, float]:
    """(rms grey level of the dominant periodic pattern on the plain stage, spectral peak ratio).

    The stage (part masked out and filled with the stage median) is high-passed, Hann-windowed and Fourier transformed.
    The strongest mid/high-frequency peak is compared with the median magnitude of its frequency ring; when it stands
    out, its band is inverted back to image space to get the pattern's amplitude.
    """
    gray = _gray(img).astype(np.float32)
    st = det.mat.stage.inset(2.0)
    poly = det.to_px(st.corners())
    h, w = gray.shape
    x0, y0 = max(int(poly[:, 0].min()), 0), max(int(poly[:, 1].min()), 0)
    x1, y1 = min(int(poly[:, 0].max()) + 1, w), min(int(poly[:, 1].max()) + 1, h)
    if x1 - x0 < 32 or y1 - y0 < 32:
        return 0.0, 0.0
    cx, cy = (x0 + x1) // 2, (y0 + y1) // 2
    hw, hh = min((x1 - x0) // 2, max_side // 2), min((y1 - y0) // 2, max_side // 2)
    x0, x1, y0, y1 = cx - hw, cx + hw, cy - hh, cy + hh
    roi = gray[y0:y1, x0:x1].copy()
    valid = _poly_mask((h, w), poly)[y0:y1, x0:x1]
    if mask is not None:
        valid &= ~(cv2.dilate(mask.astype(np.uint8), np.ones((9, 9), np.uint8))[y0:y1, x0:x1] > 0)
    if valid.mean() < 0.3:
        return 0.0, 0.0
    roi[~valid] = float(np.median(roi[valid]))
    hp = roi - cv2.GaussianBlur(roi, (0, 0), 6.0)
    hp[~valid] = 0.0
    win = np.outer(np.hanning(hp.shape[0]), np.hanning(hp.shape[1])).astype(np.float32)
    F = np.fft.fftshift(np.fft.fft2(hp * win))
    mag = np.abs(F)
    fh, fw = mag.shape
    yy, xx = np.mgrid[0:fh, 0:fw]
    ry, rx = (yy - fh // 2) / fh, (xx - fw // 2) / fw
    rad = np.hypot(rx, ry)
    band = (rad > 0.02) & (rad < 0.45)
    if not band.any():
        return 0.0, 0.0
    m = np.where(band, mag, 0)
    k = int(np.argmax(m))
    py, px = divmod(k, fw)
    r0 = rad[py, px]
    ring = band & (np.abs(rad - r0) < 0.02)
    ratio = float(mag[py, px] / (np.median(mag[ring]) + 1e-9))
    if ratio < MOIRE_PEAK_RATIO:
        return 0.0, ratio
    sel = np.zeros_like(mag, dtype=bool)
    for sy, sx in ((py, px), (fh - py, fw - px)):
        sel[max(sy - 3, 0) : sy + 4, max(sx - 3, 0) : sx + 4] = True
    comp = np.real(np.fft.ifft2(np.fft.ifftshift(np.where(sel, F, 0))))
    good = (win > 0.3) & valid
    amp = float(np.sqrt(np.mean((comp[good] / win[good]) ** 2))) if good.any() else 0.0
    return amp, ratio


def check_moire(img: U8, det: MatDetection | None, mask: BoolMask | None) -> CaptureCheck:
    if det is None:
        return _check("moire", "ok", "Moiré not checked (no mat).")
    amp, _ = moire_amplitude(img, det, mask)
    if amp >= MOIRE_FAIL:
        return _check(
            "moire",
            "fail",
            "Wavy stripes from the screen are visible — move the phone a little further away or rotate it slightly.",
            amp,
            MOIRE_WARN,
        )
    if amp >= MOIRE_WARN:
        return _check(
            "moire",
            "warn",
            "Faint screen stripes are visible — a slightly different distance or angle removes them.",
            amp,
            MOIRE_WARN,
        )
    return _check("moire", "ok", "No screen stripes.", amp, MOIRE_WARN)


def check_scale(det: MatDetection | None) -> CaptureCheck:
    if det is None:
        return _check("scale", "fail", "Scale unknown without the mat — retake with the mat in view.")
    sides = det.marker_side_mm() / det.mat.marker_size_mm
    dev = float(np.max(np.abs(sides - 1.0)))
    if dev > SCALE_FAIL:
        return _check(
            "scale",
            "fail",
            f"Markers are {dev * 100:.1f} % off their expected size — redo the card scale step (browser zoom 100 %) "
            "or reprint at 100 %.",
            dev,
            SCALE_WARN,
        )
    if dev > SCALE_WARN:
        return _check(
            "scale",
            "warn",
            f"Marker sizes vary by {dev * 100:.1f} % — check the mat is flat and shown at 1:1.",
            dev,
            SCALE_WARN,
        )
    return _check("scale", "ok", "Marker sizes match the mat.", dev, SCALE_WARN)


def edge_contrast(img: U8, det: MatDetection, mask: BoolMask, n_points: int = 360) -> tuple[float, float, float]:
    """(share of the part's outline with weak contrast, median contrast across the outline, part/stage colour distance).

    Contrast across the outline = colour distance between the mean of 0.4–1.2 mm inside and 0.4–1.2 mm outside the
    mask edge, along the edge normal. A mask that follows real edges has strong contrast everywhere; one that leaked
    into or stopped inside a part that blends with the stage has long stretches of weak contrast.
    """
    cs, _ = cv2.findContours(mask.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    if not cs:
        return 1.0, 0.0, 0.0
    c = max(cs, key=cv2.contourArea).reshape(-1, 2).astype(np.float64)
    if len(c) < 20:
        return 1.0, 0.0, 0.0
    ys, xs = np.nonzero(mask)
    ppm = det.px_per_mm_at(tuple(det.to_mm(np.array([[xs.mean(), ys.mean()]]))[0]))
    idx = np.linspace(0, len(c) - 1, min(n_points, len(c))).astype(int)
    k = max(2, len(c) // 200)
    tang = np.roll(c, -k, axis=0) - np.roll(c, k, axis=0)
    tang = tang[idx] / np.maximum(np.linalg.norm(tang[idx], axis=1, keepdims=True), 1e-9)
    nrm = np.c_[-tang[:, 1], tang[:, 0]]
    p = c[idx]
    # orient normals outwards: the inside sample must land on the mask
    probe = np.round(p - nrm * 0.8 * ppm).astype(int)
    h, w = mask.shape
    probe[:, 0] = np.clip(probe[:, 0], 0, w - 1)
    probe[:, 1] = np.clip(probe[:, 1], 0, h - 1)
    flip = ~mask[probe[:, 1], probe[:, 0]]
    nrm[flip] *= -1
    offs = np.linspace(0.4, 1.2, 5) * ppm
    imgf = img.astype(np.float32)

    def sample(sign: float) -> NDArray[np.float32]:
        pts = p[:, None, :] + sign * offs[None, :, None] * nrm[:, None, :]
        vals = cv2.remap(
            imgf,
            pts[..., 0].astype(np.float32),
            pts[..., 1].astype(np.float32),
            cv2.INTER_LINEAR,
            borderMode=cv2.BORDER_REPLICATE,
        )
        return np.asarray(vals.mean(axis=1), dtype=np.float32)

    inside, outside = sample(-1.0), sample(1.0)
    d = np.linalg.norm(inside - outside, axis=1)
    core = cv2.erode(mask.astype(np.uint8), np.ones((5, 5), np.uint8)) > 0
    st = _poly_mask(mask.shape, det.to_px(det.mat.stage.corners()))
    bg = st & ~(cv2.dilate(mask.astype(np.uint8), np.ones((15, 15), np.uint8)) > 0)
    sep = 0.0
    if core.any() and bg.any():
        sep = float(np.linalg.norm(np.median(imgf[core], axis=0) - np.median(imgf[bg], axis=0)))
    return float(np.mean(d < EDGE_MIN_CONTRAST)), float(np.median(d)), sep


def part_in_shadow_cone(img: U8, det: MatDetection, mask: BoolMask) -> bool:
    """True when the part's median colour is the stage's colour scaled by 0.70–1.05 (same chroma)."""
    core = cv2.erode(mask.astype(np.uint8), np.ones((5, 5), np.uint8)) > 0
    st = _poly_mask(mask.shape, det.to_px(det.mat.stage.corners()))
    bg = st & ~(cv2.dilate(mask.astype(np.uint8), np.ones((15, 15), np.uint8)) > 0)
    if not core.any() or not bg.any():
        return False
    imgf = img.astype(np.float32)
    P = np.median(imgf[core], axis=0)
    B = np.median(imgf[bg], axis=0)
    k = float(P @ B / max(float(B @ B), 1e-6))
    chroma = float(np.linalg.norm(P - k * B))
    return CONE_MIN_RATIO <= k <= 1.05 and chroma < CONE_CHROMA_TOL


def check_contrast(
    img: U8,
    det: MatDetection | None,
    mask: BoolMask | None,
    largest_fraction: float | None = None,
) -> CaptureCheck:
    if det is None or mask is None or not mask.any():
        return _check("contrast", "ok", "Contrast not checked yet (no part mask).")
    img3 = img if img.ndim == 3 else np.asarray(cv2.cvtColor(img, cv2.COLOR_GRAY2BGR), dtype=np.uint8)
    weak, med, sep = edge_contrast(img3, det, mask)
    like_shadow = part_in_shadow_cone(img3, det, mask)
    st = _poly_mask(mask.shape, det.to_px(det.mat.stage.corners()))
    stage_lum = float(np.median(_gray(img3)[st & ~mask])) if (st & ~mask).any() else 255.0
    fix = (
        "switch the screen mat to the dark stage (or use a darker surface)"
        if stage_lum >= 128
        else "switch the screen mat to the light stage (or use a lighter surface)"
    )
    reason = f"The part blends into the background — {fix}."
    frag = largest_fraction is not None and largest_fraction < CONTRAST_MIN_LARGEST_FRACTION
    hull = cv2.convexHull(np.argwhere(mask)[:, ::-1].astype(np.int32))
    solidity = float(mask.sum()) / max(float(cv2.contourArea(hull)), 1.0)
    if (
        weak > CONTRAST_FAIL_WEAK
        or sep < CONTRAST_MIN_SEPARATION
        or frag
        or solidity < CONTRAST_MIN_SOLIDITY
        or like_shadow
    ):
        return _check("contrast", "fail", reason, weak, CONTRAST_FAIL_WEAK)
    if weak > CONTRAST_WARN_WEAK:
        return _check(
            "contrast", "warn", f"Parts of the outline are faint — {fix} for cleaner edges.", weak, CONTRAST_FAIL_WEAK
        )
    return _check(
        "contrast", "ok", f"The part stands out from the stage (edge contrast {med:.0f}/255).", weak, CONTRAST_FAIL_WEAK
    )


_ORDER = ("markers", "reprojection", "scale", "coverage", "contrast", "glare", "tilt", "blur", "moire", "exposure")


def run_gate(
    img: U8,
    det: MatDetection | None,
    mask: BoolMask | None = None,
    *,
    pose: PoseEstimate | None = None,
    largest_fraction: float | None = None,
) -> CaptureReport:
    """All capture checks. `mask` (full-frame part mask) enables the coverage, contrast and part-exposure checks;
    `largest_fraction` (share of the segmenter's foreground in its largest component) feeds the contrast check."""
    if det is not None and pose is None:
        try:
            pose = estimate_pose(det)
        except Exception:
            pose = None
    gray = _gray(img)
    checks = [
        check_markers(det),
        check_reprojection(det),
        check_blur(gray, det),
        check_coverage(det, mask),
        check_contrast(img, det, mask, largest_fraction),
        check_tilt(pose),
        check_exposure(img, det, mask),
        check_glare(img, det, mask),
        check_moire(img, det, mask),
        check_scale(det),
    ]
    fails = sorted((c for c in checks if c.severity == "fail"), key=lambda c: _ORDER.index(c.name))
    return CaptureReport(passed=not fails, checks=checks, retake_reason=fails[0].reason if fails else None)
