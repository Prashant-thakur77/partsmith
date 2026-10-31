"""Registry operations on parts: bake, plain-words variants, paper templates, matching parts, cards and facts.

Everything numeric is decided by code: a variant request goes to the `variant` model stage, but the guard below maps
unknown parameter names to the closest real one (or reports them), clamps every value to its PARAMS range and refuses
uniform rescaling ("never rescale a part to force a fit — change the right knob").
"""

from __future__ import annotations

import difflib
import json
import math
import re
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

from partsmith_schemas import BakeResult, PartFacts, PartRecord, VariantResult
from partsmith_schemas.verification import ParamSpec

from services.agent import providers
from services.agent.providers import ModelRequest
from services.common import blobs
from services.common.paths import bakes_dir
from services.geom_worker import bake as geom_bake
from services.geom_worker.program import clamp, closest_names, params_sha
from services.geom_worker.sandbox import WarmPool
from services.media.voice import RELATIVE_WORDS, map_utterance, snap_clamp
from services.registry import gate, passport
from services.registry.store import FAMILY_TITLES as FAMILY_TITLES  # re-exported: P.FAMILY_TITLES
from services.registry.store import METRIC_CLEARANCE_MM as METRIC_CLEARANCE_MM  # re-exported
from services.registry.store import Registry, get_registry
from services.verifier.ship import short_reason

API = "/api/v1"
DEFAULT_FORMATS = ("stl", "step", "view")
ALL_FORMATS = geom_bake.FORMATS


# ------------------------------------------------------------------------------------------------- lookup


class PartNotFound(KeyError):
    """No part with this slug. `closest` holds the nearest existing slugs."""

    def __init__(self, slug: str, closest: list[str]) -> None:
        super().__init__(slug)
        self.slug = slug
        self.closest = closest

    def __str__(self) -> str:
        hint = f" (closest: {', '.join(self.closest)})" if self.closest else ""
        return f"no part {self.slug!r}{hint}"


def closest_slugs(slug: str, reg: Registry | None = None, n: int = 3) -> list[str]:
    slugs = (reg or get_registry()).slugs()
    close = difflib.get_close_matches(slug, slugs, n=n, cutoff=0.4)
    if not close:  # token overlap ("wheel" -> "caster-wheel-50")
        toks = set(re.split(r"[-_\s]+", slug.lower())) - {""}
        close = [s for s in slugs if toks & set(s.split("-"))][:n]
    return close


def require_part(slug: str, reg: Registry | None = None) -> PartRecord:
    reg = reg or get_registry()
    part = reg.get_part(slug)
    if part is None:
        raise PartNotFound(slug, closest_slugs(slug, reg))
    return part


# ------------------------------------------------------------------------------------------------- bake


def bake_url(cache_key: str, name: str) -> str:
    return f"{API}/bakes/{cache_key}/{name}"


def bake_file(cache_key: str, name: str) -> Path | None:
    """Path of a baked file, or None. Only hex cache keys and known file names are accepted (no path traversal)."""
    if not re.fullmatch(r"[0-9a-f]{64}", cache_key) or name not in set(geom_bake.FILE_NAMES.values()):
        return None
    p = bakes_dir() / cache_key[:2] / cache_key / name
    return p if p.is_file() else None


def artifact_urls(slug: str) -> dict[str, str]:
    """Stable per-part download URLs (default parameters, baked on first request, cached afterwards)."""
    return {fmt: f"{API}/parts/{slug}/bake?format={fmt}&download=1" for fmt in ALL_FORMATS}


def parse_formats(formats: str | Iterable[str] | None) -> list[str]:
    if formats is None:
        return list(DEFAULT_FORMATS)
    items = [formats] if isinstance(formats, str) else list(formats)
    out: list[str] = []
    for item in items:
        for f in item.split(","):
            f = f.strip().lower()
            f = {"tcv": "view", "threemf": "3mf"}.get(f, f)
            if f and f not in out:
                out.append(f)
    bad = [f for f in out if f not in ALL_FORMATS]
    if bad:
        raise ValueError(f"unknown format(s) {bad}; choose from {list(ALL_FORMATS)}")
    return out or list(DEFAULT_FORMATS)


