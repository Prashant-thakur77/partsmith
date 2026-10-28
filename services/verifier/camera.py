"""Camera-frame comparison: judge the model as the phone saw the part.

A rectified (orthographic) comparison of a thick part suffers parallax: the camera sees top edges enlarged and pushed
away from its nadir, and a through-hole shows only the lens where its top and bottom openings overlap. Rendering the
model through the photo's own camera (K, R, t) reproduces exactly those effects, so the photo mask and the model
silhouette can be compared pixel for pixel with no special cases.

Steps for one view with a pose:

1. Place the model on the mat. The rectified alignment gives model -> part frame (2-D, rigid, maybe mirrored);
   ``part_to_mat`` (from the measurement) gives part -> mat. In 3-D the viewed projection plane lies on the mat and the
   remaining CAD axis points up out of the table (mat z is negative above the table); the sign is chosen so the
   placement is a proper rotation, so a mirrored 2-D match means the part lies upside down. For the top view this is
   exactly ``T . Rz(theta) . diag(1, -1, -1)``. ``CameraView.cad_to_mat`` overrides the derivation.
2. Refine the placement in the image: rotation about the vertical axis and a translation on the mat, never scale,
   minimising the symmetric boundary distance between the rendered silhouette and the photo mask.
3. Metrics in image pixels over a crop around the part; distances are converted to mm with the local scale
   ``px_per_mm_local``.
4. Like-for-like dimensions: the rendered model mask goes through the SAME metrology code as the photo
   (sub-pixel contours -> mat-plane homography, optional top-plane intersection and see-through hole fits ->
   ``build_measurements``), so a parallax bias in the photo's length is matched by the same bias in the model's.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from typing import Any, Literal

import cv2
import numpy as np
import numpy.typing as npt
from partsmith_schemas.common import DataOrigin
from partsmith_schemas.measurement import Measurements, ViewKind
from partsmith_schemas.verification import ViewMetrics
from scipy.ndimage import map_coordinates
from scipy.optimize import minimize

from services.verifier import metrics as M
from services.verifier.render import VIEW_AXES, BoolMask, FloatArray, Frame, camera_coverage

CROP_MARGIN_PX = 40
REFINE_MAXITER = 80


@dataclass(frozen=True)
class CameraView:
    """One photo with a solved pose. All arrays in the photo's raw pixel frame / mat mm.

    - ``K``, ``R``, ``t_mm``: intrinsics and mat -> camera pose (mat frame: x right, y down, z into the table).
    - ``image_mask``: full-frame boolean part mask (the segmentation the metrology used).
    - ``image_field``: the soft coverage map (0..1, full frame) the metrology traced its sub-pixel contours on. When
      given, the photo's edge is its 0.5 crossing, exactly the edge that was measured; otherwise the mask's edge.
    - ``part_to_mat``: 3x3 affine part frame -> mat (``Measurements.part_to_mat`` of this view).
    - ``px_per_mm_local``: image pixels per mm around the part (to report distances in mm).
    - ``top_height_mm``: height of the plane the metrology also mapped contours onto (its height correction);
      None = mat plane only. ``scale_correction``: true mm per nominal mat mm (card / ruler).
    - ``H_ground``: the image -> mat homography the metrology used (default: derived from K, R, t).
    - ``profile``: the ``profile`` passed to ``measure_photo`` ("round" = a cylinder lying on its curved side).
    """

    K: npt.ArrayLike
    R: npt.ArrayLike
    t_mm: npt.ArrayLike
    image_mask: BoolMask
    part_to_mat: npt.ArrayLike
    px_per_mm_local: float
    image_size: tuple[int, int] | None = None  # (width, height); default: the mask's shape
    dist: npt.ArrayLike | None = None
    image_field: npt.ArrayLike | None = None
    top_height_mm: float | None = None
    scale_correction: float = 1.0
    H_ground: npt.ArrayLike | None = None
    profile: Literal["prism", "round"] = "prism"
    cad_to_mat: npt.ArrayLike | None = None

    @property
    def size(self) -> tuple[int, int]:
        if self.image_size is not None:
            return (int(self.image_size[0]), int(self.image_size[1]))
        h, w = np.asarray(self.image_mask).shape[:2]
        return (w, h)


@dataclass
class CameraCompare:
    metrics: ViewMetrics
    distances: M.ContourDistances
    overlay_png: bytes
    placement: FloatArray  # 4x4 CAD -> mat after refinement
    model_to_part: FloatArray  # 3x3: model projection plane -> this view's part frame (refined)
    model_mask: BoolMask  # crop
    photo_mask: BoolMask  # crop
    crop_xy: tuple[int, int]
    part_to_mat: FloatArray  # this view's part frame -> mat (from the CameraView)
    model_measurements: Measurements | None = None
    notes: list[str] = field(default_factory=list)
    excluded_mask: BoolMask | None = None  # crop pixels left out of the comparison (broken region)
    excluded_mm2: float = 0.0
    photo_short_side_mm: float | None = None  # short side of the photo silhouette (for the scale-aware gate)
    px_per_mm: float = 1.0  # local image scale used for the mm distances


Mesh = tuple[FloatArray, Any]  # (vertices, faces) in model coordinates


# ------------------------------------------------------------------ geometry helpers


def _arr(x: npt.ArrayLike) -> FloatArray:
    return np.asarray(x, dtype=np.float64)


def camera_centre(cam: CameraView) -> FloatArray:
    R = _arr(cam.R)
    out: FloatArray = -R.T @ _arr(cam.t_mm).reshape(3)
    return out


def ground_homography(cam: CameraView) -> FloatArray:
    """Image px (undistorted) -> mat (x, y) mm on the mat plane."""
    if cam.H_ground is not None:
        H = _arr(cam.H_ground)
    else:
        R = _arr(cam.R)
        H = np.linalg.inv(_arr(cam.K) @ np.c_[R[:, 0], R[:, 1], _arr(cam.t_mm).reshape(3)])
    return np.asarray(H / H[2, 2], dtype=np.float64)


def plane_homography(cam: CameraView, height_mm: float) -> FloatArray:
    """Image px -> mat (x, y) for points `height_mm` above the mat: the ground homography followed by the homothety
    about the camera nadir with ratio (Zc - h) / Zc."""
    C = camera_centre(cam)
    zc = -C[2]  # camera height above the mat (mat z points into the table)
    s = (zc - height_mm) / zc
    A = np.array([[s, 0.0, (1 - s) * C[0]], [0.0, s, (1 - s) * C[1]], [0.0, 0.0, 1.0]])
    out = A @ ground_homography(cam)
    return np.asarray(out / out[2, 2], dtype=np.float64)


def _apply_h(H: FloatArray, pts: FloatArray) -> FloatArray:
    p = np.c_[pts, np.ones(len(pts))] @ H.T
    out: FloatArray = p[:, :2] / p[:, 2:3]
    return out


def _undistort(cam: CameraView, pts_px: FloatArray) -> FloatArray:
    if cam.dist is None or not np.any(_arr(cam.dist)):
        return pts_px
    K = _arr(cam.K)
    u = cv2.undistortPoints(pts_px.reshape(-1, 1, 2), K, _arr(cam.dist), P=K)
    return np.asarray(u.reshape(-1, 2), dtype=np.float64)


def cad_to_mat_from_alignment(
    vertices: FloatArray, projection: str, model_to_part: npt.ArrayLike, part_to_mat: npt.ArrayLike
) -> FloatArray:
    """4x4 CAD -> mat placement for a part lying with its `projection` plane on the mat (see module docstring)."""
    a, b = VIEW_AXES[projection]
    c = 3 - a - b
    L = _arr(part_to_mat) @ _arr(model_to_part)  # model (a, b) -> mat (x, y)
    P = np.zeros((4, 4))
    P[3, 3] = 1.0
    P[0:2, a] = L[0:2, 0]
    P[0:2, b] = L[0:2, 1]
    P[0:2, 3] = L[0:2, 2]
    P[2, c] = 1.0
    s = 1.0 if np.linalg.det(P[:3, :3]) > 0 else -1.0
    P[2, c] = s
    depth = np.asarray(vertices)[:, c]
    # Resting on the mat: heights above it are negative mat z, so the extreme towards +z touches z = 0.
    P[2, 3] = -depth.max() if s > 0 else depth.min()
    return P


def _mat_rigid(dtheta_deg: float, dx: float, dy: float, centre: FloatArray) -> FloatArray:
    th = np.radians(dtheta_deg)
    c, s = np.cos(th), np.sin(th)
    D = np.eye(4)
    D[:2, :2] = [[c, -s], [s, c]]
    D[:2, 3] = centre - D[:2, :2] @ centre + [dx, dy]
    return D


def model_to_part_from_placement(P: FloatArray, projection: str, part_to_mat: npt.ArrayLike) -> FloatArray:
    """Inverse of `cad_to_mat_from_alignment` for the 2-D part: model (a, b) -> part frame."""
    a, b = VIEW_AXES[projection]
    L = np.eye(3)
    L[0:2, 0] = P[0:2, a]
    L[0:2, 1] = P[0:2, b]
    L[0:2, 2] = P[0:2, 3]
    out: FloatArray = np.linalg.inv(_arr(part_to_mat)) @ L
    return out


# ------------------------------------------------------------------ rendering in a crop


@dataclass(frozen=True)
class _Crop:
    x0: int
    y0: int
    w: int
    h: int

    def K(self, K: FloatArray) -> FloatArray:
        Kc = K.copy()
        Kc[0, 2] -= self.x0
        Kc[1, 2] -= self.y0
        return Kc


def _project(cam: CameraView, P: FloatArray, vertices: FloatArray) -> FloatArray:
    v = vertices @ P[:3, :3].T + P[:3, 3]
    cam_pts = v @ _arr(cam.R).T + _arr(cam.t_mm).reshape(3)
    h = cam_pts @ _arr(cam.K).T
    out: FloatArray = h[:, :2] / h[:, 2:3]
    return out


def _crop_for(cam: CameraView, P: FloatArray, vertices: FloatArray) -> _Crop:
    w, h = cam.size
    uv = _project(cam, P, vertices)
    lo, hi = uv.min(axis=0), uv.max(axis=0)
    ys, xs = np.nonzero(np.asarray(cam.image_mask))
    if len(xs):
        lo = np.minimum(lo, [xs.min(), ys.min()])
        hi = np.maximum(hi, [xs.max(), ys.max()])
    m = max(CROP_MARGIN_PX, 5 * cam.px_per_mm_local)
    x0, y0 = max(int(lo[0] - m), 0), max(int(lo[1] - m), 0)
    x1, y1 = min(int(hi[0] + m) + 1, w), min(int(hi[1] + m) + 1, h)
    return _Crop(x0, y0, max(x1 - x0, 1), max(y1 - y0, 1))


def render_in_crop(
    cam: CameraView, P: FloatArray, vertices: FloatArray, faces: Any, crop: _Crop, supersample: int = 4
) -> BoolMask:
    return np.asarray(coverage_in_crop(cam, P, vertices, faces, crop, supersample) >= 0.5)


def coverage_in_crop(
    cam: CameraView, P: FloatArray, vertices: FloatArray, faces: Any, crop: _Crop, supersample: int = 4
) -> npt.NDArray[np.float32]:
    """Model silhouette coverage (0..1) in the crop: its 0.5 crossing is the sub-pixel model edge."""
    return camera_coverage(
        vertices, faces, crop.K(_arr(cam.K)), cam.R, cam.t_mm, crop.h, crop.w,
        placement=P, dist=cam.dist, supersample=supersample, front_only=True,
    )  # fmt: skip


def _subpx_contours(field_: npt.ArrayLike) -> list[Any]:
    """Sub-pixel contours with the metrology's tracer (0.5 crossing; binary masks are de-staircased first)."""
    from services.metrology.segment import mask_contour_subpx

    f = np.asarray(field_)
    return list(mask_contour_subpx(f.astype(np.float32) if f.dtype != bool else f, min_area_px=2.0))


