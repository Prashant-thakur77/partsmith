"""verify(): the sole authority for ``verified`` (PLAN §6.5).

For every measured view: register the model silhouette onto the measured one (rigid 2-D search, never scaling),
compute IoU, boundary distances and over/under areas, and draw the residual overlay. When the view comes with a camera
pose (``camera_views``), the comparison moves into the photo's own pixel frame (`camera.py`): the model is placed on the
mat, refined rigidly in the image and rendered through (K, R, t), which reproduces parallax and see-through holes; the
rendered model is then measured with the metrology's own code so length, width and hole diameters are compared like
for like. Without a pose the rectified orthographic comparison is used. Then compare the model's features with the
measured values, run the part tests, and apply the pass rule:

    verified = all P0 tests pass
               AND Hausdorff <= 0.5 mm on every measured view
               AND, on every view whose silhouette's short side is >= 20 mm, IoU >= 0.97
               AND, on every smaller view, mean contour distance <= 0.15 mm
               AND no blocking judge veto

Functional probes (`functional.py`: which screws pass each hole, declared interface fits, printability) are added
as P1 tests and summarised in ``VerifyOutput.functional``; they never take part in the pass rule.

IoU depends on scale: for an L x L square with a uniform edge error e, IoU ~ 1 - 4e/L, so a 0.1 mm error already
costs 3 % IoU at 13 mm and 12 % on a 1.5 mm side profile. Views under 20 mm are therefore gated on the two
scale-free distances (Hausdorff and mean contour distance) plus their part tests; their IoU is still reported.
"""

from __future__ import annotations

import hashlib
import itertools
import json
import sys
import time
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

import cv2
import numpy as np
from partsmith_schemas.common import BBOX_TOL_MM, FEATURE_TOL_MM, HAUSDORFF_PASS_MM, IOU_PASS, DataOrigin
from partsmith_schemas.measurement import Measurements
from partsmith_schemas.partspec import PartSpec
from partsmith_schemas.verification import (
    FeatureResidual,
    JudgeVeto,
    PartTest,
    Thresholds,
    Validity,
    Verification,
    ViewMetrics,
)
from scipy.optimize import linear_sum_assignment
from shapely import affinity
from shapely.geometry import MultiPolygon, Point, Polygon, box

from services.geom_worker.bake import part_facts
from services.geom_worker.sandbox import ExecResult
from services.verifier import VERIFIER_VERSION
from services.verifier import metrics as M
from services.verifier.align import Rigid2D, align
from services.verifier.camera import CameraCompare, CameraView, Mesh, compare_camera, compare_orbit
from services.verifier.functional import FunctionalProbe, as_part_tests, run_probes
from services.verifier.part_tests import (
    CENTER_TOL_MM,
    DEPTH_TOL_MM,
    THICKNESS_TOL_MM,
    Value,
    evaluate_tests,
    expected_holes,
    expected_thickness,
    generate_tests,
)
from services.verifier.render import (
    BoolMask,
    FloatArray,
    Frame,
    apply_2d,
    circle_polygon,
    project,
    rasterize_polygon,
    silhouette,
)
from services.verifier.solid_features import SolidFeatures

DEFAULT_PX_PER_MM = 20.0
IOU_GATE_MIN_WIDTH_MM = 20.0
MEAN_GATE_MM = 0.15
HOLE_MATCH_MAX_MM = 3.0
COMPARED_VIEWS = ("top", "side")


@dataclass(frozen=True)
class PhotoMask:
    """A measured silhouette: boolean mask on a mm frame that matches the view's ``Measurements`` coordinates."""

    mask: BoolMask
    frame: Frame


@dataclass
class ViewResult:
    view: str
    projection: str  # "top" | "side_xz" | "side_yz"
    transform: Rigid2D  # rectified registration, model plane -> part frame
    metrics: ViewMetrics  # the metrics that were gated (photo frame when a pose was given)
    model_mask: BoolMask
    photo: PhotoMask
    matrix: FloatArray | None = None  # final model plane -> part frame (3x3, refined in the photo when posed)
    frame: Literal["rectified", "camera"] = "rectified"
    iou_gated: bool = True
    gate_note: str = ""
    camera: CameraCompare | None = None
    rectified_metrics: ViewMetrics | None = None
    excluded_mask: BoolMask | None = None  # pixels left out of the comparison (broken region)
    excluded_mm2: float = 0.0
    short_side_mm: float | None = None


@dataclass
class VerifyOutput:
    verification: Verification
    overlays: dict[str, bytes] = field(default_factory=dict)
    views: dict[str, ViewResult] = field(default_factory=dict)
    # Values the tests used ("bbox.x", "hole:hole_1.diameter", ...) plus the true CAD dimensions under "cad.*".
    model_values: dict[str, Value] = field(default_factory=dict)
    view_gates: dict[str, list[str]] = field(default_factory=dict)  # view -> gates applied ("hausdorff", "iou")
    # Functional probes (screws, interfaces, printability): {"passed", "total", "probes": [FunctionalProbe dicts]}.
    functional: dict[str, Any] = field(default_factory=dict)
    # Broken parts: {"region_mm2", "excluded_mm2": {view: mm2}, "informational_tests": [...], "statement"} or {}.
    broken: dict[str, Any] = field(default_factory=dict)


# ----------------------------------------------------------------------------------------------- helpers


def photo_mask_from_measurements(m: Measurements, px_per_mm: float = DEFAULT_PX_PER_MM) -> PhotoMask:
    """Rasterise the measured outline (holes and slots cleared) when no photo mask is supplied."""
    outline = np.asarray(m.outline_mm, dtype=np.float64)
    frame = Frame.around(outline, px_per_mm, margin_mm=4.0)
    holes = [circle_polygon((h.center_mm[0], h.center_mm[1]), h.diameter.value) for h in m.holes]
    for s in m.slots:
        holes.append(_slot_polygon(s.center_mm, s.length.value, s.width.value, s.angle_deg))
    return PhotoMask(rasterize_polygon(outline, holes, frame), frame)