def bake_output(
    part: PartRecord,
    params: Mapping[str, float] | None = None,
    formats: Iterable[str] = DEFAULT_FORMATS,
    *,
    pool: WarmPool | None = None,
    passport: str | None = None,
) -> geom_bake.BakeOutput:
    """Bake (or fetch from the content-addressed cache). Raises UnknownParamError / BakeError / ValueError.
    `passport` debosses that id where it is safe (off by default; see geom_worker/passport_mark.py)."""
    return geom_bake.bake(part.code, dict(params or {}), list(formats), version=part.version, pool=pool,
                          passport=passport)  # fmt: skip


def bake_part(
    slug: str,
    params: Mapping[str, float] | None = None,
    formats: Iterable[str] = DEFAULT_FORMATS,
    *,
    pool: WarmPool | None = None,
    reg: Registry | None = None,
) -> BakeResult:
    """Bake a registry part at `params` (clamped; `clamped` reports what changed). Cache hits cost nothing."""
    part = require_part(slug, reg)
    out = bake_output(part, params, formats, pool=pool)
    return out.to_bake_result(slug, lambda fmt, p: bake_url(out.cache_key, p.name))


# ------------------------------------------------------------------------------------------------- variant

VARIANT_SCHEMA: dict[str, Any] = {
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
        "not_applied": {"type": "array", "items": {"type": "string"}},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
    },
    "required": ["edits", "not_applied", "confidence"],
    "additionalProperties": False,
}

# ISO 273 "medium" clearance holes for metric screws (mm)
RESCALE_WORDS = {"scale", "rescale", "factor", "scale_factor", "size", "uniform_scale"}
_WORD_COUNTS = {
    "no": 0,
    "zero": 0,
    "one": 1,
    "a": 1,
    "single": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "twelve": 12,
}
_COUNT_NOUNS: dict[str, tuple[str, ...]] = {
    "rib": ("rib", "gusset"),
    "gusset": ("gusset", "rib"),
    "hole": ("hole",),
    "spoke": ("spoke",),
    "grip": ("grip",),
    "flute": ("grip",),
    "ridge": ("grip",),
    "knuckle": ("knuckle",),
    "channel": ("channel",),
    "slot": ("channel",),
    "flat": ("flat",),
    "groove": ("groove",),
    "tongue": ("tongue",),
}
_FIT_NOUNS: dict[str, tuple[str, ...]] = {
    "cable": ("cable",),
    "wire": ("cable",),
    "cord": ("cable",),
    "shaft": ("bore", "shaft"),
    "axle": ("bore",),
    "pin": ("pin",),
    "dowel": ("pin", "bore"),
    "screw": ("hole", "pivot"),
    "bolt": ("hole", "pivot"),
    "rod": ("bore", "pin", "cable", "reach"),
    "pipe": ("cable", "bore", "reach"),
    "tube": ("cable", "bore", "reach"),
    "rail": ("reach", "arm_height", "gap"),
    "panel": ("arm_height", "reach", "gap"),
    "shelf": ("arm_height", "reach", "gap"),
    "board": ("arm_height", "reach", "gap"),
    "door": ("arm_height", "reach", "step_depth"),
    "towel": ("reach",),
}
_CLAUSE = re.compile(r"\s*(?:,|;|\band\b|\bwith\b|\bplus\b)\s*", re.I)


def _tokens(p: ParamSpec) -> set[str]:
    return {w for w in re.split(r"[_\W\d]+", p.name.lower()) + re.findall(r"[a-z]+", p.label.lower()) if w}


def _singular(word: str) -> str:
    return word[:-1] if word.endswith("s") and not word.endswith("ss") else word


