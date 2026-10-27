"""Deterministic domain mocks for the agent's model stages (used when a stage has no key or PROVIDER_MODE=mock).

They stand in for a careful but imperfect model and drive the REAL code paths (schemas, guards, sandbox, verifier):

* understand — a PartSpec from the measurements, the user's intent / family hint and shape cues (round or long, holes,
  symmetry); every guess is marked `inferred`, hidden values become `unknowns` (questions);
* plan — template choice from the PartSpec;
* build — the template program with measured PARAMS rounded to nominal sizes (lengths to 1 mm, diameters and
  thickness to 0.5 mm, as a model tends to do) and unmeasured PARAMS left at their defaults, so the fix loop has
  real work; "free_code" writes an extruded-outline program from the measured outline;
* fix — bounded, damped edits read from the residual table (sign and size of each residual), hole-count knobs from
  missing holes, and a one-knob-at-a-time search guided by over/under areas and the measured effect of earlier edits;
* judge — rule-based vetoes (openings missing from the render, missing slots);
* capture_triage — never asks for a retake on its own; variant — the deterministic phrase mapper.

None of them reads ground truth: inputs come only from `ModelRequest.mock_context`, which the orchestrator fills with
what a model would see (measurements, intent, PartSpec, residual table, history). Every call is labelled mock in its
`model_call` event by the providers layer.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from typing import Any

from partsmith_schemas.verification import ParamSpec

from services.agent import providers
from services.agent.guards import max_delta
from services.agent.providers import ModelRequest
from services.agent.templates import Template, get_template, list_templates
from services.geom_worker.program import clamp, set_defaults

MOCK_TAG = "deterministic mock"
DAMPING = 0.9  # a careful model under-corrects slightly rather than overshooting
HD_IMPROVED_MM = 0.01
LENGTH_ROUND_MM = 1.0
DIAMETER_ROUND_MM = 0.5
THICKNESS_ROUND_MM = 0.5

# intent / family words → template
_KEYWORDS: dict[str, tuple[str, ...]] = {
    "knob": ("knob", "dial", "ghundi", "regulator"),
    "caster_wheel": ("wheel", "caster", "castor", "pahiya", "roller"),
    "cupboard_latch": ("latch", "turn button", "catch", "kundi", "chitkani"),
    "hinge_leaf": ("hinge", "kabza"),
    "battery_cover": ("battery", "remote cover", "battery door", "dhakkan"),
    "cable_clip": ("cable", "wire clip", "taar"),
    "spacer": ("spacer", "standoff", "bushing", "washer"),
    "hook": ("hook", "hanger", "khunti"),
    "l_bracket": ("bracket", "angle"),
    "clip": ("clip", "snap"),
}


# ------------------------------------------------------------------------------------------------- helpers


def _round(v: float, step: float) -> float:
    return round(round(v / step) * step, 3)


def _top(ctx: Mapping[str, Any]) -> dict[str, Any] | None:
    meas = ctx.get("measurements") or {}
    top = meas.get("top")
    return dict(top) if isinstance(top, Mapping) else None


def shape_cues(top: Mapping[str, Any]) -> dict[str, Any]:
    """What a model would notice in the top photo: size, roundness, holes and where they are."""
    L = float(top["length"]["value"])
    W = float(top["width"]["value"])
    area = float(top.get("area_mm2") or L * W)
    holes = list(top.get("holes") or [])
    ellipse = math.pi / 4 * L * W
    hole_area = sum(math.pi / 4 * float(h["diameter"]["value"]) ** 2 for h in holes)
    fill = (area + hole_area) / ellipse if ellipse > 0 else 0.0
    central = [h for h in holes if math.hypot(*h["center_mm"]) < 0.12 * L]
    return {
        "length_mm": L,
        "width_mm": W,
        "aspect": L / W if W > 0 else 1.0,
        "round": L / max(W, 1e-6) < 1.06 and 0.93 < fill < 1.07,
        "n_holes": len(holes),
        "central_hole": bool(central),
        "n_slots": len(top.get("slots") or []),
        "symmetry": top.get("symmetry_score"),
    }


def choose_template(intent: str, family_hint: str | None, cues: Mapping[str, Any] | None) -> tuple[str, str]:
    """(template name, why). Family hint first, then words in the intent, then shape cues."""
    if family_hint:
        for t in list_templates():
            if t.family.value == family_hint:
                return t.name, f"family hint {family_hint!r}"
    text = (intent or "").lower()
    for name, words in _KEYWORDS.items():
        for w in words:
            if re.search(rf"\b{re.escape(w)}", text):
                return name, f"the intent mentions {w!r}"
    if cues is None:
        return "clip", "no cues; generic clip"
    n = int(cues["n_holes"])
    if cues["round"]:
        if n == 0:
            return "knob", "round outline without through holes"
        if n == 1 and cues["central_hole"] and cues["length_mm"] <= 30:
            return "spacer", "small round part with one central bore"
        return "caster_wheel", "round outline with a central bore and lightening holes"
    if n == 0:
        return "battery_cover", "flat rectangular plate without holes"
    if n == 1:
        return (
            ("cupboard_latch", "long bar with one off-centre pivot hole")
            if not cues["central_hole"]
            else ("clip", "plate with one central screw hole")
        )
    if cues["aspect"] > 2.2:
        return "hinge_leaf", "long plate with a row of screw holes"
    return "hook", "plate with two screw holes"


def _measured(value: float, sigma: float = 0.0, note: str | None = None, source: str = "measured") -> dict[str, Any]:
    d: dict[str, Any] = {"value": round(float(value), 4), "source": source, "sigma_mm": round(float(sigma), 4)}
    if note:
        d["evidence"] = {"note": note}
    return d


def _thickness_param(t: Template) -> ParamSpec | None:
    name = t.measure_map.get("thickness")
    return t.param(name) if name else None


# ------------------------------------------------------------------------------------------------- understand


def understand(req: ModelRequest) -> dict[str, Any]:
    ctx = req.mock_context
    top = _top(ctx)
    intent = str(ctx.get("intent") or "")
    if top is None:
        raise ValueError("understand mock needs a top-view measurement")
    cues = shape_cues(top)
    name, why = choose_template(intent, ctx.get("family_hint"), cues)
    t = get_template(name)
    meas = ctx.get("measurements") or {}
    side = meas.get("side") if isinstance(meas.get("side"), Mapping) else None
    unknowns: list[dict[str, Any]] = []
    user_t = ctx.get("user_thickness_mm")
    tp = _thickness_param(t)
    if user_t:
        thickness = _measured(float(user_t), 0.3, "stated by the user", "user_stated")
    elif side and side.get("thickness"):
        thickness = dict(side["thickness"])
    elif top.get("thickness"):
        thickness = dict(top["thickness"])
    else:
        guess = tp.default if tp else 3.0
        thickness = _measured(guess, 1.0, f"not visible from the top; typical {t.title.lower()} value", "inferred")
        unknowns.append(
            {
                "id": "thickness",
                "question": "How thick is the part, in millimetres? (A side photo also works.)",
                "expects": "number_mm",
                "default": guess,
            }
        )
    features: list[dict[str, Any]] = []
    for h in top.get("holes") or []:
        features.append(
            {"kind": "through_hole", "id": h["id"], "center_mm": list(h["center_mm"]), "diameter": dict(h["diameter"])}
        )
    for s in top.get("slots") or []:
        features.append(
            {
                "kind": "slot",
                "id": s["id"],
                "center_mm": list(s["center_mm"]),
                "length": dict(s["length"]),
                "width": dict(s["width"]),
                "angle_deg": float(s.get("angle_deg", 0.0)),
            }
        )
    if "bore.diameter" in t.measure_map:
        bp = t.param(t.measure_map["bore.diameter"])
        flat = t.measure_map.get("bore.flat_depth")
        fd = t.param(flat).default if flat else 0.0
        features.append(
            {
                "kind": "d_shaft_bore",
                "id": "bore",
                "diameter": _measured(bp.default, 0.5, "blind bore underneath; not visible in the photo", "inferred"),
                "flat_depth": _measured(fd, 0.5, "typical D-shaft flat", "inferred"),
            }
        )
        unknowns.append(
            {
                "id": "bore.diameter",
                "question": "What shaft diameter does it fit on, in millimetres?",
                "expects": "number_mm",
                "default": bp.default,
            }
        )
    spec: dict[str, Any] = {
        "family": t.family.value,
        "units": "mm",
        "title": t.title,
        "base_profile": {
            "kind": "polyline",
            "points_mm": [list(p) for p in top["outline_mm"]],
            "source": "measured",
            "sigma_mm": float(top["length"].get("sigma_mm", 0.0)),
        },
        "thickness": thickness,
        "features": features,
        "unknowns": unknowns,
        "intent": intent,
        "template_hint": t.name,
    }
    sym = cues.get("symmetry")
    if isinstance(sym, (int, float)) and sym < 0.9 and "broken" in intent.lower():
        spec["broken_region"] = {
            "polygon_mm": [],
            "strategy": "template",
            "note": f"outline symmetry {sym:.2f}: the template restores the missing side ({MOCK_TAG})",
        }
    spec["title"] = f"{t.title} ({why})"
    return spec


# ------------------------------------------------------------------------------------------------- plan


def plan(req: ModelRequest) -> dict[str, Any]:
    ctx = req.mock_context
    spec = ctx.get("partspec") or {}
    hint = spec.get("template_hint")
    if ctx.get("strategy_hint") == "free_code":
        return {"strategy": "free_code", "template": None, "why": f"template did not converge ({MOCK_TAG})"}
    if hint:
        return {
            "strategy": "template",
            "template": str(hint),
            "why": f"PartSpec family {spec.get('family')} ({MOCK_TAG})",
        }
    name, why = choose_template(str(spec.get("intent", "")), spec.get("family"), None)
    return {"strategy": "template", "template": name, "why": f"{why} ({MOCK_TAG})"}


# ------------------------------------------------------------------------------------------------- build


def _representative_hole(holes: Sequence[Mapping[str, Any]], all_same: bool) -> float | None:
    if not holes:
        return None
    if all_same:
        return sum(float(h["diameter"]["value"]) for h in holes) / len(holes)
    nearest = min(holes, key=lambda h: math.hypot(*h["center_mm"]))
    return float(nearest["diameter"]["value"])


def template_values(
    t: Template, spec: Mapping[str, Any], top: Mapping[str, Any] | None, answers: Mapping[str, Any]
) -> dict[str, float]:
    """PARAMS for the first build: measured quantities via MEASURE_MAP (rounded to nominal sizes), counts of the
    measured holes, user answers; everything else stays at the template default."""
    vals: dict[str, float] = dict(t.defaults)
    mm = t.measure_map
    holes = list((top or {}).get("holes") or [])
    count_knobs = [p for p in t.params if p.topology and "hole" in p.name]
    if top is not None:
        L, W = float(top["length"]["value"]), float(top["width"]["value"])
        if mm.get("length") and mm.get("length") == mm.get("width"):
            vals[mm["length"]] = _round((L + W) / 2, LENGTH_ROUND_MM)
        else:
            if mm.get("length"):
                vals[mm["length"]] = _round(L, LENGTH_ROUND_MM)
            if mm.get("width"):
                vals[mm["width"]] = _round(W, LENGTH_ROUND_MM)
        d = _representative_hole(holes, all_same=bool(count_knobs))
        if d is not None and mm.get("hole_1.diameter"):
            vals[mm["hole_1.diameter"]] = _round(d, DIAMETER_ROUND_MM)
        for k in count_knobs:
            vals[k.name] = float(len(holes))
    th = spec.get("thickness") or {}
    if mm.get("thickness") and th.get("value"):
        vals[mm["thickness"]] = _round(float(th["value"]), THICKNESS_ROUND_MM)
    for key, value in answers.items():
        target = mm.get(key) or (key if key in vals else None)
        if target is not None:
            try:
                vals[target] = float(value)
            except (TypeError, ValueError):
                continue
    clamped, _ = clamp(vals, list(t.params))
    return clamped


def outline_program(spec: Mapping[str, Any], top: Mapping[str, Any] | None) -> str:
    """Free-code strategy: extrude the measured outline, cut the measured holes; sizes stay PARAMS."""
    pts = [(round(float(x), 3), round(float(y), 3)) for x, y in (spec.get("base_profile") or {}).get("points_mm", [])]
    if len(pts) < 3 and top is not None:
        pts = [(round(float(x), 3), round(float(y), 3)) for x, y in top["outline_mm"]]
    th = float((spec.get("thickness") or {}).get("value") or 3.0)
    holes = [f for f in spec.get("features", []) if f.get("kind") == "through_hole"]
    slots = [f for f in spec.get("features", []) if f.get("kind") == "slot"]
    lines = [
        "# part.py — generated by PartSmith (free-code strategy, deterministic mock builder). Edit PARAMS only.",
        "import cadquery as cq",
        "",
        "FAMILY = " + repr(str(spec.get("family", "custom"))),
        "OUTLINE = [" + ", ".join(f"({x}, {y})" for x, y in pts) + "]",
        "HOLES = ["
        + ", ".join(f"({float(h['center_mm'][0]):.3f}, {float(h['center_mm'][1]):.3f})" for h in holes)
        + "]",
        "SLOTS = ["
        + ", ".join(
            f"({float(s['center_mm'][0]):.3f}, {float(s['center_mm'][1]):.3f}, {float(s.get('angle_deg', 0.0)):.2f})"
            for s in slots
        )
        + "]",
        "MEASURE_MAP = {"
        + ", ".join(
            [repr("thickness") + ": " + repr("thickness")]
            + [repr(f"{h['id']}.diameter") + ": " + repr(f"hole_{i + 1}_d") for i, h in enumerate(holes)]
        )
        + "}",
        "",
        "PARAMS = {  # name: (default, min, max, step, unit, affects_fit, label)",
        f'    "thickness": ({th:.2f}, 0.8, 40.0, 0.05, "mm", True, "Plate thickness"),',
        '    "outline_offset": (0.0, -1.0, 1.0, 0.02, "mm", True, "Outline offset (+ grows the outline)"),',
    ]
    for i, h in enumerate(holes):
        d = float(h["diameter"]["value"])
        lines.append(
            f'    "hole_{i + 1}_d": ({d:.2f}, {max(0.5, d - 3):.2f}, {d + 3:.2f}, 0.05, "mm", True, "{h["id"]} diameter"),'
        )
    for i, s in enumerate(slots):
        sl, sw = float(s["length"]["value"]), float(s["width"]["value"])
        lines.append(
            f'    "slot_{i + 1}_l": ({sl:.2f}, {max(1.0, sl - 5):.2f}, {sl + 5:.2f}, 0.05, "mm", True, "slot length"),'
        )
        lines.append(
            f'    "slot_{i + 1}_w": ({sw:.2f}, {max(0.5, sw - 3):.2f}, {sw + 3:.2f}, 0.05, "mm", True, "slot width"),'
        )
    lines += [
        "}",
        "",
        "",
        "def build(p):",
        '    t = p["thickness"]',
        '    prof = cq.Workplane("XY").polyline(OUTLINE).close()',
        '    if abs(p["outline_offset"]) > 0.005:',
        '        prof = prof.offset2D(p["outline_offset"], "intersection")',
        "    body = prof.extrude(t)",
        "    for i, c in enumerate(HOLES):",
        '        d = p["hole_" + str(i + 1) + "_d"]',
        '        cutter = cq.Workplane("XY").workplane(offset=-1).center(c[0], c[1]).circle(d / 2).extrude(t + 2)',
        "        body = body.cut(cutter)",
        "    for i, s in enumerate(SLOTS):",
        '        sl, sw = p["slot_" + str(i + 1) + "_l"], p["slot_" + str(i + 1) + "_w"]',
        '        cutter = cq.Workplane("XY").workplane(offset=-1).center(s[0], s[1]).slot2D(sl, sw, s[2]).extrude(t + 2)',
        "        body = body.cut(cutter)",
        "    return body",
        "",
        "",
        "result = build({k: v[0] for k, v in PARAMS.items()})",
    ]
    return "\n".join(lines) + "\n"


def build(req: ModelRequest) -> str:
    ctx = req.mock_context
    spec = ctx.get("partspec") or {}
    top = _top(ctx)
    if ctx.get("strategy") == "free_code" or not ctx.get("template"):
        return "```python\n" + outline_program(spec, top) + "```"
    t = get_template(str(ctx["template"]))
    vals = template_values(t, spec, top, ctx.get("answers") or {})
    code = set_defaults(t.code, vals)
    header = f"# part.py — generated by PartSmith from the {t.name} template (deterministic mock builder).\n"
    return "```python\n" + header + code + "```"


# ------------------------------------------------------------------------------------------------- fix


def _param_for(key_exact: str, key_generic: str | None, measure_map: Mapping[str, str]) -> str | None:
    if key_exact in measure_map:
        return measure_map[key_exact]
    if key_generic and key_generic in measure_map:
        return measure_map[key_generic]
    return None


def _residual_param(r: Mapping[str, Any], measure_map: Mapping[str, str]) -> str | None:
    fid, qty = str(r["feature_id"]), str(r["quantity"])
    if fid == "outline" and qty in ("length", "width"):
        return measure_map.get(qty)
    if fid == "plate" and qty == "thickness":
        return measure_map.get("thickness")
    if qty == "diameter":
        return _param_for(f"{fid}.diameter", "hole_1.diameter", measure_map)
    return None


def _inner_feature(p: ParamSpec) -> bool:
    words = (p.name + " " + p.label).lower()
    return any(w in words for w in ("hole", "bore", "pin", "cable", "pivot_d", "slot", "flat"))


def _probe_candidates(specs: Sequence[ParamSpec], measure_map: Mapping[str, str]) -> list[ParamSpec]:
    mapped = set(measure_map.values())
    cands = [p for p in specs if not p.topology and p.unit == "mm" and p.name not in mapped and not _inner_feature(p)]
    first = [p for p in cands if any(w in p.name for w in ("offset", "corner", "radius", "fillet"))]
    return first + [p for p in cands if p not in first]


def _probe_step(p: ParamSpec, current: float) -> float:
    return float(min(max(p.step, 0.1 * (p.max - p.min)), max_delta(p, current)))


def _shrink_sign(p: ParamSpec) -> float:
    """Direction that removes material at the outline: larger radii/fillets, smaller everything else."""
    return 1.0 if any(w in p.name for w in ("corner", "radius", "fillet", "chamfer")) else -1.0


def _explore(
    specs: Sequence[ParamSpec],
    values: Mapping[str, float],
    measure_map: Mapping[str, str],
    history: Sequence[Mapping[str, Any]],
    views: Sequence[Mapping[str, Any]],
    center_miss_mm: float = 0.0,
) -> tuple[list[dict[str, Any]], str]:
    """One knob at a time: try a step, keep going while the Hausdorff distance drops, else try the other way, then
    move on. The orchestrator always continues from the best round, so a step that made things worse is undone."""
    by_name = {p.name: p for p in specs}
    probed = [
        str(e["param"]) for h in history for e in h.get("edits", []) if str(e.get("reason", "")).startswith("probe")
    ]
    last = history[-1] if history else None
    probe = None
    if last:
        probes = [e for e in last.get("edits", []) if str(e.get("reason", "")).startswith("probe")]
        probe = probes[-1] if probes else None
    if probe is not None and last is not None and str(probe["param"]) in by_name:
        p = by_name[str(probe["param"])]
        frm, to = float(probe["from"]), float(probe["to"])
        step = to - frm
        hd_b, hd_a = last.get("hd_before"), last.get("hd_after")
        improved = hd_b is not None and hd_a is not None and hd_a < hd_b - HD_IMPROVED_MM
        tag = str(probe["reason"]).split(":")[0]
        if improved:
            why = f"the last change of {p.name} lowered the Hausdorff distance {hd_b:.2f} → {hd_a:.2f} mm"
            return [{"param": p.name, "to": to + step, "reason": f"probe>: {why}"}], f"continue moving {p.name}"
        if tag == "probe+":
            why = f"{p.name} {step:+.2f} did not help; try the other direction"
            return [{"param": p.name, "to": frm - step, "reason": f"probe-: {why}"}], f"reverse {p.name}"
    done = set(probed)
    under = sum(float(v.get("under_area_mm2", 0.0)) for v in views)
    over = sum(float(v.get("over_area_mm2", 0.0)) for v in views)
    cands = _probe_candidates(specs, measure_map)
    if center_miss_mm > 0:  # a hole sits in the wrong place: position knobs first
        pos = [p for p in cands if any(w in p.name for w in ("offset", "pitch", "spacing", "position"))]
        cands = pos + [p for p in cands if p not in pos]
    for p in cands:
        if p.name in done:
            continue
        cur = float(values.get(p.name, p.default))
        positional = center_miss_mm > 0 and any(w in p.name for w in ("offset", "pitch", "spacing", "position"))
        mag = min(center_miss_mm, max_delta(p, cur)) if positional else _probe_step(p, cur)
        direction = 1.0 if positional else _shrink_sign(p) * (1.0 if over >= under else -1.0)
        target = min(max(cur + mag * direction, p.min), p.max)
        if math.isclose(target, cur):
            target = min(max(cur - mag * direction, p.min), p.max)
        if math.isclose(target, cur):
            continue
        why = (
            f"a hole is {center_miss_mm:.2f} mm from its measured centre; try {p.name} {target - cur:+.2f}"
            if positional
            else f"model has {over:.1f} mm² extra / {under:.1f} mm² missing material; try {p.name} {target - cur:+.2f}"
        )
        return [{"param": p.name, "to": target, "reason": f"probe+: {why}"}], f"outline still off; probing {p.name}"
    return [], "no knob left to probe"


def _failed_before(history: Sequence[Mapping[str, Any]]) -> set[tuple[str, float]]:
    """(param, target) pairs that were tried in an earlier round and did not improve the result."""
    out: set[tuple[str, float]] = set()
    for h in history:
        if h.get("improved"):
            continue
        for e in h.get("edits", []):
            out.add((str(e["param"]), round(float(e["to"]), 2)))
    return out


def fix(req: ModelRequest) -> dict[str, Any]:
    ctx = req.mock_context
    specs = [ParamSpec.model_validate(p) for p in ctx.get("params", [])]
    by_name = {p.name: p for p in specs}
    values = {k: float(v) for k, v in (ctx.get("values") or {}).items()}
    measure_map: dict[str, str] = dict(ctx.get("measure_map") or {})
    ver = ctx.get("verification") or {}
    residuals = list(ver.get("residuals") or [])
    views = list(ver.get("views") or [])
    history = list(ctx.get("history") or [])
    views_fail = any(float(v["hausdorff_mm"]) > 0.5 or float(v["iou"]) < 0.97 for v in views)
    failed = _failed_before(history)

    # 1. residuals that a mapped knob controls: move it against the residual (damped)
    wanted: dict[str, list[float]] = {}
    notes: list[str] = []
    for r in residuals:
        d, tol = float(r["delta_mm"]), float(r["tol_mm"])
        if abs(d) <= (tol if not views_fail else 0.5 * tol):
            continue
        name = _residual_param(r, measure_map)
        if name is None or name not in by_name:
            continue
        wanted.setdefault(name, []).append(d)
        notes.append(f"{r['feature_id']} {r['quantity']} {d:+.2f} mm → {name}")
    edits: list[dict[str, Any]] = []
    for name, deltas in wanted.items():
        mean = sum(deltas) / len(deltas)
        cur = values.get(name, by_name[name].default)
        to = round(cur - DAMPING * mean, 4)
        if (name, round(to, 2)) in failed:
            continue  # tried that already and it did not help
        edits.append({"param": name, "from": cur, "to": to, "reason": f"residual {mean:+.2f} mm"})
    if edits:
        return {
            "analysis": "Largest residuals first: " + "; ".join(notes) + f". ({MOCK_TAG})",
            "edits": edits,
            "code_patch": None,
        }

    # 2. holes the photo has and the model lacks (or the other way round): change a hole-count knob
    missing = sum(1 for t in ver.get("tests", []) if str(t["id"]).endswith(".diameter") and t.get("value") is None)
    measured_n, model_n = int(ctx.get("measured_holes", 0)), int(ctx.get("model_holes", 0))
    surplus = model_n - measured_n if model_n > measured_n and not missing else 0
    knobs = [p for p in specs if p.topology and "hole" in p.name]
    if (missing or surplus) and knobs:
        k = knobs[0]
        cur = values.get(k.name, k.default)
        to = cur + (1 if missing else -1)
        if k.min <= to <= k.max and (k.name, round(to, 2)) not in failed:
            why = (
                f"{missing} measured hole(s) have no match in the model"
                if missing
                else (f"the model has {surplus} more hole(s) than the photo")
            )
            return {
                "analysis": f"{why}. ({MOCK_TAG})",
                "edits": [{"param": k.name, "from": cur, "to": to, "reason": why}],
                "code_patch": None,
            }

    # 3. outline still off with every residual in tolerance: move one unmapped outline knob at a time
    if views_fail:
        centers = [
            abs(float(r["delta_mm"]))
            for r in residuals
            if str(r["quantity"]).startswith("center") and abs(float(r["delta_mm"])) > float(r["tol_mm"])
        ]
        probe_edits, why = _explore(specs, values, measure_map, history, views, max(centers, default=0.0))
        for e in probe_edits:
            e["from"] = values.get(str(e["param"]), by_name[str(e["param"])].default)
        if probe_edits:
            return {
                "analysis": f"Residuals are within tolerance but the outline is not: {why}. ({MOCK_TAG})",
                "edits": probe_edits,
                "code_patch": None,
            }
        return {
            "analysis": f"{why}; nothing more to try with parameters. ({MOCK_TAG})",
            "edits": [],
            "code_patch": None,
        }
    return {
        "analysis": f"Every residual and view is within tolerance; no change. ({MOCK_TAG})",
        "edits": [],
        "code_patch": None,
    }


# ------------------------------------------------------------------------------------------------- judge, triage, variant


def judge(req: ModelRequest) -> dict[str, Any]:
    ctx = req.mock_context
    vetoes: list[dict[str, Any]] = []
    po, mo = int(ctx.get("photo_openings", 0)), int(ctx.get("model_openings", 0))
    if mo < po:
        vetoes.append(
            {
                "feature": "holes",
                "issue": f"the photo shows {po} through-opening(s), the render {mo}",
                "severity": "blocking",
            }
        )
    elif mo > po:
        vetoes.append(
            {
                "feature": "holes",
                "issue": f"the render has {mo - po} opening(s) the photo does not show",
                "severity": "minor",
            }
        )
    if int(ctx.get("measured_slots", 0)) > 0 and mo < po:
        vetoes.append(
            {"feature": "slot", "issue": "a slot in the photo is missing from the render", "severity": "blocking"}
        )
    return {"vetoes": vetoes, "notes": f"rule-based review of openings ({MOCK_TAG})"}


def capture_triage(req: ModelRequest) -> dict[str, Any]:
    return {"retake": False, "reason": f"no retake requested ({MOCK_TAG})"}


def variant(req: ModelRequest) -> dict[str, Any]:
    """Expects mock_context {"want": str, "params": [ParamSpec dict], "values": {name: float}}."""
    from services.media.voice import map_utterance

    ctx = req.mock_context
    want = str(ctx.get("want") or ctx.get("request") or ctx.get("transcript") or "")
    params = [ParamSpec.model_validate(p) for p in ctx.get("params", [])]
    if not want or not params:
        return {"edits": [], "not_applied": [want or "empty request"], "confidence": 0.0}
    edits, missed, conf = map_utterance(want, params, ctx.get("values") or {})
    return {"edits": edits, "not_applied": missed, "confidence": conf}


HANDLERS = {
    "understand": understand,
    "plan": plan,
    "build": build,
    "fix": fix,
    "judge": judge,
    "capture_triage": capture_triage,
    "variant": variant,
}


def install(*, replace: bool = False) -> None:
    """Register the domain mocks. With `replace=False` a mock someone else installed (e.g. a test) is kept."""
    for stage, handler in HANDLERS.items():
        providers.register_mock(stage, handler, replace=replace)


__all__ = ["HANDLERS", "choose_template", "install", "outline_program", "shape_cues", "template_values"]
