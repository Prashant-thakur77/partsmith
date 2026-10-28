"""Round-2 evidence sources for the fix job: model/user feature points, the orbit clip, cited specs, broken-region
completion, judge hotspot crops and the package extras (install card, zip bundle, ship gate).

Each source is optional and feature-checked: when a provider or metrology capability is not available in this build the
job continues on the old path and the trace says so. The rules do not bend: points are measured by code; cited values
never override measured ones; a Muse Image completion only enters the outline after the code gate accepts it;
`verified` still comes only from the verifier.
"""

from __future__ import annotations

import importlib
import io
import json
import math
import re
import zipfile
from collections.abc import Callable, Mapping, Sequence
from typing import TYPE_CHECKING, Any

import cv2
import numpy as np
from partsmith_schemas import ArtifactEvent, Measured, Source
from partsmith_schemas.common import Citation, Evidence

from services.agent import providers
from services.common import blobs

if TYPE_CHECKING:
    from services.agent.orchestrator import FixRun, Round

CONFLICT_MM = 0.5
RECON_PX_PER_MM = 6.0  # rectified grid for the completion proposal (whole mat, so the gate can re-detect the markers)  # |cited - measured| beyond this is logged as a conflict
POINT_KINDS = ("hole", "slot", "tab", "broken_edge")  # feature taps; "exclude" taps are negatives, not features
_MODEL_RE = re.compile(r"\b([A-Z][A-Za-z]{1,12}[- ]?[A-Z0-9]{0,4}\d{2,}[A-Z0-9-]*)\b")


def _get(obj: Any, *names: str, default: Any = None) -> Any:
    for n in names:
        if isinstance(obj, Mapping) and n in obj:
            return obj[n]
        if hasattr(obj, n):
            return getattr(obj, n)
    return default


def _optional(module: str, name: str) -> Any:
    try:
        return getattr(importlib.import_module(module), name, None)
    except ImportError:
        return None


# ------------------------------------------------------------------------------------------------- points


def feature_points(run: FixRun) -> list[Any]:
    """Points to measure: the understand stage's feature points (evidence pixels of each hole/slot it named) plus user
    taps (`points.json` in the run dir, or RunOptions.points): {"top": [{"x", "y", "kind", "id"?}]}."""
    FeaturePoint = _optional("services.metrology.points", "FeaturePoint")
    if FeaturePoint is None or run.spec is None:
        return []
    pts: list[Any] = []
    for f in run.spec.features:
        if f.kind not in ("through_hole", "blind_hole", "slot"):
            continue
        meas = getattr(f, "diameter", None) or getattr(f, "width", None)
        ev = getattr(meas, "evidence", None)
        if ev is None or not ev.pixels or (ev.view not in (None, "top")):
            continue
        x, y = ev.pixels[0][:2]
        pts.append(FeaturePoint(f.id, "slot" if f.kind == "slot" else "hole", (float(x), float(y)), "model"))
    for i, t in enumerate(user_taps(run), start=1):
        kind = str(t.get("kind", "hole"))
        if kind == "exclude":
            continue  # a negative point for every prompt (`exclude_points`), not a feature
        kind = kind if kind in POINT_KINDS else "hole"
        pts.append(FeaturePoint(str(t.get("id") or f"tap_{i}"), kind, (float(t["x"]), float(t["y"])), "user"))
    return pts


def user_taps(run: FixRun) -> list[dict[str, Any]]:
    """The user's taps on the top photo (`points.json` in the run dir, or RunOptions.points), photo pixels."""
    taps = dict(run.opts.points or {})
    saved = run.job.read_json("points.json")
    if isinstance(saved, Mapping):
        taps.update(saved)
    return [dict(t) for t in taps.get("top") or [] if isinstance(t, Mapping) and "x" in t and "y" in t]


def point_negatives(run: FixRun, view: str = "top") -> list[tuple[float, float]]:
    """Negative points for every feature prompt on `view` besides the mat markers (which the metrology adds itself):
    the user's `exclude` taps (top view only) and, when the capture gate flagged glare on that photo, a pixel in the
    largest blown-out blob on the part."""
    out: list[tuple[float, float]] = []
    if view == "top":
        out += [(float(t["x"]), float(t["y"])) for t in user_taps(run) if t.get("kind") == "exclude"]
    mo = run.mo.get(view)
    glare_pt = _optional("services.metrology.points", "glare_point_px")
    if mo is not None and glare_pt is not None and view in run.photos:
        glare = next((c for c in mo.result.capture.checks if c.name == "glare"), None)
        if glare is not None and glare.severity != "ok":
            from services.metrology.measure import decode_image

            g = glare_pt(decode_image(run.photos[view]), mo.photo_mask)
            if g is not None:
                out.append(g)
                run.log(f"points: glare on the {view} photo; its brightest blob {tuple(round(v) for v in g)} px is "
                        "sent as a negative point")  # fmt: skip
    return out