def _slot_polygon(center: tuple[float, float], length: float, width: float, angle_deg: float) -> FloatArray:
    r = width / 2
    half = max(length / 2 - r, 0.0)
    a = np.linspace(-np.pi / 2, np.pi / 2, 48)
    right = np.column_stack([half + r * np.cos(a), r * np.sin(a)])
    left = np.column_stack([-half - r * np.cos(a), -r * np.sin(a)])
    pts = np.vstack([right, left])
    th = np.radians(angle_deg)
    rot = np.array([[np.cos(th), -np.sin(th)], [np.sin(th), np.cos(th)]])
    out: FloatArray = pts @ rot.T + np.asarray(center)
    return out


def footprint_lw(vertices: FloatArray, projection: str = "top") -> tuple[float, float]:
    """Long and short side of the minimum-area rectangle around a view's silhouette (exact: hull of vertices)."""
    uv = project(vertices, projection).astype(np.float32)
    (_, _), (w, h), _ = cv2.minAreaRect(uv)
    return float(max(w, h)), float(min(w, h))


def _origin(measurements: Mapping[str, Measurements]) -> DataOrigin:
    origins = {m.origin for m in measurements.values()}
    for o in (DataOrigin.synthetic, DataOrigin.replay, DataOrigin.reference_object):
        if o in origins:
            return o
    return DataOrigin.real


def _sha_json(obj: Any) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode()).hexdigest()


def _versions(exec_result: ExecResult) -> dict[str, str]:
    import scipy
    import trimesh

    v = {
        "verifier": VERIFIER_VERSION,
        "opencv": cv2.__version__,
        "numpy": np.__version__,
        "scipy": scipy.__version__,
        "trimesh": trimesh.__version__,
        "python": sys.version.split()[0],
    }
    v.update({k: str(x) for k, x in exec_result.versions.items() if k != "python"})
    return v


def _poly_px_mask(poly: Polygon | None, frame: Frame) -> BoolMask | None:
    if poly is None or poly.is_empty:
        return None
    parts = list(poly.geoms) if isinstance(poly, MultiPolygon) else [poly]
    out = np.zeros(frame.shape, dtype=bool)
    for g in parts:
        if isinstance(g, Polygon) and not g.is_empty:
            holes = [np.asarray(r.coords) for r in g.interiors]
            out |= rasterize_polygon(np.asarray(g.exterior.coords), holes, frame)
    return out


def _transform_poly(poly: Polygon, T: FloatArray) -> Polygon:
    a, b, c, d, xoff, yoff = T[0, 0], T[0, 1], T[1, 0], T[1, 1], T[0, 2], T[1, 2]
    out: Polygon = affinity.affine_transform(poly, [a, b, c, d, xoff, yoff])
    return out


def _compare_view(
    view: str,
    projection: str,
    vertices: FloatArray,
    faces: Any,
    photo: PhotoMask,
    *,
    exclude_frame: Polygon | None = None,
    exclude_model: Polygon | None = None,
) -> tuple[ViewResult, M.ContourDistances]:
    """Rectified comparison. `exclude_frame` (in the measurement frame) or `exclude_model` (in the model's projected
    coordinates) is the broken region: it is left out of the registration and of every metric."""
    ppm = photo.frame.px_per_mm
    uv = project(vertices, projection)
    model_frame = Frame.around(uv, ppm, margin_mm=3.0)
    model_mask = silhouette(vertices, faces, projection, model_frame)
    T = align(model_mask, model_frame, photo.mask, photo.frame).transform
    ex_model = exclude_model
    if ex_model is None and exclude_frame is not None:
        ex_model = _transform_poly(exclude_frame, np.linalg.inv(T.matrix()))
    if ex_model is not None and not ex_model.is_empty:
        mx = _poly_px_mask(ex_model, model_frame)
        px = _poly_px_mask(_transform_poly(ex_model, T.matrix()), photo.frame)
        T = align(
            model_mask & ~mx if mx is not None else model_mask,
            model_frame,
            photo.mask & ~px if px is not None else photo.mask,
            photo.frame,
        ).transform
    # Render the registered model on a frame that holds both silhouettes, so nothing is cropped.
    placed = Frame.around(T.apply(uv), ppm, margin_mm=3.0)
    frame = _snap_union(photo.frame, placed)
    photo_mask = _paste(photo, frame)
    mm = silhouette(vertices, faces, projection, frame, transform=T.matrix())
    excl = (
        _poly_px_mask(_transform_poly(ex_model, T.matrix()).buffer(BROKEN_MARGIN_MM), frame)
        if ex_model is not None and not ex_model.is_empty
        else None
    )
    keep = ~excl if excl is not None else np.ones_like(mm)
    m_all, p_all = M.contour_points_mm(mm, frame), M.contour_points_mm(photo_mask, frame)
    d = M.contour_distances_mm(M.points_outside(m_all, frame, excl), M.points_outside(p_all, frame, excl), m_all, p_all)
    over, under = M.over_under_mm2(photo_mask & keep, mm & keep, frame)
    vm = ViewMetrics(
        view=view,
        iou=M.iou(mm & keep, photo_mask & keep),
        hausdorff_mm=d.hausdorff_mm,
        hd95_mm=d.hd95_mm,
        mean_mm=d.mean_mm,
        worst_point_mm=d.worst_point_mm,
        over_area_mm2=over,
        under_area_mm2=under,
    )
    vr = ViewResult(view, projection, T, vm, mm, PhotoMask(photo_mask, frame))
    vr.excluded_mask = excl
    vr.excluded_mm2 = float(excl.sum()) / ppm**2 if excl is not None else 0.0
    return vr, d


BROKEN_MARGIN_MM = 1.0


