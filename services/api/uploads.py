"""Upload hygiene: size/type limits, decode validation and lossless removal of GPS metadata.

JPEG pixels are never re-encoded (that would cost measurement accuracy): the EXIF block is rewritten without its GPS
directory and XMP packets (which can repeat the location) are dropped; camera fields such as the focal length stay,
because intrinsics may be estimated from them. PNG and WebP are re-saved as PNG without metadata (lossless).

EXIF orientation: the browser shows a photo rotated by its Orientation tag and sends tap points in that frame, and
every decode (`services/common/images.py`) applies the tag the same way. So the tag must survive upload hygiene: a
JPEG keeps it in the rewritten EXIF block; a PNG/WebP is saved upright (rotation applied, losslessly); and in the rare
case a JPEG's EXIF block has to be dropped whole (unreadable, or too big once rewritten), the pixels are re-encoded
upright (quality 95) so the photo still looks the way the user tapped it.
"""

from __future__ import annotations

import io
import json
from typing import Any

from PIL import Image, ImageOps

from services.api.errors import ApiError
from services.common.images import exif_orientation

MAX_IMAGE_BYTES = 25 * 1024 * 1024
MAX_AUDIO_BYTES = 15 * 1024 * 1024
MAX_PIXELS = 60_000_000
MIN_SIDE_PX = 200
IMAGE_FORMATS = {"JPEG", "PNG", "WEBP"}
GPS_IFD = 0x8825
_XMP = b"http://ns.adobe.com/xap/1.0/\x00"


def _exif_without_gps(segment: bytes) -> bytes | None:
    """APP1 Exif segment (marker + length + payload) with the GPS IFD removed; None drops the segment."""
    payload = segment[4:]
    exif = Image.Exif()
    try:
        exif.load(payload)
    except Exception:  # unreadable EXIF: drop it entirely rather than risk leaking location
        return None
    if GPS_IFD not in exif:
        return segment
    del exif[GPS_IFD]
    exif._ifds.pop(GPS_IFD, None)
    data = exif.tobytes()
    if len(data) + 2 > 0xFFFF:
        return None
    return b"\xff\xe1" + (len(data) + 2).to_bytes(2, "big") + data


def strip_jpeg_gps(data: bytes) -> bytes:
    """Lossless: rewrite APP1/Exif without GPS, drop XMP packets, keep every other byte as is."""
    if data[:2] != b"\xff\xd8":
        return data
    out = bytearray(b"\xff\xd8")
    i = 2
    n = len(data)
    while i + 4 <= n:
        if data[i] != 0xFF:
            break
        marker = data[i + 1]
        if marker == 0xFF:  # fill byte
            i += 1
            continue
        if marker in (0xDA, 0xD9):  # start of scan / end of image: the rest is entropy-coded data
            break
        if 0xD0 <= marker <= 0xD7 or marker == 0x01:
            out += data[i : i + 2]
            i += 2
            continue
        seglen = int.from_bytes(data[i + 2 : i + 4], "big")
        seg = data[i : i + 2 + seglen]
        if marker == 0xE1 and seg[4:10] == b"Exif\x00\x00":
            cleaned = _exif_without_gps(seg)
            if cleaned:
                out += cleaned
        elif marker == 0xE1 and seg[4 : 4 + len(_XMP)] == _XMP:
            pass
        else:
            out += seg
        i += 2 + seglen
    out += data[i:]
    return bytes(out)


def has_gps(data: bytes) -> bool:
    try:
        with Image.open(io.BytesIO(data)) as im:
            return GPS_IFD in im.getexif()
    except Exception:
        return False


def clean_image(data: bytes, field: str = "photo") -> tuple[bytes, str]:
    """Validate an uploaded photo and strip location metadata. Returns (bytes, mime). Raises ApiError (413/415/422)."""
    if not data:
        raise ApiError(422, "empty_upload", f"{field}: the file is empty")
    if len(data) > MAX_IMAGE_BYTES:
        raise ApiError(413, "too_large", f"{field}: {len(data) / 1e6:.1f} MB > {MAX_IMAGE_BYTES / 1e6:.0f} MB limit")
    try:
        with Image.open(io.BytesIO(data)) as im:
            fmt = im.format or ""
            w, h = im.size
            if fmt not in IMAGE_FORMATS:
                raise ApiError(
                    415,
                    "unsupported_media_type",
                    f"{field}: {fmt or 'unknown'} images are not accepted; send JPEG, PNG or WebP",
                )
            if w * h > MAX_PIXELS:
                raise ApiError(413, "too_large", f"{field}: {w}x{h} px is over the {MAX_PIXELS / 1e6:.0f} MP limit")
            if min(w, h) < MIN_SIDE_PX:
                raise ApiError(422, "too_small", f"{field}: {w}x{h} px is too small to measure (min {MIN_SIDE_PX} px)")
            im.load()  # full decode: truncated or corrupt files fail here
    except ApiError:
        raise
    except Exception as exc:
        raise ApiError(
            422, "bad_image", f"{field}: the file does not decode as an image ({type(exc).__name__})"
        ) from exc
    if fmt == "JPEG":
        cleaned = strip_jpeg_gps(data)
        if exif_orientation(cleaned) != exif_orientation(data):  # the EXIF block had to go: keep what the user saw
            cleaned = _upright_jpeg(data)
        return cleaned, "image/jpeg"
    with Image.open(io.BytesIO(data)) as raw:
        upright = ImageOps.exif_transpose(raw)
        buf = io.BytesIO()
        upright.convert("RGBA" if upright.mode in ("RGBA", "LA", "P") else "RGB").save(buf, format="PNG")
    return buf.getvalue(), "image/png"


