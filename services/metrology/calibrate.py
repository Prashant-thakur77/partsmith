"""Mat detection, image→mat homography, camera pose, plane-at-height homographies and rectification.

Conventions: image points are OpenCV pixel coordinates (integer = pixel centre). Mat frame x right, y down, z into the table,
so a point at height h above the mat has z = −h. Homographies called `H` map image px → mat mm.
"""

from __future__ import annotations

import io
import math
from dataclasses import dataclass, field
from typing import Literal

import cv2
import numpy as np
from numpy.typing import NDArray
from partsmith_schemas.measurement import Calibration, CameraPose

from .mats import MatSpec, Rect, aruco_board, aruco_dictionary, get_mat, identify, mat_of_marker

F64 = NDArray[np.float64]
IntrinsicsSource = Literal["calibrated", "exif", "estimated", "synthetic"]

RANSAC_THRESHOLD_MM = 0.6
MIN_MARKERS = 2
DEFAULT_FOCAL35_MM = 26.0  # typical phone main camera, used only when nothing better is known
FOCAL35_PLAUSIBLE = (12.0, 120.0)
_DIAG35_MM = math.hypot(36.0, 24.0)


class MatNotFoundError(ValueError):
    """Fewer than two markers of a known mat were found."""


@dataclass
class MatDetection:
    """Markers found in one photo and the fitted homography (image px → mat mm on the mat plane)."""

    mat: MatSpec
    ids: NDArray[np.int32]  # detected ids on this mat, one per marker
    corners_px: F64  # (N, 4, 2) raw sub-pixel corners, TL TR BR BL
    img_pts: F64  # (4N, 2) undistorted px (== raw when no distortion model)
    mat_pts: F64  # (4N, 2) mm
    inliers: NDArray[np.bool_]  # (4N,)
    H: F64  # undistorted image px -> mat mm
    reproj_px_rms: float
    reproj_px_max: float
    reproj_mm_rms: float
    reproj_mm_max: float
    image_size: tuple[int, int]  # (w, h)
    K: F64 | None = None
    dist: F64 | None = None
    foreign_ids: list[int] = field(default_factory=list)  # ids seen that belong to another mat or none
    recovered: int = 0  # markers recovered by board-guided refinement

    @property
    def n_markers(self) -> int:
        return len(self.ids)

    @property
    def H_inv(self) -> F64:
        return np.linalg.inv(self.H)

    def undistort(self, pts_px: F64) -> F64:
        p = np.asarray(pts_px, dtype=np.float64).reshape(-1, 2)
        if self.dist is None or self.K is None or not np.any(self.dist):
            return p
        return cv2.undistortPoints(p.reshape(-1, 1, 2), self.K, self.dist, P=self.K).reshape(-1, 2).astype(np.float64)

    def distort(self, pts_px: F64) -> F64:
        p = np.asarray(pts_px, dtype=np.float64).reshape(-1, 2)
        if self.dist is None or self.K is None or not np.any(self.dist):
            return p
        Kinv = np.linalg.inv(self.K)
        norm = (np.c_[p, np.ones(len(p))] @ Kinv.T)[:, :2]
        obj = np.c_[norm, np.ones(len(p))].reshape(-1, 1, 3)
        out, _ = cv2.projectPoints(obj, np.zeros(3), np.zeros(3), self.K, self.dist)
        return out.reshape(-1, 2).astype(np.float64)

    def to_mm(self, pts_px: F64, H: F64 | None = None) -> F64:
        """Raw image px → mat mm (on the plane of `H`, default the mat plane)."""
        return apply_h(self.H if H is None else H, self.undistort(pts_px))

    def to_px(self, pts_mm: F64, H: F64 | None = None) -> F64:
        """Mat mm → raw image px."""
        return self.distort(apply_h(np.linalg.inv(self.H if H is None else H), np.asarray(pts_mm, dtype=np.float64)))

    def px_per_mm_at(self, pt_mm: tuple[float, float]) -> float:
        """Local image resolution (geometric mean of the two axes) at a mat point."""
        return local_scale(np.linalg.inv(self.H), pt_mm)

    def marker_side_mm(self) -> F64:
        """Mean side length (mm, through H) of every detected marker — used by the scale check."""
        out = []
        for c in self.corners_px:
            m = self.to_mm(c)
            out.append(float(np.mean(np.linalg.norm(m - np.roll(m, -1, axis=0), axis=1))))
        return np.array(out)