def broken_region(partspec: PartSpec | None, top: Measurements | None) -> tuple[Polygon | None, dict[str, Any]]:
    """The broken piece in the top view's part frame, from ``PartSpec.broken_region``.

    ``polygon_mm`` may be the completed outline (as the mirror completion writes it) or just the patch: when it covers
    most of the measured outline, the broken piece is what it adds outside the photo's outline; otherwise it is the
    polygon itself. Returns (region or None, report fields)."""
    if partspec is None or partspec.broken_region is None or partspec.broken_region.kind != "outline":
        return None, {}
    br = partspec.broken_region
    info: dict[str, Any] = {"strategy": br.strategy, "note": br.note or "", "region_mm2": 0.0}
    if len(br.polygon_mm) < 3:
        info["statement"] = (
            "The part is broken but the broken region was not located, so the whole silhouette was compared; "
            "the completed shape is inferred."
        )
        return None, info
    poly = Polygon(br.polygon_mm).buffer(0)
    outline = Polygon(top.outline_mm).buffer(0) if top is not None and len(top.outline_mm) >= 3 else None
    region = poly
    if outline is not None and not outline.is_empty and poly.area >= 0.8 * outline.area:
        region = poly.difference(outline).buffer(-0.2).buffer(0.2)  # drop slivers along the shared edge
    if region.is_empty or region.area < 0.5:
        info["statement"] = (
            "The completed outline adds nothing outside the photo's outline, so the whole silhouette was compared; "
            "the completed shape is inferred."
        )
        return None, info
    info["region_mm2"] = round(float(region.area), 2)
    info["statement"] = (
        f"Completed region ({region.area:.0f} mm², restored by {br.strategy}): inferred, not verified against the "
        f"photo — it and a {BROKEN_MARGIN_MM:g} mm margin are left out of every silhouette comparison."
    )
    return region, info


def broken_height(
    partspec: PartSpec | None, measurements: Mapping[str, Measurements]
) -> tuple[float | None, dict[str, Any]]:
    """Break height (mm above the bed) of a part whose top is missing (``BrokenRegion.kind == "height"``).

    The model only says the top is missing; code takes the height from the side photo (the short side of its
    silhouette, the same quantity as the ``side.thickness`` test). Returns (height or None, report fields)."""
    if partspec is None or partspec.broken_region is None or partspec.broken_region.kind != "height":
        return None, {}
    br = partspec.broken_region
    info: dict[str, Any] = {"strategy": br.strategy, "note": br.note or "", "kind": "height", "region_mm2": 0.0}
    side = measurements.get("side")
    if side is None:
        info["statement"] = (
            "The top of the part is broken off but no side photo shows where, so the whole silhouette was compared; "
            "the missing height is inferred."
        )
        return None, info
    h = float(side.width.value)
    info["break_height_mm"] = round(h, 2)
    info["statement"] = (
        f"The top of the part is broken off: the side photo shows it {h:.1f} mm tall. Everything above "
        f"{max(h - BROKEN_MARGIN_MM, 0.0):.1f} mm is inferred (restored by {br.strategy}), not verified against the "
        "photos; it is left out of the side and walk-around comparisons. The top view is compared in full."
    )
    return h, info


def _slab(vertices: FloatArray, height_mm: float) -> Mesh | None:
    """The missing top of a part as a box volume (model coordinates): everything ``height_mm`` above the model's base."""
    lo, hi = np.min(vertices, axis=0), np.max(vertices, axis=0)
    z0, z1 = float(lo[2]) + height_mm, float(hi[2]) + 1.0
    if z0 >= z1:
        return None
    return _prism(box(float(lo[0]) - 1.0, float(lo[1]) - 1.0, float(hi[0]) + 1.0, float(hi[1]) + 1.0), vertices, z0)


def _prism(poly_model: Polygon, vertices: FloatArray, z_from: float | None = None) -> Mesh | None:
    """The broken region as a vertical prism over the model's full height (model coordinates), for camera views."""
    import shapely

    if poly_model.is_empty:
        return None
    z0, z1 = float(np.min(vertices[:, 2])) - 1.0 if z_from is None else z_from, float(np.max(vertices[:, 2])) + 1.0
    tris = [t for t in shapely.constrained_delaunay_triangles(poly_model).geoms if isinstance(t, Polygon)]
    v: list[tuple[float, float, float]] = []
    f: list[tuple[int, int, int]] = []
    for t in tris:
        c = list(t.exterior.coords)[:3]
        for z in (z0, z1):
            base = len(v)
            v += [(x, y, z) for x, y in c]
            f.append((base, base + 1, base + 2))
    rings = [g.exterior for g in (poly_model.geoms if isinstance(poly_model, MultiPolygon) else [poly_model])]
    for ring in rings:
        pts = list(ring.coords)
        for (xa, ya), (xb, yb) in itertools.pairwise(pts):
            base = len(v)
            v += [(xa, ya, z0), (xb, yb, z0), (xb, yb, z1), (xa, ya, z1)]
            f += [(base, base + 1, base + 2), (base, base + 2, base + 3)]
    if not f:
        return None
    return np.asarray(v, dtype=np.float64), np.asarray(f, dtype=np.int64)


def _band(
    region_model: Polygon | MultiPolygon | None, projection: str, *, above_mm: float | None = None
) -> Polygon | MultiPolygon | None:
    """The broken region seen in a rectified side view (model coordinates): one vertical band over each piece's
    extent along the view's u axis (one band per piece, so two small pieces at the two ends do not blank out the
    whole length between them), or (``above_mm``: the missing top) a horizontal band above that height."""
    a = {"side_xz": 0, "side_yz": 1}.get(projection)
    if a is None:
        return None
    if above_mm is not None:
        out: Polygon = box(-1e3, above_mm, 1e3, 1e3)
        return out
    if region_model is None or region_model.is_empty:
        return None
    pieces = list(region_model.geoms) if isinstance(region_model, MultiPolygon) else [region_model]
    bands = [box(g.bounds[a], -1e3, g.bounds[a + 2], 1e3) for g in pieces if not g.is_empty]
    if not bands:
        return None
    merged = bands[0]
    for b in bands[1:]:
        merged = merged.union(b)
    return merged if isinstance(merged, Polygon | MultiPolygon) else None


