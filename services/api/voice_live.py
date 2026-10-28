"""Live voice edits over a WebSocket (`/api/v1/jobs/{id}/voice/live`).

The browser streams microphone audio (raw PCM s16le, mono, 16 kHz, binary frames); the server relays it to Muse Voice
Transcribe realtime through `services.agent.providers` (ENDPOINTING mode, keywords = the job's knob labels, language
bias English + Hindi) and sends partial and final transcripts back as JSON. Every final utterance runs the same
voice→knob mapping and guards as `POST /jobs/{id}/edit` (the agent service's `edit`): the model proposes edits, code
clamps them to PARAMS, and the result (with the from→to diff and the re-bake) goes back to the browser.

The API key never leaves the server. Without a key the session is the labelled mock: it "hears" a scripted Hinglish
utterance chosen to fit this job's knobs. Each session is capped in time and bytes; every failure becomes an `error`
message followed by a close, never a hang.

Client → server: binary PCM frames; text `{"type": "stop"}` (end the upload, wait for the last transcripts) or
`{"type": "ping"}`. Server → client (`type`): `ready`, `speech_start`, `partial`, `speech_end`, `final`, `edit`,
`edit_error`, `capped`, `warning`, `error`, `pong`, `closed`.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import queue
import threading
import time
from collections.abc import Callable, Iterator, Sequence
from typing import Any

from fastapi import WebSocket
from partsmith_schemas import LogEvent
from partsmith_schemas.verification import ParamSpec
from starlette.websockets import WebSocketState

from services.agent import providers
from services.agent.providers import realtime
from services.api.common import _job, _service_call, _svc
from services.api.errors import ApiError

log = logging.getLogger("partsmith.api.voice")

MAX_SECONDS = 60.0  # per session, from `ready`
MAX_BYTES = int(MAX_SECONDS * realtime.BYTES_PER_SECOND * 1.1)  # 60 s of audio plus slack for bursty clients
MAX_FRAME_BYTES = 64 * 1024  # one binary frame (2 s of audio)
DRAIN_S = 15.0  # after the upload ends, wait this long for the last transcripts
EDIT_TIMEOUT_S = 90.0  # an edit re-bakes the part
MAX_SESSIONS = 8  # concurrent live sessions per API process
MAX_KEYWORDS = 24
LANGUAGE_BIAS = ("English", "Hindi")
DEFAULT_MOCK_SCRIPT = "hook ko 1 mm mota karo"

# close codes (RFC 6455)
NORMAL, POLICY, UNSUPPORTED, SERVER_ERROR, TRY_LATER = 1000, 1008, 1003, 1011, 1013

_active = 0
_active_lock = threading.Lock()


def cors_origins() -> list[str]:
    """Browser origins allowed to call the API (`PARTSMITH_CORS_ORIGINS`); also the origins a live voice socket
    accepts, since WebSockets are not covered by CORS."""
    raw = os.environ.get("PARTSMITH_CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000")
    return [o.strip() for o in raw.split(",") if o.strip()]


def origin_allowed(origin: str | None) -> bool:
    """No Origin header (a script, curl, the CLI) is allowed; a browser page must be on an allowed origin."""
    if not origin:
        return True
    allowed = cors_origins()
    return "*" in allowed or origin.rstrip("/") in allowed


def knob_keywords(specs: Sequence[ParamSpec]) -> list[str]:
    """Recognition keywords: the job's knob labels (deduplicated, short ones only)."""
    out: list[str] = []
    for s in specs:
        label = " ".join(s.label.split())
        if label and len(label) <= 40 and label.lower() not in {k.lower() for k in out}:
            out.append(label)
    return out[:MAX_KEYWORDS]


