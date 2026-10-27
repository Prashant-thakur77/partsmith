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
from collections.abc import Collection, Mapping, Sequence
from typing import Any

from partsmith_schemas.verification import ParamSpec

from services.agent import providers
from services.agent.guards import max_delta, residual_param
from services.agent.providers import ModelRequest
from services.agent.templates import Template, get_template, list_templates
from services.geom_worker.program import clamp, set_defaults

MOCK_TAG = "deterministic mock"
BROKEN_SYMMETRY = 0.97  # below this, an outline the user calls damaged is treated as having a broken region
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


def count_lobes(outline: Sequence[Sequence[float]], min_depth_mm: float = 0.2) -> int:
    """Radial notches (grip flutes) around a round outline (part frame, centred): local minima of the radius."""
    import numpy as np

    P = np.asarray(outline, dtype=np.float64).reshape(-1, 2)
    if len(P) < 12:
        return 0
    th = np.arctan2(P[:, 1], P[:, 0])
    r = np.hypot(P[:, 0], P[:, 1])
    order = np.argsort(th)
    grid = np.linspace(-np.pi, np.pi, 720, endpoint=False)
    rr = np.interp(grid, th[order], r[order], period=2 * np.pi)
    k = 6
    n = 0
    for i in range(len(rr)):
        win = rr[np.arange(i - k, i + k + 1) % len(rr)]
        if rr[i] <= win.min() + 1e-9 and win.max() - rr[i] >= min_depth_mm and rr[i] < rr[(i - 1) % len(rr)]:
            n += 1
    return n


def edge_runs(outline: Sequence[Sequence[float]], min_rise_mm: float = 1.0) -> dict[str, Any]:
    """Raised runs along the bumpier long edge of a top outline (part frame, long axis X): hinge knuckles, tabs.
    Returns {"count", "at_ends"} or {} when neither long edge has a stepped profile."""
    import numpy as np
    from shapely.geometry import LineString, Polygon

    poly = Polygon(outline).buffer(0)
    if poly.is_empty or len(outline) < 8:
        return {}
    x0, y0, x1, y1 = poly.bounds
    xs = np.arange(x0 + 0.2, x1 - 0.2, 0.2)
    lo, hi = [], []
    for x in xs:
        b = poly.intersection(LineString([(x, y0 - 1), (x, y1 + 1)])).bounds
        lo.append(b[1] if b else np.nan)
        hi.append(b[3] if b else np.nan)
    best: dict[str, Any] = {}
    for prof in (np.asarray(hi), -np.asarray(lo)):
        if np.isnan(prof).any():
            continue
        low, top = float(np.percentile(prof, 10)), float(np.percentile(prof, 90))
        if top - low < min_rise_mm:
            continue
        up = prof > (low + top) / 2
        runs = []
        i = 0
        while i < len(xs):
            if up[i]:
                j = i
                while j + 1 < len(xs) and up[j + 1]:
                    j += 1
                if xs[j] - xs[i] >= 1.0:
                    runs.append((float(xs[i]), float(xs[j])))
                i = j + 1
            else:
                i += 1
        if len(runs) >= 1 and (not best or top - low > best["rise"]):
            ends = (runs[0][0] - x0 < 1.5, x1 - runs[-1][1] < 1.5)
            best = {"count": len(runs), "at_ends": ends, "rise": top - low}
    return best


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
        "lobes": count_lobes(top.get("outline_mm") or []),
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


