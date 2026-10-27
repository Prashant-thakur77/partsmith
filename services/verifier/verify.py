"""verify(): the sole authority for ``verified`` (PLAN §6.5).

For every measured view: register the model silhouette onto the measured one (rigid 2-D search, never scaling),
compute IoU, boundary distances and over/under areas, and draw the residual overlay. Then measure the model's own
features (hole diameters and centres, footprint length/width, plate thickness), compare them with the measured values,
run the part tests, and apply the pass rule exactly:

    verified = all P0 tests pass
               AND Hausdorff <= 0.5 mm AND IoU >= 0.97 on every measured view
               AND no blocking judge veto

``max_error_mm`` is the largest of every view's Hausdorff distance and every |feature residual|.
``status`` is "verified" when that holds, "failed" when the program did not run or the solid is invalid, and
"best_effort" otherwise. Model output never reaches this decision except through the geometry it built.
"""

from __future__ import annotations

import hashlib
import json
import sys
import time
from collections.abc import Iterable, Mapping
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

from services.geom_worker.sandbox import ExecResult
from services.verifier import VERIFIER_VERSION
from services.verifier import metrics as M
from services.verifier.align import Rigid2D, align
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
from services.verifier.render import BoolMask, FloatArray, Frame, circle_polygon, project, rasterize_polygon, silhouette
from services.verifier.solid_features import SolidFeatures

DEFAULT_PX_PER_MM = 20.0
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
    transform: Rigid2D
    metrics: ViewMetrics
    model_mask: BoolMask
    photo: PhotoMask


@dataclass
class VerifyOutput:
    verification: Verification
    overlays: dict[str, bytes] = field(default_factory=dict)
    views: dict[str, ViewResult] = field(default_factory=dict)
    model_values: dict[str, Value] = field(default_factory=dict)


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


def footprint_lw(vertices: FloatArray) -> tuple[float, float]:
    """Long and short side of the minimum-area rectangle around the top-view footprint (exact: hull of vertices)."""
    uv = project(vertices, "top").astype(np.float32)
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


def _compare_view(
    view: str, projection: str, vertices: FloatArray, faces: Any, photo: PhotoMask
) -> tuple[ViewResult, M.ContourDistances]:
    ppm = photo.frame.px_per_mm
    uv = project(vertices, projection)
    model_frame = Frame.around(uv, ppm, margin_mm=3.0)
    model_mask = silhouette(vertices, faces, projection, model_frame)
    res = align(model_mask, model_frame, photo.mask, photo.frame)
    T = res.transform
    # Render the registered model on a frame that holds both silhouettes, so nothing is cropped.
    placed = Frame.around(T.apply(uv), ppm, margin_mm=3.0)
    frame = _snap_union(photo.frame, placed)
    photo_mask = _paste(photo, frame)
    mm = silhouette(vertices, faces, projection, frame, transform=T.matrix())
    d = M.mask_contour_distances(mm, photo_mask, frame)
    over, under = M.over_under_mm2(photo_mask, mm, frame)
    vm = ViewMetrics(
        view=view,
        iou=M.iou(mm, photo_mask),
        hausdorff_mm=d.hausdorff_mm,
        hd95_mm=d.hd95_mm,
        mean_mm=d.mean_mm,
        worst_point_mm=d.worst_point_mm,
        over_area_mm2=over,
        under_area_mm2=under,
    )
    return ViewResult(view, projection, T, vm, mm, PhotoMask(photo_mask, frame)), d


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
) -> VerifyOutput:
    """Compare the executed model with the measurements and decide ``verified`` (see module docstring)."""
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

    for view, meas in sorted(measurements.items()):
        if view not in COMPARED_VIEWS:
            continue
        photo = (photo_masks or {}).get(view) or photo_mask_from_measurements(meas, px_per_mm)
        projections = ["top"] if view == "top" else ["side_xz", "side_yz"]
        best: tuple[ViewResult, M.ContourDistances] | None = None
        for proj in projections:
            r = _compare_view(view, proj, mesh.vertices, mesh.faces, photo)
            if best is None or r[0].metrics.iou > best[0].metrics.iou:
                best = r
        assert best is not None
        vr, dist = best
        view_results[view] = vr
        view_metrics.append(vr.metrics)
        title = f"{view} view: IoU {vr.metrics.iou:.3f}, Hausdorff {vr.metrics.hausdorff_mm:.2f} mm"
        overlays[f"residual_{view}.png"] = M.residual_heatmap(
            vr.photo.mask, vr.model_mask, vr.photo.frame, distances=dist, title=title
        )

    residuals, values, hole_reasons = _model_values(exec_result, feats, measurements, partspec, view_results)
    tests = evaluate_tests(generate_tests(partspec, measurements), values)
    residuals.sort(key=lambda r: abs(r.delta_mm), reverse=True)

    # ---- the pass rule (PLAN §6.5), exactly
    p0_failed = [t for t in tests if t.priority == "P0" and not t.passed]
    view_fail = [vm for vm in view_metrics if vm.hausdorff_mm > th.hausdorff_mm or vm.iou < th.iou]
    blocking = [v for v in veto_list if v.severity == "blocking"]
    verified = bool(view_metrics) and not p0_failed and not view_fail and not blocking
    invalid = validity is not None and not validity.is_valid
    status: Literal["verified", "best_effort", "failed"] = (
        "failed" if invalid else "verified" if verified else "best_effort"
    )

    reasons += _reasons(verified, tests, p0_failed, view_metrics, th, blocking, residuals)
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
    return VerifyOutput(v, overlays, view_results, values)


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


