"""Agentic fixer: the model operates PartSmith's own instrument through tools ("Spark drives the instrument").

Tools: inspect_residuals, measure_feature, segment_points, render_overlay, run_tests, set_params, ask_human, submit.
Rendering a candidate costs no round; committing one with set_params is a round (the PLAN's 6-round cap still holds),
passes the same guards as the pipeline fixer and is verified by code. `submit` only ends the session: the orchestrator
re-runs the verifier on the committed parameters and only the verifier sets `verified`.

Live: `providers.run_agent(stage="fix_agent", ...)` drives a tool-calling model. Mock (no key) and the fallback when the
provider layer has no tool loop: a deterministic policy that inspects, focuses the worst spot, renders candidate edits
from the residual table / template regions / hole layout, commits the best one, re-inspects and submits. It sees only
what the tools return — never ground truth.
"""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable, Generator, Mapping, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from partsmith_schemas import FocusEvent, ThoughtEvent, ToolCallEvent, Unknown
from partsmith_schemas.verification import ParamSpec

from services.agent import guards, mock_brain, prompt_loader, providers
from services.agent.providers import ModelRequest, ProviderError
from services.geom_worker.program import params_sha, parse_params
from services.geom_worker.sandbox import run_program
from services.verifier.verify import verify

if TYPE_CHECKING:
    from services.agent.orchestrator import FixRun, Round

STAGE = "fix_agent"
MAX_TURNS = 48
MAX_RENDERS = 30  # candidate renders per session (each is a sandbox build + verify)
RENDERS_PER_STEP = 6
MOCK_MIN_GAIN = 0.05  # rank units a rendered candidate must gain before the mock commits it
MOCK_MODEL = "mock fix agent"


@dataclass
class ToolSpecLite:
    name: str
    description: str
    parameters: dict[str, Any]


@dataclass
class ToolResultLite:
    text: str
    images: list[bytes] = field(default_factory=list)
    data: dict[str, Any] = field(default_factory=dict)
    done: bool = False


def tool_spec(name: str, description: str, parameters: dict[str, Any]) -> Any:
    cls = getattr(providers, "ToolSpec", ToolSpecLite)
    return cls(name=name, description=description, parameters=parameters)


def tool_result(
    text: str, images: Sequence[bytes] = (), data: Mapping[str, Any] | None = None, done: bool = False
) -> Any:
    cls = getattr(providers, "ToolResult", ToolResultLite)
    return cls(text=text, images=list(images), data=dict(data or {}), done=done)


def _obj(props: dict[str, Any], required: Sequence[str] = ()) -> dict[str, Any]:
    return {"type": "object", "properties": props, "required": list(required), "additionalProperties": False}


_EDITS = {
    "type": "array",
    "items": _obj(
        {"param": {"type": "string"}, "to": {"type": "number"}, "reason": {"type": "string"}}, ["param", "to"]
    ),
}
_PARAMS = {"type": "object", "additionalProperties": {"type": "number"}, "description": "PARAMS name -> value (mm)"}
_VIEW = {"type": "string", "enum": ["top", "side", "all"]}

TOOLS: list[Any] = [
    tool_spec(
        "inspect_residuals",
        "Residual table, worst spots (model frame, mm) and the residual overlay image of the committed model.",
        _obj({"view": _VIEW}),
    ),
    tool_spec(
        "measure_feature",
        "Re-read one measured feature from the photo: a feature id (hole_1, slot_1, outline) "
        "or the feature nearest to (x_mm, y_mm) in the view's part frame.",
        _obj(
            {"view": _VIEW, "feature_id": {"type": "string"}, "x_mm": {"type": "number"}, "y_mm": {"type": "number"}},
            ["view"],
        ),
    ),
    tool_spec(
        "segment_points",
        "Segment a feature from point prompts (photo pixels) and fit it.",
        _obj(
            {"view": _VIEW, "points_px": {"type": "array", "items": {"type": "array", "items": {"type": "number"}}}},
            ["view", "points_px"],
        ),
    ),
    tool_spec(
        "render_overlay",
        "Build and verify a CANDIDATE (committed PARAMS plus these values) without committing "
        "it; returns its metrics and overlay.",
        _obj({"params": _PARAMS, "view": _VIEW}, ["params"]),
    ),
    tool_spec(
        "run_tests", "Run the part tests on a candidate without committing it.", _obj({"params": _PARAMS}, ["params"])
    ),
    tool_spec(
        "set_params",
        "Commit parameter edits (one round). Unknown names are rejected with the closest names; "
        "values are clamped and step-limited.",
        _obj({"edits": _EDITS, "reason": {"type": "string"}}, ["edits"]),
    ),
    tool_spec(
        "ask_human",
        "Ask the user one short question (hidden depths, mating sizes).",
        _obj({"question": {"type": "string"}, "default": {"type": "string"}}, ["question"]),
    ),
    tool_spec(
        "submit",
        "End the session. Code re-verifies the committed model and decides.",
        _obj({"reason": {"type": "string"}}, ["reason"]),
    ),
]

