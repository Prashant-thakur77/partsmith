"""SAM 3.1 beyond text prompts: point/box prompts on one image, and video tracking for orbit clips.

- `segment_points`: one object, positive/negative points and an optional box, built into the SAM token prompt
  (`<0f>1<|box;...|><|point;...|>`, w/h = image size, frame 0). Masks come back box-local and are pasted full-frame.
- `segment_video`: the clip is uploaded with the Files API and referenced as `input_video`; the stream is collected
  with the same shim as images; frames can arrive out of order. SAM 3.1 accepts MP4/MOV only, so other containers
  (WebM from browsers) are transcoded with ffmpeg — and resampled to `fps` to keep the per-frame bill small.

Mocks run the real code path on the real pixels: flood fill around the points, and per-frame background subtraction.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np

from . import meta, mocks, pricing, replay, retry, sam_open, sam_parse
from .base import Usage
from .config import settings
from .core import Outcome, dispatch, retry_opts
from .media import BoolMask, decode_image_rgb, image_size, rle_decode, rle_encode, sha256
from .routing import Route

Point = tuple[float, float]
Box = tuple[float, float, float, float]  # x1, y1, x2, y2 in pixels
VIDEO_MIMES = {"video/mp4", "video/quicktime"}
MAX_VIDEO_BYTES = 200 * 1024 * 1024
MAX_VIDEO_FRAMES = 15_000


@dataclass
class FrameMask:
    frame_idx: int
    t_s: float
    mask: BoolMask
    score: float
    object_id: str = "1"


# ------------------------------------------------------------------------------------------------ point prompts


def _clamp(v: float, hi: int) -> int:
    return min(max(round(v), 0), hi - 1)


def object_prompt(
    width: int, height: int, points_pos: Sequence[Point], points_neg: Sequence[Point], box: Box | None
) -> str:
    """SAM prompt for one object on frame 0. Uses meta_sam_parser's builder when the installed version has it."""
    try:
        from meta_sam_parser import (  # type: ignore[attr-defined]
            FramePrompt,
            PromptBox,
            PromptObject,
            PromptPoint,
            build_object_prompt,
        )
    except ImportError:
        build_object_prompt = None
    if build_object_prompt is not None:  # pragma: no cover - not in meta-sam-parser 0.0.5
        points = [PromptPoint(_clamp(x, width), _clamp(y, height)) for x, y in points_pos]
        points += [PromptPoint(_clamp(x, width), _clamp(y, height), label="negative") for x, y in points_neg]
        pbox = PromptBox(*(_clamp(v, width if i % 2 == 0 else height) for i, v in enumerate(box))) if box else None
        frame = FramePrompt(frame=0, box=pbox, points=points or None)
        return str(build_object_prompt(size=(width, height), objects=[PromptObject(id=1, prompts=[frame])]))
    tokens: list[str] = []
    if box is not None:
        x1, y1, x2, y2 = _clamp(box[0], width), _clamp(box[1], height), _clamp(box[2], width), _clamp(box[3], height)
        tokens.append(f"<|box;x1={x1};y1={y1};x2={x2};y2={y2};w={width};h={height}|>")
    for x, y in points_pos:
        tokens.append(f"<|point;x={_clamp(x, width)};y={_clamp(y, height)};w={width};h={height}|>")
    for x, y in points_neg:  # negative points carry a "-" prefix
        tokens.append(f"-<|point;x={_clamp(x, width)};y={_clamp(y, height)};w={width};h={height}|>")
    return "<0f>1" + "".join(tokens)


def _encode_masks(masks: list[tuple[BoolMask, float]]) -> dict[str, Any]:
    return {"masks": [{"rle": rle_encode(m), "score": s} for m, s in masks]}


def _decode_masks(resp: dict[str, Any]) -> list[tuple[BoolMask, float]]:
    return [(rle_decode(m["rle"]), float(m["score"])) for m in resp.get("masks", [])]


