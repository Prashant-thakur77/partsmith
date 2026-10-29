"""Muse Image beyond single previews: region completion, iterative edits, anchored install-card series.

- `reconstruct`: Muse Image completes the broken region of the rectified photo. Code then pastes the original pixels
  back everywhere outside that region, so the intact region is pixel-identical by construction; whether the
  completion is *accepted* (markers re-detect, intact IoU) is decided by metrology, never here.
- `edit_image`: continue a stored image response (`previous_response_id`, store=True) with only the change.
- `install_card`: an anchored series — panel 1 from the photo + render, each next panel continues the previous
  response so the scene, camera and part stay the same.

Mocks (labelled MOCK): mirror-symmetry completion (+ inpainting for what the mirror can't reach), tinted copies for
edits, and composites for the install card.
"""

from __future__ import annotations

import io
import re
from collections.abc import Sequence
from typing import Any

import numpy as np

from . import meta, mocks, pricing, replay, retry
from .base import ImageResult, Usage
from .config import log, settings
from .core import Dispatched, Outcome, dispatch, retry_opts
from .media import decode_image_rgb, encode_png, sha256
from .routing import Route

MAX_PANELS = 6
STALE_RESPONSE = "referenced response not found"  # live API text when a stored image response cannot be continued
COLOURS = {
    "black": (25, 25, 28), "white": (235, 235, 230), "red": (190, 35, 35), "blue": (40, 80, 190),
    "green": (40, 140, 70), "yellow": (225, 190, 40), "orange": (225, 120, 30), "grey": (128, 128, 128),
    "gray": (128, 128, 128), "kala": (25, 25, 28), "safed": (235, 235, 230), "laal": (190, 35, 35),
}  # fmt: skip

RECONSTRUCT_PROMPT = (
    "The first image is a top-down photo of a broken plastic part on a calibration mat. The second image is a mask: "
    "white = keep exactly as it is, black = the missing or broken region. Complete only the black region so the part "
    "looks whole and undamaged, matching its material, colour, lighting and scale and continuing its edges and "
    "symmetry. Do not move, resize, recolour or redraw anything in the white region, and keep the mat markers intact."
)


def _image_result(out: Dispatched[tuple[bytes, str, str]], note: str = "") -> ImageResult:
    data, mime, rid = out.value
    return ImageResult(
        data=data, mime=mime, mode=out.mode, provider=out.provider, model=out.model, usd=out.usd, ms=out.ms,
        note="; ".join(n for n in (out.note, note) if n), response_id=rid,
    )  # fmt: skip


def _encode(v: tuple[bytes, str, str]) -> dict[str, Any]:
    import base64

    return {"b64": base64.b64encode(v[0]).decode("ascii"), "mime": v[1], "response_id": v[2]}


def _decode(r: dict[str, Any]) -> tuple[bytes, str, str]:
    import base64

    return base64.b64decode(r["b64"]), str(r.get("mime", "image/png")), str(r.get("response_id", ""))


def _keep_mask(keep_mask_png: bytes, size: tuple[int, int]) -> np.ndarray[Any, Any]:
    from PIL import Image

    with Image.open(io.BytesIO(keep_mask_png)) as im:
        gray = im.convert("L")
        if gray.size != size:
            gray = gray.resize(size, Image.Resampling.NEAREST)
        return np.asarray(gray) > 127


def keep_composite(original_rgb: np.ndarray[Any, Any], generated: bytes, keep: np.ndarray[Any, Any]) -> bytes:
    """Generated pixels inside the completed region, the original everywhere else (pixel-identical)."""
    from PIL import Image

    h, w = original_rgb.shape[:2]
    with Image.open(io.BytesIO(generated)) as im:
        gen = np.asarray(im.convert("RGB").resize((w, h), Image.Resampling.LANCZOS))
    out = np.where(keep[..., None], original_rgb, gen).astype(np.uint8)
    return encode_png(out)


