"""OpenAI-compatible Chat Completions adapter: Muse Spark Open (Baseten / Fireworks / Together) and
Muse Glimmer 30B (llama.cpp server on Modal, or Together).

- Strict JSON via `response_format={"type": "json_schema", ...}` (the Chat-Completions spelling).
- Spark Open: `reasoning_effort` low|medium|high|xhigh (server default xhigh; the loop uses medium).
- Glimmer on llama.cpp: no `reasoning_effort`; reasoning length goes through `chat_template_kwargs.reasoning_strength`.
- Calls stream by default with `stream_options.include_usage` so long generations don't hit gateway timeouts.
- Baseten's Spark Open id comes from `models.list()` (override: `SPARK_OPEN_MODEL`).
"""

from __future__ import annotations

import json
import re
from typing import Any

from . import clients, media
from .base import LiveText, ModelRequest, ProviderError, Usage
from .clients import field
from .config import env, log, warn_once
from .routing import SPARK_OPEN_DEFAULT_ID, Route

SPARK_OPEN_EFFORTS = ("low", "medium", "high", "xhigh")
GLIMMER_STRENGTHS = ("low", "medium", "high", "xhigh")
# Judge crops: every image is prompt tokens inside one 65,536-token llama.cpp slot (reasoning shares it). Keep images
# at or below this side length and roughly a dozen per request.
GLIMMER_MAX_IMAGE_SIDE = 1024
GLIMMER_MAX_IMAGES = 12
_model_cache: dict[tuple[str, str], str] = {}


def is_glimmer(route: Route) -> bool:
    return "glimmer" in route.model.lower()


def base_url(route: Route) -> str:
    url = route.endpoint.base_url()
    if not url:
        raise ProviderError(f"{route.endpoint.url_env} missing", provider=route.provider)
    if route.endpoint.name == "modal_glimmer" and not url.endswith("/v1"):
        url = url + "/v1"  # GLIMMER_BASE_URL may be the bare Modal URL
    return url


def client_for(route: Route, timeout_s: float) -> Any:
    key = route.endpoint.key()
    if not key and not route.endpoint.key_optional:
        raise ProviderError(f"{route.endpoint.key_env} missing", provider=route.provider)
    # llama.cpp without --api-key accepts any token; the SDK needs a non-empty string.
    return clients.get_client(base_url(route), key or "no-key", timeout_s)


def map_effort(effort: str | None, allowed: tuple[str, ...], default: str) -> str:
    e = (effort or default).lower()
    if e in ("none", "minimal"):
        return "low"  # reasoning cannot be turned off on these models
    if e == "max":
        return "xhigh"
    return e if e in allowed else default


def pick_spark_open_id(ids: list[str], override: str | None) -> str:
    """Choose the Spark Open id from a `models.list()` result, honouring an override only if it is served."""
    candidates = [i for i in ids if "muse-spark-open" in i.lower()]
    if override and (override in ids or not ids):
        return override
    if candidates:
        chosen = SPARK_OPEN_DEFAULT_ID if SPARK_OPEN_DEFAULT_ID in candidates else sorted(candidates)[0]
        if override:
            warn_once(f"SPARK_OPEN_MODEL={override!r} is not served by this provider; using {chosen!r}")
        return chosen
    return override or SPARK_OPEN_DEFAULT_ID


def list_model_ids(client: Any) -> list[str]:
    page = client.models.list()
    items = field(page, "data", None)
    if items is None:
        items = list(page)
    return [str(field(m, "id")) for m in items if field(m, "id")]


def resolve_model(route: Route, client: Any) -> str:
    """Baseten: the id that `models.list()` reports (cached per process); other providers: the documented id."""
    if route.endpoint.name != "baseten" or is_glimmer(route):
        return route.model
    override = env("SPARK_OPEN_MODEL")
    cache_key = (base_url(route), override or "")
    if cache_key not in _model_cache:
        try:
            ids = list_model_ids(client)
        except Exception as exc:  # listing is best-effort; the completion call reports real failures
            log.info("baseten models.list() failed (%s); using %s", type(exc).__name__, override or route.model)
            ids = []
        _model_cache[cache_key] = pick_spark_open_id(ids, override)
    return _model_cache[cache_key]