def segment_points(
    image_png: bytes, points_pos: Sequence[Point], points_neg: Sequence[Point] = (), box: Box | None = None
) -> list[tuple[BoolMask, float]]:
    """Masks for the one object marked by pixel points (and/or a box): `[(bool mask HxW, score)]`, best first."""
    if not points_pos and box is None:
        raise ValueError("segment_points needs at least one positive point or a box")
    width, height = image_size(image_png)
    prompt = object_prompt(width, height, points_pos, points_neg, box)
    request = {"image": sha256(image_png), "prompt": prompt}
    digest = meta_digest("segment_points", request)

    def attempt(route: Route) -> Outcome[list[tuple[BoolMask, float]]]:
        timeout = settings().timeout_s
        masks = retry.with_retries(lambda: meta.sam_segment(route, image_png, prompt, timeout), **retry_opts(route))
        return Outcome(masks, Usage(), route.model, pricing.segment_cost_usd(route.provider))

    def mock() -> list[tuple[BoolMask, float]]:
        return mocks.flood_segment(decode_image_rgb(image_png), list(points_pos), list(points_neg), box)

    out = dispatch(
        "segment_points",
        digest,
        request=request,
        mock=mock,
        attempt=attempt,
        encode=_encode_masks,
        decode=_decode_masks,
    )
    return out.value


def meta_digest(stage: str, request: dict[str, Any]) -> str:
    return replay.request_hash(stage, stage, request)


# ------------------------------------------------------------------------------------------------ video


@dataclass
class PreparedVideo:
    data: bytes  # MP4 / MOV bytes as uploaded
    mime: str
    width: int
    height: int
    fps: float
    n_frames: int
    transcoded: bool


def probe_video(data: bytes, suffix: str = ".mp4") -> tuple[int, int, float, int]:
    """(width, height, fps, frame count) using OpenCV's bundled decoder."""
    import cv2

    with tempfile.NamedTemporaryFile(suffix=suffix) as f:
        f.write(data)
        f.flush()
        cap = cv2.VideoCapture(f.name)
        try:
            if not cap.isOpened():
                raise ValueError("video could not be decoded")
            w, h = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            fps = float(cap.get(cv2.CAP_PROP_FPS)) or 0.0
            n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            if n <= 0:  # some containers do not report a count: decode to count
                n = 0
                while cap.grab():
                    n += 1
        finally:
            cap.release()
    if w <= 0 or h <= 0:
        raise ValueError("video has no frames")
    return w, h, fps, n


def _ffmpeg_to_mp4(data: bytes, mime: str, fps: float) -> bytes:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise ValueError(
            f"{mime} video: SAM 3.1 accepts MP4/MOV only and ffmpeg is not installed to convert it "
            "(install ffmpeg, or record MP4)"
        )
    with tempfile.TemporaryDirectory() as tmp:
        src, dst = os.path.join(tmp, "in.bin"), os.path.join(tmp, "out.mp4")
        with open(src, "wb") as f:
            f.write(data)
        last_err = ""
        for codec in (["-c:v", "libx264", "-pix_fmt", "yuv420p"], ["-c:v", "mpeg4", "-q:v", "3"]):
            cmd = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", src, "-vf", f"fps={fps:g}", *codec]
            proc = subprocess.run([*cmd, "-an", "-movflags", "+faststart", dst], capture_output=True, timeout=300)
            if proc.returncode == 0 and os.path.getsize(dst) > 0:
                with open(dst, "rb") as f:
                    return f.read()
            last_err = proc.stderr.decode(errors="replace")[:200]
    raise ValueError(f"ffmpeg could not convert the {mime} video to MP4: {last_err}")


def prepare_video(data: bytes, mime: str, fps: float) -> PreparedVideo:
    """MP4/H.264 at `fps` when ffmpeg is available; MP4/MOV pass through otherwise; anything else needs ffmpeg."""
    if len(data) > MAX_VIDEO_BYTES:
        raise ValueError(f"video is {len(data) // 2**20} MiB; the limit is {MAX_VIDEO_BYTES // 2**20} MiB")
    mime = mime.split(";")[0].strip().lower()
    if shutil.which("ffmpeg") or mime not in VIDEO_MIMES:
        mp4 = _ffmpeg_to_mp4(data, mime, fps)
        w, h, _, n = probe_video(mp4)
        return PreparedVideo(mp4, "video/mp4", w, h, float(fps), n, True)
    w, h, native_fps, n = probe_video(data, ".mov" if mime == "video/quicktime" else ".mp4")
    if native_fps <= 0:
        raise ValueError("video has no frame rate; install ffmpeg so it can be re-encoded")
    return PreparedVideo(data, mime, w, h, native_fps, n, False)


