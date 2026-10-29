"""The fix job's "where it fits" photo: measure the mate in the measure stage, check the fit in the final verdict.

1. Measure (measure stage): the mating photo passed the capture gate in the capture stage. The user's taps on it
   (`points.json` {"mating": [{"x", "y", "kind": mate_hole|mate_peg|mate_slot|exclude}]}) say where the mate is;
   without taps, Spark points at it (`mate_points`, strict JSON, pixels only; deterministic labelled mock without a
   key). Each point is cut by a SAM point prompt and measured by code (`services/metrology/mate.py`).
2. Check (final verdict): `services/verifier/mate_fit.py` pairs each mate with the model's matching feature, measured
   on the CAD solid, classifies the clearance and adds P1 tests "fits where it goes" plus one plain-words reason line.
   `verified` is never touched; a "does not fit" shows up in the export gate's reason as a warning.

Everything lands in `mate_fit.json` (and the `mate_fit` / `mate_overlay` artifacts). No mating photo: nothing runs and
nothing changes.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Any, Literal, cast

import numpy as np
from partsmith_schemas import ArtifactEvent
from partsmith_schemas.measurement import CaptureReport, MateKind, MateMeasurement
from partsmith_schemas.verification import MateFitResult, Verification

from services.agent import providers
from services.agent.providers import ModelRequest, ProviderError
from services.common import blobs

if TYPE_CHECKING:
    from services.agent.orchestrator import FixRun, Round

MATE_KINDS: tuple[MateKind, ...] = ("mate_hole", "mate_peg", "mate_slot")
MAX_MODEL_POINTS = 3
MODEL_IMAGE_PX = 1536
DEFAULT_PRESET = "pla-fdm-0.4"

MATE_POINTS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["mates", "notes"],
    "properties": {
        "mates": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["kind", "x_px", "y_px", "what"],
                "properties": {
                    "kind": {"type": "string", "enum": list(MATE_KINDS)},
                    "x_px": {"type": "number"},
                    "y_px": {"type": "number"},
                    "what": {"type": "string"},
                },
            },
        },
        "notes": {"type": "string"},
    },
}

MATE_POINTS_PROMPT = """The photo shows where a broken plastic part fits, lying on a printed calibration mat: the
socket or bore the part goes INTO (kind "mate_hole"), the shaft, axle or pin it goes ONTO ("mate_peg"), or the slot or
panel edge it clips into or onto ("mate_slot"). The person said: {intent}
Point at the mating feature: for each one give its kind and x_px, y_px, the pixel at its centre (inside the socket's
opening, on the shaft, inside the slot or on the panel's edge) in this image ({w} x {h} px, origin top-left), and in
"what" a few words naming it. At most {n}. Never estimate a size: code measures everything. If no mating feature is
visible, return an empty list."""

_KIND_WORDS: tuple[tuple[MateKind, re.Pattern[str]], ...] = (
    ("mate_peg", re.compile(r"\b(shaft|axle|pin|peg|rod|spindle|stud|post|bolt|cable|onto)\b", re.I)),
    ("mate_slot", re.compile(r"\b(slot|panel|edge|rail|sheet|board|shelf|door|clips?|clamps?)\b", re.I)),
    ("mate_hole", re.compile(r"\b(socket|bore|hole|recess|cup|into)\b", re.I)),
)


def kind_hint(intent: str) -> MateKind | None:
    """The mate kind the user's words suggest (the first family of words found), or None."""
    for kind, pat in _KIND_WORDS:
        if pat.search(intent or ""):
            return kind
    return None


def mate_taps(run: FixRun) -> list[dict[str, Any]]:
    """The user's taps on the mating photo (`points.json` in the run dir, or RunOptions.points), photo pixels."""
    taps: dict[str, Any] = dict(run.opts.points or {})
    saved = run.job.read_json("points.json")
    if isinstance(saved, Mapping):
        taps.update(saved)
    return [dict(t) for t in taps.get("mating") or [] if isinstance(t, Mapping) and "x" in t and "y" in t]


def _emit(run: FixRun, kind: str, data: bytes, ext: str, label: str) -> str:
    key = blobs.put(data, ext)
    run.job.emit(ArtifactEvent(job=run.job.id, kind=kind, sha=key, url=blobs.url(key), label=label))
    return key


def _on_stage(det: Any, px: tuple[float, float], size: tuple[int, int]) -> bool:
    w, h = size
    if not (0 <= px[0] < w and 0 <= px[1] < h):
        return False
    mm = det.to_mm(np.array([px], dtype=np.float64))[0]
    st = det.mat.stage
    return bool(st.x_mm <= mm[0] <= st.x2_mm and st.y_mm <= mm[1] <= st.y2_mm)


def model_points(run: FixRun, img: Any, det: Any) -> tuple[list[Any], list[str]]:
    """Spark points at the mating feature (pixels only). Each point is kept only when it falls on the mat's stage in
    the photo; the mock is the code's own pick (`propose_mates`), labelled."""
    from services.agent.orchestrator import fit_png
    from services.metrology.mate import MOCK_POINT_LABEL, MatePoint, propose_mates

    notes: list[str] = []
    hint = kind_hint(run.job.input.intent)
    cands = propose_mates(img, det, hint)
    png, scale = fit_png(run.photos["mating"], MODEL_IMAGE_PX)
    h, w = img.shape[:2]
    req = ModelRequest(
        messages=[
            {"role": "developer", "content": MATE_POINTS_PROMPT.format(
                intent=run.job.input.intent or "(nothing)", w=round(w * scale), h=round(h * scale),
                n=MAX_MODEL_POINTS)},
            {"role": "user", "content": "Mating photo attached."},
        ],
        images=[png],
        json_schema=MATE_POINTS_SCHEMA,
        schema_name="mate_points",
        mock_context={"candidates": [{"kind": c.kind, "x_px": c.px[0] * scale, "y_px": c.px[1] * scale,
                                      "what": MOCK_POINT_LABEL} for c in cands]},
    )  # fmt: skip
    try:
        out = run.call("mate_points", req)
    except ProviderError as exc:
        notes.append(f"mate pointer unavailable ({exc}); tap the mating feature on the photo")
        return [], notes
    data = (out.json if out else None) or {}
    mode = out.mode if out is not None else "mock"
    pts: list[Any] = []
    for i, m in enumerate(list(data.get("mates") or [])[:MAX_MODEL_POINTS], start=1):
        try:
            kind = str(m["kind"])
            px = (float(m["x_px"]) / scale, float(m["y_px"]) / scale)
        except (KeyError, TypeError, ValueError):
            notes.append(f"mate point {i}: malformed, dropped")
            continue
        if kind not in MATE_KINDS:
            notes.append(f"mate point {i}: unknown kind {kind!r}, dropped")
            continue
        if not _on_stage(det, px, (w, h)):
            notes.append(f"mate point {i} at ({px[0]:.0f}, {px[1]:.0f}) px is off the mat's stage, dropped")
            continue
        src: Literal["model", "mock"] = "mock" if mode == "mock" else "model"
        pts.append(MatePoint(f"mate_{len(pts) + 1}", kind, px, src))
    if mode == "mock":
        notes.append(MOCK_POINT_LABEL)
    return pts, notes


def measure(run: FixRun) -> str | None:
    """Measure the mating photo's mates (measure stage). Returns a label for the stage line, or None."""
    from services.agent import evidence
    from services.metrology.calibrate import MatNotFoundError, detect_mat, estimate_pose, exif_focal35_mm
    from services.metrology.mate import MatePoint, mate_overlay, measure_mates
    from services.metrology.measure import decode_image

    notes: list[str] = []
    cap: CaptureReport | None = run.mate_capture
    if "mating" not in run.photos:
        if cap is None:
            return None
        res = MateFitResult(capture=cap, notes=[f"mating photo not usable: {cap.retake_reason}"],
                            origin=run.job.input.origin)  # fmt: skip
        run.mate_result = res
        run.job.write_json("mate_fit.json", res)
        return "mating photo not usable"
    raw = run.photos["mating"]
    img = decode_image(raw)
    try:
        det = detect_mat(img, mat_id=run.opts.mat_id)
    except MatNotFoundError as exc:
        run.log(f"mating photo: {exc}", "warn")
        return None
    try:
        pose = estimate_pose(det, focal35_mm=exif_focal35_mm(raw))
    except MatNotFoundError:
        pose = None
    taps = mate_taps(run)
    points = [MatePoint(str(t.get("id") or f"mate_{i}"), cast(MateKind, t["kind"]), (float(t["x"]), float(t["y"])),
                        "user") for i, t in enumerate(taps, start=1) if t.get("kind") in MATE_KINDS]  # fmt: skip
    negatives = [(float(t["x"]), float(t["y"])) for t in taps if t.get("kind") == "exclude"]
    if not points:
        points, more = model_points(run, img, det)
        notes += more
    if not points:
        notes.append("no mating feature to measure: tap the socket, shaft or slot on the mating photo")
    seg = getattr(providers, "segment_points", None)
    mates: list[MateMeasurement] = []
    if points and seg is not None:
        with providers.job_context(run.job.id, run.job.emit, ctx=run.job.ctx):
            mates = measure_mates(img, det, pose, points, seg, mask_source=evidence.point_mask_source(),
                                  negatives_px=negatives)  # fmt: skip
        _emit(run, "mate_overlay", mate_overlay(img, det, mates), ".png", "mating photo: measured mate(s)")
    for m in mates:
        if not m.ok:
            run.log(f"mate {m.id} ({m.point_source}): " + ("retake: " if m.retake else "") + f"{m.reason}", "warn")
    run.mate_result = MateFitResult(capture=cap, mates=mates, notes=notes, origin=run.job.input.origin)
    run.job.write_json("mate_fit.json", run.mate_result)
    ok = [m for m in mates if m.ok and m.size is not None]
    if not ok:
        return "mating: nothing measured" if mates or points else None
    return "mating: " + ", ".join(_mate_label(m) for m in ok)


def _mate_label(m: MateMeasurement) -> str:
    from services.metrology.mate import MATE_WORDS

    assert m.size is not None
    word = "panel edge" if m.kind == "mate_slot" and m.material == "material" else MATE_WORDS[m.kind].split(" or ")[0]
    sym = "Ø" if m.shape == "round" or m.kind == "mate_peg" else "w "
    return f"{word} {sym}{m.size.value:.2f} ± {m.size.sigma_mm:.2f} mm"


def preset_for(run: FixRun) -> str:
    """The fit preset matching the spec's material and printer (PLA on a 0.4 mm nozzle when nothing matches)."""
    from services.registry import presets

    if run.spec is None:
        return DEFAULT_PRESET
    f = run.spec.fit
    pid = (
        "resin-sla" if f.printer == "SLA" else f"{f.material.lower()}-fdm-{'0.6' if f.printer == 'FDM_0_6' else '0.4'}"
    )
    return pid if pid in presets.BY_ID else DEFAULT_PRESET


def printer_fit(preset_id: str, clearance_mm: float | None = None, source: str = "preset", label: str = "") -> Any:
    from services.registry import presets
    from services.verifier.mate_fit import PrinterFit

    p = presets.BY_ID[preset_id]
    c = p.delta_mm if clearance_mm is None else clearance_mm
    return PrinterFit(p.id, p.title, float(c), "learned" if source == "learned" else "preset", label)


def has_fit_knobs(code: str) -> bool:
    from services.geom_worker.program import ProgramError, parse_params
    from services.registry import presets

    try:
        return bool(presets.fit_knobs(parse_params(code)))
    except ProgramError:
        return False


def check(run: FixRun, v: Verification, b: Round) -> Verification:
    """Add "fits where it goes" to the final verdict (P1 tests + one reason line); `verified` is untouched."""
    from services.verifier.mate_fit import as_part_tests, check_fits, reason_line

    res = run.mate_result
    if res is None or not res.mates:
        return v
    feats = b.exec_result.features if b.exec_result is not None else None
    pid = preset_for(run)
    fits = check_fits(res.mates, feats, printer_fit(pid), has_fit_knobs=has_fit_knobs(b.code))
    res = res.model_copy(update={"fits": fits, "preset": pid})
    run.mate_result = res
    run.job.write_json("mate_fit.json", res)
    _emit(run, "mate_fit", res.model_dump_json(indent=2).encode(), ".json", "fits where it goes (mate_fit.json)")
    line = reason_line(fits)
    tests = [t for t in v.tests if not t.id.startswith("fit.mate.")] + as_part_tests(fits)
    reasons = [r for r in v.reasons if not r.startswith(("Fits where it goes", "Does not fit where it goes"))]
    if line:
        reasons.append(line)
        run.log(line, "warn" if any(not f.passed and f.clearance_mm is not None for f in fits) else "info")
    return v.model_copy(update={"tests": tests, "reasons": reasons})


def summary_label(res: MateFitResult | None) -> str:
    if res is None or not res.fits:
        return ""
    return "; ".join(f"{f.mate_id}: {f.fit or 'not checked'}" for f in res.fits)


def mate_points_mock(req: ModelRequest) -> dict[str, Any]:
    """Mock handler for `mate_points`: the code's own pick, handed in through mock_context (labelled)."""
    from services.metrology.mate import MOCK_POINT_LABEL

    cands: Sequence[Mapping[str, Any]] = req.mock_context.get("candidates") or []
    return {"mates": [dict(c) for c in cands][:MAX_MODEL_POINTS], "notes": MOCK_POINT_LABEL}
