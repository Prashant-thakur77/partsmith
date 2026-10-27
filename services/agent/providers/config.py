"""Provider configuration from the repo `.env` plus the process environment.

Values are read on every call (the `.env` parse is cached by mtime), so editing `.env` or setting env vars in tests
takes effect without a restart. Real environment variables win over `.env`; empty values count as unset.
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from services.common.paths import REPO_ROOT

log = logging.getLogger("partsmith.providers")

Mode = Literal["live", "mock", "replay"]
MODES: tuple[Mode, ...] = ("live", "mock", "replay")

_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_dotenv_cache: dict[str, tuple[float, dict[str, str]]] = {}
_warned: set[str] = set()

# Every env var that can hold a secret. Used to redact error messages.
SECRET_ENVS = (
    "MODEL_API_KEY",
    "META_API_KEY",
    "BASETEN_API_KEY",
    "FIREWORKS_API_KEY",
    "TOGETHER_API_KEY",
    "GLIMMER_API_KEY",
    "SAM3_OPEN_API_KEY",
    "HF_TOKEN",
    "MODAL_TOKEN_SECRET",
)


def parse_dotenv(text: str) -> dict[str, str]:
    """Parse `KEY=value` lines. Supports comments, `export `, single/double quotes and inline ` #` comments."""
    out: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].lstrip()
        key, sep, value = line.partition("=")
        key = key.strip()
        if not sep or not _KEY_RE.match(key):
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] in "\"'" and value[-1] == value[0]:
            quote, value = value[0], value[1:-1]
            if quote == '"':
                value = value.replace("\\n", "\n").replace('\\"', '"')
        else:
            value = value.split(" #", 1)[0].rstrip()
        out[key] = value
    return out


def dotenv_path() -> Path:
    """`PARTSMITH_ENV_FILE` if set (tests point it at a temp file), else `<repo>/.env`."""
    override = os.environ.get("PARTSMITH_ENV_FILE")
    return Path(override) if override else REPO_ROOT / ".env"


def load_dotenv() -> dict[str, str]:
    path = dotenv_path()
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return {}
    cached = _dotenv_cache.get(str(path))
    if cached and cached[0] == mtime:
        return cached[1]
    try:
        values = parse_dotenv(path.read_text(encoding="utf-8"))
    except OSError:
        values = {}
    _dotenv_cache[str(path)] = (mtime, values)
    return values


def env(name: str, default: str | None = None) -> str | None:
    """Environment first, then `.env`. Empty strings are treated as missing."""
    value = os.environ.get(name)
    if not value:
        value = load_dotenv().get(name)
    value = value.strip() if value else value
    return value if value else default


def env_flag(name: str) -> bool:
    return (env(name) or "").lower() in {"1", "true", "yes", "on"}


def warn_once(message: str) -> None:
    """Log a warning the first time a given message is seen in this process."""
    if message not in _warned:
        _warned.add(message)
        log.warning(message)


def reset_warnings() -> None:
    _warned.clear()


@dataclass(frozen=True)
class Settings:
    mode: Mode | None  # PROVIDER_MODE; None = automatic (live where a key exists, mock otherwise)
    record: bool  # PROVIDER_RECORD=1 saves every live request/response for replay
    open_weights_only: bool  # OPEN_WEIGHTS_ONLY=1 routes every stage to open-weight models
    fallback_to_mock: bool  # PROVIDER_FALLBACK_TO_MOCK=1: when every live provider fails, answer with a labelled mock
    max_retries: int  # retries on 429 / 5xx / timeouts per provider
    timeout_s: float  # default request timeout


def settings() -> Settings:
    raw_mode = (env("PROVIDER_MODE") or "").lower()
    mode: Mode | None = None
    if raw_mode in MODES:
        mode = raw_mode
    elif raw_mode and raw_mode != "auto":
        warn_once(f"PROVIDER_MODE={raw_mode!r} is not one of live|mock|replay; using automatic mode")
    try:
        retries = max(0, int(env("PROVIDER_MAX_RETRIES") or "3"))
    except ValueError:
        retries = 3
    try:
        timeout_s = max(1.0, float(env("PROVIDER_TIMEOUT_S") or "180"))
    except ValueError:
        timeout_s = 180.0
    return Settings(
        mode=mode,
        record=env_flag("PROVIDER_RECORD"),
        open_weights_only=env_flag("OPEN_WEIGHTS_ONLY"),
        fallback_to_mock=env_flag("PROVIDER_FALLBACK_TO_MOCK"),
        max_retries=retries,
        timeout_s=timeout_s,
    )


def redact(text: str) -> str:
    """Remove secrets from a message before it is logged, emitted or raised."""
    for name in SECRET_ENVS:
        secret = env(name)
        if secret and len(secret) >= 6:
            text = text.replace(secret, "***")
    text = re.sub(r"(?i)(bearer\s+)[A-Za-z0-9._|\-]+", r"\1***", text)
    return re.sub(r"\bLLM[_|][A-Za-z0-9_|\-]{8,}", "***", text)
