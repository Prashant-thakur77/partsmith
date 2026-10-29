from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest

from services.agent import providers
from services.agent.providers import (
    ModelRequest,
    ProviderError,
    SchemaValidationError,
    chat,
    core,
    health,
    media,
    routing,
)

from .conftest import FakeHTTPError, FakeHub, Obj, chat_stream, responses_stream

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"family": {"type": "string", "enum": ["clip", "hook"]}, "n": {"type": "integer", "minimum": 1}},
    "required": ["family", "n"],
    "additionalProperties": False,
}
PNG = media.encode_png(__import__("numpy").zeros((8, 8, 3), dtype="uint8"))


def _req(**kw: Any) -> ModelRequest:
    base: dict[str, Any] = {
        "messages": [{"role": "system", "content": "rules"}, {"role": "user", "content": "describe"}],
        "json_schema": SCHEMA,
        "schema_name": "partspec",
    }
    base.update(kw)
    return ModelRequest(**base)


def test_meta_responses_request_shape(monkeypatch: pytest.MonkeyPatch, hub: FakeHub, events: list[Any]) -> None:
    monkeypatch.setenv("MODEL_API_KEY", "k-meta-000000")
    hub.handlers[("responses", "api.meta.ai")] = [responses_stream('{"family": "clip", "n": 2}', 1000, 1000)]
    with providers.job_context("job1", events.append, ctx="c1") as ledger:
        out = providers.complete(
            "understand",
            _req(
                images=[PNG],
                reasoning_effort="none",
                temperature=0.2,
                max_tokens=8,
                tools=[{"type": "function", "function": {"name": "f", "parameters": {}}}],
            ),
        )
    kw = hub.calls_for("responses")[0]
    assert kw["model"] == "muse-spark-1.3"
    assert kw["text"]["format"] == {"type": "json_schema", "name": "partspec", "schema": SCHEMA, "strict": True}
    assert "response_format" not in kw
    assert kw["reasoning"] == {"effort": "minimal"}  # "none" is a 400 on Spark
    assert kw["max_output_tokens"] == 16  # API minimum
    assert kw["tool_choice"] == "auto" and kw["tools"][0] == {"type": "function", "name": "f", "parameters": {}}
    assert kw["stream"] is True and kw["store"] is False
    assert kw["input"][0] == {"type": "message", "role": "developer", "content": "rules"}
    parts = kw["input"][1]["content"]
    assert parts[0] == {"type": "input_text", "text": "describe"}
    assert parts[1]["type"] == "input_image" and parts[1]["image_url"].startswith("data:image/png;base64,")
    assert hub.keys_seen == ["k-meta-000000"]
    assert out.json == {"family": "clip", "n": 2} and out.mode == "live" and out.provider == "meta"
    assert out.usd == pytest.approx((1000 * 1.25 + 1000 * 4.25) / 1e6)
    assert ledger.usd_total == pytest.approx(out.usd)
    (ev,) = events
    assert (ev.job, ev.ctx, ev.stage, ev.mode, ev.ok) == ("job1", "c1", "understand", "live", True)
    assert (ev.tokens_in, ev.tokens_out, ev.provider, ev.model) == (1000, 1000, "meta", "muse-spark-1.3")


def test_large_images_go_through_files_api(monkeypatch: pytest.MonkeyPatch, hub: FakeHub) -> None:
    monkeypatch.setenv("MODEL_API_KEY", "k-meta-000000")
    hub.handlers[("responses", "meta")] = [responses_stream('{"family": "hook", "n": 1}')]
    big = PNG + b"\0" * (1100 * 1024)  # still sniffs as PNG
    providers.complete("understand", _req(images=[big]))
    assert len(hub.calls_for("files")) == 1
    assert hub.calls_for("files")[0]["purpose"] == "user_data"
    image_part = hub.calls_for("responses")[0]["input"][1]["content"][1]
    assert image_part["type"] == "input_image" and image_part["file_id"].startswith("file-")