def mock_script(specs: Sequence[ParamSpec], values: dict[str, float]) -> str:
    """The utterance the mock "hears": the first of a few Hinglish requests that maps to exactly one knob of this job
    (checked with the deterministic mapper), so the demo moves a real knob on any part. Pure."""
    from services.media.voice import map_utterance

    candidates = [DEFAULT_MOCK_SCRIPT, "hole thoda bada karo"]
    candidates += [f"{s.label.lower()} 1 mm badhao" for s in specs if not s.topology]
    for text in candidates:
        edits, missed, _ = map_utterance(text, specs, values)
        if len(edits) == 1 and not missed:
            return text
    return DEFAULT_MOCK_SCRIPT


def _pcm_frame_error(data: bytes) -> str | None:
    if not data:
        return "empty audio frame"
    if len(data) % 2:
        return "audio frames must be whole 16-bit samples (even byte count)"
    if len(data) > MAX_FRAME_BYTES:
        return f"audio frame over {MAX_FRAME_BYTES} bytes; send ~100 ms frames"
    if data[:4] == b"RIFF":
        return "send raw PCM s16le mono 16 kHz frames, not a WAV file"
    return None


class _Bridge:
    """Runs the blocking provider generator in a thread: audio goes in through `chunks`, voice events (or the
    exception that ended the stream, then None) come out on an asyncio queue."""

    def __init__(self, loop: asyncio.AbstractEventLoop, job: Any, keywords: list[str], mock_text: str) -> None:
        self.loop = loop
        self.job = job
        self.keywords = keywords
        self.mock_text = mock_text
        self.chunks: queue.Queue[bytes | None] = queue.Queue()
        self.events: asyncio.Queue[realtime.VoiceEvent | BaseException | None] = asyncio.Queue()
        self.abandon = threading.Event()
        self.thread = threading.Thread(target=self._run, name="voice-live", daemon=True)

    def _source(self) -> Iterator[bytes]:
        while True:
            chunk = self.chunks.get()
            if chunk is None or self.abandon.is_set():
                return
            yield chunk

    def _put(self, item: realtime.VoiceEvent | BaseException | None) -> None:
        with contextlib.suppress(RuntimeError):  # the loop is gone: nobody is listening any more
            self.loop.call_soon_threadsafe(self.events.put_nowait, item)

    def _run(self) -> None:
        try:
            with providers.job_context(self.job.id, self.job.emit, ctx=getattr(self.job, "ctx", "") or ""):
                stream = providers.transcribe_stream(
                    self._source(), keywords=self.keywords, language_bias=LANGUAGE_BIAS, pace=False,
                    mock_text=self.mock_text,
                )  # fmt: skip
                for event in stream:
                    if self.abandon.is_set():
                        break
                    self._put(event)
        except BaseException as exc:  # handed to the event loop, which reports it to the browser
            self._put(exc)
        finally:
            self._put(None)

    def start(self) -> None:
        self.thread.start()

    def end_upload(self) -> None:
        self.chunks.put(None)

    def stop(self) -> None:
        self.abandon.set()
        self.chunks.put(None)