def _hole_param(specs: Sequence[ParamSpec]) -> ParamSpec | None:
    """The screw-hole diameter knob: hole_d, then pivot_d, then a bore."""
    for key in ("hole", "pivot", "bore"):
        for p in specs:
            if key in p.name and p.unit == "mm" and not p.topology:
                return p
    return None


def _count_param(specs: Sequence[ParamSpec], noun: str) -> ParamSpec | None:
    keys = _COUNT_NOUNS.get(noun, (noun,))
    for key in keys:
        for p in specs:
            if p.topology and key in p.name:
                return p
    return None


def _fit_param(specs: Sequence[ParamSpec], noun: str) -> ParamSpec | None:
    for key in _FIT_NOUNS.get(noun, (noun,)):
        for p in specs:
            if not p.topology and p.unit == "mm" and (key in p.name or key in _tokens(p)):
                return p
    return None


def _num(tok: str) -> float | None:
    if re.fullmatch(r"\d+(?:\.\d+)?", tok):
        return float(tok)
    v = _WORD_COUNTS.get(tok)
    return float(v) if v is not None else None


def map_variant(
    want: str, specs: Sequence[ParamSpec], values: Mapping[str, float]
) -> tuple[list[dict[str, Any]], list[str], float]:
    """Deterministic plain-English mapper (the `variant` mock): "M4 hole", "2 mm taller", "for a 25 mm rail",
    "3 ribs", "no grip flutes", "6 mm shaft". Returns raw edits, not-applied phrases and a confidence."""
    edits: list[dict[str, Any]] = []
    missed: list[str] = []
    confs: list[float] = []
    current = {p.name: float(values.get(p.name, p.default)) for p in specs}
    for clause in (c.strip() for c in _CLAUSE.split(want) if c and c.strip()):
        low = clause.lower()
        toks = re.findall(r"\d+(?:\.\d+)?|[a-z]+", low)
        if re.search(r"\b(scale|rescale|bigger overall|smaller overall|resize)\b", low):
            missed.append(f"{clause} (uniform rescaling is refused: name the dimension to change)")
            continue
        m = re.search(r"\bm\s?(\d+(?:\.\d)?)\b", low)
        if m and m.group(1) in METRIC_CLEARANCE_MM:
            p = _hole_param(specs)
            if p is None:
                missed.append(f"{clause} (this part has no screw-hole knob)")
                continue
            d = METRIC_CLEARANCE_MM[m.group(1)]
            edits.append({"param": p.name, "to": d, "reason": f"M{m.group(1)} clearance hole (ISO 273 medium, {d} mm)"})
            confs.append(0.9)
            continue
        fit = re.search(
            r"\bfor (?:an? |the |my )?(\d+(?:\.\d+)?)\s*(?:mm\s*)?(?:thick |wide |diameter |dia )?([a-z]+)", low
        )
        if fit:
            noun = _singular(fit.group(2))
            p = _fit_param(specs, noun)
            if p is None:
                missed.append(f"{clause} (no knob matches a {noun})")
                continue
            to = float(fit.group(1))
            edits.append({"param": p.name, "to": to, "reason": f"fits a {to:g} mm {noun} (set to the stated size)"})
            confs.append(0.7)
            continue
        counted = None
        for i, tok in enumerate(toks[:-1]):
            n = _num(tok)
            noun = _singular(toks[i + 1])
            if n is not None and noun in _COUNT_NOUNS:
                counted = (n, noun)
                break
            if (
                n is not None
                and i + 2 < len(toks)
                and _singular(toks[i + 2]) in _COUNT_NOUNS
                and toks[i + 1] in {"grip", "screw", "stiffening", "lightening", "cable", "finger", "mounting"}
            ):
                counted = (n, _singular(toks[i + 2]))
                break
        if counted is not None and not re.search(r"\d\s*mm", low):
            n, noun = counted
            p = _count_param(specs, noun)
            if p is None:
                missed.append(f"{clause} (this part has no {noun} count knob)")
                continue
            edits.append({"param": p.name, "to": n, "reason": f"{int(n)} {noun}{'s' if n != 1 else ''}"})
            confs.append(0.9)
            continue
        exact = _exact_dim_edit(toks, specs, current)
        if exact is not None:
            edits.append(exact)
            current[str(exact["param"])] = float(exact["to"])
            confs.append(0.85)
            continue
        raw, not_understood, conf = map_utterance(clause, specs, current)
        if raw:
            edits.extend(raw)
            confs.append(conf)
            for e in raw:
                current[str(e["param"])] = float(e["to"])
        missed.extend(not_understood)
    confidence = round(sum(confs) / len(confs), 2) if confs else 0.0
    if missed and confs:
        confidence = round(confidence * 0.8, 2)
    return edits, missed, confidence