def video_frames(video: PreparedVideo) -> list[np.ndarray[Any, Any]]:
    import cv2

    suffix = ".mov" if video.mime == "video/quicktime" else ".mp4"
    frames: list[np.ndarray[Any, Any]] = []
    with tempfile.NamedTemporaryFile(suffix=suffix) as f:
        f.write(video.data)
        f.flush()
        cap = cv2.VideoCapture(f.name)
        try:
            while len(frames) < MAX_VIDEO_FRAMES:
                ok, bgr = cap.read()
                if not ok:
                    break
                frames.append(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB))
        finally:
            cap.release()
    return frames


def _meta_video(route: Route, video: PreparedVideo, prompt: str, timeout_s: float) -> list[FrameMask]:
    client = meta.client_for(route, timeout_s)
    file_id = meta.upload(client, video.data, video.mime, "orbit.mp4" if video.mime == "video/mp4" else "orbit.mov")
    events = client.responses.create(
        model=route.model,
        stream=True,
        input=[
            {
                "type": "message",
                "role": "user",
                "content": [{"type": "input_text", "text": prompt}, {"type": "input_video", "file_id": file_id}],
            }
        ],
        metadata={"mask_encoding": "one_bit", "include_confidence": "true"},
        store=False,
    )
    try:
        text, _ = sam_parse.stream_text(events)
    finally:
        close = getattr(events, "close", None)
        if callable(close):
            close()
    return [
        FrameMask(frame, frame / video.fps, mask, score, obj)
        for frame, obj, mask, score in sam_parse.parse_video_masks(text, video.width, video.height)
    ]


def _encode_frames(frames: list[FrameMask]) -> dict[str, Any]:
    return {
        "frames": [
            {
                "frame_idx": f.frame_idx,
                "t_s": f.t_s,
                "score": f.score,
                "object_id": f.object_id,
                "rle": rle_encode(f.mask),
            }
            for f in frames
        ]
    }


def _decode_frames(resp: dict[str, Any]) -> list[FrameMask]:
    return [
        FrameMask(
            int(f["frame_idx"]), float(f["t_s"]), rle_decode(f["rle"]), float(f["score"]), str(f.get("object_id", "1"))
        )
        for f in resp.get("frames", [])
    ]


def segment_video(video_bytes: bytes, mime: str, prompt: str, *, fps: float = 5.0) -> list[FrameMask]:
    """Track one noun phrase through a short clip: one `FrameMask` per (frame, object), sorted by frame then score."""
    from .core import normalize_phrase

    phrase = normalize_phrase(prompt)
    if fps <= 0:
        raise ValueError("fps must be positive")
    video = prepare_video(video_bytes, mime, fps)
    if video.n_frames > MAX_VIDEO_FRAMES:
        raise ValueError(f"clip has {video.n_frames} frames; SAM 3.1 tracks at most {MAX_VIDEO_FRAMES}")
    request = {"video": sha256(video_bytes), "mime": mime, "prompt": phrase, "fps": fps}
    digest = meta_digest("segment_video", request)

    def attempt(route: Route) -> Outcome[list[FrameMask]]:
        timeout = max(settings().timeout_s, 600.0)
        if route.endpoint.name == "meta":
            frames = retry.with_retries(lambda: _meta_video(route, video, phrase, timeout), **retry_opts(route))
        else:
            raw = retry.with_retries(
                lambda: sam_open.segment_video(route, video.data, phrase, video.fps, timeout), **retry_opts(route)
            )
            frames = [FrameMask(f, t, m, s, o) for f, t, m, s, o in raw]
        n_frames = video.n_frames or (max((f.frame_idx for f in frames), default=-1) + 1)
        return Outcome(frames, Usage(), route.model, pricing.video_cost_usd(route.provider, n_frames))

    def mock() -> list[FrameMask]:
        out: list[FrameMask] = []
        for i, rgb in enumerate(video_frames(video)):
            for mask, score in mocks.threshold_segment(rgb):
                out.append(FrameMask(i, i / video.fps, mask, score))
        return out

    result = dispatch(
        "segment_video",
        digest,
        request=request,
        mock=mock,
        attempt=attempt,
        encode=_encode_frames,
        decode=_decode_frames,
    )
    return result.value
