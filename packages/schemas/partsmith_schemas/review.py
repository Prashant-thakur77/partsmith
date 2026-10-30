"""Human review contracts: pins a reviewer drops on the rectified top photo and the rules they keep on accept."""

from __future__ import annotations

from pydantic import Field

from .common import Strict


class Pin(Strict):
    """A reviewer's point on the rectified top photo, normalised to its width (u) and height (v), 0–1, with a note.
    Code turns it into mat and part-frame millimetres inside the job that uses it."""

    id: int = Field(ge=1)
    u: float = Field(ge=0.0, le=1.0)
    v: float = Field(ge=0.0, le=1.0)
    note: str = Field("", max_length=300)


class RuleChoice(Strict):
    """A drafted family rule as the reviewer left it on accept: `keep` promotes it, otherwise it stays a candidate."""

    text: str = Field(min_length=1, max_length=200)
    keep: bool = False
    source_pin: int | None = None
