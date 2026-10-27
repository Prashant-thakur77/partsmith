"""Tool loop: mock path runs the real tools; Responses and Chat paths checked against fake transports."""

from __future__ import annotations

import json
from typing import Any

import numpy as np
import pytest
from partsmith_schemas.events import ModelCallEvent, ThoughtEvent, ToolCallEvent

from services.agent import providers
from services.agent.providers import ModelRequest, ToolResult, ToolSpec, media

from .conftest import FakeHTTPError, FakeHub, Obj

PNG = media.encode_png(np.zeros((8, 8, 3), np.uint8))
TOOLS = [
    ToolSpec(
        "measure",
        "Measure a feature",
        {"type": "object", "properties": {"feature": {"type": "string"}}, "required": ["feature"]},
    ),
    ToolSpec("render", "Render an overlay", {"type": "object", "properties": {}}),
    ToolSpec(
        "submit",
        "Submit the final parameters",
        {"type": "object", "properties": {"hole_d": {"type": "number", "minimum": 2}}, "required": ["hole_d"]},
    ),
]
REQ = ModelRequest(
    messages=[{"role": "system", "content": "fix it"}, {"role": "user", "content": "residuals..."}], images=[PNG]
)


class Tools:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def __call__(self, name: str, args: dict[str, Any]) -> ToolResult:
        self.calls.append((name, args))
        if name == "measure":
            return ToolResult(text=f"{args['feature']} = 4.31 mm", data={"value_mm": 4.31})
        if name == "render":
            return ToolResult(text="overlay attached", images=[PNG])
        if name == "boom":
            raise RuntimeError("tool exploded")
        return ToolResult(text="accepted")


def _by_type(events: list[Any], kind: type) -> list[Any]:
    return [e for e in events if isinstance(e, kind)]


def test_mock_loop_runs_real_tools_and_emits_trace(events: list[Any]) -> None:
    def handler(req: ModelRequest, history: list[dict[str, Any]]) -> dict[str, Any]:
        if not history:
            return {"tool": "measure", "args": {"feature": "hole_1"}, "thought": "hole looks small"}
        assert history[-1]["result"] == "hole_1 = 4.31 mm" and history[-1]["data"] == {"value_mm": 4.31}
        return {"tool": "submit", "args": {"hole_d": 4.3}}

    providers.register_mock("fix_agent", handler)
    tools = Tools()
    with providers.job_context("job", events.append, ctx="c"):
        out = providers.run_agent("fix_agent", REQ, TOOLS, tools)
    assert tools.calls == [("measure", {"feature": "hole_1"}), ("submit", {"hole_d": 4.3})]
    assert (out.stop_reason, out.submitted, out.turns, out.mode, out.usd) == ("submit", {"hole_d": 4.3}, 2, "mock", 0.0)
    assert [c["name"] for c in out.calls] == ["measure", "submit"]
    assert [e.mode for e in _by_type(events, ModelCallEvent)] == ["mock", "mock"]
    (thought,) = _by_type(events, ThoughtEvent)
    assert thought.text == "hole looks small" and thought.stage == "fix_agent" and thought.iter == 1
    tc = _by_type(events, ToolCallEvent)
    assert [(t.name, t.ok, t.iter) for t in tc] == [("measure", True, 1), ("submit", True, 2)]


def test_builtin_mock_submits_schema_minimal_args() -> None:
    out = providers.run_agent("fix_agent", REQ, TOOLS, Tools())
    assert out.stop_reason == "submit" and out.submitted == {"hole_d": 2}


def test_bad_tools_are_reported_back_and_max_turns_returns() -> None:
    script = [
        {"tool": "nope", "args": {}},
        {"tool": "measure", "args": {"__invalid_json__": "{bad"}},
        {"tool": "boom", "args": {}},
        {"tool": "render", "args": {}},
    ]
    providers.register_mock("fix_agent", lambda req, history: script[min(len(history), 3)])
    tools = [*TOOLS, ToolSpec("boom", "fails", {"type": "object", "properties": {}})]
    out = providers.run_agent("fix_agent", REQ, tools, Tools(), max_turns=5)
    assert out.stop_reason == "max_turns" and out.turns == 5 and out.submitted is None
    assert [c["ok"] for c in out.calls[:3]] == [False, False, False]
    assert "unknown tool 'nope'" in out.calls[0]["result"] and "not valid JSON" in out.calls[1]["result"]
    assert "tool exploded" in out.calls[2]["result"] and out.calls[3]["images"] == 1