def point_mask_source() -> str:
    """What the point segmenter is right now: SAM 3.1 (its score is a confidence) or the labelled mock."""
    return "mock-flood" if providers.stage_mode("segment_points") == "mock" else "sam-3.1"


def _quality_of(note: str | None, radius: float) -> float:
    m = re.search(r"rms ([0-9.]+) mm", note or "")
    return float(m.group(1)) / radius if m and radius > 0 else math.inf


def apply_points(run: FixRun) -> None:
    """Measure the pointed-at features with point-prompted segmentation and merge better hole fits into the top view."""
    seg = getattr(providers, "segment_points", None)
    measure = _optional("services.metrology.points", "measure_features_from_points")
    merge = _optional("services.metrology.points", "merge_holes")
    mo, top = run.mo.get("top"), run.measurements.get("top")
    if seg is None or measure is None or merge is None or mo is None or top is None or mo.detection is None:
        return
    points = feature_points(run)
    if not points:
        return
    from services.metrology.measure import decode_image

    img = decode_image(run.photos["top"])
    height = run.heights.get("top", (None, "prism"))[0]
    negatives = point_negatives(run, "top")
    with providers.job_context(run.job.id, run.job.emit, ctx=run.job.ctx):
        feats = measure(img, mo.detection, mo.pose, points, seg, thickness_mm=height, part_mask=mo.photo_mask,
                        mask_source=point_mask_source(), negatives_px=negatives)  # fmt: skip
    quality = [
        _quality_of(h.diameter.evidence.note if h.diameter.evidence else None, h.diameter.value / 2) for h in top.holes
    ]
    holes, notes = merge(top, quality, feats)
    ok = [f for f in feats if f.ok]
    for n in notes:
        run.log(f"points: {n}")
    for f in feats:
        if not f.ok:
            run.log(f"point {f.id} ({f.point_source}): " + ("retake: " if f.retake else "") + f"{f.reason}", "warn")
    if holes != list(top.holes):
        top.holes = holes
        run.save_measurements()
    run.log(f"points: {len(ok)}/{len(feats)} pointed features measured by point-prompted segmentation")


def measure_points(run: FixRun, view: str, points_px: Sequence[Sequence[float]]) -> list[dict[str, Any]]:
    """Agent tool backend: measure features at the given photo pixels (holes), nothing committed."""
    seg = getattr(providers, "segment_points", None)
    measure = _optional("services.metrology.points", "measure_features_from_points")
    FeaturePoint = _optional("services.metrology.points", "FeaturePoint")
    mo = run.mo.get(view)
    if seg is None or measure is None or FeaturePoint is None or mo is None or mo.detection is None:
        return [{"ok": False, "reason": "point segmentation is not available in this build"}]
    from services.metrology.measure import decode_image

    pts = [FeaturePoint(f"pt_{i}", "hole", (float(p[0]), float(p[1])), "model") for i, p in enumerate(points_px, 1)]
    height = run.heights.get(view, (None, "prism"))[0]
    negatives = point_negatives(run, view)
    with providers.job_context(run.job.id, run.job.emit, ctx=run.job.ctx):
        feats = measure(decode_image(run.photos[view]), mo.detection, mo.pose, pts, seg, thickness_mm=height,
                        part_mask=mo.photo_mask, mask_source=point_mask_source(), negatives_px=negatives)  # fmt: skip
    return [
        {"id": f.id, "ok": f.ok, "kind": f.kind, "method": f.method, "center_mat_mm": f.center_mm,
         "values_mm": {k: v.value for k, v in f.values.items()},
         "sigma_mm": {k: v.sigma_mm for k, v in f.values.items()}, "confidence": f.confidence,
         "retake": f.retake, "reason": f.reason}
        for f in feats
    ]  # fmt: skip


# ------------------------------------------------------------------------------------------------- orbit


