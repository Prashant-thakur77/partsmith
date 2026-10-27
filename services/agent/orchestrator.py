"""The fix job (PLAN §3.2 Flow A, §6.2): photos on a mat → measured PartSpec → part program → verified loop → package.

    capture → measure → understand → ask → plan → build → execute → verify → fix (≤ max_iters) → judge → package → learn

`run_fix(job)` is the JobManager runner. Every stage emits `stage` events with a readable label; every model call goes
through `services/agent/providers` inside `job_context`, which emits `model_call` events (tokens, ms, $, mode). Each
event carries `ctx` = hash(photo shas, calibration, code, params): a model reply that comes back after the state moved
on is discarded. The model proposes; code decides: measured values override the model's, guards bound every edit, and
`verified` comes only from `services.verifier.verify`.
"""

from __future__ import annotations

import difflib
import json
import math
import time
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Literal

import cv2
import numpy as np
from partsmith_schemas import (
    ArtifactEvent,
    DoneEvent,
    IterationEvent,
    JudgeVeto,
    Measured,
    Measurements,
    MetricEvent,
    PartSpec,
    QuestionEvent,
    Source,
    StageEvent,
)
from partsmith_schemas.common import HAUSDORFF_PASS_MM, IOU_PASS
from partsmith_schemas.measurement import CaptureReport
from partsmith_schemas.partspec import SlotFeature, ThroughHole, Unknown
from partsmith_schemas.verification import Verification
from pydantic import ValidationError

from services.agent import guards, lessons, mock_brain, prompt_loader, providers
from services.agent.jobs import Job, JobCancelled, QuestionTimeout, Runner, context_hash
from services.agent.providers import Completion, ModelRequest, ProviderError
from services.agent.templates import Template, get_template, list_templates
from services.common import blobs
from services.geom_worker.program import ProgramError, clamp, code_sha, module_literals, parse_params, set_defaults
from services.geom_worker.sandbox import ExecResult, check_code, run_program
from services.metrology.calibrate import MatNotFoundError, detect_mat, estimate_pose
from services.metrology.capture_gate import run_gate
from services.metrology.measure import MeasureOutput, decode_image, measure_photo
from services.metrology.segment import ProviderSegmenter
from services.verifier.render import Frame, rasterize_polygon
from services.verifier.verify import PhotoMask, VerifyOutput, verify

Strategy = Literal["template", "free_code", "human"]
StageName = Literal[
    "capture", "measure", "understand", "ask", "plan", "build", "execute", "verify", "fix", "judge", "package", "learn"
]

DEFAULT_MAX_ITERS = 6
BUILD_RETRIES = 2  # inner retries when the program does not compile / run
NO_IMPROVE_SWITCH = 2  # rounds without improvement before switching strategy
IMPROVE_EPS_MM = 0.005
MASK_PX_PER_MM = 20.0
MODEL_IMAGE_MAX_PX = 1600
MIN_OPENING_MM2 = 2.0

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
        "notes": {"type": "string"},
    },
    "required": ["vetoes", "notes"],
    "additionalProperties": False,
}

TRIAGE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"retake": {"type": "boolean"}, "reason": {"type": "string"}},
    "required": ["retake", "reason"],
    "additionalProperties": False,
}

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
class RunOptions:
    """How one fix job runs. `answers` pre-fill questions by id (non-interactive runs)."""

    answers: dict[str, str | float] = field(default_factory=dict)
    question_timeout_s: float = 600.0
    max_iters: int | None = None
    wall_clock_s: float = 900.0
    mat_id: str | None = None
    package: bool = True
    learn: bool = True


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
    def rank(self) -> tuple[int, int, float]:
        """Ordering for "better": verified first, then fewer failing P0 tests, then the smaller max error."""
        v = self.verification
        if v is None or v.status == "failed" or v.max_error_mm is None:
            return (2, 1 << 30, math.inf)
        fails = sum(1 for t in v.tests if t.priority == "P0" and not t.passed)
        return (0 if v.verified else 1, fails, float(v.max_error_mm))

    def better_than(self, other: Round | None) -> bool:
        if other is None:
            return True
        a, b = self.rank, other.rank
        if a[:2] != b[:2]:
            return a[:2] < b[:2]
        return a[2] < b[2] - IMPROVE_EPS_MM

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


