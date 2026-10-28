"""Narrated walk-around: Muse Spark watches and hears the clip and points at the features the user talks about.

Live: Responses API on `muse-spark-1.3`; the MP4 clip is uploaded with the Files API (`purpose="user_data"`) and sent
as an `input_file` next to the instructions; a separate voice note is transcribed first (Muse Voice) and its text is
added to the prompt. Strict JSON through `text.format` (json_schema): the part's function, the mating feature, the
break, and per feature a name, a kind, a time in the clip and a pixel in that frame. The schema has no field for a
size: the narration steers (where to look, what the part does), and code measures. Points are checked by code
(`services/metrology/narration.py`) before anything uses them.

Mock: deterministic and labelled (`MOCK — no model watched the clip`), built only from the clip's own metadata (size,
duration) and the user's typed intent: the function and break come from the intent's words and the one point is the
centre of the middle frame. It never reads ground truth.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from . import media, meta, mocks, pricing, replay, retry, sam_parse
from .base import ModelRequest, ProviderError
from .config import Mode, settings
from .core import Outcome, dispatch, retry_opts
from .jsonschema_lite import extract_json, validate
from .routing import Route

MOCK_NOTE = "MOCK — no model watched the clip"
KINDS = ("hole", "slot", "tab", "broken_edge")
MAX_POINTS = 12

NARRATION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["function", "mating_feature", "break_description", "features", "notes"],
    "properties": {
        "function": {"type": "string"},
        "mating_feature": {"type": "string"},
        "break_description": {"type": "string"},
        "features": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["name", "kind", "t_s", "x_px", "y_px", "said"],
                "properties": {
                    "name": {"type": "string"},
                    "kind": {"type": "string", "enum": list(KINDS)},
                    "t_s": {"type": "number"},
                    "x_px": {"type": "number"},
                    "y_px": {"type": "number"},
                    "said": {"type": "string"},
                },
            },
        },
        "notes": {"type": "string"},
    },
}

INSTRUCTIONS = """You watch a short phone clip that walks around a broken plastic part lying on a printed mat, and you
listen to what the person says (and read their voice note, if one is given). Return JSON only:
- function: what the part does, in the person's words (one sentence);
- mating_feature: the feature that fits the other part (a rail, a pin, a clip), or "" if not mentioned;
- break_description: what broke and where, or "" if nothing is said about a break;
- features: for each feature the person shows or names (holes, slots, tabs, the broken edge), pick ONE moment in the
  clip where it is clearly visible and give t_s (seconds from the start) and x_px, y_px: the pixel at the feature's
  centre in that frame (frame size given below; origin top-left). "said": the words that named it.
