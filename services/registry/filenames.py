"""Download file names: `partsmith-<slug>-<knobs that differ from the defaults>.<ext>`, e.g.
`partsmith-cable-clip-hole3.4.stl`, so two variants of one part never land on disk under the same name.

Safe ASCII only (a-z, 0-9, '.', '-'), at most `MAX_LEN` characters with the extension. Knobs are listed in PARAMS
order; a knob name loses its underscores and a one-letter suffix (`hole_d` -> `hole`, `wall_t` -> `wall`). Knobs that
do not fit are dropped and counted (`-plus2`). The web app builds the same names (apps/web/src/lib/download-name.ts).
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterable, Mapping

MAX_LEN = 80
PREFIX = "partsmith"
_UNSAFE = re.compile(r"[^a-z0-9.]+")


def safe(text: str) -> str:
    """Lowercase ASCII words joined by '-' ("Cable_Clip v2!" -> "cable-clip-v2")."""
    return "-".join(w.strip(".") for w in _UNSAFE.split(text.lower()) if w.strip(".")).strip(".-")


def knob_short(name: str) -> str:
    """`hole_d` -> `hole`, `channel_count` -> `channelcount`, `wall_t` -> `wall`."""
    parts = [p for p in name.lower().split("_") if p]
    if len(parts) > 1 and len(parts[-1]) == 1:
        parts = parts[:-1]
    return re.sub(r"[^a-z0-9]", "", "".join(parts)) or "k"


def num_text(v: float) -> str:
    """Up to two decimals, no trailing zeros: 3.4 -> "3.4", 8.0 -> "8", 0.25 -> "0.25", -5 -> "-5"."""
    s = f"{math.floor(float(v) * 100 + 0.5) / 100:.2f}".rstrip("0").rstrip(".")  # half up, like the web's Math.round
    return "0" if s in ("-0", "") else s


def knob_summary(values: Mapping[str, float], defaults: Mapping[str, float], order: Iterable[str] = ()) -> list[str]:
    """`hole3.4`-style tokens for every knob whose value differs from its default (PARAMS order first)."""
    names = list(dict.fromkeys([*order, *defaults, *values]))
    out: list[str] = []
    for n in names:
        if n not in values:
            continue
        v, d = float(values[n]), defaults.get(n)
        if d is not None and abs(v - float(d)) < 1e-9:
            continue
        out.append(f"{knob_short(n)}{num_text(v)}")
    return out


def download_name(
    slug: str,
    ext: str,
    values: Mapping[str, float] | None = None,
    defaults: Mapping[str, float] | None = None,
    order: Iterable[str] = (),
) -> str:
    """`partsmith-<slug>[-<knob><value>...][-plusN].<ext>` (safe ASCII, at most MAX_LEN characters)."""
    ext = "." + safe(ext.lstrip(".")).replace("-", ".") if ext.strip(".") else ""
    base = f"{PREFIX}-{safe(slug) or 'part'}"
    budget = MAX_LEN - len(ext)
    base = base[:budget].rstrip("-.")
    tokens = knob_summary(values or {}, defaults or {}, order)
    full = "-".join([base, *tokens])
    if len(full) <= budget:
        return full + ext
    name = base
    for i, tok in enumerate(tokens):
        tail = f"-plus{len(tokens) - i - 1}"
        if len(name) + 1 + len(tok) + len(tail) > budget:
            return name + f"-plus{len(tokens) - i}" + ext if len(name) + len(tail) + 1 <= budget else name + ext
        name = f"{name}-{tok}"
    return name + ext  # not reached: the full name did not fit
