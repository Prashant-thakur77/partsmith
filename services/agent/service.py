"""Agent service facade. The REST API, the MCP server and the CLI call only these functions.

Jobs run through `JobManager` with the fix orchestrator as runner. Everything a caller needs about a job is reduced
from its event log and side files (`job_detail`), so a reloaded or replayed job looks exactly like a live one.
"""

from __future__ import annotations

import json
import mimetypes
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from partsmith_schemas import (
    ArtifactEvent,
    BakeResult,
    DataOrigin,
    FitCheckResult,
    JobInput,
    JobSummary,
    LogEvent,
    Measurements,
    ParamSpec,
    PartRecord,
    PartSpec,
    Pin,
    Provenance,
    Verification,
)
from partsmith_schemas.partspec import Family
from partsmith_schemas.registry import PartFacts, ProviderMode

from services.agent import providers
from services.agent.jobs import REPLAYS_DIR, Job, JobManager, context_hash, export_replay
from services.agent.orchestrator import ReviewRound, RunOptions, make_runner, png_bytes
from services.common import blobs
from services.common.images import decode_bgr
from services.common.paths import REPO_ROOT
from services.geom_worker.program import code_sha, parse_params, set_defaults

SAMPLES_DIRS = (REPO_ROOT / "data" / "synthetic" / "samples", REPO_ROOT / "data" / "synthetic" / "bench")
SYNC_QUESTION_TIMEOUT_S = 0.0  # synchronous runs never wait for a human: defaults are used
ASYNC_QUESTION_TIMEOUT_S = 600.0
PHOTO_EXTS = (".jpg", ".jpeg", ".png", ".webp")

_lock = threading.Lock()
_manager: JobManager | None = None


def manager() -> JobManager:
    """Process-wide JobManager (runs under $PARTSMITH_HOME/runs)."""
    global _manager
    with _lock:
        if _manager is None:
            _manager = JobManager()
        return _manager


def reset_manager(m: JobManager | None = None) -> None:
    """Swap the singleton (tests, or after changing PARTSMITH_HOME)."""
    global _manager
    with _lock:
        if _manager is not None and _manager is not m:
            _manager.shutdown()
        _manager = m


def _job(job_id: str) -> Job:
    job = manager().get(job_id)
    if job is None:
        raise KeyError(f"no job {job_id!r}")
    return job


def provider_mode() -> ProviderMode:
    """Mode label for a new job: live if any agent stage is live, replay if any replays, else mock."""
    modes = {providers.stage_mode(s) for s in ("understand", "build", "fix", "judge", "segment")}
    return "live" if "live" in modes else ("replay" if "replay" in modes else "mock")


# ------------------------------------------------------------------------------------------------- starting jobs


def _ext_for(data: bytes) -> str:
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return ".png"
    if data[:3] == b"\xff\xd8\xff":
        return ".jpg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ".webp"
    if data[:4] == b"RIFF" and data[8:12] == b"WAVE":
        return ".wav"
    if data[:4] == b"OggS":
        return ".ogg"
    if data[:3] == b"ID3" or data[:2] in (b"\xff\xfb", b"\xff\xf3", b"\xff\xf2"):
        return ".mp3"
    if data[4:8] == b"ftyp":
        if data[8:11] == b"M4A":
            return ".m4a"
        return ".mov" if data[8:10] == b"qt" else ".mp4"
    if data[:4] == b"\x1aE\xdf\xa3":
        return ".webm"
    return ".img"


