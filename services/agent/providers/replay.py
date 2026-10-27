"""Record live calls and serve them back.

`PROVIDER_RECORD=1` writes `$PARTSMITH_HOME/recordings/<request-hash>.json` for every successful live call.
`PROVIDER_MODE=replay` serves those files (falls back to mock with a warning when one is missing).
The hash covers what the model sees (stage, messages, image hashes, schema, sampling settings) and excludes
volatile fields (timeouts, streaming, mock context, provider choice), so a recording made on Baseten replays with
zero keys.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any

from services.common.paths import sub

from . import media
from .base import ModelRequest

RECORDING_VERSION = 1


def recordings_dir() -> Path:
    return sub("recordings")


def _canonical(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def request_hash(kind: str, stage: str, payload: dict[str, Any]) -> str:
    return hashlib.sha256(_canonical({"kind": kind, "stage": stage, **payload}).encode()).hexdigest()


def completion_payload(req: ModelRequest) -> dict[str, Any]:
    return {
        "messages": req.messages,
        "images": [media.sha256(i) for i in req.images],
        "images_at": req.image_message_index(),
        "json_schema": req.json_schema,
        "schema_name": req.schema_name,
        "strict": req.strict,
        "temperature": req.temperature,
        "max_tokens": req.max_tokens,
        "reasoning_effort": req.reasoning_effort,
        "tools": req.tools,
    }


def save(digest: str, record: dict[str, Any]) -> Path:
    path = recordings_dir() / f"{digest}.json"
    body = {"version": RECORDING_VERSION, "hash": digest, "recorded_at": time.time(), **record}
    tmp = path.with_suffix(f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(body, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    tmp.replace(path)
    return path


def load(digest: str) -> dict[str, Any] | None:
    path = recordings_dir() / f"{digest}.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None