def cam_ppm(cc: CameraCompare) -> float:
    return cc.px_per_mm


def _orbit_metrics(frames: Sequence[ViewResult]) -> ViewMetrics:
    """One "orbit" view: the worst frame's Hausdorff and HD95, the median mean distance, the lowest IoU."""
    worst = max(frames, key=lambda f: f.metrics.hausdorff_mm)
    return ViewMetrics(
        view="orbit",
        iou=min(f.metrics.iou for f in frames),
        hausdorff_mm=worst.metrics.hausdorff_mm,
        hd95_mm=max(f.metrics.hd95_mm for f in frames),
        mean_mm=float(np.median([f.metrics.mean_mm for f in frames])),
        worst_point_mm=worst.metrics.worst_point_mm,
        over_area_mm2=worst.metrics.over_area_mm2,
        under_area_mm2=worst.metrics.under_area_mm2,
    )


def _orbit_reason(frames: Sequence[ViewResult], agg: ViewMetrics, skipped: int, th: Thresholds) -> str:
    def ok(f: ViewResult) -> bool:
        m = f.metrics
        return bool(
            m.hausdorff_mm <= th.hausdorff_mm and (m.iou >= th.iou if f.iou_gated else m.mean_mm <= MEAN_GATE_MM)
        )

    worst = max(frames, key=lambda f: f.metrics.hausdorff_mm)
    med = float(np.median([f.metrics.hausdorff_mm for f in frames]))
    per = "; ".join(
        f"{f.view} {f.metrics.hausdorff_mm:.2f}/{f.metrics.mean_mm:.2f} mm{'' if ok(f) else ' (fails)'}" for f in frames
    )
    bad = sum(not ok(f) for f in frames)
    head = (
        f"orbit ({len(frames)} frames compared in their photo frames"
        + (f", {skipped} more not compared" if skipped else "")
        + f"): worst Hausdorff {agg.hausdorff_mm:.2f} mm ({worst.view}), median {med:.2f} mm"
        + (f" - {bad} frame(s) fail" if bad else " - every frame within tolerance")
    )
    return f"{head}. Per frame Hausdorff/mean: {per}."


def _broken_tests(
    tests: list[PartTest], region: Polygon | None, measurements: Mapping[str, Measurements]
) -> tuple[list[PartTest], list[str]]:
    """Dimension tests whose span crosses the broken region become informational (P1): the photo shows the broken
    part, the model is the intact replacement. ``region`` None: the top is missing (a height break), which only the
    side-view thickness spans."""
    grown = region.buffer(BROKEN_MARGIN_MM) if region is not None else None
    top = measurements.get("top")
    outline = Polygon(top.outline_mm).buffer(0) if top is not None and len(top.outline_mm) >= 3 else None
    # The length (width) spans the break when the broken region reaches an end (a side) of the footprint's
    # minimum-area rectangle: the photo's length is then measured on the broken end. A notch in a long edge leaves the
    # length as measured, and one in an end leaves the width.
    spans = {"bbox.x": region is not None, "bbox.y": region is not None}
    if region is not None and outline is not None and not outline.is_empty:
        spans["bbox.x"], spans["bbox.y"] = _reaches_ends(outline, region)
    hole_at = {h.id: h.center_mm for h in top.holes} if top is not None else {}
    out: list[PartTest] = []
    informational: list[str] = []
    for t in tests:
        cross = False
        if t.priority == "P0":
            if t.id in ("bbox.x", "bbox.y") and spans[t.id]:
                cross = True
            elif t.id == "side.thickness":
                cross = True  # the broken prism (or the missing top) runs through the side profile
            elif grown is not None and t.id.endswith(".diameter") and t.id.split(".")[0] in hole_at:
                c = hole_at[t.id.split(".")[0]]
                cross = grown.contains(Point(c[0], c[1]))
        if cross:
            informational.append(t.id)
            t = t.model_copy(
                update={
                    "priority": "P1",
                    "description": t.description + " — spans the broken region: informational (inferred, the photo "
                    "shows the broken part)",
                }
            )
        out.append(t)
    return out, informational


def _reaches_ends(outline: Polygon, region: Any) -> tuple[bool, bool]:
    """(along the long side, along the short side): does ``region`` come within ``BROKEN_MARGIN_MM`` of either end
    of the outline's minimum-area rectangle (or reach past it)?"""
    xy = np.asarray(outline.minimum_rotated_rectangle.exterior.coords)[:3]
    e1, e2 = xy[1] - xy[0], xy[2] - xy[1]
    long_dir = e1 if np.hypot(*e1) >= np.hypot(*e2) else e2
    ang = float(np.degrees(np.arctan2(long_dir[1], long_dir[0])))
    ox0, oy0, ox1, oy1 = affinity.rotate(outline, -ang, origin=(0, 0)).bounds
    rx0, ry0, rx1, ry1 = affinity.rotate(region, -ang, origin=(0, 0)).bounds
    m = BROKEN_MARGIN_MM
    return (rx0 <= ox0 + m or rx1 >= ox1 - m), (ry0 <= oy0 + m or ry1 >= oy1 - m)


# Residual row (feature_id, quantity) behind each dimension test that a break can make informational.
_TEST_RESIDUAL = {
    "bbox.x": ("outline", "length"),
    "bbox.y": ("outline", "width"),
    "side.thickness": ("side", "thickness"),
}


def _split_broken_residuals(
    residuals: list[FeatureResidual], informational: Sequence[str]
) -> tuple[list[FeatureResidual], list[FeatureResidual]]:
    """(kept, informational) residual rows: a row behind an informational test compares the intact model with the
    broken photo, so it is reported apart and never counts towards the pass rule, the max error or the fixer."""
    keys = {_TEST_RESIDUAL[t] for t in informational if t in _TEST_RESIDUAL}
    holes = {t.split(".")[0] for t in informational if t.endswith(".diameter")}
    kept: list[FeatureResidual] = []
    info: list[FeatureResidual] = []
    for r in residuals:
        broken = (r.feature_id, r.quantity) in keys or r.feature_id in holes
        (info if broken else kept).append(r)
    return kept, info


