"""Describe it: a person's words with numbers become ONE family-template part whose numbers code checks.

1. **Plan** — the `describe_plan` stage (Muse Spark 1.3; a deterministic, labelled mock without a key) proposes a
   template and parameter values, each with its source: "user" (with the quoted words) or "inferred".
2. **Check the plan (code)** — the same rules as Steer: real templates only (closest name when it is clear, else
   "no template fits"), parameter names mapped to the closest real knob or dropped, values clamped and snapped to
   PARAMS. A "user" value whose quoted words are not in the description is downgraded to "inferred": the model cannot
   claim the person said something they did not.
3. **Ask** — when a fit-critical number (the main length, a screw hole, bore, cable or pin size) was not given, the
   record asks for it (`questions`); answers come back through `answer()` without a second model call.
4. **Bake + number checks (code)** — the template is baked in the sandbox at the checked values, then measured
   (`services/verifier/solid_features.py`, in the sandbox). Every number the person gave is compared with the baked
   model's measured value (±max(0.1 mm, the knob's step)). All met → "Matches your numbers". This is never
   "verified": no photo of a real part was involved.

Records live in `$PARTSMITH_HOME/describe/<id>.json`; model calls are recorded as `model_call` events on the record.
"""

from __future__ import annotations

import difflib
import json
import math
import re
import secrets
import threading
import time
from collections.abc import Mapping, Sequence
from typing import Any

from partsmith_schemas.verification import ParamSpec

from services.agent import providers
from services.agent.providers import ModelRequest
from services.agent.templates import Template, get_template, list_templates
from services.common.paths import sub
from services.geom_worker.program import closest_names
from services.media.voice import snap_clamp
from services.registry import examples
from services.registry.parts import _CLAUSE, _count_param, map_variant

MAX_TEXT = 600
MAX_QUESTIONS = 3
CHECK_TOL_MM = 0.1
NAME_MATCH = 0.6  # difflib ratio for mapping a misspelt template/knob name onto a real one
CRITICAL_KNOBS = ("hole_d", "pivot_d", "bore_d", "cable_d", "pin_d")
NOT_PHOTO = (
    "Made from your description: no photo of a real part was involved, so this is not verified. "
    "Add a photo on /fix to check it against the real part."
)
DESCRIBE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "template": {"type": "string"},
        "title": {"type": "string"},
        "values": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "param": {"type": "string"},
                    "value": {"type": "number"},
                    "source": {"type": "string", "enum": ["user", "inferred"]},
                    "quote": {"type": "string"},
                    "note": {"type": "string"},
                },
                "required": ["param", "value", "source", "quote", "note"],
            },
        },
        "no_fit_reason": {"type": "string"},
        "confidence": {"type": "number"},
    },
    "required": ["template", "title", "values", "no_fit_reason", "confidence"],
}

_lock = threading.RLock()


# ------------------------------------------------------------------------------------------------- mock planner

_EXTRA_WORDS: dict[str, tuple[str, ...]] = {
    "spacer": ("spacer", "standoff", "stand-off", "bushing", "washer", "sleeve"),
    "caster_wheel": ("wheel", "caster", "castor", "roller"),
    "knob": ("knob", "dial"),
    "cupboard_latch": ("latch", "turn button", "catch"),
    "hinge_leaf": ("hinge",),
    "battery_cover": ("battery cover", "battery door", "battery lid"),
    "cable_clip": ("cable clip", "cable holder", "wire clip", "cord clip"),
    "hook": ("hook", "hanger"),
    "l_bracket": ("bracket", "l-bracket", "angle bracket"),
    "clip": ("clip", "retainer", "retaining clip"),
}


def _phrases(t: Template) -> list[str]:
    words = {t.title.lower(), t.family.value.replace("_", " "), *(x.lower() for x in t.tags)}
    words.update(_EXTRA_WORDS.get(t.name, ()))
    return sorted(w for w in words if w)


def _has(text: str, phrase: str) -> bool:
    return re.search(rf"(?<![a-z]){re.escape(phrase)}s?(?![a-z])", text) is not None


def pick_template(text: str, templates: Sequence[Template] | None = None) -> Template | None:
    """The template whose title/tags appear in the words (longer phrases weigh more), or None."""
    low = text.lower()
    best: tuple[int, str] | None = None
    for t in templates or list_templates():
        score = sum(2 * len(p.split()) for p in _phrases(t) if _has(low, p))
        if score and (best is None or score > best[0]):
            best = (score, t.name)
    return get_template(best[1]) if best else None