def start_fix_job(
    photos: dict[str, bytes],
    job_input: JobInput,
    *,
    sync: bool = False,
    options: RunOptions | None = None,
    title: str = "",
    on_created: Callable[[Job], None] | None = None,
    points: Mapping[str, Sequence[Mapping[str, Any]]] | None = None,
) -> Job:
    """Store the photos (views: top required, side, mating; `orbit` a walk-around clip and `narration` a voice note
    about it) and run a fix job. `sync` runs it in this thread and never
    waits for answers (question defaults are used unless `options.answers` has them)."""
    if "top" not in photos:
        raise ValueError("a top-view photo is required")
    bad = [v for v in photos if v not in ("top", "side", "mating", "orbit", "narration")]
    if bad:
        raise ValueError(
            f"unknown photo view(s) {bad}; use top, side, mating, orbit (a short video), narration (a voice note "
            "about the walk-around)"
        )
    shas = {view: blobs.put(data, _ext_for(data)) for view, data in photos.items()}
    ji = job_input.model_copy(update={"kind": "fix", "photo_shas": shas})
    opts = options or RunOptions()
    if sync and options is None:
        opts.question_timeout_s = SYNC_QUESTION_TIMEOUT_S
    elif options is None:
        opts.question_timeout_s = ASYNC_QUESTION_TIMEOUT_S
    label = title or (
        ji.intent[:60] if ji.intent else f"Fix job ({ji.family_hint.value if ji.family_hint else 'part'})"
    )
    if ji.origin == DataOrigin.synthetic and "synthetic" not in label.lower():
        label += " (synthetic)"
    job = manager().create("fix", ji, title=label, provider_mode=provider_mode())
    if points:  # user taps on features (photo pixels), read by the orchestrator's points pass
        job.write_json("points.json", {v: [dict(p) for p in pts] for v, pts in points.items()})
    runner = make_runner(opts)
    if on_created is not None:
        on_created(job)
    if sync:
        manager().run_sync(job, runner)
    else:
        manager().start(job, runner)
    return job


REVIEW_TITLE_RE = r" · review round \d+$"
# Capture questions a reviewer round answers with their defaults: the parent already passed them on the same photos.
REVIEW_ANSWERS: dict[str, str | float] = {"capture.retake": "continue", "capture.retake.mask": "continue"}


def start_review_job(
    parent_id: str,
    round: int,
    pins: Sequence[Pin],
    note: str,
    *,
    sync: bool = False,
    on_created: Callable[[Job], None] | None = None,
) -> Job:
    """A reviewer round: a new fix job linked to `parent_id` (live or replay) that reuses its photos and starts from
    its model, with the reviewer's pins and note for the fixer. The parent is only read; a replay's directory is never
    written. KeyError when the parent is unknown, ValueError when it cannot be reviewed (no program, photos missing)."""
    import re

    parent = _job(parent_id)
    if not parent.finished or parent.summary.status != "done":
        raise ValueError(f"job {parent_id} is {parent.summary.status}; only finished jobs can be reviewed")
    if not parent.read_text("part.py") or not parent.read_json("partspec.json"):
        raise ValueError(f"job {parent_id} has no part program to start from")
    missing = [v for v, key in parent.input.photo_shas.items() if not blobs.exists(key)]
    if "top" not in parent.input.photo_shas or missing:
        raise ValueError(f"job {parent_id}: photo(s) {missing or ['top']} not available to rerun")
    photos = {v: blobs.get(key) for v, key in parent.input.photo_shas.items()}
    spec = parent.read_json("partspec.json") or {}
    thick = (spec.get("thickness") or {}) if isinstance(spec.get("thickness"), dict) else {}
    thickness_mm = parent.input.thickness_mm
    if thickness_mm is None and thick.get("source") == "user_stated":
        thickness_mm = float(thick["value"])  # the parent's answer, so the photos are measured at the same height
    ji = parent.input.model_copy(
        update={"parent_job": parent.id, "review_round": int(round), "thickness_mm": thickness_mm}
    )
    state = parent.read_json("state.json") or {}
    mat_id = (state.get("calibration") or {}).get("mat_id")
    opts = RunOptions(
        review=ReviewRound(parent.id, int(round), list(pins), note, parent_dir=parent.dir),
        mat_id=str(mat_id) if mat_id else None,
        answers=dict(REVIEW_ANSWERS),
        question_timeout_s=SYNC_QUESTION_TIMEOUT_S if sync else ASYNC_QUESTION_TIMEOUT_S,
    )
    base = re.sub(REVIEW_TITLE_RE, "", parent.summary.title or "Fix job")
    points = parent.read_json("points.json")
    return start_fix_job(photos, ji, sync=sync, options=opts, title=f"{base} · review round {int(round)}",
                         on_created=on_created, points=points if isinstance(points, Mapping) else None)  # fmt: skip