def _snap_union(base: Frame, other: Frame) -> Frame:
    """Union of two frames, snapped to `base`'s pixel grid so the photo mask can be pasted without resampling."""
    u = base.union(other)
    ppm = base.px_per_mm
    dx = int(np.floor((u.u0_mm - base.u0_mm) * ppm))
    dy = int(np.floor((base.v0_mm - u.v0_mm) * ppm))
    u0 = base.u0_mm + dx / ppm
    v0 = base.v0_mm - dy / ppm
    w = int(np.ceil((u.u0_mm + u.width_px / ppm - u0) * ppm)) + 1
    h = int(np.ceil((v0 - (u.v0_mm - u.height_px / ppm)) * ppm)) + 1
    return Frame(ppm, u0, v0, w, h)


def _paste(photo: PhotoMask, frame: Frame) -> BoolMask:
    out = np.zeros(frame.shape, dtype=bool)
    ox = round((photo.frame.u0_mm - frame.u0_mm) * frame.px_per_mm)
    oy = round((frame.v0_mm - photo.frame.v0_mm) * frame.px_per_mm)
    h, w = photo.mask.shape
    out[oy : oy + h, ox : ox + w] = photo.mask
    return out


# ----------------------------------------------------------------------------------------------- verify


def verify(
    exec_result: ExecResult,
    measurements: Mapping[str, Measurements],
    partspec: PartSpec | None,
    *,
    photo_masks: Mapping[str, PhotoMask] | None = None,
    vetoes: Iterable[JudgeVeto] = (),
    px_per_mm: float = DEFAULT_PX_PER_MM,
    thresholds: Thresholds | None = None,
    camera_views: Mapping[str, CameraView] | None = None,
    refine_in_photo: bool = True,
) -> VerifyOutput:
    """Compare the executed model with the measurements and decide ``verified`` (see module docstring).

    ``photo_masks`` are rectified masks in each view's part frame (used for the rectified comparison and as the start
    of the camera comparison); ``camera_views`` switch a view to the photo-frame comparison.
    """
    t0 = time.perf_counter()
    th = thresholds or Thresholds(hausdorff_mm=HAUSDORFF_PASS_MM, iou=IOU_PASS)
    veto_list = list(vetoes)
    hashes: dict[str, str] = {
        "code_sha256": exec_result.code_sha,
        "params_sha256": _sha_json(exec_result.params_used),
        "measurements_sha256": _sha_json({k: v.model_dump(mode="json") for k, v in sorted(measurements.items())}),
    }
    if partspec is not None:
        hashes["partspec_sha256"] = _sha_json(partspec.model_dump(mode="json"))
    base = {
        "origin": _origin(measurements),
        "versions": _versions(exec_result),
        "thresholds": th,
        "vetoes": veto_list,
    }

    validity = _validity(exec_result)
    if not exec_result.ok or exec_result.mesh is None:
        err = exec_result.error.short() if exec_result.error else "the program produced no mesh"
        fail = [f"The program did not produce a usable solid: {err}."]
        v = Verification(verified=False, status="failed", reasons=fail, validity=validity, hashes=hashes,
                         ms=int((time.perf_counter() - t0) * 1000), **base)  # fmt: skip
        return VerifyOutput(v)

    mesh = exec_result.mesh
    hashes["mesh_sha256"] = hashlib.sha256(
        np.round(mesh.vertices, 6).tobytes() + np.asarray(mesh.faces, dtype=np.int64).tobytes()
    ).hexdigest()
    feats = SolidFeatures.from_dict(exec_result.features) if exec_result.features else None
    reasons: list[str] = []
    overlays: dict[str, bytes] = {}
    view_results: dict[str, ViewResult] = {}
    view_metrics: list[ViewMetrics] = []
    view_gates: dict[str, list[str]] = {}

    broken_part, broken_info = broken_region(partspec, measurements.get("top"))
    prism: Mesh | None = None  # broken region as a volume in model coordinates (set once the top view is registered)
    region_model: Polygon | MultiPolygon | None = None  # the same region as a footprint in model coordinates
    break_h, height_info = broken_height(partspec, measurements)
    height_break = height_info != {}
    if height_break:
        broken_info = height_info
        # the missing top as a volume above the break: left out of the side and walk-around views, never the top view
        prism = _slab(mesh.vertices, break_h) if break_h is not None else None
    slab_z = float(np.min(mesh.vertices[:, 2])) + break_h if break_h is not None else None

    def gate(vr: ViewResult, short_side: float) -> None:
        vr.short_side_mm = short_side
        vr.iou_gated = short_side >= IOU_GATE_MIN_WIDTH_MM
        if not vr.iou_gated:
            vr.gate_note = (
                f"small silhouette ({short_side:.1f} mm across, under {IOU_GATE_MIN_WIDTH_MM:g} mm), so IoU is "
                f"reported but not gated (it shrinks with size for the same edge error); gated on Hausdorff <= "
                f"{th.hausdorff_mm} mm and mean contour distance <= {MEAN_GATE_MM} mm, plus its part tests"
            )

    for view, meas in sorted(measurements.items(), key=lambda kv: (kv[0] != "top", kv[0])):
        if view not in COMPARED_VIEWS:
            continue
        photo = (photo_masks or {}).get(view) or photo_mask_from_measurements(meas, px_per_mm)
        projections = ["top"] if view == "top" else ["side_xz", "side_yz"]
        best: tuple[ViewResult, M.ContourDistances] | None = None
        for proj in projections:
            ex_frame = broken_part if view == "top" else None
            ex_model = _band(region_model, proj, above_mm=slab_z) if view != "top" else None
            r = _compare_view(
                view, proj, mesh.vertices, mesh.faces, photo, exclude_frame=ex_frame, exclude_model=ex_model
            )
            if best is None or r[0].metrics.iou > best[0].metrics.iou:
                best = r
        assert best is not None
        vr, dist = best
        vr.matrix = vr.transform.matrix()
        vr.rectified_metrics = vr.metrics
        if view == "top" and broken_part is not None:
            region_model = _transform_poly(broken_part, np.linalg.inv(vr.matrix))
            prism = _prism(region_model, mesh.vertices)
        cam = (camera_views or {}).get(view)
        if cam is not None:
            cc = compare_camera(
                view, vr.projection, mesh.vertices, mesh.faces, cam, vr.matrix, refine=refine_in_photo,
                origin=meas.origin, exclude=None if height_break and view == "top" else prism,
            )  # fmt: skip
            vr.camera, vr.frame, vr.metrics, vr.matrix = cc, "camera", cc.metrics, cc.model_to_part
            vr.excluded_mask, vr.excluded_mm2 = cc.excluded_mask, cc.excluded_mm2
            overlays[f"residual_{view}.png"] = cc.overlay_png
            reasons += cc.notes
        else:
            title = f"{view} view: IoU {vr.metrics.iou:.3f}, Hausdorff {vr.metrics.hausdorff_mm:.2f} mm"
            overlays[f"residual_{view}.png"] = M.residual_heatmap(
                vr.photo.mask, vr.model_mask, vr.photo.frame, distances=dist, title=title, excluded=vr.excluded_mask
            )
        gate(vr, float(meas.width.value))
        view_gates[view] = ["hausdorff", "iou"] if vr.iou_gated else ["hausdorff", "mean"]
        view_results[view] = vr
        view_metrics.append(vr.metrics)
        if view == "top" and broken_part is not None and vr.matrix is not None:
            region_model = _transform_poly(broken_part, np.linalg.inv(vr.matrix))
            prism = _prism(region_model, mesh.vertices)

    # Walk-around frames: calibrated views without their own Measurements, compared in their own photo frames.
    orbit_cams = {k: c for k, c in (camera_views or {}).items() if k not in measurements}
    if orbit_cams:
        top_vr = view_results.get("top")
        m2p = top_vr.matrix if top_vr is not None and top_vr.matrix is not None else np.eye(3)
        oc = compare_orbit(orbit_cams, mesh.vertices, mesh.faces, m2p, refine=refine_in_photo, exclude=prism)
        reasons += oc.notes
        frames: list[ViewResult] = []
        for name, cc in oc.frames.items():
            fvr = ViewResult(name, "top", Rigid2D(), cc.metrics, cc.model_mask,
                             PhotoMask(cc.photo_mask, Frame(cam_ppm(cc), 0.0, 0.0, *cc.photo_mask.shape[::-1])),
                             frame="camera", camera=cc, excluded_mask=cc.excluded_mask,
                             excluded_mm2=cc.excluded_mm2)  # fmt: skip
            gate(fvr, cc.photo_short_side_mm or 0.0)
            view_results[name] = fvr
            frames.append(fvr)
        agg = _orbit_metrics(frames)
        view_metrics.append(agg)
        all_iou = all(f.iou_gated for f in frames)
        view_gates["orbit"] = ["hausdorff", "iou"] if all_iou else ["hausdorff", "mean"]
        worst = max(frames, key=lambda f: f.metrics.hausdorff_mm)
        if worst.camera is not None:
            overlays["residual_orbit.png"] = worst.camera.overlay_png
        reasons.append(_orbit_reason(frames, agg, oc.skipped, th))

    hole_names: dict[int, str] = {}
    residuals, values, hole_reasons = _model_values(
        exec_result, feats, measurements, partspec, view_results, hole_names
    )
    tests = evaluate_tests(generate_tests(partspec, measurements), values)
    informational: list[str] = []
    informational_residuals: list[FeatureResidual] = []
    if broken_part is not None or break_h is not None:
        tests, informational = _broken_tests(tests, broken_part, measurements)
        residuals, informational_residuals = _split_broken_residuals(residuals, informational)
    probes = _functional(exec_result, feats, hole_names)
    tests += as_part_tests(probes)  # P1: reported, never part of the pass rule
    functional = {
        "passed": sum(p.passed for p in probes),
        "total": len(probes),
        "probes": [p.to_dict() for p in probes],
    }
    residuals.sort(key=lambda r: abs(r.delta_mm), reverse=True)

    # ---- the pass rule (PLAN §6.5), exactly
    p0_failed = [t for t in tests if t.priority == "P0" and not t.passed]
    view_fail = [
        vr.metrics
        for vr in view_results.values()
        if vr.metrics.hausdorff_mm > th.hausdorff_mm
        or (vr.iou_gated and vr.metrics.iou < th.iou)
        or (not vr.iou_gated and vr.metrics.mean_mm > MEAN_GATE_MM)
    ]
    blocking = [v for v in veto_list if v.severity == "blocking"]
    verified = bool(view_metrics) and not p0_failed and not view_fail and not blocking
    invalid = validity is not None and not validity.is_valid
    status: Literal["verified", "best_effort", "failed"] = (
        "failed" if invalid else "verified" if verified else "best_effort"
    )

    reasons += _reasons(verified, tests, p0_failed, list(view_results.values()), th, blocking, residuals)
    broken_out: dict[str, Any] = {}
    if broken_info:
        broken_out = {
            **broken_info,
            "excluded_mm2": {k: round(vr.excluded_mm2, 2) for k, vr in view_results.items() if vr.excluded_mm2 > 0},
            "informational_tests": informational,
            "informational_residuals": [r.model_dump(mode="json") for r in informational_residuals],
        }
        reasons.append(broken_info["statement"])
        if informational:
            reasons.append(
                "Informational only (they span the broken region the photo cannot show): "
                + ", ".join(informational)
                + "."
            )
        for ir in informational_residuals:
            reasons.append(
                f"{ir.feature_id} {ir.quantity}: model {ir.model_mm:.2f} mm vs {ir.measured_mm:.2f} mm on the broken "
                f"part ({ir.delta_mm:+.2f} mm) - NOT verified: the photo shows the broken part, so the replacement's "
                "value here is inferred and cannot be checked against it (informational, not in the max error)."
            )
    reasons += hole_reasons
    errors = [vm.hausdorff_mm for vm in view_metrics] + [abs(r.delta_mm) for r in residuals]
    for name, data in overlays.items():
        hashes[f"overlay:{name}"] = hashlib.sha256(data).hexdigest()
    v = Verification(
        verified=verified,
        status=status,
        reasons=reasons,
        views=view_metrics,
        residuals=residuals,
        tests=tests,
        validity=validity,
        max_error_mm=max(errors) if errors else None,
        hashes=hashes,
        ms=int((time.perf_counter() - t0) * 1000),
        **base,
    )
    return VerifyOutput(v, overlays, view_results, values, view_gates, functional, broken_out)