def test_baseten_chat_request_shape_and_model_listing(monkeypatch: pytest.MonkeyPatch, hub: FakeHub) -> None:
    monkeypatch.setenv("BASETEN_API_KEY", "k-baseten-000")
    monkeypatch.setenv("SPARK_OPEN_MODEL", "meta-models/muse-spark-open-1026")
    hub.model_ids = ["meta-models/muse-spark-open", "other/model"]
    hub.handlers[("chat", "baseten")] = [chat_stream('{"family": "hook", "n": 3}', 200, 50)]
    out = providers.complete("build", _req(images=[PNG]))
    kw = hub.calls_for("chat")[0]
    assert kw["model"] == "meta-models/muse-spark-open"  # override not served → listed id wins
    assert kw["response_format"]["type"] == "json_schema"
    assert kw["response_format"]["json_schema"] == {"name": "partspec", "schema": SCHEMA, "strict": True}
    assert kw["reasoning_effort"] == "medium"  # loop default
    assert kw["stream"] is True and kw["stream_options"] == {"include_usage": True}
    assert kw["messages"][0] == {"role": "system", "content": "rules"}
    assert kw["messages"][1]["content"][1]["type"] == "image_url"
    assert "text" not in kw
    assert out.provider == "baseten" and out.json == {"family": "hook", "n": 3}
    assert out.usd == pytest.approx((200 * 1.25 + 50 * 4.25) / 1e6)
    assert len(hub.calls_for("models")) == 1
    providers.complete("fix", _req())
    assert len(hub.calls_for("models")) == 1  # cached
    assert providers.status()[1]["model"] == "meta-models/muse-spark-open"


def test_spark_open_id_selection() -> None:
    assert chat.pick_spark_open_id(["a/muse-spark-open-1026"], None) == "a/muse-spark-open-1026"
    assert chat.pick_spark_open_id(["x/muse-spark-open"], "x/muse-spark-open") == "x/muse-spark-open"
    assert chat.pick_spark_open_id([], "custom/id") == "custom/id"
    assert chat.pick_spark_open_id([], None) == "meta-models/muse-spark-open"
    both = ["meta-models/muse-spark-open", "meta-models/muse-spark-open-1026", "zai-org/GLM-5.2"]
    assert chat.pick_spark_open_id(both, None) == "meta-models/muse-spark-open-1026"  # the hackathon deployment
    assert chat.pick_spark_open_id(both, "meta-models/muse-spark-open") == "meta-models/muse-spark-open"


def test_glimmer_llamacpp_shape(monkeypatch: pytest.MonkeyPatch, hub: FakeHub) -> None:
    monkeypatch.setenv("GLIMMER_BASE_URL", "https://ws--partsmith-glimmer.modal.run/")
    raw = 'to=self<|message|>hmm<|eom|><|start|>assistant to=user<|message|>{"vetoes": [], "notes": "ok"}<|eot|>'
    hub.handlers[("chat", "modal.run")] = [chat_stream(raw)]
    schema = {
        "type": "object",
        "properties": {"vetoes": {"type": "array", "items": {"type": "object"}}, "notes": {"type": "string"}},
        "required": ["vetoes", "notes"],
        "additionalProperties": False,
    }
    out = providers.complete(
        "judge", ModelRequest(messages=[{"role": "user", "content": "judge"}], images=[PNG], json_schema=schema)
    )
    base_url = hub.calls[0][1]
    assert base_url == "https://ws--partsmith-glimmer.modal.run/v1"
    kw = hub.calls_for("chat")[0]
    assert kw["model"] == "muse-glimmer"
    assert "reasoning_effort" not in kw
    assert kw["extra_body"] == {"chat_template_kwargs": {"reasoning_strength": "medium"}}
    assert out.json == {"vetoes": [], "notes": "ok"}
    assert out.usd == 0.0  # self-hosted: GPU time is billed by Modal, not per token
    assert hub.keys_seen == ["no-key"]


def test_schema_repair_retry_once(monkeypatch: pytest.MonkeyPatch, hub: FakeHub, events: list[Any]) -> None:
    monkeypatch.setenv("MODEL_API_KEY", "k-meta-000000")
    hub.handlers[("responses", "meta")] = [
        responses_stream('{"family": "gear", "n": 0}', 100, 10),
        responses_stream('```json\n{"family": "clip", "n": 1}\n```', 150, 10),
    ]
    with providers.job_context("j", events.append):
        out = providers.complete("understand", _req(images=[PNG]))
    assert out.json == {"family": "clip", "n": 1}
    second = hub.calls_for("responses")[1]["input"]
    assert second[-2] == {"type": "message", "role": "assistant", "content": '{"family": "gear", "n": 0}'}
    assert "did not match" in second[-1]["content"][0]["text"]
    assert second[1]["content"][1]["type"] == "input_image"  # images stay on the original message
    assert len(events) == 1 and events[0].tokens_in == 250