# ------------------------------------------------------------------------------------------------- demo samples


@dataclass
class SampleData:
    id: str
    meta: dict[str, Any]
    photos: dict[str, bytes] = field(default_factory=dict)
    path: Path | None = None


def _read_sample_dir(path: Path) -> SampleData:
    """Folder format (data/synthetic/...): top.jpg (+ side, mating), meta.json. gt.yaml is never read here."""
    meta = json.loads((path / "meta.json").read_text()) if (path / "meta.json").exists() else {}
    photos: dict[str, bytes] = {}
    for view in ("top", "side", "mating"):
        for ext in PHOTO_EXTS:
            p = path / f"{view}{ext}"
            if p.exists():
                photos[view] = p.read_bytes()
                break
    return SampleData(str(meta.get("id") or path.name), meta, photos, path)


def find_sample(sample_id: str) -> Path:
    for base in SAMPLES_DIRS:
        p = base / sample_id
        if (p / "meta.json").exists():
            return p
    known = [d["id"] for d in list_demo_samples()]
    import difflib

    close = difflib.get_close_matches(sample_id, known, n=3)
    raise KeyError(f"no sample {sample_id!r}" + (f" (closest: {', '.join(close)})" if close else ""))


def load_sample(path: Path) -> SampleData:
    """tools.synth.load_sample when available (same folder format); the direct reader covers PNG photos and folders
    the synth loader does not accept."""
    try:
        from tools.synth import load_sample as synth_load

        s = synth_load(path)
        meta: dict[str, Any] = s.meta.to_dict()
        if "top" in s.photos:
            return SampleData(str(meta.get("id") or path.name), meta, dict(s.photos), path)
    except Exception:
        pass
    return _read_sample_dir(path)


def sample_job_input(meta: dict[str, Any]) -> JobInput:
    hint = meta.get("family_hint")
    mat_id = str(meta.get("mat_id") or "")
    return JobInput(
        kind="fix",
        intent=str(meta.get("intent") or ""),
        thickness_mm=meta.get("user_thickness_mm"),
        family_hint=Family(str(hint)) if hint in Family.__members__ else None,
        origin=DataOrigin.synthetic,
        mat_kind="paper" if mat_id.startswith("paper") else "screen",
        # a bundled reference object (ID-1 card, AA cell …) is a measurement check, set here by the server only
        purpose="reference_check" if meta.get("kind") == "reference_object" else "repair",
    )


def start_demo_job(
    sample_id: str,
    *,
    sync: bool = False,
    options: RunOptions | None = None,
    on_created: Callable[[Job], None] | None = None,
) -> Job:
    """Run a bundled synthetic sample (labelled synthetic everywhere)."""
    sample = load_sample(find_sample(sample_id))
    title = f"{sample.meta.get('title') or sample.id} (synthetic sample)"
    opts = options
    if opts is None and sample.meta.get("mat_id"):
        opts = RunOptions(
            mat_id=str(sample.meta["mat_id"]),
            question_timeout_s=SYNC_QUESTION_TIMEOUT_S if sync else ASYNC_QUESTION_TIMEOUT_S,
        )
    ji = sample_job_input(sample.meta)
    return start_fix_job(sample.photos, ji, sync=sync, options=opts, title=title, on_created=on_created)


def list_demo_samples() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for base in SAMPLES_DIRS:
        if not base.exists():
            continue
        for d in sorted(base.iterdir()):
            meta_p = d / "meta.json"
            if not meta_p.exists() or d.name in seen:
                continue
            meta = json.loads(meta_p.read_text())
            seen.add(d.name)
            out.append(
                {
                    "id": str(meta.get("id") or d.name),
                    "title": str(meta.get("title") or d.name),
                    "family_hint": meta.get("family_hint"),
                    "kind": meta.get("kind", "template"),
                }
            )
    return out


# ------------------------------------------------------------------------------------------------- job detail