def _functional(
    exec_result: ExecResult, feats: SolidFeatures | None, hole_names: Mapping[int, str]
) -> list[FunctionalProbe]:
    """Screw, interface and printability probes for the executed model (all informational)."""
    if feats is None or exec_result.mesh is None or exec_result.solid_info is None:
        return []
    holes = [(hole_names.get(j, f"model_hole_{j + 1}"), h) for j, h in enumerate(feats.holes)]
    facts, over = part_facts(exec_result.solid_info.volume_mm3, exec_result.mesh)
    key = facts.orientation.split(":")[0]
    return run_probes(
        holes,
        (exec_result.features or {}).get("interfaces") or [],
        min_wall_mm=feats.min_wall_mm,
        overhang_mm2=over.get(key),
        area_mm2=exec_result.solid_info.area_mm2,
        orientation=facts.orientation.split(": ", 1)[-1],
    )


def _validity(exec_result: ExecResult) -> Validity | None:
    si = exec_result.solid_info
    if si is None:
        return None
    watertight = False
    if exec_result.mesh is not None:
        tm = exec_result.mesh.trimesh()
        watertight = bool(tm.is_watertight and tm.is_winding_consistent)
    min_wall = (exec_result.features or {}).get("min_wall_mm")
    issues = []
    if not si.valid:
        issues.append("OCCT reports an invalid solid")
    if si.n_solids != 1:
        issues.append(f"{si.n_solids} separate solids (expected 1)")
    if not watertight:
        issues.append("mesh is not watertight")
    if min_wall is not None and min_wall < 0.8:
        issues.append(f"thinnest wall about {min_wall:.2f} mm (< 0.8 mm)")
    return Validity(
        is_valid=si.valid,
        single_solid=si.n_solids == 1,
        watertight=watertight,
        volume_mm3=si.volume_mm3,
        bbox_mm=si.size_mm,
        min_wall_mm=min_wall,
        issues=issues,
    )