def cached_model(route: Route) -> str | None:
    """The id `resolve_model` picked for this route in this process, if any (no network)."""
    url = route.endpoint.base_url()
    for (cached_url, _), model in _model_cache.items():
        if url and cached_url.startswith(url):
            return model
    return None


def reset_model_cache() -> None:
    _model_cache.clear()


def image_parts(
    images: list[bytes], labels: list[str] | None = None, max_side: int | None = None
) -> list[dict[str, Any]]:
    """Chat content parts: optional caption + image_url per image, in order. Several images per message are fine on
    llama.cpp with a vision projector; each costs prompt tokens that grow with resolution, so Glimmer images are
    downscaled to `GLIMMER_MAX_IMAGE_SIDE` px."""
    out: list[dict[str, Any]] = []
    for i, img in enumerate(images):
        if labels and i < len(labels) and labels[i]:
            out.append({"type": "text", "text": f"Image {i + 1}: {labels[i]}"})
        data = media.fit_image(img, max_side) if max_side else img
        out.append({"type": "image_url", "image_url": {"url": media.data_url(data)}})
    return out


def build_messages(req: ModelRequest, max_side: int | None = None) -> list[dict[str, Any]]:
    at = req.image_message_index()
    out: list[dict[str, Any]] = []
    for i, msg in enumerate(req.messages):
        role = msg.get("role", "user")
        role = "system" if role == "developer" else role  # widest support across OpenAI-compatible servers
        content = msg.get("content", "")
        if role == "user" and i == at:
            parts: list[dict[str, Any]] = [{"type": "text", "text": content}]
            parts += image_parts(req.images, req.image_labels, max_side)
            out.append({"role": "user", "content": parts})
        else:
            out.append({"role": role, "content": content})
    return out


def _nested_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for t in tools:
        if t.get("type") == "function" and "function" not in t:
            fn = {k: v for k, v in t.items() if k != "type"}
            out.append({"type": "function", "function": fn})
        else:
            out.append(t)
    return out


def chat_kwargs(route: Route, req: ModelRequest, model: str, default_effort: str | None) -> dict[str, Any]:
    max_side = GLIMMER_MAX_IMAGE_SIDE if is_glimmer(route) else None
    if max_side and len(req.images) > GLIMMER_MAX_IMAGES:
        raise ProviderError(
            f"Glimmer requests take at most {GLIMMER_MAX_IMAGES} images (got {len(req.images)}); send fewer crops",
            provider=route.provider,
        )
    kwargs: dict[str, Any] = {"model": model, "messages": build_messages(req, max_side)}
    if req.json_schema is not None:
        kwargs["response_format"] = {
            "type": "json_schema",
            "json_schema": {"name": req.schema_name, "schema": req.json_schema, "strict": req.strict},
        }
    if is_glimmer(route):
        if route.endpoint.name == "modal_glimmer":
            strength = map_effort(req.reasoning_effort or default_effort, GLIMMER_STRENGTHS, "low")
            kwargs["extra_body"] = {"chat_template_kwargs": {"reasoning_strength": strength}}
    else:
        kwargs["reasoning_effort"] = map_effort(req.reasoning_effort or default_effort, SPARK_OPEN_EFFORTS, "medium")
    if req.temperature is not None:
        kwargs["temperature"] = req.temperature
    if req.max_tokens:
        kwargs["max_tokens"] = int(req.max_tokens)
    if req.tools:
        kwargs["tools"] = _nested_tools(req.tools)
        kwargs["tool_choice"] = "auto"
    return kwargs