_SCREWS = re.compile(r"\b(one|two|three|four|single|a|an|\d)\s+(?:m\d+(?:\.\d)?\s+)?(?:screws?|bolts?)\b", re.I)
_COUNT_WORDS = {"one": 1, "single": 1, "a": 1, "an": 1, "two": 2, "three": 3, "four": 4}


def clauses(text: str) -> list[str]:
    """The description cut into short phrases (at commas, "and", "with", and before "for"), each a substring."""
    out: list[str] = []
    for c in _CLAUSE.split(text):
        for piece in re.split(r"\s+(?=for\b)", c or "", flags=re.I):
            if piece.strip():
                out.append(piece.strip())
    return out


def mock_plan(text: str) -> dict[str, Any]:
    """Deterministic `describe_plan` mock: picks the template by its words, then reads each clause with the variant
    mapper ("for a 6 mm cable", "M3 screw", "20 mm wide", "3 ribs") and quotes the clause it came from."""
    t = pick_template(text)
    if t is None:
        return {"template": "none", "title": "", "values": [], "confidence": 0.0,
                "no_fit_reason": "none of the family templates matches these words"}  # fmt: skip
    specs = list(t.params)
    hole_count = _count_param(specs, "hole")
    words = [p for p in sorted(_phrases(t), key=len, reverse=True) if not re.search(r"\d", p)]
    values: dict[str, dict[str, Any]] = {}
    for piece in clauses(text):
        cleaned = piece
        for p in words:  # "a cable clip for a 6 mm cable": the part's own name is not a dimension
            cleaned = re.sub(rf"(?<![a-z]){re.escape(p)}s?(?![a-z])", " ", cleaned, flags=re.I)
        cleaned = " ".join(cleaned.split())
        edits, _, _ = map_variant(cleaned, specs, t.defaults)
        for e in edits:
            values[str(e["param"])] = {"param": e["param"], "value": float(e["to"]), "source": "user", "quote": piece,
                                       "note": str(e.get("reason", ""))}  # fmt: skip
        m = _SCREWS.search(piece)
        if m and hole_count is not None:
            word = m.group(1).lower()
            n = float(word) if word.isdigit() else float(_COUNT_WORDS.get(word, 1))
            values[hole_count.name] = {"param": hole_count.name, "value": n, "source": "user", "quote": piece,
                                       "note": f"{int(n)} screw hole{'s' if n != 1 else ''}"}  # fmt: skip
    return {"template": t.name, "title": t.title, "values": list(values.values()), "no_fit_reason": "",
            "confidence": 0.7 if values else 0.4}  # fmt: skip


def _plan_mock(req: ModelRequest) -> dict[str, Any]:
    return mock_plan(str(req.mock_context.get("text", "")))


def _templates_table() -> str:
    rows = []
    for t in list_templates():
        knobs = ", ".join(f"{p.name} ({p.label}) [{p.min:g}..{p.max:g}{p.unit}]" for p in t.params)
        rows.append(f"\n- {t.name}: {t.title}. {t.summary} Params: {knobs}")
    return "".join(rows)


# ------------------------------------------------------------------------------------------------- code checks


def _norm(s: str) -> str:
    return " ".join(s.lower().split())


def _closest(name: str, options: Sequence[str]) -> str | None:
    close = difflib.get_close_matches(name, list(options), n=1, cutoff=NAME_MATCH)
    return close[0] if close else None


def _value_row(spec: ParamSpec, value: float, source: str, quote: str = "", note: str = "",
               asked: float | None = None) -> dict[str, Any]:  # fmt: skip
    return {
        "param": spec.name,
        "label": spec.label,
        "unit": spec.unit,
        "value": float(value),
        "default": float(spec.default),
        "source": source,
        "quote": quote,
        "note": note,
        "asked": asked,
    }