def _match(exp_c: FloatArray, exp_d: FloatArray, got_c: FloatArray, got_d: FloatArray) -> dict[int, int]:
    """Hungarian match of expected holes to found holes on centre distance (+ half the diameter difference)."""
    if len(exp_c) == 0 or len(got_c) == 0:
        return {}
    cost = np.linalg.norm(exp_c[:, None, :] - got_c[None, :, :], axis=2) + 0.5 * np.abs(exp_d[:, None] - got_d[None, :])
    rows, cols = linear_sum_assignment(cost)
    return {
        int(r): int(c)
        for r, c in zip(rows, cols, strict=True)
        if np.linalg.norm(exp_c[r] - got_c[c]) <= HOLE_MATCH_MAX_MM
    }


def _model_values(
    exec_result: ExecResult,
    feats: SolidFeatures | None,
    measurements: Mapping[str, Measurements],
    partspec: PartSpec | None,
    views: Mapping[str, ViewResult],
    hole_names: dict[int, str] | None = None,
) -> tuple[list[FeatureResidual], dict[str, Value], list[str]]:
    """Model values for the tests, residual rows and notes.

    With a posed top/side view the tested values come from the model's camera render measured by the metrology code
    (like for like with the photo); the true CAD dimensions are kept under ``cad.*`` keys for display.
    """
    si = exec_result.solid_info
    assert exec_result.mesh is not None
    verts = exec_result.mesh.vertices
    validity = _validity(exec_result)
    values: dict[str, Value] = {
        "valid": si.valid if si else None,
        "single_solid": (si.n_solids == 1) if si else None,
        "watertight": validity.watertight if validity else None,
        "volume": si.volume_mm3 if si else None,
        "min_wall": feats.min_wall_mm if feats else None,
    }
    residuals: list[FeatureResidual] = []
    notes: list[str] = []

    def add(fid: str, qty: str, measured: float, model: float, tol: float) -> None:
        d = model - measured
        residuals.append(FeatureResidual(feature_id=fid, quantity=qty, measured_mm=measured, model_mm=model,
                                         delta_mm=d, tol_mm=tol, passed=abs(d) <= tol + 1e-9))  # fmt: skip

    def like_for_like(view: str) -> Measurements | None:
        vr = views.get(view)
        return vr.camera.model_measurements if vr is not None and vr.camera is not None else None

    top = measurements.get("top")
    top_mm = like_for_like("top")
    if top is not None:
        length, width = footprint_lw(verts)
        values["cad.length"], values["cad.width"] = length, width
        if top_mm is not None:
            length, width = top_mm.length.value, top_mm.width.value
            notes.append("top view: length, width and holes compared like for like (model rendered with the photo's "
                         "camera and measured with the same metrology code).")  # fmt: skip
        values["bbox.x"], values["bbox.y"] = length, width
        add("outline", "length", top.length.value, length, BBOX_TOL_MM)
        add("outline", "width", top.width.value, width, BBOX_TOL_MM)

    side = measurements.get("side")
    if side is not None:
        vr_side = views.get("side")
        proj = vr_side.projection if vr_side is not None else "side_xz"
        cad_t = footprint_lw(verts, proj)[1]
        values["cad.side.thickness"] = cad_t
        side_mm = like_for_like("side")
        model_t = side_mm.width.value if side_mm is not None else cad_t
        values["side.thickness"] = model_t
        add("side", "thickness", side.width.value, model_t, THICKNESS_TOL_MM)

    th = expected_thickness(partspec, measurements)
    if feats is not None and feats.plate_thickness_mm is not None:
        values["thickness"] = feats.plate_thickness_mm
        if th is not None:
            add("plate", "thickness", th.value, feats.plate_thickness_mm, THICKNESS_TOL_MM)

    exp = expected_holes(partspec, measurements)
    if not exp:
        return residuals, values, notes
    ec = np.array([h.center_mm for h in exp], dtype=np.float64)
    ed = np.array([h.diameter_mm for h in exp], dtype=np.float64)
    vr_top = views.get("top")
    M2 = vr_top.matrix if vr_top is not None and vr_top.matrix is not None else Rigid2D().matrix()
    cad_holes = feats.holes if feats is not None else []
    cad_c = apply_2d(M2, np.array([h.center_mm for h in cad_holes])) if cad_holes else np.zeros((0, 2))
    cad_d = np.array([h.diameter_mm for h in cad_holes], dtype=np.float64)
    cad_match = _match(ec, ed, cad_c, cad_d)
    for i, j in cad_match.items():
        values[f"cad.hole:{exp[i].id}.diameter"] = float(cad_d[j])
    if hole_names is not None:  # model hole index -> the measured hole's id, for the functional probes
        hole_names.update({j: exp[i].id for i, j in cad_match.items()})

    if top_mm is not None and vr_top is not None and vr_top.camera is not None:
        # Model holes as measured from its render, moved into the photo's part frame through the mat.
        to_photo = np.linalg.inv(vr_top.camera.part_to_mat) @ np.asarray(top_mm.part_to_mat, dtype=np.float64)
        got_c = apply_2d(to_photo, np.array([h.center_mm for h in top_mm.holes])) if top_mm.holes else np.zeros((0, 2))
        got_d = np.array([h.diameter.value for h in top_mm.holes], dtype=np.float64)
        got_depth: list[float | None] = [None] * len(got_d)
    else:
        got_c, got_d = cad_c, cad_d
        got_depth = [h.depth_mm for h in cad_holes]
    matched = _match(ec, ed, got_c, got_d)
    for i, eh in enumerate(exp):
        if i not in matched:
            notes.append(f"{eh.id} (diameter {eh.diameter_mm:.2f} mm at {eh.center_mm[0]:.1f}, "
                         f"{eh.center_mm[1]:.1f}) has no matching hole in the model.")  # fmt: skip
            continue
        j = matched[i]
        c = got_c[j]
        values[f"hole:{eh.id}.diameter"] = float(got_d[j])
        values[f"hole:{eh.id}.center_offset"] = float(np.linalg.norm(c - ec[i]))
        add(eh.id, "diameter", eh.diameter_mm, float(got_d[j]), FEATURE_TOL_MM)
        add(eh.id, "center_x", eh.center_mm[0], float(c[0]), CENTER_TOL_MM)
        add(eh.id, "center_y", eh.center_mm[1], float(c[1]), CENTER_TOL_MM)
        depth = got_depth[j]
        if eh.depth_mm is not None and depth is not None:
            values[f"hole:{eh.id}.depth"] = depth
            add(eh.id, "depth", eh.depth_mm, depth, DEPTH_TOL_MM)
    return residuals, values, notes