def apply_orbit(run: FixRun) -> None:
    """Orbit clip -> calibrated frames for the verifier + the visual-hull height (measured, evidence "orbit")."""
    if "orbit" not in run.photos:
        return
    fn = _optional("services.metrology.orbit", "measure_orbit")
    if fn is None:
        run.log("orbit clip stored; orbit measurement is not available in this build", "warn")
        return
    from services.metrology.segment import ThresholdSegmenter

    mime = blobs.content_type(run.photo_shas["orbit"])
    seg_video = getattr(providers, "segment_video", None)

    def call(video: bytes, mime_: str, prompt: str, fps: float) -> Any:
        assert seg_video is not None
        return seg_video(video, mime_, prompt, fps=fps)

    try:
        with providers.job_context(run.job.id, run.job.emit, ctx=run.job.ctx):
            out = fn(run.photos["orbit"], call if seg_video is not None else None, mime=mime,
                     segmenter=ThresholdSegmenter())  # fmt: skip
    except Exception as exc:  # a bad clip costs the orbit evidence, not the job
        run.log(f"orbit clip not usable ({type(exc).__name__}: {exc})", "warn")
        return
    frames = list(_get(out, "frames", default=[]) or [])
    run.orbit_footprint = _get(out, "footprint_mat")
    p2m = _get(out, "part_to_mat")
    if p2m is not None:
        from services.verifier.camera import CameraView

        for f in frames:
            try:
                run.orbit_views.append(CameraView(**f.camera_view_kwargs(np.asarray(p2m, dtype=np.float64))))
            except (TypeError, AttributeError):
                continue
    height = _get(out, "max_height")
    for n in _get(out, "notes", default=[]) or []:
        run.log(f"orbit: {n}")
    if isinstance(height, Measured):
        run.orbit_height = Measured(
            value=height.value, source=Source.measured, sigma_mm=height.sigma_mm,
            evidence=Evidence(view="orbit", note=(height.evidence.note if height.evidence and height.evidence.note
                                                  else f"orbit: visual-hull height from {len(frames)} frames")),
        )  # fmt: skip
    rejected = _get(out, "rejected", default={}) or {}
    run.log(
        f"orbit: {len(frames)} usable frame(s) of {_get(out, 'n_sampled', default='?')} sampled"
        + (f" (dropped: {', '.join(f'{k} ×{v}' for k, v in rejected.items())})" if rejected else "")
        + (f"; visual-hull height {run.orbit_height.value:.2f} mm (measured)" if run.orbit_height else "; no height")
    )


# ------------------------------------------------------------------------------------------------- narration

AUDIO_MIMES = {".wav": "audio/wav", ".ogg": "audio/ogg", ".mp3": "audio/mpeg", ".m4a": "audio/mp4",
               ".webm": "audio/webm", ".flac": "audio/flac", ".aac": "audio/aac"}  # fmt: skip