def _model_values(
    exec_result: ExecResult,
    feats: SolidFeatures | None,
    measurements: Mapping[str, Measurements],
    partspec: PartSpec | None,
    views: Mapping[str, ViewResult],
) -> tuple[list[FeatureResidual], dict[str, Value], list[str]]:
    si = exec_result.solid_info
    assert exec_result.mesh is not None
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

    top = measurements.get("top")
    if top is not None:
        length, width = footprint_lw(exec_result.mesh.vertices)
        values["bbox.x"], values["bbox.y"] = length, width
        add("outline", "length", top.length.value, length, BBOX_TOL_MM)
        add("outline", "width", top.width.value, width, BBOX_TOL_MM)

    th = expected_thickness(partspec, measurements)
    if feats is not None and feats.plate_thickness_mm is not None:
        values["thickness"] = feats.plate_thickness_mm
        if th is not None:
            add("plate", "thickness", th.value, feats.plate_thickness_mm, THICKNESS_TOL_MM)

    exp = expected_holes(partspec, measurements)
    if exp and feats is not None:
        T = views["top"].transform if "top" in views else Rigid2D()
        model_holes = feats.holes
        mc = T.apply(np.array([h.center_mm for h in model_holes])) if model_holes else np.zeros((0, 2))
        ec = np.array([h.center_mm for h in exp])
        matched: dict[int, int] = {}
        if len(mc):
            cost = np.linalg.norm(ec[:, None, :] - mc[None, :, :], axis=2)
            cost = cost + 0.5 * np.abs(np.array([h.diameter_mm for h in exp])[:, None]
                                       - np.array([h.diameter_mm for h in model_holes])[None, :])  # fmt: skip
            rows, cols = linear_sum_assignment(cost)
            for r, c in zip(rows, cols, strict=True):
                if np.linalg.norm(ec[r] - mc[c]) <= HOLE_MATCH_MAX_MM:
                    matched[int(r)] = int(c)
        for i, eh in enumerate(exp):
            if i not in matched:
                notes.append(f"{eh.id} (diameter {eh.diameter_mm:.2f} mm at {eh.center_mm[0]:.1f}, "
                             f"{eh.center_mm[1]:.1f}) has no matching hole in the model.")  # fmt: skip
                continue
            mh = model_holes[matched[i]]
            c = mc[matched[i]]
            values[f"hole:{eh.id}.diameter"] = mh.diameter_mm
            values[f"hole:{eh.id}.center_offset"] = float(np.linalg.norm(c - ec[i]))
            add(eh.id, "diameter", eh.diameter_mm, mh.diameter_mm, FEATURE_TOL_MM)
            add(eh.id, "center_x", eh.center_mm[0], float(c[0]), CENTER_TOL_MM)
            add(eh.id, "center_y", eh.center_mm[1], float(c[1]), CENTER_TOL_MM)
            if eh.depth_mm is not None:
                values[f"hole:{eh.id}.depth"] = mh.depth_mm
                add(eh.id, "depth", eh.depth_mm, mh.depth_mm, DEPTH_TOL_MM)
    return residuals, values, notes


def _reasons(
    verified: bool,
    tests: list[PartTest],
    p0_failed: list[PartTest],
    views: list[ViewMetrics],
    th: Thresholds,
    blocking: list[JudgeVeto],
    residuals: list[FeatureResidual],
) -> list[str]:
    out: list[str] = []
    n_p0 = sum(t.priority == "P0" for t in tests)
    if not views:
        out.append("No measured top or side view to compare against, so the part cannot be verified.")
    for vm in views:
        ok = vm.hausdorff_mm <= th.hausdorff_mm and vm.iou >= th.iou
        where = (
            f" (worst at x={vm.worst_point_mm[0]:.1f}, y={vm.worst_point_mm[1]:.1f} mm)"
            if vm.worst_point_mm and not ok
            else ""
        )
        out.append(
            f"{vm.view} view: IoU {vm.iou:.3f} (needs >= {th.iou}), Hausdorff {vm.hausdorff_mm:.2f} mm "
            f"(needs <= {th.hausdorff_mm} mm){where}" + ("" if ok else " - fails")
        )
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