def test_schema_failure_after_repair_falls_through_then_raises(
    monkeypatch: pytest.MonkeyPatch, hub: FakeHub, events: list[Any]
) -> None:
    monkeypatch.setenv("MODEL_API_KEY", "k-meta-000000")
    hub.handlers[("responses", "meta")] = [responses_stream("not json at all")]
    with (
        providers.job_context("j", events.append),
        pytest.raises(SchemaValidationError, match="failed schema after one repair"),
    ):
        providers.complete("understand", _req())
    assert len(hub.calls_for("responses")) == 2
    assert events[0].ok is False and events[0].tokens_in == 200 and events[0].usd > 0


def test_schema_validation_error_type(monkeypatch: pytest.MonkeyPatch, hub: FakeHub) -> None:
    from services.agent.providers import core, routing

    monkeypatch.setenv("MODEL_API_KEY", "k-meta-000000")
    hub.handlers[("responses", "meta")] = [responses_stream('{"family": "x"}')]
    with pytest.raises(SchemaValidationError) as info:
        core._live_text(routing.SPARK_13, "understand", _req(), providers.config.settings())
    assert info.value.errors and info.value.text == '{"family": "x"}'


def test_fallback_chain_and_retries(monkeypatch: pytest.MonkeyPatch, hub: FakeHub, events: list[Any]) -> None:
    monkeypatch.setenv("BASETEN_API_KEY", "k-baseten-000")
    monkeypatch.setenv("FIREWORKS_API_KEY", "k-fireworks-00")
    monkeypatch.setenv("PROVIDER_MAX_RETRIES", "1")
    hub.handlers[("chat", "baseten")] = [FakeHTTPError(503, "unavailable")]
    hub.handlers[("chat", "fireworks")] = [FakeHTTPError(429, "slow down"), chat_stream('{"family": "clip", "n": 1}')]
    with providers.job_context("j", events.append):
        out = providers.complete("plan", _req())
    assert out.provider == "fireworks" and out.model == "accounts/fireworks/models/muse-spark-open"
    assert len([c for c in hub.calls if c[0] == "chat" and "baseten" in c[1]]) == 2  # 1 try + 1 retry
    assert len([c for c in hub.calls if c[0] == "chat" and "fireworks" in c[1]]) == 2  # 429 then ok
    assert [(e.provider, e.ok) for e in events] == [("baseten", False), ("fireworks", True)]
    assert "HTTP 503" in (events[0].error or "")


def test_non_retryable_error_is_redacted(monkeypatch: pytest.MonkeyPatch, hub: FakeHub) -> None:
    monkeypatch.setenv("MODEL_API_KEY", "k-meta-supersecret")
    hub.handlers[("responses", "meta")] = [FakeHTTPError(401, "bad key k-meta-supersecret")]
    with pytest.raises(ProviderError) as info:
        providers.complete("understand", _req())
    assert "supersecret" not in str(info.value)
    assert "HTTP 401" in str(info.value)
    assert len(hub.calls_for("responses")) == 1


def test_fallback_to_mock_flag(monkeypatch: pytest.MonkeyPatch, hub: FakeHub) -> None:
    monkeypatch.setenv("MODEL_API_KEY", "k-meta-000000")
    monkeypatch.setenv("PROVIDER_FALLBACK_TO_MOCK", "1")
    hub.handlers[("responses", "meta")] = [FakeHTTPError(400, "bad")]
    out = providers.complete("understand", _req())
    assert out.mode == "mock" and out.json == {"family": "clip", "n": 1}


def test_non_stream_and_text_only(monkeypatch: pytest.MonkeyPatch, hub: FakeHub) -> None:
    monkeypatch.setenv("MODEL_API_KEY", "k-meta-000000")
    hub.handlers[("responses", "meta")] = [
        Obj(output_text="plain answer", output=[], usage=Obj(input_tokens=5, output_tokens=2))
    ]
    out = providers.complete("steer_plan", ModelRequest(messages=[{"role": "user", "content": "hi"}], stream=False))
    kw = hub.calls_for("responses")[0]
    assert "stream" not in kw and kw["model"] == "muse-wonder-1.0" and kw["reasoning"] == {"effort": "medium"}
    assert out.text == "plain answer" and out.json is None
    assert out.usd == pytest.approx((5 * 4.0 + 2 * 20.0) / 1e6)


