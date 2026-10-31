"""Voice / text edits: speech → transcript → parameter edits, clamped to the part's PARAMS ranges.

Live mode: Muse Voice Transcribe, then the `voice_map` stage (Muse Spark) maps the utterance to edits.
Mock mode: a deterministic rule-based mapper handles English and Hindi/Hinglish ("hook ko 1 mm mota karo",
"hole thoda bada", "make it 2 mm longer", "dedh mm", "two millimetres"). Relative words without a number move
holes/clearances by 0.2 mm and everything else by 0.5 mm. Whatever the model proposes, code applies the edits:
unknown parameters are reported, values are clamped to [min, max] and snapped to the step.
"""

from __future__ import annotations

import difflib
import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from partsmith_schemas.verification import ParamSpec

from services.agent import providers
from services.agent.providers import ModelRequest

FINE_STEP_MM = 0.2  # holes, bores, clearances
COARSE_STEP_MM = 0.5  # everything else

EDIT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "edits": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"param": {"type": "string"}, "to": {"type": "number"}, "reason": {"type": "string"}},
                "required": ["param", "to", "reason"],
                "additionalProperties": False,
            },
        },
        "not_understood": {"type": "array", "items": {"type": "string"}},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
    },
    "required": ["edits", "not_understood", "confidence"],
    "additionalProperties": False,
}

DEVELOPER_PROMPT = """You turn a spoken edit request for a 3D-printable part into parameter edits.
The request may mix Hindi and English (Hinglish). Use only parameter names from the PARAMS list.
All lengths are millimetres. When the user says a relative word without a number ("thoda", "a bit", "slightly",
"bada", "chhota") change holes, bores and clearances by 0.2 mm and other dimensions by 0.5 mm.
Return the new absolute value in "to". Put any phrase you cannot map in "not_understood"; never guess a parameter.
Answer with JSON matching the schema."""


@dataclass
class VoiceEdit:
    param: str
    from_value: float
    to: float
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {"param": self.param, "from": self.from_value, "to": self.to, "reason": self.reason}


