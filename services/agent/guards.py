"""Guards between model proposals and the geometry (PLAN §6.6). Pure functions, no IO.

The fixer and the voice editor propose parameter edits; these checks decide what is applied:

* unknown parameters are rejected with the closest valid names;
* targets are clamped to the PARAMS range and snapped to the step (topology knobs move by at most one per round);
* a single round may move a length by at most `max_delta_mm` (20 % of the current value, at least 0.5 mm, at most 2 mm),
  so one bad proposal cannot throw away a model that nearly fits;
* edits that scale every outline dimension by the same factor are refused: rescaling the whole part to force a fit
  hides the real error (change the knob that is actually wrong).
"""

from __future__ import annotations

import difflib
import math
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from partsmith_schemas.verification import ParamSpec

MAX_REL_DELTA = 0.20
MAX_ABS_DELTA_MM = 2.0
MIN_DELTA_MM = 0.5
MAX_DELTA_DEG = 10.0
MAX_TOPOLOGY_STEP = 1
MAX_BACKED_DELTA_MM = 10.0  # an edit backed by its own measured residual may move by up to that residual
RESCALE_MIN_PARAMS = 2
RESCALE_REL_TOL = 0.01  # factors within 1 % of each other count as "the same scale"
RESCALE_MIN_CHANGE = 0.01  # ... and they must actually change the size by more than 1 %
OUTLINE_KEYS = ("length", "width")  # MEASURE_MAP keys that describe the outline's size


@dataclass
class GuardedEdit:
    param: str
    from_value: float
    to: float
    reason: str
    proposed: float
    limited: bool = False  # the proposal was clamped, snapped or capped

    def to_dict(self) -> dict[str, Any]:
        return {"param": self.param, "from": self.from_value, "to": self.to, "reason": self.reason}


@dataclass
class GuardResult:
    applied: list[GuardedEdit] = field(default_factory=list)
    rejected: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def values(self, current: Mapping[str, float]) -> dict[str, float]:
        out = dict(current)
        for e in self.applied:
            out[e.param] = e.to
        return out


def closest_names(name: str, names: Iterable[str], n: int = 3) -> list[str]:
    return difflib.get_close_matches(name, list(names), n=n, cutoff=0.4)


def max_delta(spec: ParamSpec, current: float) -> float:
    """Largest change allowed for one parameter in one fix round."""
    if spec.topology:
        return float(MAX_TOPOLOGY_STEP)
    if spec.unit == "deg":
        return MAX_DELTA_DEG
    if spec.unit == "":
        return float(max(MAX_REL_DELTA * abs(current), spec.step, 0.05 * (spec.max - spec.min)))
    if spec.min < 0:  # an offset, not a size: "20 % of the current value" means nothing around zero
        return float(max(MAX_ABS_DELTA_MM, 0.25 * (spec.max - spec.min)))
    return float(min(MAX_ABS_DELTA_MM, max(MAX_REL_DELTA * abs(current), MIN_DELTA_MM)))


def snap(value: float, spec: ParamSpec) -> float:
    """Clamp to [min, max] and snap to the step grid (topology knobs become integers)."""
    v = min(max(value, spec.min), spec.max)
    if spec.topology:
        return float(round(v))
    if spec.step > 0:
        v = spec.min + round((v - spec.min) / spec.step) * spec.step
        v = min(max(v, spec.min), spec.max)
    decimals = max(0, -math.floor(math.log10(spec.step))) + 1 if spec.step > 0 else 4
    return float(round(v, decimals))


