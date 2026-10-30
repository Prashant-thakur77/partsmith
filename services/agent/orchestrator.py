"""The fix job (PLAN §3.2 Flow A, §6.2): photos on a mat → measured PartSpec → part program → verified loop → package.

    capture → measure → understand → ask → plan → build → execute → verify → fix (≤ max_iters) → judge → package → learn

`run_fix(job)` is the JobManager runner. Every stage emits `stage` events with a readable label; every model call goes
through `services/agent/providers` inside `job_context`, which emits `model_call` events (tokens, ms, $, mode). Each
event carries `ctx` = hash(photo shas, calibration, code, params): a model reply that comes back after the state moved
on is discarded. The model proposes; code decides: measured values override the model's, guards bound every edit, and
`verified` comes only from `services.verifier.verify`.
"""

from __future__ import annotations

import ast
import difflib
import json
import math
import re
import time
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import cv2
import numpy as np
from partsmith_schemas import (
    ArtifactEvent,
    DoneEvent,
    IterationEvent,
    JudgeScore,
    JudgeVeto,
    Measured,
    Measurements,
    MetricEvent,
    PartSpec,
    Pin,
    QuestionEvent,
    Source,
    StageEvent,
)
from partsmith_schemas.common import HAUSDORFF_PASS_MM, IOU_PASS, Evidence
from partsmith_schemas.measurement import CaptureReport
from partsmith_schemas.partspec import SlotFeature, ThroughHole, Unknown
from partsmith_schemas.verification import MateFitResult, Verification
from pydantic import ValidationError

from services.agent import guards, lessons, mock_brain, prompt_loader, providers, stated
from services.agent.jobs import Job, JobCancelled, QuestionTimeout, Runner, context_hash
from services.agent.providers import Completion, ModelRequest, ProviderError
from services.agent.templates import Template, get_template, knobs_at, list_templates
from services.common import blobs
from services.common.images import decode_bgr, exif_orientation
from services.geom_worker.program import ProgramError, clamp, code_sha, module_literals, parse_params, set_defaults
from services.geom_worker.sandbox import ExecResult, check_code, run_program
from services.metrology.calibrate import MatNotFoundError, detect_mat, estimate_pose
from services.metrology.capture_gate import run_gate
from services.metrology.measure import MeasureOutput, decode_image, measure_photo
from services.metrology.segment import ProviderSegmenter
from services.verifier.camera import CameraView
from services.verifier.part_tests import unchecked_values
from services.verifier.render import Frame, rasterize_polygon
from services.verifier.verify import MEAN_GATE_MM, BreakEnds, PhotoMask, VerifyOutput, break_ends, verify

Strategy = Literal["template", "free_code", "human"]
StageName = Literal[
    "capture", "measure", "understand", "ask", "plan", "build", "execute", "verify", "fix", "judge", "package", "learn"
]

DEFAULT_MAX_ITERS = 6
PHOTO_LIMITED_SUFFIX = ".height"  # verifier tests that another photo settles, never a model edit
# Part-mask checks that make the measurement itself unreliable: the job stops with the retake reason.
FATAL_PART_CHECKS = ("contrast", "coverage", "markers", "scale", "reprojection", "single_part")
ROUND_FAMILIES = ("wheel", "knob", "spacer")
HIDDEN_HOLE_RE = re.compile(r"possible hidden hole near mat \(([-\d.]+), ([-\d.]+)\) mm, about Ø([\d.]+) mm")
NOTE_KEYS = ("hidden hole", "taller than", "clearly above the stated", "not a round vertical hole")
BUILD_RETRIES = 2  # inner retries when the program does not compile / run
NO_IMPROVE_SWITCH = 3  # rounds without real progress before switching strategy
PROGRESS_EPS = 0.1  # rank units: a round must cut the pass-rule violation by this much to count as progress
IMPROVE_EPS_MM = 0.005
IMPROVE_EPS = 0.01  # rank units (multiples of a tolerance)
MISSING_TEST_PENALTY = 3.0  # a P0 test the model cannot even be measured for (e.g. a missing hole)
MASK_PX_PER_MM = 20.0
MODEL_IMAGE_MAX_PX = 1600
MIN_OPENING_MM2 = 2.0
HOLLOW_RATIO = 0.5  # free-code plate thickness below this share of the expected one, at full height: a hidden cavity

# ------------------------------------------------------------------------------------------------- JSON schemas

PLAN_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "strategy": {"type": "string", "enum": ["template", "free_code"]},
        "template": {"type": ["string", "null"]},
        "why": {"type": "string"},
    },
    "required": ["strategy", "template", "why"],
    "additionalProperties": False,
}

FIX_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "analysis": {"type": "string"},
        "edits": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "param": {"type": "string"},
                    "from": {"type": ["number", "null"]},
                    "to": {"type": "number"},
                    "reason": {"type": "string"},
                },
                "required": ["param", "from", "to", "reason"],
                "additionalProperties": False,
            },
        },
        "code_patch": {"type": ["string", "null"]},
    },
    "required": ["analysis", "edits", "code_patch"],
    "additionalProperties": False,
}

JUDGE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "vetoes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "feature": {"type": "string"},
                    "issue": {"type": "string"},
                    "severity": {"type": "string", "enum": ["blocking", "minor"]},
                },
                "required": ["feature", "issue", "severity"],
                "additionalProperties": False,
            },
        },
        # Bounds are checked by code (`parse_judge_reply`): one out-of-range score is dropped, not the whole reply.
        "scores": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "criterion": {"type": "string", "description": "outline | features | printability | fit"},
                    "score": {"type": "integer", "description": "1 = wrong, 3 = usable with fixes, 5 = matches"},
                    "reason": {"type": "string"},
                },
                "required": ["criterion", "score", "reason"],
                "additionalProperties": False,
            },
        },
        "notes": {"type": "string"},
    },
    "required": ["vetoes", "scores", "notes"],
    "additionalProperties": False,
}
JUDGE_CRITERIA = ("outline", "features", "printability", "fit")
JUDGE_LETTERS = {"outline": "o", "features": "f", "printability": "p", "fit": "u"}  # u = fit for use

TRIAGE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"retake": {"type": "boolean"}, "reason": {"type": "string"}},
    "required": ["retake", "reason"],
    "additionalProperties": False,
}

REFERENCE_CHECK_NOTE = (
    "\nPurpose: a measurement check of a known reference object. Describe it as a rigid solid of its shape (family "
    "`custom` unless a template fits); do not refuse it: nothing will be printed."
)
PLAN_PROMPT = (
    "You plan how to build a replacement part. Choose `template` when one of these templates matches the PartSpec "
    "family and shape (the builder then only fills its PARAMS), otherwise `free_code`. Templates: {templates}. "
    'Return JSON: {{"strategy": "template" | "free_code", "template": name or null, "why": str}}.'
)
TRIAGE_PROMPT = (
    "You check a phone photo of a part on a calibration mat before it is measured. Software already checked markers, "
    "blur, tilt, exposure, glare and moire: {checks}. Ask for a retake only if the part is clearly not fully visible, "
    'covered, or not on the mat. Return JSON: {{"retake": bool, "reason": str}}.'
)


@dataclass
class ReviewRound:
    """A reviewer round: the person reviewed `parent_job` and sent it back with pins (normalised points on its
    rectified top photo, each with a note) and a general note. The job starts from the parent's model."""

    parent_job: str
    round: int
    pins: list[Pin] = field(default_factory=list)
    note: str = ""
    parent_dir: Path | None = None  # the parent's run directory (read only: a replay's files are never written)


@dataclass
class RunOptions:
    """How one fix job runs. `answers` pre-fill questions by id (non-interactive runs)."""

    answers: dict[str, str | float] = field(default_factory=dict)
    question_timeout_s: float = 600.0
    max_iters: int | None = None
    wall_clock_s: float = 900.0
    mat_id: str | None = None
    package: bool = True
    learn: bool = True
    # Bench ablations (PLAN §10.3); each switches off exactly one thing. Defaults = the full PartSmith loop.
    single_shot: bool = False  # B0/B1: one build; no fix loop, no strategy switch, no judge
    mat_scale: bool = True  # B0: False = the models get no mat-calibrated numbers (sizes guessed from the photo)
    numeric_feedback: bool = True  # B2: False = the fixer sees the overlay images only, no residual numbers
    templates: bool = True  # PS-noTemplate: False = free code only
    judge: bool = True  # PS-noJudge: False = no judge stage
    height_correction: bool = True  # PS-noHeightCorr: False = measure on the mat plane, no parallax correction
    fix_mode: Literal["agent", "pipeline"] = "agent"  # agent = the model operates the tools; pipeline = fixed loop
    points: dict[str, list[dict[str, Any]]] | None = None  # user taps: {"top": [{"x", "y", "kind"?, "id"?}]} (photo px)
    review: ReviewRound | None = None  # a reviewer round: start from the parent's model, give the fixer the notes


@dataclass
class JudgeResult:
    """One judge reply as code accepted it: vetoes (they feed the verifier) and the advisory 1–5 scorecard."""

    vetoes: list[JudgeVeto] = field(default_factory=list)
    scores: list[JudgeScore] = field(default_factory=list)
    notes: str = ""
    model: str | None = None
    mode: str = "mock"

    def score_label(self) -> str:
        """`scores o4 f3 p5 u4` (outline, features, printability, fit for use), or "" without a scorecard."""
        by = {s.criterion: s.score for s in self.scores}
        parts = [f"{JUDGE_LETTERS[c]}{by[c]}" for c in JUDGE_CRITERIA if c in by]
        return "scores " + " ".join(parts) if parts else ""

    def to_json(self) -> dict[str, Any]:
        return {
            "model": self.model,
            "mode": self.mode,
            "scores": [s.model_dump(mode="json") for s in self.scores],
            "vetoes": [v.model_dump(mode="json") for v in self.vetoes],
            "notes": self.notes,
        }


def parse_judge_reply(data: Mapping[str, Any], *, model: str | None, mode: str) -> JudgeResult:
    """Code's reading of a judge reply: malformed vetoes, unknown criteria, out-of-range or repeated scores are
    dropped one by one; a reply without scores (older prompt, replay) is still a valid reply."""
    vetoes: list[JudgeVeto] = []
    for raw in data.get("vetoes") or []:
        try:
            vetoes.append(JudgeVeto.model_validate(raw))
        except ValidationError:
            continue
    scores: list[JudgeScore] = []
    seen: set[str] = set()
    for raw in data.get("scores") or []:
        if not isinstance(raw, Mapping):
            continue
        val = raw.get("score")
        if isinstance(val, float) and val.is_integer():
            val = int(val)
        try:
            sc = JudgeScore(criterion=raw.get("criterion"), score=val, reason=str(raw.get("reason") or "")[:200])
        except ValidationError:
            continue
        if sc.criterion in seen:
            continue
        seen.add(sc.criterion)
        scores.append(sc)
    return JudgeResult(vetoes, scores, str(data.get("notes") or "")[:1000], model, mode)


class _Finish(Exception):
    def __init__(self, status: Literal["verified", "best_effort", "failed", "refused"], summary: dict[str, Any]):
        super().__init__(status)
        self.status = status
        self.summary = summary


@dataclass
class _StageNote:
    label: str
    status: Literal["ok", "fail", "skip"] = "ok"


@dataclass
class Round:
    """One build + verify of a (code, values) pair."""

    iter: int
    strategy: Strategy
    code: str
    values: dict[str, float]
    exec_result: ExecResult | None
    out: VerifyOutput | None
    error: str | None = None

    @property
    def verification(self) -> Verification | None:
        return self.out.verification if self.out else None

    @property
    def verified(self) -> bool:
        v = self.verification
        return bool(v and v.verified)

    @property
    def score(self) -> float:
        """Lower is better: the verifier's max error; a program that did not run scores infinity."""
        v = self.verification
        if v is None or v.status == "failed" or v.max_error_mm is None:
            return math.inf
        return float(v.max_error_mm)

    @property
    def rank(self) -> tuple[int, float]:
        """Ordering for "better": verified first, then the total violation of the pass rule — how far each failing P0
        test and each view metric is beyond its tolerance, in units of that tolerance."""
        v = self.verification
        if v is None or v.status == "failed" or v.max_error_mm is None:
            return (2, math.inf)
        excess = 0.0
        for t in v.tests:
            if t.priority != "P0" or t.passed or t.id.endswith(PHOTO_LIMITED_SUFFIX):
                continue  # a height-bound test asks for another photo, not a different model
            if t.value is None or t.expected is None or not t.tol:
                excess += MISSING_TEST_PENALTY
            else:
                excess += min(max(abs(t.value - t.expected) - t.tol, 0.0) / t.tol, 10.0)
        gates = self.out.view_gates if self.out is not None else {}
        for m in v.views:
            excess += max(m.hausdorff_mm - v.thresholds.hausdorff_mm, 0.0) / v.thresholds.hausdorff_mm
            if "iou" in gates.get(m.view, ["iou"]):
                excess += max(v.thresholds.iou - m.iou, 0.0) / (1.0 - v.thresholds.iou)
            if "mean" in gates.get(m.view, []):
                excess += max(m.mean_mm - MEAN_GATE_MM, 0.0) / MEAN_GATE_MM
        return (0 if v.verified else 1, round(excess, 4))

    def better_than(self, other: Round | None) -> bool:
        if other is None:
            return True
        a, b = self.rank, other.rank
        if a[0] != b[0]:
            return a[0] < b[0]
        return a[1] < b[1] - IMPROVE_EPS

    @property
    def worst_hd(self) -> float | None:
        v = self.verification
        return max((m.hausdorff_mm for m in v.views), default=None) if v else None

    @property
    def min_iou(self) -> float | None:
        v = self.verification
        return min((m.iou for m in v.views), default=None) if v else None


def make_runner(options: RunOptions | None = None) -> Runner:
    opts = options or RunOptions()

    def runner(job: Job) -> None:
        run_fix(job, opts)

    return runner


def run_fix(job: Job, options: RunOptions | None = None) -> None:
    """JobManager runner for a fix job."""
    FixRun(job, options or RunOptions()).run()


# ------------------------------------------------------------------------------------------------- small helpers


def png_bytes(img: np.ndarray[Any, Any]) -> bytes:
    ok, buf = cv2.imencode(".png", img)
    if not ok:
        raise RuntimeError("PNG encode failed")
    return bytes(buf.tobytes())


def image_size(data: bytes) -> tuple[int, int] | None:
    """(width, height) of an encoded image: the PNG header when it is one, else a decode. None when unreadable."""
    if data[:8] == b"\x89PNG\r\n\x1a\n" and len(data) >= 24:
        return int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")
    img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_UNCHANGED)
    return (int(img.shape[1]), int(img.shape[0])) if img is not None else None