_FILLER = {
    "make",
    "it",
    "a",
    "an",
    "the",
    "bit",
    "little",
    "slightly",
    "mm",
    "by",
    "please",
    "part",
    "of",
    "to",
    "set",
    "be",
    "more",
    "overall",
    "total",
    "is",
    "at",
    "karo",
    "kar",
    "kardo",
    "thoda",
    "thodi",
    "zara",
    "isko",
    "ise",
    "ko",
    "aur",
}


def _exact_dim_edit(toks: list[str], specs: Sequence[ParamSpec], current: Mapping[str, float]) -> dict[str, Any] | None:
    """ "40 mm diameter", "height 20 mm", "2 mm thicker" when a knob is named exactly after the dimension and the clause
    names nothing else (so "hook thicker" still goes to the part-aware mapper)."""
    names = {p.name: p for p in specs}
    numbers = [float(t) for t in toks if re.fullmatch(r"\d+(?:\.\d+)?", t)]
    words = [t for t in toks if not re.fullmatch(r"\d+(?:\.\d+)?", t) and t not in _FILLER]
    if len(words) != 1 or len(numbers) > 1:
        return None
    w = words[0]
    if w in names and numbers and not names[w].topology:
        return {"param": w, "to": numbers[0], "reason": f"{w} = {numbers[0]:g} mm"}
    if w in RELATIVE_WORDS and RELATIVE_WORDS[w][0] in names:
        name, sign = RELATIVE_WORDS[w]
        step = numbers[0] if numbers else 0.5
        return {"param": name, "to": current[name] + sign * step, "reason": f"{step:g} mm {w}"}
    return None


def _variant_mock(req: ModelRequest) -> dict[str, Any]:
    ctx = req.mock_context
    specs = [ParamSpec.model_validate(p) for p in ctx.get("params", [])]
    edits, missed, confidence = map_variant(str(ctx.get("want", "")), specs, ctx.get("values", {}))
    return {"edits": edits, "not_applied": missed, "confidence": confidence}