def _usage(u: Any) -> Usage:
    if u is None:
        return Usage()
    prompt_details = field(u, "prompt_tokens_details")
    completion_details = field(u, "completion_tokens_details")
    return Usage(
        tokens_in=int(field(u, "prompt_tokens", 0) or 0),
        tokens_out=int(field(u, "completion_tokens", 0) or 0),
        cached_in=int(field(prompt_details, "cached_tokens", 0) or 0) if prompt_details is not None else 0,
        reasoning_tokens=int(field(completion_details, "reasoning_tokens", 0) or 0)
        if completion_details is not None
        else 0,
    )


_CHANNEL_USER_RE = re.compile(r"to=user<\|message\|>(.*?)(?=<\|eot\|>|<\|eom\|>|$)", re.DOTALL)
_SPECIAL_RE = re.compile(r"<\|[a-z_]+\|>")


def clean_glimmer_text(text: str) -> str:
    """Keep only the user-facing channel if raw channel markup leaked through the server's parser."""
    if "to=user<|message|>" in text:
        found = _CHANNEL_USER_RE.findall(text)
        text = found[-1] if found else text
    return _SPECIAL_RE.sub("", text).strip()


def collect_stream(chunks: Any) -> tuple[str, Usage, list[dict[str, Any]]]:
    parts: list[str] = []
    usage = Usage()
    tools: dict[int, dict[str, Any]] = {}
    for chunk in chunks:
        u = field(chunk, "usage")
        if u is not None:
            usage = _usage(u)
        for choice in field(chunk, "choices", None) or []:
            delta = field(choice, "delta")
            if delta is None:
                continue
            content = field(delta, "content")
            if content:
                parts.append(str(content))
            for tc in field(delta, "tool_calls", None) or []:
                idx = int(field(tc, "index", 0) or 0)
                slot = tools.setdefault(idx, {"id": None, "name": None, "arguments": ""})
                slot["id"] = field(tc, "id") or slot["id"]
                fn = field(tc, "function")
                if fn is not None:
                    slot["name"] = field(fn, "name") or slot["name"]
                    slot["arguments"] += field(fn, "arguments") or ""
    return "".join(parts), usage, [tools[i] for i in sorted(tools)]


def chat_complete(route: Route, req: ModelRequest, default_effort: str | None, timeout_s: float) -> LiveText:
    client = client_for(route, timeout_s)
    model = resolve_model(route, client)
    kwargs = chat_kwargs(route, req, model, default_effort)
    stream = True if req.stream is None else req.stream
    if stream:
        chunks = client.chat.completions.create(**kwargs, stream=True, stream_options={"include_usage": True})
        try:
            text, usage, tool_calls = collect_stream(chunks)
        finally:
            close = getattr(chunks, "close", None)
            if callable(close):
                close()
    else:
        resp = client.chat.completions.create(**kwargs)
        choices = field(resp, "choices", None) or []
        message = field(choices[0], "message") if choices else None
        text = str(field(message, "content", "") or "") if message is not None else ""
        usage = _usage(field(resp, "usage"))
        tool_calls = [
            {
                "id": field(tc, "id"),
                "name": field(field(tc, "function"), "name"),
                "arguments": field(field(tc, "function"), "arguments"),
            }
            for tc in (field(message, "tool_calls", None) or [] if message is not None else [])
        ]
    if is_glimmer(route):
        text = clean_glimmer_text(text)
    if not text and not tool_calls:
        raise ProviderError(
            f"{route.provider}: empty reply (reasoning may have used the whole token budget)",
            provider=route.provider,
        )
    return LiveText(text=text, usage=usage, model=model, tool_calls=tool_calls)


def tool_args(call: dict[str, Any]) -> Any:
    """Decode a tool call's JSON arguments (models sometimes send a dict already)."""
    args = call.get("arguments")
    return json.loads(args) if isinstance(args, str) and args else args