def _measurements(job: Job) -> dict[str, Any]:
    data = job.read_json("measurements.json") or {}
    return {v: Measurements.model_validate(m).model_dump(mode="json") for v, m in data.items()}


def current_ctx(job: Job) -> str:
    state = job.read_json("state.json") or {}
    return str(state.get("ctx") or job.ctx or "")


def _review_of(job: Job) -> dict[str, Any] | None:
    """{"status", "round", "root_job"} of the review chain the job is in, or None (not a job to review)."""
    try:
        from services.review.store import review_of

        return review_of(job)
    except Exception:  # the review badge is optional on the job page
        return None


def detail_of(job: Job) -> dict[str, Any]:
    """JobDetail (docs/API.md) reduced from the event log + side files."""
    events = [e.model_dump(mode="json", exclude_none=True) for e in job.events]
    spec = job.read_json("partspec.json")
    ver = job.read_json("verification.json")
    code = job.read_text("part.py")
    params: list[dict[str, Any]] = []
    if code:
        try:
            params = [p.model_dump(mode="json") for p in parse_params(code)]
        except Exception:
            params = []
    ctx = current_ctx(job)
    artifacts: dict[str, str] = {}
    for e in job.events:
        if e.t != "artifact":
            continue
        if e.kind == "preview" and ctx and e.ctx != ctx:
            continue  # a preview of an older state is stale
        artifacts[e.kind] = e.url
    q = job.pending_question()
    judge = job.read_json("judge.json")
    return {
        "judge": judge if isinstance(judge, dict) else None,  # the judge's advisory scorecard (never the verdict)
        "review": _review_of(job),
        "summary": job.summary.model_dump(mode="json"),
        "events": events,
        "partspec": PartSpec.model_validate(spec).model_dump(mode="json") if spec else None,
        "measurements": _measurements(job),
        "verification": Verification.model_validate(ver).model_dump(mode="json") if ver else None,
        "code": code,
        "params": params,
        "values": job.read_json("values.json") or {},
        "artifacts": artifacts,
        "question": q.model_dump(mode="json") if q is not None and not job.finished else None,
    }


def job_detail(job_id: str) -> dict[str, Any]:
    return detail_of(_job(job_id))


def get_job(job_id: str) -> Job:
    return _job(job_id)


def list_jobs(limit: int = 50) -> list[JobSummary]:
    return manager().list(limit)


def answer(job_id: str, qid: str, value: str | float, via: str = "text") -> JobSummary:
    job = _job(job_id)
    job.answer(qid, value, via)
    return job.summary


def cancel(job_id: str) -> JobSummary:
    job = _job(job_id)
    job.cancel()
    return job.summary


# ------------------------------------------------------------------------------------------------- bake / edit


def _program(job: Job) -> tuple[str, dict[str, float]]:
    code = job.read_text("part.py")
    if not code:
        raise KeyError(f"job {job.id} has no part program yet")
    values = {k: float(v) for k, v in (job.read_json("values.json") or {}).items()}
    return code, values


def _bake_result(
    code: str, params: dict[str, float], formats: tuple[str, ...], slug: str, passport: str | None = None
) -> BakeResult:
    from services.geom_worker.bake import bake

    bo = bake(code, params, formats, passport=passport)
    exts = {"stl": ".stl", "step": ".step", "3mf": ".3mf", "glb": ".glb", "view": ".json", "py": ".py"}

    def url_for(fmt: str, path: Path) -> str:
        return blobs.url(blobs.put(path.read_bytes(), exts.get(fmt, path.suffix)))

    return bo.to_bake_result(slug, url_for)


def job_params(job_id: str) -> tuple[list[ParamSpec], dict[str, float]]:
    """The job's knobs before publishing: PARAMS of its current part program and the values it holds now (what a
    fit preset is applied on top of, like a published part's defaults)."""
    code, values = _program(_job(job_id))
    specs = parse_params(code)
    return specs, {s.name: float(values.get(s.name, s.default)) for s in specs}


