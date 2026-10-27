"""Steer: a one-line brief becomes a coherent kit of registry parts (PLAN flow D).

1. **Plan** — the `steer_plan` stage (Muse Wonder) turns the brief into parts, each a family template plus parameter
   values. Code checks the plan: unknown templates/parameters are mapped to the closest real ones or dropped, values are
   clamped to PARAMS, slugs are made unique. Without a key a deterministic mock planner builds the kit (labelled mock).
2. **Lanes** — each planned part is a job (`kind="steer"`): the template program is executed at the planned parameters
   in the sandbox, then verified against its OWN rendered top silhouette. That is a SYNTHETIC self-check (it proves the
   program builds a valid solid whose outline and holes measure as designed), never a claim about a real part.
3. **Approval queue** — a person approves (publish to the registry), sends back with a plain-words note (applied with
   the variant guard, then rebuilt) or rejects. Nothing is published without approval.

State lives in `$PARTSMITH_HOME/steer/<id>.json`; lanes run in background threads.
"""

from __future__ import annotations

import importlib
import json
import re
import secrets
import threading
import time
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, cast

from partsmith_schemas import (
    ArtifactEvent,
    DataOrigin,
    DoneEvent,
    IterationEvent,
    JobInput,
    MetricEvent,
    PartRecord,
    StageEvent,
)
from partsmith_schemas.registry import Provenance
from partsmith_schemas.verification import ParamSpec

from services.agent import providers
from services.agent.jobs import Job, JobManager
from services.agent.providers import ModelRequest
from services.agent.templates import Template, get_template, list_templates
from services.common import blobs
from services.common.paths import sub
from services.geom_worker import bake as geom_bake
from services.geom_worker.program import clamp, closest_names, code_sha, parse_params, set_defaults
from services.registry import parts as P
from services.registry.store import Registry, get_registry

MAX_COUNT = 24
SELF_CHECK_NOTE = (
    "Steer factory part: the {template} template at planned parameters, verified only against its own rendered "
    "silhouette (SYNTHETIC self-check), not against a photo of a real part."
)
PLAN_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "family_title": {"type": "string"},
        "parts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "slug": {"type": "string"},
                    "title": {"type": "string"},
                    "template": {"type": "string"},
                    "params": {"type": "object", "additionalProperties": {"type": "number"}},
                    "why": {"type": "string"},
                },
                "required": ["slug", "title", "template", "params", "why"],
            },
        },
    },
    "required": ["family_title", "parts"],
}

_runs: dict[str, dict[str, Any]] = {}
_lock = threading.RLock()
_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="steer")
_local_manager: JobManager | None = None


def job_manager() -> JobManager:
    """The agent service's job manager when it exists (so lanes show up in /jobs), else a local one."""
    global _local_manager
    try:
        service = importlib.import_module("services.agent.service")
        return cast(JobManager, service.manager())
    except (ImportError, AttributeError):
        if _local_manager is None:
            _local_manager = JobManager()
        return _local_manager


# ------------------------------------------------------------------------------------------------- planning

_SYNONYMS: dict[str, tuple[str, ...]] = {
    "cupboard": ("cupboard_latch", "hinge_leaf", "hook", "l_bracket", "clip"),
    "cabinet": ("cupboard_latch", "hinge_leaf", "l_bracket", "clip"),
    "kitchen": ("hook", "cupboard_latch", "knob", "clip", "hinge_leaf"),
    "hostel": ("hook", "cupboard_latch", "cable_clip", "clip", "l_bracket"),
    "door": ("cupboard_latch", "hinge_leaf", "hook", "knob"),
    "drawer": ("knob", "cupboard_latch", "clip"),
    "shelf": ("l_bracket", "clip", "hook"),
    "desk": ("cable_clip", "hook", "clip", "spacer"),
    "cable": ("cable_clip", "clip", "hook"),
    "furniture": ("caster_wheel", "l_bracket", "spacer", "hinge_leaf"),
    "trolley": ("caster_wheel", "spacer", "l_bracket"),
    "appliance": ("knob", "battery_cover", "clip"),
    "remote": ("battery_cover",),
    "toy": ("battery_cover", "caster_wheel", "spacer"),
    "pcb": ("spacer",),
    "electronics": ("spacer", "cable_clip", "battery_cover"),
    "wall": ("hook", "l_bracket", "cable_clip"),
    "garage": ("hook", "l_bracket", "cable_clip", "caster_wheel"),
}
_GRID_KEYS = ("length", "width", "height", "leaf_width", "diameter")