def test_done_result_and_submit_continue() -> None:
    class Guarded(Tools):
        def __call__(self, name: str, args: dict[str, Any]) -> ToolResult:
            self.calls.append((name, args))
            if name == "submit" and len(self.calls) == 1:
                return ToolResult(text="rejected: hole_d outside range", data={"continue": True})
            if name == "render":
                return ToolResult(text="ok", done=True, data={"final": 1})
            return ToolResult(text="accepted")

    providers.register_mock(
        "fix_agent",
        lambda req, h: {"tool": "submit", "args": {"hole_d": 99}} if not h else {"tool": "render", "args": {}},
    )
    out = providers.run_agent("fix_agent", REQ, TOOLS, Guarded())
    assert out.stop_reason == "done" and out.submitted == {"final": 1} and out.turns == 2


def _resp_events(output: list[dict[str, Any]], text: str = "", tin: int = 100, tout: int = 40) -> list[dict[str, Any]]:
    lane = {"item_id": "m", "output_index": 0, "content_index": 0}
    events: list[dict[str, Any]] = []
    if text:
        events.append({"type": "response.output_text.delta", **lane, "delta": text})
    events.append(
        {
            "type": "response.completed",
            "response": {"output": output, "usage": {"input_tokens": tin, "output_tokens": tout}},
        }
    )
    return events


def test_meta_responses_tool_loop(monkeypatch: pytest.MonkeyPatch, hub: FakeHub, events: list[Any]) -> None:
    monkeypatch.setenv("MODEL_API_KEY", "k-meta-000000")
    monkeypatch.setenv("BASETEN_API_KEY", "")
    reasoning = {
        "type": "reasoning",
        "id": "rs_1",
        "summary": [{"type": "summary_text", "text": "Render first."}],
        "encrypted_content": "enc",
    }
    call1 = {"type": "function_call", "id": "fc_1", "call_id": "call_1", "name": "render", "arguments": "{}"}
    call2 = {"type": "function_call", "id": "fc_2", "call_id": "call_2", "name": "render", "arguments": "{}"}
    final_msg = {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "Looks right."}]}
    hub.handlers[("responses", "meta")] = [
        _resp_events([reasoning, call1]),
        _resp_events([call2]),
        _resp_events([final_msg], text="Looks right."),
    ]
    with providers.job_context("j", events.append):
        out = providers.run_agent("fix_agent", REQ, TOOLS, Tools(), keep_images=1)
    reqs = hub.calls_for("responses")
    assert len(reqs) == 3
    kw = reqs[0]
    assert kw["model"] == "muse-spark-1.3" and kw["tool_choice"] == "auto" and kw["parallel_tool_calls"] is False
    assert kw["store"] is False and kw["include"] == ["reasoning.encrypted_content"] and kw["stream"] is True
    assert kw["reasoning"] == {"effort": "medium", "summary": "auto"}
    assert kw["tools"][0] == {"type": "function", **{k: v for k, v in TOOLS[0].flat().items() if k != "type"}}
    second = reqs[1]["input"]
    assert second[0] == {"type": "message", "role": "developer", "content": "fix it"}  # instructions resent
    assert {"type": "reasoning", "id": "rs_1", "summary": reasoning["summary"], "encrypted_content": "enc"} in second
    fco = [i for i in second if i.get("type") == "function_call_output"]
    assert fco[0]["call_id"] == "call_1"
    assert [p["type"] for p in fco[0]["output"]] == ["input_text", "input_image"]
    third = [i for i in reqs[2]["input"] if i.get("type") == "function_call_output"]
    assert [p["type"] for p in third[0]["output"]] == ["input_text", "input_text"]  # older image pruned
    assert "omitted" in third[0]["output"][1]["text"]
    assert [p["type"] for p in third[1]["output"]] == ["input_text", "input_image"]
    assert reqs[2]["input"][1]["content"][1]["type"] == "input_image"  # the original photo always stays
    assert out.final_text == "Looks right." and out.stop_reason == "final" and out.turns == 3
    assert out.usage.tokens_in == 300 and out.usd == pytest.approx(3 * (100 * 1.25 + 40 * 4.25) / 1e6)
    assert _by_type(events, ThoughtEvent)[0].text == "Render first."
    assert len(_by_type(events, ModelCallEvent)) == 3 and len(_by_type(events, ToolCallEvent)) == 2


def _chat_tool_chunks(name: str, args: str, note: str = "") -> list[Obj]:
    chunks = []
    if note:
        chunks.append(Obj(choices=[Obj(delta=Obj(content=note))]))
    tc = Obj(index=0, id="tc_1", function=Obj(name=name, arguments=args[:3]))
    tc2 = Obj(index=0, id=None, function=Obj(name=None, arguments=args[3:]))
    chunks += [Obj(choices=[Obj(delta=Obj(tool_calls=[tc]))]), Obj(choices=[Obj(delta=Obj(tool_calls=[tc2]))])]
    chunks.append(Obj(choices=[], usage=Obj(prompt_tokens=50, completion_tokens=10)))
    return chunks