def apply_narration(run: FixRun) -> str | None:
    """Narrated walk-around: Muse Spark watches/hears the clip (and reads a voice note) and points at features; code
    checks every point on its decoded frame and measures the kept ones with SAM point prompts. The narration's words
    steer the understand stage; it never sets a number. Returns a short label for the measure stage (or None)."""
    clip = run.photos.get("orbit")
    if clip is None:
        return None
    from services.agent.providers import vision
    from services.metrology import narration as N

    voice = run.photos.get("narration")
    if voice is None and not N.has_audio_track(clip):
        run.log("walk-around: no sound and no voice note, so there is no narration to follow")
        return None
    clip_key = run.photo_shas["orbit"]
    mime = blobs.content_type(clip_key)
    suffix = "." + clip_key.rsplit(".", 1)[-1] if "." in clip_key else ".mp4"
    try:
        w, h, fps, n = vision.probe_video(clip, suffix)
    except ValueError as exc:
        run.log(f"narration skipped: the clip could not be decoded ({exc})", "warn")
        return None
    voice_note = None
    if voice is not None:
        vkey = run.photo_shas["narration"]
        voice_note = (voice, AUDIO_MIMES.get("." + vkey.rsplit(".", 1)[-1], "audio/wav"))
    try:
        with providers.job_context(run.job.id, run.job.emit, ctx=run.job.ctx):
            nar = providers.narrate_video(clip, mime, width=w, height=h, duration_s=n / fps if fps > 0 else 0.0,
                                          intent=run.job.input.intent, voice_note=voice_note)  # fmt: skip
    except Exception as exc:  # narration is optional evidence: never fail the job over it
        run.log(f"narration skipped: {type(exc).__name__}: {exc}", "warn")
        return None
    run.narration = nar
    pts = [N.NarratedPoint(str(f["name"]), f["kind"], float(f["t_s"]), float(f["x_px"]), float(f["y_px"]),
                           str(f.get("said", ""))) for f in nar.features]  # fmt: skip
    mo, top = run.mo.get("top"), run.measurements.get("top")
    height = run.heights.get("top", (None, "prism"))[0]
    top_fp = mo.footprint_mat if mo is not None else None
    clip_fp = getattr(run, "orbit_footprint", None)
    # The part may have been moved between the photo and the clip: points are checked against the clip's own
    # footprint when the walk-around measured one, and merged into the top view only when both footprints coincide.
    same_place = clip_fp is None or (top_fp is not None and N.same_placement(top_fp, clip_fp))
    checks, frames = N.locate_points(clip, pts, footprint_mat=clip_fp if clip_fp is not None else top_fp,
                                     thickness_mm=height, suffix=suffix)  # fmt: skip
    feats: list[Any] = []
    seg = getattr(providers, "segment_points", None)
    if frames and seg is not None:
        with providers.job_context(run.job.id, run.job.emit, ctx=run.job.ctx):
            feats = N.measure_located(frames, seg, thickness_mm=height, mask_source=point_mask_source())
    for c in checks:
        if not c.ok:
            run.log(f"narrated point {c.point.name!r} dropped: {c.reason}", "warn")
    merged: list[str] = []
    merge = _optional("services.metrology.points", "merge_holes")
    holes_found = any(f.ok and f.kind == "hole" for f in feats)
    if holes_found and not same_place:
        run.log("narration: the part was moved between the top photo and the clip, so narrated holes are measured on "
                "the clip and reported, not merged into the top view")  # fmt: skip
    if top is not None and merge is not None and holes_found and same_place:
        quality = [_quality_of(hh.diameter.evidence.note if hh.diameter.evidence else None, hh.diameter.value / 2)
                   for hh in top.holes]  # fmt: skip
        holes, notes = merge(top, quality, feats)
        merged = [f"{x} ({N.NARRATION_NOTE})" for x in notes]
        if holes != list(top.holes):
            top.holes = holes
            run.save_measurements()
    for x in merged:
        run.log(f"narration: {x}")
    for f in feats:
        vals = ", ".join(f"{k} {v.value:.2f} mm" for k, v in f.values.items())
        run.log(f"narrated {f.kind} {f.id!r}: " + (f"measured {vals} ({N.NARRATION_NOTE})" if f.ok else
                                                   f"not measured: {f.reason}"))  # fmt: skip
    record = {
        "narration": nar.to_dict(),
        "points": [c.to_dict() for c in checks],
        "measured": [
            {
                "id": f.id,
                "kind": f.kind,
                "ok": f.ok,
                "method": f.method,
                "center_mat_mm": f.center_mm,
                "values_mm": {k: v.value for k, v in f.values.items()},
                "reason": f.reason,
                "provenance": N.NARRATION_NOTE,
            }
            for f in feats
        ],
        "merged": merged,
        "same_placement": same_place,
    }
    run.job.write_json("narration.json", record)
    label = f"walk-around narration ({nar.label})"
    emit_artifact(run, "narration", json.dumps(record, indent=1).encode(), ".json", label)
    ok = sum(c.ok for c in checks)
    measured = sum(f.ok for f in feats)
    return f"narration: {ok}/{len(checks)} pointed feature(s) kept, {measured} measured ({nar.mode})"


# ------------------------------------------------------------------------------------------------- cited specs


def appliance_in(intent: str) -> str | None:
    """A make/model token in the user's words (e.g. 'Prestige PIC20', 'LG-T70SNSF'), else None."""
    m = _MODEL_RE.search(intent or "")
    return m.group(1) if m else None