def _kit_slug(brief: str) -> str:
    words = [
        w
        for w in re.findall(r"[a-z]+", brief.lower())
        if w not in {"a", "an", "the", "kit", "for", "of", "and", "parts", "part", "mm", "grid", "with"}
    ]
    return "-".join(words[:3]) or "kit"


def _pick_templates(brief: str, templates: list[Template]) -> list[Template]:
    words = set(re.findall(r"[a-z]+", brief.lower()))
    by_name = {t.name: t for t in templates}
    chosen: list[str] = []
    for w in sorted(words):
        for name in _SYNONYMS.get(w, ()):
            if name in by_name and name not in chosen:
                chosen.append(name)
    for t in templates:
        text = " ".join([t.title, t.family.value, *t.tags]).lower()
        if t.name not in chosen and any(len(w) > 3 and w in text for w in words):
            chosen.append(t.name)
    return [by_name[n] for n in chosen] or templates


def _screw_clearance(brief: str) -> float:
    m = re.search(r"\bm(\d(?:\.\d)?)\b", brief.lower())
    return P.METRIC_CLEARANCE_MM.get(m.group(1), 4.5) if m else 4.5


def mock_plan(brief: str, count: int, templates: list[Template] | None = None) -> dict[str, Any]:
    """Deterministic kit planner (the `steer_plan` mock): picks templates by brief keywords, shares one screw size
    (M4 clearance unless the brief names another) and snaps the main dimensions to the brief's grid."""
    templates = templates or list_templates()
    picked = _pick_templates(brief, templates)
    grid_m = re.search(r"(\d+(?:\.\d+)?)\s*mm\s*grid", brief.lower())
    grid = float(grid_m.group(1)) if grid_m else None
    screw = _screw_clearance(brief)
    kit = _kit_slug(brief)
    out: list[dict[str, Any]] = []
    for i in range(count):
        t = picked[i % len(picked)]
        k = i // len(picked)
        params: dict[str, float] = {}
        lp = t.measure_map.get("length")
        for spec in t.params:
            v = spec.default
            if spec.name == lp:
                v = spec.default * (1.0 + 0.25 * k)
            if any(h in spec.name for h in ("hole_d", "pivot_d")):
                v = screw
            if grid and spec.name in _GRID_KEYS:
                v = max(grid, round(v / grid) * grid)
            if spec.topology and k and "count" in spec.name:
                v = spec.default + k
            params[spec.name] = round(min(max(v, spec.min), spec.max), 3)
        main = params.get(lp or "", 0.0)
        out.append(
            {
                "slug": f"{kit}-{t.name.replace('_', '-')}-{k + 1}",
                "title": f"{t.title} {main:g} mm" if main else t.title,
                "template": t.name,
                "params": params,
                "why": f"{t.title} for '{brief[:60]}'; shared M-screw clearance {screw:g} mm"
                + (f", dimensions on a {grid:g} mm grid" if grid else "")
                + (f", size step {k + 1}" if k else ""),
            }
        )
    return {"family_title": brief.strip()[:80] or "Steer kit", "parts": out}


def _plan_mock(req: ModelRequest) -> dict[str, Any]:
    ctx = req.mock_context
    return mock_plan(str(ctx.get("brief", "")), int(ctx.get("count", 6)))


def _templates_table() -> str:
    rows = []
    for t in list_templates():
        knobs = ", ".join(f"{p.name} [{p.min:g}..{p.max:g}{p.unit}]" for p in t.params)
        rows.append(f"\n- {t.name} ({t.family.value}): {t.title}. Params: {knobs}")
    return "".join(rows)


def _slugify(s: str) -> str:
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", s.lower())).strip("-")[:80] or "part"