def test_tool_calls_returned_from_responses(monkeypatch: pytest.MonkeyPatch, hub: FakeHub) -> None:
    monkeypatch.setenv("MODEL_API_KEY", "k-meta-000000")
    stream = responses_stream("")
    stream[-1]["response"]["output"] = [
        {"type": "function_call", "call_id": "c1", "name": "lookup", "arguments": json.dumps({"q": "x"})}
    ]
    hub.handlers[("responses", "meta")] = [stream]
    out = providers.complete(
        "variant",
        ModelRequest(
            messages=[{"role": "user", "content": "x"}],
            tools=[{"type": "function", "name": "lookup", "parameters": {}}],
        ),
    )
    assert out.tool_calls == [{"id": "c1", "name": "lookup", "arguments": '{"q": "x"}'}]


def test_self_hosted_endpoint_waits_for_cold_start(monkeypatch: pytest.MonkeyPatch, hub: FakeHub) -> None:
    monkeypatch.setenv("GLIMMER_BASE_URL", "https://ws--glimmer.modal.run")
    monkeypatch.setenv("PROVIDER_MAX_RETRIES", "1")
    replies: list[Any] = [FakeHTTPError(503, "no replica")] * 6 + [chat_stream("ready")]
    hub.handlers[("chat", "modal.run")] = replies
    out = providers.complete("capture_triage", ModelRequest(messages=[{"role": "user", "content": "ok?"}]))
    assert out.text == "ready" and len(hub.calls_for("chat")) == 7


def test_a_slow_route_goes_behind_the_ready_fallback_until_its_cool_down_ends(
    monkeypatch: pytest.MonkeyPatch, hub: FakeHub, events: list[Any]
) -> None:
    monkeypatch.setenv("BASETEN_API_KEY", "k-baseten-000")
    monkeypatch.setenv("MODEL_API_KEY", "k-meta-000000")
    now = [1000.0]
    monkeypatch.setattr(core, "time", SimpleNamespace(monotonic=lambda: now[0]))
    monkeypatch.setattr(health, "clock", lambda: now[0])

    def slow_baseten(kw: dict[str, Any]) -> Any:
        now[0] += 50.0  # live, 2026-10-29: shared hackathon deployment, 28 s median and up to 318 s per turn
        return chat_stream('{"family": "clip", "n": 1}')

    hub.handlers[("chat", "baseten")] = slow_baseten
    hub.handlers[("responses", "meta")] = lambda kw: responses_stream('{"family": "clip", "n": 1}')
    with providers.job_context("j", events.append):
        served = [providers.complete("plan", _req()).provider for _ in range(health.MIN_CALLS + 1)]
        assert served == ["baseten"] * health.MIN_CALLS + ["meta"]
        assert "Baseten slow (50 s per call) → Meta Model API first" in routing.resolve("plan").note
        now[0] += health.COOL_DOWN_S
        assert providers.complete("plan", _req()).provider == "baseten"  # a fresh window after the cool-down
    assert [e.provider for e in events] == [*served, "baseten"]  # every call still names the model that served it


def test_a_slow_route_with_no_ready_alternative_keeps_its_place(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BASETEN_API_KEY", "k-baseten-000")
    route = routing.SPARK_OPEN_BASETEN
    for _ in range(health.MIN_CALLS):
        health.note(route, "fix_agent", 90_000)
    assert health.slow(route, "fix_agent") == pytest.approx(90.0)
    res = routing.resolve("fix_agent")  # Spark 1.3 is not ready without a Meta key
    assert res.routes == [route] and "slow" not in res.note
    health.note(routing.SPARK_13, "fix_agent", 2_000)
    assert health.slow(routing.SPARK_13, "fix_agent") is None


def test_a_stage_that_is_slow_by_nature_does_not_demote_the_route_for_other_stages() -> None:
    for _ in range(health.MIN_CALLS):  # live, 2026-10-29: understand reads two photos, 36–55 s per call
        health.note(routing.SPARK_13, "understand", 49_000)
    assert health.slow(routing.SPARK_13, "understand") is not None
    assert health.slow(routing.SPARK_13, "fix_agent") is None