class _Session:
    def __init__(self, ws: WebSocket, job_id: str) -> None:
        self.ws = ws
        self.job_id = job_id
        self.send_lock = asyncio.Lock()
        self.gone = False
        self.bytes_in = 0
        self.finals = 0
        self.edits = 0
        self.fatal: dict[str, str] | None = None
        self.final_queue: asyncio.Queue[tuple[str, str | None, str] | None] = asyncio.Queue()

    async def send(self, msg: dict[str, Any]) -> None:
        if self.gone:
            return
        async with self.send_lock:
            try:
                await self.ws.send_text(json.dumps(msg))
            except Exception:  # the browser went away mid-send
                self.gone = True

    async def close(self, code: int) -> None:
        if self.ws.client_state == WebSocketState.CONNECTED:
            with contextlib.suppress(Exception):
                await self.ws.close(code=code)

    async def pump(self, bridge: _Bridge) -> None:
        """Provider events → browser; finals also go to the edit worker."""
        while True:
            item = await bridge.events.get()
            if item is None:
                return
            if isinstance(item, BaseException):
                self.fatal = {"code": "provider_error", "message": _message(item)}
                await self.send({"type": "error", **self.fatal})
                continue
            msg: dict[str, Any] = {"type": item.kind, "turn_id": item.turn_id, "mode": item.mode}
            if item.kind in ("partial", "final"):
                msg["text"] = item.text
            await self.send(msg)
            if item.kind == "final" and item.text.strip():
                self.finals += 1
                await self.final_queue.put((item.text.strip(), item.turn_id, item.mode))

    async def edit_worker(self, job: Any) -> None:
        """Each final utterance → the agent service's edit (same mapping and guards as POST /edit), in order."""
        while True:
            item = await self.final_queue.get()
            if item is None:
                return
            text, turn_id, mode = item
            if self.gone:
                continue  # nobody to show the diff to: do not change the job behind the user's back
            with contextlib.suppress(Exception):
                job.emit(LogEvent(job=job.id, msg=f"live voice ({mode}) heard: {text[:200]!r}"))
            try:
                out = await asyncio.wait_for(
                    asyncio.to_thread(_service_call, _svc().edit, self.job_id, text=text[:500], conflict="no_program"),
                    EDIT_TIMEOUT_S,
                )
            except ApiError as exc:
                await self.send({"type": "edit_error", "turn_id": turn_id, "code": exc.code, "message": exc.message})
                continue
            except TimeoutError:
                await self.send({"type": "edit_error", "turn_id": turn_id, "code": "timeout",
                                 "message": f"the edit took over {EDIT_TIMEOUT_S:g} s"})  # fmt: skip
                continue
            except Exception as exc:
                log.exception("live voice edit failed")
                await self.send({"type": "edit_error", "turn_id": turn_id, "code": "internal_error",
                                 "message": _message(exc)})  # fmt: skip
                continue
            result = dict(out)
            result["transcript_mode"] = mode  # heard live (or by the labelled mock), not typed
            self.edits += len(result.get("edits") or [])
            await self.send({"type": "edit", "turn_id": turn_id, "result": result})


def _message(exc: BaseException) -> str:
    text = str(exc) or type(exc).__name__
    return text[:300]


async def _receive(ws: WebSocket, timeout: float, stop: asyncio.Future[Any]) -> dict[str, Any] | None:
    """The next client message, or None when `timeout` passed or `stop` finished first."""
    recv: asyncio.Future[Any] = asyncio.ensure_future(ws.receive())
    done, _ = await asyncio.wait({recv, stop}, timeout=timeout, return_when=asyncio.FIRST_COMPLETED)
    if recv in done:
        return dict(recv.result())
    recv.cancel()
    with contextlib.suppress(BaseException):
        await recv
    return None