def _fill_contours(contours: list[Any], h: int, w: int, ss: int = 4) -> BoolMask:
    """Boolean mask of sub-pixel contours (outer rings filled, hole rings cleared), area-correct to 1/ss px."""
    canvas = np.zeros((h * ss, w * ss), np.uint8)
    for want_hole, val in ((False, 255), (True, 0)):
        rings = [c.points_px for c in contours if c.is_hole == want_hole and len(c.points_px) >= 3]
        pts = [np.round(((r + 0.5) * ss - 0.5) * 16).astype(np.int32).reshape(-1, 1, 2) for r in rings]
        if pts:
            cv2.fillPoly(canvas, pts, val, cv2.LINE_8, 4)
    small = cv2.resize(canvas, (w, h), interpolation=cv2.INTER_AREA)
    return np.asarray(small >= 128)


def _contour_points_mm(contours: list[Any], frame: Frame) -> FloatArray:
    pts = [M.resample_closed(frame.to_mm(c.points_px), M.RESAMPLE_MM) for c in contours if len(c.points_px) >= 3]
    return np.vstack(pts) if pts else np.zeros((0, 2))


def _boundary(mask: BoolMask) -> tuple[FloatArray, FloatArray]:
    """(boundary points px, distance-to-boundary field px)."""
    m = np.asarray(mask, dtype=np.uint8)
    edge = m - cv2.erode(m, np.ones((3, 3), np.uint8), borderType=cv2.BORDER_CONSTANT, borderValue=0)
    ys, xs = np.nonzero(edge)
    dt = cv2.distanceTransform(np.where(edge > 0, 0, 255).astype(np.uint8), cv2.DIST_L2, cv2.DIST_MASK_PRECISE)
    return np.c_[xs, ys].astype(np.float64), dt.astype(np.float64)


