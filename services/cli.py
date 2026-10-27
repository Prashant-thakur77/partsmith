"""`partsmith` command line. Every command goes through `services.agent.service` (the same facade as the API and MCP).

partsmith fix <folder> [--sync] [--answers k=v] [--max-iters N]   photos → verified part program (live trace)
partsmith demo <sample_id>                                          run a bundled SYNTHETIC sample
partsmith replay export <job_id> [--as <id>]                        copy a finished run to data/replays
partsmith bake <slug|template> --param k=v --format stl             bake a registry part or a template
partsmith mat --pdf out.pdf | --web                                 calibration mats
partsmith synth ...                                                 synthetic samples (tools.synth)
partsmith seed [--if-empty]                                         seed the registry from the pipeline
partsmith serve                                                     REST API (uvicorn)
partsmith status                                                    provider table (live / mock / replay)
"""

from __future__ import annotations

import contextlib
import json
import sys
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Annotated, Any

import typer
from partsmith_schemas import DataOrigin, Event, JobInput
from partsmith_schemas.partspec import Family

app = typer.Typer(add_completion=False, no_args_is_help=True, help="PartSmith: photos of a broken part → verified CAD.")
replay_app = typer.Typer(no_args_is_help=True, help="Replays (labelled recorded runs).")
app.add_typer(replay_app, name="replay")

PHOTO_EXTS = (".jpg", ".jpeg", ".png", ".webp")
VIDEO_EXTS = (".mp4", ".mov", ".webm")


# ------------------------------------------------------------------------------------------------- trace printing


def _fmt_mm(v: float | None, digits: int = 2) -> str:
    return "—" if v is None else f"{v:.{digits}f}"


def format_event(e: Event) -> str | None:
    """One readable line per event (None = not worth printing)."""
    if e.t == "stage":
        if e.status == "start":
            return None
        mark = {"ok": "✓", "fail": "✗", "skip": "·"}.get(e.status, "?")
        ms = f" ({e.ms} ms)" if e.ms is not None else ""
        it = f" #{e.iter}" if e.iter else ""
        return f"  {mark} {e.stage:<10}{it:<4} {e.label}{ms}"
    if e.t == "iteration":
        edits = ", ".join(f"{d.get('param')} {d.get('from')}→{d.get('to')}" for d in e.edits) or "—"
        return (
            f"  ↻ round {e.iter} [{e.strategy}] Hausdorff {_fmt_mm(e.hausdorff_mm)} mm · IoU {_fmt_mm(e.iou, 3)} · "
            f"tests {e.passed_tests}/{e.total_tests} · edits: {edits}"
        )
    if e.t == "question":
        return f"  ? {e.text} (id {e.id}, default {e.default!r})"
    if e.t == "answer":
        return f"  ! answer {e.id} = {e.value!r} ({e.via})"
    if e.t == "model_call":
        tag = "" if e.ok else f" FAILED: {e.error}"
        return f"    · model {e.stage}: {e.provider}/{e.model} [{e.mode}] {e.ms} ms ${e.usd:.4f}{tag}"
    if e.t == "log":
        return f"    {'!' if e.level != 'info' else '·'} {e.msg}"
    if e.t == "thought":
        return f"    ~ {e.text}"
    if e.t == "tool_call":
        first = e.result.splitlines()[0] if e.result else ""
        return f"    ⚙ {e.name}({', '.join(f'{k}=' for k in e.args)}) → {first[:140]}"
    if e.t == "focus":
        at = ", ".join(f"{v:.1f}" for v in e.at_mm) if e.at_mm else "—"
        return f"    ⌖ focus {e.view} ({at}) mm: {e.label}"
    if e.t == "done":
        s = e.summary
        return (
            f"  ■ done: {e.status.upper()} (verified={e.verified}) · max error {_fmt_mm(s.get('max_error_mm'), 3)} mm · "
            f"{s.get('iterations', 0)} round(s) · ${s.get('cost_usd', 0.0):.4f} · mode {s.get('mode')} · "
            f"origin {s.get('origin')}"
        )
    return None