def fit_png(png: bytes, max_side: int = MODEL_IMAGE_MAX_PX) -> tuple[bytes, float]:
    """Downscale an image so its long side is at most `max_side`. Returns (png, scale). A photo with an EXIF rotation
    is always re-encoded upright, so a model sees the pixels our measurements and the user's taps use."""
    try:
        img = decode_bgr(png)
    except ValueError:
        return png, 1.0
    h, w = img.shape[:2]
    s = min(1.0, max_side / max(h, w))
    if s >= 1.0:
        return (png, 1.0) if exif_orientation(png) == 1 else (png_bytes(img), 1.0)
    small = cv2.resize(img, (round(w * s), round(h * s)), interpolation=cv2.INTER_AREA)
    return png_bytes(small), s


def photo_mask_for(mo: MeasureOutput, meas: Measurements) -> PhotoMask | None:
    """The measured footprint (holes included) rasterised in the view's PART frame, the frame of `meas`."""
    fp = mo.footprint_mat
    if fp is None or not meas.part_to_mat:
        return None
    Mi = np.linalg.inv(np.asarray(meas.part_to_mat, dtype=np.float64))

    def to_part(coords: Any) -> np.ndarray[Any, Any]:
        p = np.asarray(coords, dtype=np.float64)[:, :2]
        return np.asarray(p @ Mi[:2, :2].T + Mi[:2, 2], dtype=np.float64)

    ext = to_part(fp.exterior.coords)
    holes = [to_part(r.coords) for r in fp.interiors]
    frame = Frame.around(ext, MASK_PX_PER_MM, margin_mm=4.0)
    return PhotoMask(rasterize_polygon(ext, holes, frame), frame)