def template_misfit(t: Template, top: Mapping[str, Any], thickness_mm: float | None) -> str | None:
    """Why the measured size cannot be this template (a mapped size far outside its PARAMS range), else None."""
    mm = t.measure_map
    L, W = float(top["length"]["value"]), float(top["width"]["value"])
    checks: list[tuple[str, float, str]] = []
    if mm.get("length") and mm.get("length") == mm.get("width"):
        checks.append((mm["length"], (L + W) / 2, "diameter"))
    else:
        if mm.get("length"):
            checks.append((mm["length"], L, "length"))
        if mm.get("width"):
            checks.append((mm["width"], W, "width"))
    if thickness_mm and mm.get("thickness"):
        checks.append((mm["thickness"], thickness_mm, "thickness"))
    for name, value, what in checks:
        p = t.param(name)
        if not 0.9 * p.min <= value <= 1.1 * p.max:
            return f"its {what} ({value:.2f} mm) is outside the {t.name} template's {p.min:g}–{p.max:g} mm range"
    return None


THIN_RING_RATIO = 0.75  # bore / outer diameter at or above this: a thin ring (gasket, O-ring, washer)


def _thin_ring(top: Mapping[str, Any]) -> tuple[float, float] | None:
    """(outer Ø, wall) when the top view is a round outline around one central bore with a thin wall."""
    cues = shape_cues(top)
    holes = list(top.get("holes") or [])
    if not cues["round"] or len(holes) != 1 or not cues["central_hole"]:
        return None
    od = (float(top["length"]["value"]) + float(top["width"]["value"])) / 2
    d = float(holes[0]["diameter"]["value"])
    return (od, (od - d) / 2) if od > 0 and d / od >= THIN_RING_RATIO else None


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
    misfit = template_misfit(t, top, float(thickness["value"]) if thickness["source"] != "inferred" else None)
    if "height" in t.measure_map and side is None and not misfit:
        hp = t.param(t.measure_map["height"])
        unknowns.append(
            {
                "id": "height",
                "question": "How tall is the tallest part (above the mat), in millimetres?",
                "expects": "number_mm",
                "default": hp.default,
            }
        )
    if "bore.diameter" in t.measure_map and not misfit:
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
        "template_hint": None if misfit else t.name,
    }
    if misfit:
        spec["family"] = "custom"
        spec["title"] = f"Custom part (not a {t.title.lower()}: {misfit})"
        return spec
    ring = _thin_ring(top)
    if ring is not None:  # a thin annulus could be a gasket or O-ring: rigid prints do not seal, so ask
        unknowns.append(
            {
                "id": "material.flexible",
                "question": f"This looks like a thin ring (Ø{ring[0]:.1f} mm, wall {ring[1]:.1f} mm). Is it soft or "
                "flexible — rubber, silicone, a gasket or a seal?",
                "expects": "choice",
                "choices": ["no", "yes"],
                "default": "no",
            }
        )
    sym = cues.get("symmetry")
    damage = re.search(
        r"\b(missing|cracked|chipped|snapped off|broken off|broke off|piece|corner|tip)\b", intent.lower()
    )
    if isinstance(sym, (int, float)) and sym < BROKEN_SYMMETRY and damage:
        spec["broken_region"] = {
            "polygon_mm": [],
            "strategy": "mirror",
            "note": f"the user says {damage.group(1)!r} and the outline symmetry is {sym:.2f}: the missing side is "
            f"restored from its mirror image and the template ({MOCK_TAG})",
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
    if not hint and spec.get("family") == "custom":
        return {"strategy": "free_code", "template": None, "why": f"no template fits the measured size ({MOCK_TAG})"}
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
    t: Template,
    spec: Mapping[str, Any],
    top: Mapping[str, Any] | None,
    answers: Mapping[str, Any],
    side: Mapping[str, Any] | None = None,
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
        cues = shape_cues(top)
        knuckle = [p for p in t.params if p.topology and "knuckles on" in p.label.lower()]
        phase = [p for p in t.params if p.topology and "mating leaf" in p.label.lower()]
        if knuckle:  # count the knuckles along the edge, and see whether they reach the leaf's ends
            runs = edge_runs(top.get("outline_mm") or [])
            if runs:
                vals[knuckle[0].name] = float(runs["count"])
                if phase:
                    vals[phase[0].name] = 0.0 if any(runs["at_ends"]) else 1.0
        lobes = int(cues["lobes"])
        if cues["round"] and lobes >= 3:  # count the grip flutes seen around the rim
            for p in t.params:
                if p.topology and any(w in p.label.lower() for w in ("flute", "notch", "lobe")):
                    vals[p.name] = float(lobes)
    side_h = ((side or {}).get("thickness") or {}).get("value")
    th = spec.get("thickness") or {}
    if mm.get("height") and side_h:  # the side photo shows the part's full height
        vals[mm["height"]] = _round(float(side_h), LENGTH_ROUND_MM)
    sk = mm.get("side.thickness")
    if sk and side_h and th.get("value") and sk != mm.get("height") and sk != mm.get("thickness"):
        p = t.param(sk)
        if "above the plate" in p.label.lower():  # a feature standing on the plate: full height minus the plate
            vals[sk] = _round(float(side_h) - float(th["value"]), THICKNESS_ROUND_MM)
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


BOSS_MIN_HEIGHT_MM = 0.4  # bumps lower than this on the side silhouette are edge noise
BOSS_REGULARITY = 0.3  # widths and spacings may vary by this fraction and still count as one pattern


def side_bosses(
    side: Mapping[str, Any] | None, plate_mm: float | None, top: Mapping[str, Any] | None
) -> dict[str, Any]:
    """Bosses (studs) standing on the top face, read from the side silhouette: a regular row of bumps above the
    plate along one long edge. Returns {} when the side shows no such pattern. The side row is taken to run along
    the top view's matching dimension; rows across the other dimension repeat at the same pitch."""
    import numpy as np
    from shapely.geometry import LineString, Polygon

    if side is None or top is None or len(side.get("outline_mm") or []) < 8:
        return {}
    poly = Polygon(side["outline_mm"]).buffer(0)
    if poly.is_empty:
        return {}
    x0, y0, x1, y1 = poly.bounds
    xs = np.arange(x0 + 0.1, x1 - 0.1, 0.1)
    lo, hi = np.full(len(xs), np.nan), np.full(len(xs), np.nan)
    for i, x in enumerate(xs):
        cut = poly.intersection(LineString([(x, y0 - 1), (x, y1 + 1)]))
        if not cut.is_empty:
            b = cut.bounds
            lo[i], hi[i] = b[1], b[3]
    ok = ~np.isnan(lo)
    if ok.sum() < 20:
        return {}
    xs, lo, hi = xs[ok], lo[ok], hi[ok]
    flat_low = float(np.std(lo)) <= float(np.std(hi))  # bosses stand on the edge that is not flat
    base_edge = float(np.median(lo if flat_low else hi))
    prof = (hi - base_edge) if flat_low else (base_edge - lo)
    plate = plate_mm if plate_mm else float(np.percentile(prof, 25))
    above = prof > plate + BOSS_MIN_HEIGHT_MM
    segs: list[tuple[float, float, float]] = []  # (start, end, top)
    i = 0
    while i < len(xs):
        if above[i]:
            j = i
            while j + 1 < len(xs) and above[j + 1]:
                j += 1
            segs.append((float(xs[i]), float(xs[j]), float(prof[i : j + 1].max())))
            i = j + 1
        else:
            i += 1
    segs = [sg for sg in segs if sg[1] - sg[0] >= 1.0]
    if len(segs) < 2:
        return {}
    widths = np.array([b - a for a, b, _ in segs])
    centres = np.array([(a + b) / 2 for a, b, _ in segs])
    pitches = np.diff(centres)
    if np.std(widths) > BOSS_REGULARITY * np.mean(widths) or np.std(pitches) > BOSS_REGULARITY * np.mean(pitches):
        return {}
    pitch = float(np.mean(pitches))
    L, W = float(top["length"]["value"]), float(top["width"]["value"])
    along_length = abs((x1 - x0) - L) <= abs((x1 - x0) - W)
    other = W if along_length else L
    rows = max(1, round(other / pitch))
    n = len(segs)
    off = float(np.mean(centres)) - (x0 + x1) / 2
    off = 0.0 if abs(off) < 0.25 * pitch else off  # a centred pattern stays centred (the side may be mirrored)
    a_pos = [off + (k - (n - 1) / 2) * pitch for k in range(n)]
    b_pos = [(k - (rows - 1) / 2) * pitch for k in range(rows)]
    pts = [(a, b) if along_length else (b, a) for a in a_pos for b in b_pos]
    return {
        "centres": [(round(x, 3), round(y, 3)) for x, y in pts],
        "diameter": round(float(np.mean(widths)), 3),
        "height": round(float(np.median([t for _, _, t in segs])) - plate, 3),
        "plate": round(plate, 3),
        "pitch": round(pitch, 3),
    }


def outline_program(
    spec: Mapping[str, Any], top: Mapping[str, Any] | None, side: Mapping[str, Any] | None = None
) -> str:
    """Free-code strategy: extrude the measured outline, cut the measured holes, add bosses seen on the side
    silhouette; sizes stay PARAMS."""
    pts = [(round(float(x), 3), round(float(y), 3)) for x, y in (spec.get("base_profile") or {}).get("points_mm", [])]
    if len(pts) < 3 and top is not None:
        pts = [(round(float(x), 3), round(float(y), 3)) for x, y in top["outline_mm"]]
    th = float((spec.get("thickness") or {}).get("value") or 3.0)
    holes = [f for f in spec.get("features", []) if f.get("kind") == "through_hole"]
    slots = [f for f in spec.get("features", []) if f.get("kind") == "slot"]
    th_src = (spec.get("thickness") or {}).get("source")
    bosses = side_bosses(side, th if th_src in ("user_stated", "measured") else None, top)
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
        "BOSSES = [" + ", ".join(f"({x}, {y})" for x, y in bosses.get("centres", [])) + "]",
        "MEASURE_MAP = {"
        + ", ".join(
            [repr("thickness") + ": " + repr("thickness")]
            + [repr("side.thickness") + ": " + repr("boss_h" if bosses else "thickness")]
            + [repr(f"{h['id']}.diameter") + ": " + repr(f"hole_{i + 1}_d") for i, h in enumerate(holes)]
        )
        + "}",
        "",
        "PARAMS = {  # name: (default, min, max, step, unit, affects_fit, label)",
        f'    "thickness": ({th:.2f}, {min(0.8, round(th * 0.5, 2)):.2f}, 40.0, 0.01, "mm", True, "Plate thickness"),',
        '    "outline_offset": (0.0, -1.0, 1.0, 0.02, "mm", True, "Outline offset (+ grows the outline)"),',
    ]
    for i, h in enumerate(holes):
        d = float(h["diameter"]["value"])
        lines.append(
            f'    "hole_{i + 1}_d": ({d:.2f}, {max(0.5, d - 3):.2f}, {d + 3:.2f}, 0.05, "mm", True, "{h["id"]} diameter"),'
        )
    if bosses:
        bd, bh = float(bosses["diameter"]), float(bosses["height"])
        lines.append(
            f'    "boss_d": ({bd:.2f}, 0.5, {bd + 6:.2f}, 0.05, "mm", True, "Boss diameter (seen on the side)"),'
        )
        lines.append(
            f'    "boss_h": ({bh:.2f}, 0.2, {bh + 6:.2f}, 0.05, "mm", True, "Boss height above the top face"),'
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
        "    if BOSSES:",
        '        studs = cq.Workplane("XY").workplane(offset=t - 0.2).pushPoints(BOSSES).circle(p["boss_d"] / 2)',
        '        body = body.union(studs.extrude(p["boss_h"] + 0.2))',
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
        meas = ctx.get("measurements") or {}
        side_m = meas.get("side") if isinstance(meas.get("side"), Mapping) else None
        return "```python\n" + outline_program(spec, top, side_m) + "```"
    t = get_template(str(ctx["template"]))
    meas = ctx.get("measurements") or {}
    side = meas.get("side") if isinstance(meas.get("side"), Mapping) else None
    if side is None and ctx.get("orbit_height_mm"):  # the orbit clip measured the full height
        side = {"thickness": {"value": float(ctx["orbit_height_mm"])}}
    vals = template_values(t, spec, top, ctx.get("answers") or {}, side)
    code = set_defaults(t.code, vals)
    header = f"# part.py — generated by PartSmith from the {t.name} template (deterministic mock builder).\n"
    return "```python\n" + header + code + "```"


# ------------------------------------------------------------------------------------------------- fix


def _residual_param(r: Mapping[str, Any], measure_map: Mapping[str, str]) -> str | None:
    return residual_param(str(r["feature_id"]), str(r["quantity"]), measure_map)


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
    centre_residuals: Mapping[str, float] | None = None,
    hints: Sequence[Mapping[str, Any]] = (),
    pos_names: Collection[str] = (),
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
        if "improved" in last:  # the code's verdict (all tests and views), not just the Hausdorff distance
            improved = bool(last["improved"])
        else:
            improved = hd_b is not None and hd_a is not None and hd_a < hd_b - HD_IMPROVED_MM
        tag = str(probe["reason"]).split(":")[0]
        cres = dict(centre_residuals or {})
        if improved and cres and _positional(p, pos_names):
            slope = _measured_slope(p.name, list(cres), history, signed=True)
            if slope is not None:
                d = sum(cres.values()) / len(cres)
                why = f"the hole centre moves {slope:+.2f} mm per mm of {p.name}; {d:+.2f} mm left"
                return [
                    {"param": p.name, "to": to - d / slope, "reason": f"probe=: {why}"}
                ], f"place the hole with {p.name}"
        if improved:
            why = f"the last change of {p.name} lowered the Hausdorff distance {hd_b:.2f} → {hd_a:.2f} mm"
            return [{"param": p.name, "to": to + step, "reason": f"probe>: {why}"}], f"continue moving {p.name}"
        if tag == "probe+" and p.min <= frm - step <= p.max:
            why = f"{p.name} {step:+.2f} did not help; try the other direction"
            return [{"param": p.name, "to": frm - step, "reason": f"probe-: {why}"}], f"reverse {p.name}"
        if tag in ("probe>", "probe="):
            why = f"{p.name} {step:+.2f} overshot; try half of that step"
            return [{"param": p.name, "to": frm + step / 2, "reason": f"probe~: {why}"}], f"halve the step on {p.name}"
    done = set(probed)
    cres_now = dict(centre_residuals or {})
    if center_miss_mm > 0 and cres_now:  # a position knob already tried: its measured response places the hole
        for p in specs:
            if not _positional(p, pos_names) or p.name not in by_name:
                continue
            slope = _measured_slope(p.name, list(cres_now), history, signed=True)
            if slope is None:
                continue
            cur = float(values.get(p.name, p.default))
            d = sum(cres_now.values()) / len(cres_now)
            why = f"the hole centre moves {slope:+.2f} mm per mm of {p.name}; {d:+.2f} mm left"
            return [
                {"param": p.name, "to": cur - d / slope, "reason": f"probe=: {why}"}
            ], f"place the hole with {p.name}"
    under = sum(float(v.get("under_area_mm2", 0.0)) for v in views)
    over = sum(float(v.get("over_area_mm2", 0.0)) for v in views)
    for h in hints:  # knobs that shape the region where the worst residual is
        hp = by_name.get(str(h["param"]))
        if hp is None or hp.name in done:
            continue
        cur = float(values.get(hp.name, hp.default))
        if hp.topology:
            mag = 1.0
        elif hp.unit == "mm":
            mag = min(max(0.8 * float(h["mag"]), hp.step), max_delta(hp, cur))
        else:
            mag = _probe_step(hp, cur)
        sign = float(h["sign"])
        target = min(max(cur + mag * sign, hp.min), hp.max)
        if math.isclose(target, cur):
            target = min(max(cur - mag * sign, hp.min), hp.max)
        if math.isclose(target, cur):
            continue
        why = f"{h['why']}; try {hp.name} {target - cur:+.2f}"
        return [
            {"param": hp.name, "to": target, "reason": f"probe+: {why}"}
        ], f"worst residual sits where {hp.name} acts"
    cands = _probe_candidates(specs, measure_map)
    if center_miss_mm > 0:  # a hole sits in the wrong place: position knobs first
        pos = [q for q in specs if _positional(q, pos_names) and not q.topology]
        pos += [p for p in cands if _positional(p, pos_names) and p not in pos]
        cands = pos + [p for p in cands if p not in pos]
    for p in cands:
        if p.name in done:
            continue
        cur = float(values.get(p.name, p.default))
        positional = center_miss_mm > 0 and _positional(p, pos_names)
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


HOLE_ROW_TOL_MM = 0.3


def _hole_row_edits(
    holes: Mapping[str, Any],
    regions: Mapping[str, Sequence[Sequence[Any]]],
    by_name: Mapping[str, ParamSpec],
    values: Mapping[str, float],
    failed: Collection[tuple[str, float]],
) -> list[dict[str, Any]]:
    """Pair each measured hole with the nearest model hole (both in the model frame); the mean offset moves the knobs
    a template declares under planes "holes_x" / "holes_y" (effect = direction a raise moves the holes)."""
    measured, model = list(holes.get("measured") or []), list(holes.get("model") or [])
    if not measured or not model:
        return []
    dx: list[float] = []
    dy: list[float] = []
    for mx, my, _ in measured:
        nx, ny, _ = min(model, key=lambda q: math.hypot(q[0] - mx, q[1] - my))
        dx.append(mx - nx)
        dy.append(my - ny)
    mdx, mdy = sum(dx) / len(dx), sum(dy) / len(dy)
    edits: list[dict[str, Any]] = []
    for axis, d in (("holes_x", mdx), ("holes_y", mdy)):
        if abs(d) <= HOLE_ROW_TOL_MM:
            continue
        for name, boxes in regions.items():
            eff = next((int(b[5]) for b in boxes if str(b[0]) == axis and int(b[5]) != 0), 0)
            p = by_name.get(name)
            if not eff or p is None:
                continue
            cur = float(values.get(name, p.default))
            to = round(cur + eff * d, 3)
            if any(q == name and abs(t - to) < 0.06 for q, t in failed):
                continue
            edits.append(
                {"param": name, "from": cur, "to": to, "reason": f"measured holes sit {d:+.2f} mm along {axis[-1]}"}
            )
            break
    return edits


def region_hints(
    worst: Sequence[Mapping[str, Any]],
    regions: Mapping[str, Sequence[Sequence[Any]]],
    topology: Collection[str] = (),
) -> list[dict[str, Any]]:
    """Knobs whose template region contains a worst residual (smallest region first), with the direction that
    removes extra material or adds missing material there."""
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for w in worst:
        a, b = (float(x) for x in w["norm"])
        cands: list[tuple[float, int, str, int]] = []
        for order, (name, boxes) in enumerate(regions.items()):
            for box in boxes:
                plane, a0, a1, b0, b1, eff = str(box[0]), *(float(x) for x in box[1:5]), int(box[5])
                if plane == w["plane"] and a0 - 0.05 <= a <= a1 + 0.05 and b0 - 0.05 <= b <= b1 + 0.05:
                    # topology knobs first: a pattern error (a knuckle on the wrong side) is not a size error
                    # pattern knobs first (counts, phases, shifts: effect 0): a pattern error is not a size error
                    pattern = name in topology or eff == 0
                    cands.append((0.0 if pattern else (a1 - a0) * (b1 - b0), order, name, eff))
                    break
        kind = str(w.get("kind", "unclear"))
        want = 1 if kind == "missing" else -1 if kind == "extra" else 0
        for _, _, name, eff in sorted(cands):
            if name in seen:
                continue
            seen.add(name)
            why = (
                f"worst {w['view']} residual {float(w['hausdorff_mm']):.2f} mm ({kind} material) lies where {name} acts"
            )
            out.append({"param": name, "sign": (want * eff) or 1, "mag": float(w["hausdorff_mm"]), "why": why})
    return out


def _tried_and_failed(
    name: str,
    values: Mapping[str, float],
    hint: Mapping[str, Any],
    by_name: Mapping[str, ParamSpec],
    failed: Collection[tuple[str, float]],
) -> bool:
    """A region hint whose next step was already tried without improvement."""
    p = by_name.get(name)
    if p is None:
        return True
    cur = float(values.get(name, p.default))
    return any(q == name and (t - cur) * float(hint["sign"]) > 0 for q, t in failed)


def _failed_before(history: Sequence[Mapping[str, Any]]) -> set[tuple[str, float]]:
    """(param, target) pairs that were tried in an earlier round and did not improve the result."""
    out: set[tuple[str, float]] = set()
    for h in history:
        if h.get("improved"):
            continue
        for e in h.get("edits", []):
            out.add((str(e["param"]), round(float(e["to"]), 2)))
    return out


def _hole_centres(residuals: Sequence[Mapping[str, Any]]) -> dict[str, tuple[float, float]]:
    """Measured hole centres (part frame) from the centre residual rows."""
    xs: dict[str, float] = {}
    ys: dict[str, float] = {}
    for r in residuals:
        if r["quantity"] == "center_x":
            xs[str(r["feature_id"])] = float(r["measured_mm"])
        elif r["quantity"] == "center_y":
            ys[str(r["feature_id"])] = float(r["measured_mm"])
    return {h: (xs[h], ys.get(h, 0.0)) for h in xs}


def _positional(p: ParamSpec, extra: Collection[str] = ()) -> bool:
    """A knob that moves holes: named like one, or listed by the template's REGIONS under plane "holes"."""
    return p.name in extra or any(w in p.name for w in ("offset", "pitch", "spacing", "position"))


def _measured_slope(
    param: str, keys: Sequence[str], history: Sequence[Mapping[str, Any]], *, signed: bool = False
) -> float | None:
    """d(residual)/d(param) from the latest round that changed only this knob's value among its edits."""
    for h in reversed(history):
        for e in h.get("edits", []):
            if e.get("param") != param:
                continue
            dx = float(e["to"]) - float(e["from"])
            before, after = h.get("residuals_before") or {}, h.get("residuals_after") or {}
            ds = [float(after[k]) - float(before[k]) for k in keys if k in before and k in after]
            if abs(dx) < 1e-6 or not ds:
                return None
            slope = (sum(ds) / len(ds)) / dx
            ok = 0.15 <= (abs(slope) if signed else slope) <= 5.0
            return slope if ok else None
    return None


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

    # 1. residuals that a mapped knob controls: move it against the residual. Every residual the knob controls is
    #    averaged (a stated and a measured thickness can disagree a little); after one try the measured response
    #    (secant) sets the step, because a knob does not always move the measured size 1:1 (parallax, fillets).
    centres = _hole_centres(residuals)
    # a hole in the wrong place explains a large Hausdorff distance better than sub-tolerance size residuals do
    hole_misplaced = any(
        str(r["quantity"]).startswith("center") and abs(float(r["delta_mm"])) > float(r["tol_mm"]) for r in residuals
    )
    has_count = any(p.topology and "hole" in p.name for p in specs)
    controlled: dict[str, list[tuple[str, float]]] = {}
    failing: set[str] = set()
    for r in residuals:
        d, tol = float(r["delta_mm"]), float(r["tol_mm"])
        name = _residual_param(r, measure_map)
        if name is None or name not in by_name:
            continue
        fid = str(r["feature_id"])
        generic = fid in centres and f"{fid}.diameter" not in measure_map and not has_count and len(centres) > 1
        if generic and fid != min(centres, key=lambda h: math.hypot(*centres[h])):
            continue  # the generic hole knob sizes the central hole only
        key = f"{fid}.{r['quantity']}"
        controlled.setdefault(name, []).append((key, d))
        if abs(d) > (tol if not views_fail or hole_misplaced else 0.5 * tol):
            failing.add(name)
    edits: list[dict[str, Any]] = []
    notes: list[str] = []
    for name in sorted(failing, key=lambda n: -max(abs(d) for _, d in controlled[n])):
        pairs = controlled[name]
        mean = sum(d for _, d in pairs) / len(pairs)
        cur = values.get(name, by_name[name].default)
        slope = _measured_slope(name, [k for k, _ in pairs], history)
        step = -mean / slope if slope is not None else -DAMPING * mean
        to = round(cur + step, 4)
        if any(p == name and abs(t - to) < 0.06 for p, t in failed):
            continue  # tried that already and it did not help
        how = f"measured response {slope:.2f} mm/mm" if slope is not None else "damped"
        edits.append({"param": name, "from": cur, "to": to, "reason": f"residual {mean:+.2f} mm ({how})"})
        notes.append(f"{', '.join(k for k, _ in pairs)} {mean:+.2f} mm → {name}")
    if edits:
        return {
            "analysis": "Largest residuals first: " + "; ".join(notes) + f". ({MOCK_TAG})",
            "edits": edits,
            "code_patch": None,
        }

    # 2a. the model's hole row sits elsewhere than the photo's: move it with the template's hole-position knobs
    row = _hole_row_edits(ctx.get("holes") or {}, ctx.get("regions") or {}, by_name, values, failed)
    if row:
        return {"analysis": f"The hole row is off: {row[0]['reason']}. ({MOCK_TAG})", "edits": row, "code_patch": None}

    # 2. holes the photo has and the model lacks (or the other way round): change a hole-count knob
    missing = sum(1 for t in ver.get("tests", []) if str(t["id"]).endswith(".diameter") and t.get("value") is None)
    measured_n, model_n = int(ctx.get("measured_holes", 0)), int(ctx.get("model_holes", 0))
    surplus = model_n - measured_n if model_n > measured_n and not missing else 0
    knobs = [p for p in specs if p.topology and "hole" in p.name]
    if (missing or surplus) and knobs:
        k = knobs[0]
        cur = values.get(k.name, k.default)
        to = cur + (1 if missing else -1)
        if k.min <= to <= k.max and not any(p == k.name and abs(t - to) < 0.06 for p, t in failed):
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
        cres = {
            f"{r['feature_id']}.{r['quantity']}": float(r["delta_mm"])
            for r in residuals
            if str(r["quantity"]).startswith("center") and abs(float(r["delta_mm"])) > 0.5 * float(r["tol_mm"])
        }
        topo = {p.name for p in specs if p.topology}
        hints = region_hints(ctx.get("worst") or [], ctx.get("regions") or {}, topo)
        hints = [h for h in hints if not _tried_and_failed(str(h["param"]), values, h, by_name, failed)]
        regions = ctx.get("regions") or {}
        pos_names = {k for k, boxes in regions.items() if any(str(b[0]).startswith("holes") for b in boxes)}
        miss = max(centers, default=0.0)
        probe_edits, why = _explore(specs, values, measure_map, history, views, miss, cres, hints, pos_names)
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