def is_rescale(
    edits: Sequence[Mapping[str, Any]],
    current: Mapping[str, float],
    outline_params: Iterable[str],
    residual_deltas: Mapping[str, float] | None = None,
) -> bool:
    """True when the edits scale every outline-size parameter by (nearly) the same factor without each change being
    backed by that parameter's own measured residual (`residual_deltas`: param -> model − measured, mm)."""
    names = [p for p in dict.fromkeys(outline_params) if p in current]
    if len(names) < RESCALE_MIN_PARAMS:
        return False
    targets: dict[str, float] = {}
    for e in edits:
        try:
            targets[str(e.get("param"))] = float(e.get("to"))  # type: ignore[arg-type]
        except (TypeError, ValueError):
            continue
    if not all(n in targets for n in names):
        return False
    factors = [targets[n] / current[n] for n in names if current[n] != 0]
    if len(factors) < RESCALE_MIN_PARAMS:
        return False
    mean = sum(factors) / len(factors)
    same = max(factors) - min(factors) <= RESCALE_REL_TOL * mean
    if not (same and abs(mean - 1.0) > RESCALE_MIN_CHANGE):
        return False
    deltas = residual_deltas or {}

    def backed(n: str) -> bool:
        d = deltas.get(n)
        move = targets[n] - current[n]
        return d is not None and move * d < 0 and abs(move) <= abs(d) * 1.1 + 0.05

    return not all(backed(n) for n in names)


def guard_edits(
    edits: Sequence[Mapping[str, Any]],
    specs: Sequence[ParamSpec],
    current: Mapping[str, float],
    *,
    outline_params: Iterable[str] = (),
    cap_deltas: bool = True,
    residual_deltas: Mapping[str, float] | None = None,
) -> GuardResult:
    """Apply the guards to raw `{"param", "to", "reason"}` proposals. `current` holds the values in force now."""
    by_name = {s.name: s for s in specs}
    res = GuardResult()
    if is_rescale(edits, current, outline_params, residual_deltas):
        res.rejected.append(
            "refused: the edits scale the whole outline by one factor — never rescale to force a fit; change the "
            "parameter that is actually wrong"
        )
        return res
    seen: set[str] = set()
    for e in edits:
        name = str(e.get("param", "")).strip()
        spec = by_name.get(name)
        if spec is None:
            close = closest_names(name, by_name)
            res.rejected.append(f"unknown parameter {name!r}" + (f" (closest: {', '.join(close)})" if close else ""))
            continue
        if name in seen:
            res.rejected.append(f"{name}: edited twice in one round; kept the first edit")
            continue
        try:
            proposed = float(e.get("to"))  # type: ignore[arg-type]
        except (TypeError, ValueError):
            res.rejected.append(f"{name}: no numeric target")
            continue
        if not math.isfinite(proposed):
            res.rejected.append(f"{name}: target is not a finite number")
            continue
        cur = float(current.get(name, spec.default))
        target = proposed
        notes: list[str] = []
        if cap_deltas:
            lim = max_delta(spec, cur)
            d = (residual_deltas or {}).get(name)
            if d is not None and (target - cur) * d < 0 and not spec.topology:
                lim = max(lim, min(2 * abs(d), MAX_BACKED_DELTA_MM))
            if abs(target - cur) > lim + 1e-9:
                target = cur + math.copysign(lim, target - cur)
                notes.append(f"capped to a {lim:g}{' ' + spec.unit if spec.unit else ''} change this round")
        value = snap(target, spec)
        if not spec.min <= target <= spec.max:
            notes.append(f"clamped to {spec.min:g}..{spec.max:g} {spec.unit}".rstrip())
        if math.isclose(value, cur, abs_tol=1e-9):
            res.rejected.append(f"{name}: already {cur:g}" + (f" ({'; '.join(notes)})" if notes else ""))
            continue
        seen.add(name)
        reason = str(e.get("reason", "")).strip()
        if notes:
            reason = (reason + " — " if reason else "") + "; ".join(notes)
        res.applied.append(
            GuardedEdit(name, cur, value, reason, proposed, limited=bool(notes) or not math.isclose(value, proposed))
        )
    return res


def residual_param(feature_id: str, quantity: str, measure_map: Mapping[str, str]) -> str | None:
    """The PARAMS knob a template says controls a measured quantity (MEASURE_MAP), or None."""
    if feature_id == "outline" and quantity in ("length", "width"):
        return measure_map.get(quantity)
    if feature_id == "plate" and quantity == "thickness":
        return measure_map.get("thickness")
    if feature_id == "side" and quantity == "thickness":
        return measure_map.get("side.thickness") or measure_map.get("height")
    if quantity == "diameter":
        return measure_map.get(f"{feature_id}.diameter") or measure_map.get("hole_1.diameter")
    return None


