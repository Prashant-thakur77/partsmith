"""Realtime speech: Muse Voice Transcribe over WebSocket, ENDPOINTING mode, so the user can talk over the agent loop.

Protocol (`wss://api.meta.ai/v1/asr/realtime`): the key travels inside the first JSON frame
(`{"authorization": {"accessToken": "Bearer <key>"}, ...}`) because browsers cannot set WebSocket headers; the server
answers `{"sessionId"}`; then raw PCM s16le mono 16 kHz goes up as binary frames paced at real time, and
`{"type": "endStream"}` closes the upload. Events: `speechStart`, `transcript{transcript, final}` (cumulative
partials), `speechEnd`, `speechComplete{transcript}` (the final text of one turn), `error`.

If the socket cannot be opened (or drops before any text), the audio already received is sent to the file
endpoint instead (`providers.transcribe`) and one `final` event is yielded — the file endpoint stays the fallback.
The mock turns a provided text (or the registered `transcribe_stream` mock) into the same event sequence.
"""

from __future__ import annotations

import contextlib
import io
import json
import queue
import threading
import time
import wave
from collections.abc import Callable, Iterable, Iterator, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from . import clients, mocks, pricing
from .base import ModelRequest, ProviderError, Usage
from .config import log, redact, warn_once
from .routing import resolve
from .telemetry import record_call

STREAM_PATH = "/asr/realtime"
SAMPLE_RATE = 16_000
BYTES_PER_SECOND = SAMPLE_RATE * 2  # s16le mono
sleep: Callable[[float], None] = time.sleep  # tests replace this

VoiceKind = Literal["speech_start", "speech_end", "partial", "final"]


@dataclass
class VoiceEvent:
    kind: VoiceKind
    text: str = ""
    turn_id: str | None = None
    mode: str = "live"


def _strip_wav_header(chunk: bytes) -> bytes:
    if chunk[:4] != b"RIFF" or chunk[8:12] != b"WAVE":
        return chunk
    with wave.open(io.BytesIO(chunk)) as w:
        if w.getframerate() != SAMPLE_RATE or w.getnchannels() != 1 or w.getsampwidth() != 2:
            raise ValueError("realtime voice needs 16 kHz mono 16-bit PCM")
        frames: bytes = w.readframes(w.getnframes())
        return frames


def handshake(key: str, model: str, keywords: Sequence[str], language_bias: Sequence[str] | None) -> dict[str, Any]:
    """First frame. Unknown fields are silently ignored by the server, so only documented names are sent."""
    frame: dict[str, Any] = {
        "authorization": {"accessToken": key if key.startswith("Bearer ") else f"Bearer {key}"},
        "model": model,
        "audioEncoding": "PCM_16KHZ",
        "mode": "ENDPOINTING",
        "partialMode": "CUMULATIVE",
        "emitAudioProgress": False,
    }
    if keywords:
        frame["keywords"] = list(keywords)
    if language_bias:
        frame["languageBias"] = list(language_bias)
    return frame


def _to_event(frame: dict[str, Any]) -> VoiceEvent | None:
    kind = frame.get("type")
    turn = frame.get("turnId")
    turn_id = str(turn) if turn is not None else None
    if kind == "speechStart":
        return VoiceEvent("speech_start", turn_id=turn_id)
    if kind == "speechEnd":
        return VoiceEvent("speech_end", turn_id=turn_id)
    if kind == "speechComplete":
        return VoiceEvent("final", str(frame.get("transcript", "")).strip(), turn_id)
    if kind == "transcript":
        text = str(frame.get("transcript", "")).strip()
        return VoiceEvent("final" if frame.get("final") else "partial", text, turn_id)
    if kind == "error":
        raise ProviderError(redact(f"Muse Voice realtime error: {frame.get('message', frame)}"), provider="meta")
    return None


def _wav(pcm: bytes) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(pcm)
    return buf.getvalue()


def _mock_events(text: str) -> Iterator[VoiceEvent]:
    for t, sentence in enumerate(s.strip() for s in text.replace("?", ".").replace("|", ".").split(".")):
        if not sentence:
            continue
        turn = f"mock-{t + 1}"
        yield VoiceEvent("speech_start", turn_id=turn, mode="mock")
        words = sentence.split()
        for i in range(1, len(words)):
            yield VoiceEvent("partial", " ".join(words[:i]), turn, mode="mock")
        yield VoiceEvent("final", sentence, turn, mode="mock")
        yield VoiceEvent("speech_end", turn_id=turn, mode="mock")


