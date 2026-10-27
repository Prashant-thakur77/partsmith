"""SYNTHETIC measurements made from a model's own silhouette (exact ground truth, labelled synthetic everywhere).

Used by the Phase 2 self-check and tests: render the model at a known pose, then measure the rendered mask the way the
metrology stage measures a photo mask (outer contour -> outline and min-area rectangle, inner contours -> holes).
A hole's contour runs through the centres of the solid pixels around it, about half a pixel outside the true edge, so
hole diameters get a -0.5 px correction (applied here only). Lengths come from the min-area rectangle of the contour,
whose extreme points are the outermost pixel centres, so they get none.
"""

from __future__ import annotations

import cv2
import numpy as np
from partsmith_schemas.common import DataOrigin, Measured, Source
from partsmith_schemas.measurement import Hole, Measurements, ViewKind

from services.geom_worker.sandbox import ExecResult
from services.verifier.align import Rigid2D
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
