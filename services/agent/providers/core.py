"""Dispatcher: stage → mode (live / mock / replay) → adapter, with fallbacks, retries, pricing, events and recording."""

from __future__ import annotations

import base64
import re
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, replace
from typing import Any

from . import budget, chat, health, meta, mocks, pricing, replay, retry, sam_open
from .base import (
    Completion,
    ImageResult,
    LiveText,
    ModelRequest,
    ProviderError,
    SchemaValidationError,
    Transcript,
    Usage,
)
from .config import Mode, Settings, env, settings, warn_once
from .jsonschema_lite import extract_json, validate
from .media import BoolMask, rle_decode, rle_encode, sha256
from .routing import STAGES, Resolution, Route, resolve, stage_spec
from .telemetry import record_call

COLD_START_RETRIES = 12  # with 5 s base backoff capped at 20 s: about 3.5 minutes of waiting

REPAIR_PROMPT = (
    "Your previous reply did not match the required JSON schema. Problems: {errors}. "
    "Reply again with only the corrected JSON object, no prose and no code fences."
)


@dataclass
class Outcome[T]:
    value: T
    usage: Usage
    model: str
    usd: float


def _retry_opts(route: Route, s: Settings) -> dict[str, Any]:
    """Self-hosted Modal endpoints scale to zero and answer 503 while a replica starts: give them minutes, not seconds."""
    if route.endpoint.key_optional:
        return {"max_retries": max(s.max_retries, COLD_START_RETRIES), "base_delay_s": 5.0}
    return {"max_retries": s.max_retries}


def _ms(t0: float) -> int:
    return round((time.monotonic() - t0) * 1000)


def _mock_label(res: Resolution) -> str:
    return res.display.model if res.display else "none"


def _run_chain[T](
    stage: str, res: Resolution, s: Settings, attempt: Callable[[Route], Outcome[T]]
) -> tuple[Outcome[T], Route, int] | None:
    """Try each live route in order. Emits one event per route tried. Returns None if every route failed."""
    budget.check(stage)
    errors: list[str] = []
    failures: list[ProviderError] = []
    text = res.spec.kind in ("complete", "agent")
    for route in res.routes:
        t0 = time.monotonic()
        try:
            out = attempt(route)
        except Exception as exc:
            if text:
                health.note(route, stage, _ms(t0))
            err = retry.classify(exc, route.provider)
            usage = err.usage
            usd = pricing.token_cost_usd(route.provider, route.model, usage) if usage.tokens_in else 0.0
            record_call(
                stage=stage,
                provider=route.provider,
                model=route.model,
                mode="live",
                usage=usage,
                ms=_ms(t0),
                usd=usd,
                ok=False,
                error=str(err),
            )
            errors.append(str(err))
            failures.append(err)
            continue
        ms = _ms(t0)
        if text:
            health.note(route, stage, ms)
        record_call(
            stage=stage, provider=route.provider, model=out.model, mode="live", usage=out.usage, ms=ms, usd=out.usd
        )
        return out, route, ms
    if s.fallback_to_mock:
        warn_once(f"{stage}: every live provider failed ({' | '.join(errors)}); PROVIDER_FALLBACK_TO_MOCK=1 → mock")
        return None
    if failures and all(isinstance(f, SchemaValidationError) for f in failures):
        raise failures[-1]  # callers can tell "model answered badly" from "provider unreachable"
    raise ProviderError(f"{stage}: every live provider failed: {' | '.join(errors)}", stage=stage)


@dataclass
class Dispatched[T]:
    value: T
    mode: Mode
    provider: str
    model: str
    usd: float
    ms: int
    note: str = ""