def lookup_specs(run: FixRun) -> None:
    """Resolve unknowns from a cited source when the user named the appliance. Cited values never override measured
    ones (a disagreement of more than CONFLICT_MM is logged); what is not found stays a question for the human."""
    fn = getattr(providers, "lookup_spec", None)
    spec = run.spec
    if fn is None or spec is None or not spec.unknowns:
        return
    model = appliance_in(run.job.input.intent)
    if model is None:
        return
    wanted = [u.id for u in spec.unknowns if u.expects == "number_mm"]
    if not wanted:
        return
    query = f"{model} {spec.family.value} replacement part dimensions"
    try:
        with providers.job_context(run.job.id, run.job.emit, ctx=run.job.ctx):
            out = fn(query, wanted)
    except Exception as exc:  # a failed lookup leaves the questions for the human
        run.log(f"spec lookup failed ({type(exc).__name__}: {exc}); asking the human instead", "warn")
        return
    items = _get(out, "values", "items", "results", default=out if isinstance(out, list) else []) or []
    for it in items:
        uid = str(_get(it, "id", "name", default=""))
        value = _get(it, "value_mm", "value")
        cit = _get(it, "citation", default={}) or {}
        url = str(_get(cit, "url", default="") or _get(it, "url", default="") or "")
        if not uid or value is None or not url:
            continue  # uncited values are ignored
        citation = Citation(
            url=url, title=str(_get(cit, "title", default="") or ""), quote=str(_get(cit, "quote", default="") or "")
        )
        accept_cited(run, uid, float(value), citation)


def accept_cited(run: FixRun, uid: str, value: float, citation: Citation) -> bool:
    """Apply one cited value to an unknown. Returns False when a measured value already exists (conflict logged)."""
    spec = run.spec
    assert spec is not None
    measured = _measured_value(run, uid)
    if measured is not None:
        if abs(measured - value) > CONFLICT_MM:
            run.log(f"cited {uid} = {value:.2f} mm ({citation.url}) disagrees with the measured {measured:.2f} mm by "
                    f"{abs(measured - value):.2f} mm; the measured value stands", "warn")  # fmt: skip
        return False
    cited = Measured(value=value, source=Source.cited, sigma_mm=0.2,
                     evidence=Evidence(note=f"cited for {run.job.input.intent[:60]!r}", citation=citation))  # fmt: skip
    fid, _, attr = uid.partition(".")
    done = False
    if uid == "thickness":
        if spec.thickness.source in (Source.measured, Source.user_stated):
            return False
        spec.thickness = cited
        done = True
    else:
        for f in spec.features:
            cur = getattr(f, attr or "diameter", None)
            if f.id == fid and isinstance(cur, Measured):
                if cur.source in (Source.measured, Source.user_stated):
                    return False
                setattr(f, attr or "diameter", cited)
                done = True
    run.answers[uid] = value
    spec.unknowns = [u for u in spec.unknowns if u.id != uid]
    run.log(f"cited {uid} = {value:.2f} mm from {citation.title or citation.url}" + ("" if done else " (as an answer)"))
    return True


def _measured_value(run: FixRun, uid: str) -> float | None:
    top = run.measurements.get("top")
    if uid == "thickness":
        for m in run.measurements.values():
            if m.thickness is not None and m.thickness.source == Source.measured:
                return float(m.thickness.value)
        return None
    fid, _, attr = uid.partition(".")
    if top is not None and (attr or "diameter") == "diameter":
        for h in top.holes:
            if h.id == fid:
                return float(h.diameter.value)
    return None


# ------------------------------------------------------------------------------------------------- broken parts


MIRROR_CROSS_MIN_IOU = 0.8  # the outline must still be this symmetric about the cross axis to be mirrored about it too
MIRROR_SNAP_DEG = 2.0  # a symmetry axis this close to a part-frame axis is that axis (the break tilts the estimate)


def _mirror(poly: Any, axis_deg: float) -> Any:
    from shapely.affinity import rotate, scale

    return rotate(scale(rotate(poly, -axis_deg, origin=(0, 0)), 1.0, -1.0, origin=(0, 0)), axis_deg, origin=(0, 0))