def guard_edits(
    raw: Sequence[Mapping[str, Any]], specs: Sequence[ParamSpec], values: Mapping[str, float]
) -> tuple[dict[str, float], list[str], list[str]]:
    """The code side of a variant. Returns (full params, applied descriptions, not-applied reasons).

    Unknown names map to the closest real parameter when the match is clear, else they are reported. Values are clamped
    and snapped to PARAMS. A set of edits that scales three or more mm dimensions by one common factor is refused.
    """
    by_name = {p.name: p for p in specs}
    current = {p.name: float(values.get(p.name, p.default)) for p in specs}
    applied: list[str] = []
    rejected: list[str] = []
    staged: list[tuple[ParamSpec, float, str]] = []
    for e in raw:
        name = str(e.get("param", "")).strip()
        if name.lower() in RESCALE_WORDS:
            rejected.append(f"{name}: uniform rescaling is refused — change the dimension that matters")
            continue
        spec = by_name.get(name)
        note = ""
        if spec is None:
            close = closest_names(name, list(specs), n=1)
            if close and difflib.SequenceMatcher(None, name, close[0]).ratio() >= 0.6:
                spec = by_name[close[0]]
                note = f" (asked for {name!r}, used {spec.name!r})"
            else:
                hint = closest_names(name, list(specs), n=3)
                rejected.append(f"unknown parameter {name!r}" + (f" (closest: {', '.join(hint)})" if hint else ""))
                continue
        try:
            wanted = float(e.get("to"))  # type: ignore[arg-type]
        except (TypeError, ValueError):
            rejected.append(f"{spec.name}: no numeric value")
            continue
        if not math.isfinite(wanted):
            rejected.append(f"{spec.name}: value is not finite")
            continue
        value, was_clamped = snap_clamp(wanted, spec)
        if spec.topology:
            value = float(round(value))
        reason = str(e.get("reason", "")).strip() + note
        if was_clamped:
            reason += f" (clamped to {spec.min:g}–{spec.max:g} {spec.unit})".replace("  ", " ")
        staged.append((spec, value, reason.strip()))

    mm_edits = [(s, v) for s, v, _ in staged if s.unit == "mm" and current[s.name] > 0]
    if len(mm_edits) >= 3:
        r0 = mm_edits[0][1] / current[mm_edits[0][0].name]
        uniform = all(abs(v - current[s.name] * r0) <= max(s.step, 0.01 * abs(v)) for s, v in mm_edits)
        if uniform and abs(r0 - 1) > 0.02:
            rejected.append(f"uniform rescale by {r0:.3g}x refused — never rescale a part to force a fit")
            staged = [(s, v, r) for s, v, r in staged if s.unit != "mm"]

    for spec, value, reason in staged:
        if math.isclose(value, current[spec.name]):
            rejected.append(f"{spec.name}: already {value:g} {spec.unit}".rstrip())
            continue
        unit = f" {spec.unit}" if spec.unit else ""
        applied.append(f"{spec.name}: {current[spec.name]:g} → {value:g}{unit}" + (f" — {reason}" if reason else ""))
        current[spec.name] = value
    full, _ = clamp(current, list(specs))
    return {k: float(v) for k, v in full.items()}, applied, rejected


def _params_table(specs: Sequence[ParamSpec], values: Mapping[str, float]) -> str:
    return "\n".join(
        f"- {p.name}, {float(values.get(p.name, p.default)):g}, {p.min:g}, {p.max:g}, {p.unit or '-'}, {p.label}"
        for p in specs
    )


def variant_for_specs(
    specs: Sequence[ParamSpec], values: Mapping[str, float], want: str, *, title: str = ""
) -> VariantResult:
    """Plain words → parameter values for any PARAMS list (Muse Spark proposes via the `variant` stage, `guard_edits`
    decides). Used by registry variants and by Steer send-backs."""
    from services.agent import prompt_loader

    specs = list(specs)
    values = {p.name: float(values.get(p.name, p.default)) for p in specs}
    want = want.strip()[:500]
    if not want:
        return VariantResult(
            params=dict(values), applied=[], not_applied=["empty request"], confidence=0.0, mode="mock"
        )
    prompt = prompt_loader.load("variant")
    dev, user = prompt.render(want=want, params="\n" + _params_table(specs, values))
    if title:
        user = f"Part: {title}\n{user}"
    req = ModelRequest(
        messages=[{"role": "system", "content": dev}, {"role": "user", "content": user}],
        json_schema=VARIANT_SCHEMA,
        schema_name="variant",
        temperature=0.0,
        mock_context={"want": want, "params": [p.model_dump() for p in specs], "values": values},
    )
    providers.register_mock("variant", _variant_mock, replace=False)
    out = providers.complete("variant", req)
    data = out.json or {}
    params, applied, rejected = guard_edits(data.get("edits", []), specs, values)
    not_applied = [str(x) for x in data.get("not_applied", [])] + rejected
    confidence = float(data.get("confidence", 0.0)) if applied else 0.0
    if not_applied and applied:
        confidence = min(confidence, 0.75)
    return VariantResult(
        params=params,
        applied=applied,
        not_applied=not_applied,
        confidence=round(min(max(confidence, 0.0), 1.0), 2),
        mode=out.mode,
    )