def dispatch[T](
    stage: str,
    digest: str,
    *,
    request: dict[str, Any],
    mock: Callable[[], T],
    attempt: Callable[[Route], Outcome[T]],
    encode: Callable[[T], dict[str, Any]],
    decode: Callable[[dict[str, Any]], T],
) -> Dispatched[T]:
    """Shared mode handling for non-text capabilities: replay (recording or mock on a miss) → mock → live chain.

    `encode`/`decode` turn the value into the JSON stored under `$PARTSMITH_HOME/recordings/<digest>.json`.
    Emits one `model_call` event for mock/replay and one per live route tried.
    """
    s = settings()
    res = resolve(stage)

    def run_mock(note: str) -> Dispatched[T]:
        t0 = time.monotonic()
        value = mock()
        ms = _ms(t0)
        model = _mock_label(res)
        record_call(stage=stage, provider="mock", model=model, mode="mock", usage=Usage(), ms=ms, usd=0.0)
        return Dispatched(value, "mock", "mock", model, 0.0, ms, note)

    if res.mode == "replay":
        rec = replay.load(digest)
        if rec is not None:
            t0 = time.monotonic()
            value = decode(rec.get("response", {}))
            provider, model = str(rec.get("provider", "replay")), str(rec.get("model", ""))
            usage = Usage.from_dict(rec.get("usage"))
            record_call(stage=stage, provider=provider, model=model, mode="replay", usage=usage, ms=_ms(t0), usd=0.0)
            return Dispatched(value, "replay", provider, model, 0.0, _ms(t0), f"replayed recording {digest[:12]}")
        warn_once(f"replay: no recording for {stage} ({digest[:12]}) → deterministic mock")
        return run_mock("replay miss → deterministic mock")
    if res.mode == "mock":
        return run_mock(res.note)
    result = _run_chain(stage, res, s, attempt)
    if result is None:
        return run_mock("live providers failed → deterministic mock")
    out, route, ms = result
    if s.record:
        replay.save(
            digest,
            {
                "kind": stage, "stage": stage, "provider": route.provider, "model": out.model, "request": request,
                "response": encode(out.value), "usage": out.usage.to_dict(), "usd": out.usd, "ms": ms,
            },
        )  # fmt: skip
    return Dispatched(out.value, "live", route.provider, out.model, out.usd, ms, res.note)


def retry_opts(route: Route) -> dict[str, Any]:
    """`with_retries` keyword arguments for one live call on `route` (longer for scale-to-zero endpoints)."""
    return {"provider": route.provider, **_retry_opts(route, settings())}


# ---------------------------------------------------------------------------------------------------------------
# Text / JSON completions


def _parse_validate(text: str, schema: dict[str, Any]) -> tuple[Any, list[str]]:
    try:
        parsed = extract_json(text)
    except ValueError as exc:
        return None, [str(exc)]
    return parsed, validate(parsed, schema)


def _live_text(route: Route, stage: str, req: ModelRequest, s: Settings) -> Outcome[tuple[str, Any, list[Any]]]:
    spec = stage_spec(stage)
    timeout = req.timeout_s or s.timeout_s

    def call(r: ModelRequest) -> LiveText:
        if route.protocol == "responses":
            return retry.with_retries(
                lambda: meta.responses_complete(route, r, spec.default_reasoning, timeout),
                provider=route.provider,
                **_retry_opts(route, s),
            )
        if route.protocol == "chat":
            return retry.with_retries(
                lambda: chat.chat_complete(route, r, spec.default_reasoning, timeout),
                provider=route.provider,
                **_retry_opts(route, s),
            )
        raise ProviderError(f"route {route.provider}/{route.model} cannot serve text", provider=route.provider)

    live = call(req)
    usage = live.usage
    text, parsed = live.text, None
    if req.json_schema is not None:
        parsed, errors = _parse_validate(text, req.json_schema)
        if errors:
            repair = replace(
                req,
                messages=[
                    *req.messages,
                    {"role": "assistant", "content": text},
                    {"role": "user", "content": REPAIR_PROMPT.format(errors="; ".join(errors[:8]))},
                ],
                images_at=req.image_message_index(),
            )
            live = call(repair)
            usage = usage + live.usage
            text = live.text
            parsed, errors = _parse_validate(text, req.json_schema)
            if errors:
                err = SchemaValidationError(
                    f"{route.provider}: reply failed schema after one repair: {'; '.join(errors[:4])}",
                    text=text,
                    errors=errors,
                    provider=route.provider,
                    stage=stage,
                )
                err.usage = usage
                raise err
    usd = pricing.token_cost_usd(route.provider, live.model, usage)
    return Outcome((text, parsed, live.tool_calls), usage, live.model, usd)


def _mock_completion(stage: str, req: ModelRequest, res: Resolution, digest: str, note: str) -> Completion:
    t0 = time.monotonic()
    model = _mock_label(res)
    try:
        text, parsed = mocks.mock_complete(stage, req)
    except Exception as exc:
        record_call(
            stage=stage,
            provider="mock",
            model=model,
            mode="mock",
            usage=Usage(),
            ms=_ms(t0),
            usd=0.0,
            ok=False,
            error=str(exc)[:300],
        )
        raise
    ms = _ms(t0)
    record_call(stage=stage, provider="mock", model=model, mode="mock", usage=Usage(), ms=ms, usd=0.0)
    return Completion(
        text=text,
        json=parsed,
        usage=Usage(),
        ms=ms,
        usd=0.0,
        provider="mock",
        model=model,
        mode="mock",
        stage=stage,
        request_hash=digest,
        note=note,
    )


