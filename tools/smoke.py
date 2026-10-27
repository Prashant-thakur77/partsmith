"""`make smoke`: one tiny live call per provider/model.

    ✅  live call succeeded
    ⚠️  key / URL missing → that provider is skipped and its stages run as deterministic mocks (env var named)
    ❌  live call failed (short reason)

Exit code 0 when there are only ✅ / ⚠️ rows, 1 if any live call failed. Calls cost a fraction of a cent
(Muse Image $0.01 is the largest). Self-hosted Modal endpoints may need a cold start; `--cold-start-s` bounds the wait.
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Literal

import numpy as np

from services.agent import providers
from services.agent.providers import ModelRequest, chat, media, meta, routing, sam_open
from services.agent.providers.config import redact
from services.agent.providers.routing import Route

Status = Literal["ok", "missing", "fail"]
ICONS: dict[Status, str] = {"ok": "✅", "missing": "⚠️ ", "fail": "❌"}
HELLO = ModelRequest(messages=[{"role": "user", "content": "Reply with the single word OK."}], max_tokens=512)


@dataclass(frozen=True)
class Check:
    name: str
    route: Route
    run: Callable[[Route, float], str]
    fallback_only: bool = False  # missing key only matters if the primary is missing too


@dataclass
class Result:
    name: str
    status: Status
    detail: str
    ms: int = 0


def _square_png(rgb: tuple[int, int, int] = (20, 20, 20)) -> bytes:
    img = np.full((128, 128, 3), 235, dtype=np.uint8)
    img[32:96, 32:96] = rgb
    return media.encode_png(img)


def _text(route: Route, timeout_s: float, effort: str = "minimal") -> str:
    req = ModelRequest(messages=HELLO.messages, max_tokens=HELLO.max_tokens, reasoning_effort=effort)
    if route.protocol == "responses":
        out = meta.responses_complete(route, req, None, timeout_s)
    else:
        out = chat.chat_complete(route, req, None, timeout_s)
    return f"{out.model}: {out.text.strip()[:24]!r} ({out.usage.tokens_in}+{out.usage.tokens_out} tok)"


def _spark_open(route: Route, timeout_s: float) -> str:
    return _text(route, timeout_s, effort="low")


def _image(route: Route, timeout_s: float) -> str:
    data, mime, _ = meta.image_generate(
        route, "a small grey plastic washer on a white table, product photo", [], timeout_s
    )
    return f"{len(data) // 1024} KiB {mime}"


def _voice_realtime(route: Route, timeout_s: float) -> str:
    """WebSocket handshake + 1 s of silence + endStream; no fallback to the file endpoint here."""
    import json

    from services.agent.providers import clients, realtime

    url = (route.endpoint.base_url() or "").replace("https://", "wss://") + realtime.STREAM_PATH
    ws = clients.ws_connect(url, max_size=None, open_timeout=15)
    try:
        ws.send(json.dumps(realtime.handshake(route.endpoint.key() or "", route.model, [], ["English", "Hindi"])))
        ack = json.loads(ws.recv(timeout=15))
        if "sessionId" not in ack:
            raise RuntimeError(f"handshake rejected: {str(ack)[:100]}")
        ws.send(b"\0\0" * realtime.SAMPLE_RATE)
        ws.send(json.dumps({"type": "endStream"}))
        return f"session {str(ack['sessionId'])[:12]} opened, 1 s streamed"
    finally:
        ws.close()


def _voice(route: Route, timeout_s: float) -> str:
    text, duration = meta.voice_transcribe(route, media.silent_wav(1.0), "audio/wav", None, timeout_s)
    return f"1 s of silence → {text!r} ({duration} ms billed)"


def _sam(route: Route, timeout_s: float) -> str:
    masks = meta.sam_segment(route, _square_png(), "black square", timeout_s)
    return f"{len(masks)} mask(s)" + (f", {int(masks[0][0].sum())} px" if masks else "")


def _baseten_models(route: Route, timeout_s: float) -> str:
    ids = chat.list_model_ids(chat.client_for(route, timeout_s))
    spark = [i for i in ids if "muse-spark-open" in i.lower()]
    chosen = chat.pick_spark_open_id(ids, providers.config.env("SPARK_OPEN_MODEL"))
    return f"{len(ids)} models; Spark Open ids: {', '.join(spark) or 'none'} → using {chosen}"


def _wait_ready(route: Route, cold_start_s: float, probe: Callable[[], object]) -> None:
    """Self-hosted Modal endpoints answer 503 while a replica starts; poll until ready or the budget runs out."""
    deadline = time.monotonic() + cold_start_s
    while True:
        try:
            probe()
            return
        except Exception as exc:
            status = getattr(getattr(exc, "response", None), "status_code", None)
            if status != 503 or time.monotonic() > deadline:
                raise
            time.sleep(5)


def _glimmer(cold_start_s: float) -> Callable[[Route, float], str]:
    def run(route: Route, timeout_s: float) -> str:
        url = chat.base_url(route).removesuffix("/v1")
        with providers.clients.http_client(30) as http:
            _wait_ready(route, cold_start_s, lambda: http.get(f"{url}/health").raise_for_status())
        req = ModelRequest(
            messages=[{"role": "user", "content": "What colour is the square in this image? Answer in one word."}],
            images=[_square_png((200, 30, 30))],
            max_tokens=2048,
            reasoning_effort="low",
        )
        out = chat.chat_complete(route, req, None, timeout_s)
        return f"{out.model}: {out.text.strip()[:24]!r} ({out.usage.tokens_in}+{out.usage.tokens_out} tok, image in)"

    return run


def _sam3_health(cold_start_s: float) -> Callable[[Route, float], str]:
    def run(route: Route, timeout_s: float) -> str:
        holder: dict[str, object] = {}
        _wait_ready(route, cold_start_s, lambda: holder.update(sam_open.health(route, timeout_s)))
        return f"health {holder}"

    return run


def checks(cold_start_s: float = 300.0) -> list[Check]:
    return [
        Check("Meta · muse-spark-1.3", routing.SPARK_13, _text),
        Check("Meta · muse-wonder-1.0", routing.WONDER, _text),
        Check("Meta · muse-image-1.0", routing.MUSE_IMAGE, _image),
        Check("Meta · muse-voice-transcribe-1.0", routing.MUSE_VOICE, _voice),
        Check("Meta · voice realtime (WebSocket)", routing.MUSE_VOICE, _voice_realtime),
        Check("Meta · sam-3.1", routing.SAM_31, _sam),
        Check("Baseten · models.list", routing.SPARK_OPEN_BASETEN, _baseten_models),
        Check("Baseten · Muse Spark Open", routing.SPARK_OPEN_BASETEN, _spark_open),
        Check("Fireworks · Muse Spark Open", routing.SPARK_OPEN_FIREWORKS, _spark_open, fallback_only=True),
        Check("Together · Muse Spark Open", routing.SPARK_OPEN_TOGETHER, _spark_open, fallback_only=True),
        Check("Together · Muse Glimmer 30B", routing.GLIMMER_TOGETHER, _spark_open, fallback_only=True),
        Check("Modal · Muse Glimmer 30B (llama.cpp)", routing.GLIMMER_MODAL, _glimmer(cold_start_s)),
        Check("Modal · SAM 3 open weights /health", routing.SAM_3_OPEN, _sam3_health(cold_start_s)),
    ]


def _short(exc: BaseException) -> str:
    err = providers.retry.classify(exc, "")
    msg = str(err).removeprefix(": ").splitlines()[0] if str(err) else type(exc).__name__
    return redact(msg)[:140]


def run_checks(items: Sequence[Check], timeout_s: float = 90.0) -> list[Result]:
    results: list[Result] = []
    for c in items:
        missing = c.route.endpoint.missing()
        if missing:
            what = " / ".join(missing)
            tail = "fallback only, skipped" if c.fallback_only else "stages using it run as mock"
            results.append(Result(c.name, "missing", f"{what} missing → {tail}"))
            continue
        t0 = time.monotonic()
        try:
            detail = c.run(c.route, timeout_s)
            results.append(Result(c.name, "ok", detail, int((time.monotonic() - t0) * 1000)))
        except Exception as exc:
            results.append(Result(c.name, "fail", _short(exc), int((time.monotonic() - t0) * 1000)))
    return results


def render(results: Sequence[Result]) -> str:
    width = max(len(r.name) for r in results)
    lines = [f"   {'check':<{width}}  {'ms':>6}  detail", "   " + "-" * (width + 40)]
    for r in results:
        ms = str(r.ms) if r.status != "missing" else ""
        lines.append(f"{ICONS[r.status]} {r.name:<{width}}  {ms:>6}  {r.detail}")
    return "\n".join(lines)


def render_status() -> str:
    rows = providers.status()
    width = max(len(r["stage"]) for r in rows)
    lines = ["", f"Stage routing (overall mode: {providers.overall_mode()})"]
    for r in rows:
        where = f"{r['provider']} · {r['model']}"
        lines.append(f"  {r['stage']:<{width}}  {r['mode']:<6}  {where}" + (f"  — {r['note']}" if r["note"] else ""))
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m tools.smoke", description=__doc__.splitlines()[0])
    parser.add_argument("--timeout", type=float, default=90.0, help="seconds per live call")
    parser.add_argument("--cold-start-s", type=float, default=300.0, help="max wait for Modal endpoints to wake up")
    parser.add_argument("--no-status", action="store_true", help="skip the stage routing table")
    args = parser.parse_args(argv)
    logging.getLogger("partsmith.providers").setLevel(logging.ERROR)  # the table already names every missing key
    results = run_checks(checks(args.cold_start_s), args.timeout)
    print(render(results))
    if not args.no_status:
        print(render_status())
    failed = [r for r in results if r.status == "fail"]
    ok = sum(r.status == "ok" for r in results)
    missing = sum(r.status == "missing" for r in results)
    print(f"\n{ok} live ✅ · {missing} missing ⚠️ (mock) · {len(failed)} failed ❌")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