@dataclass
class PoseEstimate:
    K: F64
    dist: F64
    R: F64  # mat -> camera rotation
    t: F64  # mat -> camera translation (mm)
    intrinsics_source: IntrinsicsSource
    reproj_px_rms: float

    @property
    def camera_center_mm(self) -> F64:
        return np.asarray(-self.R.T @ self.t, dtype=np.float64)

    @property
    def camera_height_mm(self) -> float:
        """Height of the camera centre above the mat plane (mat z points into the table)."""
        return float(-self.camera_center_mm[2])

    @property
    def nadir_mm(self) -> tuple[float, float]:
        """Point on the mat straight below the camera centre."""
        c = self.camera_center_mm
        return float(c[0]), float(c[1])

    @property
    def tilt_deg(self) -> float:
        """Angle between the optical axis and the mat normal."""
        return float(np.degrees(np.arccos(np.clip(abs(self.R[2, 2]), -1.0, 1.0))))

    def to_schema(self) -> CameraPose:
        return CameraPose(
            K=self.K.tolist(),
            dist=[float(x) for x in self.dist.ravel()],
            R=self.R.tolist(),
            t_mm=[float(x) for x in self.t.ravel()],
            camera_height_mm=self.camera_height_mm,
            tilt_deg=self.tilt_deg,
            intrinsics_source=self.intrinsics_source,
        )


@dataclass
class Rectified:
    """Orthographic mat-frame image. Pixel (row v, col u) centre sits at mat mm (x0 + (u+0.5)/ppm, y0 + (v+0.5)/ppm)."""

    image: NDArray[np.uint8]
    px_per_mm: float
    origin_mm: tuple[float, float]  # mat mm of the rectified image's top-left corner

    def px_to_mm(self, pts_px: F64) -> F64:
        p = np.asarray(pts_px, dtype=np.float64).reshape(-1, 2)
        return np.asarray((p + 0.5) / self.px_per_mm + np.asarray(self.origin_mm), dtype=np.float64)

    def mm_to_px(self, pts_mm: F64) -> F64:
        p = np.asarray(pts_mm, dtype=np.float64).reshape(-1, 2)
        return np.asarray((p - np.asarray(self.origin_mm)) * self.px_per_mm - 0.5, dtype=np.float64)


# ---------------------------------------------------------------- small helpers


def apply_h(H: F64, pts: F64) -> F64:
    p = np.asarray(pts, dtype=np.float64).reshape(-1, 2)
    q = np.c_[p, np.ones(len(p))] @ np.asarray(H, dtype=np.float64).T
    return np.asarray(q[:, :2] / q[:, 2:3], dtype=np.float64)


def local_scale(H: F64, pt: tuple[float, float]) -> float:
    """sqrt(|det J|) of the map `H` at `pt` (output units per input unit)."""
    x, y = pt
    eps = 0.5
    p = apply_h(H, np.array([[x, y], [x + eps, y], [x, y + eps]]))
    jx, jy = (p[1] - p[0]) / eps, (p[2] - p[0]) / eps
    return float(math.sqrt(abs(jx[0] * jy[1] - jx[1] * jy[0])))


def _gray(img: NDArray[np.uint8]) -> NDArray[np.uint8]:
    if img.ndim == 2:
        return img
    return np.asarray(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), dtype=np.uint8)


def _detector() -> cv2.aruco.ArucoDetector:
    p = cv2.aruco.DetectorParameters()
    p.cornerRefinementMethod = cv2.aruco.CORNER_REFINE_SUBPIX
    p.cornerRefinementWinSize = 6
    p.relativeCornerRefinmentWinSize = 0.3
    p.cornerRefinementMaxIterations = 60
    p.cornerRefinementMinAccuracy = 0.005
    p.adaptiveThreshWinSizeMax = 53
    return cv2.aruco.ArucoDetector(aruco_dictionary(), p)


