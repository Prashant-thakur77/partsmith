"""Meta Model API adapter (`https://api.meta.ai/v1`, OpenAI SDK with an explicit key).

- Text (Muse Spark 1.3, Muse Wonder): Responses API; strict JSON via `text.format` (never `response_format`);
  `tool_choice` is only ever "auto"; reasoning effort "none" is mapped to "minimal"; streamed by default (long
  non-streamed calls hit 504). Images go inline as data URLs unless the body would exceed 1 MiB, then via Files API.
- SAM 3.1: Responses, one noun phrase per call, streamed, parsed with meta-sam-parser into full-frame masks.
- Muse Image: Responses with reference images wrapped in a role:user message; base64 image in
  `image_generation_call.result`.
- Muse Voice Transcribe: `POST /asr/transcribe` multipart (`request` JSON part + `audio` part).
"""

from __future__ import annotations

import base64
import binascii
import json
from typing import Any

from . import clients, media, sam_parse
from .base import LiveText, ModelRequest, ProviderError, Usage
from .clients import field
from .routing import Route

MAX_BODY_BYTES = 1024 * 1024
INLINE_BODY_LIMIT = MAX_BODY_BYTES - 64 * 1024  # margin for headers/encoding differences
VOICE_MAX_BYTES = 32 * 1024 * 1024
META_EFFORTS = ("minimal", "low", "medium", "high", "xhigh", "max")


def client_for(route: Route, timeout_s: float) -> Any:
    base = route.endpoint.base_url()
    key = route.endpoint.key()
    if not base or not key:
        raise ProviderError(f"{route.endpoint.key_env} missing", provider=route.provider)
    return clients.get_client(base, key, timeout_s)


def normalize_effort(effort: str | None) -> str | None:
    if not effort:
        return None
    e = effort.lower()
    if e == "none":
        return "minimal"  # "none" is a 400 on Spark and Wonder
    return e if e in META_EFFORTS else "medium"


def _upload(client: Any, data: bytes, mime: str, name: str) -> str:
    uploaded = client.files.create(file=(name, data, mime), purpose="user_data")
    file_id = field(uploaded, "id")
    if not isinstance(file_id, str) or not file_id.startswith("file-"):
        raise ProviderError("Files API returned an invalid file id", provider="meta")
    return file_id


def _image_parts(images: list[bytes], file_ids: list[str] | None) -> list[dict[str, Any]]:
    if file_ids is not None:
        return [{"type": "input_image", "file_id": fid} for fid in file_ids]
    return [{"type": "input_image", "image_url": media.data_url(img)} for img in images]


def build_input(req: ModelRequest, file_ids: list[str] | None = None) -> list[dict[str, Any]]:
    """Responses `input` list. System prompts become `developer` messages (standing rules belong there)."""
    at = req.image_message_index()
    items: list[dict[str, Any]] = []
    for i, msg in enumerate(req.messages):
        role = msg.get("role", "user")
        role = "developer" if role == "system" else role
        content = msg.get("content", "")
        if role == "user":
            parts: list[dict[str, Any]] = [{"type": "input_text", "text": content}]
            if i == at:
                parts += _image_parts(req.images, file_ids)
            items.append({"type": "message", "role": "user", "content": parts})
        else:
            items.append({"type": "message", "role": role, "content": content})
    return items


def _body_size(kwargs: dict[str, Any]) -> int:
    return len(json.dumps(kwargs, default=str).encode())


def _usage(response: Any) -> Usage:
    u = field(response, "usage")
    if u is None:
        return Usage()
    in_details = field(u, "input_tokens_details")
    out_details = field(u, "output_tokens_details")
    return Usage(
        tokens_in=int(field(u, "input_tokens", 0) or 0),
        tokens_out=int(field(u, "output_tokens", 0) or 0),
        cached_in=int(field(in_details, "cached_tokens", 0) or 0) if in_details is not None else 0,
        reasoning_tokens=int(field(out_details, "reasoning_tokens", 0) or 0) if out_details is not None else 0,
    )