def check_plan(raw: Mapping[str, Any], text: str) -> tuple[Template | None, list[dict[str, Any]], list[str]]:
    """Code side of the plan. Returns (template or None when nothing fits, one row per knob, notes)."""
    notes: list[str] = []
    names = [t.name for t in list_templates()]
    tname = str(raw.get("template") or "").strip()
    if not tname or tname.lower() == "none":
        return None, [], notes
    if tname not in names:
        near = _closest(tname, names)
        if near is None:
            notes.append(f"the plan named an unknown template {tname!r}")
            return None, [], notes
        notes.append(f"template {tname!r} → {near!r}")
        tname = near
    t = get_template(tname)
    specs = {p.name: p for p in t.params}
    said = _norm(text)
    chosen: dict[str, dict[str, Any]] = {}
    for item in list(raw.get("values") or []):
        if not isinstance(item, Mapping):
            continue
        name = str(item.get("param", "")).strip()
        if name not in specs:
            near = _closest(name, list(specs)) or next(iter(closest_names(name, list(t.params), n=1)), None)
            if near is None or difflib.SequenceMatcher(None, name, near).ratio() < NAME_MATCH:
                notes.append(f"unknown knob {name!r} ignored")
                continue
            notes.append(f"knob {name!r} → {near!r}")
            name = near
        try:
            asked = float(item.get("value"))  # type: ignore[arg-type]
        except (TypeError, ValueError):
            notes.append(f"{name}: no numeric value")
            continue
        if not math.isfinite(asked):
            notes.append(f"{name}: value is not finite")
            continue
        spec = specs[name]
        value, was_clamped = snap_clamp(asked, spec)
        if spec.topology:
            value = float(round(value))
        quote = " ".join(str(item.get("quote", "")).split())[:160]
        source = "user" if str(item.get("source")) == "user" else "inferred"
        note = str(item.get("note", ""))[:200]
        if source == "user" and (not quote or _norm(quote) not in said):
            source = "inferred"
            note = (note + "; " if note else "") + "the quoted words are not in your description, so it is inferred"
            notes.append(f"{name}: quote not found in the description → inferred")
        chosen[name] = _value_row(spec, value, source, quote if source == "user" else "", note,
                                  asked if was_clamped else None)  # fmt: skip
        if was_clamped:
            notes.append(f"{name}: {asked:g} is outside {spec.min:g}–{spec.max:g} {spec.unit}".rstrip())
    rows = [chosen.get(p.name) or _value_row(p, p.default, "default") for p in t.params]
    return t, rows, notes


def critical_knobs(t: Template, rows: Sequence[Mapping[str, Any]]) -> list[ParamSpec]:
    """Fit-critical knobs: the one that sets the main length, then screw hole / pivot / bore / cable / pin sizes.
    Hole sizes are skipped when the part has no holes."""
    values = {str(r["param"]): float(r["value"]) for r in rows}
    out: list[ParamSpec] = []
    main = t.measure_map.get("length")
    for p in t.params:
        if p.name == main or p.name in CRITICAL_KNOBS:
            if p.name in ("hole_d",) and values.get("hole_count", 1) < 1:
                continue
            out.append(p)
    return out