def variant(
    slug: str, want: str, *, base: Mapping[str, float] | None = None, reg: Registry | None = None
) -> VariantResult:
    """Plain words → parameter values for a registry part. `base` overrides the defaults the request starts from."""
    part = require_part(slug, reg)
    return variant_for_specs(part.params, {**part.defaults, **dict(base or {})}, want, title=part.title)


# ------------------------------------------------------------------------------------------------- template PDF


def outline_and_holes(
    code: str, params: Mapping[str, float] | None = None, *, pool: WarmPool | None = None
) -> tuple[list[tuple[float, float]], list[dict[str, Any]], tuple[float, float]]:
    """Top-view silhouette outline and through-holes of a program, in the part frame (mm, Y up), plus (length, width)
    of its min-area rectangle. Holes are the inner contours of the silhouette, so only through-holes appear."""
    from services.geom_worker.sandbox import run_program
    from services.verifier.align import Rigid2D
    from services.verifier.synthetic import synthetic_top_measurement

    res = run_program(code, dict(params or {}), outputs=(), features=False, pool=pool)
    try:
        if not res.ok or res.mesh is None:
            err = res.error.short() if res.error else "no mesh"
            raise geom_bake.BakeError(res.error) if res.error else RuntimeError(err)
        meas, _ = synthetic_top_measurement(res, pose=Rigid2D(), px_per_mm=20.0, with_thickness=False)
    finally:
        res.cleanup()
    holes = [
        {"center_mm": [h.center_mm[0], h.center_mm[1]], "diameter_mm": round(h.diameter.value, 2)} for h in meas.holes
    ]
    return [(float(x), float(y)) for x, y in meas.outline_mm], holes, (meas.length.value, meas.width.value)


def template_pdf(
    slug: str, params: Mapping[str, float] | None = None, *, reg: Registry | None = None, pool: WarmPool | None = None
) -> bytes:
    """1:1 paper template of the part's top silhouette: outline, through-holes and overall dimensions."""
    from tools.mat.template_pdf import template_pdf as render_pdf

    part = require_part(slug, reg)
    specs = list(part.params)
    values, _ = clamp(dict(params or {}), specs)
    outline, holes, _ = outline_and_holes(part.code, values, pool=pool)
    xs = [p[0] for p in outline]
    ys = [p[1] for p in outline]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    dims = [
        {"label": "X", "from_mm": [x0, y0 - 6.0], "to_mm": [x1, y0 - 6.0], "value_mm": round(x1 - x0, 2)},
        {"label": "Y", "from_mm": [x0 - 6.0, y0], "to_mm": [x0 - 6.0, y1], "value_mm": round(y1 - y0, 2)},
    ]
    changed = {k: v for k, v in values.items() if not math.isclose(float(v), float(part.defaults.get(k, v)))}
    notes = [
        "Print at 100 % (no 'fit to page'); the 50 mm ruler must measure 50 mm.",
        "Silhouette from the part program (top view); only through-holes show.",
    ]
    if changed:
        notes.append("Params: " + ", ".join(f"{k}={float(v):g}" for k, v in sorted(changed.items())))
    status = part.verification.status if part.verification else part.status
    return render_pdf(outline, holes, dims, title=f"{part.title} ({slug}) — {status}", notes=notes)


# ------------------------------------------------------------------------------------------------- matching

_INTERFACE_KEYS = ("hole", "bore", "pin", "pivot", "cable", "shaft")


def interface_dims(part: PartRecord) -> dict[str, float]:
    """Mating-interface diameters (screw holes, bores, pins, cables) at the part's defaults."""
    return {
        p.name: float(part.defaults.get(p.name, p.default))
        for p in part.params
        if p.unit == "mm" and not p.topology and any(k in p.name for k in _INTERFACE_KEYS)
    }