async def run(ws: WebSocket, job_id: str, *, knobs: Callable[[str], tuple[list[ParamSpec], dict[str, float]]]) -> None:
    """One live voice session on an accepted-or-not WebSocket. `knobs(job_id)` → (PARAMS, current values)."""
    global _active
    if not origin_allowed(ws.headers.get("origin")):
        await ws.close(code=POLICY)  # before accept: the handshake is refused with 403
        return
    await ws.accept()
    session = _Session(ws, job_id)
    try:
        job = await asyncio.to_thread(_job, job_id)
        specs, values = await asyncio.to_thread(knobs, job_id)
    except ApiError as exc:
        await session.send({"type": "error", "code": exc.code, "message": exc.message})
        await session.close(POLICY)
        return
    with _active_lock:
        busy = _active >= MAX_SESSIONS
        if not busy:
            _active += 1
    if busy:
        await session.send({"type": "error", "code": "busy", "message": "too many live voice sessions; try again"})
        await session.close(TRY_LATER)
        return
    bridge: _Bridge | None = None
    reason = "stopped"
    try:
        mode = realtime.mode()
        keywords = knob_keywords(specs)
        script = mock_script(specs, values)
        bridge = _Bridge(asyncio.get_running_loop(), job, keywords, script)
        ready: dict[str, Any] = {
            "type": "ready", "mode": mode, "model": "muse-voice-transcribe-1.0", "keywords": keywords,
            "language_bias": list(LANGUAGE_BIAS), "sample_rate": realtime.SAMPLE_RATE, "encoding": "pcm_s16le",
            "channels": 1, "max_seconds": MAX_SECONDS, "max_bytes": MAX_BYTES,
        }  # fmt: skip
        if mode == "mock":
            ready["mock_script"] = script
            ready["note"] = "mock: no voice key on the server, so a scripted utterance is replayed as you talk"
        await session.send(ready)
        bridge.start()
        pump = asyncio.ensure_future(session.pump(bridge))
        editor = asyncio.ensure_future(session.edit_worker(job))
        deadline = time.monotonic() + MAX_SECONDS
        while True:
            remaining = deadline - time.monotonic()
            msg = await _receive(ws, max(remaining, 0.0), pump) if remaining > 0 else None
            if msg is None:
                if pump.done():
                    reason = "provider_ended" if session.fatal is None else "error"
                else:
                    reason = "time_cap"
                    await session.send({"type": "capped", "reason": "time", "limit": MAX_SECONDS})
                break
            if msg.get("type") == "websocket.disconnect":
                session.gone = True
                reason = "client_gone"
                break
            data = msg.get("bytes")
            if data is not None:
                problem = _pcm_frame_error(data)
                if problem:
                    session.fatal = {"code": "bad_frame", "message": problem}
                    await session.send({"type": "error", **session.fatal})
                    reason = "error"
                    break
                if session.bytes_in + len(data) > MAX_BYTES:
                    reason = "size_cap"
                    await session.send({"type": "capped", "reason": "size", "limit": MAX_BYTES})
                    break
                session.bytes_in += len(data)
                bridge.chunks.put(data)
                continue
            text = msg.get("text")
            try:
                ctl = json.loads(text) if text else None
            except json.JSONDecodeError:
                ctl = None
            kind = ctl.get("type") if isinstance(ctl, dict) else None
            if kind == "stop":
                break
            if kind == "ping":
                await session.send({"type": "pong"})
                continue
            await session.send({"type": "warning", "code": "bad_frame",
                                "message": 'text frames must be {"type": "stop"} or {"type": "ping"}'})  # fmt: skip
        bad_frame = session.fatal is not None and session.fatal["code"] == "bad_frame"
        if session.gone or bad_frame:
            bridge.stop()
        else:
            bridge.end_upload()
        try:
            await asyncio.wait_for(asyncio.shield(pump), DRAIN_S)
        except TimeoutError:
            bridge.stop()
            await session.send({"type": "warning", "code": "drain_timeout",
                                "message": f"no final transcript within {DRAIN_S:g} s of the end"})  # fmt: skip
            pump.cancel()
        await session.final_queue.put(None)
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(editor, EDIT_TIMEOUT_S + 5)
        if session.fatal is not None:
            reason = "error"
        await session.send({
            "type": "closed", "reason": reason, "seconds": round(session.bytes_in / realtime.BYTES_PER_SECOND, 2),
            "bytes": session.bytes_in, "finals": session.finals, "edits": session.edits,
        })  # fmt: skip
        await session.close(NORMAL if session.fatal is None else UNSUPPORTED if bad_frame else SERVER_ERROR)
    except Exception as exc:  # anything unexpected: tell the browser, then close
        log.exception("live voice session failed")
        await session.send({"type": "error", "code": "internal_error", "message": _message(exc)})
        await session.close(SERVER_ERROR)
    finally:
        if bridge is not None:
            bridge.stop()
        with _active_lock:
            _active -= 1