_FENCE = re.compile(r"```(?:python|py)?[ \t]*\n(.*?)```", re.S)


def extract_code(text: str) -> str:
    """The python program in a model reply: the longest fenced block, else the whole reply."""
    blocks = _FENCE.findall(text or "")
    code = max(blocks, key=len) if blocks else (text or "")
    return code.strip() + "\n"


FLEXIBLE = "flexible or elastomer part"
ORGANIC = "organic or free-form object"

# Refused part classes (PLAN §13). The understand model classifies too; this list is the code-side backstop.
REFUSED_PATTERNS: dict[str, tuple[str, ...]] = {
    "firearm or weapon component": (
        r"\bgun\b",
        r"\bguns\b",
        r"firearm",
        r"pistol",
        r"rifle",
        r"shotgun",
        r"\btrigger\b",
        r"magazine (?:body|follower|spring)",
        r"silencer",
        r"suppressor",
        r"\bammo\b",
        r"ammunition",
        r"bullet",
        r"\bweapon",
        r"knuckle ?duster",
        r"brass knuckles",
        r"bandook",
        r"katta",
    ),
    "medical device": (
        r"medical",
        r"implant",
        r"prosthe",
        r"catheter",
        r"syringe",
        r"inhaler",
        r"\bstent\b",
        r"surgical",
        r"orthopedic",
        r"orthopaedic",
        r"hearing aid",
        r"pacemaker",
        r"\bsplint\b",
    ),
    "child-safety-critical part": (
        r"car ?seat",
        r"child seat",
        r"baby gate",
        r"\bcrib\b",
        r"\bcot\b",
        r"pacifier",
        r"stroller brake",
    ),
    "vehicle safety system": (
        r"seat ?belt",
        r"airbag",
        r"brake",
        r"steering",
        r"\babs\b sensor",
        r"helmet",
    ),
    "load-bearing for people": (
        r"climbing",
        r"harness",
        r"carabiner",
        r"ladder",
        r"scaffold",
        r"load[- ]bearing",
        r"chair leg",
        r"stair",
        r"railing",
        r"\bhoist\b",
    ),
    FLEXIBLE: (
        r"\brubber\b",
        r"\bsilicone\b",
        r"\bgaskets?\b",
        r"\bo-?rings?\b",
        r"\b(?:rubber|silicone|door|oil|shaft|lip|fridge|refrigerator) seals?\b",
        r"elastomer",
        r"\bsqueegee\b",
        r"\bbellows\b",
    ),
    ORGANIC: (
        r"figurine",
        r"\bstatue",
        r"sculpture",
        r"\bclay\b",
        r"\bdoll\b",
        r"action figure",
        r"toy figure",
        r"\bfigure of\b",
    ),
}

# Plain reasons per class (the safety classes share one).
REFUSAL_REASONS: dict[str, str] = {
    FLEXIBLE: "This looks like a soft, flexible part (rubber, silicone, a gasket or seal). A rigid FDM print would not seal "
    "or flex like the original, and PartSmith only verifies rigid shapes — please buy the right gasket or seal, or print it "
    "yourself in TPU at your own risk.",
    ORGANIC: "This is a free-form object (a figurine, statue or sculpture), not a functional part with dimensions to "
    "measure. PartSmith rebuilds parametric replacement parts; it does not copy free-form shapes.",
}


def refused_class(*texts: str) -> str | None:
    """Name of the refused class mentioned in any of `texts`, or None."""
    blob = " ".join(t for t in texts if t).lower()
    if not blob:
        return None
    for cls, patterns in REFUSED_PATTERNS.items():
        for pat in patterns:
            if re.search(pat, blob):
                return cls
    return None


def refusal_message(cls: str) -> str:
    if cls in REFUSAL_REASONS:
        return REFUSAL_REASONS[cls]
    return (
        f"PartSmith does not make replacement parts in this class ({cls}). A printed copy could fail without warning "
        "where people's safety depends on it — please use an original part from the manufacturer."
    )