def matching(slug: str, *, limit: int = 12, reg: Registry | None = None) -> list[tuple[PartRecord, str]]:
    """Parts that go with this one: declared mating parts, then shared interface dimensions (same screw hole, pin or
    bore within 0.05 mm), then the same family."""
    reg = reg or get_registry()
    part = require_part(slug, reg)
    mine = interface_dims(part)
    others, _ = reg.search("", limit=10_000, sort="title", role="part")
    out: list[tuple[PartRecord, str]] = []
    seen = {slug}
    for s in part.mating:
        other = reg.get_part(s)
        if other is not None and s not in seen:
            out.append((other, "declared mating part"))
            seen.add(s)
    for other in others:
        if other.slug in seen:
            continue
        theirs = interface_dims(other)
        shared = [(a, b, v) for a, v in mine.items() for b, w in theirs.items() if abs(v - w) <= 0.05]
        if shared:
            a, b, v = shared[0]
            out.append((other, f"shares a {v:g} mm interface ({a} = {b})"))
            seen.add(other.slug)
    for other in others:
        if other.slug not in seen and other.family == part.family:
            out.append((other, f"same family ({part.family.value})"))
            seen.add(other.slug)
    return out[:limit]


# ------------------------------------------------------------------------------------------------- cards, facts, thumbs


def thumbnail_urls(slug: str, reg: Registry | None = None) -> tuple[str, str]:
    """(1x, 2x) thumbnail URLs: stored blobs when rendered, else the lazy render route."""
    t = (reg or get_registry()).thumbnail(slug)
    if t:
        return blobs.url(t["key_1x"]), blobs.url(t["key_2x"])
    return f"{API}/parts/{slug}/thumbnail.png", f"{API}/parts/{slug}/thumbnail.png?scale=2"


def part_card(
    part: PartRecord, reg: Registry | None = None, thumbs: Mapping[str, Mapping[str, Any]] | None = None
) -> dict[str, Any]:
    """`PartCard` (docs/API.md)."""
    v = part.verification
    if thumbs is not None:
        t = thumbs.get(part.slug)
        thumb = blobs.url(t["key_1x"]) if t else f"{API}/parts/{part.slug}/thumbnail.png"
        thumb2 = blobs.url(t["key_2x"]) if t else f"{API}/parts/{part.slug}/thumbnail.png?scale=2"
    else:
        thumb, thumb2 = thumbnail_urls(part.slug, reg)
    return {
        "slug": part.slug,
        "title": part.title,
        "family": part.family.value,
        "status": part.status,
        "origin": part.provenance.origin.value,
        "verified": bool(v and v.verified),
        "max_error_mm": v.max_error_mm if v else None,
        "status_reason": short_reason(v),
        "thumbnail_url": thumb,
        "thumbnail_2x_url": thumb2,
        "params_count": len(part.params),
        "topology_knobs": [p.name for p in part.params if p.topology],
        "summary": part.summary,
        "bbox_mm": list(part.facts.bbox_mm) if part.facts else None,
    }


def facts(part: PartRecord, *, pool: WarmPool | None = None) -> PartFacts | None:
    """Printing facts at the defaults (stored on the record, else computed from a bake)."""
    if part.facts is not None:
        return part.facts
    return bake_output(part, {}, ("stl",), pool=pool).facts


def ensure_thumbnail(
    part: PartRecord, *, force: bool = False, reg: Registry | None = None, pool: WarmPool | None = None
) -> tuple[str, str]:
    """Render (if needed) and store the 1x/2x thumbnails of a part at its defaults. Returns their blob URLs."""
    from services.registry import thumbs

    reg = reg or get_registry()
    psha = params_sha(part.defaults)
    t = reg.thumbnail(part.slug)
    fresh = bool(t) and not force and t["code_sha"] == part.code_sha and t["params_sha"] == psha  # type: ignore[index]
    if t and fresh and blobs.exists(t["key_1x"]) and blobs.exists(t["key_2x"]):
        return blobs.url(t["key_1x"]), blobs.url(t["key_2x"])
    out = bake_output(part, {}, ("view",), pool=pool)
    view = json.loads(out.files["view"].read_text())
    k1, k2 = thumbs.store_pair(view)
    reg.set_thumbnail(part.slug, code_sha=part.code_sha, params_sha=psha, key_1x=k1, key_2x=k2)
    return blobs.url(k1), blobs.url(k2)