def count_openings(mask: np.ndarray[Any, Any], px_per_mm: float) -> int:
    """Through-openings in a top silhouette: interior contours larger than MIN_OPENING_MM2."""
    m8 = np.ascontiguousarray(mask.astype(np.uint8))
    contours, hier = cv2.findContours(m8, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
    if hier is None:
        return 0
    min_px = MIN_OPENING_MM2 * px_per_mm * px_per_mm
    return sum(1 for i, c in enumerate(contours) if hier[0][i][3] >= 0 and cv2.contourArea(c) >= min_px)


def mask_png(mask: np.ndarray[Any, Any], fg: tuple[int, int, int] = (90, 90, 90)) -> bytes:
    img = np.full((*mask.shape, 3), 255, np.uint8)
    img[mask.astype(bool)] = fg
    return png_bytes(img)


def model_outline(out: VerifyOutput, exec_result: ExecResult | None) -> dict[str, Any] | None:
    """Model top outline + through holes in the measured part frame (mm, Y up): fit outline and 1:1 template."""
    vr = out.views.get("top")
    if vr is None:
        return None
    frame = vr.photo.frame
    m8 = np.ascontiguousarray(vr.model_mask.astype(np.uint8))
    contours, _ = cv2.findContours(m8, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    if not contours:
        return None
    c = max(contours, key=cv2.contourArea)
    pts = frame.to_mm(c.reshape(-1, 2).astype(np.float64))
    simple = cv2.approxPolyDP(pts.astype(np.float32).reshape(-1, 1, 2), 0.05, True).reshape(-1, 2)
    holes: list[dict[str, Any]] = []
    feats = (exec_result.features or {}) if exec_result else {}
    for h in feats.get("holes", []):
        if not h.get("through"):
            continue
        cxy = vr.transform.apply(np.array([h["center_mm"]], dtype=np.float64))[0]
        holes.append(
            {
                "center_mm": [round(float(cxy[0]), 3), round(float(cxy[1]), 3)],
                "diameter_mm": round(float(h["diameter_mm"]), 3),
            }
        )
    thickness = feats.get("plate_thickness_mm")
    return {
        "outline_mm": [[round(float(x), 3), round(float(y), 3)] for x, y in simple],
        "holes": holes,
        "thickness_mm": thickness,
        "frame": "measured top-view part frame (mm, Y up)",
    }


def outline_dims(outline: list[list[float]], holes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Dimension lines for the 1:1 template: overall X / Y extent and each hole diameter (part frame)."""
    P = np.asarray(outline, dtype=np.float64)
    (x0, y0), (x1, y1) = P.min(axis=0), P.max(axis=0)
    dims = [
        {"label": f"{x1 - x0:.2f} mm", "from_mm": [x0, y0 - 6], "to_mm": [x1, y0 - 6], "value_mm": round(x1 - x0, 3)},
        {"label": f"{y1 - y0:.2f} mm", "from_mm": [x1 + 6, y0], "to_mm": [x1 + 6, y1], "value_mm": round(y1 - y0, 3)},
    ]
    for h in holes:
        cx, cy = h["center_mm"]
        d = float(h["diameter_mm"])
        dims.append({"label": f"Ø{d:.2f}", "from_mm": [cx - d / 2, cy], "to_mm": [cx + d / 2, cy], "value_mm": d})
    return dims


def residual_table(v: Verification) -> list[dict[str, Any]]:
    return [r.model_dump(mode="json") for r in sorted(v.residuals, key=lambda r: abs(r.delta_mm), reverse=True)]


def residual_keys(v: Verification | None) -> dict[str, float]:
    """{"feature.quantity": model − measured} for the history the fixer sees."""
    return {f"{r.feature_id}.{r.quantity}": round(r.delta_mm, 4) for r in v.residuals} if v else {}


def format_residuals(v: Verification, limit: int = 12) -> str:
    rows = sorted(v.residuals, key=lambda r: abs(r.delta_mm), reverse=True)[:limit]
    out = [
        f"{r.feature_id} {r.quantity}: measured {r.measured_mm:.2f}, model {r.model_mm:.2f}, "
        f"Δ {r.delta_mm:+.2f} mm (tol ±{r.tol_mm}) {'ok' if r.passed else 'FAIL'}"
        for r in rows
    ]
    return "\n".join(out) or "(no feature residuals)"


def format_views(v: Verification) -> str:
    return "; ".join(
        f"{m.view}: IoU {m.iou:.3f}, Hausdorff {m.hausdorff_mm:.2f} mm"
        + (f" at ({m.worst_point_mm[0]:.1f}, {m.worst_point_mm[1]:.1f})" if m.worst_point_mm else "")
        + f", extra {m.over_area_mm2:.1f} mm², missing {m.under_area_mm2:.1f} mm²"
        for m in v.views
    )


def why_not_verified(v: Verification, gates: Mapping[str, Sequence[str]] | None = None, limit: int = 6) -> list[str]:
    """Each pass rule `v` breaks, in plain words: the failing P0 tests and every view gate (the same rules
    `Round.rank` sums). A small silhouette is gated on its mean edge distance instead of IoU; a fixer shown only IoU
    and Hausdorff cannot see that rule (live, 2026-10-29: the knob's side view failed it at 0.19 mm, Hausdorff 0.43)."""
    out = [
        f"P0 test {t.id}: {t.description}" + (f" (model {t.value:.2f})" if t.value is not None else "")
        for t in v.tests
        if t.priority == "P0" and not t.passed and not t.id.endswith(PHOTO_LIMITED_SUFFIX)
    ]
    th = v.thresholds
    for m in v.views:
        applied = (gates or {}).get(m.view, ["hausdorff", "iou"])
        if m.hausdorff_mm > th.hausdorff_mm:
            out.append(f"{m.view} view: Hausdorff {m.hausdorff_mm:.2f} mm > {th.hausdorff_mm:g} mm")
        if "iou" in applied and m.iou < th.iou:
            out.append(f"{m.view} view: IoU {m.iou:.3f} < {th.iou:g}")
        if "mean" in applied and m.mean_mm > MEAN_GATE_MM:
            out.append(
                f"{m.view} view: mean edge distance {m.mean_mm:.2f} mm > {MEAN_GATE_MM:g} mm (small silhouette: gated "
                f"on the mean distance between the outlines, not on IoU; extra {m.over_area_mm2:.1f} mm², missing "
                f"{m.under_area_mm2:.1f} mm²)"
            )
    return out[:limit]


def format_gate_failures(v: Verification, gates: Mapping[str, Sequence[str]] | None = None) -> str:
    """Empty when `v` is verified, else one line naming what still fails."""
    if v.verified:
        return ""
    why = why_not_verified(v, gates)
    return "\nnot verified because: " + ("; ".join(why) if why else "a P1 check or a veto (see the tests)")


VISUAL_ONLY_NOTE = "(withheld: visual-only feedback — compare the overlay images)"
NO_SCALE_DISTANCE_MM = 300.0  # B0 guess: a phone held ~30 cm above the part with a 26 mm-equivalent lens
NO_SCALE_FOCAL35_MM = 26.0


def guessed_scale(mo: MeasureOutput) -> float:
    """B0 ablation: factor that turns mat-calibrated mm into sizes guessed from the photo alone (pixels at an assumed
    distance and focal length). 1.0 when the photo was not calibrated."""
    det = mo.detection
    if det is None:
        return 1.0
    w, h = det.image_size
    f_px = NO_SCALE_FOCAL35_MM * math.hypot(w, h) / math.hypot(36.0, 24.0)
    st = det.mat.stage
    px_per_mm = det.px_per_mm_at((st.x_mm + st.w_mm / 2, st.y_mm + st.h_mm / 2))
    return float(px_per_mm * NO_SCALE_DISTANCE_MM / f_px)


def scale_measurements(m: Measurements, f: float) -> Measurements:
    """Every in-plane size scaled by f (thickness stated by the user stays as stated)."""
    if f == 1.0:
        return m
    d = m.model_copy(deep=True)

    def sc(x: Measured) -> Measured:
        return x.model_copy(update={"value": x.value * f, "sigma_mm": x.sigma_mm * f})

    d.outline_mm = [(x * f, y * f) for x, y in m.outline_mm]
    d.length, d.width = sc(m.length), sc(m.width)
    d.area_mm2 = m.area_mm2 * f * f
    d.holes = [
        h.model_copy(update={"center_mm": (h.center_mm[0] * f, h.center_mm[1] * f), "diameter": sc(h.diameter)})
        for h in m.holes
    ]
    d.slots = [
        s.model_copy(
            update={"center_mm": (s.center_mm[0] * f, s.center_mm[1] * f), "length": sc(s.length), "width": sc(s.width)}
        )
        for s in m.slots
    ]
    if m.thickness is not None and m.thickness.source == Source.measured:
        d.thickness = sc(m.thickness)
    d.notes = [*m.notes, f"ABLATION: sizes guessed without the mat scale (×{f:.3f})"]
    return d


def local_kind(photo: np.ndarray[Any, Any], model: np.ndarray[Any, Any], frame: Frame, at_mm: Any) -> str:
    """'extra' when the model has material the photo lacks around `at_mm` (part frame), 'missing' for the opposite."""
    c = frame.to_px(np.asarray(at_mm, dtype=np.float64))
    r = max(2, round(1.5 * frame.px_per_mm))
    x0, y0 = round(c[0]) - r, round(c[1]) - r
    h, w = photo.shape[:2]
    xs, ys = slice(max(x0, 0), min(x0 + 2 * r + 1, w)), slice(max(y0, 0), min(y0 + 2 * r + 1, h))
    p, m = photo[ys, xs].astype(bool), model[ys, xs].astype(bool)
    extra, missing = int(np.count_nonzero(m & ~p)), int(np.count_nonzero(p & ~m))
    return "extra" if extra > missing else "missing" if missing > extra else "unclear"


def format_spots(spots: list[dict[str, Any]]) -> str:
    return "".join(
        f"; worst {s['view']} residual {s['hausdorff_mm']:.2f} mm at model {s['plane']} ({s['at_mm'][0]:.1f}, "
        f"{s['at_mm'][1]:.1f}) mm — the model has {s['kind']} material there"
        for s in spots
    )


def template_measure_map(code: str, template: Template | None) -> dict[str, str]:
    if template is not None:
        return dict(template.measure_map)
    try:
        lit = module_literals(code, ("MEASURE_MAP",)).get("MEASURE_MAP")
    except (SyntaxError, ValueError):
        lit = None
    return {str(k): str(v) for k, v in lit.items()} if isinstance(lit, dict) else {}


def photo_field(mo: MeasureOutput) -> np.ndarray[Any, np.dtype[np.float32]] | None:
    """The soft coverage map the metrology traced its sub-pixel contours on. The verifier compares the model with
    this edge, not with the binary mask's blur halo."""
    return mo.photo_field


# ------------------------------------------------------------------------------------------------- the run


class FixRun:
    def __init__(self, job: Job, opts: RunOptions) -> None:
        self.job = job
        self.opts = opts
        self.t0 = time.monotonic()
        self.max_iters = max(1, opts.max_iters or job.input.max_iters or DEFAULT_MAX_ITERS)
        self.photos: dict[str, bytes] = {}
        self.photo_shas: dict[str, str] = dict(job.input.photo_shas)
        self.mo: dict[str, MeasureOutput] = {}
        self.measurements: dict[str, Measurements] = {}
        self.masks: dict[str, PhotoMask] = {}
        self.calibration: dict[str, Any] = {}
        self.spec: PartSpec | None = None
        self.answers: dict[str, str | float] = {}
        self.template: Template | None = None
        self.strategy: Strategy = "template"
        self.iteration = 0
        self.history: list[dict[str, Any]] = []
        self.iter_events: list[dict[str, Any]] = []
        self.switches: list[str] = []
        self.first_values: dict[str, float] = {}
        self.vetoes: list[JudgeVeto] = []
        self.best: Round | None = None
        self.current: Round | None = None
        self.heights: dict[
            str, tuple[float | None, Literal["prism", "round"]]
        ] = {}  # view -> (height passed to the metrology, profile)
        self.pending_heights: dict[str, tuple[float | None, Literal["prism", "round"]]] = {}
        self.noted: set[tuple[str, str]] = set()
        self.hidden_holes: dict[str, tuple[float, float]] = {}  # question id -> part-frame centre
        self.orbit_views: list[Any] = []  # calibrated orbit frames (CameraView) for the verifier
        self.orbit_height: Measured | None = None  # visual-hull height from the orbit clip (measured)
        self.narration: providers.Narration | None = None  # Spark's reading of a narrated walk-around (steers only)
        self.orbit_footprint: Any = None  # the walk-around's own footprint on the mat (shapely Polygon) when measured
        self.completion_accepted = False
        self.rebuilt: set[str] = set()  # code findings that already triggered their one rebuild
        # Dimensions the user stated because the photo cannot show them (measured quantity -> value), and the knobs
        # they fix (knob -> why): the guards never move those, the verifier treats them as stated, not observed.
        self.stated: dict[str, Measured] = {}
        self.locked: dict[str, str] = {}
        # The "where it fits" photo: its capture report and the measured mates (+ fits once the verdict is in).
        self.mate_capture: CaptureReport | None = None
        self.mate_result: MateFitResult | None = None
        # A reviewer round's pins resolved on this job's own photo (review_round.json), and the promoted family rules
        # this job was given (lessons_used.json).
        self.review_pins: list[dict[str, Any]] = []
        self.lessons_used: list[str] = []

    # ---- events ------------------------------------------------------------------------------------------------------
    def stage_event(self, stage: StageName, status: str, label: str, ms: int | None = None) -> None:
        it = self.iteration if stage in ("execute", "verify", "fix", "build") and self.iteration else None
        self.job.emit(StageEvent(job=self.job.id, stage=stage, status=status, label=label, ms=ms, iter=it))

    @contextmanager
    def stage(self, name: StageName, label: str) -> Iterator[_StageNote]:
        self.check_alive()
        t = time.perf_counter()
        self.stage_event(name, "start", label)
        note = _StageNote(label)
        try:
            yield note
        except _Finish:
            self.stage_event(name, note.status, note.label, self._ms(t))
            raise
        except (JobCancelled, QuestionTimeout):
            raise
        except Exception as exc:
            self.stage_event(name, "fail", f"{note.label} — {type(exc).__name__}: {exc}"[:300], self._ms(t))
            raise
        self.stage_event(name, note.status, note.label, self._ms(t))

    @staticmethod
    def _ms(t: float) -> int:
        return int((time.perf_counter() - t) * 1000)

    def artifact(self, kind: str, data: bytes, ext: str, label: str, iter: int | None = None) -> str:
        key = blobs.put(data, ext)
        self.job.emit(ArtifactEvent(job=self.job.id, kind=kind, sha=key, url=blobs.url(key), label=label, iter=iter))
        return key

    def log(self, msg: str, level: str = "info") -> None:
        self.job.log(msg, level)

    def set_ctx(self, code: str | None = None, values: Mapping[str, float] | None = None) -> None:
        self.job.ctx = context_hash(
            self.photo_shas, self.calibration, code_sha(code) if code else None, dict(values or {})
        )
        self.job.write_json("state.json", {"ctx": self.job.ctx, "calibration": self.calibration})

    def check_alive(self) -> None:
        if self.job.cancelled:
            raise JobCancelled(self.job.id)

    def over_budget(self) -> str | None:
        if self.job.summary.cost_usd >= self.job.input.budget_usd:
            return f"cost cap reached (${self.job.summary.cost_usd:.3f} of ${self.job.input.budget_usd:.2f})"
        if time.monotonic() - self.t0 > self.opts.wall_clock_s:
            return f"wall-clock cap reached ({self.opts.wall_clock_s:.0f} s)"
        return None

    # ---- model calls ---------------------------------------------------------------------------------------------------
    def call(self, stage: str, req: ModelRequest) -> Completion | None:
        """One model call inside the job context. A reply whose ctx went stale meanwhile is discarded (None)."""
        ctx = self.job.ctx
        with providers.job_context(self.job.id, self.job.emit, ctx=ctx):
            out = providers.complete(stage, req)
        if self.job.ctx != ctx:
            self.log(f"{stage}: reply arrived for an older state (ctx {ctx}); discarded", "warn")
            return None
        return out

    # ---- main ----------------------------------------------------------------------------------------------------------
    def run(self) -> None:
        mock_brain.install(replace=False)
        try:
            self._run()
        except _Finish as fin:
            self.finish(fin.status, fin.summary)

    def _run(self) -> None:
        self.set_ctx()
        self.capture()
        self.measure()
        if self.opts.review is not None:
            first = self.start_from_parent(
                self.opts.review
            )  # no understand / ask / plan: the reviewed model is round 1
        else:
            self.understand()
            self.ask()
            self.plan()
            self.ask_stated_length()
            first = self.build_round(self.strategy, iter_label="first build")
            if first.score == math.inf and self.strategy in ("template", "free_code") and not self.opts.single_shot:
                self.switch_strategy()  # template → free code, or free code with no solid → the family's template
        self.first_values = dict(first.values)
        if not self.opts.single_shot:
            b = self.best
            if (
                self.opts.review is not None
                and b is not None
                and b.verification is not None
                and b.verification.status != "failed"
            ):
                self.fix_round(reviewer=True)  # the person says something is wrong: one round even if verified
            if self.opts.fix_mode == "agent":
                self.agent_fix()
            else:
                self.fix_loop()
            if self.opts.judge:
                self.judge()
        final = self.final_verification()
        if self.opts.review is not None:
            self.save_review_pins(after=self.best)
        if self.opts.package:
            self.package(final)
            self.buy_or_print(final)
        if self.opts.learn:
            self.learn(final)
        self.finish(final.status if final is not None else "failed", {})

    def summary(self, extra: Mapping[str, Any]) -> dict[str, Any]:
        b = self.best
        v = b.verification if b else None
        modes = {e.mode for e in self.job.events if e.t == "model_call"}
        mode = "mock" if modes <= {"mock"} else ("live" if "live" in modes else "replay")
        if len(modes) > 1:
            mode = "mixed"
        out: dict[str, Any] = {
            "max_error_mm": v.max_error_mm if v else None,
            "iterations": self.iteration,
            "cost_usd": round(self.job.summary.cost_usd, 6),
            "mode": mode,
            "origin": self.job.input.origin.value,
            "strategy": b.strategy if b else self.strategy,
            "template": self.template.name if self.template else None,
            "title": self.spec.title if self.spec else "",
            "family": self.spec.family.value if self.spec else None,
        }
        ship = self.job.read_json("ship.json")
        if ship:
            out["can_ship"] = bool(ship.get("ok"))
        out["fix_mode"] = self.opts.fix_mode
        if self.opts.review is not None:
            out["parent_job"] = self.opts.review.parent_job
            out["review_round"] = self.opts.review.round
        if v is not None and v.views:
            out["hausdorff_mm"] = max(m.hausdorff_mm for m in v.views)
            out["iou"] = min(m.iou for m in v.views)
            out["tests_passed"] = sum(t.passed for t in v.tests)
            out["tests_total"] = len(v.tests)
        out.update(extra)
        return out

    def finish(self, status: Literal["verified", "best_effort", "failed", "refused"], extra: dict[str, Any]) -> None:
        final = self.read_final_verification()
        verified = bool(final is not None and final.verified and status == "verified")
        self.job.emit(DoneEvent(job=self.job.id, verified=verified, status=status, summary=self.summary(extra)))

    def read_final_verification(self) -> Verification | None:
        data = self.job.read_json("verification.json")
        return Verification.model_validate(data) if data else None

    # ---- 0. capture ------------------------------------------------------------------------------------------------------
    def capture(self) -> None:
        with self.stage("capture", "Checking the photos (markers, blur, tilt, light)") as st:
            for view, key in self.photo_shas.items():
                self.photos[view] = blobs.get(key)
                kind, what = {
                    "orbit": ("video", "orbit clip"),
                    "narration": ("narration", "voice note about the clip"),
                }.get(view, ("photo", f"{view} photo"))
                self.job.emit(ArtifactEvent(job=self.job.id, kind=kind, sha=key, url=blobs.url(key), label=what))
            if "top" not in self.photos:
                st.status = "fail"
                st.label = "No top photo"
                raise _Finish("failed", {"retake_reason": "A top-view photo of the part on the mat is required."})
            reports: dict[str, CaptureReport] = {}
            for view in ("top", "side", "mating"):
                if view not in self.photos:
                    continue
                img = decode_image(self.photos[view])
                try:
                    det = detect_mat(img, mat_id=self.opts.mat_id)
                    try:
                        pose = estimate_pose(det)
                    except Exception:
                        pose = None
                    reports[view] = run_gate(img, det, None, pose=pose)
                except MatNotFoundError:
                    reports[view] = run_gate(img, None)
            top = reports["top"]
            if not top.passed:
                st.status = "fail"
                st.label = f"Retake the top photo: {top.retake_reason}"
                raise _Finish("failed", {"retake_reason": top.retake_reason, "capture": top.model_dump(mode="json")})
            side = reports.get("side")
            if side is not None and not side.passed:
                self.log(f"side photo not usable ({side.retake_reason}); continuing with the top view only", "warn")
                self.photos.pop("side", None)
            mating = reports.get("mating")
            if mating is not None:
                self.mate_capture = mating
                if not mating.passed:
                    self.log(f"mating photo not usable ({mating.retake_reason}); the fit is not checked", "warn")
                    self.photos.pop("mating", None)
            warns = [c for c in top.checks if c.severity == "warn"]
            if warns:
                self.triage(top)
            st.label = "Photos OK: " + ", ".join(f"{v} ✓" for v in reports if v in self.photos)

    def triage(self, report: CaptureReport) -> None:
        """Optional model look at a borderline photo. It can only ask for a retake (as a question), never pass one."""
        checks = "; ".join(f"{c.name}: {c.severity} ({c.reason})" for c in report.checks)
        png, _ = fit_png(self.photos["top"], 1024)
        req = ModelRequest(
            messages=[
                {"role": "developer", "content": TRIAGE_PROMPT.format(checks=checks)},
                {"role": "user", "content": "Top photo attached."},
            ],
            images=[png],
            json_schema=TRIAGE_SCHEMA,
            schema_name="capture_triage",
            mock_context={"checks": [c.model_dump(mode="json") for c in report.checks]},
        )
        try:
            out = self.call("capture_triage", req)
        except ProviderError as exc:
            self.log(f"capture triage unavailable ({exc}); continuing on the code checks", "warn")
            return
        data = (out.json if out else None) or {}
        if data.get("retake"):
            ans = self.question(
                Unknown(
                    id="capture.retake",
                    question=f"The photo checker suggests a retake: {data.get('reason', '')}. Continue anyway?",
                    expects="choice",
                    default="continue",
                    choices=["continue", "retake"],
                )
            )
            if str(ans) == "retake":
                raise _Finish("failed", {"retake_reason": str(data.get("reason", "retake requested"))})

    # ---- 1. measure ------------------------------------------------------------------------------------------------------
    def segmenter(self) -> ProviderSegmenter:
        hint = self.job.input.family_hint
        # A mock mask is labelled as one: its score is not SAM's confidence, so it never widens a value's ±σ.
        source = "mock-threshold" if providers.stage_mode("segment") == "mock" else "sam-3.1"
        return ProviderSegmenter(
            providers.segment, family_word=hint.value.replace("_", " ") if hint else None, source=source
        )

    def confidence_retake(self, view: str, cap: CaptureReport) -> None:
        """The segmenter is unsure of the part's outline (`mask_confidence` warning): the values already carry a wider
        ±σ; ask whether to retake the photo (default: continue, so unattended runs go on)."""
        low = next((c for c in cap.checks if c.name == "mask_confidence" and c.severity != "ok"), None)
        if low is None:
            return
        self.log(f"{view} photo: {low.reason} (every value from this mask carries a wider ±σ)", "warn")
        if view != "top":
            return
        ans = self.question(
            Unknown(
                id="capture.retake.mask",
                question=f"{low.reason} Retake the top photo, or continue with the wider ± values?",
                expects="choice",
                default="continue",
                choices=["continue", "retake"],
            )
        )
        if str(ans) == "retake":
            raise _Finish("failed", {"retake_reason": low.reason, "capture": cap.model_dump(mode="json")})

    def measure_view(
        self,
        view: str,
        thickness_mm: float | None,
        *,
        profile: Literal["prism", "round"] = "prism",
        stated_thickness_mm: float | None = None,
    ) -> MeasureOutput:
        if not self.opts.height_correction:
            thickness_mm = None  # ablation: footprints stay on the mat plane
        with providers.job_context(self.job.id, self.job.emit, ctx=self.job.ctx):
            mo = measure_photo(
                self.photos[view],
                view,
                segmenter=self.segmenter(),
                thickness_mm=thickness_mm,
                origin=self.job.input.origin,
                mat_id=self.opts.mat_id,
                profile=profile,
                stated_thickness_mm=stated_thickness_mm,
            )
        self.pending_heights[view] = (thickness_mm, profile)
        return mo

    def measure_side(self, profile: Literal["prism", "round"]) -> bool:
        """Measure the side photo (part on its side): its top face stands at the top view's width."""
        top = self.measurements["top"]
        ms = self.measure_view(
            "side", top.width.value, profile=profile, stated_thickness_mm=self.job.input.thickness_mm
        )
        self.store_view("side", ms)
        self.confidence_retake("side", ms.result.capture)
        m = ms.result.measurements
        if m is None or m.thickness is None:
            self.log("side photo could not be measured; continuing with the top view", "warn")
            return False
        self.accept_view("side", ms, m)
        return True

    def round_part(self) -> bool:
        """A solid of revolution (wheel, knob, spacer): on its side it lies on its curved surface."""
        fam = (
            self.spec.family.value
            if self.spec
            else (self.job.input.family_hint.value if self.job.input.family_hint else None)
        )
        if fam in ROUND_FAMILIES:
            return True
        cues = mock_brain.shape_cues(self.measurements["top"].model_dump(mode="json"))
        return bool(cues["round"])

    def camera_view(self, view: str) -> CameraView | None:
        """The photo's own camera for the verifier's camera-frame comparison (None without a solved pose)."""
        mo = self.mo.get(view)
        if mo is None or mo.pose is None or mo.photo_mask is None or mo.detection is None or mo.part_to_mat is None:
            return None
        if mo.K is None or mo.R is None or mo.t_mm is None:
            return None
        det = mo.detection
        ppm = mo.top_px_per_mm
        if ppm is None and mo.footprint_mat is not None:
            c = mo.footprint_mat.centroid
            ppm = det.px_per_mm_at((c.x, c.y))
        if ppm is None:
            return None
        h, w = mo.photo_mask.shape[:2]
        height, profile = self.heights.get(view, (None, "prism"))
        return CameraView(
            image_field=photo_field(mo),
            K=mo.K,
            R=mo.R,
            t_mm=mo.t_mm,
            image_mask=mo.photo_mask,
            part_to_mat=mo.part_to_mat,
            px_per_mm_local=float(ppm),
            image_size=(w, h),
            dist=det.dist,
            top_height_mm=height,
            scale_correction=1.0,
            H_ground=det.H,
            profile=profile,
        )

    def camera_views(self) -> dict[str, CameraView]:
        out: dict[str, CameraView] = {}
        for view in self.measurements:
            cv = self.camera_view(view)
            if cv is not None:
                out[view] = cv
        for i, frame in enumerate(self.orbit_views):  # every usable orbit frame is one more calibrated view
            out[f"orbit_{i}"] = frame
        return out

    def measure_points(self, view: str, points_px: Sequence[Sequence[float]]) -> list[dict[str, Any]]:
        from services.agent import evidence

        return evidence.measure_points(self, view, points_px)

    def surface_notes(self) -> None:
        """Metrology notes that change what the model can know: shown in the trace once."""
        for view, m in self.measurements.items():
            for n in m.notes:
                if any(k in n for k in NOTE_KEYS) and (view, n) not in self.noted:
                    self.noted.add((view, n))
                    self.log(f"{view} photo: {n}", "warn")

    def store_view(self, view: str, mo: MeasureOutput) -> None:
        self.artifact("measure_overlay", mo.overlay_png, ".png", f"{view}: measured outline and features")
        if mo.rectified_png:
            key = self.artifact("rectified", mo.rectified_png, ".png", f"{view}: rectified to the mat plane")
            if view == "top":
                grid = {"sha": key, "px_per_mm": mo.px_per_mm, "origin_mm": list(mo.origin_mm)}
                self.job.write_json("rectified.json", grid)
        if mo.mask_png:
            self.artifact("mask_overlay", mo.mask_png, ".png", f"{view}: part mask (rectified)")

    def measure(self) -> None:
        with self.stage("measure", "Measuring the part in millimetres") as st:
            mo = self.measure_view("top", self.job.input.thickness_mm)
            self.store_view("top", mo)
            m = mo.result.measurements
            cap = mo.result.capture
            fatal = [c for c in cap.checks if c.severity == "fail" and c.name in FATAL_PART_CHECKS]
            if m is None or fatal:
                st.status = "fail"
                reason = (fatal[0].reason if fatal else None) or cap.retake_reason or "No part found on the stage."
                st.label = f"Retake: {reason}"
                raise _Finish("failed", {"retake_reason": reason, "capture": cap.model_dump(mode="json")})
            for c in cap.checks:
                if c.severity == "fail":
                    self.log(
                        f"photo check {c.name}: {c.reason} (measuring anyway; the verifier compares the result)", "warn"
                    )
            self.confidence_retake("top", cap)
            self.accept_view("top", mo, m)
            labels = [f"top {m.length.value:.2f} × {m.width.value:.2f} mm, {len(m.holes)} hole(s)"]
            if "side" in self.photos:
                profile: Literal["prism", "round"] = "round" if self.round_part() else "prism"
                if self.measure_side(profile):
                    sm = self.measurements["side"]
                    assert sm.thickness is not None
                    labels.append(f"side ({profile}): height {sm.thickness.value:.2f} mm")
            self.surface_notes()
            if "mating" in self.photos or self.mate_capture is not None:
                from services.agent import mating as mating_photo

                said_mate = mating_photo.measure(self)
                if said_mate:
                    labels.append(said_mate)
            if "orbit" in self.photos:
                from services.agent import evidence

                evidence.apply_orbit(self)
                if self.orbit_height is not None:
                    labels.append(f"orbit: height {self.orbit_height.value:.2f} mm")
                said = evidence.apply_narration(self)
                if said:
                    labels.append(said)
            cal = mo.result.calibration
            if cal is not None:
                self.calibration = {"mat_id": cal.mat_id, "H": cal.homography}
            self.save_measurements()
            self.set_ctx()
            st.label = "Measured " + "; ".join(labels) + f" (mask: {m.mask_source})"

    def accept_view(self, view: str, mo: MeasureOutput, m: Measurements) -> None:
        self.mo[view] = mo
        self.measurements[view] = m
        self.heights[view] = self.pending_heights.get(view, (None, "prism"))
        pm = photo_mask_for(mo, m)
        if pm is not None:
            self.masks[view] = pm

    def model_measurements(self) -> dict[str, Measurements]:
        """What the models are shown: the measurements, or (B0 ablation) the same shapes at a scale guessed from a
        typical phone distance instead of the mat."""
        if self.opts.mat_scale:
            return self.measurements
        out: dict[str, Measurements] = {}
        for view, m in self.measurements.items():
            mo = self.mo.get(view)
            f = guessed_scale(mo) if mo is not None else 1.0
            out[view] = scale_measurements(m, f)
        return out

    def save_measurements(self) -> None:
        self.job.write_json("measurements.json", {v: m.model_dump(mode="json") for v, m in self.measurements.items()})

    # ---- 2. understand ------------------------------------------------------------------------------------------------------
    def templates_info(self) -> list[dict[str, Any]]:
        return [
            {
                "name": t.name,
                "family": t.family.value,
                "title": t.title,
                "tags": list(t.tags),
                "measure_map": t.measure_map,
            }
            for t in list_templates()
        ]

    def intent_for_models(self) -> str:
        """The user's words, plus what Spark understood from a narrated walk-around (words only: it never carries a
        size, and the measured values stay the only numbers)."""
        intent = str(self.job.input.intent)
        n = self.narration
        if n is None:
            return intent
        said = [f"function: {n.function}"] if n.function else []
        if n.mating_feature:
            said.append(f"mating feature: {n.mating_feature}")
        if n.break_description:
            said.append(f"break: {n.break_description}")
        if not said:
            return intent
        return (
            f"{intent}\n[Narrated walk-around, as understood by {n.label}; steering only, never a "
            f"measurement] " + "; ".join(said)
        )

    @property
    def reference_check(self) -> bool:
        """A measurement check of a known object (server-set `JobInput.purpose`; never from a public request)."""
        return getattr(self.job.input, "purpose", "repair") == "reference_check"

    def understand(self) -> None:
        with self.stage("understand", "Understanding the part (features, family, unknowns)") as st:
            top = self.measurements["top"]
            if self.opts.mat_scale:
                rect_png, s = fit_png(self.mo["top"].rectified_png or self.photos["top"])
                images = [rect_png]
                if "side" in self.mo and self.mo["side"].rectified_png:
                    images.append(fit_png(self.mo["side"].rectified_png or b"")[0])
            else:  # B0: the raw photo, and only sizes guessed without the mat scale
                rect_png, s = fit_png(self.photos["top"])
                images = [rect_png]
            model_meas = self.model_measurements()
            p = prompt_loader.load("understand")
            meas_json = {v: m.model_dump(mode="json", exclude={"part_to_mat"}) for v, m in model_meas.items()}
            dev, user = p.render(
                px_per_mm_inv=f"{1.0 / (self.mo['top'].px_per_mm * s):.3f}",
                templates=", ".join(t.name for t in list_templates()),
                measurements=json.dumps(meas_json),
                intent=self.intent_for_models(),
                side_note=" and side view" if len(images) > 1 else "",
                purpose_note=REFERENCE_CHECK_NOTE if self.reference_check else "",
            )
            req = ModelRequest(
                messages=[{"role": "developer", "content": dev}, {"role": "user", "content": user}],
                images=images,
                json_schema=PartSpec.model_json_schema(),
                schema_name="PartSpec",
                strict=False,
                mock_context={
                    "measurements": {v: m.model_dump(mode="json") for v, m in model_meas.items()},
                    "intent": self.job.input.intent,
                    "family_hint": self.job.input.family_hint.value if self.job.input.family_hint else None,
                    "user_thickness_mm": self.job.input.thickness_mm,
                    "templates": self.templates_info(),
                },
            )
            spec: PartSpec | None = None
            try:
                out = self.call("understand", req)
                if out is not None and out.json is not None:
                    spec = PartSpec.model_validate(out.json)
            except (ProviderError, ValidationError) as exc:
                self.log(
                    f"understand reply unusable ({type(exc).__name__}); using the measurement-only PartSpec", "warn"
                )
            if spec is None:
                spec = PartSpec.model_validate(mock_brain.understand(req))
                self.log("PartSpec built deterministically from the measurements (no usable model reply)", "warn")
            if self.opts.mat_scale:
                spec = self.enforce_measured(spec, top)
            else:
                self.log("ablation (no mat scale): the model's own size estimates are kept", "warn")
            cls = guards.refused_class(self.job.input.intent, spec.title, spec.intent)
            if spec.refusal and self.reference_check and cls is None:
                # live, 2026-10-29: Spark refused the AA cell and SD card reference samples ("not a rigid plastic
                # part"). A measurement check prints nothing, so the model's refusal is logged and ignored; code's own
                # refused classes still apply, and the export gate labels the job as a measurement check.
                self.log(f"model refusal ignored on a reference check (nothing is printed): {spec.refusal}", "warn")
                spec.refusal = None
            reason = spec.refusal or (guards.refusal_message(cls) if cls else None)
            self.spec = spec
            if reason:
                self.save_spec()
                st.label = f"Refused: {reason}"
                raise _Finish("refused", {"reason": reason})
            self.note_unknowns(spec)
            from services.agent import evidence

            evidence.apply_points(self)
            self.enforce_measured(spec, self.measurements["top"])
            dropped = evidence.check_break_support(self)
            evidence.propose_completion(self)
            side_h = self.heights.get("side")
            if side_h is not None and side_h[1] != "round" and self.round_part() and self.measure_side("round"):
                self.save_measurements()
                self.log("side photo re-measured as a round profile (the part lies on its curved side)")
            self.save_spec()
            st.label = (
                f"{spec.family.value}: {len(spec.features)} feature(s), thickness {spec.thickness.value:.2f} mm "
                f"({spec.thickness.source.value}), {len(spec.unknowns)} question(s)"
                + (" · proposed break dropped (no evidence besides the model)" if dropped else "")
            )

    def note_unknowns(self, spec: PartSpec) -> None:
        """Questions from metrology notes: a bore the camera could not see through may still be a hole."""
        top = self.measurements["top"]
        if not top.part_to_mat:
            return
        Mi = np.linalg.inv(np.asarray(top.part_to_mat, dtype=np.float64))
        k = 0
        for n in top.notes:
            m = HIDDEN_HOLE_RE.search(n)
            if m is None:
                continue
            k += 1
            x, y, d = (float(g) for g in m.groups())
            px, py = (Mi @ np.array([x, y, 1.0]))[:2]
            uid = f"hidden_hole_{k}.diameter"
            self.hidden_holes[uid] = (round(float(px), 3), round(float(py), 3))
            if not any(u.id == uid for u in spec.unknowns):
                spec.unknowns.append(
                    Unknown(
                        id=uid,
                        question=f"The photo may hide a through-hole about Ø{d:.1f} mm at ({px:.1f}, {py:.1f}) mm from "
                        "the part's centre. If there is a hole there, what is its diameter in mm? (0 = no hole)",
                        default=0.0,
                    )
                )

    def enforce_measured(self, spec: PartSpec, top: Measurements) -> PartSpec:
        """Code decides: measured values replace whatever the model wrote; unmeasured 'measured' claims are downgraded."""
        changed: list[str] = []
        spec.base_profile.points_mm = list(top.outline_mm)
        spec.base_profile.source = Source.measured
        spec.base_profile.sigma_mm = top.length.sigma_mm
        measured_ids = {h.id for h in top.holes} | {s.id for s in top.slots}
        kept = []
        for f in spec.features:
            if f.id in measured_ids and not isinstance(f, ThroughHole | SlotFeature):
                changed.append(f"{f.id} kind")
                continue
            kept.append(f)
        spec.features = kept
        by_id = {f.id: f for f in spec.features}
        for h in top.holes:
            hf = by_id.get(h.id)
            if isinstance(hf, ThroughHole):
                if abs(hf.diameter.value - h.diameter.value) > 1e-6 or tuple(hf.center_mm) != tuple(h.center_mm):
                    changed.append(h.id)
                hf.diameter, hf.center_mm = h.diameter, h.center_mm
            else:
                spec.features.append(ThroughHole(id=h.id, center_mm=h.center_mm, diameter=h.diameter))
                changed.append(f"{h.id} added")
        for s in top.slots:
            sf = by_id.get(s.id)
            if isinstance(sf, SlotFeature):
                sf.center_mm, sf.length, sf.width, sf.angle_deg = s.center_mm, s.length, s.width, s.angle_deg
            else:
                spec.features.append(
                    SlotFeature(id=s.id, center_mm=s.center_mm, length=s.length, width=s.width, angle_deg=s.angle_deg)
                )
                changed.append(f"{s.id} added")
        for f in spec.features:
            if f.id in measured_ids:
                continue
            for attr in (
                "diameter",
                "depth",
                "length",
                "width",
                "height",
                "outer_d",
                "inner_d",
                "flat_depth",
                "overhang",
                "thickness",
                "radius",
            ):
                val = getattr(f, attr, None)
                if isinstance(val, Measured) and val.source == Source.measured:
                    val.source = Source.inferred
                    changed.append(f"{f.id}.{attr} → inferred")
        thick = self.trusted_thickness()
        if thick is not None:
            if abs(spec.thickness.value - thick.value) > 1e-6 or spec.thickness.source != thick.source:
                changed.append("thickness")
            spec.thickness = thick
            spec.unknowns = [u for u in spec.unknowns if u.id != "thickness"]
        elif spec.thickness.source != Source.inferred:
            spec.thickness.source = Source.inferred
            changed.append("thickness → inferred")
        if spec.thickness.source == Source.inferred and not any(u.id == "thickness" for u in spec.unknowns):
            spec.unknowns.append(
                Unknown(
                    id="thickness",
                    question="How thick is the part, in millimetres?",
                    default=round(spec.thickness.value, 2),
                )
            )
        if spec.template_hint:
            try:
                get_template(spec.template_hint)
            except KeyError:
                changed.append(f"template_hint {spec.template_hint!r} unknown")
                spec.template_hint = None
        if changed:
            self.log("kept measured values over the model's: " + ", ".join(changed[:12]))
        return spec

    def trusted_thickness(self) -> Measured | None:
        if self.job.input.thickness_mm:
            return Measured(value=float(self.job.input.thickness_mm), source=Source.user_stated, sigma_mm=0.3)
        side = self.measurements.get("side")
        if side is not None and side.thickness is not None:
            return side.thickness
        if self.orbit_height is not None:
            return self.orbit_height
        top = self.measurements["top"]
        if top.thickness is not None and top.thickness.source != Source.inferred:
            return top.thickness
        return None

    def save_spec(self) -> None:
        assert self.spec is not None
        self.job.write_json("partspec.json", self.spec)

    # ---- 3. ask -----------------------------------------------------------------------------------------------------------
    def question(self, u: Unknown) -> str | float | None:
        """Ask one question; pre-supplied answers win, otherwise wait (or use the default after the timeout)."""
        q = QuestionEvent(
            job=self.job.id, id=u.id, text=u.question, expects=u.expects, default=u.default, choices=u.choices
        )
        if u.id in self.opts.answers:
            self.job.emit(q)
            value = self.opts.answers[u.id]
            self.job.answer(u.id, value, "text")
            return value
        try:
            got: str | float = self.job.ask(q, timeout_s=self.opts.question_timeout_s).value
            return got
        except QuestionTimeout:
            self.log(f"no answer to {u.id!r}; using the default ({u.default!r})", "warn")
            default: str | float | None = u.default
            return default

    def ask(self) -> None:
        assert self.spec is not None
        from services.agent import evidence

        evidence.lookup_specs(self)
        if not self.spec.unknowns:
            with self.stage("ask", "No questions needed") as st:
                st.status = "skip"
            return
        with self.stage("ask", f"Asking {len(self.spec.unknowns)} question(s)") as st:
            got: list[str] = []
            for u in list(self.spec.unknowns):
                value = self.question(u)
                if value is None or value == "":
                    continue
                self.answers[u.id] = value
                self.apply_answer(u.id, value)
                got.append(f"{u.id} = {value}")
            self.save_spec()
            st.label = "Answers: " + (", ".join(got) if got else "none")
            if str(self.answers.get("material.flexible", "")).strip().lower() in ("yes", "y", "haan", "ha"):
                st.label = "Refused: the user says the part is soft or flexible"
                raise _Finish("refused", {"reason": guards.refusal_message(guards.FLEXIBLE)})

    def apply_answer(self, qid: str, value: str | float) -> None:
        assert self.spec is not None
        try:
            num = float(value)
        except (TypeError, ValueError):
            return
        if qid == "thickness":
            self.spec.thickness = Measured(value=num, source=Source.user_stated, sigma_mm=0.3)
            if self.measurements["top"].thickness is None or self.measurements["top"].height_correction_scale == 1.0:
                mo = self.measure_view("top", num)  # re-measure with the height correction
                if mo.result.measurements is not None:
                    self.accept_view("top", mo, mo.result.measurements)
                    self.save_measurements()
                    self.enforce_measured(self.spec, mo.result.measurements)
            return
        if qid in self.hidden_holes:
            if num > 0:
                cx, cy = self.hidden_holes[qid]
                hid = qid.split(".")[0]
                d = Measured(value=num, source=Source.user_stated, sigma_mm=0.2)
                self.spec.features.append(ThroughHole(id=hid, center_mm=(cx, cy), diameter=d))
            return
        fid, _, attr = qid.partition(".")
        for f in self.spec.features:
            if f.id == fid and isinstance(getattr(f, attr or "diameter", None), Measured):
                setattr(f, attr or "diameter", Measured(value=num, source=Source.user_stated, sigma_mm=0.2))

    # ---- 3b. ask: a length the photo cannot show ------------------------------------------------------------------------
    def length_knob(self) -> str | None:
        """The template knob that sets the part's length (MEASURE_MAP "length"), unless it is also the width (a round
        part's diameter)."""
        if self.template is None or self.strategy != "template":
            return None
        mm = self.template.measure_map
        knob = mm.get("length")
        return knob if knob and knob != mm.get("width") else None

    def tapped_to_edge(self, ends: BreakEnds) -> float | None:
        """Length the photo shows from the intact end up to the user's broken-edge tap (mm), or None without a usable
        tap (none, both ends broken, or the tap is off the part's length)."""
        from services.agent import evidence

        if ends.length[0] == ends.length[1]:
            return None
        mo, top = self.mo.get("top"), self.measurements.get("top")
        if mo is None or top is None or mo.detection is None or not top.part_to_mat:
            return None
        taps = [t for t in evidence.user_taps(self) if t.get("kind") == "broken_edge"]
        if not taps:
            return None
        det = mo.detection
        H = mo.H_top if mo.H_top is not None else det.H
        Mi = np.linalg.inv(np.asarray(top.part_to_mat, dtype=np.float64))
        x0, _, x1, _ = ends.bounds
        out: list[float] = []
        for t in taps:
            mat = det.to_mm(np.array([[float(t["x"]), float(t["y"])]], dtype=np.float64), H)[0]
            part = Mi @ np.array([mat[0], mat[1], 1.0])
            a = ends.along(part[:2])
            d = a - x0 if ends.length[1] else x1 - a  # from the intact end
            if 0.0 < d <= (x1 - x0) + 2.0:
                out.append(d)
        return round(min(out), 2) if out else None

    def ask_stated_length(self) -> None:
        """A break that reaches an end of the part hides its length: no mirror restores it. Take the original length
        from the user (intent words, or one question; with a broken-edge tap only the missing piece), never from a
        model. The value is user-stated: it sets and locks the length knob, and the verifier treats it as stated, not
        observed. "skip" (or no answer) keeps the length inferred, as before."""
        knob = self.length_knob()
        top = self.measurements.get("top")
        if knob is None or top is None or self.spec is None or self.template is None:
            return
        ends = break_ends(self.spec, top)
        if ends is None or not ends.spans_length:
            return
        spec_p = next((p for p in self.template.params if p.name == knob), None)
        if spec_p is None:
            return
        seen = ends.bounds[2] - ends.bounds[0]

        def accept(sv: stated.StatedValue) -> str | None:
            why = stated.check_stated_length(
                sv.value_mm, sv.sigma_mm, knob_min=spec_p.min, knob_max=spec_p.max, broken_length_mm=seen
            )
            if why is not None:
                self.log(f"stated length refused: {why} ({sv.how})", "warn")
                return why
            m = Measured(value=sv.value_mm, source=Source.user_stated, sigma_mm=sv.sigma_mm,
                         evidence=Evidence(view="top", note=f"stated by the user ({sv.how}); not observed: the photo "
                                           "shows the broken part"))  # fmt: skip
            self.stated["length"] = m
            self.answers["length"] = sv.value_mm
            self.locked[knob] = f"the user stated the original length ({sv.value_mm:g} mm)"
            self.job.write_json("stated.json", {"length": m.model_dump(mode="json"), "knob": knob, "how": sv.how})
            return None

        with self.stage("ask", "The break reaches an end: asking how long the part was") as st:
            said = stated.parse_intent_length(self.job.input.intent)
            if said is not None and accept(said) is None:
                st.label = f"Length {said.value_mm:g} ± {said.sigma_mm:g} mm, stated in the request (not measured)"
                return
            to_edge = self.tapped_to_edge(ends)
            if to_edge is not None:
                u = Unknown(
                    id="length.missing",
                    question=f"The photo measures {to_edge:.1f} mm from the intact end to the broken edge you tapped. "
                    "How much is missing beyond that edge, in mm? (a ruler on the matching intact part is fine) — "
                    "or type 'skip' to leave the length inferred",
                    expects="text",
                    default="skip",
                )
            else:
                u = Unknown(
                    id="length.original",
                    question=f"The break reaches the end of the part, so the photo cannot show its length (it shows "
                    f"{seen:.1f} mm of the broken piece). How long was it before it broke? (mm, a ruler is fine) — "
                    "or measure the matching intact part, or type 'skip'",
                    expects="text",
                    default="skip",
                )
            raw = self.question(u)
            got = stated.parse_answer_length(raw)
            if got is None:
                self.log(f"could not read {raw!r} as a length; the length stays inferred", "warn")
                got = "skip"
            if got == "skip":
                st.status = "skip"
                st.label = "Length skipped: it stays inferred from the photo of the broken part (not verified)"
                return
            sv = stated.with_tap(to_edge, got) if to_edge is not None else got
            why = accept(sv)
            st.label = (
                f"Length not used: {why}"
                if why
                else f"Length {sv.value_mm:g} ± {sv.sigma_mm:g} mm, stated by the user (not measured)"
            )

    def apply_stated(self, code: str, values: dict[str, float]) -> dict[str, float]:
        """The knobs a user-stated dimension fixes, set to that value (snapped to the knob's step and range)."""
        if not self.stated:
            return values
        try:
            specs = {p.name: p for p in parse_params(code)}
        except ProgramError:
            return values
        mmap = template_measure_map(code, self.template if self.strategy == "template" else None)
        out = dict(values)
        for key, m in self.stated.items():
            knob = mmap.get(key)
            if knob is not None and knob in specs and knob in out:
                out[knob] = guards.snap(m.value, specs[knob])
        return out

    # ---- 4. plan ------------------------------------------------------------------------------------------------------------
    def plan(self) -> None:
        assert self.spec is not None
        if not self.opts.templates:
            with self.stage("plan", "Free code from the outline (template library switched off)") as st:
                self.template = None
                self.strategy = "free_code"
            return
        with self.stage("plan", "Choosing a template or free code") as st:
            names = ", ".join(f"{t.name} ({t.family.value})" for t in list_templates())
            req = ModelRequest(
                messages=[
                    {"role": "developer", "content": PLAN_PROMPT.format(templates=names)},
                    {"role": "user", "content": "PartSpec: " + self.spec.model_dump_json(exclude_none=True)},
                ],
                json_schema=PLAN_SCHEMA,
                schema_name="plan",
                mock_context={"partspec": self.spec.model_dump(mode="json"), "templates": self.templates_info()},
            )
            data: dict[str, Any] = {}
            try:
                out = self.call("plan", req)
                data = (out.json if out else None) or {}
            except ProviderError as exc:
                self.log(f"planner unavailable ({exc}); using the PartSpec template hint", "warn")
            chosen = data.get("template") or self.spec.template_hint
            strategy = data.get("strategy") or ("template" if chosen else "free_code")
            self.template = None
            if strategy == "template" and chosen:
                try:
                    self.template = get_template(str(chosen))
                except KeyError as exc:
                    self.log(f"planner chose {exc}; falling back to the family's template", "warn")
            if strategy == "template" and self.template is None:
                fam = [t for t in list_templates() if t.family == self.spec.family]
                self.template = fam[0] if fam else None
            if self.template is None:
                self.template = self.free_code_override()
            self.strategy = "template" if self.template is not None else "free_code"
            st.label = (
                f"Template: {self.template.name} ({self.template.title})"
                if self.template
                else "Free code from the outline"
            )

    # ---- 4b. reviewer round: start from the reviewed model ------------------------------------------------------------------
    def start_from_parent(self, rv: ReviewRound) -> Round:
        """A reviewer round skips understand / ask / plan: the parent's PartSpec, template and stated values are loaded
        (its measurements are redone on the same photos, so the mat frame is the same) and its program is rebuilt and
        verified as round 1. Then the pins are resolved on this job's own rectified photo."""
        from services.agent import evidence
        from services.agent.jobs import load_job

        if rv.parent_dir is None:
            raise _Finish("failed", {"error": f"reviewer round: the parent job {rv.parent_job} was not found"})
        parent = load_job(rv.parent_dir)
        notes = "; ".join(f'{p.id}: "{p.note}"' for p in rv.pins) + (f'; note: "{rv.note}"' if rv.note else "")
        self.log(f"Reviewer round {rv.round}: {len(rv.pins)} pin(s) on {rv.parent_job} — {notes or 'no notes'}")
        with self.stage("plan", f"Reviewer round {rv.round}: starting from the reviewed model") as st:
            spec_data, code = parent.read_json("partspec.json"), parent.read_text("part.py")
            if not spec_data or not code:
                st.status = "fail"
                st.label = f"Reviewer round {rv.round}: {rv.parent_job} has no PartSpec or part program"
                raise _Finish("failed", {"error": st.label})
            self.spec = PartSpec.model_validate(spec_data)
            done = next((e for e in reversed(parent.events) if e.t == "done"), None)
            summary = dict(done.summary) if done is not None else {}
            try:
                self.template = get_template(str(summary["template"])) if summary.get("template") else None
            except KeyError:
                self.template = None
            self.strategy = "template" if summary.get("strategy") == "template" and self.template else "free_code"
            if self.strategy == "free_code":
                self.template = None
            said = parent.read_json("stated.json") or {}
            if isinstance(said.get("length"), Mapping) and said.get("knob"):
                m = Measured.model_validate(said["length"])
                self.stated["length"] = m
                self.locked[str(said["knob"])] = f"the user stated the original length ({m.value:g} mm)"
                self.job.write_json("stated.json", said)
            evidence.apply_points(self)  # the user's taps on the parent's photo (points.json copied with the photos)
            self.enforce_measured(self.spec, self.measurements["top"])
            side_h = self.heights.get("side")
            if side_h is not None and side_h[1] != "round" and self.round_part() and self.measure_side("round"):
                self.save_measurements()
            self.save_spec()
            values = {str(k): float(v) for k, v in (parent.read_json("values.json") or {}).items()}
            st.label = (
                f"Reviewer round {rv.round}: {rv.parent_job}'s PartSpec and "
                + (f"{self.template.name} template" if self.template else "free-code program")
                + " (no new reading, no new plan)"
            )
        self.iteration += 1
        with self.stage("build", f"Rebuilding the reviewed model ({rv.parent_job}'s part.py)") as st:
            err = self.program_error(code)
            if err is not None:
                st.status = "fail"
                st.label = f"The reviewed program does not pass the sandbox check: {err}"
        if err is not None:
            rnd = Round(self.iteration, self.strategy, code, values, None, None, error=err)
            self.record_round(rnd, [], "reviewed model", prev=None)
            raise _Finish("failed", {"error": f"reviewer round: {err}"})
        specs = parse_params(code)
        values = {s.name: float(values.get(s.name, s.default)) for s in specs}
        rnd = self.evaluate(code, values, self.strategy, [], "reviewed model", prev=None)
        self.resolve_pins(rv, rnd)
        return rnd

    def resolve_pins(self, rv: ReviewRound, rnd: Round) -> None:
        """Each pin in mat mm (this job's rectified grid) and part mm (`part_to_mat`), and the local mismatch on the
        reviewed model ("before"). A pin that cannot be placed keeps its note with null numbers."""
        from services.review import pins as pinmath

        rect = self.job.read_json("rectified.json")
        mo, top = self.mo.get("top"), self.measurements.get("top")
        size = image_size(mo.rectified_png) if mo is not None and mo.rectified_png else None
        self.review_pins = []
        for pin in rv.pins:
            row: dict[str, Any] = {"id": pin.id, "u": pin.u, "v": pin.v, "note": pin.note, "mat_mm": None,
                                   "part_mm": None, "before_mm": None, "after_mm": None}  # fmt: skip
            if rect and size and top is not None and top.part_to_mat:
                mat = pinmath.uv_to_mat_mm(pin.u, pin.v, rect, size)
                part = pinmath.mat_to_part_mm(mat, top.part_to_mat)
                row["mat_mm"] = [round(mat[0], 3), round(mat[1], 3)]
                row["part_mm"] = [round(part[0], 3), round(part[1], 3)]
                row["before_mm"] = self.pin_mismatch(rnd, row)
            self.review_pins.append(row)
        self.save_review_pins()

    def pin_mismatch(self, rnd: Round | None, row: Mapping[str, Any]) -> float | None:
        from services.review import pins as pinmath

        part = row.get("part_mm")
        if rnd is None or rnd.out is None or part is None or "top" not in rnd.out.views:
            return None
        return pinmath.local_mismatch_mm(rnd.out.views["top"], (float(part[0]), float(part[1])))

    def save_review_pins(self, after: Round | None = None) -> None:
        """review_round.json: the pins with their mm positions and code's mismatch before (reviewed model) and after
        (the final best round)."""
        rv = self.opts.review
        if rv is None:
            return
        if after is not None:
            for row in self.review_pins:
                row["after_mm"] = self.pin_mismatch(after, row)
        self.job.write_json(
            "review_round.json",
            {"parent_job": rv.parent_job, "round": rv.round, "note": rv.note, "pins": self.review_pins},
        )

    def near_feature(self, part_mm: Sequence[float]) -> str | None:
        """The measured hole or slot a pin sits on or next to (within 3 mm of its edge), for the fixer's note."""
        top = self.measurements.get("top")
        if top is None:
            return None
        best: tuple[float, str] | None = None
        for h in top.holes:
            d = math.hypot(part_mm[0] - h.center_mm[0], part_mm[1] - h.center_mm[1]) - h.diameter.value / 2
            if best is None or d < best[0]:
                best = (d, h.id)
        for sl in top.slots:
            d = math.hypot(part_mm[0] - sl.center_mm[0], part_mm[1] - sl.center_mm[1]) - sl.length.value / 2
            if best is None or d < best[0]:
                best = (d, sl.id)
        return best[1] if best is not None and best[0] <= 3.0 else None

    def reviewer_text(self, rnd: Round, *, numeric: bool = True) -> str:
        """The reviewer's notes for a fixer prompt: one line per pin (code's local mismatch on `rnd`) + the general
        note. Empty outside a reviewer round."""
        rv = self.opts.review
        if rv is None:
            return ""
        lines: list[str] = []
        for row in self.review_pins:
            part = row.get("part_mm")
            where = f"at ({part[0]:.1f}, {part[1]:.1f}) mm" if part is not None else "(position not measurable)"
            near = self.near_feature(part) if part is not None else None
            m = self.pin_mismatch(rnd, row) if numeric else None
            said = f"local mismatch {m:.2f} mm" if m is not None else "local mismatch not measurable here"
            lines.append(f'Reviewer pin {row["id"]} {where}' + (f" near {near}" if near else "")
                         + f': "{row["note"]}" — {said}')  # fmt: skip
        if rv.note:
            lines.append(f'Reviewer note: "{rv.note}"')
        if not lines:
            return ""
        return (
            f"Reviewer round {rv.round}: a person looked at the model and says something is wrong (part-frame mm; "
            "each pin is a numbered red ring on the attached photo | model crops). Address these notes; code still "
            "decides pass/fail.\n" + "\n".join(lines)
        )

    def reviewer_images(self, rnd: Round) -> list[bytes]:
        from services.review import pins as pinmath

        if self.opts.review is None or rnd.out is None or "top" not in rnd.out.views:
            return []
        placed = [(int(r["id"]), (float(r["part_mm"][0]), float(r["part_mm"][1])))
                  for r in self.review_pins if r.get("part_mm") is not None]  # fmt: skip
        return pinmath.pin_crops(rnd.out.views["top"], placed) if placed else []

    def family_rules(self) -> list[dict[str, str]]:
        """Promoted rules for the part's family (a person approved each one); records their ids in
        lessons_used.json so later reviews of this job count for or against each rule."""
        if self.spec is None:
            return []
        try:
            rows = lessons.promoted_lessons(self._registry(), self.spec.family.value)
        except Exception:
            return []
        new = [r["id"] for r in rows if r["id"] not in self.lessons_used]
        if new:
            self.lessons_used += new
            self.job.write_json(
                "lessons_used.json", {"family": self.spec.family.value, "lesson_ids": self.lessons_used}
            )
        return rows

    # ---- 5–7. build, execute, verify ------------------------------------------------------------------------------------------
    def build_program(self, strategy: Strategy, feedback: tuple[str, str] | None = None) -> str:
        """Ask the builder for a part program; policy/compile/runtime errors are fed back for up to BUILD_RETRIES.
        `feedback` = (previous program, what code found wrong with its solid) starts the exchange from that program."""
        assert self.spec is not None
        tpl = self.template if strategy == "template" else None
        family = self.spec.family.value
        rules = [r["rule"] for r in self.family_rules()]
        p = prompt_loader.load("build")
        dev, user = p.render(
            template_name=tpl.name if tpl else "(none — write free code from the outline)",
            family=family,
            lessons=lessons.format_for_prompt(rules),
            partspec=self.spec.model_dump_json(exclude_none=True),
            template_source=tpl.code if tpl else "(none)",
        )
        error: str | None = feedback[1] if feedback else None
        last_code = feedback[0] if feedback else ""
        for attempt in range(BUILD_RETRIES + 1):
            messages = [{"role": "developer", "content": dev}, {"role": "user", "content": user}]
            if error:
                messages += [
                    {"role": "assistant", "content": f"```python\n{last_code}```"},
                    {"role": "user", "content": f"That program failed: {error}. Return the corrected program."},
                ]
            req = ModelRequest(
                messages=messages,
                mock_context={
                    "strategy": strategy,
                    "template": tpl.name if tpl else None,
                    "partspec": self.spec.model_dump(mode="json"),
                    "measurements": {v: m.model_dump(mode="json") for v, m in self.model_measurements().items()},
                    "answers": dict(self.answers),
                    "orbit_height_mm": self.orbit_height.value if self.orbit_height else None,
                    "previous_error": error,
                    "attempt": attempt,
                },
            )
            out = self.call("build", req)
            if out is None:
                raise RuntimeError("build reply discarded (stale context)")
            code = guards.extract_code(out.text)
            last_code = code
            error = self.program_error(code)
            if error is None:
                return self.template_program(tpl, code) if tpl is not None else code
            self.log(f"build attempt {attempt + 1}: {error}", "warn")
        raise _BuildFailed(error or "the builder returned no usable program", last_code)

    def template_program(self, tpl: Template, code: str) -> str:
        """In template mode the builder only fills PARAMS: code runs the template's own source with the builder's
        values for the knobs they share (clamped to the template's ranges). A rewritten body would otherwise be
        verified as the known template form (`known_form`) and its knobs mapped with the template's MEASURE_MAP.

        Live, 2026-10-29: for the knob (rerun) and the white-on-light cover the builder returned new geometry with the
        template's MEASURE_MAP (an extruded polyline; a cover without length/width knobs) under the template label."""
        values = {s.name: float(s.default) for s in parse_params(code)}
        out = set_defaults(tpl.code, {k: v for k, v in values.items() if k in {p.name for p in tpl.params}})
        if ast.dump(ast.parse(out)) == ast.dump(ast.parse(code)):
            return code  # the template with new defaults (comments, e.g. a part.py header, do not count)
        mine, theirs = {p.name for p in tpl.params}, set(values)
        what = f"; its PARAMS differ (+{sorted(theirs - mine)} -{sorted(mine - theirs)})" if mine != theirs else ""
        self.log(
            f"builder changed the {tpl.name} template's program{what}; code runs the template source with the "
            "builder's values for the shared knobs"
        )
        return out

    @staticmethod
    def program_error(code: str) -> str | None:
        violations = check_code(code)
        if violations:
            v = violations[0]
            return f"line {v.line}: {v.message}" + (f" (+{len(violations) - 1} more)" if len(violations) > 1 else "")
        try:
            specs = parse_params(code)
        except ProgramError as exc:
            return f"PARAMS: {exc.message}" + (f" (line {exc.line})" if exc.line else "")
        if not specs:
            return "PARAMS is empty — every dimension must be a parameter"
        return None

    def build_round(
        self, strategy: Strategy, *, iter_label: str, analysis: str = "", feedback: tuple[str, str] | None = None
    ) -> Round:
        """Build a new program with `strategy`, run it, verify it. Counts as one iteration. A free-code solid that code
        finds hollow where no photo looks is rebuilt once with that finding (`hollow_finding`)."""
        self.iteration += 1
        self.strategy = strategy
        label = "Writing the part program" + (
            f" from the {self.template.name} template"
            if strategy == "template" and self.template
            else " (free code from the measured outline)"
        )
        code = ""
        with self.stage("build", label) as st:
            try:
                code = self.build_program(strategy, feedback)
            except _BuildFailed as bf:
                st.status = "fail"
                st.label = f"Builder failed after {BUILD_RETRIES + 1} attempts: {bf.error}"
                code = bf.code
            if code and self.program_error(code) is None:
                st.label = f"Program ready: {len(parse_params(code))} PARAMS ({iter_label})"
        if not code or self.program_error(code) is not None:
            rnd = Round(self.iteration, strategy, code, {}, None, None, error="no runnable program")
            self.record_round(rnd, [], analysis or "builder failed", prev=self.current)
            return rnd
        values = self.apply_stated(code, {s.name: float(s.default) for s in parse_params(code)})
        rnd = self.evaluate(code, values, strategy, [], analysis or iter_label, prev=self.current)
        finding = self.hollow_finding(rnd) if strategy == "free_code" and not self.opts.single_shot else None
        if finding is not None and "hollow" not in self.rebuilt:
            self.rebuilt.add("hollow")
            self.log(f"free-code solid rejected by code: {finding}; rebuilding once with that finding", "warn")
            return self.build_round(
                strategy, iter_label="rebuild: solid where no photo looks", feedback=(code, finding)
            )
        return rnd

    def hollow_finding(self, rnd: Round) -> str | None:
        """The plate-thickness P0 test fails because the solid is hollow (full height, little material along vertical
        lines), not short: the program invented a cavity no photo can see. Code's finding for the builder, else None.

        Live, 2026-10-29: free code for the LEGO 2×4 reference hollowed out its underside with a 1.2–2 mm wall; the
        stated 9.6 mm body failed by 7.9 mm and no knob in the program's own ranges could close it."""
        v = rnd.verification
        si = rnd.exec_result.solid_info if rnd.exec_result is not None else None
        t = next((t for t in v.tests if t.id == "thickness"), None) if v is not None else None
        if t is None or si is None or t.passed or t.value is None or t.expected is None or not t.tol:
            return None
        if t.value >= HOLLOW_RATIO * t.expected or si.size_mm[2] < t.expected - t.tol:
            return None  # thin but not far off, or simply too short: a knob edit fixes that
        return (
            f"the verifier measured a plate thickness of {t.value:.2f} mm (the most common amount of material along "
            f"vertical lines through the footprint) on a solid {si.size_mm[2]:.2f} mm tall, but the part is "
            f"{t.expected:.2f} mm thick. No photo shows its underside or inside: model the body solid to that "
            "thickness and add only the features the PartSpec names"
        )

    def evaluate(
        self,
        code: str,
        values: dict[str, float],
        strategy: Strategy,
        edits: list[dict[str, Any]],
        analysis: str,
        prev: Round | None,
    ) -> Round:
        self.set_ctx(code, values)
        assert self.spec is not None
        res: ExecResult | None = None
        with self.stage("execute", "Running the program in the sandbox") as st:
            res = run_program(code, values, outputs=(), features=True)
            if not res.ok:
                st.status = "fail"
                st.label = f"Program failed: {res.error.short() if res.error else 'no solid'}"
            else:
                si = res.solid_info
                st.label = f"Solid ready in {res.ms} ms" + (
                    f": {si.size_mm[0]:.1f} × {si.size_mm[1]:.1f} × {si.size_mm[2]:.1f} mm" if si else ""
                )
        out: VerifyOutput | None = None
        with self.stage("verify", "Comparing the model with the photo") as st:
            out = verify(res, self.measurements, self.spec, photo_masks=self.masks, camera_views=self.camera_views(),
                         known_form=strategy == "template", stated=self.stated)  # fmt: skip
            v = out.verification
            st.label = (
                f"{'Verified' if v.verified else v.status.replace('_', ' ')}: "
                + format_views(v).split("; ")[0]
                + f"; tests {sum(t.passed for t in v.tests)}/{len(v.tests)}"
            )
        res.cleanup()
        rnd = Round(
            self.iteration, strategy, code, dict(values), res, out, error=res.error.short() if res.error else None
        )
        self.record_round(rnd, edits, analysis, prev)
        self.current = rnd
        if rnd.better_than(self.best):
            self.best = rnd
        return rnd

    def record_round(
        self, rnd: Round, edits: list[dict[str, Any]], analysis: str, prev: Round | None, *, artifacts: bool = True
    ) -> None:
        """Iteration + metric events and per-iteration artifacts (program, residual overlays)."""
        it = rnd.iter
        text = set_defaults(rnd.code, rnd.values) if rnd.values else rnd.code
        diff = ""
        if prev is not None and prev.code:
            before = set_defaults(prev.code, prev.values) if prev.values else prev.code
            diff = "".join(
                difflib.unified_diff(before.splitlines(True), text.splitlines(True), "before.py", "after.py", n=0)
            )[:6000]
        sha = code_sha(rnd.code) if rnd.code else None
        if text and artifacts:
            self.artifact("code", text.encode(), ".py", f"part.py after round {it}", iter=it)
        v = rnd.verification
        if rnd.out is not None and artifacts:
            for name, png in rnd.out.overlays.items():
                self.artifact("residual_heatmap", png, ".png", f"round {it}: {name.removesuffix('.png')}", iter=it)
        hd, iou = rnd.worst_hd, rnd.min_iou
        passed = sum(t.passed for t in v.tests) if v else 0
        total = len(v.tests) if v else 0
        ev = IterationEvent(
            job=self.job.id,
            iter=it,
            strategy=rnd.strategy,
            edits=edits,
            analysis=analysis[:2000],
            code_sha=sha,
            diff=diff,
            hausdorff_mm=hd,
            iou=iou,
            passed_tests=passed,
            total_tests=total,
        )
        self.job.emit(ev)
        self.iter_events.append(ev.model_dump(mode="json"))
        if v is not None:
            if hd is not None:
                self.job.emit(
                    MetricEvent(job=self.job.id, iter=it, name="hausdorff_mm", value=hd, threshold=HAUSDORFF_PASS_MM)
                )
            if iou is not None:
                self.job.emit(MetricEvent(job=self.job.id, iter=it, name="iou", value=iou, threshold=IOU_PASS, unit=""))
            if v.max_error_mm is not None:
                self.job.emit(MetricEvent(job=self.job.id, iter=it, name="max_error_mm", value=v.max_error_mm))
            self.job.emit(
                MetricEvent(job=self.job.id, iter=it, name="tests_passed", value=passed, threshold=total, unit="")
            )

    # ---- 8. fix loop ----------------------------------------------------------------------------------------------------------
    def openings(self, rnd: Round) -> tuple[int, int]:
        """(openings in the photo, openings in the model) from the registered top silhouettes."""
        if rnd.out is None or "top" not in rnd.out.views:
            return 0, 0
        vr = rnd.out.views["top"]
        ppm = vr.photo.frame.px_per_mm
        return count_openings(vr.photo.mask, ppm), count_openings(vr.model_mask, ppm)

    def hole_layout(self, rnd: Round) -> dict[str, list[list[float]]]:
        """Measured and model through-holes, both in the MODEL's top-view frame (x, y, diameter mm)."""
        top = self.measurements.get("top")
        if rnd.out is None or rnd.exec_result is None or top is None or "top" not in rnd.out.views:
            return {}
        vr = rnd.out.views["top"]
        if vr.matrix is None:
            return {}
        Mi = np.linalg.inv(np.asarray(vr.matrix, dtype=np.float64))
        measured = []
        for h in top.holes:
            q = Mi @ np.array([h.center_mm[0], h.center_mm[1], 1.0])
            measured.append([round(float(q[0]), 3), round(float(q[1]), 3), h.diameter.value])
        model = [
            [round(float(h["center_mm"][0]), 3), round(float(h["center_mm"][1]), 3), float(h["diameter_mm"])]
            for h in (rnd.exec_result.features or {}).get("holes", [])
            if h.get("through")
        ]
        return {"measured": measured, "model": model}

    def worst_spots(self, rnd: Round) -> list[dict[str, Any]]:
        """Where each failing view is worst, in the MODEL's own frame (so a template can say which knob shapes that
        region), plus whether the model has extra or missing material there."""
        out: list[dict[str, Any]] = []
        if rnd.out is None or rnd.exec_result is None or rnd.exec_result.solid_info is None:
            return out
        th = rnd.verification.thresholds if rnd.verification else None
        b = rnd.exec_result.solid_info.bbox_mm
        lo, hi = np.array(b[:3]), np.array(b[3:])
        centre, half = (lo + hi) / 2, np.maximum((hi - lo) / 2, 1e-6)
        for view, vr in rnd.out.views.items():
            m = vr.metrics
            if m.worst_point_mm is None or vr.matrix is None:
                continue
            if th is not None and m.hausdorff_mm <= th.hausdorff_mm:
                continue
            q = np.linalg.inv(np.asarray(vr.matrix, dtype=np.float64)) @ np.array([*m.worst_point_mm, 1.0])
            axes = {"top": "xy", "side_xz": "xz", "side_yz": "yz"}.get(vr.projection, "xy")
            idx = ["xyz".index(a) for a in axes]
            norm = []
            for k, val in zip(idx, q[:2], strict=True):
                norm.append(
                    float((val - lo[k]) / max(hi[k] - lo[k], 1e-6)) if k == 2 else float((val - centre[k]) / half[k])
                )
            out.append(
                {
                    "view": view,
                    "plane": axes,
                    "at_mm": [round(float(q[0]), 2), round(float(q[1]), 2)],
                    "norm": [round(norm[0], 3), round(norm[1], 3)],
                    "hausdorff_mm": round(m.hausdorff_mm, 3),
                    "kind": local_kind(vr.photo.mask, vr.model_mask, vr.photo.frame, m.worst_point_mm),
                }
            )
        return sorted(out, key=lambda w: -float(w["hausdorff_mm"]))

    def fix_context(self, rnd: Round, *, numeric: bool = True) -> dict[str, Any]:
        """Everything a fixer may know about a round: residual table, views, tests, worst spots in the model frame,
        hole layout, template regions, edit history. Never ground truth."""
        assert rnd.verification is not None
        v = rnd.verification
        specs = parse_params(rnd.code)
        tpl = self.template if rnd.strategy == "template" else None
        photo_n, model_n = self.openings(rnd)
        return {
            "strategy": rnd.strategy,
            "measure_map": template_measure_map(rnd.code, tpl),
            "params": [s.model_dump(mode="json") for s in specs],
            "values": dict(rnd.values),
            "verification": {
                "residuals": residual_table(v),
                "views": [m.model_dump(mode="json") for m in v.views],
                "tests": [t.model_dump(mode="json") for t in v.tests],
            }
            if numeric
            else {},
            "history": [dict(h) for h in self.history] if numeric else [],
            "measured_holes": photo_n,
            "model_holes": model_n,
            "worst": self.worst_spots(rnd),
            "holes": self.hole_layout(rnd),
            "regions": {k: [list(b) for b in bx] for k, bx in (dict(tpl.regions) if tpl else {}).items()},
            "vetoes": [x.model_dump(mode="json") for x in self.vetoes],
        }

    def propose_fix(self, rnd: Round) -> dict[str, Any] | None:
        assert self.spec is not None and rnd.verification is not None
        v = rnd.verification
        specs = parse_params(rnd.code)
        spots = self.worst_spots(rnd)
        hist = self.history[-2:]
        p = prompt_loader.load("fix")
        limits = ", ".join(f"{s.name} ±{guards.max_delta(s, rnd.values.get(s.name, s.default)):g}" for s in specs)
        hist_text = (
            "; ".join(
                f"round {h['iter']}: "
                + ", ".join(f"{e['param']} {e['from']:g}→{e['to']:g}" for e in h["edits"])
                + f" → Hausdorff {h['hd_before']}→{h['hd_after']} mm"
                for h in hist
            )
            or "(none)"
        )
        if self.vetoes:
            hist_text += "; judge vetoes: " + "; ".join(f"{x.feature}: {x.issue} ({x.severity})" for x in self.vetoes)
        numeric = self.opts.numeric_feedback
        if not numeric:  # B2: visual-only feedback — the overlays, no measured numbers
            hist_text = (
                "; ".join(
                    f"round {h['iter']}: " + ", ".join(f"{e['param']} {e['from']:g}→{e['to']:g}" for e in h["edits"])
                    for h in hist
                )
                or "(none)"
            )
        dev, user = p.render(
            limits=limits,
            param_names=", ".join(s.name for s in specs),
            residuals=format_residuals(v) if numeric else VISUAL_ONLY_NOTE,
            views=(
                format_views(v) + format_spots(spots) + format_gate_failures(v, rnd.out.view_gates if rnd.out else None)
            )
            if numeric
            else VISUAL_ONLY_NOTE,
            values=json.dumps(rnd.values),
            history=hist_text,
        )
        images = [fit_png(png)[0] for name, png in sorted((rnd.out.overlays if rnd.out else {}).items())][:2]
        user += self.prompt_extras(rnd, numeric=numeric)
        images += self.reviewer_images(rnd)
        req = ModelRequest(
            messages=[{"role": "developer", "content": dev}, {"role": "user", "content": user}],
            images=images,
            json_schema=FIX_SCHEMA,
            schema_name="fix",
            mock_context=self.fix_context(rnd, numeric=numeric),
        )
        try:
            out = self.call("fix", req)
        except ProviderError as exc:
            self.log(f"fixer unavailable ({exc})", "warn")
            return None
        return dict(out.json) if out is not None and isinstance(out.json, dict) else None

    def prompt_extras(self, rnd: Round, *, numeric: bool = True) -> str:
        """What a fixer prompt gets besides the residuals: the family rules a person approved, and in a reviewer round
        the reviewer's notes."""
        out = ""
        rules = self.family_rules()
        if rules:
            out += "\nFamily rules a person approved (from earlier reviews):\n" + lessons.format_for_prompt(
                [r["rule"] for r in rules]
            )
        said = self.reviewer_text(rnd, numeric=numeric)
        return out + ("\n" + said if said else "")

    def guard(self, base: Round, edits: Sequence[Mapping[str, Any]]) -> guards.GuardResult:
        """The guards for edits proposed against `base` (unknown names, ranges, step caps, no whole-outline rescale)."""
        specs = parse_params(base.code)
        mmap = template_measure_map(base.code, self.template if base.strategy == "template" else None)
        outline_params = [p for k, p in mmap.items() if k in guards.OUTLINE_KEYS]
        backing: dict[str, list[float]] = {}
        for r in base.verification.residuals if base.verification else []:
            rp = guards.residual_param(r.feature_id, r.quantity, mmap)
            if rp is not None:
                backing.setdefault(rp, []).append(r.delta_mm)
        return guards.guard_edits(
            edits,
            specs,
            base.values,
            outline_params=outline_params,
            residual_deltas={k: sum(v) / len(v) for k, v in backing.items()},
            locked=self.locked,
        )

    def fix_round(self, *, reviewer: bool = False) -> bool:
        """One fix iteration from the best round so far. Returns True when it improved on the best. `reviewer`: the
        round a reviewer round always runs (the person's notes lead, even when the model already verified)."""
        base = self.best
        assert base is not None and self.spec is not None
        self.iteration += 1
        before = base.score
        rv = self.opts.review
        tag = f"Reviewer round {rv.round} · " if reviewer and rv is not None else ""
        ask = "the reviewer's notes" if tag else "the largest residuals"
        with self.stage("fix", f"{tag}Round {self.iteration}: asking the fixer about {ask}") as st:
            proposal = self.propose_fix(base) or {"analysis": "no proposal", "edits": [], "code_patch": None}
            analysis = str(proposal.get("analysis", ""))
            patch = proposal.get("code_patch")
            g = self.guard(base, proposal.get("edits") or [])
            for rejected in g.rejected:
                self.log(f"guard: {rejected}", "warn")
            new_code, new_values = base.code, g.values(base.values)
            if patch and not g.applied:
                err = self.program_error(str(patch))
                if err is None:
                    new_code = guards.extract_code(str(patch))
                    pspecs = parse_params(new_code)
                    keep = {k: v for k, v in base.values.items() if k in {s.name for s in pspecs}}
                    new_values, _ = clamp(keep, pspecs)
                else:
                    self.log(f"code patch rejected by the sandbox check: {err}", "warn")
            changed = new_code != base.code or new_values != base.values
            st.label = f"{tag}Round {self.iteration}: " + (
                ", ".join(f"{e.param} {e.from_value:g}→{e.to:g}" for e in g.applied)
                or ("code patch" if new_code != base.code else "no applicable edit")
            )
        edits = [e.to_dict() for e in g.applied]
        if not changed:
            rnd = Round(
                self.iteration, base.strategy, base.code, dict(base.values), None, base.out, error="no applicable edit"
            )
            note = analysis + (" | rejected: " + "; ".join(g.rejected) if g.rejected else "")
            self.record_round(rnd, [], note, base, artifacts=False)
            self.history.append(
                {
                    "iter": self.iteration,
                    "edits": [],
                    "hd_before": base.worst_hd,
                    "hd_after": base.worst_hd,
                    "max_error_before": before,
                    "max_error_after": before,
                }
            )
            return False
        rnd = self.evaluate(new_code, new_values, base.strategy, edits, analysis, prev=base)
        improved = rnd.better_than(base)
        self.history.append(
            {
                "iter": self.iteration,
                "edits": edits,
                "hd_before": _r(base.worst_hd),
                "hd_after": _r(rnd.worst_hd),
                "max_error_before": _r(before),
                "max_error_after": _r(rnd.score),
                "improved": improved,
                "residuals_before": residual_keys(base.verification),
                "residuals_after": residual_keys(rnd.verification),
            }
        )
        return rnd.rank[0] < base.rank[0] or rnd.rank[1] < base.rank[1] - PROGRESS_EPS

    def photo_limited(self) -> list[str]:
        """Ids of the failing P0 tests when every one of them needs another photo rather than a model change
        (a thick part's length seen only from the top), else []. Fix rounds cannot settle those, so the loop stops."""
        b = self.best
        v = b.verification if b is not None else None
        if v is None or v.verified or v.status == "failed" or b is None or b.out is None:
            return []
        failing = [t.id for t in v.tests if t.priority == "P0" and not t.passed]
        if not failing or not all(t.endswith(PHOTO_LIMITED_SUFFIX) for t in failing):
            return []
        th = v.thresholds
        gates = b.out.view_gates
        for m in v.views:
            if m.hausdorff_mm > th.hausdorff_mm:
                return []
            if "iou" in gates.get(m.view, ["iou"]) and m.iou < th.iou:
                return []
            if "mean" in gates.get(m.view, []) and m.mean_mm > MEAN_GATE_MM:
                return []
        return failing

    def stop_if_photo_limited(self) -> bool:
        ids = self.photo_limited()
        if ids:
            self.log(
                f"stopping the fix rounds: the model matches the photo, but {', '.join(ids)} need a side photo (a top "
                "photo cannot show whether the ends stand the full stated height)",
                "warn",
            )
        return bool(ids)

    def agent_fix(self) -> None:
        """Agentic fixer sessions on the best round. A session that commits nothing better hands over to the next
        strategy (template -> free code), like the pipeline does; the round cap is the same."""
        from services.agent import agent_loop

        agent_loop.install_mock(replace=False)
        sessions = 0
        while self.best is not None and not self.best.verified and self.iteration < self.max_iters and sessions < 4:
            stop = self.over_budget()
            if stop:
                self.log(f"stopping the agent: {stop}", "warn")
                break
            if self.stop_if_photo_limited():
                break
            self.check_alive()
            sessions += 1
            # A template session leaves one round for the free-code alternative (code's fallback), unless the side
            # photo shows features an extruded outline cannot express.
            reserve = 1 if self.strategy == "template" and not self.side_taller_than_plate() else 0
            before = self.best
            agent_loop.AgentSession(self, self.max_iters - reserve).drive()
            if self.best.verified or self.iteration >= self.max_iters:
                break
            if self.best is not before and self.best.better_than(before) and self.iteration < self.max_iters - reserve:
                continue  # the session made progress and stopped early: a fresh session looks again
            strategy = self.strategy
            if not self.switch_strategy() or self.strategy == strategy:
                break

    def fix_loop(self) -> None:
        no_improve = 0
        limit = self.max_iters
        while self.best is not None and not self.best.verified and self.iteration < limit:
            stop = self.over_budget()
            if stop:
                self.log(f"stopping the loop: {stop}", "warn")
                break
            if self.stop_if_photo_limited():
                break
            self.check_alive()
            improved = self.fix_round()
            no_improve = 0 if improved else no_improve + 1
            if no_improve >= self.switch_after() and not self.best.verified and self.iteration < limit:
                no_improve = 0
                if not self.switch_strategy():
                    break

    def switch_after(self) -> int:
        """Rounds without progress before leaving the template: one more when the template still has knobs for the
        region where the model is worst."""
        b = self.best
        if b is None or self.template is None or b.strategy != "template":
            return NO_IMPROVE_SWITCH - 1
        spots = self.worst_spots(b)
        has_knob = any(knobs_at(self.template, s["plane"], *s["norm"]) for s in spots)
        return NO_IMPROVE_SWITCH if has_knob else NO_IMPROVE_SWITCH - 1

    def side_taller_than_plate(self) -> bool:
        side = self.measurements.get("side")
        return side is not None and any("clearly above the stated" in n for n in side.notes)

    def free_code_override(self) -> Template | None:
        """The template code uses when the planner picked free code: the PartSpec's hinted template, if it belongs to
        the part's family and the measured size fits its ranges. Model proposes, code decides: templates verify far
        more often than free code (PS vs PS-noTemplate); free code stays the fallback after rounds without progress,
        except for a broken or tall part (an extruded outline would copy the break or flatten the tall features).

        Live, 2026-10-29: the planner chose free code for the intact cupboard latch, hinge leaf, snap clip and cable
        clip although understand named their templates ("a template would discard measured fidelity"); all four ended
        best effort, 0.9–2.7 mm. The latch is neither broken nor tall, so only this rule moves it to its template."""
        assert self.spec is not None
        hinted = self.family_template(self.spec.template_hint)
        if hinted is None:
            return None
        misfit = self.template_misfit(hinted)
        if misfit is not None:
            self.log(f"planner chose free code and the hinted {hinted.name} template does not fit: {misfit}")
            return None
        why = (
            "the part is broken or taller than its plate, which free code from the outline cannot express"
            if self.spec.broken_region is not None or self.side_taller_than_plate()
            else "the measured size fits it; free code stays the fallback if the template stalls"
        )
        self.log(f"planner chose free code; code uses the hinted {hinted.name} template instead: {why}")
        return hinted

    def template_misfit(self, tpl: Template) -> str | None:
        """Why the measured size cannot be this template (a mapped size far outside its PARAMS range), else None."""
        top = self.measurements.get("top")
        if top is None or self.spec is None:
            return None
        th = self.spec.thickness
        return mock_brain.template_misfit(
            tpl, top.model_dump(mode="json"), th.value if th.source != Source.inferred else None
        )

    def family_template(self, name: str | None) -> Template | None:
        """The named template if it exists and belongs to the part's family, else None."""
        if not name or self.spec is None:
            return None
        try:
            tpl = get_template(str(name))
        except KeyError:
            return None
        return tpl if tpl.family == self.spec.family else None

    def switch_strategy(self) -> bool:
        """template → free code → ask the human. Returns False when the loop should stop."""
        cur = self.strategy
        if cur == "template" and self.spec is not None and self.spec.broken_region is not None:
            self.log(
                "no switch to free code: the part is broken, and an extrusion of the measured outline would copy the "
                "break into the replacement; the template (the intact shape) keeps probing"
            )
            return True
        if cur == "template" and self.side_taller_than_plate():
            self.log(
                "no switch to free code: the side photo shows features above the plate, which an extruded outline "
                "cannot express; the template keeps probing"
            )
            return True
        if cur == "template":
            self.switches.append("template → free_code")
            self.log("three rounds without progress: switching from the template to free code")
            self.build_round("free_code", iter_label="strategy switch: free code from the measured outline")
            return True
        if cur == "free_code" and self.best is None and self.opts.templates and self.spec is not None:
            fallback = self.family_template(self.spec.template_hint) or next(
                (t for t in list_templates() if t.family == self.spec.family), None
            )
            if fallback is not None and "free_code → template" not in self.switches:
                # every free-code program failed to produce a solid: the family's template is a known-good program
                self.switches.append("free_code → template")
                self.log(f"free code produced no valid solid; switching to the {fallback.name} template")
                self.template = fallback
                self.build_round("template", iter_label=f"strategy switch: the {fallback.name} template")
                return True
        if cur == "free_code":
            self.switches.append("free_code → human")
            self.strategy = "human"
            err = self.best.score if self.best else math.inf
            ans = self.question(
                Unknown(
                    id=f"stuck_{self.iteration}",
                    question=f"The model is still {err:.2f} mm off after {self.iteration} rounds. Keep trying, or accept "
                    "the best effort?",
                    expects="choice",
                    default="accept best effort",
                    choices=["accept best effort", "keep trying"],
                )
            )
            return str(ans) == "keep trying"
        return False

    # ---- 9. judge ---------------------------------------------------------------------------------------------------------------
    def run_judge(self, rnd: Round) -> JudgeResult | None:
        """One judge call on `rnd`. None when the judge is unavailable (no vetoes, no scorecard)."""
        assert self.spec is not None
        if rnd.out is None or "top" not in rnd.out.views:
            return None
        vr = rnd.out.views["top"]
        photo_n, model_n = self.openings(rnd)
        p = prompt_loader.load("judge")
        feats = [f"{f.kind} {f.id}" for f in self.spec.features] or ["outline only"]
        dev, user = p.render(
            features=", ".join(feats),
            intent=self.job.input.intent or "replacement part",
            side_note=", photo (side)" if "side" in self.mo else "",
        )
        from services.agent import evidence

        images = [fit_png(self.mo["top"].rectified_png or self.photos["top"])[0], mask_png(vr.model_mask)]
        images += evidence.hotspot_crops(rnd)  # photo | model, zoomed on the verifier's worst spots
        validity = rnd.verification.validity if rnd.verification is not None else None
        req = ModelRequest(
            messages=[{"role": "developer", "content": dev}, {"role": "user", "content": user}],
            images=images,
            json_schema=JUDGE_SCHEMA,
            schema_name="judge",
            mock_context={
                "features": feats,
                "photo_openings": photo_n,
                "model_openings": model_n,
                "measured_slots": len(self.measurements["top"].slots),
                "intent": self.job.input.intent,
                "hausdorff_mm": rnd.worst_hd,
                "valid": validity.is_valid if validity is not None else None,
                "min_wall_mm": validity.min_wall_mm if validity is not None else None,
            },
        )
        try:
            out = self.call("judge", req)
        except ProviderError as exc:
            self.log(f"judge unavailable ({exc}); no vetoes or scores recorded", "warn")
            return None
        if out is None:
            return None
        return parse_judge_reply(out.json if isinstance(out.json, Mapping) else {}, model=out.model, mode=out.mode)

    def judge_label(self, res: JudgeResult | None) -> str:
        if res is None:
            return "Judge unavailable: no vetoes, no scorecard"
        label = (
            "Judge: no vetoes"
            if not res.vetoes
            else "Judge vetoes: " + "; ".join(f"{x.feature}: {x.issue} ({x.severity})" for x in res.vetoes)
        )
        sl = res.score_label()
        return f"{label} · {sl}" if sl else label

    def run_judge_stage(self, label: str) -> None:
        """The judge stage on the best round: vetoes for the verifier, the scorecard to judge.json (advice only)."""
        assert self.best is not None
        with self.stage("judge", label) as st:
            res = self.run_judge(self.best)
            self.vetoes = res.vetoes if res is not None else []
            if res is not None:
                self.job.write_json("judge.json", res.to_json())
            st.label = self.judge_label(res)

    def judge(self) -> None:
        if self.best is None or self.best.out is None or self.best.verification is None:
            return
        if self.best.verification.status == "failed":
            return
        self.run_judge_stage("Independent judge looks at photo vs render (vetoes + advisory scorecard)")
        blocking = [x for x in self.vetoes if x.severity == "blocking"]
        if blocking and self.over_budget() is None:
            self.log("blocking veto: one more fix round with the judge's notes")
            self.fix_round()
            self.run_judge_stage("Judge looks again after the extra round")

    def label_unchecked(self, v: Verification, b: Round) -> Verification:
        """The verdict plus every knob no test checked (template defaults, inferred values): labelled inferred."""
        try:
            specs = parse_params(b.code)
        except ProgramError:
            return v
        mmap = template_measure_map(b.code, self.template)
        views = [m.view for m in v.views]
        unchecked = unchecked_values(specs, b.values, mmap, v.tests, views, stated=self.stated)
        return v.model_copy(update={"unchecked": unchecked})

    def final_verification(self) -> Verification | None:
        """The verdict: the best round's verification, re-run with the judge's vetoes when there are any."""
        b = self.best
        if b is None or b.out is None:
            return None
        v = b.out.verification
        if self.vetoes and b.exec_result is not None:
            out = verify(
                b.exec_result,
                self.measurements,
                self.spec,
                photo_masks=self.masks,
                vetoes=self.vetoes,
                camera_views=self.camera_views(),
                known_form=b.strategy == "template",
                stated=self.stated,
            )
            v = out.verification
            b.out = out
        v = self.label_unchecked(v, b)
        if self.mate_result is not None and self.mate_result.mates:
            from services.agent import mating as mating_photo

            with self.stage("verify", "Fits where it goes: the mating photo against the model") as st:
                v = mating_photo.check(self, v, b)
                st.label = "Fits where it goes: " + (mating_photo.summary_label(self.mate_result) or "not checked")
        b.out.verification = v
        self.job.write_json("verification.json", v)
        self.job.write_text("part.py", set_defaults(b.code, b.values))
        self.job.write_json("values.json", b.values)
        self.set_ctx(b.code, b.values)
        outline = model_outline(b.out, b.exec_result)
        if outline is not None:
            self.job.write_json("outline.json", outline)
        return v

    # ---- 10. package ----------------------------------------------------------------------------------------------------------
    def package(self, v: Verification | None) -> None:
        from services.agent import evidence
        from services.geom_worker.bake import BakeError, bake

        b = self.best
        if b is None or v is None or v.status == "failed" or not b.code:
            with self.stage("package", "Nothing to package") as st:
                st.status = "skip"
            return
        assert self.spec is not None
        with self.stage("package", "Exporting STL, STEP, 3MF, part.py, templates and cards") as st:
            made: list[str] = []
            try:
                bo = bake(b.code, b.values, ("stl", "step", "3mf", "view", "py"))
                kinds = {
                    "stl": ("stl", ".stl"),
                    "step": ("step", ".step"),
                    "3mf": ("threemf", ".3mf"),
                    "view": ("view", ".json"),
                    "py": ("code", ".py"),
                }
                for fmt, path in sorted(bo.files.items()):
                    kind, ext = kinds[fmt]
                    self.artifact(kind, path.read_bytes(), ext, f"{fmt.upper()} export" if fmt != "py" else "part.py")
                    made.append(fmt)
                if bo.facts is not None:
                    self.job.write_json("facts.json", bo.facts)
            except BakeError as exc:
                self.log(f"export failed: {exc}", "error")
            self.artifact("verification", v.model_dump_json(indent=2).encode(), ".json", "verification.json")
            self.artifact("partspec", self.spec.model_dump_json(indent=2).encode(), ".json", "partspec.json")
            outline = self.job.read_json("outline.json")
            extras: list[tuple[str, Callable[[], bool]]] = [
                ("template_pdf", lambda: self.template_pdf(outline, v)),
                ("repair_card", lambda: self.repair_card(v)),
                ("coupon", self.coupon),
                ("install_card", lambda: evidence.install_card(self)),
            ]
            for name, fn in extras:
                try:
                    if fn():
                        made.append(name)
                except Exception as exc:  # optional extras never fail the job
                    self.log(f"{name} skipped: {type(exc).__name__}: {exc}", "warn")
            try:
                self.artifact("zip", evidence.zip_bundle(self), ".zip", "everything in one zip (model, part.py, cards)")
                made.append("zip")
            except Exception as exc:
                self.log(f"zip skipped: {type(exc).__name__}: {exc}", "warn")
            ship = evidence.ship_decision(self, v)
            if self.reference_check:  # labelled: the files exist to measure the measurer, not to replace a part
                ship["purpose"] = "reference_check"
                ship["reason"] = f"measurement check of a reference object, not a replacement part: {ship['reason']}"
            self.job.write_json("ship.json", ship)
            st.label = "Exported: " + ", ".join(made) + f" · ship gate: {'open' if ship['ok'] else 'closed'}"

    def buy_or_print(self, v: Verification | None) -> None:
        """The buy-or-print card: code's print estimate from the exported mesh plus cited offers for the original
        (search-grounded lookup, `buy_lookup` model_call). Optional: it never changes the verdict or fails the job."""
        from services.agent import buy_or_print as bop

        if v is None or v.status == "failed" or self.best is None:
            return
        with self.stage("package", "Buy or print: print cost from the mesh, cited offers for the original") as st:
            try:
                stop = self.over_budget()
                if stop:
                    self.log(f"buy-or-print lookup skipped: {stop}", "warn")
                elif not bop.lookup_enabled():
                    stop = "PARTSMITH_BUY_LOOKUP=0 (benches never score it); the print side is still computed"
                    self.log(f"buy-or-print lookup skipped: {stop}")
                card = bop.job_card(self.job, lookup=stop is None)
                self.artifact("buy_or_print", card.model_dump_json(indent=2).encode(), ".json", "buy-or-print card")
                lk = card.lookup
                found = f"{len(lk.offers)} cited offer(s), {len(lk.places)} place(s)" if lk else "no lookup"
                grams = f"{card.prints[0].grams:.1f} g PLA" if card.prints else "no print estimate"
                st.label = f"Buy or print: {grams}; {found} ({card.mode})"
            except Exception as exc:  # an optional card never fails the job
                self.log(f"buy-or-print card skipped: {type(exc).__name__}: {exc}", "warn")
                st.status = "skip"

    def template_pdf(self, outline: dict[str, Any] | None, v: Verification) -> bool:
        from tools.mat.template_pdf import template_pdf

        if not outline:
            return False
        o, holes = outline["outline_mm"], outline["holes"]
        title = (self.spec.title if self.spec else "") or "PartSmith part"
        badge = "VERIFIED" if v.verified else "best effort"
        origin = self.job.input.origin.value
        pdf = template_pdf(
            o,
            holes,
            outline_dims(o, holes),
            title=f"{title} — 1:1 ({badge})",
            notes=[f"Job {self.job.id} · origin {origin} · print at 100 % and check the 50 mm bar"],
        )
        self.artifact("template_pdf", pdf, ".pdf", "1:1 paper template")
        return True

    def repair_card(self, v: Verification) -> bool:
        from services.media.repair_card import KeyDim, PrintSettings, RepairCardData, make_repair_card
        from services.registry import passport

        assert self.spec is not None
        pid = passport.job_id(self.job.id)  # the card's QR brings the part back (docs/API.md "Repair passport")
        top = self.measurements["top"]
        dims = [
            KeyDim("Length", top.length.value, top.length.source.value, top.length.sigma_mm),
            KeyDim("Width", top.width.value, top.width.source.value, top.width.sigma_mm),
            KeyDim(
                "Thickness", self.spec.thickness.value, self.spec.thickness.source.value, self.spec.thickness.sigma_mm
            ),
        ]
        for h in top.holes[:4]:
            dims.append(KeyDim(f"{h.id} Ø", h.diameter.value, h.diameter.source.value, h.diameter.sigma_mm))
        facts = self.job.read_json("facts.json") or {}
        card = RepairCardData(
            title=self.spec.title or "Replacement part",
            family=self.spec.family.value,
            key_dims=dims,
            verification=v,
            print_settings=PrintSettings(
                material=self.spec.fit.material,
                supports=facts.get("supports_needed"),
                orientation=str(facts.get("orientation", "")),
            ),
            origin=self.job.input.origin.value,
            provider_mode=self.summary({})["mode"],
            job_id=self.job.id,
            passport_id=pid,
            passport_url=f"{passport.web_base()}/p/{pid}",
        )
        self.artifact("repair_card", make_repair_card(card), ".pdf", f"printable repair card (passport {pid})")
        return True

    def coupon(self) -> bool:
        from services.geom_worker.bake import bake
        from services.media.coupon import coupon_from_partspec

        assert self.spec is not None
        try:
            code = coupon_from_partspec(self.spec)
        except ValueError:
            return False  # no hole, slot or bore to test
        bo = bake(code, {}, ("stl",))
        self.artifact("coupon", bo.files["stl"].read_bytes(), ".stl", "fit-test coupon (−0.2 / 0 / +0.2 mm)")
        return True

    # ---- 11. learn ------------------------------------------------------------------------------------------------------------
    @staticmethod
    def _registry() -> Any:
        from services.registry.store import get_registry

        return get_registry()

    def learn(self, v: Verification | None) -> None:
        assert self.spec is not None
        with self.stage("learn", "Recording lesson candidates (never auto-promoted)") as st:
            b = self.best
            cands = lessons.extract_candidates(
                job_id=self.job.id,
                family=self.spec.family.value,
                template=self.template.name if self.template else None,
                first_values=self.first_values if b and b.strategy == "template" else {},
                final_values=b.values if b else {},
                iterations=self.iter_events,
                verified=bool(v and v.verified),
                strategy_switches=self.switches,
                max_error_mm=v.max_error_mm if v else None,
                origin=self.job.input.origin.value,
            )
            try:
                ids = lessons.record(cands, self._registry())
            except Exception as exc:
                self.log(f"lessons not stored: {type(exc).__name__}: {exc}", "warn")
                ids = []
            st.label = f"{len(ids)} lesson candidate(s) stored for review" if ids else "No new lesson candidates"


class _BuildFailed(Exception):
    def __init__(self, error: str, code: str) -> None:
        super().__init__(error)
        self.error = error
        self.code = code


def _r(x: float | None) -> float | None:
    return None if x is None or not math.isfinite(x) else round(float(x), 4)


def stale(job: Job, ctx: str) -> bool:
    """True when `ctx` no longer matches the job's current state (the result must be discarded)."""
    return bool(ctx) and job.ctx != ctx


__all__ = [
    "DEFAULT_MAX_ITERS",
    "FixRun",
    "Round",
    "RunOptions",
    "count_openings",
    "make_runner",
    "model_outline",
    "photo_mask_for",
    "run_fix",
    "stale",
]
