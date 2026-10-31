"""Sizes the photo cannot see: a few named hidden dimensions the user types on /fix (inner bore Ø, socket depth …).

A top photo shows outlines; it cannot show how deep a socket goes or the bore inside a hub. The user can state such a
size (`JobInput.hidden_dims`: name + value_mm). The value is user-stated, never observed:

* the builder gets it as a number the program must use (`prompt_block`);
* when the program has a knob for that kind of size (`HIDDEN_KINDS[...].knobs`, first match in PARAMS order of the
  list), code sets that knob to the value and locks it, so the fix rounds cannot move it;
* after the verdict, `check` compares the final knob value with the stated one (within half a knob step, at least
  `TOL_MM`): "checked against the program" — the photo still does not show it, so it is never part of `verified` or
  the max error. A size with no matching knob (or a free-named one) is "used, not checked from the photo".

Pure functions, no IO.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from partsmith_schemas.registry import HiddenDim
from partsmith_schemas.verification import ParamSpec

TOL_MM = 0.05
MAX_DIMS = 4


@dataclass(frozen=True)
class HiddenKind:
    label: str
    knobs: tuple[str, ...]  # knob names that hold this size, best first


HIDDEN_KINDS: dict[str, HiddenKind] = {
    "bore_d": HiddenKind("Inner bore Ø", ("bore_d", "pin_d", "pivot_d", "hole_d")),
    "socket_depth": HiddenKind("Socket depth", ("bore_depth", "step_depth", "flat_depth", "grip_depth")),
    "hole_d": HiddenKind("Hole Ø", ("hole_d", "bore_d", "pin_d")),
    "wall": HiddenKind("Wall thickness", ("wall", "knuckle_wall", "rim_thickness", "arm_thickness")),
    "cable_d": HiddenKind("Cable / rod Ø it holds", ("cable_d", "opening")),
}

Status = Literal["checked", "mismatch", "used_not_checked"]


def label(name: str) -> str:
    kind = HIDDEN_KINDS.get(name)
    return kind.label if kind else name.replace("_", " ").strip()


def match_knob(name: str, specs: Sequence[ParamSpec]) -> ParamSpec | None:
    """The program's knob for a named hidden size (a millimetre knob from the kind's list), or None."""
    kind = HIDDEN_KINDS.get(name)
    if kind is None:
        return None
    by_name = {p.name: p for p in specs if p.unit == "mm"}
    return next((by_name[k] for k in kind.knobs if k in by_name), None)


def tolerance(spec: ParamSpec | None) -> float:
    return max(TOL_MM, (spec.step / 2.0) if spec is not None and spec.step > 0 else 0.0)


def prompt_block(dims: Sequence[HiddenDim], specs: Sequence[ParamSpec] = ()) -> str:
    """Lines for the builder: the stated sizes as numbers the program must use (empty when there are none)."""
    if not dims:
        return ""
    lines = [
        "Sizes the user stated because the photo cannot show them (user-stated, not measured). Use these exact "
        "values in the program; do not infer them from the photo:"
    ]
    for d in dims:
        knob = match_knob(d.name, specs)
        where = f" (knob {knob.name})" if knob is not None else ""
        lines.append(f"- {label(d.name)} = {d.value_mm:g} mm{where}")
    return "\n".join(lines)


def knob_values(dims: Sequence[HiddenDim], specs: Sequence[ParamSpec]) -> dict[str, tuple[float, str]]:
    """knob -> (stated value, why) for every stated size the program has a knob for (first size wins a knob)."""
    out: dict[str, tuple[float, str]] = {}
    for d in dims:
        knob = match_knob(d.name, specs)
        if knob is not None and knob.name not in out and knob.min <= d.value_mm <= knob.max:
            out[knob.name] = (float(d.value_mm), f"the user stated the {label(d.name).lower()} ({d.value_mm:g} mm)")
    return out


def check(dims: Sequence[HiddenDim], specs: Sequence[ParamSpec], values: Mapping[str, float]) -> list[dict[str, Any]]:
    """One row per stated size: the knob that holds it, the model's value and whether they agree (code only)."""
    rows: list[dict[str, Any]] = []
    for d in dims:
        knob = match_knob(d.name, specs)
        row: dict[str, Any] = {"name": d.name, "label": label(d.name), "value_mm": d.value_mm, "knob": None,
                               "model_mm": None, "tol_mm": None}  # fmt: skip
        status: Status = "used_not_checked"
        if knob is None:
            note = "given to the builder; no knob of this program holds it, so it is used, not checked from the photo"
        elif not knob.min <= d.value_mm <= knob.max:
            note = (f"outside what the {knob.name} knob can make ({knob.min:g}–{knob.max:g} mm), so it was not "
                    "applied; used, not checked from the photo")  # fmt: skip
        else:
            model = float(values.get(knob.name, knob.default))
            tol = tolerance(knob)
            row.update(knob=knob.name, model_mm=round(model, 4), tol_mm=round(tol, 4))
            if abs(model - d.value_mm) <= tol:
                status = "checked"
                note = (f"the program's {knob.name} is {model:g} mm, the stated value within {tol:g} mm (checked "
                        "against the program; the photo does not show it, so it is not part of verified)")  # fmt: skip
            else:
                status = "mismatch"
                note = f"the program's {knob.name} is {model:g} mm, not the stated {d.value_mm:g} mm"
        row.update(status=status, note=note)
        rows.append(row)
    return rows


def reason_lines(rows: Sequence[Mapping[str, Any]]) -> list[str]:
    """Plain-words lines for the verdict's notes (one per stated size)."""
    return [f"{r['label']} {r['value_mm']:g} mm stated by the user: {r['note']}." for r in rows]