def fit_png(png: bytes, max_side: int = MODEL_IMAGE_MAX_PX) -> tuple[bytes, float]:
    """Downscale a PNG so its long side is at most `max_side`. Returns (png, scale)."""
    img = cv2.imdecode(np.frombuffer(png, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        return png, 1.0
    h, w = img.shape[:2]
    s = min(1.0, max_side / max(h, w))
    if s >= 1.0:
        return png, 1.0
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


def template_measure_map(code: str, template: Template | None) -> dict[str, str]:
    if template is not None:
        return dict(template.measure_map)
    try:
        lit = module_literals(code, ("MEASURE_MAP",)).get("MEASURE_MAP")
    except (SyntaxError, ValueError):
        lit = None
    return {str(k): str(v) for k, v in lit.items()} if isinstance(lit, dict) else {}


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
        self.understand()
        self.ask()
        self.plan()
        first = self.build_round(self.strategy, iter_label="first build")
        if first.score == math.inf and self.strategy == "template":
            self.switch_strategy()
        self.first_values = dict(first.values)
        self.fix_loop()
        self.judge()
        final = self.final_verification()
        if self.opts.package:
            self.package(final)
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
                self.job.emit(
                    ArtifactEvent(job=self.job.id, kind="photo", sha=key, url=blobs.url(key), label=f"{view} photo")
                )
            if "top" not in self.photos:
                st.status = "fail"
                st.label = "No top photo"
                raise _Finish("failed", {"retake_reason": "A top-view photo of the part on the mat is required."})
            reports: dict[str, CaptureReport] = {}
            for view in ("top", "side"):
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
        return ProviderSegmenter(providers.segment, family_word=hint.value.replace("_", " ") if hint else None)

    def measure_view(self, view: str, thickness_mm: float | None) -> MeasureOutput:
        with providers.job_context(self.job.id, self.job.emit, ctx=self.job.ctx):
            return measure_photo(
                self.photos[view],
                view,
                segmenter=self.segmenter(),
                thickness_mm=thickness_mm,
                origin=self.job.input.origin,
                mat_id=self.opts.mat_id,
            )

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
            if m is None:
                st.status = "fail"
                reason = mo.result.capture.retake_reason or "No part found on the mat's stage."
                st.label = f"Retake: {reason}"
                raise _Finish("failed", {"retake_reason": reason, "capture": mo.result.capture.model_dump(mode="json")})
            self.accept_view("top", mo, m)
            labels = [f"top {m.length.value:.2f} × {m.width.value:.2f} mm, {len(m.holes)} hole(s)"]
            if "side" in self.photos:
                ms = self.measure_view("side", m.width.value)
                self.store_view("side", ms)
                if ms.result.measurements is not None and ms.result.measurements.thickness is not None:
                    self.accept_view("side", ms, ms.result.measurements)
                    labels.append(f"side: thickness {ms.result.measurements.thickness.value:.2f} mm")
                else:
                    self.log("side photo could not be measured; continuing with the top view", "warn")
            cal = mo.result.calibration
            if cal is not None:
                self.calibration = {"mat_id": cal.mat_id, "H": cal.homography}
            self.save_measurements()
            self.set_ctx()
            st.label = "Measured " + "; ".join(labels) + f" (mask: {m.mask_source})"

    def accept_view(self, view: str, mo: MeasureOutput, m: Measurements) -> None:
        self.mo[view] = mo
        self.measurements[view] = m
        pm = photo_mask_for(mo, m)
        if pm is not None:
            self.masks[view] = pm

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

    def understand(self) -> None:
        with self.stage("understand", "Understanding the part (features, family, unknowns)") as st:
            top = self.measurements["top"]
            rect_png, s = fit_png(self.mo["top"].rectified_png or self.photos["top"])
            images = [rect_png]
            if "side" in self.mo and self.mo["side"].rectified_png:
                images.append(fit_png(self.mo["side"].rectified_png or b"")[0])
            p = prompt_loader.load("understand")
            meas_json = {v: m.model_dump(mode="json", exclude={"part_to_mat"}) for v, m in self.measurements.items()}
            dev, user = p.render(
                px_per_mm_inv=f"{1.0 / (self.mo['top'].px_per_mm * s):.3f}",
                templates=", ".join(t.name for t in list_templates()),
                measurements=json.dumps(meas_json),
                intent=self.job.input.intent,
                side_note=" and side view" if len(images) > 1 else "",
            )
            req = ModelRequest(
                messages=[{"role": "developer", "content": dev}, {"role": "user", "content": user}],
                images=images,
                json_schema=PartSpec.model_json_schema(),
                schema_name="PartSpec",
                strict=False,
                mock_context={
                    "measurements": {v: m.model_dump(mode="json") for v, m in self.measurements.items()},
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
            spec = self.enforce_measured(spec, top)
            cls = guards.refused_class(self.job.input.intent, spec.title, spec.intent)
            reason = spec.refusal or (guards.refusal_message(cls) if cls else None)
            self.spec = spec
            self.save_spec()
            if reason:
                st.label = f"Refused: {reason}"
                raise _Finish("refused", {"reason": reason})
            st.label = (
                f"{spec.family.value}: {len(spec.features)} feature(s), thickness {spec.thickness.value:.2f} mm "
                f"({spec.thickness.source.value}), {len(spec.unknowns)} question(s)"
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
            f = by_id.get(h.id)
            if isinstance(f, ThroughHole):
                if abs(f.diameter.value - h.diameter.value) > 1e-6 or tuple(f.center_mm) != tuple(h.center_mm):
                    changed.append(h.id)
                f.diameter, f.center_mm = h.diameter, h.center_mm
            else:
                spec.features.append(ThroughHole(id=h.id, center_mm=h.center_mm, diameter=h.diameter))
                changed.append(f"{h.id} added")
        for s in top.slots:
            f = by_id.get(s.id)
            if isinstance(f, SlotFeature):
                f.center_mm, f.length, f.width, f.angle_deg = s.center_mm, s.length, s.width, s.angle_deg
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
        fid, _, attr = qid.partition(".")
        for f in self.spec.features:
            if f.id == fid and isinstance(getattr(f, attr or "diameter", None), Measured):
                setattr(f, attr or "diameter", Measured(value=num, source=Source.user_stated, sigma_mm=0.2))

    # ---- 4. plan ------------------------------------------------------------------------------------------------------------
    def plan(self) -> None:
        assert self.spec is not None
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
            self.strategy = "template" if self.template is not None else "free_code"
            st.label = (
                f"Template: {self.template.name} ({self.template.title})"
                if self.template
                else "Free code from the outline"
            )

    # ---- 5–7. build, execute, verify ------------------------------------------------------------------------------------------
    def build_program(self, strategy: Strategy) -> str:
        """Ask the builder for a part program; policy/compile/runtime errors are fed back for up to BUILD_RETRIES."""
        assert self.spec is not None
        tpl = self.template if strategy == "template" else None
        family = self.spec.family.value
        try:
            rules = lessons.promoted_rules(self._registry(), family)
        except Exception:
            rules = []
        p = prompt_loader.load("build")
        dev, user = p.render(
            template_name=tpl.name if tpl else "(none — write free code from the outline)",
            family=family,
            lessons=lessons.format_for_prompt(rules),
            partspec=self.spec.model_dump_json(exclude_none=True),
            template_source=tpl.code if tpl else "(none)",
        )
        error: str | None = None
        last_code = ""
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
                    "measurements": {v: m.model_dump(mode="json") for v, m in self.measurements.items()},
                    "answers": dict(self.answers),
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
                return code
            self.log(f"build attempt {attempt + 1}: {error}", "warn")
        raise _BuildFailed(error or "the builder returned no usable program", last_code)

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

    def build_round(self, strategy: Strategy, *, iter_label: str, analysis: str = "") -> Round:
        """Build a new program with `strategy`, run it, verify it. Counts as one iteration."""
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
                code = self.build_program(strategy)
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
        values = {s.name: float(s.default) for s in parse_params(code)}
        return self.evaluate(code, values, strategy, [], analysis or iter_label, prev=self.current)

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
            out = verify(res, self.measurements, self.spec, photo_masks=self.masks)
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

    def propose_fix(self, rnd: Round) -> dict[str, Any] | None:
        assert self.spec is not None and rnd.verification is not None
        v = rnd.verification
        specs = parse_params(rnd.code)
        measure_map = template_measure_map(rnd.code, self.template if rnd.strategy == "template" else None)
        photo_n, model_n = self.openings(rnd)
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
        dev, user = p.render(
            limits=limits,
            param_names=", ".join(s.name for s in specs),
            residuals=format_residuals(v),
            views=format_views(v),
            values=json.dumps(rnd.values),
            history=hist_text,
        )
        images = [fit_png(png)[0] for name, png in sorted((rnd.out.overlays if rnd.out else {}).items())][:2]
        req = ModelRequest(
            messages=[{"role": "developer", "content": dev}, {"role": "user", "content": user}],
            images=images,
            json_schema=FIX_SCHEMA,
            schema_name="fix",
            mock_context={
                "strategy": rnd.strategy,
                "measure_map": measure_map,
                "params": [s.model_dump(mode="json") for s in specs],
                "values": dict(rnd.values),
                "verification": {
                    "residuals": residual_table(v),
                    "views": [m.model_dump(mode="json") for m in v.views],
                    "tests": [t.model_dump(mode="json") for t in v.tests],
                },
                "history": [dict(h) for h in self.history],
                "measured_holes": photo_n,
                "model_holes": model_n,
                "vetoes": [x.model_dump(mode="json") for x in self.vetoes],
            },
        )
        try:
            out = self.call("fix", req)
        except ProviderError as exc:
            self.log(f"fixer unavailable ({exc})", "warn")
            return None
        return dict(out.json) if out is not None and isinstance(out.json, dict) else None

    def fix_round(self) -> bool:
        """One fix iteration from the best round so far. Returns True when it improved on the best."""
        base = self.best
        assert base is not None and self.spec is not None
        self.iteration += 1
        before = base.score
        with self.stage("fix", f"Round {self.iteration}: asking the fixer about the largest residuals") as st:
            proposal = self.propose_fix(base) or {"analysis": "no proposal", "edits": [], "code_patch": None}
            analysis = str(proposal.get("analysis", ""))
            patch = proposal.get("code_patch")
            specs = parse_params(base.code)
            mmap = template_measure_map(base.code, self.template if base.strategy == "template" else None)
            outline_params = [p for k, p in mmap.items() if k in guards.OUTLINE_KEYS]
            g = guards.guard_edits(proposal.get("edits") or [], specs, base.values, outline_params=outline_params)
            for r in g.rejected:
                self.log(f"guard: {r}", "warn")
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
            st.label = f"Round {self.iteration}: " + (
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
            }
        )
        return improved

    def fix_loop(self) -> None:
        no_improve = 0
        limit = self.max_iters
        while self.best is not None and not self.best.verified and self.iteration < limit:
            stop = self.over_budget()
            if stop:
                self.log(f"stopping the loop: {stop}", "warn")
                break
            self.check_alive()
            improved = self.fix_round()
            no_improve = 0 if improved else no_improve + 1
            if no_improve >= NO_IMPROVE_SWITCH and not self.best.verified and self.iteration < limit:
                no_improve = 0
                if not self.switch_strategy():
                    break

    def switch_strategy(self) -> bool:
        """template → free code → ask the human. Returns False when the loop should stop."""
        cur = self.strategy
        if cur == "template":
            self.switches.append("template → free_code")
            self.log("two rounds without improvement: switching from the template to free code")
            self.build_round("free_code", iter_label="strategy switch: free code from the measured outline")
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
    def run_judge(self, rnd: Round) -> list[JudgeVeto]:
        assert self.spec is not None
        if rnd.out is None or "top" not in rnd.out.views:
            return []
        vr = rnd.out.views["top"]
        photo_n, model_n = self.openings(rnd)
        p = prompt_loader.load("judge")
        feats = [f"{f.kind} {f.id}" for f in self.spec.features] or ["outline only"]
        dev, user = p.render(
            features=", ".join(feats),
            intent=self.job.input.intent or "replacement part",
            side_note=", photo (side)" if "side" in self.mo else "",
        )
        images = [fit_png(self.mo["top"].rectified_png or self.photos["top"])[0], mask_png(vr.model_mask)]
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
            },
        )
        try:
            out = self.call("judge", req)
        except ProviderError as exc:
            self.log(f"judge unavailable ({exc}); no vetoes recorded", "warn")
            return []
        vetoes: list[JudgeVeto] = []
        for raw in ((out.json if out else None) or {}).get("vetoes", []):
            try:
                vetoes.append(JudgeVeto.model_validate(raw))
            except ValidationError:
                continue
        return vetoes

    def judge(self) -> None:
        if self.best is None or self.best.out is None or self.best.verification is None:
            return
        if self.best.verification.status == "failed":
            return
        with self.stage("judge", "Independent judge looks at photo vs render (veto only)") as st:
            self.vetoes = self.run_judge(self.best)
            blocking = [x for x in self.vetoes if x.severity == "blocking"]
            st.label = (
                "Judge: no vetoes"
                if not self.vetoes
                else "Judge vetoes: " + "; ".join(f"{x.feature}: {x.issue} ({x.severity})" for x in self.vetoes)
            )
        if blocking and self.over_budget() is None:
            self.log("blocking veto: one more fix round with the judge's notes")
            self.fix_round()
            with self.stage("judge", "Judge looks again after the extra round") as st:
                self.vetoes = self.run_judge(self.best)
                st.label = (
                    "Judge: no vetoes"
                    if not self.vetoes
                    else "Judge vetoes: " + "; ".join(f"{x.feature}: {x.issue} ({x.severity})" for x in self.vetoes)
                )

    def final_verification(self) -> Verification | None:
        """The verdict: the best round's verification, re-run with the judge's vetoes when there are any."""
        b = self.best
        if b is None or b.out is None:
            return None
        v = b.out.verification
        if self.vetoes and b.exec_result is not None:
            out = verify(b.exec_result, self.measurements, self.spec, photo_masks=self.masks, vetoes=self.vetoes)
            v = out.verification
            b.out = VerifyOutput(v, b.out.overlays, b.out.views, b.out.model_values)
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
            ]
            for name, fn in extras:
                try:
                    if fn():
                        made.append(name)
                except Exception as exc:  # optional extras never fail the job
                    self.log(f"{name} skipped: {type(exc).__name__}: {exc}", "warn")
            st.label = "Exported: " + ", ".join(made)

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

        assert self.spec is not None
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
        )
        self.artifact("repair_card", make_repair_card(card), ".pdf", "printable repair card")
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