def _mirror(a: np.ndarray[Any, Any], c2: int) -> np.ndarray[Any, Any]:
    """Mirror columns of `a` about x = c2 / 2 (columns that fall outside become False / 0)."""
    w = a.shape[1]
    src = c2 - np.arange(w)
    valid = (src >= 0) & (src < w)
    out = np.zeros_like(a)
    out[:, valid] = a[:, src[valid]]
    return out


def symmetry_axis(part: np.ndarray[Any, Any], keep: np.ndarray[Any, Any]) -> tuple[str, float]:
    """Best mirror axis ("x" = vertical line x=c, "y" = horizontal line y=c) for completing the broken region.

    Score = symmetry IoU of the completed part × (1 + share of the broken region the mirror fills with part), so the
    trivial axis of the remaining stub (which fills nothing) loses to the axis that restores the missing end.
    """
    scale = min(1.0, 256 / max(part.shape))
    if scale < 1.0:
        import cv2

        size = (max(1, round(part.shape[1] * scale)), max(1, round(part.shape[0] * scale)))
        part = cv2.resize(part.astype(np.uint8), size, interpolation=cv2.INTER_NEAREST) > 0
        keep = cv2.resize(keep.astype(np.uint8), size, interpolation=cv2.INTER_NEAREST) > 0
    broken = ~keep
    best = ("x", (part.shape[1] - 1) / 2.0, -1.0)
    for axis in ("x", "y"):
        p, k, b = (part, keep, broken) if axis == "x" else (part.T, keep.T, broken.T)
        cols = np.nonzero(p.any(axis=0) | b.any(axis=0))[0]
        if len(cols) == 0:
            continue
        for c2 in range(int(2 * cols.min()), int(2 * cols.max()) + 1):
            fill = b & _mirror(p & k, c2)
            completed = (p & k) | fill
            union = (completed | _mirror(completed, c2)).sum()
            iou = (completed & _mirror(completed, c2)).sum() / union if union else 0.0
            score = iou * (1 + fill.sum() / max(1, b.sum()))
            if score > best[2]:
                best = (axis, c2 / 2.0 / scale, score)
    return best[0], best[1]


def mirror_complete(rgb: np.ndarray[Any, Any], keep: np.ndarray[Any, Any]) -> np.ndarray[Any, Any]:
    """Mock completion: mirror the intact part across its best symmetry axis, inpaint whatever is left."""
    import cv2

    h, w = keep.shape
    filler = np.median(rgb[keep], axis=0) if keep.any() else np.zeros(3)
    part = mocks.threshold_segment(np.where(keep[..., None], rgb, filler).astype(np.uint8))
    axis, c = symmetry_axis(part[0][0], keep) if part else ("x", (w - 1) / 2.0)
    out = rgb.copy()
    ys, xs = np.nonzero(~keep)
    if axis == "x":
        my, mx = ys, np.round(2 * c - xs).astype(int)
    else:
        my, mx = np.round(2 * c - ys).astype(int), xs
    ok = (mx >= 0) & (mx < w) & (my >= 0) & (my < h)
    ok[ok] &= keep[my[ok], mx[ok]]
    out[ys[ok], xs[ok]] = rgb[my[ok], mx[ok]]
    rest = np.zeros((h, w), np.uint8)
    rest[ys[~ok], xs[~ok]] = 255
    if rest.any():
        out = cv2.inpaint(out, rest, 5, cv2.INPAINT_TELEA)
    return out


def _stamp_region(rgb: np.ndarray[Any, Any], region: np.ndarray[Any, Any], text: str = "MOCK") -> np.ndarray[Any, Any]:
    """Write `text` inside the completed region only, so the intact region stays pixel-identical."""
    import cv2

    ys, xs = np.nonzero(region)
    if len(xs) == 0:
        return rgb
    x0, y0, x1, y1 = xs.min(), ys.min(), xs.max(), ys.max()
    if x1 - x0 < 30 or y1 - y0 < 10:
        return rgb
    canvas = rgb.copy()
    scale = max(0.3, min(1.5, (x1 - x0) / 120))
    cv2.putText(canvas, text, (int(x0) + 2, int((y0 + y1) / 2) + 4), cv2.FONT_HERSHEY_SIMPLEX, scale, (220, 0, 0), 1)
    return np.where(region[..., None], canvas, rgb).astype(np.uint8)