def complete(stage: str, req: ModelRequest) -> Completion:
    """Run one text/JSON model call for `stage` (see `routing.STAGES`). Never fails for a missing key (mock instead).

    Raises `ProviderError` when every configured live provider fails, `SchemaValidationError` (a ProviderError)
    when the reply cannot be made to match `req.json_schema`.
    """
    spec = stage_spec(stage)
    if spec.kind != "complete":
        raise ValueError(f"stage {stage!r} is a {spec.kind} stage; use providers.{spec.kind}()")
    s = settings()
    res = resolve(stage)
    digest = replay.request_hash("complete", stage, replay.completion_payload(req))
    if res.mode == "replay":
        rec = replay.load(digest)
        if rec is not None:
            t0 = time.monotonic()
            resp = rec.get("response", {})
            usage = Usage.from_dict(rec.get("usage"))
            provider, model = str(rec.get("provider", "replay")), str(rec.get("model", ""))
            ms = _ms(t0)
            record_call(stage=stage, provider=provider, model=model, mode="replay", usage=usage, ms=ms, usd=0.0)
            return Completion(
                text=str(resp.get("text", "")),
                json=resp.get("json"),
                usage=usage,
                ms=ms,
                usd=0.0,
                provider=provider,
                model=model,
                mode="replay",
                stage=stage,
                tool_calls=list(resp.get("tool_calls") or []),
                request_hash=digest,
                note=f"replayed recording {digest[:12]}",
            )
        warn_once(f"replay: no recording for stage {stage!r} ({digest[:12]}) → deterministic mock")
        return _mock_completion(stage, req, res, digest, "replay miss → deterministic mock")
    if res.mode == "mock":
        return _mock_completion(stage, req, res, digest, res.note)
    result = _run_chain(stage, res, s, lambda route: _live_text(route, stage, req, s))
    if result is None:
        return _mock_completion(stage, req, res, digest, "live providers failed → deterministic mock")
    out, route, ms = result
    text, parsed, tool_calls = out.value
    if s.record:
        replay.save(
            digest,
            {
                "kind": "complete",
                "stage": stage,
                "provider": route.provider,
                "model": out.model,
                "request": replay.completion_payload(req),
                "response": {"text": text, "json": parsed, "tool_calls": tool_calls},
                "usage": out.usage.to_dict(),
                "usd": out.usd,
                "ms": ms,
            },
        )
    return Completion(
        text=text,
        json=parsed,
        usage=out.usage,
        ms=ms,
        usd=out.usd,
        provider=route.provider,
        model=out.model,
        mode="live",
        stage=stage,
        tool_calls=tool_calls,
        request_hash=digest,
        note=res.note,
    )


# ---------------------------------------------------------------------------------------------------------------
# Segmentation


def normalize_phrase(prompt: str) -> str:
    phrase = re.sub(r"\s+", " ", prompt).strip()
    if not phrase or "," in phrase or len(phrase) > 80:
        raise ValueError("SAM takes one short noun phrase per call (no commas, at most 80 characters)")
    return phrase


def segment(image_png: bytes, prompt: str) -> list[tuple[BoolMask, float]]:
    """Text-prompted masks for one noun phrase: `[(bool mask HxW in full-frame pixels, score)]`, best first."""
    phrase = normalize_phrase(prompt)
    s = settings()
    res = resolve("segment")
    digest = replay.request_hash("segment", "segment", {"image": sha256(image_png), "prompt": phrase})

    def mock() -> list[tuple[BoolMask, float]]:
        t0 = time.monotonic()
        masks = mocks.mock_segment(image_png, phrase)
        record_call(
            stage="segment", provider="mock", model=_mock_label(res), mode="mock", usage=Usage(), ms=_ms(t0), usd=0.0
        )
        return masks

    if res.mode == "replay":
        rec = replay.load(digest)
        if rec is not None:
            masks = [(rle_decode(m["rle"]), float(m["score"])) for m in rec.get("response", {}).get("masks", [])]
            record_call(
                stage="segment",
                provider=str(rec.get("provider", "replay")),
                model=str(rec.get("model", "")),
                mode="replay",
                usage=Usage(),
                ms=0,
                usd=0.0,
            )
            return masks
        warn_once(f"replay: no recording for segment {phrase!r} ({digest[:12]}) → deterministic mock")
        return mock()
    if res.mode == "mock":
        return mock()

    def attempt(route: Route) -> Outcome[list[tuple[BoolMask, float]]]:
        timeout = s.timeout_s
        if route.protocol == "sam_meta":
            fn: Callable[[], list[tuple[BoolMask, float]]] = lambda: meta.sam_segment(route, image_png, phrase, timeout)  # noqa: E731
        else:
            fn = lambda: sam_open.segment(route, image_png, phrase, timeout)  # noqa: E731
        masks = retry.with_retries(fn, provider=route.provider, **_retry_opts(route, s))
        return Outcome(masks, Usage(), route.model, pricing.segment_cost_usd(route.provider))

    result = _run_chain("segment", res, s, attempt)
    if result is None:
        return mock()
    out, route, ms = result
    if s.record:
        replay.save(
            digest,
            {
                "kind": "segment",
                "stage": "segment",
                "provider": route.provider,
                "model": out.model,
                "request": {"image": sha256(image_png), "prompt": phrase},
                "response": {"masks": [{"rle": rle_encode(m), "score": sc} for m, sc in out.value]},
                "usd": out.usd,
                "ms": ms,
            },
        )
    return out.value