def _sample(field_: FloatArray, pts: FloatArray) -> FloatArray:
    out: FloatArray = map_coordinates(field_, [pts[:, 1], pts[:, 0]], order=1, mode="nearest")
    return out


# ------------------------------------------------------------------ like-for-like measurement


@dataclass(frozen=True)
class _MatView:
    """The two things the metrology footprint code reads from a `MatDetection`: its ground homography and
    `to_mm` (undistort, then map through a homography)."""

    cam: CameraView
    H: FloatArray

    def to_mm(self, pts_px: FloatArray, H: FloatArray | None = None) -> FloatArray:
        return _apply_h(self.H if H is None else H, _undistort(self.cam, np.asarray(pts_px, dtype=np.float64)))


def metrology_pose(cam: CameraView) -> Any:
    """The camera as a metrology `PoseEstimate` (K, dist, R, t)."""
    from services.metrology.calibrate import PoseEstimate

    dist = np.zeros(5) if cam.dist is None else _arr(cam.dist).ravel()
    return PoseEstimate(_arr(cam.K), dist, _arr(cam.R), _arr(cam.t_mm).reshape(3), "synthetic", 0.0)


def measure_mask_like_metrology(
    mask_full: npt.ArrayLike | None,
    cam: CameraView,
    view: str,
    *,
    origin: DataOrigin = DataOrigin.synthetic,
    crop_mask: npt.ArrayLike | None = None,
    crop_xy: tuple[int, int] = (0, 0),
) -> Measurements | None:
    """Measure a camera-frame mask with the metrology's own footprint code, exactly as `measure_photo` does after
    segmentation: sub-pixel contours -> mat-plane footprint; with a stated height, the thick-part footprint (outer ring
    on the mat plane and the top plane intersected, see-through cylinder fits cut out as discs, side views allowed to
    keep less of their outline), or the round-profile footprint; then `build_measurements`.

    The metrology functions are called directly (with a small adapter standing in for its mat detection), so the two
    sides cannot drift apart. Pass either the full-frame mask or a crop plus its offset. None when nothing is found.
    """
    from services.metrology.calibrate import plane_homography as metrology_plane_homography
    from services.metrology.features import SigmaModel, build_measurements
    from services.metrology.measure import (
        MIN_KEEP_SIDE,
        MIN_KEEP_TOP,
        footprint_from_contours,
        round_footprint,
        thick_footprint,
    )
    from services.metrology.segment import mask_contour_subpx

    mask = crop_mask if crop_mask is not None else mask_full
    if mask is None or not np.any(mask):
        return None
    off = np.array(crop_xy if crop_mask is not None else (0, 0), dtype=np.float64)
    contours = [
        replace(c, points_px=c.points_px + off)
        for c in mask_contour_subpx(
            np.asarray(mask, dtype=np.float32) if np.asarray(mask).dtype != bool else np.asarray(mask),
            min_area_px=2.0,
        )
    ]
    det = _MatView(cam, ground_homography(cam))
    ground = footprint_from_contours(contours, det, det.H) if contours else None
    if ground is None:
        return None
    footprint = ground
    fits: list[Any] = []
    notes = ["model silhouette rendered with the photo's camera and measured with the metrology code"]
    h = cam.top_height_mm
    pose = metrology_pose(cam)
    if h is not None and h > 0 and pose.camera_height_mm > h:
        min_keep = MIN_KEEP_SIDE if view == ViewKind.side.value else MIN_KEEP_TOP
        H_top = metrology_plane_homography(pose, h, det.H)
        corrected = thick_footprint(contours, det, pose, h, H_top, notes, min_keep=min_keep)
        if corrected is not None and cam.profile == "round":
            rounded = round_footprint(contours, det, pose, h, corrected[0])
            if rounded is not None:
                footprint, corrected = rounded, None
                notes.append(f"round profile like the photo (cylinder of diameter {h:.2f} mm lying down)")
        if corrected is not None:
            footprint, fits = corrected
            notes.append(f"height-corrected like the photo ({h:.2f} mm top face, see-through hole fits)")
    meas, _ = build_measurements(
        footprint,
        view=ViewKind(view),
        origin=origin,
        sigma=SigmaModel(),
        scale=cam.scale_correction,
        mask_source="synthetic-gt",
        notes=notes,
        hole_fits=fits,
    )
    return meas