def _reasons(
    verified: bool,
    tests: list[PartTest],
    p0_failed: list[PartTest],
    views: list[ViewResult],
    th: Thresholds,
    blocking: list[JudgeVeto],
    residuals: list[FeatureResidual],
) -> list[str]:
    out: list[str] = []
    n_p0 = sum(t.priority == "P0" for t in tests)
    if not views:
        out.append("No measured top or side view to compare against, so the part cannot be verified.")
    for vr in views:
        if vr.view not in COMPARED_VIEWS:
            continue  # walk-around frames get one summary line of their own
        vm = vr.metrics
        ok = vm.hausdorff_mm <= th.hausdorff_mm and (vm.iou >= th.iou if vr.iou_gated else vm.mean_mm <= MEAN_GATE_MM)
        where = (
            f" (worst at x={vm.worst_point_mm[0]:.1f}, y={vm.worst_point_mm[1]:.1f} mm)"
            if vm.worst_point_mm and not ok
            else ""
        )
        frame = "photo frame" if vr.frame == "camera" else "rectified"
        iou = (
            f"IoU {vm.iou:.3f} (needs >= {th.iou})"
            if vr.iou_gated
            else f"IoU {vm.iou:.3f} (not gated), mean contour distance {vm.mean_mm:.2f} mm (needs <= {MEAN_GATE_MM} mm)"
        )
        out.append(
            f"{vm.view} view ({frame}): {iou}, Hausdorff {vm.hausdorff_mm:.2f} mm "
            f"(needs <= {th.hausdorff_mm} mm){where}" + ("" if ok else " - fails")
        )
        if vr.gate_note:
            out.append(f"{vm.view} view: {vr.gate_note}.")
    if verified:
        out.insert(0, f"Verified: all {n_p0} P0 tests pass and every measured view is within tolerance.")
    for t in p0_failed:
        val = "missing" if t.value is None else f"{t.value:.2f}"
        out.append(f"Test failed: {t.description} (model: {val}).")
    for r in residuals:
        if not r.passed:
            out.append(f"{r.feature_id} {r.quantity}: model {r.model_mm:.2f} vs measured {r.measured_mm:.2f} mm "
                       f"({r.delta_mm:+.2f} mm, tolerance +/-{r.tol_mm} mm).")  # fmt: skip
    for v in blocking:
        out.append(f"Blocking judge veto on {v.feature}: {v.issue}.")
    return out