def questions_for(t: Template, rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """One question per fit-critical knob the person did not give a number for (at most MAX_QUESTIONS)."""
    given = {str(r["param"]) for r in rows if r["source"] in ("user", "answer")}
    out = []
    for p in critical_knobs(t, rows):
        if p.name in given:
            continue
        unit = f" ({p.unit})" if p.unit else ""
        out.append({
            "id": p.name, "param": p.name, "label": p.label, "unit": p.unit, "min": p.min, "max": p.max,
            "step": p.step, "default": p.default,
            "prompt": f"{p.label}{unit}? Leave it empty to use the template default, {p.default:g} {p.unit}".rstrip(),
        })  # fmt: skip
    return out[:MAX_QUESTIONS]


def apply_answers(t: Template, rows: list[dict[str, Any]], answers: Mapping[str, float | None]) -> list[str]:
    """Answers become "answer" values (you said, by answering); empty answers keep the default. Returns notes."""
    specs = {p.name: p for p in t.params}
    notes: list[str] = []
    for name, raw in answers.items():
        spec = specs.get(name)
        if spec is None:
            notes.append(f"answer for unknown knob {name!r} ignored")
            continue
        if raw is None:
            continue
        asked = float(raw)
        if not math.isfinite(asked):
            continue
        value, was_clamped = snap_clamp(asked, spec)
        if spec.topology:
            value = float(round(value))
        quote = f"{asked:g} {spec.unit}".strip()
        row = _value_row(spec, value, "answer", quote, "your answer", asked if was_clamped else None)
        for i, r in enumerate(rows):
            if r["param"] == name:
                rows[i] = row
    return notes


# ------------------------------------------------------------------------------------------------- number checks


def _interface_gap(features: Mapping[str, Any], token: str) -> float | None:
    for i in features.get("interfaces") or []:
        if token in str(i.get("id", "")) and i.get("gap_mm") is not None:
            return float(i["gap_mm"])
    return None


def measure_knob(t: Template, name: str, value: float, features: Mapping[str, Any]) -> tuple[float | None, str]:
    """The baked model's own measurement of knob `name` (mm, or a count), and how it was measured. (None, why) when
    the model has no measurement for that knob."""
    size = [float(x) for x in features.get("size_mm") or [0.0, 0.0, 0.0]]
    holes = [float(h["diameter_mm"]) for h in features.get("holes") or []]
    keys = [k for k, v in t.measure_map.items() if v == name]
    round_part = t.measure_map.get("length") == t.measure_map.get("width") == name
    for key in ("cable.diameter", "pin.diameter", "bore.diameter", "hole_1.diameter"):
        if key not in keys:
            continue
        token = {"cable.diameter": "cable", "pin.diameter": "pin", "bore.diameter": "bore"}.get(key)
        if key == "hole_1.diameter" and "bore" in name:
            token = "bore"
        gap = _interface_gap(features, token) if token else None
        if gap is not None:
            return gap, f"measured across the {token} on the baked model"
        if key in ("bore.diameter", "hole_1.diameter") and holes:
            near = min(holes, key=lambda d: abs(d - value))
            return near, "diameter of the nearest round hole on the baked model"
    if round_part and "length" in keys:
        return max(size[0], size[1]), "outside diameter of the baked model (bounding box)"
    if "length" in keys:
        return size[0], "length of the baked model (bounding box, X)"
    if "width" in keys:
        return size[1], "width of the baked model (bounding box, Y)"
    if "height" in keys:
        return size[2], "height of the baked model (bounding box, Z)"
    if "thickness" in keys and features.get("plate_thickness_mm") is not None:
        return float(features["plate_thickness_mm"]), "material thickness of the baked model (most common)"
    return None, "this knob has no measurement on the model: it is set on the knob only"


def number_checks(t: Template, rows: Sequence[Mapping[str, Any]], features: Mapping[str, Any]) -> dict[str, Any]:
    """Compare every number the person gave with the baked model. Never sets "verified"."""
    specs = {p.name: p for p in t.params}
    values = {str(r["param"]): float(r["value"]) for r in rows}
    holes = [float(h["diameter_mm"]) for h in features.get("holes") or []]
    items: list[dict[str, Any]] = []
    for r in rows:
        if r["source"] not in ("user", "answer"):
            continue
        spec = specs[str(r["param"])]
        stated = float(r["asked"]) if r.get("asked") is not None else float(r["value"])
        set_to = float(r["value"])
        tol = 0.0 if spec.topology else max(CHECK_TOL_MM, spec.step)
        unit = spec.unit
        item: dict[str, Any] = {"param": spec.name, "label": spec.label, "unit": unit, "stated": stated,
                                "quote": r.get("quote", ""), "set": set_to, "measured": None, "tol": tol,
                                "method": "", "status": "knob_only", "note": ""}  # fmt: skip
        if r.get("asked") is not None:
            item.update(status="clamped", note=(f"you said {stated:g} {unit}; the knob's range is {spec.min:g}–"
                                                f"{spec.max:g} {unit}, so it is set to {set_to:g} {unit}").replace("  ", " "))  # fmt: skip
            items.append(item)
            continue
        if spec.name == "hole_count" and "hole_d" in values:
            d = values["hole_d"]
            measured: float | None = float(sum(abs(h - d) <= CHECK_TOL_MM for h in holes))
            method = f"round {d:g} mm holes counted on the baked model"
        else:
            measured, method = measure_knob(t, spec.name, set_to, features)
        item["method"] = method
        if measured is None:
            item["note"] = "set on its knob; the model has no direct measurement for it"
        else:
            item["measured"] = round(measured, 3)
            ok = abs(measured - set_to) <= tol + 1e-9
            item["status"] = "met" if ok else "not_met"
            if not ok:
                item["note"] = (f"the baked model measures {measured:.2f} {unit} instead of {set_to:g} {unit}: the "
                                "template could not reach it at the other values").replace("  ", " ")  # fmt: skip
        items.append(item)
    met = sum(i["status"] == "met" for i in items)
    knob_only = sum(i["status"] == "knob_only" for i in items)
    failed = [i for i in items if i["status"] in ("not_met", "clamped")]
    if not items:
        status, label = "none", "You gave no numbers: every value is a template default or inferred"
    elif failed:
        status, label = "partial", f"{len(failed)} of your {len(items)} numbers could not be met"
    else:
        status, label = "matches", "Matches your numbers"
    measured_n = sum(i["status"] in ("met", "not_met") for i in items)
    return {"status": status, "label": label, "items": items, "met": met, "measured": measured_n,
            "knob_only": knob_only, "failed": len(failed),
        "tolerance": f"±max({CHECK_TOL_MM:g} mm, the knob's step)",
        "note": "Code compared the baked model with the numbers you gave. No photo was involved: this is not "
                "verification against a real part."}  # fmt: skip


# ------------------------------------------------------------------------------------------------- storage


def _path(rid: str) -> Any:
    return sub("describe") / f"{rid}.json"


def save(rec: dict[str, Any]) -> None:
    rec["updated_at"] = time.time()
    path = _path(rec["id"])
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(rec, indent=1, default=str))
    tmp.replace(path)


