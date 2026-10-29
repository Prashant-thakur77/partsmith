"""SAM 3.1 (Meta API) output → full-frame boolean masks.

The API answers in a special-token grammar: `<0f>ID<|box;x1=..;y1=..;x2=..;y2=..;w=W;h=H|><|mask;x=0;y=0;data=H,W,!...|>`.
The mask raster is box-local (height first) and gets pasted into a full-frame mask at the box origin.
`meta_sam_parser` decodes records; its grammar has no confidence field, so `;c=` values requested via
`include_confidence` are read here and stripped before parsing.
The streaming API emits `response.content_part.done` but not `response.output_text.done`; `stream_text` closes each
text lane from whichever of the two arrives.
"""

from __future__ import annotations

import contextlib
import math
import re
from collections.abc import Iterable
from typing import Any

import numpy as np

from .base import ProviderError
from .clients import field
from .media import BoolMask

_RECORD_BOX_RE = re.compile(r"(\d+)<\|box;([^|]*)\|>")
_BOX_KEYS = ("x1", "y1", "x2", "y2", "w", "h")
_FRAME_RE = re.compile(r"^<(\d+)f>")
# Live SAM 3.1 also puts `c=<float>` in the mask token (`<|mask;x=0;y=0;c=0.77;data=…|>`), which the parser rejects.
# Only the part before `data=` is touched: the encoded mask bytes can contain any character.
_MASK_CONF_RE = re.compile(r"(<\|mask;(?:(?!data=)[^|])*?);c=[-+0-9.eE]+")


def _event_dict(event: Any) -> dict[str, Any]:
    if isinstance(event, dict):
        return event
    dump = getattr(event, "model_dump", None)
    if callable(dump):
        out = dump()
        if isinstance(out, dict):
            return out
    return {k: getattr(event, k) for k in dir(event) if not k.startswith("_") and not callable(getattr(event, k))}


def stream_text(events: Iterable[Any]) -> tuple[str, Any]:
    """Collect output text from a Responses event stream. Returns (text, final response object or None)."""
    lanes: dict[tuple[Any, Any, Any], list[str]] = {}
    done: dict[tuple[Any, Any, Any], str] = {}
    order: list[tuple[Any, Any, Any]] = []
    final: Any = None
    for event in events:
        data = _event_dict(event)
        etype = data.get("type")
        lane = (data.get("item_id"), data.get("output_index"), data.get("content_index"))
        if etype == "response.output_text.delta":
            if lane not in lanes:
                lanes[lane] = []
                order.append(lane)
            lanes[lane].append(str(data.get("delta", "")))
        elif etype == "response.output_text.done" and isinstance(data.get("text"), str):
            done.setdefault(lane, data["text"])
            if lane not in order:
                order.append(lane)
        elif etype == "response.content_part.done":
            part = data.get("part")
            if isinstance(part, dict) and part.get("type") == "output_text" and isinstance(part.get("text"), str):
                done.setdefault(lane, part["text"])
                if lane not in order:
                    order.append(lane)
        elif etype == "response.completed":
            final = field(event, "response", data.get("response"))
        elif etype in ("response.failed", "response.incomplete", "error"):
            resp = data.get("response") or {}
            err = (resp.get("error") if isinstance(resp, dict) else None) or data.get("error") or data.get("message")
            raise ProviderError(f"stream ended with {etype}: {str(err)[:300]}", retryable=etype == "error")
    text = "".join(done.get(lane, "".join(lanes.get(lane, []))) for lane in order)
    if not text and final is not None:
        text = str(field(final, "output_text", "") or "")
    return text, final


def split_confidence(text: str) -> tuple[str, dict[tuple[int, str], float]]:
    """Strip `;c=<float>` (and any other unknown box keys) from box tokens, and `;c=<float>` from mask tokens.

    Returns the clean text and {(frame index, object id): confidence}; the frame comes from each line's `<Nf>` header.
    """
    conf: dict[tuple[int, str], float] = {}
    lines = []
    for line in text.split("\n"):
        header = _FRAME_RE.match(line)
        frame = int(header.group(1)) if header else 0

        def repl(m: re.Match[str], frame: int = frame) -> str:
            obj, body = m.group(1), m.group(2)
            params = dict(p.split("=", 1) for p in body.split(";") if "=" in p)
            if "c" in params:
                with contextlib.suppress(ValueError):
                    conf[(frame, obj)] = float(params["c"])
            if not all(k in params for k in _BOX_KEYS):
                return m.group(0)
            return obj + "<|box;" + ";".join(f"{k}={params[k]}" for k in _BOX_KEYS) + "|>"

        lines.append(_MASK_CONF_RE.sub(r"\1", _RECORD_BOX_RE.sub(repl, line)))
    return "\n".join(lines), conf