def reconstruct(rectified_png: bytes, keep_mask_png: bytes, instruction: str = "") -> ImageResult:
    """Complete the broken region of `rectified_png`. `keep_mask_png`: white = intact (kept pixel-identical)."""
    original = decode_image_rgb(rectified_png)
    h, w = original.shape[:2]
    keep = _keep_mask(keep_mask_png, (w, h))
    if keep.all():
        raise ValueError("keep mask covers the whole image: nothing to reconstruct")
    prompt = RECONSTRUCT_PROMPT + (f" {instruction.strip()}" if instruction.strip() else "")
    request = {"image": sha256(rectified_png), "mask": sha256(keep_mask_png), "prompt": prompt}
    digest = replay.request_hash("reconstruct", "reconstruct", request)

    def attempt(route: Route) -> Outcome[tuple[bytes, str, str]]:
        timeout = max(settings().timeout_s, 300.0)
        gen, _, _ = retry.with_retries(
            lambda: meta.image_generate(route, prompt, [rectified_png, keep_mask_png], timeout), **retry_opts(route)
        )
        return Outcome(
            (keep_composite(original, gen, keep), "image/png", ""),
            Usage(),
            route.model,
            pricing.image_cost_usd(route.provider),
        )

    def mock() -> tuple[bytes, str, str]:
        filled = _stamp_region(mirror_complete(original, keep), ~keep)
        return encode_png(np.where(keep[..., None], original, filled).astype(np.uint8)), "image/png", ""

    out = dispatch("reconstruct", digest, request=request, mock=mock, attempt=attempt, encode=_encode, decode=_decode)
    note = "intact region pixel-identical (enforced by code)"
    if out.mode == "mock":
        note = "MOCK reconstruction — mirror symmetry + inpainting, not AI-generated; " + note
    return _image_result(out, note)


def _tint(png: bytes, instruction: str) -> bytes:
    rgb = decode_image_rgb(png).astype(np.float32)
    colour = next((COLOURS[w] for w in re.findall(r"[a-z]+", instruction.lower()) if w in COLOURS), None)
    masks = mocks.threshold_segment(rgb.astype(np.uint8))
    if colour is not None and masks:
        m = masks[0][0][..., None]
        lum = rgb.mean(axis=2, keepdims=True) / 255.0
        tinted = np.clip(np.array(colour, np.float32) * (0.6 + 0.8 * lum), 0, 255)
        rgb = np.where(m, tinted, rgb)
    else:
        rgb = np.clip(rgb * 0.92 + 10, 0, 255)
    return encode_png(rgb.astype(np.uint8))


def _labelled(png: bytes, text: str) -> bytes:
    from PIL import Image

    with Image.open(io.BytesIO(png)) as im:
        out = mocks.label_image(im, text)
    buf = io.BytesIO()
    out.save(buf, format="PNG")
    return buf.getvalue()


def edit_image(previous_id: str, instruction: str) -> ImageResult:
    """Iterative edit of a stored image response ("show it in black PETG"). Send only the change."""
    if not previous_id:
        raise ValueError("edit_image needs the response_id of a stored image (generate it with editable=True)")
    request = {"previous_id": previous_id, "instruction": instruction}
    digest = replay.request_hash("image_edit", "image", request)

    def attempt(route: Route) -> Outcome[tuple[bytes, str, str]]:
        if previous_id.startswith("mock-img-"):
            raise ValueError("this image came from the mock; generate it live before editing it live")
        timeout = max(settings().timeout_s, 300.0)
        value = retry.with_retries(
            lambda: meta.image_generate(route, instruction, [], timeout, store=True, previous_response_id=previous_id),
            **retry_opts(route),
        )
        return Outcome(value, Usage(), route.model, pricing.image_cost_usd(route.provider))

    def mock() -> tuple[bytes, str, str]:
        prev = mocks.recall_mock_image(previous_id)
        if prev is None:
            raise ValueError(f"unknown image id {previous_id!r} (mock images live only in this process)")
        data = _labelled(_tint(prev, instruction), f"MOCK EDIT — not AI-generated: {instruction[:60]}")
        return data, "image/png", mocks.remember_mock_image(data)

    return _image_result(
        dispatch("image", digest, request=request, mock=mock, attempt=attempt, encode=_encode, decode=_decode)
    )