# ------------------------------------------------------------------ the comparison


def compare_camera(
    view: str,
    projection: str,
    vertices: FloatArray,
    faces: Any,
    cam: CameraView,
    model_to_part: npt.ArrayLike,
    *,
    refine: bool = True,
    origin: DataOrigin = DataOrigin.real,
    measure: bool = True,
    exclude: Mesh | None = None,
    exclude_margin_mm: float = 1.0,
) -> CameraCompare:
    """Compare the model with one posed photo in the photo's own pixel frame (see module docstring).

    ``exclude`` is a volume in model coordinates (the broken region as a prism): wherever it projects in the photo,
    grown by ``exclude_margin_mm``, both silhouettes are left out of every metric."""
    v = np.asarray(vertices, dtype=np.float64)
    P0 = (
        _arr(cam.cad_to_mat)
        if cam.cad_to_mat is not None
        else cad_to_mat_from_alignment(v, projection, model_to_part, cam.part_to_mat)
    )
    crop = _crop_for(cam, P0, v)
    window = (slice(crop.y0, crop.y0 + crop.h), slice(crop.x0, crop.x0 + crop.w))
    # The photo's edge is the sub-pixel boundary the metrology measured (0.5 crossing of its soft coverage map), not
    # the cleaned binary mask, which carries a pixel or two of blur halo (~0.3 mm at 3-4 px/mm).
    src = cam.image_field if cam.image_field is not None else cam.image_mask
    photo_cs = _subpx_contours(np.asarray(src)[window])
    photo = _fill_contours(photo_cs, crop.h, crop.w) if photo_cs else np.zeros((crop.h, crop.w), dtype=bool)
    notes: list[str] = []
    P = P0
    ppm = float(cam.px_per_mm_local)

    def excluded(Pk: FloatArray) -> BoolMask | None:
        if exclude is None:
            return None
        cov_x = coverage_in_crop(cam, Pk, np.asarray(exclude[0], dtype=np.float64), exclude[1], crop, supersample=1)
        k = max(1, round(exclude_margin_mm * ppm))
        grown = cv2.dilate((cov_x > 0).astype(np.uint8), cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * k + 1,) * 2))
        return np.asarray(grown > 0)

    if refine:
        excl0 = excluded(P0)
        p_pts, p_dt = _boundary(photo)
        if excl0 is not None and len(p_pts):
            p_pts = p_pts[~excl0[p_pts[:, 1].astype(int), p_pts[:, 0].astype(int)]]
        if len(p_pts) > 2000:
            p_pts = p_pts[np.linspace(0, len(p_pts) - 1, 2000).astype(int)]
        centre = (v @ P0[:3, :3].T + P0[:3, 3])[:, :2].mean(axis=0)

        def cost(x: FloatArray) -> float:
            Pk = _mat_rigid(float(x[0]), float(x[1]), float(x[2]), centre) @ P0
            m = render_in_crop(cam, Pk, v, faces, crop, supersample=2)
            m_pts, m_dt = _boundary(m)
            if excl0 is not None and len(m_pts):
                m_pts = m_pts[~excl0[m_pts[:, 1].astype(int), m_pts[:, 0].astype(int)]]
            if len(m_pts) == 0 or len(p_pts) == 0:
                return 1e6
            return float((_sample(p_dt, m_pts).mean() + _sample(m_dt, p_pts).mean()) / 2)

        x0 = np.zeros(3)
        simplex = np.array([x0, [0.5, 0, 0], [0, 0.3, 0], [0, 0, 0.3]], dtype=np.float64)
        r = minimize(
            cost, x0, method="Nelder-Mead",
            options={"initial_simplex": simplex, "xatol": 1e-3, "fatol": 1e-3, "maxiter": REFINE_MAXITER},
        )  # fmt: skip
        if float(r.fun) <= cost(x0):
            P = _mat_rigid(float(r.x[0]), float(r.x[1]), float(r.x[2]), centre) @ P0
            notes.append(
                f"{view}: refined in the photo frame by {r.x[0]:+.2f} deg, ({r.x[1]:+.2f}, {r.x[2]:+.2f}) mm on the mat"
            )
    cov = coverage_in_crop(cam, P, v, faces, crop, supersample=4)
    model = np.asarray(cov >= 0.5)

    frame = Frame(ppm, 0.0, 0.0, crop.w, crop.h)  # a pixel-scale frame: distances in mm, positions in crop pixels
    excl = excluded(P)
    keep = ~excl if excl is not None else np.ones_like(model)
    # Distances between the two sub-pixel edges (not pixel staircases: one pixel is ~0.3 mm here).
    m_all, p_all = _contour_points_mm(_subpx_contours(cov), frame), _contour_points_mm(photo_cs, frame)
    m_pts, p_pts = M.points_outside(m_all, frame, excl), M.points_outside(p_all, frame, excl)
    d = M.contour_distances_mm(m_pts, p_pts, m_all, p_all)
    over, under = M.over_under_mm2(photo & keep, model & keep, frame)
    worst_part: tuple[float, float] | None = None
    if d.worst_point_mm is not None:
        px = frame.to_px(np.array(d.worst_point_mm)) + np.array([crop.x0, crop.y0])
        mat = _apply_h(ground_homography(cam), _undistort(cam, px.reshape(1, 2)))
        part = _apply_h(np.linalg.inv(_arr(cam.part_to_mat)), mat)[0]
        worst_part = (float(part[0]), float(part[1]))
    vm = ViewMetrics(
        view=view, iou=M.iou(model & keep, photo & keep), hausdorff_mm=d.hausdorff_mm, hd95_mm=d.hd95_mm,
        mean_mm=d.mean_mm,
        worst_point_mm=worst_part, over_area_mm2=over, under_area_mm2=under,
    )  # fmt: skip
    title = f"{view} view (photo frame): IoU {vm.iou:.3f}, Hausdorff {vm.hausdorff_mm:.2f} mm"
    png = M.residual_heatmap(photo, model, frame, distances=d, title=title, label_point_mm=worst_part, excluded=excl)
    short = None
    outers = [c.points_px for c in photo_cs if not c.is_hole and len(c.points_px) >= 3]
    if outers:
        (_, _), (rw, rh), _ = cv2.minAreaRect(np.vstack(outers).astype(np.float32))
        short = float(min(rw, rh)) / ppm
    model_meas = None
    if measure:
        try:
            model_meas = measure_mask_like_metrology(
                None, cam, view, origin=origin, crop_mask=cov, crop_xy=(crop.x0, crop.y0)
            )
        except Exception as e:  # metrology code is evolving; the comparison itself does not depend on it
            notes.append(f"{view}: like-for-like measurement of the model failed ({type(e).__name__}: {e})")
    return CameraCompare(
        metrics=vm,
        distances=d,
        overlay_png=png,
        placement=P,
        model_to_part=model_to_part_from_placement(P, projection, cam.part_to_mat)
        if cam.cad_to_mat is None
        else np.asarray(model_to_part, dtype=np.float64),
        model_mask=model,
        photo_mask=photo,
        crop_xy=(crop.x0, crop.y0),
        part_to_mat=_arr(cam.part_to_mat),
        model_measurements=model_meas,
        notes=notes,
        excluded_mask=excl,
        excluded_mm2=float(excl.sum()) / ppm**2 if excl is not None else 0.0,
        photo_short_side_mm=short,
        px_per_mm=ppm,
    )