def verification_table(detail: dict[str, Any]) -> str:
    v = detail.get("verification")
    if not v:
        return "no verification (the job ended before a model was verified)"
    lines = [f"Verification: {v['status'].upper()} (verified={v['verified']}, origin {v.get('origin')})"]
    lines.append(f"  {'view':<6} {'IoU':>7} {'Hausdorff':>10} {'HD95':>7} {'mean':>7}")
    for m in v.get("views", []):
        lines.append(
            f"  {m['view']:<6} {m['iou']:>7.4f} {m['hausdorff_mm']:>8.3f}mm {m['hd95_mm']:>5.3f}mm {m['mean_mm']:>5.3f}mm"
        )
    lines.append(f"  thresholds: Hausdorff ≤ {v['thresholds']['hausdorff_mm']} mm, IoU ≥ {v['thresholds']['iou']}")
    if v.get("residuals"):
        lines.append(f"  {'feature':<10} {'quantity':<10} {'measured':>9} {'model':>9} {'Δ':>8} {'tol':>6}")
        for r in v["residuals"]:
            lines.append(
                f"  {r['feature_id']:<10} {r['quantity']:<10} {r['measured_mm']:>9.3f} {r['model_mm']:>9.3f} "
                f"{r['delta_mm']:>+8.3f} {r['tol_mm']:>6.2f} {'ok' if r['passed'] else 'FAIL'}"
            )
    for t in v.get("tests", []):
        val = "missing" if t["value"] is None else f"{t['value']:.3f}"
        lines.append(f"  [{'pass' if t['passed'] else 'FAIL'}] {t['priority']} {t['description']} (model: {val})")
    for r in v.get("reasons", [])[:6]:
        lines.append(f"  - {r}")
    if v.get("max_error_mm") is not None:
        lines.append(f"  max error {v['max_error_mm']:.3f} mm")
    return "\n".join(lines)


def _follow(job: Any, interactive: bool) -> None:
    """Print events as they arrive until the job finishes; answer questions on stdin when interactive."""
    seq = 0
    asked: set[str] = set()
    while True:
        evs = job.events_since(seq, timeout_s=1.0)
        for e in evs:
            line = format_event(e)
            if line:
                typer.echo(line)
        seq += len(evs)
        q = job.pending_question()
        if interactive and q is not None and q.id not in asked and not job.finished:
            asked.add(q.id)
            raw = typer.prompt(f"    answer {q.id}", default=str(q.default) if q.default is not None else "")
            try:
                value: str | float = float(raw) if q.expects == "number_mm" else raw
            except ValueError:
                value = raw
            with contextlib.suppress(KeyError):
                job.answer(q.id, value, "text")
        if job.finished and seq >= len(job.events):
            break


def _run_and_print(start: Callable[[Callable[[Any], None]], Any], interactive: bool) -> None:
    """Run `start(on_created)` in a worker thread and follow the job's events here."""
    from services.agent import service

    holder: dict[str, Any] = {}
    created = threading.Event()

    def on_created(job: Any) -> None:
        holder["job"] = job
        created.set()

    def target() -> None:
        try:
            start(on_created)
        except Exception as exc:
            holder["error"] = exc
        finally:
            created.set()

    t = threading.Thread(target=target, daemon=True)
    t.start()
    created.wait()
    job = holder.get("job")
    if job is None:
        raise typer.Exit(_fail(str(holder.get("error", "the job did not start"))))
    typer.echo(f"job {job.id} · {job.summary.title} · providers: {job.summary.provider_mode}")
    _follow(job, interactive)
    t.join()
    if "error" in holder:
        raise typer.Exit(_fail(str(holder["error"])))
    detail = service.detail_of(job)
    typer.echo("")
    typer.echo(verification_table(detail))
    typer.echo("")
    for kind, url in sorted(detail["artifacts"].items()):
        typer.echo(f"  {kind:<16} {url}")
    typer.echo(f"\nrun dir: {job.dir}")


def _fail(msg: str) -> int:
    typer.echo(f"error: {msg}", err=True)
    return 1


def _parse_kv(pairs: list[str]) -> dict[str, str | float]:
    out: dict[str, str | float] = {}
    for p in pairs:
        if "=" not in p:
            raise typer.BadParameter(f"expected k=v, got {p!r}")
        k, v = p.split("=", 1)
        try:
            out[k.strip()] = float(v)
        except ValueError:
            out[k.strip()] = v.strip()
    return out


