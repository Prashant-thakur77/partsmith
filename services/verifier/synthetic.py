"""SYNTHETIC measurements made from a model's own silhouette (exact ground truth, labelled synthetic everywhere).

Used by the Phase 2 self-check and tests: render the model at a known pose, then measure the rendered mask the way the
metrology stage measures a photo mask (outer contour -> outline and min-area rectangle, inner contours -> holes).
A hole's contour runs through the centres of the solid pixels around it, about half a pixel outside the true edge, so
hole diameters get a -0.5 px correction (applied here only). Lengths come from the min-area rectangle of the contour,
whose extreme points are the outermost pixel centres, so they get none.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

import cv2
import numpy as np
import numpy.typing as npt
from partsmith_schemas.common import DataOrigin, Measured, Source
from partsmith_schemas.measurement import Hole, Measurements, ViewKind

from services.geom_worker.sandbox import ExecResult
from services.verifier.align import Rigid2D
from services.verifier.camera import (
    CameraView,
    _crop_for,
    cad_to_mat_from_alignment,
    coverage_in_crop,
    local_px_per_mm,
    measure_mask_like_metrology,
)
from services.verifier.render import Frame, project, silhouette
from services.verifier.verify import PhotoMask

SYNTH_NOTE = "SYNTHETIC: measured from the model's own rendered silhouette (self-check), not from a photo"
HOLE_MIN_CIRCULARITY = 0.85


def synthetic_top_measurement(
    exec_result: ExecResult,
    *,
    pose: Rigid2D = Rigid2D(17.0, 1.3, -0.7, False),
    px_per_mm: float = 20.0,
    with_thickness: bool = True,
) -> tuple[Measurements, PhotoMask]:
    """Top-view Measurements + mask of the model placed at `pose` (mm). Origin is DataOrigin.synthetic."""
    if exec_result.mesh is None:
        raise ValueError("exec_result has no mesh")
    v, f = exec_result.mesh.vertices, exec_result.mesh.faces
    uv = pose.apply(project(v, "top"))
    frame = Frame.around(uv, px_per_mm, margin_mm=4.0)
    mask = silhouette(v, f, "top", frame, transform=pose.matrix())
    m8 = np.ascontiguousarray(mask.astype(np.uint8))
    contours, hier = cv2.findContours(m8, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_NONE)
    if not contours:
        raise ValueError("empty silhouette")
    outer_i = max((i for i in range(len(contours)) if hier[0][i][3] < 0), key=lambda i: cv2.contourArea(contours[i]))
    outer_mm = frame.to_mm(contours[outer_i].reshape(-1, 2).astype(np.float64))
    px = 1.0 / px_per_mm
    (_, _), (rw, rh), _ = cv2.minAreaRect(outer_mm.astype(np.float32))
    length, width = max(rw, rh), min(rw, rh)
    simplified = cv2.approxPolyDP(outer_mm.astype(np.float32).reshape(-1, 1, 2), 0.02, True).reshape(-1, 2)

    holes: list[Hole] = []
    for i, c in enumerate(contours):
        if hier[0][i][3] != outer_i:
            continue
        pts = frame.to_mm(c.reshape(-1, 2).astype(np.float64))
        area = abs(cv2.contourArea(pts.astype(np.float32)))
        perim = cv2.arcLength(pts.astype(np.float32), True)
        if area <= 0 or perim <= 0 or 4 * np.pi * area / perim**2 < HOLE_MIN_CIRCULARITY:
            continue
        d = 2 * np.sqrt(area / np.pi) - 0.5 * px
        cx, cy = pts.mean(axis=0)
        holes.append(Hole(id=f"hole_{len(holes) + 1}", center_mm=(float(cx), float(cy)),
                          diameter=Measured(value=float(d), source=Source.measured, sigma_mm=px)))  # fmt: skip

    thickness = None
    notes = [SYNTH_NOTE]
    feats = exec_result.features or {}
    if with_thickness and feats.get("plate_thickness_mm") is not None:
        thickness = Measured(value=float(feats["plate_thickness_mm"]), source=Source.user_stated, sigma_mm=0.0)
        notes.append("SYNTHETIC: thickness copied from the model's plate thickness (as if stated by the user)")
    meas = Measurements(
        view=ViewKind.top,
        origin=DataOrigin.synthetic,
        outline_mm=[(float(x), float(y)) for x, y in simplified],
        holes=holes,
        length=Measured(value=float(length), source=Source.measured, sigma_mm=px),
        width=Measured(value=float(width), source=Source.measured, sigma_mm=px),
        thickness=thickness,
        area_mm2=float(mask.sum()) * px * px,
        mask_source="synthetic-gt",
        notes=notes,
    )
    return meas, PhotoMask(mask, frame)


def mat_placement(cx_mm: float, cy_mm: float, theta_deg: float) -> npt.NDArray[np.float64]:
    """3x3 part -> mat affine with the metrology's convention (part Y up, mat y down): c + Rot(theta).diag(1, -1).p"""
    th = np.radians(theta_deg)
    c, s = np.cos(th), np.sin(th)
    return np.array([[c, s, cx_mm], [s, -c, cy_mm], [0.0, 0.0, 1.0]])


