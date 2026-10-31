"""Job state machine, event bus, run.jsonl persistence and replays.

A job is a directory `$PARTSMITH_HOME/runs/<job_id>/` holding `run.jsonl` (every event, append-only), `summary.json` and the
side files the orchestrator writes (`partspec.json`, `measurements.json`, `verification.json`, `part.py`, `values.json`).
Events are the single source of truth for the UI: SSE streams them, `GET /jobs/{id}` reduces them, replays re-stream them.
The orchestrator runs in a worker thread; questions pause it on a threading.Event until `answer()` is called.
"""

from __future__ import annotations

import hashlib
import json
import secrets
import shutil
import threading
import time
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from partsmith_schemas import (
    AnswerEvent,
    DataOrigin,
    DoneEvent,
    Event,
    JobInput,
    JobSummary,
    LogEvent,
    QuestionEvent,
)
from partsmith_schemas.registry import JobKind, ProviderMode
from pydantic import TypeAdapter

from services.common import blobs
from services.common.paths import REPO_ROOT, runs_dir

EVENT_ADAPTER: TypeAdapter[Event] = TypeAdapter(Event)
REPLAYS_DIR = REPO_ROOT / "data" / "replays"  # committed, labelled replays for the judge path
TERMINAL = {"done", "failed", "cancelled"}


class QuestionTimeout(Exception):
    pass


class JobCancelled(Exception):
    pass


def new_job_id() -> str:
    return "j_" + time.strftime("%y%m%d") + "_" + secrets.token_hex(4)


def context_hash(*parts: Any) -> str:
    """Stamp for async results: sha256 of the inputs that define the current state (photos, calibration, params)."""
    blob = json.dumps(parts, sort_keys=True, default=str).encode()
    return hashlib.sha256(blob).hexdigest()[:16]