_POLICIES: dict[str, MockAgent] = {}
_LOCK = threading.Lock()


def handle_mock(req: ModelRequest, history: Any = None) -> dict[str, Any]:
    """The deterministic agent behind stage "fix_agent" (registered with providers.register_mock)."""
    with _LOCK:
        pol = _POLICIES.get(str(req.mock_context.get("run_id", "")))
    if pol is None:
        return {"final": "no active fix session"}
    return pol.step()


def install_mock(*, replace: bool = False) -> None:
    providers.register_mock(STAGE, handle_mock, replace=replace)


def _short(x: float | None, d: int = 2) -> str:
    return "—" if x is None else f"{x:.{d}f}"


class AgentSession:
    """One agentic fix session on the job's best committed round."""

    def __init__(self, run: FixRun, round_limit: int) -> None:
        self.run = run
        self.round_limit = round_limit
        self.id = f"{run.job.id}:{run.iteration}:{time.monotonic_ns()}"
        self.renders = 0
        self.cache: dict[str, Round] = {}
        self.submitted: dict[str, Any] | None = None
        self.last: Any = None
        self.calls: list[dict[str, Any]] = []
        self.commits = 0
        self.asked = 0

    # ---- state ---------------------------------------------------------------------------------------------------------
    @property
    def base(self) -> Round:
        assert self.run.best is not None
        return self.run.best

    def rounds_left(self) -> int:
        if self.run.stalled():  # the shortfall stood still for STALL_ROUNDS commits: no more rounds
            return 0
        return max(0, self.round_limit - self.run.iteration)

    def specs(self) -> list[ParamSpec]:
        return parse_params(self.base.code)

    # ---- tools ---------------------------------------------------------------------------------------------------------
    def call_tool(self, name: str, args: dict[str, Any]) -> Any:
        fn: Callable[[dict[str, Any]], Any] | None = getattr(self, f"tool_{name}", None)
        if fn is None:
            names = [t.name for t in TOOLS]
            res = tool_result(f"error: unknown tool {name!r}; tools: {', '.join(names)}")
        else:
            try:
                res = fn(dict(args or {}))
            except Exception as exc:  # a tool error is reported to the model, never raised into the job
                res = tool_result(f"error: {type(exc).__name__}: {exc}")
        self.last = res
        self.calls.append({"tool": name, "args": args, "result": res.text[:400]})
        return res

    def tool_inspect_residuals(self, args: dict[str, Any]) -> Any:
        from services.agent.orchestrator import (
            fit_png,
            format_gate_failures,
            format_residuals,
            format_spots,
            format_views,
        )

        rnd = self.base
        v = rnd.verification
        assert v is not None
        ctx = self.run.fix_context(rnd)
        spots = ctx["worst"]
        view = str(args.get("view") or "all")
        overlays = rnd.out.overlays if rnd.out else {}
        imgs = [fit_png(png)[0] for k, png in sorted(overlays.items()) if view == "all" or k == f"residual_{view}.png"]
        failing = [t.description for t in v.tests if not t.passed and t.priority == "P0"]
        if spots:
            self.focus(spots[0], f"worst {spots[0]['view']} residual {spots[0]['hausdorff_mm']:.2f} mm")
        stalled = self.run.stalled()
        text = (
            f"{'VERIFIED' if v.verified else 'not verified'} · {self.rounds_left()} round(s) left"
            + (f" (stopped: no progress for {guards.STALL_ROUNDS} rounds; call submit)" if stalled else "")
            + "\n"
            f"{format_views(v)}{format_spots(spots)}\nresiduals:\n{format_residuals(v)}"
            + (f"\nfailing P0 tests: {'; '.join(failing)}" if failing else "")
            + format_gate_failures(v, rnd.out.view_gates if rnd.out else None)
        )
        return tool_result(
            text,
            imgs[:2],
            {
                "ctx": ctx,
                "verified": v.verified,
                "rank0": rnd.rank[0],
                "excess": rnd.rank[1],
                "rounds_left": self.rounds_left(),
                "stalled": stalled,
                "worst_view": spots[0]["view"] if spots else "top",
            },
        )

    def tool_measure_feature(self, args: dict[str, Any]) -> Any:
        view = str(args.get("view") or "top")
        m = self.run.measurements.get("top" if view == "all" else view)
        if m is None:
            return tool_result(f"no measured {view} view")
        fid = args.get("feature_id")
        items: list[dict[str, Any]] = [
            {
                "id": h.id,
                "kind": "hole",
                "center_mm": list(h.center_mm),
                "diameter_mm": h.diameter.value,
                "sigma_mm": h.diameter.sigma_mm,
                "note": (h.diameter.evidence.note if h.diameter.evidence else ""),
            }
            for h in m.holes
        ] + [
            {
                "id": s.id,
                "kind": "slot",
                "center_mm": list(s.center_mm),
                "length_mm": s.length.value,
                "width_mm": s.width.value,
                "angle_deg": s.angle_deg,
            }
            for s in m.slots
        ]
        if fid == "outline" or (not fid and args.get("x_mm") is None):
            d = {"id": "outline", "length_mm": m.length.value, "width_mm": m.width.value, "area_mm2": m.area_mm2}
            return tool_result(f"outline: {m.length.value:.2f} × {m.width.value:.2f} mm (measured)", data=d)
        if fid:
            hit = next((i for i in items if i["id"] == fid), None)
            if hit is None:
                return tool_result(f"no feature {fid!r}; measured: {', '.join(i['id'] for i in items) or 'none'}")
        else:
            x, y = float(args["x_mm"]), float(args.get("y_mm") or 0.0)
            if not items:
                return tool_result("no measured holes or slots in this view")
            hit = min(items, key=lambda i: (i["center_mm"][0] - x) ** 2 + (i["center_mm"][1] - y) ** 2)
        return tool_result(json.dumps(hit), data=hit)

    def tool_segment_points(self, args: dict[str, Any]) -> Any:
        fn = getattr(self.run, "measure_points", None)
        if fn is None:
            return tool_result("point segmentation is not available in this build")
        out = fn(str(args.get("view") or "top"), [list(map(float, p)) for p in args.get("points_px") or []])
        return tool_result(json.dumps(out)[:2000], data={"features": out})

    def _candidate(self, params: Mapping[str, Any]) -> tuple[Round | None, Any]:
        """Guarded candidate values -> built + verified Round (not committed). Returns (round, guard result)."""
        from services.agent.orchestrator import Round

        edits = [{"param": k, "to": v} for k, v in params.items()]
        g = self.run.guard(self.base, edits)
        values = g.values(self.base.values)
        key = params_sha(values)
        if key in self.cache:
            return self.cache[key], g
        if self.renders >= MAX_RENDERS:
            return None, g
        self.renders += 1
        run = self.run
        res = run_program(self.base.code, values, outputs=(), features=True)
        out = verify(res, run.measurements, run.spec, photo_masks=run.masks, camera_views=run.camera_views(),
                     known_form=self.base.strategy == "template", stated=getattr(run, "stated", None))  # fmt: skip
        res.cleanup()
        cand = Round(0, self.base.strategy, self.base.code, dict(values), res, out)
        self.cache[key] = cand
        return cand, g

    def _describe(self, cand: Round, g: Any) -> tuple[str, dict[str, Any]]:
        from services.agent.orchestrator import why_not_verified

        v = cand.verification
        assert v is not None
        base = self.base
        changes = ", ".join(f"{e.param} {e.from_value:g}→{e.to:g}" for e in g.applied) or "no change"
        text = (
            f"candidate ({changes}): Hausdorff {_short(cand.worst_hd)} mm (committed {_short(base.worst_hd)}), "
            f"IoU {_short(cand.min_iou, 3)}, tests {sum(t.passed for t in v.tests)}/{len(v.tests)}"
            f"{' — would verify' if v.verified else ''}"
            + (f"; rejected: {'; '.join(g.rejected)}" if g.rejected else "")
        )
        if not v.verified:
            why = why_not_verified(v, cand.out.view_gates if cand.out else None, limit=3)
            text += f"; still failing: {'; '.join(why)}" if why else ""
        data = {
            "values": cand.values,
            "applied": [e.to_dict() for e in g.applied],
            "rejected": list(g.rejected),
            "verified": v.verified,
            "rank0": cand.rank[0],
            "excess": cand.rank[1],
            "hausdorff_mm": cand.worst_hd,
        }
        return text, data

    def tool_render_overlay(self, args: dict[str, Any]) -> Any:
        from services.agent.orchestrator import fit_png

        cand, g = self._candidate(args.get("params") or {})
        if cand is None:
            return tool_result(f"error: render budget used up ({MAX_RENDERS}); commit or submit")
        text, data = self._describe(cand, g)
        view = str(args.get("view") or "top")
        overlays = cand.out.overlays if cand.out else {}
        imgs = [fit_png(p)[0] for k, p in sorted(overlays.items()) if view == "all" or k == f"residual_{view}.png"]
        return tool_result(text, imgs[:1], data)

    def tool_run_tests(self, args: dict[str, Any]) -> Any:
        cand, g = self._candidate(args.get("params") or {})
        if cand is None or cand.verification is None:
            return tool_result(f"error: render budget used up ({MAX_RENDERS}); commit or submit")
        text, data = self._describe(cand, g)
        fails = [f"{t.description} (model {_short(t.value)})" for t in cand.verification.tests if not t.passed]
        return tool_result(text + ("\nfailing: " + "; ".join(fails) if fails else "\nall tests pass"), data=data)

    def tool_set_params(self, args: dict[str, Any]) -> Any:
        from services.agent.orchestrator import _r, residual_keys

        run = self.run
        if run.stalled():
            return tool_result(f"nothing committed: stopped: no progress for {guards.STALL_ROUNDS} rounds; call submit")
        if self.rounds_left() <= 0:
            return tool_result("no rounds left (the round cap is fixed); call submit")
        stop = self.run.over_budget()
        if stop:
            return tool_result(f"nothing committed: {stop}; call submit")
        base = self.base
        g = run.guard(base, list(args.get("edits") or []))
        for rej in g.rejected:
            run.log(f"guard: {rej}", "warn")
        if not g.applied:
            return tool_result("nothing committed: " + ("; ".join(g.rejected) or "no edits"))
        values = g.values(base.values)
        edits = [e.to_dict() for e in g.applied]
        reason = str(args.get("reason") or "")
        run.iteration += 1
        change = ", ".join(_edit_label(e.param, e.from_value, e.to, parse_params(base.code)) for e in g.applied)
        with run.stage("fix", f"Round {run.iteration}: agent commits {change}") as st:
            rnd = run.evaluate(base.code, values, base.strategy, edits, f"agent: {reason}"[:2000], prev=base)
            st.label = (
                f"Round {run.iteration}: {change} · Hausdorff {_short(base.worst_hd)}→{_short(rnd.worst_hd)} mm"
                + (" · verified" if rnd.verified else "")
            )
        improved = rnd.better_than(base)
        run.note_progress(base)
        run.history.append(
            {
                "iter": run.iteration,
                "edits": edits,
                "hd_before": _r(base.worst_hd),
                "hd_after": _r(rnd.worst_hd),
                "max_error_before": _r(base.score),
                "max_error_after": _r(rnd.score),
                "improved": improved,
                "residuals_before": residual_keys(base.verification),
                "residuals_after": residual_keys(rnd.verification),
            }
        )
        self.commits += 1
        spots = run.worst_spots(rnd) if not rnd.verified else []
        if spots:
            self.focus(spots[0], f"after {change}")
        text = (
            f"committed round {run.iteration}: {change}; Hausdorff {_short(base.worst_hd)}→{_short(rnd.worst_hd)} mm, "
            f"{'verified by code' if rnd.verified else 'not verified'}; "
            + (
                "now the closest to passing (keep rule: shortfall, not max error)"
                if improved
                else "not closer to passing than the best committed round (keep rule: shortfall, not max error); "
                "code keeps that one"
            )
            + (
                f"; stopped: no progress for {guards.STALL_ROUNDS} rounds — no more rounds, call submit"
                if run.stalled()
                else ""
            )
        )
        run.stop_if_stalled()  # logs the stop line once
        return tool_result(text, data={"improved": improved, "verified": rnd.verified, "stalled": run.stalled()})

    def tool_ask_human(self, args: dict[str, Any]) -> Any:
        self.asked += 1
        q = Unknown(
            id=f"agent_q{self.run.iteration}_{self.asked}",
            question=str(args.get("question") or "")[:300],
            expects="text",
            default=args.get("default"),
        )
        ans = self.run.question(q)
        return tool_result(f"answer: {ans!r}" if ans not in (None, "") else "no answer (the user did not reply)")

    def tool_submit(self, args: dict[str, Any]) -> Any:
        self.submitted = {"reason": str(args.get("reason") or "")}
        return tool_result("submitted; code re-runs the verifier on the committed parameters", done=True)

    # ---- events --------------------------------------------------------------------------------------------------------
    def focus(self, spot: Mapping[str, Any], label: str) -> None:
        a, b = (float(x) for x in spot["at_mm"])
        plane = str(spot.get("plane", "xy"))
        at = (a, b, 0.0) if plane == "xy" else (a, 0.0, b) if plane == "xz" else (0.0, a, b)
        self.run.job.emit(
            FocusEvent(
                job=self.run.job.id,
                feature=plane,
                view=str(spot.get("view", "top")),
                at_mm=at,
                label=label,
                iter=self.run.iteration,
            )
        )

    # ---- session -------------------------------------------------------------------------------------------------------
    def request(self) -> ModelRequest:
        from services.agent.orchestrator import format_gate_failures, format_residuals, format_views

        run = self.run
        rnd = self.base
        assert rnd.verification is not None and run.spec is not None
        specs = self.specs()
        p = prompt_loader.load(STAGE)
        dev, user = p.render(
            rounds_left=self.rounds_left(),
            param_names=", ".join(s.name for s in specs),
            limits=", ".join(f"{s.name} ±{guards.max_delta(s, rnd.values.get(s.name, s.default)):g}" for s in specs),
            title=run.spec.title or "part",
            family=run.spec.family.value,
            strategy=rnd.strategy,
            residuals=format_residuals(rnd.verification),
            views=format_views(rnd.verification)
            + format_gate_failures(rnd.verification, rnd.out.view_gates if rnd.out else None),
            values=json.dumps(rnd.values),
        )
        user += run.prompt_extras(rnd)  # approved family rules; in a reviewer round, the person's pinned notes
        return ModelRequest(
            messages=[{"role": "developer", "content": dev}, {"role": "user", "content": user}],
            images=run.reviewer_images(rnd),  # photo | model crops with each pin's numbered ring
            mock_context={"run_id": self.id},
        )

    def drive(self) -> None:
        """Drive the session through providers.run_agent when it exists, else the local deterministic loop."""
        req = self.request()
        pol = MockAgent(self)
        with _LOCK:
            _POLICIES[self.id] = pol
        try:
            run_agent = getattr(providers, "run_agent", None)
            if run_agent is not None:
                try:
                    with providers.job_context(self.run.job.id, self.run.job.emit, ctx=self.run.job.ctx):
                        run_agent(STAGE, req, TOOLS, self.call_tool, max_turns=MAX_TURNS)
                    return
                except (ProviderError, ValueError, KeyError) as exc:
                    self.run.log(f"agent tool loop unavailable ({exc}); deterministic local loop", "warn")
            self.local_loop(req)
        finally:
            with _LOCK:
                _POLICIES.pop(self.id, None)

    def local_loop(self, req: ModelRequest) -> None:
        from services.agent.providers import mocks

        handler = mocks.handler_for(STAGE) or handle_mock
        history: list[dict[str, Any]] = []
        job = self.run.job
        for _ in range(MAX_TURNS):
            action = handler(req, history)
            if not isinstance(action, Mapping):
                break
            if action.get("thought"):
                job.emit(
                    ThoughtEvent(
                        job=job.id,
                        stage=STAGE,
                        model=str(action.get("model") or MOCK_MODEL),
                        text=str(action["thought"])[:500],
                        iter=self.run.iteration,
                        mode="mock",
                    )
                )
            if "tool" not in action:
                break
            name, args = str(action["tool"]), dict(action.get("args") or {})
            t0 = time.perf_counter()
            res = self.call_tool(name, args)
            job.emit(
                ToolCallEvent(
                    job=job.id,
                    stage=STAGE,
                    name=name,
                    args=_safe_args(args),
                    result=res.text[:400],
                    ok=not res.text.startswith("error"),
                    ms=int((time.perf_counter() - t0) * 1000),
                    iter=self.run.iteration,
                    mode="mock",
                )
            )
            history.append({"tool": name, "args": args, "result": res.text})
            if getattr(res, "done", False):
                break