# ---------------------------------------------------------------------------------------------------------------
# Images


def generate_image(
    prompt: str, reference_images: list[bytes] | tuple[bytes, ...] = (), *, editable: bool = False
) -> ImageResult:
    """Muse Image generation with optional reference images. Mock mode returns a labelled placeholder.

    `editable=True` stores the response with Meta (store=True) so `edit_image(result.response_id, ...)` can continue
    it; leave it False for anything private.
    """
    refs = list(reference_images)
    digest = replay.request_hash(
        "image", "image", {"prompt": prompt, "refs": [sha256(r) for r in refs], "editable": editable}
    )

    def attempt(route: Route) -> Outcome[tuple[bytes, str, str]]:
        timeout = max(settings().timeout_s, 300.0)
        value = retry.with_retries(
            lambda: meta.image_generate(route, prompt, refs, timeout, store=editable), **retry_opts(route)
        )
        return Outcome(value, Usage(), route.model, pricing.image_cost_usd(route.provider))

    def mock() -> tuple[bytes, str, str]:
        data, mime = mocks.mock_image(prompt, refs)
        return data, mime, mocks.remember_mock_image(data) if editable else ""

    out = dispatch(
        "image",
        digest,
        request={"prompt": prompt, "refs": [sha256(r) for r in refs], "editable": editable},
        mock=mock,
        attempt=attempt,
        encode=lambda v: {"b64": base64.b64encode(v[0]).decode("ascii"), "mime": v[1], "response_id": v[2]},
        decode=lambda r: (base64.b64decode(r["b64"]), str(r.get("mime", "image/png")), str(r.get("response_id", ""))),
    )
    data, mime, response_id = out.value
    return ImageResult(
        data=data, mime=mime, mode=out.mode, provider=out.provider, model=out.model, usd=out.usd, ms=out.ms,
        note=out.note, response_id=response_id,
    )  # fmt: skip


# ---------------------------------------------------------------------------------------------------------------
# Speech


def transcribe(audio: bytes, mime: str, language_hint: str | None = None) -> Transcript:
    """Muse Voice file transcription. Non-WAV audio is converted with ffmpeg when available."""
    s = settings()
    res = resolve("transcribe")
    digest = replay.request_hash(
        "transcribe", "transcribe", {"audio": sha256(audio), "mime": mime, "language_hint": language_hint}
    )

    def mock(note: str) -> Transcript:
        t0 = time.monotonic()
        text = mocks.mock_transcript(audio, mime, language_hint)
        ms = _ms(t0)
        record_call(
            stage="transcribe", provider="mock", model=_mock_label(res), mode="mock", usage=Usage(), ms=ms, usd=0.0
        )
        return Transcript(
            text=text,
            mode="mock",
            provider="mock",
            model=_mock_label(res),
            ms=ms,
            language_hint=language_hint,
            note=f"MOCK transcript — no speech recognition ran ({note})",
        )

    if res.mode == "replay":
        rec = replay.load(digest)
        if rec is not None:
            resp = rec.get("response", {})
            provider, model = str(rec.get("provider", "replay")), str(rec.get("model", ""))
            record_call(stage="transcribe", provider=provider, model=model, mode="replay", usage=Usage(), ms=0, usd=0.0)
            return Transcript(
                text=str(resp.get("text", "")),
                mode="replay",
                provider=provider,
                model=model,
                duration_ms=resp.get("duration_ms"),
                language_hint=language_hint,
                note=f"replayed recording {digest[:12]}",
            )
        warn_once(f"replay: no recording for transcribe ({digest[:12]}) → deterministic mock")
        return mock("replay miss")
    if res.mode == "mock":
        return mock(res.note)

    def attempt(route: Route) -> Outcome[tuple[str, int | None]]:
        value = retry.with_retries(
            lambda: meta.voice_transcribe(route, audio, mime, language_hint, s.timeout_s),
            provider=route.provider,
            **_retry_opts(route, s),
        )
        return Outcome(value, Usage(), route.model, pricing.voice_cost_usd(route.provider, value[1]))

    result = _run_chain("transcribe", res, s, attempt)
    if result is None:
        return mock("live providers failed")
    out, route, ms = result
    text, duration = out.value
    if s.record:
        replay.save(
            digest,
            {
                "kind": "transcribe",
                "stage": "transcribe",
                "provider": route.provider,
                "model": out.model,
                "request": {"audio": sha256(audio), "mime": mime, "language_hint": language_hint},
                "response": {"text": text, "duration_ms": duration},
                "usd": out.usd,
                "ms": ms,
            },
        )
    return Transcript(
        text=text,
        mode="live",
        provider=route.provider,
        model=out.model,
        duration_ms=duration,
        usd=out.usd,
        ms=ms,
        language_hint=language_hint,
    )