def _paste(raster: np.ndarray[Any, Any], left: int, top: int, right: int, bottom: int, out: BoolMask) -> None:
    """Nearest-neighbour resize `raster` to the box size and OR it into `out` at (left, top)."""
    height, width = out.shape
    bw, bh = right - left, bottom - top
    if bw <= 0 or bh <= 0:
        return
    rh, rw = raster.shape
    rows = (np.arange(bh) * rh // bh).clip(0, rh - 1)
    cols = (np.arange(bw) * rw // bw).clip(0, rw - 1)
    box = raster[rows][:, cols]
    x0, y0 = max(0, left), max(0, top)
    x1, y1 = min(width, right), min(height, bottom)
    if x1 <= x0 or y1 <= y0:
        return
    out[y0:y1, x0:x1] |= box[y0 - top : y1 - top, x0 - left : x1 - left]


def parse_masks(text: str, width: int, height: int) -> list[tuple[BoolMask, float]]:
    """Decode SAM 3.1 output into `(full-frame bool mask, score)` per object, sorted by score then area.

    Score is the API confidence when present, else 1.0 (the API omits it unless `include_confidence` is honoured).
    """
    try:
        from meta_sam_parser import CompletedOutcome, SegmentationMaskRecord, decode_mask_to_raster
        from meta_sam_parser import image_segmentation_format as fmt
    except ImportError as exc:  # pragma: no cover - dependency is in the `sam` extra
        raise ProviderError("meta-sam-parser is not installed (uv sync --all-extras)") from exc
    if not text.strip():
        return []
    clean, conf = split_confidence(text)
    parser = fmt().create_parser()
    parser.push(clean)
    result = parser.finish(CompletedOutcome()).result
    latest: dict[str, Any] = {}
    for rec in result.records:
        if isinstance(rec, SegmentationMaskRecord):
            latest[rec.object_id] = rec
    if not latest:
        errors = [d.message for d in result.diagnostics if d.severity == "error"]
        if errors:
            raise ProviderError(f"SAM output could not be parsed: {'; '.join(errors[:3])}")
        return []
    out: list[tuple[BoolMask, float]] = []
    for obj, rec in latest.items():
        raw = decode_mask_to_raster(rec.mask)
        raster = np.frombuffer(raw, dtype=np.uint8).reshape(rec.mask.height, rec.mask.width).astype(bool)
        mask = np.zeros((height, width), dtype=bool)
        b = rec.bounds
        _paste(raster, math.floor(b.left), math.floor(b.top), math.ceil(b.right), math.ceil(b.bottom), mask)
        if mask.any():
            out.append((mask, float(conf.get((0, obj), 1.0))))
    out.sort(key=lambda t: (-t[1], -int(t[0].sum())))
    return out


def parse_video_masks(text: str, width: int, height: int) -> list[tuple[int, str, BoolMask, float]]:
    """SAM 3.1 video output → `[(frame index, object id, full-frame mask, score)]` sorted by frame then score.

    Frames may arrive out of order (forward then backward propagation); the latest revision per (frame, object) wins.
    """
    from meta_sam_parser import (
        CompletedOutcome,
        SegmentationMaskRecord,
        decode_mask_to_raster,
        video_segmentation_format,
    )

    if not text.strip():
        return []
    clean, conf = split_confidence(text)
    parser = video_segmentation_format().create_parser()
    parser.push(clean)
    result = parser.finish(CompletedOutcome()).result
    latest: dict[tuple[int, str], Any] = {}
    for rec in result.records:
        if isinstance(rec, SegmentationMaskRecord):
            frame = rec.frame.frame_index if rec.frame is not None else 0
            latest[(frame, rec.object_id)] = rec
    if not latest and any(d.severity == "error" for d in result.diagnostics):
        raise ProviderError(f"SAM video output could not be parsed: {result.diagnostics[0].message}")
    out: list[tuple[int, str, BoolMask, float]] = []
    for (frame, obj), rec in latest.items():
        flat = np.frombuffer(decode_mask_to_raster(rec.mask), dtype=np.uint8)
        raster = flat.reshape(rec.mask.height, rec.mask.width).astype(bool)
        mask = np.zeros((height, width), dtype=bool)
        b = rec.bounds
        _paste(raster, math.floor(b.left), math.floor(b.top), math.ceil(b.right), math.ceil(b.bottom), mask)
        if mask.any():
            out.append((frame, obj, mask, float(conf.get((frame, obj), 1.0))))
    out.sort(key=lambda t: (t[0], -t[3]))
    return out
