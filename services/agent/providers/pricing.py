"""Price table → `usd` on every model call. Mock and replay calls cost $0.

Meta Model API rates are the published per-1M-token / per-image / per-hour prices. Spark Open on Baseten uses
Baseten's published rate; Fireworks and Together Spark Open rates are not in our reference notes, so they are
*assumed* equal to Baseten (flagged `assumed=True`; check the provider page). Self-hosted Modal endpoints are billed
by GPU time, not per token, so they report $0 here and their GPU cost shows on the Modal dashboard.
"""

from __future__ import annotations

from dataclasses import dataclass

from .base import Usage


@dataclass(frozen=True)
class TokenPrice:
    input_per_m: float
    output_per_m: float
    cached_per_m: float
    assumed: bool = False


SPARK = TokenPrice(1.25, 4.25, 0.15)
SPARK_CONTRIBUTOR = TokenPrice(0.10, 0.20, 0.002)
WONDER = TokenPrice(4.00, 20.00, 0.20)
SPARK_OPEN_BASETEN = TokenPrice(1.25, 4.25, 0.15)
SPARK_OPEN_ASSUMED = TokenPrice(1.25, 4.25, 0.15, assumed=True)
GLIMMER_TOGETHER = TokenPrice(0.35, 1.50, 0.04)
SELF_HOSTED = TokenPrice(0.0, 0.0, 0.0)

SAM_31_PER_IMAGE_USD = 2.50 / 1000
MUSE_IMAGE_PER_IMAGE_USD = 0.01
VOICE_PER_HOUR_USD = 0.18


def token_price(provider: str, model: str) -> TokenPrice:
    m = model.lower()
    if provider in ("modal_glimmer", "modal_sam3"):
        return SELF_HOSTED
    if provider == "meta":
        if m.endswith("-contributor"):
            return SPARK_CONTRIBUTOR
        if m.startswith("muse-wonder"):
            return WONDER
        return SPARK
    if "glimmer" in m:
        return GLIMMER_TOGETHER
    if provider == "baseten":
        return SPARK_OPEN_BASETEN
    return SPARK_OPEN_ASSUMED


def token_cost_usd(provider: str, model: str, usage: Usage) -> float:
    """Reasoning tokens are billed as output tokens and are already inside `tokens_out`."""
    p = token_price(provider, model)
    cached = min(usage.cached_in, usage.tokens_in)
    fresh = usage.tokens_in - cached
    usd = (fresh * p.input_per_m + cached * p.cached_per_m + usage.tokens_out * p.output_per_m) / 1_000_000
    return round(usd, 8)


def segment_cost_usd(provider: str, n_images: int = 1) -> float:
    return round(SAM_31_PER_IMAGE_USD * n_images, 8) if provider == "meta" else 0.0


def image_cost_usd(provider: str, n_images: int = 1) -> float:
    return round(MUSE_IMAGE_PER_IMAGE_USD * n_images, 8) if provider == "meta" else 0.0


def voice_cost_usd(provider: str, duration_ms: int | None) -> float:
    if provider != "meta" or not duration_ms:
        return 0.0
    return round(VOICE_PER_HOUR_USD * duration_ms / 3_600_000, 8)