# ---------------------------------------------------------------------------------------------------------------
# Status


def _display_model(route: Route) -> str:
    if route.endpoint.name == "baseten" and not chat.is_glimmer(route):
        return chat.cached_model(route) or env("SPARK_OPEN_MODEL") or route.model
    return route.model


def stage_mode(stage: str) -> Mode:
    """The mode `stage` would run in right now."""
    return resolve(stage).mode


def status() -> list[dict[str, Any]]:
    """One `ProviderStatus` dict per stage (docs/API.md)."""
    out: list[dict[str, Any]] = []
    for name, spec in STAGES.items():
        res = resolve(name)
        route = res.display
        if route is None:
            out.append(
                {
                    "stage": name,
                    "role": spec.role,
                    "provider": "none",
                    "model": "none",
                    "mode": res.mode,
                    "key_env": None,
                    "key_present": False,
                    "open_weights": True,
                    "where": "—",
                    "note": res.note,
                }
            )
            continue
        ep = route.endpoint
        key_env = ep.url_env if ep.key_optional else ep.key_env
        out.append(
            {
                "stage": name,
                "role": spec.role,
                "provider": ep.name,
                "model": _display_model(route),
                "mode": res.mode,
                "key_env": key_env,
                "key_present": ep.ready(),
                "open_weights": ep.open_weights,
                "where": ep.where,
                "note": res.note,
            }
        )
    return out


def overall_mode() -> str:
    """`live`, `mock` or `replay` when every stage agrees, else `mixed`."""
    modes = {resolve(name).mode for name in STAGES}
    return modes.pop() if len(modes) == 1 else "mixed"


def warnings() -> list[str]:
    return [f"{row['stage']}: {row['note']}" for row in status() if row["note"]]


def open_weights_summary(events: Iterable[Any] | None = None) -> dict[str, dict[str, Any]]:
    """Per stage: which model/provider served it, whether that is open weights, and how often (live + replay calls).

    Built from this process's model calls, or from recorded `model_call` events (e.g. every run.jsonl) when given.
    Mock calls are counted separately under `modes` and never as evidence.
    """
    from .routing import ENDPOINTS
    from .telemetry import tally, tally_from_events

    rows = tally() if events is None else tally_from_events(events)
    out: dict[str, dict[str, Any]] = {}
    for r in rows:
        st = out.setdefault(
            r["stage"],
            {"model": "", "provider": "", "open_weights": False, "calls": 0, "tokens": 0, "modes": {}, "routes": []},
        )
        st["modes"][r["mode"]] = st["modes"].get(r["mode"], 0) + r["calls"]
        if r["mode"] == "mock":
            continue
        ep = ENDPOINTS.get(r["provider"])
        st["routes"].append(
            {
                "provider": r["provider"], "model": r["model"], "mode": r["mode"],
                "open_weights": bool(ep and ep.open_weights), "calls": r["calls"],
                "tokens": r["tokens_in"] + r["tokens_out"],
            }
        )  # fmt: skip
        st["calls"] += r["calls"]
        st["tokens"] += r["tokens_in"] + r["tokens_out"]
    for st in out.values():
        if st["routes"]:
            top = max(st["routes"], key=lambda x: x["calls"])
            st["model"], st["provider"], st["open_weights"] = top["model"], top["provider"], top["open_weights"]
    return out