def mirror_completion(outline: Sequence[Sequence[float]], axis_deg: float | None) -> list[tuple[float, float]] | None:
    """Union of the outline and its mirror images (part frame, axes through the origin).

    Always mirrored about the measured symmetry axis (snapped to the part frame's axis when within
    ``MIRROR_SNAP_DEG``: a tilted mirror adds slivers along every edge). Also about the axis across it when the outline is still nearly
    symmetric about that one (mirror IoU >= ``MIRROR_CROSS_MIN_IOU``): a piece missing from the middle of an end is
    its own mirror image about the long axis, so only the end-to-end mirror can restore it."""
    from shapely.geometry import Polygon

    if axis_deg is None or len(outline) < 3:
        return None
    poly = Polygon(outline).buffer(0)
    snap = round(axis_deg / 90.0) * 90.0
    if abs(axis_deg - snap) <= MIRROR_SNAP_DEG:
        axis_deg = snap
    u = poly.union(_mirror(poly, axis_deg))
    cross = _mirror(poly, axis_deg + 90.0)
    inter = poly.intersection(cross).area
    if inter / max(poly.area * 2 - inter, 1e-9) >= MIRROR_CROSS_MIN_IOU:
        u = u.union(cross)
    if u.geom_type != "Polygon":
        return None
    return [(round(x, 3), round(y, 3)) for x, y in list(u.exterior.coords)[:-1]]


def propose_completion(run: FixRun) -> None:
    """Broken region: (a) mirror completion by code; (b) a Muse Image proposal on the rectified photo, used only when
    the code gate accepts it. Accepted completions enter as inferred; each proposal leaves a labelled artifact."""
    spec, top = run.spec, run.measurements.get("top")
    if spec is None or top is None or spec.broken_region is None:
        return
    br = spec.broken_region
    if br.kind != "outline":  # a missing top: the verifier takes the break height from the side photo
        return
    completed = mirror_completion(top.outline_mm, top.symmetry_axis_deg)
    if completed is not None:
        br.polygon_mm = [(float(p[0]), float(p[1])) for p in completed]
        br.note = (br.note or "") + " · mirror completion about the measured symmetry axis (code)"
        png = _outline_png(top.outline_mm, completed)
        run.artifact("reconstruction", png, ".png", "mirror completion (code): inferred, not measured")
    gen = getattr(providers, "reconstruct", None)
    gate = _optional("services.metrology.recon_gate", "gate_reconstruction")
    mo = run.mo.get("top")
    if gen is None or mo is None or mo.detection is None or mo.footprint_mat is None or "top" not in run.photos:
        return
    if gate is None:
        run.log("Muse Image completion skipped: no code gate in this build (an ungated proposal is never used)", "warn")
        return
    from services.metrology.calibrate import rectify
    from services.metrology.measure import _rasterize, decode_image

    det = mo.detection
    rect = rectify(decode_image(run.photos["top"]), det.H, RECON_PX_PER_MM, det.mat.bounds, K=det.K, dist=det.dist)
    part = _rasterize(mo.footprint_mat, rect.origin_mm, RECON_PX_PER_MM, rect.image.shape[:2])
    near = cv2.dilate(part.astype(np.uint8), np.ones((int(15 * RECON_PX_PER_MM) | 1,) * 2, np.uint8)) > 0
    keep = ~(near & ~part)  # the model may only add material next to the part; markers and the rest stay identical
    ok_k, keep_png = cv2.imencode(".png", (keep * 255).astype(np.uint8))
    ok_r, rect_png = cv2.imencode(".png", rect.image)
    try:
        with providers.job_context(run.job.id, run.job.emit, ctx=run.job.ctx):
            img = gen(bytes(rect_png.tobytes()), bytes(keep_png.tobytes()), f"complete the broken {spec.family.value}")
    except Exception as exc:
        run.log(f"Muse Image completion unavailable ({type(exc).__name__}: {exc})", "warn")
        return
    data = _get(img, "data", default=img)
    if not isinstance(data, (bytes, bytearray)) or not (ok_k and ok_r):
        run.log("Muse Image returned no image; no completion", "warn")
        return
    verdict = gate(rect, decode_image(bytes(data)), part, det.mat)
    accepted = bool(_get(verdict, "ok", "accepted", default=False))
    markers = _get(verdict, "marker_shift_px", "markers_px")
    iou = _get(verdict, "intact_iou", "iou")
    why = str(_get(verdict, "reason", default="") or "")
    nums = ", ".join(x for x in (f"markers {float(markers):.1f} px" if markers is not None else "",
                                 f"intact IoU {float(iou):.3f}" if iou is not None else "") if x)  # fmt: skip
    mode = str(_get(img, "mode", default=""))
    tag = " (mock)" if mode == "mock" else ""
    if accepted:
        label = f"Muse Image proposal{tag}, accepted by code gate: {nums}"
        outlines = _get(verdict, "completion_outline_mm", default=[]) or []
        if outlines and top.part_to_mat:
            Mi = np.linalg.inv(np.asarray(top.part_to_mat, dtype=np.float64))
            ring = np.asarray(outlines[0], dtype=np.float64)
            pp = ring @ Mi[:2, :2].T + Mi[:2, 2]
            br.polygon_mm = [(round(float(x), 3), round(float(y), 3)) for x, y in pp]
        run.completion_accepted = True
        if outlines and mode != "mock":
            add_completion_to_masks(run, outlines)
        elif outlines:
            run.log("mock completion: recorded as an artifact only, never added to the compared silhouette")
    else:
        label = f"Muse Image proposal{tag}, rejected by code gate: {why or nums or 'failed the checks'}"
    run.artifact("reconstruction", bytes(data), ".png", label)
    run.log(label, "info" if accepted else "warn")