def get(rid: str) -> dict[str, Any]:
    """A stored describe record. KeyError when unknown or malformed."""
    if not re.fullmatch(r"d_[0-9]{6}_[0-9a-f]{8}", rid):
        raise KeyError(rid)
    path = _path(rid)
    if not path.exists():
        raise KeyError(rid)
    rec: dict[str, Any] = json.loads(path.read_text())
    return rec


def recent(limit: int = 5) -> list[str]:
    files = sorted(sub("describe").glob("d_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    return [p.stem for p in files[:limit]]


# ------------------------------------------------------------------------------------------------- pipeline


def _no_fit(rec: dict[str, Any], reason: str) -> None:
    rec.update(status="no_fit", no_fit={
        "reason": reason or "none of the family templates can make this part from its knobs",
        "templates": [t.title for t in list_templates()],
        "next": [{"href": "/fix", "label": "Photograph the part on the mat instead"},
                 {"href": "/requests", "label": "Ask for this part on the requests board"}],
    })  # fmt: skip


def _plan(rec: dict[str, Any]) -> dict[str, Any]:
    from services.agent import prompt_loader

    prompt = prompt_loader.load("describe_plan")
    dev, user = prompt.render(templates=_templates_table(), text=rec["text"])
    req = ModelRequest(
        messages=[{"role": "system", "content": dev}, {"role": "user", "content": user}],
        json_schema=DESCRIBE_SCHEMA,
        schema_name="describe_plan",
        strict=False,
        temperature=0.0,
        mock_context={"text": rec["text"]},
    )
    providers.register_mock("describe_plan", _plan_mock, replace=False)
    events: list[dict[str, Any]] = rec.setdefault("events", [])

    def emit(ev: Any) -> None:
        events.append(ev.model_dump(mode="json") if hasattr(ev, "model_dump") else dict(ev))

    with providers.job_context(rec["id"], emit):
        comp = providers.complete("describe_plan", req)
    rec["planner"] = {"provider": comp.provider, "model": comp.model, "mode": comp.mode, "prompt": prompt.tag}
    return comp.json or {}


def build(rec: dict[str, Any]) -> dict[str, Any]:
    """Bake the checked values in the sandbox, measure the model and compare it with the person's numbers."""
    from services.agent.buy_or_print import print_plan
    from services.geom_worker.sandbox import run_program

    t = get_template(rec["template"])
    params = {str(r["param"]): float(r["value"]) for r in rec["values"]}
    out = examples.bake_template(t.name, params, ("view", "stl"))
    res = run_program(t.code, out.params, outputs=(), features=True)
    try:
        if not res.ok or res.features is None:
            raise RuntimeError(res.error.short() if res.error else "the model could not be measured")
        features = dict(res.features)
    finally:
        res.cleanup()
    rec["checks"] = number_checks(t, rec["values"], features)
    rec["bake"] = {
        "cache_key": out.cache_key, "params": out.params, "clamped": out.clamped, "ms": out.ms,
        "cache_hit": out.cache_hit, "facts": out.facts.model_dump(mode="json") if out.facts else None,
        "view_url": f"/api/v1/bakes/{out.cache_key}/{out.files['view'].name}",
    }  # fmt: skip
    rec["downloads"] = examples.template_urls(t.name, out.params)
    rec["coupon"] = bool(examples.coupon_features(t, out.params))
    rec["print_plan"] = print_plan(out.facts) if out.facts else None
    rec["ship"] = {"status": "best_effort", "reason": examples.TEMPLATE_SHIP_REASON, "needs_ack": True,
                   "source": "registry.gate (template bake)"}  # fmt: skip
    rec["status"] = "done"
    return rec


def _fail(rec: dict[str, Any], exc: BaseException) -> dict[str, Any]:
    rec.update(status="failed", error=f"{type(exc).__name__}: {exc}"[:300])
    return rec


def _record(rid: str, text: str) -> dict[str, Any]:
    return {
        "id": rid, "text": text, "status": "planning", "created_at": time.time(), "updated_at": time.time(),
        "template": None, "family": None, "title": "", "summary": "", "params": [], "values": [], "questions": [],
        "answers": {}, "plan_notes": [], "planner": None, "checks": None, "bake": None, "downloads": None,
        "print_plan": None, "coupon": False, "no_fit": None, "events": [], "label": NOT_PHOTO,
    }  # fmt: skip


def _check_and_build(rec: dict[str, Any], raw: Mapping[str, Any]) -> None:
    t, rows, notes = check_plan(raw, rec["text"])
    rec["plan_notes"] = notes
    if t is None:
        _no_fit(rec, str(raw.get("no_fit_reason", "")))
        return
    rec.update(template=t.name, family=t.family.value, title=str(raw.get("title") or t.title)[:120],
               summary=t.summary, params=[p.model_dump(mode="json") for p in t.params], values=rows)  # fmt: skip
    rec["questions"] = questions_for(t, rows)
    if rec["questions"]:
        rec["status"] = "needs_answers"
    else:
        build(rec)


def start(text: str) -> dict[str, Any]:
    """Plan, check, then either ask for missing numbers, say no template fits, or bake and check. Synchronous."""
    text = " ".join(text.split())[:MAX_TEXT]
    if len(text) < 3:
        raise ValueError("describe the part in a few words, with its numbers")
    rec = _record("d_" + time.strftime("%y%m%d") + "_" + secrets.token_hex(4), text)
    try:
        _check_and_build(rec, _plan(rec))
    except Exception as exc:  # a failed plan or bake is a record state, never a 500
        _fail(rec, exc)
    with _lock:
        save(rec)
    return rec


EXAMPLE_TEXT = "A spacer 12 mm tall for an M3 screw, outer diameter 7 mm"
EXAMPLE_LABEL = (
    "Example result: this sentence run through the describe pipeline on this server with the deterministic mock "
    "planner (no model call). Code checked the plan, built the part in the sandbox and measured it."
)
_examples: dict[str, dict[str, Any]] = {}


def example(text: str = EXAMPLE_TEXT) -> dict[str, Any]:
    """The example sentence through the same check, bake and measure steps as `start()`, planned by the
    deterministic mock (no model call, no `model_call` event, not stored as a description). Computed once per
    process; the record says `example: true` and its planner mode is "mock"."""
    with _lock:
        hit = _examples.get(text)
        if hit is not None:
            return hit
        rec = _record("example", text)
        rec["example"] = True
        rec["label"] = f"{EXAMPLE_LABEL} {NOT_PHOTO}"
        rec["planner"] = {"provider": "mock", "model": "describe_plan mock", "mode": "mock", "prompt": ""}
        try:
            _check_and_build(rec, mock_plan(text))
        except Exception as exc:
            _fail(rec, exc)
            return rec  # not cached: the next request tries again
        _examples[text] = rec
        return rec


def answer(rid: str, answers: Mapping[str, float | None]) -> dict[str, Any]:
    """Apply the answers to the stored plan (no new model call), then bake and check. KeyError for an unknown id,
    ValueError when the record is not waiting for answers."""
    with _lock:
        rec = get(rid)
        if rec["status"] != "needs_answers":
            raise ValueError(f"this description is {rec['status']}, not waiting for answers")
        t = get_template(rec["template"])
        asked = {q["param"] for q in rec["questions"]}
        unknown = [k for k in answers if k not in asked]
        if unknown:
            raise ValueError(f"no question for {', '.join(sorted(unknown))}; answer {', '.join(sorted(asked))}")
        rec["plan_notes"] += apply_answers(t, rec["values"], answers)
        rec["answers"] = {k: v for k, v in answers.items()}
        rec["questions_asked"] = rec["questions"]
        rec["questions"] = []
        try:
            build(rec)
        except Exception as exc:
            _fail(rec, exc)
        save(rec)
        return rec


def public(rec: Mapping[str, Any]) -> dict[str, Any]:
    """The record as the API returns it."""
    return dict(rec)


__all__ = [
    "DESCRIBE_SCHEMA",
    "EXAMPLE_TEXT",
    "NOT_PHOTO",
    "answer",
    "check_plan",
    "example",
    "get",
    "measure_knob",
    "mock_plan",
    "number_checks",
    "pick_template",
    "public",
    "questions_for",
    "start",
]