def after_publish(part: PartRecord, *, reg: Registry | None = None, pool: WarmPool | None = None) -> PartRecord:
    """Fill printing facts if missing and render the thumbnails. Called by seed, Steer approval and the publish route."""
    reg = reg or get_registry()
    if part.facts is None:
        try:
            part.facts = facts(part, pool=pool)
            reg.upsert_part(part)
        except Exception:  # facts are a nicety; a failed bake must not block publishing
            pass
    ensure_thumbnail(part, reg=reg, pool=pool)
    return part


def lineage(part: PartRecord, reg: Registry | None = None) -> list[dict[str, Any]]:
    """Parent (`forked_from`) and registry parts derived from this one (`variant_of` = that part is a variant of this)."""
    reg = reg or get_registry()
    out: list[dict[str, Any]] = []
    parent = part.provenance.forked_from
    if parent:
        p = reg.get_part(parent)
        out.append(
            {
                "slug": parent,
                "version": p.version if p else 1,
                "relation": "forked_from",
                "title": p.title if p else parent,
            }
        )
    children, _ = reg.search("", limit=10_000, sort="title")
    for c in children:
        if c.provenance.forked_from == part.slug and c.slug != part.slug:
            out.append({"slug": c.slug, "version": c.version, "relation": "variant_of", "title": c.title})
    return out


def verify_part(slug: str, params: Mapping[str, float], measurements: Mapping[str, Any], *,
                reg: Registry | None = None) -> tuple[Any, dict[str, Any]]:  # fmt: skip
    """Run the verifier for a registry part at `params` against measurements ({view: Measurements}). Deterministic:
    the program runs in the sandbox and the pass rule decides `verified`. Returns (`Verification`, functional probe
    summary — screws that pass each hole, interface fits, printability; never part of the pass rule)."""
    from partsmith_schemas import Measurements

    from services.geom_worker.sandbox import run_program
    from services.verifier.verify import verify

    part = require_part(slug, reg)
    meas = {
        str(k): (m if isinstance(m, Measurements) else Measurements.model_validate(m)) for k, m in measurements.items()
    }
    if not meas:
        raise ValueError("no measurements to verify against")
    res = run_program(part.code, dict(params), outputs=(), features=True)
    try:
        out = verify(res, meas, None)
    finally:
        res.cleanup()
    return out.verification, dict(getattr(out, "functional", {}) or {})


def part_detail(part: PartRecord, reg: Registry | None = None) -> dict[str, Any]:
    """`GET /parts/{slug}`: the PartRecord plus stable artifact URLs, lineage, thumbnails, fact notes and fit reports."""
    reg = reg or get_registry()
    d: dict[str, Any] = part.model_dump(mode="json")
    t1, t2 = thumbnail_urls(part.slug, reg)
    d["artifacts"] = artifact_urls(part.slug)
    d["lineage"] = lineage(part, reg)
    d["thumbnail_url"] = t1
    d["thumbnail_2x_url"] = t2
    d["facts_notes"] = dict(geom_bake.FACT_NOTES)
    d["fit_reports"] = reg.fit_reports(part.slug)
    d["origin"] = part.provenance.origin.value
    d["verified"] = bool(part.verification and part.verification.verified)
    d["status_reason"] = short_reason(part.verification)  # which check kept a best-effort part from passing
    d["ship"] = gate.decide_part(part).to_dict()  # the export gate's decision, same as jobs and bundle.zip
    d["passport"] = passport.link(passport.part_id(part)).model_dump(mode="json")
    return d
