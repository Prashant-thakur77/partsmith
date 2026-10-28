"""User-stated dimensions the photo cannot show: the original length of a part whose break reaches an end.

A snapped end shortens the part, and no mirror image can restore a length that is missing from both sides of the
photo. The user knows it (a ruler on the matching intact part, or the box), so the fix job takes it from the user's
own words, never from a model:

* up front, in the intent text ("it was 51 mm long", "about 5.1 cm long", "original length 51mm") — parsed by the
  unit-aware patterns below;
* as the answer to one question when the job finds the break reaches an end ("51", "51 mm", "5.1 cm", "skip");
* with a tapped broken edge, as the missing piece only: the photo gives the length up to the tap, the user adds
  how much is gone beyond it.

A stated value carries the user's uncertainty: a ruler reading is +/- ``RULER_SIGMA_MM``, a hedged one ("about",
"around", "roughly", "~") +/- ``HEDGED_SIGMA_MM``, an explicit "+/- x mm" wins. It is ``Source.user_stated`` and the
verifier treats it as stated, not observed (see ``services/verifier/verify.py``). Pure functions, no IO.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Literal

RULER_SIGMA_MM = 0.5  # a reading off a ruler or tape: half a millimetre either way
HEDGED_SIGMA_MM = 1.0  # "about 51 mm": the user says it is approximate
TAP_SIGMA_MM = 0.5  # a fingertip tap on the broken edge in a phone photo, not an edge fit
SHORTER_SLACK_MM = 1.0  # a stated length may undercut the broken piece by this much (plus its sigma), no more

_NUM = r"(\d+(?:[.,]\d+)?)"
_UNIT = r"(mm|millimet(?:er|re)s?|cm|centimet(?:er|re)s?|inch(?:es)?|in\b|\")"
_HEDGE = r"(about|around|roughly|approx(?:imately|\.)?|nearly|almost|maybe|~|ca\.?)"
_PM = rf"(?:\s*(?:\+/-|±|\+-|plus or minus)\s*{_NUM}\s*{_UNIT}?)?"
# "51 mm long", "about 5.1 cm long", "51mm in length"
_LONG = re.compile(rf"(?:{_HEDGE}\s*)?{_NUM}\s*{_UNIT}{_PM}\s+(?:long\b|in length\b)", re.I)
# "length was 51 mm", "original length: about 51 mm", "it was 51 mm from end to end"
_LENGTH = re.compile(rf"\blength\b(?:\s+(?:was|is|of|=|:))?\s*:?\s*(?:{_HEDGE}\s*)?{_NUM}\s*{_UNIT}{_PM}", re.I)
_SKIP = re.compile(r"^\s*(skip|no|none|n/?a|don'?t know|do not know|not sure|unknown|pass|-)?\s*[.!]?\s*$", re.I)
_ANSWER = re.compile(rf"^\s*(?:{_HEDGE}\s*)?{_NUM}\s*{_UNIT}?{_PM}\s*(?:long)?\s*[.!]?\s*$", re.I)


@dataclass(frozen=True)
class StatedValue:
    """A length the user stated, in mm, with the uncertainty their words carry."""

    value_mm: float
    sigma_mm: float
    how: str  # plain words: where it came from ("intent: 'it was 51 mm long'", "answer: '51'")
    hedged: bool = False


def _num(s: str) -> float:
    return float(s.replace(",", "."))


def _unit(u: str | None) -> float:
    """mm per unit; no unit means millimetres."""
    key = (u or "mm").lower()
    if key.startswith(("cm", "centimet")):
        return 10.0
    if key.startswith(("in", '"')):
        return 25.4
    return 1.0


def _sigma(hedge: str | None, pm: str | None, pm_unit: str | None, unit_f: float) -> tuple[float, bool]:
    if pm:
        return max(_num(pm) * (_unit(pm_unit) if pm_unit else unit_f), 0.05), bool(hedge)
    if hedge:
        return HEDGED_SIGMA_MM, True
    return RULER_SIGMA_MM, False


def parse_intent_length(text: str | None) -> StatedValue | None:
    """The original length the user gave in their own words, or None. Only phrases that say it is a length count
    ("51 mm long", "length 51 mm"); a bare "5 mm" (a thickness, a hole) never does."""
    if not text:
        return None
    for rx, groups in ((_LONG, (1, 2, 3, 4, 5)), (_LENGTH, (1, 2, 3, 4, 5))):
        m = rx.search(text)
        if m is None:
            continue
        hedge, num, unit, pm, pm_unit = (m.group(i) for i in groups)
        f = _unit(unit)
        value = _num(num) * f
        if not math.isfinite(value) or value <= 0:
            continue
        sigma, hedged = _sigma(hedge, pm, pm_unit, f)
        return StatedValue(round(value, 3), round(sigma, 3), f"intent: {m.group(0).strip()!r}", hedged)
    return None


def parse_answer_length(value: str | float | int | None) -> StatedValue | Literal["skip"] | None:
    """An answer to the length question: a number (mm unless a unit is given), "skip" (or an empty / "don't know"
    answer), or None when it cannot be read (treated as skip by the caller, with a log line)."""
    if value is None:
        return "skip"
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        v = float(value)
        if not math.isfinite(v) or v <= 0:
            return None
        return StatedValue(round(v, 3), RULER_SIGMA_MM, f"answer: {v:g} mm")
    text = str(value)
    if _SKIP.match(text):
        return "skip"
    m = _ANSWER.match(text)
    if m is None:
        return None
    hedge, num, unit, pm, pm_unit = m.groups()
    f = _unit(unit)
    v = _num(num) * f
    if not math.isfinite(v) or v <= 0:
        return None
    sigma, hedged = _sigma(hedge, pm, pm_unit, f)
    return StatedValue(round(v, 3), round(sigma, 3), f"answer: {text.strip()!r}", hedged)


def check_stated_length(
    value_mm: float, sigma_mm: float, *, knob_min: float, knob_max: float, broken_length_mm: float | None
) -> str | None:
    """Plain-words reason to refuse a stated length, or None when it is plausible: it must lie in the template knob's
    range, and it cannot be clearly shorter than the broken piece the photo shows."""
    if not knob_min <= value_mm <= knob_max:
        return (
            f"{value_mm:g} mm is outside what this part's template can make ({knob_min:g}–{knob_max:g} mm), so it "
            "was not used"
        )
    if broken_length_mm is not None and value_mm < broken_length_mm - SHORTER_SLACK_MM - sigma_mm:
        return (
            f"{value_mm:g} mm is shorter than the broken piece itself ({broken_length_mm:.1f} mm in the photo), so "
            "it was not used"
        )
    return None


def with_tap(to_edge_mm: float, missing: StatedValue) -> StatedValue:
    """Length = the photo's length up to the tapped broken edge + the missing piece the user stated."""
    return StatedValue(
        round(to_edge_mm + missing.value_mm, 3),
        round(math.hypot(missing.sigma_mm, TAP_SIGMA_MM), 3),
        f"{to_edge_mm:.1f} mm measured up to the tapped broken edge + {missing.how}",
        missing.hedged,
    )