def bake_job(
    job_id: str, params: dict[str, float], formats: tuple[str, ...] = ("view",), *, passport: str | None = None
) -> BakeResult:
    """Re-bake the job's current part program with `params` (clamped to PARAMS). Does not change the job.
    `passport` debosses that id where it is safe (geom_worker/passport_mark.py); the report is stored with the bake."""
    job = _job(job_id)
    code, values = _program(job)
    return _bake_result(code, {**values, **params}, tuple(formats), job.summary.part_slug or job.id, passport)


def edit(
    job_id: str, *, text: str | None = None, audio: bytes | None = None, mime: str = "audio/wav"
) -> dict[str, Any]:
    """Voice or text edit → clamped parameter edits → new values + re-bake (docs/API.md /edit shape)."""
    from services.media.voice import transcribe_and_map

    job = _job(job_id)
    code, values = _program(job)
    source: bytes | str
    if audio is not None:
        source = audio
    elif text is not None:
        source = text
    else:
        raise ValueError("an edit needs text or audio")
    specs = parse_params(code)
    spec_data = job.read_json("partspec.json") or {}
    with providers.job_context(job.id, job.emit, ctx=job.ctx or current_ctx(job)):
        res = transcribe_and_map(source, specs, values, mime=mime, part_title=str(spec_data.get("title", "")))
    out = res.to_dict()
    new_values = dict(values)
    for e in res.edits:
        new_values[e.param] = e.to
    bake: BakeResult | None = None
    if res.edits:
        bake = _bake_result(code, new_values, ("view", "stl"), job.summary.part_slug or job.id)
        new_values = dict(bake.params)
        job.write_json("values.json", new_values)
        job.write_text("part.py", set_defaults(code, new_values))
        state = job.read_json("state.json") or {}
        cal = state.get("calibration") or {}
        job.ctx = context_hash(job.input.photo_shas, cal, code_sha(code), new_values)
        job.write_json("state.json", {**state, "ctx": job.ctx})
        desc = ", ".join(f"{e.param} {e.from_value:g}→{e.to:g}" for e in res.edits)
        job.emit(
            LogEvent(job=job.id, msg=f"edit ({res.transcript_mode}): {res.transcript!r} → {desc} (not re-verified)")
        )
        for kind, fmt in (("view", "view"), ("stl", "stl")):
            url = bake.artifacts.get(fmt)
            if url:
                key = url.rsplit("/", 1)[-1]
                job.emit(ArtifactEvent(job=job.id, kind=kind, sha=key, url=url, label=f"after edit: {desc}"))
    out["bake"] = bake.model_dump(mode="json") if bake else None
    out["values"] = new_values
    return out


# ------------------------------------------------------------------------------------------------- preview


def _render_on_rectified(job: Job) -> tuple[bytes, bytes] | None:
    """(rectified top photo, model silhouette drawn on the same rectified grid) for the 'see the fix' preview."""
    rect = job.read_json("rectified.json")
    outline = job.read_json("outline.json")
    meas = (job.read_json("measurements.json") or {}).get("top")
    if not rect or not outline or not meas:
        return None
    photo = blobs.get(rect["sha"])
    try:
        img = decode_bgr(photo)
    except ValueError:
        return None
    M = np.asarray(meas["part_to_mat"], dtype=np.float64)
    ppm = float(rect["px_per_mm"])
    origin = np.asarray(rect["origin_mm"], dtype=np.float64)

    def to_px(pts: Any) -> np.ndarray[Any, Any]:
        p = np.asarray(pts, dtype=np.float64)
        mat = p @ M[:2, :2].T + M[:2, 2]
        return np.asarray(np.round(((mat - origin) * ppm - 0.5) * 16), dtype=np.int32)

    canvas = np.full(img.shape, 255, np.uint8)
    cv2.fillPoly(canvas, [to_px(outline["outline_mm"])], (70, 140, 230), cv2.LINE_AA, shift=4)
    for h in outline.get("holes", []):
        c = to_px([h["center_mm"]])[0]
        r = round(float(h["diameter_mm"]) / 2 * ppm * 16)
        cv2.circle(canvas, (int(c[0]), int(c[1])), r, (255, 255, 255), -1, cv2.LINE_AA, shift=4)
    return photo, png_bytes(canvas)