def test_chat_tool_loop_baseten(monkeypatch: pytest.MonkeyPatch, hub: FakeHub, events: list[Any]) -> None:
    monkeypatch.setenv("BASETEN_API_KEY", "k-baseten-000")
    hub.handlers[("chat", "baseten")] = [
        _chat_tool_chunks("render", "{}", note="Checking the overlay."),
        _chat_tool_chunks("submit", json.dumps({"hole_d": 4.4})),
    ]
    tools = Tools()
    with providers.job_context("j", events.append):
        out = providers.run_agent("fix_agent", REQ, TOOLS, tools)
    reqs = hub.calls_for("chat")
    kw = reqs[0]
    assert kw["tools"][0] == TOOLS[0].nested() and kw["tool_choice"] == "auto" and kw["parallel_tool_calls"] is False
    assert kw["reasoning_effort"] == "medium" and kw["model"] == "meta-models/muse-spark-open"
    msgs = reqs[1]["messages"]
    assert msgs[-3]["role"] == "assistant" and msgs[-3]["tool_calls"][0]["function"]["name"] == "render"
    assert msgs[-2] == {"role": "tool", "tool_call_id": "tc_1", "content": "overlay attached"}
    assert msgs[-1]["role"] == "user" and [p["type"] for p in msgs[-1]["content"]] == ["text", "text", "image_url"]
    assert all("tool_images" not in m for m in msgs)
    assert out.submitted == {"hole_d": 4.4} and out.provider == "baseten" and out.usage.tokens_in == 100
    assert _by_type(events, ThoughtEvent)[0].text == "Checking the overlay."


def test_live_route_fallback_on_first_turn(monkeypatch: pytest.MonkeyPatch, hub: FakeHub) -> None:
    monkeypatch.setenv("BASETEN_API_KEY", "k-baseten-000")
    monkeypatch.setenv("FIREWORKS_API_KEY", "k-fireworks-00")
    monkeypatch.setenv("PROVIDER_MAX_RETRIES", "0")
    hub.handlers[("chat", "baseten")] = [FakeHTTPError(500, "down")]
    hub.handlers[("chat", "fireworks")] = [_chat_tool_chunks("submit", json.dumps({"hole_d": 5}))]
    out = providers.run_agent("fix_agent", REQ, TOOLS, Tools())
    assert out.provider == "fireworks" and out.submitted == {"hole_d": 5} and out.turns == 1


def test_glimmer_agent_uses_template_kwargs(monkeypatch: pytest.MonkeyPatch, hub: FakeHub) -> None:
    monkeypatch.setenv("GLIMMER_BASE_URL", "https://ws--glimmer.modal.run")
    hub.handlers[("chat", "modal.run")] = [_chat_tool_chunks("submit", json.dumps({"hole_d": 3}))]
    out = providers.run_agent("judge", REQ, TOOLS, Tools())
    kw = hub.calls_for("chat")[0]
    assert (
        kw["extra_body"] == {"chat_template_kwargs": {"reasoning_strength": "medium"}} and "reasoning_effort" not in kw
    )
    assert out.submitted == {"hole_d": 3}


def test_record_then_replay_agent_turns(monkeypatch: pytest.MonkeyPatch, hub: FakeHub) -> None:
    monkeypatch.setenv("BASETEN_API_KEY", "k-baseten-000")
    monkeypatch.setenv("PROVIDER_RECORD", "1")
    hub.handlers[("chat", "baseten")] = [
        _chat_tool_chunks("measure", json.dumps({"feature": "hole_1"})),
        _chat_tool_chunks("submit", json.dumps({"hole_d": 4.31})),
    ]
    live = providers.run_agent("fix_agent", REQ, TOOLS, Tools())
    monkeypatch.delenv("BASETEN_API_KEY")
    monkeypatch.delenv("PROVIDER_RECORD")
    monkeypatch.setenv("PROVIDER_MODE", "replay")
    tools = Tools()
    again = providers.run_agent("fix_agent", REQ, TOOLS, tools)
    assert again.mode == "replay" and again.submitted == live.submitted == {"hole_d": 4.31}
    assert tools.calls == [("measure", {"feature": "hole_1"}), ("submit", {"hole_d": 4.31})]
    # a different conversation misses the recording and continues as the labelled mock
    other = providers.run_agent("fix_agent", ModelRequest(messages=[{"role": "user", "content": "x"}]), TOOLS, Tools())
    assert other.mode == "mock"


def test_live_failure_without_progress_raises(monkeypatch: pytest.MonkeyPatch, hub: FakeHub) -> None:
    monkeypatch.setenv("MODEL_API_KEY", "k-meta-000000")
    monkeypatch.setenv("PROVIDER_MAX_RETRIES", "0")
    hub.handlers[("responses", "meta")] = [FakeHTTPError(401, "bad key")]
    with pytest.raises(providers.ProviderError, match="HTTP 401"):
        providers.run_agent("fix_agent", REQ, TOOLS, Tools())
    with pytest.raises(ValueError, match="not an agent stage"):
        providers.run_agent("segment", REQ, TOOLS, Tools())