# ------------------------------------------------------------------------------------------------- commands


@app.command()
def fix(
    folder: Annotated[Path, typer.Argument(help="folder with top.jpg|png (+ side, mating) and optional meta.json")],
    sync: Annotated[bool, typer.Option("--sync", help="never wait for answers: use defaults")] = False,
    answers: Annotated[list[str] | None, typer.Option("--answers", help="pre-answer questions: id=value")] = None,
    max_iters: Annotated[int, typer.Option("--max-iters", help="max build/verify rounds")] = 6,
    intent: Annotated[str | None, typer.Option(help="what is broken / what you want")] = None,
    thickness: Annotated[float | None, typer.Option(help="part thickness in mm, if known")] = None,
    family: Annotated[str | None, typer.Option(help="family hint (knob, latch, wheel, ...)")] = None,
    mat: Annotated[str | None, typer.Option(help="mat id (auto-detected when omitted)")] = None,
    fix_mode: Annotated[str, typer.Option("--fix-mode", help="agent (model drives the tools) or pipeline")] = "agent",
) -> None:
    """Photos of a part on the mat → measured, verified part program. Prints the loop live."""
    from services.agent import service
    from services.agent.orchestrator import RunOptions

    if not folder.is_dir():
        raise typer.Exit(_fail(f"{folder} is not a folder"))
    photos: dict[str, bytes] = {}
    for view in ("top", "side", "mating", "orbit"):
        for ext in PHOTO_EXTS + VIDEO_EXTS:
            p = folder / f"{view}{ext}"
            if p.exists():
                photos[view] = p.read_bytes()
                break
    if "top" not in photos:
        raise typer.Exit(_fail(f"no top.jpg / top.png in {folder}"))
    meta: dict[str, Any] = json.loads((folder / "meta.json").read_text()) if (folder / "meta.json").exists() else {}
    hint = family or meta.get("family_hint")
    origin = DataOrigin(meta["origin"]) if meta.get("origin") in DataOrigin.__members__ else DataOrigin.real
    mat_id = mat or meta.get("mat_id")
    ji = JobInput(
        intent=intent if intent is not None else str(meta.get("intent", "")),
        thickness_mm=thickness if thickness is not None else meta.get("user_thickness_mm"),
        family_hint=Family(str(hint)) if hint in Family.__members__ else None,
        origin=origin,
        max_iters=max_iters,
        mat_kind="paper" if str(mat_id or "").startswith("paper") else "screen",
    )
    interactive = not sync and sys.stdin.isatty()
    opts = RunOptions(
        answers=_parse_kv(answers or []),
        question_timeout_s=600.0 if interactive else 0.0,
        max_iters=max_iters,
        mat_id=mat_id,
        fix_mode="pipeline" if fix_mode == "pipeline" else "agent",
        points=json.loads((folder / "points.json").read_text()) if (folder / "points.json").exists() else None,
    )
    title = str(meta.get("title") or folder.name)
    _run_and_print(
        lambda cb: service.start_fix_job(photos, ji, sync=True, options=opts, title=title, on_created=cb), interactive
    )


@app.command()
def demo(sample_id: str, sync: Annotated[bool, typer.Option("--sync")] = True) -> None:
    """Run a bundled SYNTHETIC sample (data/synthetic/samples/<id>)."""
    from services.agent import service

    if sample_id in ("list", "ls"):
        for s in service.list_demo_samples():
            typer.echo(f"{s['id']:<28} {s['family_hint'] or '—':<12} {s['title']}")
        return
    _run_and_print(
        lambda cb: service.start_demo_job(sample_id, sync=True, on_created=cb),
        interactive=not sync and sys.stdin.isatty(),
    )


@replay_app.command("export")
def replay_export(
    job_id: str, as_id: Annotated[str | None, typer.Option("--as", help="replay id (default: the job id)")] = None
) -> None:
    """Copy a finished run (events, side files, blobs) into data/replays/ as a labelled replay."""
    from services.agent import service

    try:
        dest = service.replay_export(job_id, as_id)
    except (KeyError, ValueError) as exc:
        raise typer.Exit(_fail(str(exc))) from None
    typer.echo(f"replay written to {dest}")