def _refine_corners(gray: NDArray[np.uint8], corners: F64) -> F64:
    """Corners as intersections of sub-pixel edge lines.

    A marker's outer corner is an L-junction, not a saddle, so gradient-based corner refinement pulls it ~0.1–0.4 px
    inwards. Instead, each side's edge is located at the 50 % crossing between the black border and the white quiet zone
    along short normal profiles (middle 70 % of the side), a line is fitted per side, and adjacent lines are intersected.
    Markers too small for that keep the detector's corners.
    """
    g = gray.astype(np.float32)
    out = np.asarray(corners, dtype=np.float64).copy()
    for i, c in enumerate(out):
        side = float(np.mean(np.linalg.norm(c - np.roll(c, -1, axis=0), axis=1)))
        cell = side / 7.0
        if cell < 3.0:
            continue
        reach = float(np.clip(0.45 * cell, 1.5, 8.0))
        offs = np.arange(-reach, reach + 1e-9, 0.25)
        centre = c.mean(axis=0)
        lines: list[tuple[F64, F64]] = []
        for k in range(4):
            a, b = c[k], c[(k + 1) % 4]
            u = (b - a) / max(np.linalg.norm(b - a), 1e-9)
            n = np.array([-u[1], u[0]])
            if n @ ((a + b) / 2 - centre) < 0:
                n = -n
            ts = np.linspace(0.15, 0.85, max(8, int(side * 0.7)))
            base = a[None, :] + ts[:, None] * (b - a)[None, :]
            pts = base[:, None, :] + offs[None, :, None] * n[None, None, :]
            prof = cv2.remap(
                g, pts[..., 0].astype(np.float32), pts[..., 1].astype(np.float32), cv2.INTER_LINEAR
            ).astype(np.float64)
            m = max(2, len(offs) // 6)
            lo, hi = prof[:, :m].mean(axis=1), prof[:, -m:].mean(axis=1)
            good = hi - lo > 20.0
            if good.sum() < 4:
                break
            mid = (lo + hi) / 2
            edge_pts = []
            for j in np.flatnonzero(good):
                above = np.flatnonzero(prof[j] >= mid[j])
                if len(above) == 0 or above[0] == 0:
                    continue
                q = above[0]
                p0, p1 = prof[j, q - 1], prof[j, q]
                frac = (mid[j] - p0) / max(p1 - p0, 1e-9)
                edge_pts.append(base[j] + (offs[q - 1] + frac * (offs[q] - offs[q - 1])) * n)
            if len(edge_pts) < 4:
                break
            e = np.array(edge_pts)
            mu = e.mean(axis=0)
            _, _, vt = np.linalg.svd(e - mu)
            lines.append((mu, vt[0]))
        if len(lines) != 4:
            continue
        new = np.empty((4, 2))
        ok = True
        for k in range(4):
            (p1, d1), (p2, d2) = lines[(k - 1) % 4], lines[k]
            A = np.c_[d1, -d2]
            if abs(np.linalg.det(A)) < 1e-6:
                ok = False
                break
            s = np.linalg.solve(A, p2 - p1)
            new[k] = p1 + s[0] * d1
        if ok and np.max(np.linalg.norm(new - c, axis=1)) < 0.5 * cell:
            out[i] = new
    return out


# ---------------------------------------------------------------- detection


def detect_mat(
    img_bgr: NDArray[np.uint8], *, K: F64 | None = None, dist: F64 | None = None, mat_id: str | None = None
) -> MatDetection:
    """Find mat markers, identify the mat from their ids, fit a RANSAC homography image px → mat mm.

    `K`/`dist` (from a camera calibration) undistort corner points before the fit. Raises `MatNotFoundError` when fewer
    than two markers of one mat are visible.
    """
    gray = _gray(img_bgr)
    h_img, w_img = gray.shape[:2]
    det = _detector()
    corners, ids, rejected = det.detectMarkers(gray)
    if ids is None or len(ids) == 0:
        raise MatNotFoundError("No mat markers found.")
    flat_ids = [int(i) for i in ids.ravel()]
    try:
        mat = get_mat(mat_id) if mat_id else identify(flat_ids)
    except ValueError as e:
        raise MatNotFoundError(str(e)) from None

    recovered = 0
    if len(set(flat_ids) & set(mat.ids)) >= 1:
        try:
            before = len(flat_ids)
            corners, ids, rejected, _ = det.refineDetectedMarkers(gray, aruco_board(mat), corners, ids, rejected)
            flat_ids = [int(i) for i in ids.ravel()] if ids is not None else []
            recovered = max(0, len(flat_ids) - before)
        except cv2.error:
            pass

    keep_c: list[F64] = []
    keep_i: list[int] = []
    foreign: list[int] = []
    seen: set[int] = set()
    for c, i in zip(corners, flat_ids, strict=True):
        if i in mat.ids and i not in seen:
            seen.add(i)
            keep_c.append(np.asarray(c, dtype=np.float64).reshape(4, 2))
            keep_i.append(i)
        elif mat_of_marker(i) != mat.mat_id:
            foreign.append(i)
    if len(keep_i) < MIN_MARKERS:
        raise MatNotFoundError(f"Only {len(keep_i)} marker(s) of mat {mat.mat_id} found; need at least {MIN_MARKERS}.")

    raw = _refine_corners(gray, np.stack(keep_c))
    K_ = None if K is None else np.asarray(K, dtype=np.float64)
    d_ = None if dist is None else np.asarray(dist, dtype=np.float64).ravel()
    tmp = MatDetection(
        mat=mat,
        ids=np.array(keep_i, dtype=np.int32),
        corners_px=raw,
        img_pts=raw.reshape(-1, 2),
        mat_pts=np.concatenate([mat.marker_corners_mm(i) for i in keep_i]),
        inliers=np.ones(4 * len(keep_i), dtype=bool),
        H=np.eye(3),
        reproj_px_rms=0.0,
        reproj_px_max=0.0,
        reproj_mm_rms=0.0,
        reproj_mm_max=0.0,
        image_size=(w_img, h_img),
        K=K_,
        dist=d_,
        foreign_ids=foreign,
        recovered=recovered,
    )
    tmp.img_pts = tmp.undistort(raw.reshape(-1, 2))
    H, inl = cv2.findHomography(
        tmp.img_pts, tmp.mat_pts, cv2.RANSAC, RANSAC_THRESHOLD_MM, maxIters=4000, confidence=0.999
    )
    if H is None:
        raise MatNotFoundError("Could not fit the mat plane from the detected markers.")
    inliers = inl.ravel().astype(bool)
    # Least-squares refit on the inliers (RANSAC's own refinement minimises the same error; this pins it down).
    H2, _ = cv2.findHomography(tmp.img_pts[inliers], tmp.mat_pts[inliers], 0)
    if H2 is not None:
        H = H2
    tmp.H = np.asarray(H / H[2, 2], dtype=np.float64)
    tmp.inliers = inliers
    e_mm = np.linalg.norm(apply_h(tmp.H, tmp.img_pts[inliers]) - tmp.mat_pts[inliers], axis=1)
    e_px = np.linalg.norm(apply_h(np.linalg.inv(tmp.H), tmp.mat_pts[inliers]) - tmp.img_pts[inliers], axis=1)
    tmp.reproj_mm_rms = float(np.sqrt(np.mean(e_mm**2)))
    tmp.reproj_mm_max = float(e_mm.max())
    tmp.reproj_px_rms = float(np.sqrt(np.mean(e_px**2)))
    tmp.reproj_px_max = float(e_px.max())
    return tmp


# ---------------------------------------------------------------- intrinsics


def intrinsics_from_focal35(focal35_mm: float, image_size: tuple[int, int]) -> F64:
    """K from a 35 mm-equivalent focal length (diagonal convention), principal point at the image centre."""
    w, h = image_size
    f = focal35_mm * math.hypot(w, h) / _DIAG35_MM
    return np.array([[f, 0, (w - 1) / 2.0], [0, f, (h - 1) / 2.0], [0, 0, 1.0]])


def exif_focal35_mm(img_bytes: bytes) -> float | None:
    """`FocalLengthIn35mmFilm` from EXIF, if present and plausible."""
    try:
        from PIL import Image

        with Image.open(io.BytesIO(img_bytes)) as im:
            exif = im.getexif()
            val = exif.get_ifd(0x8769).get(0xA405) or exif.get(0xA405)
    except Exception:
        return None
    if val is None:
        return None
    try:
        f = float(val)
    except (TypeError, ValueError):
        return None
    return f if FOCAL35_PLAUSIBLE[0] <= f <= FOCAL35_PLAUSIBLE[1] else None


def estimate_focal_px(H_img_to_mat: F64, image_size: tuple[int, int]) -> float | None:
    """Single-view focal length from a plane homography (square pixels, principal point at the centre).

    With G = T⁻¹·H_mat→img ∝ K[r1 r2 t] and ω = diag(1/f², 1/f², 1), the two constraints g1ᵀωg2 = 0 and
    g1ᵀωg1 = g2ᵀωg2 are linear in u = 1/f². Returns None when the view is too close to fronto-parallel to tell.
    """
    w, h = image_size
    T = np.array([[1, 0, (w - 1) / 2.0], [0, 1, (h - 1) / 2.0], [0, 0, 1.0]])
    G = np.linalg.inv(T) @ np.linalg.inv(H_img_to_mat)
    G = G / np.linalg.norm(G[:, 0])
    g1, g2 = G[:, 0], G[:, 1]
    a = np.array([g1[0] * g2[0] + g1[1] * g2[1], g1[0] ** 2 + g1[1] ** 2 - g2[0] ** 2 - g2[1] ** 2])
    b = np.array([g1[2] * g2[2], g1[2] ** 2 - g2[2] ** 2])
    # Each row: a_i·u + b_i = 0. Rows with tiny b carry no focal information (fronto-parallel).
    denom = float(a @ a)
    if denom <= 0:
        return None
    u = -float(a @ b) / denom
    if not np.isfinite(u) or u <= 0:
        return None
    f = 1.0 / math.sqrt(u)
    # Reject when the perspective terms are too small for a stable estimate (≈ < 4° tilt).
    persp = math.hypot(g1[2], g2[2]) * f
    if persp < 0.07:
        return None
    f35 = f * _DIAG35_MM / math.hypot(w, h)
    if not FOCAL35_PLAUSIBLE[0] <= f35 <= FOCAL35_PLAUSIBLE[1]:
        return None
    return f


# ---------------------------------------------------------------- pose


def estimate_pose(
    det: MatDetection,
    K: F64 | None = None,
    *,
    focal35_mm: float | None = None,
    intrinsics_source: IntrinsicsSource | None = None,
) -> PoseEstimate:
    """Camera pose from the detected corners (IPPE + LM refinement).

    Intrinsics priority: explicit `K` (calibration file) > `det.K` > EXIF 35 mm-equivalent focal > single-view estimate
    from the homography > a 26 mm-equivalent default.
    """
    src: IntrinsicsSource
    if K is not None:
        K_ = np.asarray(K, dtype=np.float64)
        src = "calibrated"
    elif det.K is not None:
        K_ = det.K
        src = "calibrated"
    elif focal35_mm is not None:
        K_ = intrinsics_from_focal35(focal35_mm, det.image_size)
        src = "exif"
    else:
        f = estimate_focal_px(det.H, det.image_size)
        if f is None:
            K_ = intrinsics_from_focal35(DEFAULT_FOCAL35_MM, det.image_size)
        else:
            w, h = det.image_size
            K_ = np.array([[f, 0, (w - 1) / 2.0], [0, f, (h - 1) / 2.0], [0, 0, 1.0]])
        src = "estimated"
    if intrinsics_source is not None:
        src = intrinsics_source
    obj = np.c_[det.mat_pts[det.inliers], np.zeros(int(det.inliers.sum()))].astype(np.float64)
    img = det.img_pts[det.inliers].astype(np.float64)
    ok, rvec, tvec = cv2.solvePnP(obj, img, K_, None, flags=cv2.SOLVEPNP_IPPE)
    if not ok:
        raise MatNotFoundError("Camera pose could not be solved from the markers.")
    rvec, tvec = cv2.solvePnPRefineLM(obj, img, K_, None, rvec, tvec)
    R, _ = cv2.Rodrigues(rvec)
    proj, _ = cv2.projectPoints(obj, rvec, tvec, K_, None)
    err = np.linalg.norm(proj.reshape(-1, 2) - img, axis=1)
    return PoseEstimate(
        K=K_,
        dist=np.zeros(5) if det.dist is None else det.dist,
        R=np.asarray(R, dtype=np.float64),
        t=np.asarray(tvec, dtype=np.float64).ravel(),
        intrinsics_source=src,
        reproj_px_rms=float(np.sqrt(np.mean(err**2))),
    )


def height_scale(camera_height_mm: float, h_mm: float) -> float:
    """Scale (Zc − h)/Zc from a plane at height h to the mat plane, seen from a camera Zc above the mat (reporting)."""
    if camera_height_mm <= h_mm:
        raise ValueError("the camera must be above the plane")
    return (camera_height_mm - h_mm) / camera_height_mm


def plane_homography(pose: PoseEstimate, height_mm: float, H_ground: F64 | None = None) -> F64:
    """Image px → mat (x, y) mm for points on the plane `height_mm` above the mat.

    Exact projective model. With `H_ground` (the fitted mat-plane homography) the result is that homography followed by
    the homothety about the camera nadir with ratio s = (Zc − h)/Zc — every viewing ray meets the raised plane at
    nadir + s·(ground point − nadir). Without it the model homography K[r1 r2 (t − h·r3)] is inverted directly.
    """
    if H_ground is not None:
        s = height_scale(pose.camera_height_mm, height_mm)
        nx, ny = pose.nadir_mm
        A = np.array([[s, 0.0, (1 - s) * nx], [0.0, s, (1 - s) * ny], [0.0, 0.0, 1.0]])
        out = A @ np.asarray(H_ground, dtype=np.float64)
    else:
        r1, r2, r3 = pose.R[:, 0], pose.R[:, 1], pose.R[:, 2]
        M = pose.K @ np.c_[r1, r2, pose.t - height_mm * r3]
        out = np.linalg.inv(M)
    return np.asarray(out / out[2, 2], dtype=np.float64)


# ---------------------------------------------------------------- rectification


def rectify(
    img: NDArray[np.uint8],
    H: F64,
    px_per_mm: float = 10.0,
    region: Rect | None = None,
    *,
    K: F64 | None = None,
    dist: F64 | None = None,
    interpolation: int = cv2.INTER_LINEAR,
) -> Rectified:
    """Orthographic mat-frame image of `region` (default: the whole homography's mat, caller passes the stage).

    `H` maps (undistorted) image px → mat mm on the plane of interest. With `K`/`dist` the lens distortion is undone in
    the same resampling pass.
    """
    if region is None:
        raise ValueError("pass the mat region to rectify (e.g. mat.stage or mat.bounds)")
    w = max(1, round(region.w_mm * px_per_mm))
    h = max(1, round(region.h_mm * px_per_mm))
    A = np.array(
        [
            [1 / px_per_mm, 0, region.x_mm + 0.5 / px_per_mm],
            [0, 1 / px_per_mm, region.y_mm + 0.5 / px_per_mm],
            [0, 0, 1.0],
        ]
    )
    M = np.linalg.inv(H) @ A  # rectified px -> undistorted image px
    if K is None or dist is None or not np.any(dist):
        out = cv2.warpPerspective(
            img, M, (w, h), flags=interpolation | cv2.WARP_INVERSE_MAP, borderMode=cv2.BORDER_REPLICATE
        )
    else:
        uu, vv = np.meshgrid(np.arange(w, dtype=np.float64), np.arange(h, dtype=np.float64))
        und = apply_h(M, np.c_[uu.ravel(), vv.ravel()])
        Kinv = np.linalg.inv(K)
        norm = np.c_[und, np.ones(len(und))] @ Kinv.T
        proj, _ = cv2.projectPoints(norm.reshape(-1, 1, 3), np.zeros(3), np.zeros(3), K, dist)
        mp = proj.reshape(h, w, 2).astype(np.float32)
        out = cv2.remap(img, mp[..., 0], mp[..., 1], interpolation, borderMode=cv2.BORDER_REPLICATE)
    return Rectified(image=np.asarray(out, dtype=np.uint8), px_per_mm=px_per_mm, origin_mm=(region.x_mm, region.y_mm))


def calibration_from(
    det: MatDetection, pose: PoseEstimate | None, rectified_px_per_mm: float, scale_correction: float = 1.0
) -> Calibration:
    return Calibration(
        mat_id=det.mat.mat_id,
        mat_kind=det.mat.kind,
        markers_found=det.n_markers,
        homography=det.H.tolist(),
        reproj_error_px=det.reproj_px_rms,
        reproj_error_mm=det.reproj_mm_rms,
        rectified_px_per_mm=rectified_px_per_mm,
        scale_correction=scale_correction,
        pose=None if pose is None else pose.to_schema(),
    )
