"""Agentic tool loop: a model drives our own tools (measure, segment, render, test, set params, submit).

The model only *proposes* tool calls; `call_tool` (our code) runs them, and nothing a tool returns can set `verified`.

Live paths
- Meta Responses (Muse Spark 1.3 / Wonder): flat function tools, `tool_choice="auto"` (the only accepted value),
  `parallel_tool_calls=False`, `reasoning={"effort", "summary": "auto"}`. The conversation is kept client-side
  (`store=False` + `include=["reasoning.encrypted_content"]`, reasoning items replayed), so instructions, tools and
  reasoning settings are resent every turn and old images can be dropped. Tool outputs go back as
  `function_call_output` with `input_text` + `input_image` items; only the last `keep_images` tool images stay inline.
  Bodies over 1 MiB move images to the Files API.
- Chat Completions (Muse Spark Open on Baseten / Fireworks / Together, Glimmer on llama.cpp): nested tools; tool
  messages are text only, so tool images follow in one user message per turn.

Every turn emits a `model_call` event (tokens, $) and, when present, a `thought` event (Responses reasoning summary; on
the chat path the model's visible note — raw reasoning is never forwarded). Every call emits a `tool_call` event.
A tool named `submit` ends the loop (unless its result sets `data["continue"]`), as does any `ToolResult(done=True)`.
On `max_turns` the loop returns what it has.

Mock mode: `register_mock(stage, handler)` with `handler(req, history) -> {"tool": name, "args": {...}} | {"final": text}`
(optional `"thought"`, and `"model"` to name the mock in its events). Thought and tool-call events carry the driver's
`mode`, so a mock turn is labelled mock everywhere. The loop runs the REAL `call_tool`, so mocks exercise real tools.
Replay mode serves recorded per-turn decisions (keyed by the conversation so far) and falls back to the mock on a miss.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

from . import budget, chat, health, meta, mocks, pricing, replay, retry, sam_parse
from .base import ModelRequest, ProviderError, Usage
from .clients import field as get
from .config import Mode, settings, warn_once
from .core import retry_opts
from .jsonschema_lite import minimal_instance
from .media import data_url, sha256, sniff_image_mime
from .routing import Route, resolve, stage_spec
from .telemetry import record_call, record_thought, record_tool_call

KEEP_IMAGES = 4
OMITTED = "[earlier image omitted to keep the request small]"


@dataclass
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]  # JSON schema of the arguments

    def flat(self) -> dict[str, Any]:
        return {"type": "function", "name": self.name, "description": self.description, "parameters": self.parameters}

    def nested(self) -> dict[str, Any]:
        fn = {"name": self.name, "description": self.description, "parameters": self.parameters}
        return {"type": "function", "function": fn}


@dataclass
class ToolResult:
    text: str
    images: list[bytes] = field(default_factory=list)
    data: dict[str, Any] = field(default_factory=dict)
    done: bool = False


@dataclass
class AgentResult:
    final_text: str
    turns: int
    calls: list[dict[str, Any]]
    submitted: dict[str, Any] | None
    usage: Usage
    usd: float
    mode: Mode
    provider: str
    model: str
    stop_reason: str = ""  # final | submit | done | max_turns | error
    error: str | None = None


@dataclass
class Decision:
    text: str = ""
    thought: str = ""
    calls: list[dict[str, Any]] = field(default_factory=list)  # {"id", "name", "args"}
    usage: Usage = field(default_factory=Usage)
    model: str = ""

    def to_record(self) -> dict[str, Any]:
        return {"text": self.text, "thought": self.thought, "calls": self.calls}


class Driver(Protocol):
    mode: Mode
    provider: str
    model: str

    def next(self, history: list[dict[str, Any]]) -> Decision: ...

    def add_result(self, call: dict[str, Any], result: ToolResult) -> None: ...


def _parse_args(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if not raw:
        return {}
    try:
        value = json.loads(str(raw))
    except ValueError:
        return {"__invalid_json__": str(raw)[:500]}
    return value if isinstance(value, dict) else {"__invalid_json__": str(raw)[:500]}


def _plain(item: Any) -> dict[str, Any]:
    """SDK output item → plain dict without None fields, ready to be sent back as input."""
    data: Any = item
    dump = getattr(item, "model_dump", None)
    if callable(dump):
        data = dump(exclude_none=True)
    if not isinstance(data, dict):
        return {}
    return {k: v for k, v in data.items() if v is not None}


# ------------------------------------------------------------------------------------------------ drivers


class MockDriver:
    mode: Mode = "mock"
    provider = "mock"

    def __init__(self, stage: str, req: ModelRequest, tools: Sequence[ToolSpec], model: str) -> None:
        self.stage, self.req, self.tools, self.model = stage, req, tools, model

    def next(self, history: list[dict[str, Any]]) -> Decision:
        handler = mocks.handler_for(self.stage)
        if handler is not None:
            out = handler(self.req, history)
        else:  # built-in: submit a schema-minimal answer if there is a submit tool, else stop
            submit = next((t for t in self.tools if t.name == "submit"), None)
            if submit is not None and not history:
                out = {"tool": "submit", "args": minimal_instance(submit.parameters), "thought": "[mock] submitting"}
            else:
                out = {"final": f"[mock {self.stage}] deterministic mock — no model was called."}
        if not isinstance(out, dict):
            raise ProviderError(f"mock for {self.stage!r} must return a dict, got {type(out).__name__}")
        thought = str(out.get("thought", ""))
        model = str(out.get("model") or self.model)  # a domain mock may name itself (e.g. "mock fix agent")
        if "tool" in out:
            call = {"id": f"mock_{len(history) + 1}", "name": str(out["tool"]), "args": dict(out.get("args") or {})}
            return Decision(thought=thought, calls=[call], model=model)
        return Decision(text=str(out.get("final", "")), thought=thought, model=model)

    def add_result(self, call: dict[str, Any], result: ToolResult) -> None:
        return None


class ReplayDriver:
    mode: Mode = "replay"

    def __init__(self, digest: Callable[[list[dict[str, Any]]], str], fallback: MockDriver) -> None:
        self.digest, self.fallback = digest, fallback
        self.provider, self.model = "replay", ""
        self.missed = False

    def next(self, history: list[dict[str, Any]]) -> Decision:
        rec = None if self.missed else replay.load(self.digest(history))
        if rec is None:
            if not self.missed:
                warn_once(f"replay: no recorded agent turn for {self.fallback.stage!r} → deterministic mock from here")
            self.missed = True
            self.mode, self.provider, self.model = "mock", "mock", self.fallback.model
            return self.fallback.next(history)
        self.provider, self.model = str(rec.get("provider", "replay")), str(rec.get("model", ""))
        resp = rec.get("response", {})
        return Decision(
            text=str(resp.get("text", "")),
            thought=str(resp.get("thought", "")),
            calls=list(resp.get("calls") or []),
            usage=Usage.from_dict(rec.get("usage")),
            model=self.model,
        )

    def add_result(self, call: dict[str, Any], result: ToolResult) -> None:
        return None


class MetaDriver:
    """Muse Spark 1.3 / Wonder through the Responses API, conversation kept client-side."""

    mode: Mode = "live"

    def __init__(
        self, route: Route, req: ModelRequest, tools: Sequence[ToolSpec], effort: str | None, keep_images: int
    ) -> None:
        self.route, self.req, self.tools, self.keep_images = route, req, tools, keep_images
        self.provider, self.model = route.provider, route.model
        self.effort = meta.normalize_effort(effort) or "medium"
        self.items: list[dict[str, Any]] = meta.build_input(req)
        self.file_ids: dict[str, str] = {}

    def _pruned(self) -> list[dict[str, Any]]:
        """Keep only the newest `keep_images` tool images inline; older ones become a short text note."""
        seen = 0
        out: list[dict[str, Any]] = []
        for item in reversed(self.items):
            if item.get("type") == "function_call_output" and isinstance(item.get("output"), list):
                parts = []
                for part in reversed(item["output"]):
                    if part.get("type") == "input_image":
                        seen += 1
                        if seen > self.keep_images:
                            part = {"type": "input_text", "text": OMITTED}
                    parts.append(part)
                item = {**item, "output": list(reversed(parts))}
            out.append(item)
        return list(reversed(out))

    def _move_images_to_files(self, client: Any, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        def swap(part: dict[str, Any]) -> dict[str, Any]:
            url = part.get("image_url")
            if part.get("type") != "input_image" or not isinstance(url, str) or not url.startswith("data:"):
                return part
            import base64

            raw = base64.b64decode(url.split(",", 1)[1])
            key = sha256(raw)
            if key not in self.file_ids:
                uploaded = client.files.create(file=(f"img-{key[:8]}", raw, sniff_image_mime(raw)), purpose="user_data")
                self.file_ids[key] = str(get(uploaded, "id"))
            return {"type": "input_image", "file_id": self.file_ids[key]}

        out = []
        for item in items:
            for key in ("content", "output"):
                if isinstance(item.get(key), list):
                    item = {**item, key: [swap(p) if isinstance(p, dict) else p for p in item[key]]}
            out.append(item)
        return out

    def kwargs(self) -> dict[str, Any]:
        kw: dict[str, Any] = {
            "model": self.route.model,
            "input": self._pruned(),
            "tools": [t.flat() for t in self.tools],
            "tool_choice": "auto",
            "parallel_tool_calls": False,
            "store": False,
            "include": ["reasoning.encrypted_content"],
            "reasoning": {"effort": self.effort, "summary": "auto"},
        }
        if self.req.max_tokens:
            kw["max_output_tokens"] = max(16, int(self.req.max_tokens))
        if self.req.temperature is not None:
            kw["temperature"] = self.req.temperature
        return kw

    def next(self, history: list[dict[str, Any]]) -> Decision:
        timeout = self.req.timeout_s or settings().timeout_s
        client = meta.client_for(self.route, timeout)
        kw = self.kwargs()
        if len(json.dumps(kw, default=str)) > meta.INLINE_BODY_LIMIT:
            kw["input"] = self._move_images_to_files(client, kw["input"])

        def call() -> tuple[str, Any]:
            events = client.responses.create(**kw, stream=True)
            try:
                return sam_parse.stream_text(events)
            finally:
                close = getattr(events, "close", None)
                if callable(close):
                    close()

        text, final = retry.with_retries(call, **retry_opts(self.route))
        if final is None:
            raise ProviderError("Responses stream ended without response.completed", provider=self.provider)
        output = [_plain(o) for o in (get(final, "output", None) or [])]
        self.items.extend(o for o in output if o)
        thoughts: list[str] = []
        calls: list[dict[str, Any]] = []
        for o in output:
            if o.get("type") == "reasoning":
                thoughts += [str(s.get("text", "")) for s in o.get("summary") or [] if isinstance(s, dict)]
            elif o.get("type") == "function_call":
                calls.append({"id": o.get("call_id"), "name": o.get("name"), "args": _parse_args(o.get("arguments"))})
        if not text:
            text = str(get(final, "output_text", "") or "")
        return Decision(
            text=text, thought="\n".join(t for t in thoughts if t), calls=calls, usage=meta.usage_of(final),
            model=self.model,
        )  # fmt: skip

    def add_result(self, call: dict[str, Any], result: ToolResult) -> None:
        content: list[dict[str, Any]] = [{"type": "input_text", "text": result.text}]
        content += [{"type": "input_image", "image_url": data_url(img)} for img in result.images]
        self.items.append({"type": "function_call_output", "call_id": call["id"], "output": content})


class ChatDriver:
    """Muse Spark Open / Glimmer through Chat Completions. Tool messages are text; images follow in a user message."""

    mode: Mode = "live"

    def __init__(
        self, route: Route, req: ModelRequest, tools: Sequence[ToolSpec], effort: str | None, keep_images: int
    ) -> None:
        self.route, self.req, self.tools, self.keep_images, self.effort = route, req, tools, keep_images, effort
        self.provider, self.model = route.provider, route.model
        self.glimmer = chat.is_glimmer(route)
        self.max_side = chat.GLIMMER_MAX_IMAGE_SIDE if self.glimmer else None
        self.messages: list[dict[str, Any]] = chat.build_messages(req, self.max_side)
        self.pending_images: list[tuple[str, bytes]] = []

    def _flush_images(self) -> None:
        if not self.pending_images:
            return
        labels = [name for name, _ in self.pending_images]
        parts: list[dict[str, Any]] = [{"type": "text", "text": "Images returned by the tool calls above:"}]
        parts += chat.image_parts([img for _, img in self.pending_images], labels, self.max_side)
        self.messages.append({"role": "user", "content": parts, "tool_images": True})
        self.pending_images = []

    def _pruned(self) -> list[dict[str, Any]]:
        seen = 0
        out: list[dict[str, Any]] = []
        for msg in reversed(self.messages):
            if msg.get("tool_images"):
                parts = []
                for part in reversed(msg["content"]):
                    if part.get("type") == "image_url":
                        seen += 1
                        if seen > self.keep_images:
                            part = {"type": "text", "text": OMITTED}
                    parts.append(part)
                msg = {"role": "user", "content": list(reversed(parts))}
            out.append(msg)
        return list(reversed(out))

    def next(self, history: list[dict[str, Any]]) -> Decision:
        self._flush_images()
        timeout = self.req.timeout_s or settings().timeout_s
        client = chat.client_for(self.route, timeout)
        self.model = chat.resolve_model(self.route, client)
        kw: dict[str, Any] = {
            "model": self.model,
            "messages": self._pruned(),
            "tools": [t.nested() for t in self.tools],
            "tool_choice": "auto",
            "parallel_tool_calls": False,
        }
        if self.glimmer:
            if self.route.endpoint.name == "modal_glimmer":
                strength = chat.map_effort(self.effort, chat.GLIMMER_STRENGTHS, "low")
                kw["extra_body"] = {"chat_template_kwargs": {"reasoning_strength": strength}}
        else:
            kw["reasoning_effort"] = chat.map_effort(self.effort, chat.SPARK_OPEN_EFFORTS, "medium")
        if self.req.max_tokens:
            kw["max_tokens"] = int(self.req.max_tokens)
        if self.req.temperature is not None:
            kw["temperature"] = self.req.temperature

        def call() -> tuple[str, Usage, list[dict[str, Any]]]:
            chunks = client.chat.completions.create(**kw, stream=True, stream_options={"include_usage": True})
            try:
                return chat.collect_stream(chunks)
            finally:
                close = getattr(chunks, "close", None)
                if callable(close):
                    close()

        text, usage, raw_calls = retry.with_retries(call, **retry_opts(self.route))
        if self.glimmer:
            text = chat.clean_glimmer_text(text)
        calls = [
            {
                "id": c.get("id") or f"call_{len(history) + i + 1}",
                "name": c.get("name"),
                "args": _parse_args(c.get("arguments")),
            }
            for i, c in enumerate(raw_calls)
        ]
        assistant: dict[str, Any] = {"role": "assistant", "content": text}
        if calls:
            assistant["tool_calls"] = [
                {"id": c["id"], "type": "function", "function": {"name": c["name"], "arguments": json.dumps(c["args"])}}
                for c in calls
            ]
        self.messages.append(assistant)
        if not text and not calls:
            raise ProviderError(
                f"{self.provider}: empty reply (token budget spent on reasoning?)", provider=self.provider
            )
        return Decision(text=text, thought=text if calls else "", calls=calls, usage=usage, model=self.model)

    def add_result(self, call: dict[str, Any], result: ToolResult) -> None:
        self.messages.append({"role": "tool", "tool_call_id": call["id"], "content": result.text})
        self.pending_images += [(f"{call['name']} image {i + 1}", img) for i, img in enumerate(result.images)]


# ------------------------------------------------------------------------------------------------ loop


def _turn_digest(stage: str, req: ModelRequest, tools: Sequence[ToolSpec], history: list[dict[str, Any]]) -> str:
    payload = {
        "req": replay.completion_payload(req),
        "tools": [t.flat() for t in tools],
        "history": [{k: h[k] for k in ("tool", "args", "result", "image_shas", "ok")} for h in history],
    }
    return replay.request_hash("agent", stage, payload)


def _live_driver(route: Route, req: ModelRequest, tools: Sequence[ToolSpec], effort: str | None, keep: int) -> Driver:
    if route.protocol == "responses":
        return MetaDriver(route, req, tools, effort, keep)
    return ChatDriver(route, req, tools, effort, keep)


def run_agent(
    stage: str,
    req: ModelRequest,
    tools: Sequence[ToolSpec],
    call_tool: Callable[[str, dict[str, Any]], ToolResult],
    *,
    max_turns: int = 12,
    keep_images: int = KEEP_IMAGES,
) -> AgentResult:
    """Let the stage's model drive `tools` until it submits, stops talking, or runs out of turns."""
    spec = stage_spec(stage)
    if spec.kind not in ("agent", "complete"):
        raise ValueError(f"stage {stage!r} is a {spec.kind} stage, not an agent stage")
    s = settings()
    res = resolve(stage)
    effort = req.reasoning_effort or spec.default_reasoning
    names = {t.name for t in tools}
    mock_model = res.display.model if res.display else "none"
    mock_driver = MockDriver(stage, req, tools, mock_model)
    routes = list(res.routes)
    driver: Driver
    if res.mode == "mock":
        driver = mock_driver
    elif res.mode == "replay":
        driver = ReplayDriver(lambda h: _turn_digest(stage, req, tools, h), mock_driver)
    else:
        driver = _live_driver(routes.pop(0), req, tools, effort, keep_images)

    history: list[dict[str, Any]] = []
    calls: list[dict[str, Any]] = []
    usage, usd = Usage(), 0.0
    final_text = ""

    def result(stop: str, submitted: dict[str, Any] | None = None, error: str | None = None) -> AgentResult:
        return AgentResult(
            final_text=final_text, turns=turn, calls=calls, submitted=submitted, usage=usage, usd=round(usd, 8),
            mode=driver.mode, provider=driver.provider, model=driver.model, stop_reason=stop, error=error,
        )  # fmt: skip

    turn = 0
    while turn < max_turns:
        turn += 1
        t0 = time.monotonic()
        if driver.mode == "live":
            try:
                budget.check(stage)
            except budget.BudgetExceeded as exc:
                if not calls:
                    raise
                return result("error", error=str(exc))
        try:
            decision = driver.next(history)
        except Exception as exc:
            err = retry.classify(exc, driver.provider)
            ms = round((time.monotonic() - t0) * 1000)
            if isinstance(driver, (MetaDriver, ChatDriver)):
                health.note(driver.route, stage, ms)
            record_call(
                stage=stage, provider=driver.provider, model=driver.model, mode=driver.mode, usage=Usage(), ms=ms,
                usd=0.0, ok=False, error=str(err),
            )  # fmt: skip
            if driver.mode == "live" and not calls and routes:
                driver = _live_driver(routes.pop(0), req, tools, effort, keep_images)
                turn -= 1
                continue
            if driver.mode == "live" and not calls and s.fallback_to_mock:
                warn_once(f"{stage}: live agent failed ({err}); PROVIDER_FALLBACK_TO_MOCK=1 → mock")
                driver = mock_driver
                turn -= 1
                continue
            if not calls:
                raise err from exc
            return result("error", error=str(err))
        ms = round((time.monotonic() - t0) * 1000)
        turn_usd = 0.0
        if isinstance(driver, (MetaDriver, ChatDriver)):
            health.note(driver.route, stage, ms)
        if driver.mode == "live":
            turn_usd = pricing.token_cost_usd(driver.provider, decision.model or driver.model, decision.usage)
            if s.record:
                replay.save(
                    _turn_digest(stage, req, tools, history),
                    {
                        "kind": "agent_turn", "stage": stage, "provider": driver.provider, "model": decision.model,
                        "response": decision.to_record(), "usage": decision.usage.to_dict(), "usd": turn_usd, "ms": ms,
                    },
                )  # fmt: skip
        record_call(
            stage=stage, provider=driver.provider, model=decision.model or driver.model, mode=driver.mode,
            usage=decision.usage, ms=ms, usd=turn_usd,
        )  # fmt: skip
        usage = usage + decision.usage
        usd += turn_usd
        record_thought(
            stage=stage, model=decision.model or driver.model, text=decision.thought, iter=turn, mode=driver.mode
        )
        if decision.text:
            final_text = decision.text
        if not decision.calls:
            return result("final")
        for call in decision.calls:
            name, args = str(call.get("name") or ""), dict(call.get("args") or {})
            t1 = time.monotonic()
            ok = True
            if name not in names:
                out = ToolResult(text=f"unknown tool {name!r}; available: {', '.join(sorted(names))}")
                ok = False
            elif "__invalid_json__" in args:
                out = ToolResult(text=f"arguments were not valid JSON: {args['__invalid_json__'][:200]}")
                ok = False
            else:
                try:
                    out = call_tool(name, args)
                except Exception as exc:  # a failing tool is reported to the model, not raised
                    out = ToolResult(text=f"tool error: {type(exc).__name__}: {str(exc)[:300]}")
                    ok = False
            tool_ms = round((time.monotonic() - t1) * 1000)
            record_tool_call(
                stage=stage, name=name, args=args, result=out.text, ok=ok, ms=tool_ms, iter=turn, mode=driver.mode
            )
            history.append(
                {
                    "turn": turn, "tool": name, "args": args, "result": out.text, "data": out.data, "ok": ok,
                    "images": len(out.images), "image_shas": [sha256(i) for i in out.images],
                }
            )  # fmt: skip
            calls.append(
                {
                    "turn": turn,
                    "name": name,
                    "args": args,
                    "result": out.text,
                    "ok": ok,
                    "ms": tool_ms,
                    "images": len(out.images),
                }
            )
            driver.add_result(call, out)
            if ok and name == "submit" and not out.data.get("continue"):
                return result("submit", submitted=args)
            if ok and out.done:
                return result("done", submitted=out.data or args)
    return result("max_turns")