def _atomic_write(path: Path, text: str) -> None:
    """Write via a temp file + rename so readers (API requests) never see a half-written file."""
    tmp = path.with_name(f".{path.name}.{threading.get_ident()}.tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


class Job:
    """One job: events, status and the pause/resume handshake for questions. Thread-safe."""

    def __init__(
        self, summary: JobSummary, job_input: JobInput, run_dir: Path, *, events: list[Event] | None = None
    ) -> None:
        self.summary = summary
        self.input = job_input
        self.dir = run_dir
        self.events: list[Event] = events or []
        self.ctx = ""
        self._lock = threading.RLock()
        self._cond = threading.Condition(self._lock)
        self._answers: dict[str, AnswerEvent] = {}
        self._cancel = threading.Event()

    @property
    def id(self) -> str:
        return str(self.summary.id)

    # ---- events ------------------------------------------------------------------------------------------------------
    def emit(self, event: Event | dict[str, Any]) -> Event:
        """Append an event (seq/ts/ctx/job filled in), persist it to run.jsonl and wake SSE subscribers."""
        ev = EVENT_ADAPTER.validate_python(event) if isinstance(event, dict) else event
        with self._cond:
            ev.job = self.id
            ev.seq = len(self.events)
            ev.ts = ev.ts or time.time()
            ev.ctx = ev.ctx or self.ctx
            self.events.append(ev)
            self._apply(ev)
            with (self.dir / "run.jsonl").open("a", encoding="utf-8") as fh:
                fh.write(ev.model_dump_json(exclude_none=True) + "\n")
            self._cond.notify_all()
        return ev

    def log(self, msg: str, level: str = "info") -> None:
        self.emit(LogEvent(job=self.id, level=level, msg=msg))

    def _apply(self, ev: Event) -> None:
        s = self.summary
        s.updated_at = ev.ts
        if ev.t == "question":
            s.status = "waiting_for_answer"
        elif ev.t == "answer" and s.status == "waiting_for_answer":
            s.status = "running"
        elif ev.t == "iteration":
            s.iterations = max(s.iterations, ev.iter)
            if ev.hausdorff_mm is not None:
                s.max_error_mm = ev.hausdorff_mm
        elif ev.t == "model_call":
            s.cost_usd = round(s.cost_usd + ev.usd, 6)
        elif ev.t == "done":
            s.status = "cancelled" if ev.status == "cancelled" else ("failed" if ev.status == "failed" else "done")
            s.verified = ev.verified
            if "max_error_mm" in ev.summary:
                s.max_error_mm = ev.summary["max_error_mm"]
            if ev.summary.get("part_slug"):
                s.part_slug = ev.summary["part_slug"]
        self.save_summary()

    def save_summary(self) -> None:
        _atomic_write(self.dir / "summary.json", self.summary.model_dump_json(indent=2))

    def events_since(self, seq: int, timeout_s: float = 15.0) -> list[Event]:
        """Block until there are events with seq >= `seq` (or the job is finished, or the timeout passes)."""
        with self._cond:
            self._cond.wait_for(lambda: len(self.events) > seq or self.finished, timeout=timeout_s)
            return self.events[seq:]

    @property
    def finished(self) -> bool:
        return self.summary.status in TERMINAL

    # ---- questions ---------------------------------------------------------------------------------------------------
    def ask(self, question: QuestionEvent, timeout_s: float = 3600.0) -> AnswerEvent:
        """Pause the job until `answer()` delivers a value for `question.id`."""
        self.emit(question)
        with self._cond:
            ok = self._cond.wait_for(lambda: question.id in self._answers or self._cancel.is_set(), timeout=timeout_s)
            if self._cancel.is_set():
                raise JobCancelled(self.id)
            if not ok:
                raise QuestionTimeout(question.id)
            return self._answers.pop(question.id)

    def answer(self, qid: str, value: str | float, via: str = "text") -> None:
        pending = self.pending_question()
        if pending is None or pending.id != qid:
            raise KeyError(f"no pending question {qid!r}")
        ev = AnswerEvent(job=self.id, id=qid, value=value, via=via)
        with self._cond:
            self._answers[qid] = ev
            self.emit(ev)

    def pending_question(self) -> QuestionEvent | None:
        answered = {e.id for e in self.events if e.t == "answer"}
        for e in reversed(self.events):
            if e.t == "question":
                return None if e.id in answered else e
        return None

    def cancel(self) -> None:
        self._cancel.set()
        with self._cond:
            self._cond.notify_all()

    @property
    def cancelled(self) -> bool:
        return self._cancel.is_set()

    # ---- side files --------------------------------------------------------------------------------------------------
    def write_json(self, name: str, data: Any) -> None:
        text = (
            data.model_dump_json(indent=2)
            if hasattr(data, "model_dump_json")
            else json.dumps(data, indent=2, default=str)
        )
        _atomic_write(self.dir / name, text)

    def read_json(self, name: str) -> Any:
        p = self.dir / name
        return json.loads(p.read_text()) if p.exists() else None

    def write_text(self, name: str, text: str) -> None:
        _atomic_write(self.dir / name, text)

    def read_text(self, name: str) -> str | None:
        p = self.dir / name
        return p.read_text() if p.exists() else None


Runner = Callable[[Job], None]


class JobManager:
    """Creates, runs, finds and lists jobs. Jobs from earlier sessions and bundled replays load from disk."""

    def __init__(self, root: Path | None = None, max_workers: int = 2) -> None:
        self.root = root or runs_dir()
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()
        self._pool = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="job")

    def create(
        self,
        kind: JobKind,
        job_input: JobInput,
        *,
        title: str = "",
        provider_mode: ProviderMode = "mock",
        job_id: str | None = None,
    ) -> Job:
        jid = job_id or new_job_id()
        run_dir = self.root / jid
        run_dir.mkdir(parents=True, exist_ok=False)
        now = time.time()
        summary = JobSummary(
            id=jid,
            kind=kind,
            status="queued",
            created_at=now,
            updated_at=now,
            title=title,
            origin=job_input.origin,
            provider_mode=provider_mode,
        )
        job = Job(summary, job_input, run_dir)
        job.write_json("input.json", job_input)
        job.save_summary()
        with self._lock:
            self._jobs[jid] = job
        return job

    def start(self, job: Job, runner: Runner) -> None:
        job.summary.status = "running"
        job.save_summary()
        self._pool.submit(self._run, job, runner)

    def run_sync(self, job: Job, runner: Runner) -> Job:
        job.summary.status = "running"
        self._run(job, runner)
        return job

    def _run(self, job: Job, runner: Runner) -> None:
        try:
            runner(job)
        except JobCancelled:
            job.emit(DoneEvent(job=job.id, verified=False, status="cancelled"))
        except Exception as exc:  # the job fails, the server keeps running
            job.emit(LogEvent(job=job.id, level="error", msg=f"{type(exc).__name__}: {exc}"))
            job.emit(DoneEvent(job=job.id, verified=False, status="failed", summary={"error": str(exc)}))
        if not job.finished:
            job.emit(
                DoneEvent(job=job.id, verified=False, status="failed", summary={"error": "runner ended without done"})
            )

    def get(self, jid: str) -> Job | None:
        with self._lock:
            if jid in self._jobs:
                return self._jobs[jid]
        for base in (self.root, REPLAYS_DIR):
            run_dir = base / jid
            if (run_dir / "run.jsonl").exists():
                job = load_job(run_dir, is_replay=base == REPLAYS_DIR)
                with self._lock:
                    self._jobs[jid] = job
                return job
        return None

    def list(self, limit: int = 50, *, include_replays: bool = False) -> list[JobSummary]:
        dirs = [d for d in self.root.iterdir() if (d / "summary.json").exists()] if self.root.exists() else []
        if include_replays and REPLAYS_DIR.exists():
            dirs += [d for d in REPLAYS_DIR.iterdir() if (d / "run.jsonl").exists()]
        out: list[JobSummary] = []
        seen: set[str] = set()
        for d in dirs:  # a run copied to the replays folder keeps its id: list it once (the local run wins, as in get)
            if d.name in seen:
                continue
            seen.add(d.name)
            job = self.get(d.name)
            if job is not None:
                out.append(job.summary)
        return sorted(out, key=lambda s: s.created_at, reverse=True)[:limit]

    def shutdown(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)


