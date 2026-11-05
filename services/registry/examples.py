"""The parametric playground: every family template as an example part with knobs, named presets and a thumbnail.

A template is a complete part program (PARAMS + `build(p)`), so the playground needs no registry record: it bakes the
template's own code at the requested values through the same sandbox and content-addressed bake cache as registry
parts (`services/geom_worker/bake.py`). Presets are plain knob values defined here, next to nothing but code; a test
checks that every preset names real knobs and stays inside their PARAMS ranges.

Template bakes make no claim about a real part: no photo was involved. Printable files therefore leave through the
export gate as best effort (`TEMPLATE_SHIP`): the plain-words reason is shown and the download needs `ack=1`.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from services.agent.templates import BENCH_TEMPLATES, Template, all_templates, get_template
from services.common.paths import sub
from services.geom_worker import bake as geom_bake
from services.geom_worker.program import clamp
from services.registry.parts import API, METRIC_CLEARANCE_MM

TEMPLATE_VERSION = 1
TEMPLATE_SHIP_REASON = (
    "A family template at the values you chose: nothing compared it with a photo of a real part. "
    "Print the fit-test coupon or a test piece before relying on it."
)


@dataclass(frozen=True)
class Preset:
    id: str
    title: str
    note: str
    values: dict[str, float]

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "title": self.title, "note": self.note, "values": dict(self.values)}


def _m(size: str) -> float:
    return METRIC_CLEARANCE_MM[size]


_M = "clearance hole for an M{s} screw (ISO 273 medium, {d:g} mm)"


def _screw(knob: str, size: str, extra: Mapping[str, float] | None = None) -> Preset:
    d = _m(size)
    return Preset(f"m{size}", f"M{size} screw", _M.format(s=size, d=d), {knob: d, **dict(extra or {})})


PRESETS: dict[str, tuple[Preset, ...]] = {
    "battery_cover": (
        Preset("small-door", "Small door", "a shorter, narrower door", {"length": 40.0, "width": 24.0}),
        Preset(
            "large-door",
            "Large door",
            "longer and wider, three hinge tongues",
            {"length": 70.0, "width": 45.0, "tongue_count": 3},
        ),
        Preset("thin-wall", "Thin wall", "the thinnest door the knob allows", {"thickness": 1.0}),
    ),
    "cable_clip": (
        _screw("hole_d", "3"),
        _screw("hole_d", "4"),
        Preset(
            "three-thin",
            "Three thin cables",
            "three 4 mm cables on a longer base",
            {"cable_d": 4.0, "channel_count": 3, "length": 50.0},
        ),
    ),
    "caster_wheel": (
        Preset("axle-8", "8 mm axle", "bore for an 8 mm axle", {"bore_d": 8.0}),
        Preset(
            "small-30",
            "Small 30 mm wheel",
            "a small wheel on a 5 mm axle",
            {"diameter": 30.0, "tread_width": 12.0, "bore_d": 5.0, "hub_d": 12.0},
        ),
        Preset("wide-60", "Wide 60 mm wheel", "a larger, wider wheel", {"diameter": 60.0, "tread_width": 24.0}),
    ),
    "clip": (
        _screw("hole_d", "3"),
        _screw("hole_d", "4"),
        Preset("thin-wall", "Thin wall", "thinner plate and arm", {"thickness": 1.6, "arm_thickness": 1.4}),
    ),
    "cupboard_latch": (
        _screw("pivot_d", "3"),
        _screw("pivot_d", "4"),
        Preset("no-ridges", "No finger ridges", "a plain top", {"grip_count": 0}),
    ),
    "hinge_leaf": (
        _screw("hole_d", "3"),
        _screw("hole_d", "4"),
        Preset("thin-wall", "Thin wall", "a thinner leaf", {"thickness": 1.6}),
    ),
    "hook": (
        _screw("hole_d", "4"),
        _screw("hole_d", "5"),
        Preset("deep", "Deep towel hook", "a longer reach", {"reach": 45.0}),
    ),
    "knob": (
        Preset(
            "d-shaft-6",
            "6 mm D-shaft",
            "bore for a 6 mm D-shaft with a 1.5 mm flat",
            {"bore_d": 6.0, "flat_depth": 1.5},
        ),
        Preset("round-4", "4 mm round shaft", "a round 4 mm bore, no flat", {"bore_d": 4.0, "flat_depth": 0.0}),
        Preset("big-45", "Big 45 mm knob", "a larger grip", {"diameter": 45.0, "height": 20.0}),
    ),
    "l_bracket": (
        _screw("hole_d", "3"),
        _screw("hole_d", "4"),
        Preset("thin-wall", "Thin wall", "a lighter bracket", {"thickness": 2.0}),
    ),
    "spacer": (
        _screw("bore_d", "3", {"outer_d": 6.0}),
        _screw("bore_d", "4", {"outer_d": 8.0}),
        Preset(
            "washer", "Thin washer", "a 2 mm washer, the thinnest the knob allows", {"height": 2.0, "outer_d": 10.0}
        ),
    ),
    "sliding_battery_door": (
        Preset("small", "Smaller door", "a shorter, narrower door", {"length": 40.0, "width": 28.0}),
        Preset("thin", "Thin door", "for a tight groove", {"thickness": 1.2, "rail_thickness": 0.7}),
        Preset("no-grooves", "No grip grooves", "a plain outer face", {"groove_count": 0}),
    ),
    "drawer_runner": (
        _screw("hole_d", "3"),
        _screw("hole_d", "4"),
        Preset("long", "Long runner", "180 mm with four screws", {"length": 180.0, "hole_count": 4}),
    ),
    "hinge_pin_bracket": (
        _screw("hole_d", "3"),
        _screw("hole_d", "4"),
        Preset("pin-8", "8 mm pin", "a thicker pin and lugs", {"pin_d": 8.0, "lug_thickness": 5.0}),
    ),
    "curtain_ring": (
        Preset("rod-19", "19 mm rod", "a 22 mm bore for a 19 mm rod", {"inner_d": 22.0}),
        Preset("rod-25", "25 mm rod", "a 29 mm bore for a 25 mm rod", {"inner_d": 29.0}),
        Preset("no-eyelet", "No eyelet", "a plain ring", {"eyelet_count": 0}),
    ),
    "pointer_knob": (
        Preset("d-shaft-6", "6 mm D-shaft", "a 6 mm bore with a 1.5 mm flat", {"bore_d": 6.0, "flat_depth": 1.5}),
        Preset("round-6", "Round 6 mm shaft", "a 6 mm bore with no flat", {"bore_d": 6.0, "flat_depth": 0.0}),
        Preset("wide", "Wide skirt", "a bigger skirt and pointer", {"skirt_d": 50.0, "pointer_length": 7.0}),
    ),
    "spur_gear": (
        Preset("d-shaft-5", "5 mm D-shaft", "a 5 mm bore with a 1 mm flat", {"bore_d": 5.0, "flat_depth": 1.0}),
        Preset(
            "small-12", "Small 12-tooth pinion", "a small driving gear", {"pitch_d": 18.0, "teeth": 12, "hub_d": 8.0}
        ),
        Preset("flat", "No hub", "a flat gear", {"hub_height": 0.0}),
    ),
    "shelf_pin": (
        Preset("peg-5", "5 mm hole", "for a 5 mm hole, with a little clearance", {"peg_d": 4.9}),
        Preset("peg-6", "6 mm hole", "for a 6 mm hole, with a little clearance", {"peg_d": 5.9}),
        Preset("no-lip", "No lip", "a plain flat rest", {"lip_height": 0.0}),
    ),
    "chair_glide": (
        Preset("leg-19", "19 mm leg", "a cap for a 19 mm leg", {"leg_d": 19.0}),
        Preset("leg-25", "25 mm leg", "a cap for a 25 mm leg", {"leg_d": 25.0, "sole_d": 38.0}),
        Preset("no-ribs", "No ribs", "a smooth inside", {"rib_count": 0}),
    ),
    "desk_grommet": (
        Preset("hole-60", "60 mm hole", "for a 60 mm hole in the desk", {"hole_d": 59.5, "flange_d": 72.0}),
        Preset("hole-80", "80 mm hole", "for an 80 mm hole in the desk", {"hole_d": 79.5, "flange_d": 92.0}),
        Preset("no-notch", "No notches", "a plain sleeve", {"notch_count": 0}),
    ),
    "lug_cap": (
        Preset("small-28", "28 mm cap", "a 28 mm cap", {"outer_d": 28.0, "height": 12.0}),
        Preset("jar-63", "63 mm jar lid", "a wide, low lid", {"outer_d": 63.0, "height": 14.0, "lug_count": 6}),
        Preset("no-seal", "No sealing ring", "a plain underside", {"seal_height": 0.0}),
    ),
}


def presets_for(name: str) -> tuple[Preset, ...]:
    return PRESETS.get(name, ())


def template_urls(name: str, values: Mapping[str, float] | None = None) -> dict[str, str]:
    """Download URLs of a template bake at `values` (printable files go through the export gate: add `ack=1`)."""
    from urllib.parse import urlencode

    q = {k: f"{float(v):g}" for k, v in sorted((values or {}).items())}
    out = {
        fmt: f"{API}/templates/{name}/bake?" + urlencode({**q, "format": fmt, "download": 1})
        for fmt in ("stl", "3mf", "step", "py")
    }
    out["coupon"] = f"{API}/templates/{name}/coupon.stl" + (f"?{urlencode(q)}" if q else "")
    return out


def template_card(t: Template) -> dict[str, Any]:
    """One playground example: what the template is, its knobs, presets and thumbnail URLs."""
    return {
        "name": t.name,
        "family": t.family.value,
        "title": t.title,
        "summary": t.summary,
        "tags": list(t.tags),
        "params": [p.model_dump(mode="json") for p in t.params],
        "defaults": {k: float(v) for k, v in t.defaults.items()},
        "presets": [p.to_dict() for p in presets_for(t.name)],
        "topology_knobs": t.topology_knobs,
        "thumbnail_url": f"{API}/templates/{t.name}/thumbnail.png",
        "thumbnail_2x_url": f"{API}/templates/{t.name}/thumbnail.png?scale=2",
        "coupon": bool(coupon_features(t, t.defaults)),
        "in_bench": t.name in BENCH_TEMPLATES,
    }


def template_detail(t: Template) -> dict[str, Any]:
    """The card plus the program itself (part.py) and which knob sets which measured quantity."""
    return {**template_card(t), "code": t.code, "code_sha": t.code_sha, "measure_map": dict(t.measure_map)}


def all_cards() -> list[dict[str, Any]]:
    return [template_card(t) for t in all_templates()]


def bake_template(
    name: str, params: Mapping[str, float] | None = None, formats: Iterable[str] = ("view",)
) -> geom_bake.BakeOutput:
    """Bake a template at `params` (clamped to PARAMS) through the sandbox and the shared bake cache."""
    t = get_template(name)
    return geom_bake.bake(t.code, dict(params or {}), list(formats), version=TEMPLATE_VERSION)


def thumbnail_path(name: str, scale: int = 1) -> Path:
    """Isometric PNG of the template at its defaults (rendered once per program version and renderer, then cached on
    disk)."""
    from services.registry import thumbs

    t = get_template(name)
    key = hashlib.sha256(f"{t.code_sha}|{TEMPLATE_VERSION}|{thumbs.RENDER_TAG}".encode()).hexdigest()[:24]
    d = sub("template_thumbs")
    p1, p2 = d / f"{name}-{key}.png", d / f"{name}-{key}@2x.png"
    if not (p1.exists() and p2.exists()):
        out = bake_template(name, {}, ("view",))
        view = json.loads(out.files["view"].read_text())
        b1, b2 = thumbs.render_pair(view)
        p1.write_bytes(b1)
        p2.write_bytes(b2)
    return p2 if scale == 2 else p1


# ------------------------------------------------------------------------------------------------- fit-test coupon


def coupon_features(t: Template, values: Mapping[str, float]) -> list[Any]:
    """The template's fit-critical holes at `values` as coupon features: the screw hole / pivot (round), the bore
    (a D-bore when the template has a flat), nothing when the part has no hole knob or zero holes."""
    from services.media.coupon import CouponFeature

    full, _ = clamp(dict(values), list(t.params))
    out: list[CouponFeature] = []
    if full.get("hole_count", 1) >= 1:
        for knob in ("hole_d", "pivot_d"):
            if knob in full:
                out.append(CouponFeature(knob, "hole", diameter_mm=float(full[knob])))
    if "bore_d" in full:
        flat = float(full.get("flat_depth", 0.0)) if "flat_count" not in full else 0.0
        if flat > 0:
            out.append(CouponFeature("bore_d", "d_bore", diameter_mm=float(full["bore_d"]), flat_depth_mm=flat))
        else:
            out.append(CouponFeature("bore_d", "hole", diameter_mm=float(full["bore_d"])))
    return out


def coupon_code(name: str, values: Mapping[str, float]) -> str | None:
    """A coupon program for the template's critical holes at `values`, or None when it has none."""
    from services.media.coupon import coupon_program

    t = get_template(name)
    feats = coupon_features(t, values)
    if not feats:
        return None
    return coupon_program(feats, title=f"{t.title} fit test")


__all__ = [
    "PRESETS",
    "TEMPLATE_SHIP_REASON",
    "TEMPLATE_VERSION",
    "Preset",
    "all_cards",
    "bake_template",
    "coupon_code",
    "coupon_features",
    "presets_for",
    "template_card",
    "template_detail",
    "template_urls",
    "thumbnail_path",
]
