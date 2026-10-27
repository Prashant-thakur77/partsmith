"""Client for the self-hosted SAM 3 open-weights service (`infra/modal/sam3.py`).

Wire format (shared with the Modal app):
    POST {SAM3_OPEN_URL}/segment  {"image_b64": str, "prompt": str, "threshold": float}
      -> {"width": int, "height": int, "model": str, "ms": int,
          "masks": [{"score": float, "box_xyxy": [x1, y1, x2, y2], "rle": {"size": [h, w], "counts": [...]}}]}
    GET  {SAM3_OPEN_URL}/health -> {"ok": true, "model": str, "gpu": str}
`rle` is uncompressed row-major run lengths starting with a run of False (see `media.rle_encode`).
An optional bearer token (`SAM3_OPEN_API_KEY`) is sent when set.
"""

from __future__ import annotations

import base64
from typing import Any

from . import clients, media
from .base import ProviderError
from .routing import Route


def _headers(route: Route) -> dict[str, str]:
    key = route.endpoint.key()
    return {"Authorization": f"Bearer {key}"} if key else {}


def _url(route: Route) -> str:
    base = route.endpoint.base_url()
    if not base:
        raise ProviderError(f"{route.endpoint.url_env} missing", provider=route.provider)
    return base


def segment_request(image: bytes, prompt: str, threshold: float = 0.5) -> dict[str, Any]:
    return {"image_b64": base64.b64encode(image).decode("ascii"), "prompt": prompt, "threshold": threshold}


def decode_response(data: dict[str, Any], width: int, height: int) -> list[tuple[media.BoolMask, float]]:
    out: list[tuple[media.BoolMask, float]] = []
    for m in data.get("masks", []):
        mask = media.rle_decode(m["rle"])
        if mask.shape != (height, width):
            raise ProviderError(f"SAM 3 service returned a {mask.shape} mask for a {width}x{height} image")
        out.append((mask, float(m.get("score", 0.0))))
    out.sort(key=lambda t: -t[1])
    return out


def segment(route: Route, image: bytes, prompt: str, timeout_s: float) -> list[tuple[media.BoolMask, float]]:
    width, height = media.image_size(image)
    with clients.http_client(timeout_s) as http:
        resp = http.post(f"{_url(route)}/segment", json=segment_request(image, prompt), headers=_headers(route))
    resp.raise_for_status()
    return decode_response(resp.json(), width, height)


def health(route: Route, timeout_s: float = 30.0) -> dict[str, Any]:
    with clients.http_client(timeout_s) as http:
        resp = http.get(f"{_url(route)}/health", headers=_headers(route))
    resp.raise_for_status()
    data = resp.json()
    return data if isinstance(data, dict) else {"ok": bool(data)}