def local_px_per_mm(cam: CameraView, mat_xy: tuple[float, float], height_mm: float = 0.0) -> float:
    """Image pixels per mm (geometric mean of both axes) at a mat point on the plane `height_mm` above the mat."""
    R = _arr(cam.R)
    t = _arr(cam.t_mm).reshape(3)
    K = _arr(cam.K)

    def proj(p: FloatArray) -> FloatArray:
        h = K @ (R @ p + t)
        out: FloatArray = h[:2] / h[2]
        return out

    p0 = np.array([mat_xy[0], mat_xy[1], -height_mm])
    ex, ey = np.array([0.5, 0.0, 0.0]), np.array([0.0, 0.5, 0.0])
    dx = np.linalg.norm(proj(p0 + ex) - proj(p0 - ex))
    dy = np.linalg.norm(proj(p0 + ey) - proj(p0 - ey))
    return float(np.sqrt(dx * dy))


@dataclass
class OrbitCompare:
    frames: dict[str, CameraCompare]  # per compared frame, in clip order
    placement: FloatArray  # one rigid placement shared by every frame of the clip
    skipped: int = 0  # frames not compared (evenly thinned to `max_frames`)
    notes: list[str] = field(default_factory=list)


def compare_orbit(
    frames: Mapping[str, CameraView],
    vertices: FloatArray,
    faces: Any,
    model_to_part: npt.ArrayLike,
    *,
    refine: bool = True,
    max_frames: int = 8,
    exclude: Mesh | None = None,
) -> OrbitCompare:
    """Compare the model with the calibrated frames of a walk-around clip.

    The part does not move during the clip, so one placement serves every frame: it starts from the top-view
    registration (model -> part frame) mapped through the clip's own part frame, tries the 180 deg turn the part-frame
    convention leaves open, refines rigidly on the first frame (rotation about the vertical and a shift on the mat;
    never scale, never height), and is then reused unchanged for every other frame. Wrong heights therefore show up as
    silhouette errors in the oblique frames."""
    names = sorted(frames, key=lambda n: (len(n), n))
    keep = names
    if len(names) > max_frames:
        idx = np.linspace(0, len(names) - 1, max_frames).round().astype(int)
        keep = [names[i] for i in sorted(set(idx.tolist()))]
    first = frames[keep[0]]
    M0 = np.asarray(model_to_part, dtype=np.float64)
    turn = np.diag([-1.0, -1.0, 1.0])
    best: CameraCompare | None = None
    for cand in (M0, turn @ M0):
        cc = compare_camera(keep[0], "top", vertices, faces, first, cand, refine=refine, measure=False, exclude=exclude)
        if best is None or cc.metrics.mean_mm < best.metrics.mean_mm:
            best = cc
    assert best is not None
    out = {keep[0]: best}
    for name in keep[1:]:
        cam = replace(frames[name], cad_to_mat=best.placement)
        out[name] = compare_camera(name, "top", vertices, faces, cam, M0, refine=False, measure=False, exclude=exclude)
    notes = [n.replace(keep[0] + ":", "orbit:") for n in best.notes]
    return OrbitCompare(out, best.placement, len(names) - len(keep), notes)