def synthetic_camera_view(
    exec_result: ExecResult,
    *,
    K: npt.ArrayLike,
    R: npt.ArrayLike,
    t_mm: npt.ArrayLike,
    image_size: tuple[int, int],
    part_to_mat: npt.ArrayLike,
    view: str = "top",
    projection: str = "top",
    top_height_mm: float | None = None,
    cam_kwargs: dict[str, Any] | None = None,
) -> tuple[Measurements, CameraView]:
    """SYNTHETIC posed photo of the model: render its silhouette through (K, R, t) with the part lying on the mat at
    `part_to_mat`, then measure that mask with the metrology code. Returns the Measurements (origin synthetic) and a
    CameraView whose part frame is the measurement's own, exactly like the real pipeline would hand them over."""
    if exec_result.mesh is None:
        raise ValueError("exec_result has no mesh")
    v, f = exec_result.mesh.vertices, exec_result.mesh.faces
    P = cad_to_mat_from_alignment(v, projection, np.eye(3), part_to_mat)
    w, h = image_size
    empty = np.zeros((h, w), dtype=bool)
    probe = CameraView(K, R, t_mm, empty, part_to_mat, 1.0, image_size=image_size)
    crop = _crop_for(probe, P, v)
    cov = coverage_in_crop(probe, P, v, f, crop)
    field_ = np.zeros((h, w), dtype=np.float32)
    field_[crop.y0 : crop.y0 + crop.h, crop.x0 : crop.x0 + crop.w] = cov
    mask = field_ >= 0.5
    centre = (v @ P[:3, :3].T + P[:3, 3])[:, :2].mean(axis=0)
    ppm = local_px_per_mm(probe, (float(centre[0]), float(centre[1])))
    cam = replace(
        probe, image_mask=mask, image_field=field_, px_per_mm_local=ppm, top_height_mm=top_height_mm,
        **(cam_kwargs or {}),
    )  # fmt: skip
    meas = measure_mask_like_metrology(field_, cam, view, origin=DataOrigin.synthetic)
    if meas is None:
        raise ValueError("the part is not visible in the synthetic photo")
    meas.mask_source = "synthetic-gt"
    meas.notes.insert(0, "SYNTHETIC: posed photo rendered from the model (exact ground truth)")
    if view == "side":
        meas.thickness = Measured(value=meas.width.value, source=Source.measured, sigma_mm=meas.width.sigma_mm)
    elif top_height_mm is not None:
        meas.thickness = Measured(value=top_height_mm, source=Source.user_stated, sigma_mm=0.3)
    return meas, replace(cam, part_to_mat=np.asarray(meas.part_to_mat, dtype=np.float64))