def add_completion_to_masks(run: FixRun, outlines_mat: Sequence[Sequence[Sequence[float]]]) -> None:
    """An accepted completion (mat frame) joins the silhouette the model is compared with: the rectified photo mask and
    the full-frame mask/field of the top photo. Labelled inferred in the trace; the measurements stay as measured."""
    from services.verifier.render import rasterize_polygon
    from services.verifier.verify import PhotoMask

    top, mo = run.measurements.get("top"), run.mo.get("top")
    if top is None or mo is None or mo.detection is None or not top.part_to_mat:
        return
    Mi = np.linalg.inv(np.asarray(top.part_to_mat, dtype=np.float64))
    pm = run.masks.get("top")
    full = np.zeros(mo.photo_mask.shape[:2], np.uint8) if mo.photo_mask is not None else None
    for ring in outlines_mat:
        r = np.asarray(ring, dtype=np.float64)[:, :2]
        if len(r) < 3:
            continue
        if pm is not None:
            part = r @ Mi[:2, :2].T + Mi[:2, 2]
            pm = PhotoMask(pm.mask | rasterize_polygon(part, [], pm.frame), pm.frame)
        if full is not None:
            px = mo.detection.to_px(r)
            cv2.fillPoly(full, [np.round(px * 16).astype(np.int32)], 1, cv2.LINE_8, shift=4)
    if pm is not None:
        run.masks["top"] = pm
    if full is not None and mo.photo_mask is not None:
        add = full > 0
        mo.photo_mask = mo.photo_mask | add
        if mo.photo_field is not None:
            mo.photo_field = np.maximum(mo.photo_field, add.astype(np.float32))
    run.log("the accepted completion (inferred) is part of the silhouette the model is compared with")


def _outline_png(original: Sequence[Sequence[float]], completed: Sequence[Sequence[float]], ppm: float = 8.0) -> bytes:
    pts = np.asarray(list(original) + list(completed), dtype=np.float64)
    lo, hi = pts.min(axis=0) - 3, pts.max(axis=0) + 3
    w, h = (int((hi - lo)[0] * ppm) + 1, int((hi - lo)[1] * ppm) + 1)
    img = np.full((h, w, 3), 255, np.uint8)

    def px(p: Sequence[Sequence[float]]) -> np.ndarray[Any, Any]:
        a = (np.asarray(p, dtype=np.float64) - lo) * ppm
        return np.asarray(np.c_[a[:, 0], h - a[:, 1]], dtype=np.int32)

    cv2.fillPoly(img, [px(completed)], (235, 200, 150))
    cv2.fillPoly(img, [px(original)], (150, 150, 150))
    ok, buf = cv2.imencode(".png", img)
    return bytes(buf.tobytes()) if ok else b""


# ------------------------------------------------------------------------------------------------- judge crops


def hotspot_crops(rnd: Round, half_mm: float = 6.0, max_crops: int = 2) -> list[bytes]:
    """Photo | model crops around each failing view's worst point (rectified frame), side by side, for the judge."""
    out: list[bytes] = []
    if rnd.out is None:
        return out
    for vr in sorted(rnd.out.views.values(), key=lambda v: -v.metrics.hausdorff_mm)[:max_crops]:
        wp = vr.metrics.worst_point_mm
        if wp is None:
            continue
        fr = vr.photo.frame
        c = fr.to_px(np.asarray(wp, dtype=np.float64))
        r = int(half_mm * fr.px_per_mm)
        x0, y0 = max(int(c[0]) - r, 0), max(int(c[1]) - r, 0)
        x1, y1 = x0 + 2 * r, y0 + 2 * r
        p = vr.photo.mask[y0:y1, x0:x1]
        m = vr.model_mask[y0:y1, x0:x1]
        if p.size == 0 or m.size == 0 or p.shape != m.shape:
            continue
        pane = np.full((p.shape[0], p.shape[1] * 2 + 4, 3), 255, np.uint8)
        pane[:, : p.shape[1]][p] = (60, 60, 60)
        pane[:, p.shape[1] + 4 :][m] = (200, 120, 40)
        ok, buf = cv2.imencode(".png", pane)
        if ok:
            out.append(bytes(buf.tobytes()))
    return out