Never estimate a size or a distance: other code measures everything. Leave out anything you cannot see."""


@dataclass
class Narration:
    function: str
    mating_feature: str
    break_description: str
    features: list[dict[str, Any]]  # {"name", "kind", "t_s", "x_px", "y_px", "said"}
    notes: list[str] = field(default_factory=list)
    transcript: str | None = None  # the voice note's transcript, when one was given
    mode: Mode = "mock"
    provider: str = ""
    model: str = ""
    usd: float = 0.0

    @property
    def label(self) -> str:
        return MOCK_NOTE if self.mode == "mock" else f"Muse Spark ({self.mode})"

    def to_dict(self) -> dict[str, Any]:
        return {
            "function": self.function, "mating_feature": self.mating_feature,
            "break_description": self.break_description, "features": self.features, "notes": self.notes,
            "transcript": self.transcript, "mode": self.mode, "provider": self.provider, "model": self.model,
            "usd": self.usd, "label": self.label,
        }  # fmt: skip


def clean(answer: Any, duration_s: float) -> tuple[dict[str, Any], list[str]]:
    """Shape check plus light clean-up (times clamped to the clip); pixel and mask checks happen in the metrology
    code, against the decoded frame."""
    if not isinstance(answer, dict) or validate(answer, NARRATION_SCHEMA):
        return {"function": "", "mating_feature": "", "break_description": "", "features": []}, [
            "narration reply did not match the expected JSON shape"
        ]
    notes: list[str] = []
    feats: list[dict[str, Any]] = []
    for f in answer["features"][:MAX_POINTS]:
        feats.append(
            {
                "name": str(f["name"]).strip()[:80] or f"feature_{len(feats) + 1}",
                "kind": f["kind"],
                "t_s": float(min(max(float(f["t_s"]), 0.0), max(duration_s, 0.0))),
                "x_px": float(f["x_px"]),
                "y_px": float(f["y_px"]),
                "said": str(f["said"]).strip()[:200],
            }
        )
    if len(answer["features"]) > MAX_POINTS:
        notes.append(f"only the first {MAX_POINTS} narrated features are used")
    out: dict[str, Any] = {k: str(answer[k]).strip()[:300] for k in ("function", "mating_feature", "break_description")}
    out["features"] = feats
    if answer.get("notes"):
        notes.append(f"model note: {str(answer['notes'])[:300]}")
    return out, notes


def _prompt(width: int, height: int, duration_s: float, transcript: str | None) -> str:
    text = f"Frame size: {width} x {height} px. Clip length: {duration_s:.1f} s."
    if transcript:
        text += f"\nThe person's voice note (transcribed): {transcript}"
    return text


def _live(
    route: Route, video: bytes, mime: str, width: int, height: int, duration_s: float, transcript: str | None
) -> Outcome[dict[str, Any]]:
    if mime.split(";")[0].strip().lower() != "video/mp4":
        raise ProviderError("video understanding takes MP4 only; record the walk-around as MP4", provider="meta")
    timeout = max(settings().timeout_s, 300.0)
    client = meta.client_for(route, timeout)
    file_id = meta.upload(client, video, "video/mp4", "walkaround.mp4")
    kwargs: dict[str, Any] = {
        "model": route.model,
        "input": [
            {"type": "message", "role": "developer", "content": INSTRUCTIONS},
            {
                "type": "message",
                "role": "user",
                "content": [
                    {"type": "input_text", "text": _prompt(width, height, duration_s, transcript)},
                    {"type": "input_file", "file_id": file_id},
                ],
            },
        ],
        "text": {"format": {"type": "json_schema", "name": "narration", "schema": NARRATION_SCHEMA, "strict": True}},
        "reasoning": {"effort": "low"},
        "store": False,
    }

    def call() -> tuple[str, Any]:
        events = client.responses.create(**kwargs, stream=True)
        try:
            return sam_parse.stream_text(events)
        finally:
            close = getattr(events, "close", None)
            if callable(close):
                close()

    text, final = retry.with_retries(call, **retry_opts(route))
    if final is None:
        raise ProviderError("narration stream ended without a completed response", provider=route.provider)
    try:
        answer = extract_json(text)
    except ValueError:
        answer = None
    out, notes = clean(answer, duration_s)
    out["notes"] = notes
    usage = meta.usage_of(final)
    return Outcome(out, usage, route.model, round(pricing.token_cost_usd(route.provider, route.model, usage), 8))


_FUNCTION_RE = re.compile(r"(?:replacement for|replace|fix|for) (?:this |the |my |a )?(.+?)[.!]?$", re.IGNORECASE)


def mock_narration(intent: str, width: int, height: int, duration_s: float) -> dict[str, Any]:
    """Deterministic labelled stand-in from the typed intent and the clip's size/length (never ground truth)."""
    words = intent.strip()
    m = _FUNCTION_RE.search(words)
    thing = (m.group(1) if m else words or "the part").strip()
    broken = re.search(r"\b(broke|broken|snapped|cracked|split|missing)\b", words, re.IGNORECASE)
    return {
        "function": f"MOCK: {thing} (from the typed intent; no model watched the clip)",
        "mating_feature": "",
        "break_description": f"MOCK: the intent says it is {broken.group(1).lower()}" if broken else "",
        "features": [
            {
                "name": "part (mock point: centre of the middle frame)",
                "kind": "tab",
                "t_s": round(duration_s / 2, 3),
                "x_px": width / 2.0,
                "y_px": height / 2.0,
                "said": "MOCK",
            }
        ],
        "notes": [MOCK_NOTE],
    }


def narrate_video(
    video: bytes,
    mime: str,
    *,
    width: int,
    height: int,
    duration_s: float,
    intent: str = "",
    voice_note: tuple[bytes, str] | None = None,
    fixture: Mapping[str, Any] | None = None,
) -> Narration:
    """Spark's reading of a narrated walk-around (points + words, never sizes). `voice_note` = (audio, mime)."""
    transcript: str | None = None
    if voice_note is not None:
        from .core import transcribe

        transcript = transcribe(voice_note[0], voice_note[1]).text.strip() or None
    request = {"video_sha": media.sha256(video), "size": [width, height], "duration_s": round(duration_s, 3),
               "transcript": transcript}  # fmt: skip
    digest = replay.request_hash("narrate", "narrate", request)

    def mock() -> dict[str, Any]:
        handler = mocks.handler_for("narrate")
        supplied: Mapping[str, Any] | None = fixture
        if supplied is None and handler is not None:
            supplied = handler(ModelRequest(messages=[{"role": "user", "content": intent}],
                                            mock_context={"width": width, "height": height,
                                                          "duration_s": duration_s, "transcript": transcript}))  # fmt: skip
        raw = dict(supplied) if supplied else mock_narration(intent, width, height, duration_s)
        raw_notes = raw.get("notes", [])
        joined = "; ".join(str(n) for n in raw_notes) if isinstance(raw_notes, list) else str(raw_notes)
        out, notes = clean({**raw, "notes": joined}, duration_s)
        out["notes"] = [MOCK_NOTE] + [n for n in notes if MOCK_NOTE not in n]
        return out

    out = dispatch(
        "narrate",
        digest,
        request=request,
        mock=mock,
        attempt=lambda route: _live(route, video, mime, width, height, duration_s, transcript),
        encode=dict,
        decode=dict,
    )
    v = out.value
    return Narration(
        function=str(v.get("function", "")), mating_feature=str(v.get("mating_feature", "")),
        break_description=str(v.get("break_description", "")), features=list(v.get("features", [])),
        notes=list(v.get("notes", [])), transcript=transcript, mode=out.mode, provider=out.provider,
        model=out.model, usd=out.usd,
    )  # fmt: skip