def read_events(path: Path) -> Iterator[Event]:
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                yield EVENT_ADAPTER.validate_json(line)


def say_synthetic_once(title: str) -> str:
    """Older runs were titled "Spacer (synthetic, clean) (synthetic sample)": drop the trailing "(synthetic sample)"
    when the title already says synthetic (new runs are titled that way from the start)."""
    head, sep, _ = title.rpartition(" (synthetic sample)")
    return head if sep and title.endswith(sep) and "synthetic" in head.lower() else title


def load_job(run_dir: Path, *, is_replay: bool = False) -> Job:
    """Rebuild a finished (or interrupted) job from disk. Interrupted jobs are marked failed — they cannot resume a thread."""
    events = list(read_events(run_dir / "run.jsonl"))
    summary_path = run_dir / "summary.json"
    input_path = run_dir / "input.json"
    job_input = JobInput.model_validate_json(input_path.read_text()) if input_path.exists() else JobInput()
    if summary_path.exists():
        summary = JobSummary.model_validate_json(summary_path.read_text())
    else:
        t0 = events[0].ts if events else time.time()
        summary = JobSummary(
            id=run_dir.name, kind="fix", status="done", created_at=t0, updated_at=t0, origin=job_input.origin
        )
    if is_replay:
        summary.is_replay = True
        summary.origin = DataOrigin.replay if summary.origin == DataOrigin.real else summary.origin
    if summary.title:
        summary.title = say_synthetic_once(summary.title)
    if summary.status not in TERMINAL:
        summary.status = "failed"
    return Job(summary, job_input, run_dir, events=events)


# Large lossless images are re-encoded for committed replays (the judge path only displays them).
REPLAY_JPEG_KINDS = {
    "rectified",
    "measure_overlay",
    "mask_overlay",
    "residual_heatmap",
    "render_overlay",
    "install_card",
    "reconstruction",
}
REPLAY_MAX_SIDE_PX = 1600
REPLAY_JPEG_QUALITY = 85


def _replay_image(key: str) -> str:
    """Re-encode a PNG artifact as a smaller JPEG blob for replays; returns the new key (or the old one if unchanged)."""
    import cv2
    import numpy as np

    if not key.endswith(".png"):
        return key
    img = cv2.imdecode(np.frombuffer(blobs.get(key), np.uint8), cv2.IMREAD_UNCHANGED)
    if img is None:
        return key
    if img.ndim == 3 and img.shape[2] == 4:  # flatten transparency onto white
        alpha = img[:, :, 3:4].astype(np.float32) / 255.0
        img = (img[:, :, :3].astype(np.float32) * alpha + 255.0 * (1.0 - alpha)).astype(np.uint8)
    h, w = img.shape[:2]
    scale = min(1.0, REPLAY_MAX_SIDE_PX / max(h, w))
    if scale < 1.0:
        img = cv2.resize(img, (round(w * scale), round(h * scale)), interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, REPLAY_JPEG_QUALITY])
    return blobs.put(buf.tobytes(), ".jpg") if ok else key


def export_replay(job: Job, replay_id: str | None = None) -> Path:
    """Copy a finished run into data/replays/ with every referenced blob, so the judge path works on a fresh clone.
    Display-only images are re-encoded as JPEG; the replay's own run.jsonl points at the re-encoded copies."""
    dest = REPLAYS_DIR / (replay_id or job.id)
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(job.dir, dest)
    lines: list[str] = []
    for ev in job.events:
        if ev.t == "artifact":
            if ev.kind in REPLAY_JPEG_KINDS:
                new_key = _replay_image(ev.sha)
                if new_key != ev.sha:
                    ev = ev.model_copy(update={"sha": new_key, "url": blobs.url(new_key)})
            blobs.copy_to_replays(ev.sha)
        lines.append(ev.model_dump_json(exclude_none=True))
    (dest / "run.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return dest