def preview(job_id: str) -> dict[str, Any]:
    """'See the fix': Muse Image (live) or a labelled mock composite. Discarded if the job changed meanwhile."""
    from services.media.preview import see_the_fix

    job = _job(job_id)
    pair = _render_on_rectified(job)
    if pair is None:
        raise KeyError(f"job {job_id} has no verified outline or rectified photo to preview")
    ctx = current_ctx(job)
    spec = job.read_json("partspec.json") or {}
    with providers.job_context(job.id, job.emit, ctx=ctx):
        res = see_the_fix(pair[0], pair[1], prompt_hint=str(spec.get("intent", "")))
    if current_ctx(job) != ctx:
        return {"url": "", "label": res.label, "mode": res.mode, "stale": True}
    ext = mimetypes.guess_extension(res.mime) or ".png"
    key = blobs.put(res.image, ext)
    job.emit(ArtifactEvent(job=job.id, kind="preview", sha=key, url=blobs.url(key), label=res.label, ctx=ctx))
    return {"url": blobs.url(key), "label": res.label, "mode": res.mode}


# ------------------------------------------------------------------------------------------------- fit check / measure


def fit_outline(job_id: str, mat_id: str) -> dict[str, Any]:
    from services.metrology.fit_check import fit_outline_for

    job = _job(job_id)
    outline = job.read_json("outline.json")
    if not outline:
        raise KeyError(f"job {job_id} has no model outline yet")
    return fit_outline_for(outline["outline_mm"], outline.get("holes", []), mat_id)


def fit_check(job_id: str, photo: bytes, mat_id: str) -> dict[str, Any]:
    from services.metrology.fit_check import fit_check as run_fit_check

    job = _job(job_id)
    fo = fit_outline(job_id, mat_id)
    outline = job.read_json("outline.json") or {}
    out = run_fit_check(photo, mat_id, fo["outline_mm"], fo["holes"], thickness_mm=outline.get("thickness_mm"))
    key = blobs.put(out.overlay_png, ".png")
    res: FitCheckResult = out.result.model_copy(update={"overlay_url": blobs.url(key)})
    data: dict[str, Any] = res.model_dump(mode="json")
    job.emit(
        LogEvent(
            job=job.id,
            msg=f"screen fit check on {mat_id}: {'PASS' if res.passed else 'FAIL'} "
            + (
                f"(IoU {res.iou:.3f}, Hausdorff {res.hausdorff_mm:.2f} mm)"
                if res.hausdorff_mm is not None
                else "(not compared)"
            ),
        )
    )
    if job.summary.part_slug:
        try:
            from services.registry.store import get_registry

            get_registry().add_fit_report(
                job.summary.part_slug, "screen_fit_check", "pass" if res.passed else "fail", {**data, "job_id": job.id}
            )
        except Exception:
            pass
    return data


def measure(
    photo: bytes, view: str = "top", *, thickness_mm: float | None = None, mat_id: str | None = None
) -> dict[str, Any]:
    """Stateless measurement of one photo: MeasureResult + overlay_url (blobs stored, shas filled)."""
    from services.metrology.measure import measure_photo
    from services.metrology.segment import ProviderSegmenter

    source = "mock-threshold" if providers.stage_mode("segment") == "mock" else "sam-3.1"  # a mock mask says so
    mo = measure_photo(
        photo, view, segmenter=ProviderSegmenter(providers.segment, source=source), thickness_mm=thickness_mm,
        mat_id=mat_id,
    )  # fmt: skip
    r = mo.result
    overlay = blobs.put(mo.overlay_png, ".png")
    r.overlay_sha = overlay
    if mo.rectified_png:
        r.rectified_sha = blobs.put(mo.rectified_png, ".png")
    if mo.mask_png:
        r.mask_sha = blobs.put(mo.mask_png, ".png")
    data: dict[str, Any] = r.model_dump(mode="json")
    data["overlay_url"] = blobs.url(overlay)
    return data


# ------------------------------------------------------------------------------------------------- publish / replays