def check_plan(
    raw: Mapping[str, Any], count: int, reg: Registry | None = None
) -> tuple[str, list[dict[str, Any]], list[str]]:
    """Code side of the plan: real templates only, params clamped, unique slugs. Returns (title, parts, notes)."""
    reg = reg or get_registry()
    names = [t.name for t in list_templates()]
    notes: list[str] = []
    taken = set(reg.slugs())
    parts: list[dict[str, Any]] = []
    for item in list(raw.get("parts") or [])[:count]:
        tname = str(item.get("template", ""))
        if tname not in names:
            close = closest_names(tname, [ParamSpec(name=n, default=0, min=0, max=1, step=1) for n in names], n=1)
            if not close:
                notes.append(f"dropped {item.get('slug')!r}: unknown template {tname!r}")
                continue
            notes.append(f"{item.get('slug')!r}: template {tname!r} → {close[0]!r}")
            tname = close[0]
        t = get_template(tname)
        specs = list(t.params)
        given = {str(k): v for k, v in dict(item.get("params") or {}).items()}
        clean: dict[str, float] = {}
        for k, v in given.items():
            near = closest_names(k, specs, n=1)
            name = k if k in t.defaults else (near[0] if near else None)
            if name is None:
                notes.append(f"{item.get('slug')!r}: unknown param {k!r} ignored")
                continue
            try:
                clean[name] = float(v)
            except (TypeError, ValueError):
                notes.append(f"{item.get('slug')!r}: {k}={v!r} is not a number")
        values, changed = clamp(clean, specs)
        for k, v in changed.items():
            notes.append(f"{item.get('slug')!r}: {k} clamped to {v:g}")
        slug = _slugify(str(item.get("slug") or f"{tname}"))
        base, n = slug, 2
        while slug in taken:
            slug, n = f"{base}-{n}", n + 1
        taken.add(slug)
        parts.append(
            {
                "slug": slug,
                "title": str(item.get("title") or t.title)[:120],
                "family": t.family.value,
                "template": tname,
                "params": {k: float(v) for k, v in values.items()},
                "why": str(item.get("why", ""))[:300],
            }
        )
    return str(raw.get("family_title") or "Steer kit")[:120], parts, notes


# ------------------------------------------------------------------------------------------------- persistence


def _dir() -> Path:
    return sub("steer")


def _save(run: dict[str, Any]) -> None:
    path = _dir() / f"{run['id']}.json"
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(run, indent=1, default=str))
    tmp.replace(path)


def _load(run_id: str) -> dict[str, Any] | None:
    if not re.fullmatch(r"s_[0-9a-z_]+", run_id):
        return None
    path = _dir() / f"{run_id}.json"
    if not path.exists():
        return None
    run: dict[str, Any] = json.loads(path.read_text())
    # a run interrupted by a restart cannot resume its threads
    for lane in run.get("lanes", []):
        if lane["status"] in ("queued", "running"):
            lane["status"] = "failed"
            lane["error"] = "interrupted by a server restart"
    for q in run.get("queue", []):
        if q["status"] == "building":
            q["status"] = "failed"
    if run.get("status") in ("planning", "building"):
        run["status"] = "failed" if not run.get("queue") else "reviewing"
    return run


def _copy(d: Mapping[str, Any]) -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(json.dumps(d, default=str)))


def get(run_id: str) -> dict[str, Any]:
    """Steer state (docs/API.md). KeyError if unknown."""
    with _lock:
        run = _runs.get(run_id) or _load(run_id)
        if run is None:
            raise KeyError(run_id)
        _runs[run_id] = run
        return _copy(run)