def transcribe_stream(
    chunks: Iterable[bytes],
    *,
    keywords: Sequence[str] = (),
    language_bias: Sequence[str] | None = ("English", "Hindi"),
    pace: bool = True,
    mock_text: str | None = None,
) -> Iterator[VoiceEvent]:
    """Stream 16 kHz mono PCM chunks (a leading WAV header is accepted) and yield voice events as they arrive.

    `keywords` bias recognition (use the part's knob labels); `language_bias` defaults to English + Hindi.
    `pace=False` for microphone input that is already real time. `mock_text` is what the mock "hears".
    """
    res = resolve("transcribe_stream")
    t0 = time.monotonic()
    if res.mode != "live":  # replay has no per-chunk recordings: realtime runs as the labelled mock
        pcm = b"".join(_strip_wav_header(c) for c in chunks)
        handler = mocks.handler_for("transcribe_stream")
        text = mock_text
        if text is None and handler is not None:
            text = str(handler(ModelRequest(messages=[], mock_context={"audio_bytes": len(pcm)})))
        record_call(
            stage="transcribe_stream", provider="mock", model="muse-voice-transcribe-1.0", mode="mock", usage=Usage(),
            ms=round((time.monotonic() - t0) * 1000), usd=0.0,
        )  # fmt: skip
        yield from _mock_events(text if text is not None else mocks.MOCK_TRANSCRIPT)
        return
    route = res.routes[0]
    key, base = route.endpoint.key() or "", route.endpoint.base_url() or ""
    url = base.replace("https://", "wss://").replace("http://", "ws://") + STREAM_PATH
    sent: list[bytes] = []
    got_text = False
    source = iter(chunks)
    try:
        ws = clients.ws_connect(url, max_size=None, open_timeout=15)
    except Exception as exc:
        warn_once(f"realtime voice unavailable ({type(exc).__name__}); using the file endpoint")
        yield from _fallback(sent, source, list(language_bias or []))
        return
    errors: queue.Queue[BaseException] = queue.Queue()
    try:
        ws.send(json.dumps(handshake(key, route.model, keywords, language_bias)))
        ack = json.loads(ws.recv(timeout=15))
        if ack.get("type") == "error" or "sessionId" not in ack:
            raise ProviderError(redact(f"Muse Voice handshake rejected: {ack.get('message', ack)}"), provider="meta")

        def upload() -> None:
            try:
                started = time.monotonic()
                total = 0
                for chunk in source:
                    pcm = _strip_wav_header(chunk)
                    if not pcm:
                        continue
                    if pace and total:
                        delay = started + total / BYTES_PER_SECOND - time.monotonic()
                        if delay > 0:
                            sleep(delay)
                    ws.send(pcm)
                    sent.append(pcm)
                    total += len(pcm)
                ws.send(json.dumps({"type": "endStream"}))
            except BaseException as exc:  # surfaced by the reader below
                errors.put(exc)

        sender = threading.Thread(target=upload, name="voice-upload", daemon=True)
        sender.start()
        while True:
            try:
                raw = ws.recv(timeout=30)
            except TimeoutError:
                if sender.is_alive():
                    continue  # long silence while still uploading: no events yet
                raise ProviderError(
                    "Muse Voice sent nothing for 30 s after the upload ended", provider="meta"
                ) from None
            except Exception as exc:  # closed: normal end after endStream, or a failure
                if errors.empty() and not sender.is_alive():
                    break
                raise ProviderError(redact(f"Muse Voice stream closed: {exc}"), provider="meta") from exc
            if isinstance(raw, bytes):
                continue
            event = _to_event(json.loads(raw))
            if event is None:
                continue
            got_text = got_text or bool(event.text)
            yield event
        sender.join(timeout=5)
        if not errors.empty():
            raise errors.get()
    except ProviderError as exc:
        if got_text:
            raise
        log.warning("realtime voice failed before any text (%s); using the file endpoint", exc)
        yield from _fallback(sent, source, list(language_bias or []))
        return
    finally:
        with contextlib.suppress(Exception):
            ws.close()
    seconds_ms = round(sum(len(c) for c in sent) * 1000 / BYTES_PER_SECOND)
    record_call(
        stage="transcribe_stream", provider=route.provider, model=route.model, mode="live", usage=Usage(),
        ms=round((time.monotonic() - t0) * 1000), usd=pricing.voice_cost_usd(route.provider, seconds_ms),
    )  # fmt: skip


def _fallback(sent: list[bytes], rest: Iterator[bytes], bias: list[str]) -> Iterator[VoiceEvent]:
    from .core import transcribe

    pcm = b"".join(sent) + b"".join(_strip_wav_header(c) for c in rest)
    hint = "-".join(b[:2].lower() for b in bias) if bias else None
    t = transcribe(_wav(pcm), "audio/wav", hint)
    yield VoiceEvent("final", t.text, None, mode=t.mode)