@dataclass
class VoiceEditResult:
    transcript: str
    edits: list[VoiceEdit] = field(default_factory=list)
    not_understood: list[str] = field(default_factory=list)
    confidence: float = 0.0
    mode: str = "mock"  # mode of the mapping call
    transcript_mode: str = "text"  # "text" when the user typed, else the transcription mode
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Shape used by `POST /jobs/{id}/edit` (minus `bake`, which the API adds)."""
        return {
            "transcript": self.transcript,
            "edits": [e.to_dict() for e in self.edits],
            "not_understood": self.not_understood,
            "confidence": self.confidence,
            "mode": self.mode,
            "transcript_mode": self.transcript_mode,
            "note": self.note,
        }


# --------------------------------------------------------------------------------------------- vocabulary

_INCREASE = {
    "bigger", "larger", "big", "bada", "badi", "bade", "badhao", "badha", "badhaao", "increase", "more", "zyada",
    "jyada", "longer", "lamba", "lambi", "lambe", "thicker", "mota", "moti", "mote", "wider", "chauda", "chaudi",
    "taller", "uncha", "unchi", "unche", "ooncha", "oonchi", "oonche", "deeper", "gehra", "gehri", "looser", "loose", "dheela", "dheeli", "add", "plus",
    "extra", "raise", "expand", "widen", "lengthen", "thicken", "enlarge", "grow",
}  # fmt: skip
_DECREASE = {
    "smaller", "small", "chhota", "chota", "chhoti", "choti", "chhote", "chote", "kam", "ghatao", "ghata", "reduce",
    "decrease", "less", "shorter", "thinner", "thin", "patla", "patli", "patle", "narrower", "shallower", "tighter",
    "tight", "kasa", "minus", "shrink", "trim", "lower", "remove", "hatao", "fewer",
}  # fmt: skip
# canonical dimension -> trigger words, and the param-name tokens that dimension matches
_DIMENSIONS: dict[str, tuple[set[str], tuple[str, ...]]] = {
    "length": ({"length", "long", "longer", "shorter", "lamba", "lambi", "lambe", "lambai"}, ("length", "len", "long")),
    "thickness": (
        {
            "thick",
            "thicker",
            "thickness",
            "thin",
            "thinner",
            "mota",
            "moti",
            "mote",
            "motai",
            "patla",
            "patli",
            "patle",
        },
        ("thickness", "thick", "wall"),
    ),
    "width": ({"wide", "wider", "width", "narrow", "narrower", "chauda", "chaudi", "chaudai"}, ("width", "wide")),
    "height": (
        {
            "tall",
            "taller",
            "height",
            "high",
            "higher",
            "uncha",
            "unchi",
            "unche",
            "unchai",
            "ooncha",
            "oonchi",
            "oonche",
            "oonchai",
        },
        ("height", "tall", "high"),
    ),
    "depth": ({"deep", "deeper", "depth", "shallower", "gehra", "gehri", "gehrai"}, ("depth", "deep")),
    "diameter": ({"diameter", "dia", "radius"}, ("d", "dia", "diameter", "od", "id")),
    "clearance": (
        {"clearance", "loose", "looser", "tight", "tighter", "dheela", "dheeli", "kasa", "gap", "fit"},
        ("clearance", "gap", "tol", "tolerance", "fit"),
    ),
    "overhang": ({"overhang", "lip", "catch"}, ("overhang", "lip")),
    "angle": ({"angle", "tilt", "kon"}, ("angle", "deg")),
}
_PART_WORDS: dict[str, tuple[str, ...]] = {
    "hole": ("hole", "bore"),
    "holes": ("hole", "bore"),
    "chhed": ("hole", "bore"),
    "ched": ("hole", "bore"),
    "chhid": ("hole", "bore"),
    "surakh": ("hole", "bore"),
    "bore": ("bore", "hole"),
    "screw": ("screw", "hole"),
    "hook": ("hook",),
    "slot": ("slot",),
    "rib": ("rib",),
    "ribs": ("rib",),
    "tab": ("tab",),
    "boss": ("boss",),
    "shaft": ("shaft",),
    "knob": ("knob",),
    "wall": ("wall",),
    "plate": ("plate", "base"),
    "base": ("base", "plate"),
    "arm": ("arm",),
    "leg": ("leg",),
    "pin": ("pin",),
    "teeth": ("tooth", "teeth"),
    "tooth": ("tooth", "teeth"),
    "flange": ("flange",),
    "lip": ("lip",),
    "clip": ("clip",),
}
_FINE_TOKENS = ("hole", "bore", "clearance", "gap", "tol", "fit", "screw", "shaft")
_UNITS = {"mm": 1.0, "millimeter": 1.0, "millimeters": 1.0, "millimetre": 1.0, "millimetres": 1.0, "cm": 10.0}
_UNITS.update({"centimeter": 10.0, "centimeters": 10.0, "centimetre": 10.0, "centimetres": 10.0})
_WORD_NUMBERS = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
    "ten": 10, "eleven": 11, "twelve": 12, "fifteen": 15, "twenty": 20, "half": 0.5, "quarter": 0.25,
    "ek": 1, "do": 2, "teen": 3, "char": 4, "chaar": 4, "paanch": 5, "panch": 5, "chhe": 6, "chhah": 6, "che": 6,
    "saat": 7, "aath": 8, "nau": 9, "das": 10, "aadha": 0.5, "adha": 0.5, "aadhaa": 0.5, "dedh": 1.5, "derh": 1.5,
    "dhai": 2.5, "dhaai": 2.5, "dhaee": 2.5, "sawa": 1.25, "paune": 0.75,
}  # fmt: skip
_DIGITS = {"zero": "0", "one": "1", "two": "2", "three": "3", "four": "4", "five": "5", "six": "6", "seven": "7"}
_DIGITS.update({"eight": "8", "nine": "9"})
_COUNT_WORDS = {"add", "more", "remove", "count", "number", "extra", "another", "aur", "hatao", "fewer"}
_CLAUSE_SPLIT = re.compile(r"\s*(?:,|;|\band\b|\baur\b|\bthen\b|\bphir\b|\balso\b|\bbhi\b)\s*")


# Shared with the registry's variant mapper (services/registry/parts.py), so "2 mm taller" / "thoda ooncha" mean the
# same thing in a voice edit and in a plain-words variant.
RELATIVE_WORDS: dict[str, tuple[str, int]] = {
    "taller": ("height", 1), "higher": ("height", 1), "uncha": ("height", 1), "unchi": ("height", 1),
    "unche": ("height", 1), "ooncha": ("height", 1), "oonchi": ("height", 1), "oonche": ("height", 1),
    "lower": ("height", -1), "neecha": ("height", -1), "nicha": ("height", -1),
    "longer": ("length", 1), "lamba": ("length", 1), "lambi": ("length", 1), "lambe": ("length", 1),
    "shorter": ("length", -1),
    "wider": ("width", 1), "chauda": ("width", 1), "chaudi": ("width", 1), "chaude": ("width", 1),
    "narrower": ("width", -1),
    "thicker": ("thickness", 1), "mota": ("thickness", 1), "moti": ("thickness", 1), "mote": ("thickness", 1),
    "thinner": ("thickness", -1), "patla": ("thickness", -1), "patli": ("thickness", -1), "patle": ("thickness", -1),
    "deeper": ("depth", 1), "gehra": ("depth", 1), "gehri": ("depth", 1), "shallower": ("depth", -1),
}  # fmt: skip
# When no knob is named after the dimension, these knobs carry it (in order). A flat extruded part's height is its
# thickness; a cylinder's length is its height; a round part's width is its diameter; a part with no thickness knob but
# a height (a spacer, a knob) is as thick as it is high — its template maps the photo's thickness to `height` too.
DIMENSION_FALLBACKS: dict[str, tuple[str, ...]] = {
    "height": ("height", "thickness"),
    "length": ("length", "height"),
    "width": ("width", "diameter", "outer_d", "leaf_width"),
    "thickness": ("thickness", "plate_thickness", "base_thickness", "height"),
    "depth": ("depth", "bore_depth"),
    "diameter": ("diameter", "outer_d"),
}


def dimension_param(dim: str, params: Sequence[ParamSpec]) -> ParamSpec | None:
    """The knob that carries a plain dimension word ("height", "width", ...) on this part, or None."""
    by_name = {p.name: p for p in params if not p.topology}
    for name in DIMENSION_FALLBACKS.get(dim, (dim,)):
        if name in by_name:
            return by_name[name]
    return None


def _tokens(text: str) -> list[str]:
    text = text.lower().replace("ø", " diameter ")
    text = re.sub(r"(\d)\s*(mm|cm)\b", r"\1 \2", text)
    text = re.sub(r"(\d),(\d)", r"\1.\2", text)
    return re.findall(r"\d+(?:\.\d+)?|[a-z]+", text)


def _parse_amount(tokens: list[str]) -> tuple[float | None, int | None]:
    """First quantity in mm and its token index. Word numbers count only before a unit ("do mm", "two millimetres")
    because "do" is also an English verb; digits without a unit are taken as mm."""
    for i, tok in enumerate(tokens):
        nxt = tokens[i + 1] if i + 1 < len(tokens) else ""
        if re.fullmatch(r"\d+(?:\.\d+)?", tok):
            scale = _UNITS.get(nxt, 1.0)
            return float(tok) * scale, i
        if tok in _WORD_NUMBERS or tok == "point":
            value, j = 0.0, i
            if tok != "point":
                value = float(_WORD_NUMBERS[tok])
                j = i + 1
                # "one and a half", "ek aur aadha" / "two point five"
                if tokens[j : j + 3] in (["and", "a", "half"], ["aur", "aadha"]):
                    value += 0.5
                    j += 3 if tokens[j] == "and" else 2
            if j < len(tokens) and tokens[j] == "point":
                digits = ""
                j += 1
                while j < len(tokens) and tokens[j] in _DIGITS:
                    digits += _DIGITS[tokens[j]]
                    j += 1
                if digits:
                    value += float("0." + digits)
            if j < len(tokens) and tokens[j] in _UNITS:
                return value * _UNITS[tokens[j]], i
    return None, None


@dataclass
class _Intent:
    clause: str
    words: set[str]
    parts: set[str]
    dims: set[str]
    direction: int  # +1, -1 or 0
    amount_mm: float | None


def _intent(clause: str) -> _Intent:
    toks = _tokens(clause)
    parts: set[str] = set()
    for t in toks:
        parts.update(_PART_WORDS.get(t, ()))
    dims = {name for name, (words, _) in _DIMENSIONS.items() if any(t in words for t in toks)}
    inc = sum(t in _INCREASE for t in toks)
    dec = sum(t in _DECREASE for t in toks)
    direction = (inc > dec) - (dec > inc)
    amount, _ = _parse_amount(toks)
    return _Intent(clause.strip(), set(toks), parts, dims, direction, amount)


def _param_tokens(p: ParamSpec) -> set[str]:
    words = set(re.split(r"[_\W\d]+", p.name.lower())) | set(re.findall(r"[a-z]+", p.label.lower()))
    return {w for w in words if w}


def _pick(params: Sequence[ParamSpec], it: _Intent) -> tuple[ParamSpec | None, float, str]:
    """Choose the parameter a clause refers to. Returns (param, confidence, why-not when None)."""
    toks = {p.name: _param_tokens(p) for p in params}
    conf = 0.9
    if it.dims:
        dim_tokens = set().union(*(_DIMENSIONS[d][1] for d in it.dims))
        pool = [p for p in params if toks[p.name] & dim_tokens]
        if it.parts:
            both = [p for p in pool if toks[p.name] & it.parts]
            if both:
                pool = both
            elif pool:
                conf = 0.6  # e.g. "hook thicker" with only a global thickness
        if len(pool) > 1:
            generic = [p for p in pool if toks[p.name] <= dim_tokens | {"overall", "total", "mm"}]
            pool = generic if len(generic) == 1 else pool
    elif it.parts:
        pool = [p for p in params if toks[p.name] & it.parts]
        if len(pool) > 1 and it.parts & {"hole", "bore"}:
            sized = [p for p in pool if set(re.split(r"[_\W\d]+", p.name.lower())) & {"d", "dia", "diameter"}]
            pool = sized or pool
        if len(pool) > 1 and it.words & _COUNT_WORDS:
            counts = [p for p in pool if p.topology]
            pool = counts or pool
    else:
        return None, 0.0, "no part or dimension named"
    if it.dims and not it.parts and len(it.dims) == 1 and len(pool) != 1:
        fallback = dimension_param(next(iter(it.dims)), params)
        if fallback is not None:
            return fallback, 0.75, ""
    if not pool:
        return None, 0.0, "no matching parameter"
    if len(pool) > 1:
        return None, 0.0, "ambiguous: " + ", ".join(p.name for p in pool[:4])
    return pool[0], conf, ""


def _fine(p: ParamSpec) -> bool:
    return bool(_param_tokens(p) & set(_FINE_TOKENS)) or any(t in p.name.lower() for t in ("hole", "clear", "bore"))


def snap_clamp(value: float, spec: ParamSpec) -> tuple[float, bool]:
    """Clamp to [min, max] and snap to `step` (relative to min). Returns (value, clamped?)."""
    clamped = min(max(value, spec.min), spec.max)
    if spec.step > 0:
        steps = round((clamped - spec.min) / spec.step)
        clamped = min(max(spec.min + steps * spec.step, spec.min), spec.max)
    decimals = max(0, -math.floor(math.log10(spec.step))) + 1 if spec.step > 0 else 4
    return round(clamped, min(decimals, 6)), not spec.min <= value <= spec.max


def map_utterance(
    text: str, params: Sequence[ParamSpec], values: Mapping[str, float]
) -> tuple[list[dict[str, Any]], list[str], float]:
    """Deterministic mapper. Returns raw edits `[{"param","to","reason"}]`, not_understood, confidence."""
    edits: list[dict[str, Any]] = []
    missed: list[str] = []
    confs: list[float] = []
    previous: ParamSpec | None = None
    current = {p.name: float(values.get(p.name, p.default)) for p in params}
    for clause in (c for c in _CLAUSE_SPLIT.split(text) if c and c.strip()):
        it = _intent(clause)
        if not it.parts and not it.dims and it.direction == 0 and it.amount_mm is None:
            continue  # filler ("please", "theek hai")
        if it.parts or it.dims:
            target, conf, why = _pick(params, it)
        elif previous is not None and (it.direction or it.amount_mm is not None):
            target, conf, why = previous, 0.6, ""  # "... nahi, thoda chhota" refers back to the last parameter
        else:
            target, conf, why = None, 0.0, "which dimension?"
        if target is None:
            missed.append(f"{it.clause} ({why})")
            continue
        base = current[target.name]
        if it.direction:
            delta = it.amount_mm if it.amount_mm is not None else (FINE_STEP_MM if _fine(target) else COARSE_STEP_MM)
            if target.topology:
                delta = max(1.0, round(it.amount_mm or 1.0))
            to = base + it.direction * delta
            if it.amount_mm is None:
                conf -= 0.1
        elif it.amount_mm is not None:
            to = it.amount_mm
        else:
            missed.append(it.clause)
            continue
        edits.append({"param": target.name, "to": to, "reason": f'"{it.clause}"'})
        current[target.name] = to
        previous = target
        confs.append(conf)
    if not edits and not missed and text.strip():
        missed.append(f"{text.strip()} (no parameter edit found)")
    confidence = round(sum(confs) / len(confs), 2) if confs else 0.0
    if missed and confs:
        confidence = round(confidence * 0.8, 2)
    return edits, missed, confidence


def apply_edits(
    raw: Sequence[Mapping[str, Any]], params: Sequence[ParamSpec], values: Mapping[str, float]
) -> tuple[list[VoiceEdit], list[str]]:
    """The guard: unknown params → not_understood (with closest names); values clamped and snapped to PARAMS."""
    specs = {p.name: p for p in params}
    current = {p.name: float(values.get(p.name, p.default)) for p in params}
    out: list[VoiceEdit] = []
    rejected: list[str] = []
    for e in raw:
        name = str(e.get("param", ""))
        spec = specs.get(name)
        if spec is None:
            close = difflib.get_close_matches(name, list(specs), n=3)
            rejected.append(f"unknown parameter {name!r}" + (f" (closest: {', '.join(close)})" if close else ""))
            continue
        try:
            wanted = float(e.get("to"))  # type: ignore[arg-type]
        except (TypeError, ValueError):
            rejected.append(f"{name}: no numeric target")
            continue
        value, clamped = snap_clamp(wanted, spec)
        reason = str(e.get("reason", "")).strip()
        if clamped:
            reason += f" (clamped to {spec.min:g}–{spec.max:g} {spec.unit}, step {spec.step:g})"
        if math.isclose(value, current[name]):
            rejected.append(f"{name}: already {value:g} {spec.unit}".rstrip() + (" (limit)" if clamped else ""))
            continue
        out.append(VoiceEdit(param=name, from_value=current[name], to=value, reason=reason.strip()))
        current[name] = value
    return out, rejected


def _mock_handler(req: ModelRequest) -> dict[str, Any]:
    ctx = req.mock_context
    params = [ParamSpec.model_validate(p) for p in ctx.get("params", [])]
    edits, missed, confidence = map_utterance(str(ctx.get("transcript", "")), params, ctx.get("values", {}))
    return {"edits": edits, "not_understood": missed, "confidence": confidence}


def _params_table(params: Sequence[ParamSpec], values: Mapping[str, float]) -> str:
    rows = [
        f"- {p.name} = {float(values.get(p.name, p.default)):g} {p.unit} (range {p.min:g}..{p.max:g}, step {p.step:g})"
        + (f" — {p.label}" if p.label else "")
        for p in params
    ]
    return "\n".join(rows)


def transcribe_and_map(
    source: bytes | str,
    params: Sequence[ParamSpec],
    values: Mapping[str, float] | None = None,
    *,
    mime: str = "audio/wav",
    language_hint: str | None = "hinglish",
    part_title: str = "",
) -> VoiceEditResult:
    """Audio bytes (or typed text) → clamped parameter edits for the given PARAMS."""
    values = dict(values or {})
    if isinstance(source, bytes):
        t = providers.transcribe(source, mime, language_hint)
        transcript, transcript_mode, note = t.text, str(t.mode), t.note
    else:
        transcript, transcript_mode, note = source.strip(), "text", ""
    if not transcript:
        return VoiceEditResult(transcript="", transcript_mode=transcript_mode, note=note or "empty transcript")
    user = f"Part: {part_title or 'unnamed'}\nPARAMS:\n{_params_table(params, values)}\n\nRequest: {transcript}"
    req = ModelRequest(
        messages=[{"role": "system", "content": DEVELOPER_PROMPT}, {"role": "user", "content": user}],
        json_schema=EDIT_SCHEMA,
        schema_name="voice_edit",
        temperature=0.0,
        mock_context={"transcript": transcript, "params": [p.model_dump() for p in params], "values": values},
    )
    providers.register_mock("voice_map", _mock_handler, replace=False)  # keeps a mock the orchestrator installed
    out = providers.complete("voice_map", req)
    data = out.json or {}
    edits, rejected = apply_edits(data.get("edits", []), params, values)
    missed = [str(x) for x in data.get("not_understood", [])] + rejected
    confidence = float(data.get("confidence", 0.0)) if edits else 0.0
    return VoiceEditResult(
        transcript=transcript,
        edits=edits,
        not_understood=missed,
        confidence=round(min(max(confidence, 0.0), 1.0), 2),
        mode=str(out.mode),
        transcript_mode=transcript_mode,
        note=note,
    )