# ------------------------------------------------------------------------------------------------- package extras


BUNDLE_KINDS = {"stl": ".stl", "step": ".step", "threemf": ".3mf", "code": ".py", "template_pdf": ".pdf",
                "repair_card": ".pdf", "coupon": ".stl"}  # fmt: skip


def zip_bundle(run: FixRun) -> bytes:
    """Everything a maker needs in one file: model files, part.py, templates, cards and the verification record."""
    latest: dict[str, str] = {}
    for e in run.job.events:
        if e.t == "artifact" and e.kind in BUNDLE_KINDS and e.iter is None:
            latest[e.kind] = e.sha
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for kind, key in sorted(latest.items()):
            name = {"code": "part.py", "threemf": "part.3mf", "template_pdf": "template_1to1.pdf",
                    "repair_card": "repair_card.pdf", "coupon": "fit_test_coupon.stl"}.get(kind, f"part{BUNDLE_KINDS[kind]}")  # fmt: skip
            z.writestr(name, blobs.get(key))
        for side in ("verification.json", "partspec.json", "measurements.json", "values.json"):
            data = run.job.read_text(side)
            if data:
                z.writestr(side, data)
        z.writestr(
            "README.txt", f"PartSmith job {run.job.id}. Units: millimetres. Origin: {run.job.input.origin.value}.\n"
        )
    return buf.getvalue()


def ship_decision(run: FixRun, verification: Any) -> dict[str, Any]:
    can_ship: Callable[..., Any] | None = _optional("services.verifier.ship", "can_ship")
    if can_ship is None:
        return {
            "ok": bool(verification and verification.verified),
            "reason": "ship gate not available",
            "requires_ack": False,
        }
    d = can_ship(verification, job_status="done")
    return dict(d.to_dict()) if hasattr(d, "to_dict") else {"ok": bool(_get(d, "ok")), "reason": str(_get(d, "reason"))}


INSTALL_STEPS = (
    "Take out the broken part and clean the mounting spot",
    "Fit the printed replacement part in the same place",
    "Check that it moves and holds like the original",
)


def install_card(run: FixRun) -> bool:
    """Anchored 3-panel install card (Muse Image; labelled mock without a key) in the user's own scene."""
    fn = getattr(providers, "install_card", None)
    b = run.best
    if fn is None or b is None or b.out is None or "top" not in b.out.views or "top" not in run.photos:
        return False
    from services.agent.orchestrator import fit_png, mask_png

    render = mask_png(b.out.views["top"].model_mask, (70, 140, 230))
    photo, _ = fit_png(run.photos["top"], 1536)
    with providers.job_context(run.job.id, run.job.emit, ctx=run.job.ctx):
        panels = fn(photo, render, list(INSTALL_STEPS))
    n = 0
    for i, res in enumerate(panels, start=1):
        data = _get(res, "data", default=None)
        if isinstance(data, (bytes, bytearray)):
            mode = str(_get(res, "mode", default=""))
            run.artifact("install_card", bytes(data), ".png",
                         f"install card {i}/{len(panels)}: {INSTALL_STEPS[i - 1] if i <= 3 else ''}"
                         + (" (mock)" if mode == "mock" else ""))  # fmt: skip
            n += 1
    return n > 0


def emit_artifact(run: FixRun, kind: str, data: bytes, ext: str, label: str) -> None:
    key = blobs.put(data, ext)
    run.job.emit(ArtifactEvent(job=run.job.id, kind=kind, sha=key, url=blobs.url(key), label=label))


__all__ = [
    "accept_cited",
    "appliance_in",
    "apply_narration",
    "apply_orbit",
    "apply_points",
    "feature_points",
    "hotspot_crops",
    "install_card",
    "lookup_specs",
    "measure_points",
    "mirror_completion",
    "propose_completion",
    "ship_decision",
    "zip_bundle",
]
