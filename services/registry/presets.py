"""Fit presets: material × process clearances applied to the knobs that set a fit.

A preset changes only `affects_fit` knobs that are internal fits — screw holes, bores, pin holes, cable channels and
explicit gap/clearance knobs — by adding the preset's clearance (internal features print undersize on FDM). Outer
dimensions never change. The deltas are documented starting points, not measurements: print the fit-test coupon and
report how it fit (`services/registry/fit_learning.py`); the learned clearance replaces the delta for that printer +
material on that device, always inside `clearance_range`.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from partsmith_schemas.verification import ParamSpec

from services.media.voice import snap_clamp

FIT_KEYS = ("hole", "bore", "pivot", "pin", "cable", "gap", "clearance", "slot")
LEARN_SPAN_MM = 0.25  # coupon learning may move a preset's clearance at most this far either way (never below 0)


@dataclass(frozen=True)
class Preset:
    id: str
    title: str
    material: str
    process: str
    nozzle_mm: float | None
    delta_mm: float  # added to internal-fit diameters / gaps
    note: str


PRESETS: tuple[Preset, ...] = (
    Preset("pla-fdm-0.4", "PLA · FDM 0.4 mm nozzle", "PLA", "FDM", 0.4, 0.20,
           "Holes print ~0.2 mm small on a 0.4 mm nozzle."),
    Preset("petg-fdm-0.4", "PETG · FDM 0.4 mm nozzle", "PETG", "FDM", 0.4, 0.25,
           "PETG strings and oozes into holes a little more than PLA."),
    Preset("abs-fdm-0.4", "ABS · FDM 0.4 mm nozzle", "ABS", "FDM", 0.4, 0.30,
           "ABS shrinks as it cools; holes close up."),
    Preset("pla-fdm-0.6", "PLA · FDM 0.6 mm nozzle", "PLA", "FDM", 0.6, 0.30,
           "Wider extrusion rounds inner corners more."),
    Preset("petg-fdm-0.6", "PETG · FDM 0.6 mm nozzle", "PETG", "FDM", 0.6, 0.35, ""),
    Preset("abs-fdm-0.6", "ABS · FDM 0.6 mm nozzle", "ABS", "FDM", 0.6, 0.40, ""),
    Preset("resin-sla", "Resin · SLA/MSLA", "Resin", "SLA", None, 0.10,
           "Resin is precise; a small clearance avoids press fits after curing."),
)  # fmt: skip
BY_ID = {p.id: p for p in PRESETS}


def clearance_range(preset: Preset) -> tuple[float, float]:
    """The documented range a learned clearance stays in: the preset's delta ± LEARN_SPAN_MM, never below 0 mm."""
    return round(max(0.0, preset.delta_mm - LEARN_SPAN_MM), 4), round(preset.delta_mm + LEARN_SPAN_MM, 4)


def fit_knobs(specs: Sequence[ParamSpec]) -> list[ParamSpec]:
    """Knobs a preset may change: affects_fit, mm, not topology, and an internal fit by name."""
    return [
        p for p in specs
        if p.affects_fit and p.unit == "mm" and not p.topology and any(k in p.name.lower() for k in FIT_KEYS)
    ]  # fmt: skip


def apply(
    preset_id: str, specs: Sequence[ParamSpec], values: Mapping[str, float], *, delta_mm: float | None = None
) -> tuple[dict[str, float], list[dict[str, Any]]]:
    """(new values, [{"param","from","to","delta_mm"}]). Values are clamped and snapped like any other edit.
    `delta_mm` replaces the preset's clearance (a learned one); it is clamped to `clearance_range`.
    KeyError for an unknown preset id."""
    preset = BY_ID[preset_id]
    lo, hi = clearance_range(preset)
    delta = preset.delta_mm if delta_mm is None else min(hi, max(lo, float(delta_mm)))
    out = {p.name: float(values.get(p.name, p.default)) for p in specs}
    changes: list[dict[str, Any]] = []
    for p in fit_knobs(specs):
        before = out[p.name]
        after, _ = snap_clamp(before + delta, p)
        if abs(after - before) > 1e-9:
            out[p.name] = after
            changes.append({"param": p.name, "from": before, "to": after, "delta_mm": round(after - before, 4)})
    return out, changes


def for_part(specs: Sequence[ParamSpec], values: Mapping[str, float]) -> list[dict[str, Any]]:
    """Every preset with what it would change on this part."""
    rows = []
    for p in PRESETS:
        _, changes = apply(p.id, specs, values)
        rows.append({"id": p.id, "title": p.title, "material": p.material, "process": p.process,
                     "nozzle_mm": p.nozzle_mm, "delta_mm": p.delta_mm, "note": p.note, "changes": changes})  # fmt: skip
    return rows


DEFAULT_ID = "pla-fdm-0.4"


def for_fit(material: str | None, printer: str | None) -> str | None:
    """The preset id for a PartSpec `fit` (material + printer), None when no preset matches."""
    if printer == "SLA":
        return "resin-sla"
    pid = f"{(material or '').lower()}-fdm-{'0.6' if printer == 'FDM_0_6' else '0.4'}"
    return pid if pid in BY_ID else None