def _tool_calls(response: Any) -> list[dict[str, Any]]:
    calls = []
    for item in field(response, "output", None) or []:
        if field(item, "type") == "function_call":
            calls.append(
                {"id": field(item, "call_id"), "name": field(item, "name"), "arguments": field(item, "arguments")}
            )
    return calls


def _flat_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Responses wants the flat tool shape; accept the nested Chat shape too."""
    out = []
    for t in tools:
        if t.get("type") == "function" and isinstance(t.get("function"), dict):
            out.append({"type": "function", **t["function"]})
        else:
            out.append(t)
    return out


def responses_kwargs(route: Route, req: ModelRequest, default_effort: str | None) -> dict[str, Any]:
    kwargs: dict[str, Any] = {"model": route.model, "input": build_input(req), "store": False}
    effort = normalize_effort(req.reasoning_effort or default_effort)
    if effort:
        kwargs["reasoning"] = {"effort": effort}
    if req.json_schema is not None:
        kwargs["text"] = {
            "format": {"type": "json_schema", "name": req.schema_name, "schema": req.json_schema, "strict": req.strict}
        }
    if req.temperature is not None:
        kwargs["temperature"] = req.temperature
    if req.max_tokens:
        kwargs["max_output_tokens"] = max(16, int(req.max_tokens))
    if req.tools:
        kwargs["tools"] = _flat_tools(req.tools)
        kwargs["tool_choice"] = "auto"  # the only accepted value
    return kwargs


def responses_complete(route: Route, req: ModelRequest, default_effort: str | None, timeout_s: float) -> LiveText:
    client = client_for(route, timeout_s)
    kwargs = responses_kwargs(route, req, default_effort)
    if req.images and _body_size(kwargs) > INLINE_BODY_LIMIT:
        ids = [_upload(client, img, media.sniff_image_mime(img), f"image-{i}") for i, img in enumerate(req.images)]
        kwargs["input"] = build_input(req, ids)
    stream = True if req.stream is None else req.stream
    if stream:
        events = client.responses.create(**kwargs, stream=True)
        try:
            text, response = sam_parse.stream_text(events)
        finally:
            close = getattr(events, "close", None)
            if callable(close):
                close()
    else:
        response = client.responses.create(**kwargs)
        text = str(field(response, "output_text", "") or "")
    return LiveText(text=text, usage=_usage(response), model=route.model, tool_calls=_tool_calls(response))


def sam_request(route: Route, image_url_or_file: dict[str, str], prompt: str) -> dict[str, Any]:
    return {
        "model": route.model,
        "input": [
            {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": prompt}, {"type": "input_image", **image_url_or_file}],
            }
        ],
        "metadata": {"mask_encoding": "one_bit", "include_confidence": "true"},
        "store": False,
        "stream": True,
    }


def sam_segment(route: Route, image: bytes, prompt: str, timeout_s: float) -> list[tuple[media.BoolMask, float]]:
    client = client_for(route, timeout_s)
    width, height = media.image_size(image)
    ref: dict[str, str] = {"image_url": media.data_url(image)}
    if len(image) * 4 // 3 > INLINE_BODY_LIMIT:
        ref = {"file_id": _upload(client, image, media.sniff_image_mime(image), "segment-image")}
    events = client.responses.create(**sam_request(route, ref, prompt))
    try:
        text, _ = sam_parse.stream_text(events)
    finally:
        close = getattr(events, "close", None)
        if callable(close):
            close()
    return sam_parse.parse_masks(text, width, height)


def image_request(route: Route, prompt: str, refs: list[dict[str, str]]) -> dict[str, Any]:
    payload: Any = prompt
    if refs:
        # Reference images must be wrapped in a role:user message; a bare content list is a 400.
        content: list[dict[str, Any]] = [{"type": "input_text", "text": prompt}]
        content += [{"type": "input_image", **r} for r in refs]
        payload = [{"role": "user", "content": content}]
    return {
        "model": route.model,
        "input": payload,
        "tools": [{"type": "image_generation", "output_format": "png"}],
        "store": False,
    }


def extract_image(response: Any) -> bytes:
    for item in field(response, "output", None) or []:
        if field(item, "type") != "image_generation_call":
            continue
        result = field(item, "result")
        if isinstance(result, str) and result:
            try:
                return base64.b64decode(result, validate=True)
            except (binascii.Error, ValueError) as exc:
                raise ProviderError("Muse Image returned invalid base64", provider="meta") from exc
    raise ProviderError("Muse Image returned no image (filtered or failed)", provider="meta")


def image_generate(route: Route, prompt: str, references: list[bytes], timeout_s: float) -> tuple[bytes, str]:
    client = client_for(route, timeout_s)
    refs = [{"image_url": media.data_url(r)} for r in references]
    kwargs = image_request(route, prompt, refs)
    if references and _body_size(kwargs) > INLINE_BODY_LIMIT:
        refs = [
            {"file_id": _upload(client, r, media.sniff_image_mime(r), f"ref-{i}")} for i, r in enumerate(references)
        ]
        kwargs = image_request(route, prompt, refs)
    data = extract_image(client.responses.create(**kwargs))
    try:
        mime = media.sniff_image_mime(data)
    except ValueError:
        mime = "image/webp"
    return data, mime


_LANGS = {"en": "English", "hi": "Hindi", "english": "English", "hindi": "Hindi"}


def language_bias(hint: str | None) -> list[str] | None:
    """`"hi"`, `"Hindi"`, `"hi-en"`, `"hinglish"` → languageBias list; None lets the model auto-detect."""
    if not hint:
        return None
    h = hint.strip().lower()
    if h in ("hinglish", "hi-en", "en-hi", "hi_en"):
        return ["Hindi", "English"]
    out = []
    for part in h.replace("_", "-").replace(",", "-").split("-"):
        name = _LANGS.get(part, part.capitalize() if len(part) > 2 else None)
        if name and name not in out:
            out.append(name)
    return out or None


def voice_request(route: Route, language_hint: str | None) -> dict[str, Any]:
    request: dict[str, Any] = {"model": route.model, "audioEncoding": "WAV", "mode": "PUSH_TO_TALK"}
    bias = language_bias(language_hint)
    if bias:
        request["languageBias"] = bias
    return request


def voice_transcribe(
    route: Route, audio: bytes, mime: str, language_hint: str | None, timeout_s: float
) -> tuple[str, int | None]:
    """Returns (transcript, audio duration ms)."""
    key = route.endpoint.key()
    base = route.endpoint.base_url()
    if not key or not base:
        raise ProviderError(f"{route.endpoint.key_env} missing", provider=route.provider)
    try:
        wav = media.to_wav_16k(audio, mime)
    except ValueError as exc:
        raise ProviderError(str(exc), provider=route.provider) from exc
    if len(wav) > VOICE_MAX_BYTES:
        raise ProviderError("audio over 32 MB; split it or use the realtime endpoint", provider=route.provider)
    files: dict[str, tuple[str | None, bytes | str, str]] = {
        "request": (None, json.dumps(voice_request(route, language_hint)), "application/json"),
        "audio": ("audio.wav", wav, "audio/wav"),
    }
    headers = {"Authorization": f"Bearer {key}", "Accept": "application/json"}
    with clients.http_client(timeout_s) as http:
        resp = http.post(f"{base}/asr/transcribe", headers=headers, files=files)
    if resp.status_code != 200:
        resp.raise_for_status()
    data = resp.json()
    text = str(data.get("transcript") or "").strip()
    duration = data.get("audioDurationMs")
    return text, int(duration) if isinstance(duration, (int, float)) else media.wav_duration_ms(wav)