def _safe_args(args: Mapping[str, Any]) -> dict[str, Any]:
    out = json.loads(json.dumps(args, default=str))
    return out if isinstance(out, dict) else {}


def _edit_label(name: str, frm: float, to: float, specs: Sequence[ParamSpec]) -> str:
    unit = next((s.unit for s in specs if s.name == name), "")
    sym = "Ø " if name.endswith("_d") or "diam" in name else ""
    return f"{name} {sym}{frm:.2f}→{to:.2f}{' ' + unit if unit else ''}".replace("  ", " ")


# ------------------------------------------------------------------------------------------------- the mock policy


Action = dict[str, Any]


class MockAgent:
    """Deterministic tool-using policy (labelled mock): inspect → focus the worst spot → render candidates → commit the
    best → re-inspect → submit. Candidates come from the residual table, the template's regions and the hole layout."""

    def __init__(self, session: AgentSession) -> None:
        self.s = session
        self.gen: Generator[Action, Any, None] | None = None

    def step(self) -> Action:
        try:
            if self.gen is None:
                self.gen = self.plan()
                return next(self.gen)
            return self.gen.send(self.s.last)
        except StopIteration:
            return {"final": "session over"}

    @staticmethod
    def act(tool: str, args: dict[str, Any], thought: str = "") -> Action:
        return {
            "tool": tool,
            "args": args,
            "thought": f"{thought} (deterministic mock)" if thought else "",
            "model": MOCK_MODEL,
        }

    def plan(self) -> Generator[Action, Any, None]:
        r = yield self.act("inspect_residuals", {"view": "all"}, "Inspecting where the model and the photo disagree.")
        tried: set[str] = set()
        d: dict[str, Any] = getattr(r, "data", {}) or {}  # the latest inspection (renders do not replace it)
        while True:
            if d.get("verified"):
                yield self.act("submit", {"reason": "the committed model passes every check"}, "Everything passes.")
                return
            if d.get("stalled"):
                yield self.act(
                    "submit", {"reason": "no progress for two rounds"}, "Two rounds without getting closer; stopping."
                )
                return
            if int(d.get("rounds_left", 0)) <= 0 or "ctx" not in d:
                yield self.act("submit", {"reason": "rounds used up"}, "No rounds left.")
                return
            ctx = d["ctx"]
            cands = [c for c in candidates(ctx) if _key(c[1]) not in tried][:RENDERS_PER_STEP]
            if not cands:
                yield self.act("submit", {"reason": "no candidate change improves the model"}, "Out of ideas.")
                return
            best: tuple[tuple[int, float], str, dict[str, float]] | None = None
            for label, params in cands:
                tried.add(_key(params))
                r = yield self.act(
                    "render_overlay", {"params": params, "view": d.get("worst_view", "top")}, f"Trying {label}."
                )
                rd = getattr(r, "data", {}) or {}
                if "excess" not in rd:
                    if "budget" in getattr(r, "text", ""):
                        break
                    continue
                score = (int(rd["rank0"]), float(rd["excess"]))
                if best is None or score < best[0]:
                    best = (score, label, params)
                if rd.get("verified"):
                    break
            cur = (int(d["rank0"]), float(d["excess"]))
            if best is not None and (best[0][0] < cur[0] or best[0][1] < cur[1] - MOCK_MIN_GAIN):
                edits = [{"param": k, "to": v, "reason": best[1]} for k, v in best[2].items()]
                yield self.act("set_params", {"edits": edits, "reason": best[1]}, f"Committing {best[1]}.")
                r = yield self.act("inspect_residuals", {"view": "all"}, "Re-inspecting after the change.")
                d = getattr(r, "data", {}) or {}
            elif self.s.renders >= MAX_RENDERS:
                yield self.act("submit", {"reason": "render budget used up"}, "Render budget used up.")
                return
            # else: the same inspection stands; try the next batch of untried candidates