def _slugify(text: str) -> str:
    import re

    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return s[:48] or "part"


def publish(job_id: str, *, slug: str | None = None, note: str = "") -> PartRecord:
    """Turn a finished job's part program into a registry part (origin, provider mode and builder kept). `note` is
    added to the provenance (an accepted review: "best effort, accepted by a person")."""
    from services.registry.store import get_registry

    job = _job(job_id)
    code, values = _program(job)
    ver_data = job.read_json("verification.json")
    ver = Verification.model_validate(ver_data) if ver_data else None
    spec_data = job.read_json("partspec.json") or {}
    family = Family(spec_data.get("family", "custom"))
    title = str(spec_data.get("title") or job.summary.title or "Replacement part").split(" (")[0]
    reg = get_registry()
    slug = slug or f"{_slugify(title)}-{job.id[-6:]}"
    facts_data = job.read_json("facts.json")
    facts = PartFacts.model_validate(facts_data) if facts_data else None
    if facts is None:
        try:
            from services.geom_worker.bake import bake

            facts = bake(code, values, ("stl",)).facts
        except Exception:
            facts = None
    builder = None
    for e in job.events:
        if e.t == "model_call" and e.stage == "build":
            builder = f"{e.provider}/{e.model} ({e.mode})"
    status = "verified" if ver is not None and ver.verified else "best_effort"
    final_code = set_defaults(code, values)
    rec = PartRecord(
        id="p_" + job.id[2:],
        slug=slug,
        title=title,
        family=family,
        summary=f"{title} rebuilt by PartSmith from photos ({job.input.origin.value}).",
        tags=[family.value, job.input.origin.value],
        status=status,
        params=parse_params(final_code),
        defaults=dict(values),
        code=final_code,
        code_sha=code_sha(final_code),
        verification=ver,
        provenance=Provenance(
            origin=job.input.origin,
            job_id=job.id,
            photo_shas=list(job.input.photo_shas.values()),
            builder_model=builder,
            provider_mode=job.summary.provider_mode,
            note="; ".join(
                n
                for n in (
                    "mock builder — deterministic, no model was called" if job.summary.provider_mode == "mock" else "",
                    note,
                )
                if n
            ),
        ),
        facts=facts,
        created_at=time.time(),
    )
    from services.registry.publish import publish_part

    outcome = publish_part(rec, reg=reg, render=True)
    part = outcome.part
    job.summary.part_slug = part.slug
    job.save_summary()
    note = f" ({outcome.action}" + (f", same part as {outcome.duplicate_of}" if outcome.duplicate_of else "") + ")"
    job.emit(LogEvent(job=job.id, msg=f"published to the registry as {part.slug} ({status}){note}"))
    return part


def replays() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if not REPLAYS_DIR.exists():
        return out
    for d in sorted(REPLAYS_DIR.iterdir()):
        if not (d / "run.jsonl").exists():
            continue
        s = JobSummary.model_validate_json((d / "summary.json").read_text()) if (d / "summary.json").exists() else None
        out.append(
            {
                "id": d.name,
                "title": s.title if s else d.name,
                "origin": (s.origin.value if s else DataOrigin.replay.value),
                "provider_mode": s.provider_mode if s else "replay",
                "verified": bool(s and s.verified),
                "max_error_mm": s.max_error_mm if s else None,
                "iterations": s.iterations if s else 0,
            }
        )
    return out


def replay_export(job_id: str, replay_id: str | None = None) -> Path:
    job = _job(job_id)
    if not job.finished:
        raise ValueError(f"job {job_id} is still {job.summary.status}")
    return export_replay(job, replay_id)


__all__ = [
    "SampleData",
    "answer",
    "bake_job",
    "cancel",
    "detail_of",
    "edit",
    "fit_check",
    "fit_outline",
    "get_job",
    "job_detail",
    "list_demo_samples",
    "list_jobs",
    "manager",
    "measure",
    "preview",
    "provider_mode",
    "publish",
    "replay_export",
    "replays",
    "reset_manager",
    "start_demo_job",
    "start_fix_job",
    "start_review_job",
]