def _panel_mock(photo_png: bytes, render_png: bytes, k: int, n: int, step: str) -> bytes:
    from PIL import Image

    photo = Image.open(io.BytesIO(photo_png)).convert("RGB")
    render = (
        Image.open(io.BytesIO(render_png))
        .convert("RGB")
        .resize((max(1, photo.width // 3), max(1, photo.height // 3)), Image.Resampling.BILINEAR)
    )
    canvas = photo.copy()
    # the part moves from the corner towards the centre as the steps progress
    frac = (k + 1) / n
    x = int((photo.width - render.width) * (0.1 + 0.4 * frac))
    y = int((photo.height - render.height) * (0.9 - 0.4 * frac))
    canvas.paste(render, (x, y))
    out = mocks.label_image(canvas, f"MOCK — step {k + 1}/{n}: {step[:50]}")
    buf = io.BytesIO()
    out.save(buf, format="PNG")
    return buf.getvalue()


def install_card(photo_png: bytes, render_png: bytes, steps: Sequence[str]) -> list[ImageResult]:
    """One anchored panel per step (≤ 6): the replacement part installed in the user's own scene."""
    steps = [s.strip() for s in steps if s.strip()]
    if not steps or len(steps) > MAX_PANELS:
        raise ValueError(f"install_card takes 1 to {MAX_PANELS} non-empty steps")
    n = len(steps)
    panels: list[ImageResult] = []
    previous = ""
    for k, step in enumerate(steps):
        if k == 0:
            prompt = (
                f"Panel 1 of {n} of a photoreal installation guide. The first image is the user's photo of where the part "
                "goes; the second image is a render of the 3D-printed replacement part. Show this step in the same scene "
                f"and camera angle as the first image, with the replacement part exactly as rendered. Step: {step}"
            )
        else:
            prompt = f"Panel {k + 1} of {n}. Keep the same scene, camera, lighting and part. Step: {step}"
        request = {"photo": sha256(photo_png), "render": sha256(render_png), "steps": steps[: k + 1]}
        digest = replay.request_hash("install_card", "image", request)
        prev_id = previous

        def attempt(
            route: Route, k: int = k, prompt: str = prompt, prev_id: str = prev_id
        ) -> Outcome[tuple[bytes, str, str]]:
            timeout = max(settings().timeout_s, 300.0)
            anchored = k > 0 and bool(prev_id) and not prev_id.startswith("mock-img-")

            def panel(anchor: bool) -> tuple[bytes, str, str]:
                refs = [] if anchor else [photo_png, render_png]  # no stored previous panel: re-send the references
                return retry.with_retries(
                    lambda: meta.image_generate(
                        route, prompt, refs, timeout, store=True, previous_response_id=prev_id if anchor else None
                    ),
                    **retry_opts(route),
                )

            try:
                value = panel(anchored)
            except Exception as exc:
                # the live API can answer "referenced response not found or expired" for a panel it just stored:
                # redo this panel from the photo and render instead of losing the whole card
                if not (anchored and STALE_RESPONSE in str(exc).lower()):
                    raise
                log.info(
                    "install card panel %d: stored previous panel unavailable (%s); re-sending references", k + 1, exc
                )
                value = panel(False)
            return Outcome(value, Usage(), route.model, pricing.image_cost_usd(route.provider))

        def mock(k: int = k, step: str = step) -> tuple[bytes, str, str]:
            data = _panel_mock(photo_png, render_png, k, n, step)
            return data, "image/png", mocks.remember_mock_image(data)

        result = _image_result(
            dispatch("image", digest, request=request, mock=mock, attempt=attempt, encode=_encode, decode=_decode)
        )
        panels.append(result)
        previous = result.response_id
    return panels