@app.command()
def bake(
    slug: Annotated[str, typer.Argument(help="registry slug or template name")],
    param: Annotated[list[str] | None, typer.Option("--param", help="k=v (mm)")] = None,
    fmt: Annotated[list[str] | None, typer.Option("--format", help="stl, step, 3mf, glb, view, py")] = None,
) -> None:
    """Bake a registry part (or a family template) with parameters; prints the file paths."""
    from services.agent.templates import get_template
    from services.geom_worker.bake import BakeError
    from services.geom_worker.bake import bake as run_bake
    from services.geom_worker.program import UnknownParamError

    code = None
    try:
        from services.registry.store import get_registry

        part = get_registry().get_part(slug)
        code = part.code if part is not None else None
    except Exception:
        code = None
    if code is None:
        try:
            code = get_template(slug).code
        except KeyError as exc:
            raise typer.Exit(_fail(f"no registry part or template {slug!r}: {exc}")) from None
    values = {k: float(v) for k, v in _parse_kv(param or []).items()}
    try:
        out = run_bake(code, values, tuple(fmt or ["stl"]))
    except (BakeError, UnknownParamError, ValueError) as exc:
        raise typer.Exit(_fail(str(exc))) from None
    if out.clamped:
        typer.echo(f"clamped to PARAMS ranges: {out.clamped}")
    for f, p in sorted(out.files.items()):
        typer.echo(f"{f:<5} {p}")
    if out.facts is not None:
        typer.echo(out.facts.model_dump_json(indent=1))


@app.command()
def mat(
    pdf: Annotated[Path | None, typer.Option("--pdf", help="write the plain-paper mat PDF here")] = None,
    web: Annotated[bool, typer.Option("--web", help="write apps/web/public/mats/*.json")] = False,
    mat_id: Annotated[str, typer.Option("--mat", help="mat id for --pdf")] = "paper-a4",
) -> None:
    """Calibration mats (delegates to tools.mat.make_mat)."""
    from tools.mat.make_mat import main as mat_main

    argv: list[str] = []
    if pdf is not None:
        argv += ["--pdf", str(pdf), "--mat", mat_id]
    if web:
        argv.append("--web")
    if not argv:
        raise typer.Exit(_fail("nothing to do: pass --pdf PATH and/or --web"))
    raise typer.Exit(mat_main(argv))


@app.command(context_settings={"allow_extra_args": True, "ignore_unknown_options": True})
def synth(ctx: typer.Context) -> None:
    """Synthetic samples with exact ground truth (all arguments go to `python -m tools.synth`)."""
    try:
        from tools.synth.__main__ import main as synth_main
    except ImportError:
        raise typer.Exit(_fail("tools.synth is not available in this checkout")) from None
    raise typer.Exit(synth_main(list(ctx.args)))


@app.command()
def seed(if_empty: Annotated[bool, typer.Option("--if-empty")] = False) -> None:
    """Seed the registry by running the bundled samples through the real pipeline."""
    try:
        from services.registry.seed import seed as run_seed
    except ImportError:
        raise typer.Exit(_fail("services.registry.seed is not available yet; nothing seeded")) from None
    out = run_seed(if_empty)
    typer.echo(json.dumps(out, indent=1))
    if out.get("failed") and not out.get("seeded"):
        raise typer.Exit(1)


@app.command()
def serve(
    host: Annotated[str, typer.Option()] = "127.0.0.1",
    port: Annotated[int, typer.Option()] = 8000,
    reload: Annotated[bool, typer.Option()] = False,
) -> None:
    """Run the REST API (uvicorn services.api.main:app)."""
    import uvicorn

    uvicorn.run("services.api.main:app", host=host, port=port, reload=reload)


@app.command()
def status() -> None:
    """Which model serves each stage, and whether it is live, mock or replay."""
    from services.agent import providers

    rows = providers.status()
    typer.echo(f"overall mode: {providers.overall_mode()}")
    typer.echo(f"{'stage':<15} {'mode':<7} {'provider':<14} {'model':<40} note")
    for r in rows:
        typer.echo(f"{r['stage']:<15} {r['mode']:<7} {r['provider']:<14} {str(r['model'])[:40]:<40} {r['note']}")
    for w in providers.warnings():
        typer.echo(f"! {w}")


def main() -> None:
    app()


if __name__ == "__main__":
    main()