def _upright_jpeg(data: bytes) -> bytes:
    """Re-encode with the EXIF rotation applied and no metadata (only when the EXIF block cannot be kept)."""
    with Image.open(io.BytesIO(data)) as raw:
        im = ImageOps.exif_transpose(raw).convert("RGB")
        buf = io.BytesIO()
        im.save(buf, format="JPEG", quality=95)
    return buf.getvalue()


AUDIO_TYPES = {
    "audio/wav",
    "audio/x-wav",
    "audio/wave",
    "audio/webm",
    "audio/ogg",
    "audio/mpeg",
    "audio/mp4",
    "audio/m4a",
    "audio/x-m4a",
    "audio/aac",
    "audio/flac",
    "video/webm",
}


def check_audio(data: bytes, mime: str | None, field: str = "audio") -> str:
    if not data:
        raise ApiError(422, "empty_upload", f"{field}: the file is empty")
    if len(data) > MAX_AUDIO_BYTES:
        raise ApiError(413, "too_large", f"{field}: {len(data) / 1e6:.1f} MB > {MAX_AUDIO_BYTES / 1e6:.0f} MB limit")
    m = (mime or "audio/wav").split(";")[0].strip().lower()
    if m not in AUDIO_TYPES:
        raise ApiError(415, "unsupported_media_type", f"{field}: {m} is not an accepted audio type")
    return m


MAX_VIDEO_BYTES = 60 * 1024 * 1024
MAX_POINTS = 32
POINT_KINDS = ("hole", "slot", "tab", "broken_edge", "exclude")  # exclude: a negative point (finger, glare, clutter)


def check_video(data: bytes, field: str = "orbit") -> str:
    """A short walk-around clip: MP4/MOV (ISO-BMFF `ftyp`) or WebM, ≤ 60 MB. Returns the MIME type."""
    if not data:
        raise ApiError(422, "empty_upload", f"{field}: the file is empty")
    if len(data) > MAX_VIDEO_BYTES:
        raise ApiError(413, "too_large", f"{field}: {len(data) / 1e6:.1f} MB > {MAX_VIDEO_BYTES / 1e6:.0f} MB limit")
    if data[4:8] == b"ftyp":
        return "video/quicktime" if data[8:10] == b"qt" else "video/mp4"
    if data[:4] == b"\x1aE\xdf\xa3":
        return "video/webm"
    raise ApiError(415, "unsupported_media_type", f"{field}: use an MP4, MOV or WebM clip")


def parse_points(raw: str | None) -> dict[str, list[dict[str, Any]]] | None:
    """User taps on features: JSON {"top": [{"x": px, "y": px, "kind"?: hole|slot|tab|broken_edge|exclude,
    "id"?: str}]} in top-photo pixels (`exclude` marks something that is not the part: a negative point for every
    point prompt). Returns None when absent; malformed input is a 422 with the reason."""
    if raw is None or not raw.strip():
        return None
    try:
        data = json.loads(raw)
    except ValueError as exc:
        raise ApiError(422, "invalid_points", f"points: not JSON ({exc})") from exc
    if not isinstance(data, dict) or set(data) - {"top"}:
        raise ApiError(422, "invalid_points", 'points: expected {"top": [{"x", "y", "kind"?, "id"?}]}')
    pts = data.get("top") or []
    if not isinstance(pts, list) or len(pts) > MAX_POINTS:
        raise ApiError(422, "invalid_points", f"points.top: a list of at most {MAX_POINTS} points")
    out: list[dict[str, Any]] = []
    for i, p in enumerate(pts):
        if not isinstance(p, dict):
            raise ApiError(422, "invalid_points", f"points.top[{i}]: expected an object")
        try:
            x, y = float(p["x"]), float(p["y"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ApiError(422, "invalid_points", f"points.top[{i}]: x and y (photo pixels) are required") from exc
        if not (0 <= x < 20000 and 0 <= y < 20000):
            raise ApiError(422, "invalid_points", f"points.top[{i}]: pixel coordinates out of range")
        kind = str(p.get("kind", "hole"))
        if kind not in POINT_KINDS:
            raise ApiError(422, "invalid_points", f"points.top[{i}]: kind must be one of {', '.join(POINT_KINDS)}")
        item: dict[str, Any] = {"x": x, "y": y, "kind": kind}
        if p.get("id"):
            item["id"] = str(p["id"])[:40]
        out.append(item)
    return {"top": out} if out else None