def _key(params: Mapping[str, float]) -> str:
    return json.dumps({k: round(float(v), 3) for k, v in sorted(params.items())})


def candidates(ctx: Mapping[str, Any]) -> list[tuple[str, dict[str, float]]]:
    """Candidate edit sets for the committed model, most promising first (labels say why)."""
    specs = [ParamSpec.model_validate(p) for p in ctx.get("params", [])]
    by_name = {p.name: p for p in specs}
    values = {k: float(v) for k, v in (ctx.get("values") or {}).items()}
    out: list[tuple[str, dict[str, float]]] = []

    def add(label: str, params: Mapping[str, float]) -> None:
        clean = {
            k: round(float(v), 4) for k, v in params.items() if k in by_name and abs(float(v) - values.get(k, 0)) > 1e-6
        }
        if clean and all(_key(clean) != _key(p) for _, p in out):
            out.append((label, clean))

    # 1. what the residual-driven fixer would do (mapped residuals, hole counts, region probes)
    prop = mock_brain.fix(ModelRequest(messages=[], mock_context=dict(ctx)))
    if prop.get("edits"):
        add(
            str(prop.get("analysis", "residual fix")).split(". (")[0][:120],
            {e["param"]: e["to"] for e in prop["edits"]},
        )
    # 2. the hole row, measured vs model
    row = mock_brain._hole_row_edits(ctx.get("holes") or {}, ctx.get("regions") or {}, by_name, values, set())
    if row:
        add("move the hole row onto the measured holes", {e["param"]: e["to"] for e in row})
    # 3. both directions of every knob that shapes the worst region
    topo = {p.name for p in specs if p.topology}
    for h in mock_brain.region_hints(ctx.get("worst") or [], ctx.get("regions") or {}, topo):
        p = by_name.get(str(h["param"]))
        if p is None:
            continue
        cur = values.get(p.name, p.default)
        if p.topology:
            mag = 1.0
        elif p.unit == "mm":
            mag = min(max(0.8 * float(h["mag"]), p.step), guards.max_delta(p, cur))
        else:
            mag = mock_brain._probe_step(p, cur)
        for sgn in (float(h["sign"]), -float(h["sign"])):
            add(
                f"{p.name} {sgn * mag:+g} where the worst residual is",
                {p.name: min(max(cur + sgn * mag, p.min), p.max)},
            )
            if not p.topology:
                half = sgn * mag / 2
                add(f"{p.name} {half:+g} where the worst residual is", {p.name: min(max(cur + half, p.min), p.max)})
    # 4. the other outline knobs, both directions
    for p in mock_brain._probe_candidates(specs, ctx.get("measure_map") or {})[:4]:
        cur = values.get(p.name, p.default)
        step = mock_brain._probe_step(p, cur)
        for sgn in (1.0, -1.0):
            add(f"{p.name} {sgn * step:+g}", {p.name: min(max(cur + sgn * step, p.min), p.max)})
    return out


__all__ = ["STAGE", "TOOLS", "AgentSession", "MockAgent", "candidates", "handle_mock", "install_mock"]
