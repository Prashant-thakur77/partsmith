"""Byte-level helpers: MIME sniffing, data URLs, image size, WAV duration, run-length mask encoding."""

from __future__ import annotations

import base64
import hashlib
import io
import shutil
import struct
import subprocess
import wave
from typing import Any

import numpy as np
from numpy.typing import NDArray

BoolMask = NDArray[np.bool_]
_FFMPEG_WAV_ARGS = ("-ac", "1", "-ar", "16000", "-sample_fmt", "s16", "-f", "wav", "pipe:1")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sniff_image_mime(data: bytes) -> str:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    raise ValueError("unsupported image bytes (expected PNG, JPEG, WebP or GIF)")


def data_url(data: bytes, mime: str | None = None) -> str:
    return f"data:{mime or sniff_image_mime(data)};base64,{base64.b64encode(data).decode('ascii')}"


def image_size(data: bytes) -> tuple[int, int]:
    """(width, height) without decoding pixels."""
    from PIL import Image

    with Image.open(io.BytesIO(data)) as im:
        w, h = im.size
    return int(w), int(h)


def decode_image_rgb(data: bytes) -> NDArray[np.uint8]:
    from PIL import Image

    with Image.open(io.BytesIO(data)) as im:
        return np.asarray(im.convert("RGB"), dtype=np.uint8)


def encode_png(rgb: NDArray[Any]) -> bytes:
    from PIL import Image

    buf = io.BytesIO()
    Image.fromarray(np.ascontiguousarray(rgb)).save(buf, format="PNG")
    return buf.getvalue()


def fit_image(data: bytes, max_side: int) -> bytes:
    """Downscale so the longest side is at most `max_side` (PNG out); returns the input unchanged when it fits."""
    from PIL import Image

    with Image.open(io.BytesIO(data)) as im:
        if max(im.size) <= max_side:
            return data
        scale = max_side / max(im.size)
        small = im.convert("RGB").resize(
            (max(1, round(im.width * scale)), max(1, round(im.height * scale))), Image.Resampling.LANCZOS
        )
    buf = io.BytesIO()
    small.save(buf, format="PNG")
    return buf.getvalue()


def is_wav(data: bytes) -> bool:
    return data[:4] == b"RIFF" and data[8:12] == b"WAVE"


def wav_duration_ms(data: bytes) -> int | None:
    try:
        with wave.open(io.BytesIO(data)) as w:
            frames, rate = w.getnframes(), w.getframerate()
    except (wave.Error, EOFError, struct.error):
        return None
    return round(frames * 1000 / rate) if rate else None


def silent_wav(seconds: float = 1.0, rate: int = 16_000) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x00\x00" * int(rate * seconds))
    return buf.getvalue()


def to_wav_16k(data: bytes, mime: str) -> bytes:
    """Return WAV bytes ready for the transcription endpoint (mono PCM 16 kHz). Converts with ffmpeg if needed."""
    if is_wav(data):
        return data
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise ValueError(f"audio is {mime}; the transcription endpoint needs WAV and ffmpeg is not installed")
    proc = subprocess.run(
        [ffmpeg, "-hide_banner", "-loglevel", "error", "-i", "pipe:0", *_FFMPEG_WAV_ARGS],
        input=data,
        capture_output=True,
        timeout=60,
        check=False,
    )
    if proc.returncode != 0 or not is_wav(proc.stdout):
        raise ValueError(f"ffmpeg could not convert {mime} audio to WAV: {proc.stderr.decode(errors='replace')[:200]}")
    return proc.stdout


def rle_encode(mask: BoolMask) -> dict[str, Any]:
    """Uncompressed row-major run lengths, starting with a run of False: `{"size": [h, w], "counts": [...]}`."""
    flat = np.ascontiguousarray(mask, dtype=bool).ravel()
    h, w = int(mask.shape[0]), int(mask.shape[1])
    if flat.size == 0:
        return {"size": [h, w], "counts": []}
    change = np.flatnonzero(flat[1:] != flat[:-1]) + 1
    bounds = np.concatenate(([0], change, [flat.size]))
    counts = np.diff(bounds).tolist()
    if flat[0]:
        counts = [0, *counts]
    return {"size": [h, w], "counts": [int(c) for c in counts]}


def rle_decode(rle: dict[str, Any]) -> BoolMask:
    h, w = (int(v) for v in rle["size"])
    counts = np.asarray(rle["counts"], dtype=np.int64)
    if int(counts.sum()) != h * w:
        raise ValueError(f"RLE counts sum to {int(counts.sum())}, expected {h * w}")
    values = (np.arange(counts.size) % 2).astype(bool)
    return np.repeat(values, counts).reshape(h, w)