def list_runs(limit: int = 20) -> list[dict[str, Any]]:
    out = []
    for path in sorted(_dir().glob("s_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)[:limit]:
        try:
            r = get(path.stem)
        except (KeyError, json.JSONDecodeError):
            continue
        out.append(
            {k: r[k] for k in ("id", "brief", "count", "status", "created_at", "family_title")}
            | {
                "pending": sum(q["status"] == "pending_review" for q in r["queue"]),
                "published": sum(q["status"] == "published" for q in r["queue"]),
            }
        )
    return out


def _update(run_id: str, fn: Any) -> dict[str, Any]:
    with _lock:
        if run_id not in _runs:
            get(run_id)
        run = _runs[run_id]
        fn(run)
        run["updated_at"] = time.time()
        _save(run)
        return run


# ------------------------------------------------------------------------------------------------- lanes


def _lane_record(job: Job, item: Mapping[str, Any], plan_mode: str) -> PartRecord:
    """Execute + self-verify one planned part inside `job`; returns the (unpublished) PartRecord."""
    from services.geom_worker.sandbox import run_program
    from services.verifier.selfcheck import POSE
    from services.verifier.synthetic import synthetic_top_measurement
    from services.verifier.verify import verify

    t = get_template(str(item["template"]))
    params = dict(item["params"])
    code = set_defaults(t.code, params)
    job.emit(StageEvent(job=job.id, stage="plan", status="ok", label=f"planned: {item['title']} from {t.name}"))
    job.emit(StageEvent(job=job.id, stage="build", status="ok", label=f"{t.name} template at planned parameters"))
    job.write_text("part.py", code)
    code_key = blobs.put(code.encode(), ".py")
    job.emit(
        ArtifactEvent(job=job.id, kind="code", sha=code_key.split(".")[0], url=blobs.url(code_key), label="part.py")
    )
    t0 = time.perf_counter()
    job.emit(StageEvent(job=job.id, stage="execute", status="start", label="sandboxed CadQuery"))
    res = run_program(code, params, outputs=(), features=True)
    try:
        ms = int((time.perf_counter() - t0) * 1000)
        if not res.ok or res.mesh is None or res.solid_info is None:
            job.emit(
                StageEvent(
                    job=job.id,
                    stage="execute",
                    status="fail",
                    ms=ms,
                    label=res.error.short() if res.error else "no solid",
                )
            )
            raise RuntimeError(res.error.short() if res.error else "the program produced no solid")
        job.emit(StageEvent(job=job.id, stage="execute", status="ok", ms=ms, label="solid built"))
        job.emit(StageEvent(job=job.id, stage="verify", status="start", label="SYNTHETIC self-check"))
        meas, photo = synthetic_top_measurement(res, pose=POSE)
        out = verify(res, {"top": meas}, None, photo_masks={"top": photo})
        v = out.verification
        for name, png in out.overlays.items():
            key = blobs.put(png, ".png")
            job.emit(
                ArtifactEvent(
                    job=job.id,
                    kind="residual_heatmap",
                    sha=key.split(".")[0],
                    url=blobs.url(key),
                    iter=1,
                    label=f"SYNTHETIC self-check {name}",
                )
            )
        vm = v.views[0] if v.views else None
        if vm is not None:
            job.emit(
                MetricEvent(
                    job=job.id, iter=1, name="hausdorff_mm", value=vm.hausdorff_mm, threshold=v.thresholds.hausdorff_mm
                )
            )
            job.emit(MetricEvent(job=job.id, iter=1, name="iou", value=vm.iou, threshold=v.thresholds.iou, unit=""))
        job.emit(
            IterationEvent(
                job=job.id,
                iter=1,
                strategy="template",
                analysis="template at planned parameters (no model-written code)",
                code_sha=code_sha(code),
                hausdorff_mm=vm.hausdorff_mm if vm else None,
                iou=vm.iou if vm else None,
                passed_tests=sum(t_.passed for t_ in v.tests),
                total_tests=len(v.tests),
            )
        )
        job.write_json("verification.json", v)
        job.emit(
            StageEvent(
                job=job.id,
                stage="verify",
                status="ok" if v.verified else "fail",
                label=f"self-check {'passed' if v.verified else 'failed'} (SYNTHETIC)",
            )
        )
        facts, _ = geom_bake.part_facts(res.solid_info.volume_mm3, res.mesh)
    finally:
        res.cleanup()
    job.emit(StageEvent(job=job.id, stage="judge", status="skip", label="no judge for a synthetic self-check"))
    specs = parse_params(code)
    record = PartRecord(
        id="p_" + secrets.token_hex(6),
        slug=str(item["slug"]),
        title=str(item["title"]),
        family=t.family,
        summary=t.summary,
        tags=[*t.tags, "steer"],
        status="verified" if v.verified else "best_effort",
        params=specs,
        defaults={s.name: float(s.default) for s in specs},
        code=code,
        code_sha=code_sha(code),
        verification=v,
        provenance=Provenance(
            origin=DataOrigin.synthetic,
            job_id=job.id,
            builder_model=f"template:{t.name}",
            provider_mode=cast(Any, plan_mode if plan_mode in ("live", "mock", "replay") else "mock"),
            created_by="steer",
            note=SELF_CHECK_NOTE.format(template=t.name),
        ),
        facts=facts,
        created_at=time.time(),
    )
    job.write_text("part_record.json", record.model_dump_json(indent=1))
    job.emit(StageEvent(job=job.id, stage="package", status="ok", label="waiting for human approval"))
    job.emit(
        DoneEvent(
            job=job.id,
            verified=v.verified,
            status="verified" if v.verified else "best_effort",
            summary={"max_error_mm": v.max_error_mm, "origin": "synthetic", "steer": True},
        )
    )
    return record


def _run_lane(run_id: str, slug: str) -> None:
    run = get(run_id)
    item = next(p for p in run["plan"] if p["slug"] == slug)
    mgr = job_manager()
    job = mgr.create(
        "steer",
        JobInput(kind="steer", intent=run["brief"], origin=DataOrigin.synthetic),
        title=f"Steer: {item['title']}",
        provider_mode="mock",
    )

    def mark(r: dict[str, Any], **kw: Any) -> None:
        for lane in r["lanes"]:
            if lane["slug"] == slug:
                lane.update(kw)
        for q in r["queue"]:
            if q["slug"] == slug and "queue_status" in kw:
                q["status"] = kw["queue_status"]

    _update(run_id, lambda r: mark(r, status="running", job_id=job.id))
    holder: dict[str, PartRecord] = {}

    def runner(j: Job) -> None:
        holder["record"] = _lane_record(j, item, run.get("plan_mode", "mock"))

    mgr.run_sync(job, runner)
    rec = holder.get("record")

    def finish(r: dict[str, Any]) -> None:
        for lane in r["lanes"]:
            if lane["slug"] != slug:
                continue
            if rec is None:
                lane.update(status="failed", error=_job_error(job))
            else:
                v = rec.verification
                lane.update(status="done", verified=bool(v and v.verified), max_error_mm=v.max_error_mm if v else None)
        for q in r["queue"]:
            if q["slug"] == slug:
                q.update(job_id=job.id, status="failed" if rec is None else "pending_review")
                if rec is not None and rec.verification is not None:
                    q.update(verified=rec.verification.verified, max_error_mm=rec.verification.max_error_mm)
        if all(lane["status"] in ("done", "failed") for lane in r["lanes"]):
            r["status"] = "reviewing"

    _update(run_id, finish)


def _job_error(job: Job) -> str:
    for ev in reversed(job.events):
        if ev.t == "log" and ev.level == "error":
            return str(ev.msg)[:300]
    return "lane failed"


def _plan_and_build(run_id: str) -> None:
    run = get(run_id)
    mgr = job_manager()
    job = mgr.create(
        "steer",
        JobInput(kind="steer", intent=run["brief"], origin=DataOrigin.synthetic),
        title=f"Steer plan: {run['brief'][:60]}",
        provider_mode=providers.stage_mode("steer_plan"),
    )
    out: dict[str, Any] = {}

    def planner(j: Job) -> None:
        from services.agent import prompt_loader

        j.emit(StageEvent(job=j.id, stage="plan", status="start", label="Muse Wonder plans the kit"))
        prompt = prompt_loader.load("steer_plan")
        dev, user = prompt.render(templates=_templates_table(), brief=run["brief"], count=run["count"])
        req = ModelRequest(
            messages=[{"role": "system", "content": dev}, {"role": "user", "content": user}],
            json_schema=PLAN_SCHEMA,
            schema_name="steer_plan",
            strict=False,
            mock_context={"brief": run["brief"], "count": run["count"]},
        )
        providers.register_mock("steer_plan", _plan_mock, replace=False)
        with providers.job_context(j.id, j.emit):
            comp = providers.complete("steer_plan", req)
        title, plan, notes = check_plan(comp.json or {}, run["count"])
        out.update(title=title, plan=plan, notes=notes, mode=comp.mode, model=comp.model, provider=comp.provider)
        for n in notes:
            j.log(n, "warn")
        j.emit(StageEvent(job=j.id, stage="plan", status="ok" if plan else "fail", label=f"{len(plan)} parts planned"))
        j.emit(
            DoneEvent(
                job=j.id,
                verified=False,
                status="best_effort" if plan else "failed",
                summary={"steer_id": run_id, "planned": len(plan), "mode": comp.mode},
            )
        )

    mgr.run_sync(job, planner)
    if not out.get("plan"):
        _update(run_id, lambda r: r.update(status="failed", plan_job_id=job.id, error=_job_error(job)))
        return

    def planned(r: dict[str, Any]) -> None:
        r.update(
            status="building",
            plan_job_id=job.id,
            family_title=out["title"],
            plan=out["plan"],
            plan_notes=out["notes"],
            plan_mode=out["mode"],
            planner={"provider": out["provider"], "model": out["model"], "mode": out["mode"]},
        )
        r["lanes"] = [
            {"slug": p["slug"], "status": "queued", "job_id": None, "verified": False, "max_error_mm": None}
            for p in out["plan"]
        ]
        r["queue"] = [
            {
                "slug": p["slug"],
                "title": p["title"],
                "family": p["family"],
                "status": "building",
                "job_id": None,
                "verified": False,
                "max_error_mm": None,
                "params": p["params"],
                "note": "",
            }
            for p in out["plan"]
        ]

    _update(run_id, planned)
    for p in out["plan"]:
        _pool.submit(_safe_lane, run_id, p["slug"])


def _safe_lane(run_id: str, slug: str) -> None:
    try:
        _run_lane(run_id, slug)
    except Exception as exc:  # a broken lane must never take the factory down
        msg = f"{type(exc).__name__}: {exc}"[:300]

        def fail(r: dict[str, Any]) -> None:
            for lane in r["lanes"]:
                if lane["slug"] == slug:
                    lane.update(status="failed", error=msg)
            for q in r["queue"]:
                if q["slug"] == slug:
                    q["status"] = "failed"

        _update(run_id, fail)


def _safe_plan(run_id: str) -> None:
    try:
        _plan_and_build(run_id)
    except Exception as exc:
        msg = f"{type(exc).__name__}: {exc}"[:300]
        _update(run_id, lambda r: r.update(status="failed", error=msg))


def start(brief: str, count: int = 6, *, sync: bool = False) -> str:
    """Start a Steer run; returns its id. `sync=True` plans and builds every lane before returning (tests, CLI)."""
    brief = " ".join(brief.split())[:300]
    if not brief:
        raise ValueError("brief is empty")
    count = max(1, min(int(count), MAX_COUNT))
    run_id = "s_" + time.strftime("%y%m%d") + "_" + secrets.token_hex(4)
    run = {
        "id": run_id,
        "brief": brief,
        "count": count,
        "status": "planning",
        "created_at": time.time(),
        "updated_at": time.time(),
        "family_title": "",
        "plan": [],
        "plan_notes": [],
        "lanes": [],
        "queue": [],
        "plan_job_id": None,
        "plan_mode": None,
        "planner": None,
        "history": [],
        "label": "Lanes are verified against their own rendered silhouette: a SYNTHETIC self-check, not a photo.",
    }
    with _lock:
        _runs[run_id] = run
        _save(run)
    if sync:
        _plan_and_build_inline(run_id)
    else:
        threading.Thread(target=_safe_plan, args=(run_id,), name=f"steer-{run_id}", daemon=True).start()
    return run_id


def _plan_and_build_inline(run_id: str) -> None:
    """Like `_plan_and_build` but lanes run in this thread (deterministic order)."""
    global _pool
    original = _pool

    class _Inline:
        def submit(self, fn: Any, *args: Any) -> None:
            fn(*args)

    _pool = _Inline()  # type: ignore[assignment]
    try:
        _safe_plan(run_id)
    finally:
        _pool = original


def wait(run_id: str, timeout_s: float = 120.0) -> dict[str, Any]:
    """Block until planning and every lane are finished (or the timeout passes)."""
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout_s:
        r = get(run_id)
        if r["status"] in ("reviewing", "done", "failed"):
            return r
        time.sleep(0.2)
    return get(run_id)


def _lane_part(run: Mapping[str, Any], slug: str) -> PartRecord | None:
    q = next((q for q in run["queue"] if q["slug"] == slug), None)
    if q is None or not q.get("job_id"):
        return None
    job = job_manager().get(q["job_id"])
    text = job.read_text("part_record.json") if job else None
    return PartRecord.model_validate_json(text) if text else None


def review(run_id: str, slug: str, action: str, note: str = "", *, reg: Registry | None = None) -> dict[str, Any]:
    """approve → publish to the registry; send_back → apply the note with the variant guard and rebuild;
    reject → drop. Returns the updated state. Raises KeyError (unknown run/slug) or ValueError (bad action/state)."""
    reg = reg or get_registry()
    run = get(run_id)
    q = next((q for q in run["queue"] if q["slug"] == slug), None)
    if q is None:
        raise KeyError(slug)
    if action not in ("approve", "send_back", "reject"):
        raise ValueError(f"unknown action {action!r}; use approve, send_back or reject")
    entry = {"slug": slug, "action": action, "note": note[:500], "ts": time.time()}
    if action == "approve":
        if q["status"] != "pending_review":
            raise ValueError(f"{slug} is {q['status']}, not pending review")
        part = _lane_part(run, slug)
        if part is None:
            raise ValueError(f"{slug} has no built part to publish")
        if reg.get_part(slug) is not None:
            raise ValueError(f"slug {slug!r} is already taken in the registry")
        reg.upsert_part(part)
        P.after_publish(part, reg=reg)

        def approve(r: dict[str, Any]) -> None:
            for x in r["queue"]:
                if x["slug"] == slug:
                    x.update(status="published", note=note)
            r["history"].append(entry)
            if all(x["status"] in ("published", "rejected", "failed") for x in r["queue"]):
                r["status"] = "done"

        return _copy(_update(run_id, approve))
    if action == "reject":

        def reject(r: dict[str, Any]) -> None:
            for x in r["queue"]:
                if x["slug"] == slug:
                    x.update(status="rejected", note=note)
            r["history"].append(entry)
            if all(x["status"] in ("published", "rejected", "failed") for x in r["queue"]):
                r["status"] = "done"

        return _copy(_update(run_id, reject))

    # send back: the note is a plain-words change request applied with the variant guard, then the lane rebuilds
    if q["status"] in ("building", "published"):
        raise ValueError(f"{slug} is {q['status']}; it cannot be sent back now")
    plan_item = next(p for p in run["plan"] if p["slug"] == slug)
    t = get_template(plan_item["template"])
    result = P.variant_for_specs(t.params, plan_item["params"], note, title=plan_item["title"]) if note else None
    entry["applied"] = result.applied if result else []
    entry["not_applied"] = result.not_applied if result else []

    def send_back(r: dict[str, Any]) -> None:
        for p in r["plan"]:
            if p["slug"] == slug and result is not None:
                p["params"] = result.params
        for x in r["queue"]:
            if x["slug"] == slug:
                x.update(status="building" if result and result.applied else "sent_back", note=note)
                if result is not None:
                    x["params"] = result.params
        for lane in r["lanes"]:
            if lane["slug"] == slug and result and result.applied:
                lane.update(status="queued", verified=False, max_error_mm=None)
        r["history"].append(entry)
        if result and result.applied:
            r["status"] = "building"

    state = _update(run_id, send_back)
    if result and result.applied:
        _pool.submit(_safe_lane, run_id, slug)
    return _copy(state)
