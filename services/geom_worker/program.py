"""The part program contract (PLAN §6.4).

A part program is a plain Python file::

    import cadquery as cq

    PARAMS = {  # name: (default, min, max, step, unit, affects_fit, label)
        "thickness": (3.0, 1.2, 8.0, 0.1, "mm", True, "Plate thickness"),
        "rib_count": (2, 0, 6, 1, "", False, "Stiffening ribs"),
    }

    def build(p):
        ...
        return wp  # a cq.Workplane

    result = build({k: v[0] for k, v in PARAMS.items()})

`PARAMS` is read with AST literal parsing only, so nothing in the program runs in the caller's process. Integer knobs with
step 1 and no unit are *topology* knobs (rib_count, hole_count): they change the face count, which shows the model is not
just being rescaled.
"""

from __future__ import annotations

import ast
import difflib
import hashlib
import math
from collections.abc import Mapping
from typing import Any

from partsmith_schemas.verification import ParamSpec

_UNITS = ("mm", "deg", "")


class ProgramError(ValueError):
    """The program does not follow the part program contract."""

    def __init__(self, message: str, line: int | None = None) -> None:
        super().__init__(message)
        self.line = line
        self.message = message


class UnknownParamError(KeyError):
    """A caller asked for a parameter that PARAMS does not define. Carries the closest names."""

    def __init__(self, names: list[str], closest: dict[str, list[str]]) -> None:
        super().__init__(", ".join(names))
        self.names = names
        self.closest = closest

    def __str__(self) -> str:
        parts = []
        for n in self.names:
            hint = self.closest.get(n) or []
            parts.append(f"{n!r}" + (f" (closest: {', '.join(hint)})" if hint else ""))
        return "unknown parameter " + "; ".join(parts)


def code_sha(code: str) -> str:
    """sha256 of the program text (UTF-8)."""
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


def _find_params_node(tree: ast.Module) -> ast.expr | None:
    for node in tree.body:
        if isinstance(node, ast.Assign):
            if any(isinstance(t, ast.Name) and t.id == "PARAMS" for t in node.targets):
                return node.value
        elif (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id == "PARAMS"
            and node.value is not None
        ):
            return node.value
    return None


def _num(v: Any, what: str, line: int) -> float:
    if isinstance(v, bool) or not isinstance(v, int | float) or not math.isfinite(float(v)):
        raise ProgramError(f"{what} must be a finite number, got {v!r}", line)
    return v


def parse_params(code: str) -> list[ParamSpec]:
    """Read the PARAMS block without executing anything.

    Raises ProgramError when PARAMS is missing or malformed. Order follows the source.
    """
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        raise ProgramError(f"syntax error: {e.msg}", e.lineno) from e
    node = _find_params_node(tree)
    if node is None:
        raise ProgramError("no top-level PARAMS = {...} block")
    line = getattr(node, "lineno", 0)
    try:
        raw = ast.literal_eval(node)
    except (ValueError, TypeError, SyntaxError, RecursionError) as e:
        raise ProgramError("PARAMS must be a literal dict of tuples (no expressions)", line) from e
    if not isinstance(raw, dict):
        raise ProgramError("PARAMS must be a dict", line)
    specs: list[ParamSpec] = []
    for name, tup in raw.items():
        if not isinstance(name, str) or not name.isidentifier() or name.startswith("_"):
            raise ProgramError(f"bad parameter name {name!r}", line)
        if not isinstance(tup, tuple) or len(tup) != 7:
            raise ProgramError(f"{name}: expected (default, min, max, step, unit, affects_fit, label)", line)
        default, lo, hi, step, unit, affects_fit, label = tup
        default = _num(default, f"{name}.default", line)
        lo = _num(lo, f"{name}.min", line)
        hi = _num(hi, f"{name}.max", line)
        step = _num(step, f"{name}.step", line)
        if unit not in _UNITS:
            raise ProgramError(f"{name}: unit must be one of {_UNITS}, got {unit!r}", line)
        if not isinstance(affects_fit, bool):
            raise ProgramError(f"{name}: affects_fit must be True/False", line)
        if not isinstance(label, str):
            raise ProgramError(f"{name}: label must be a string", line)
        if lo > hi:
            raise ProgramError(f"{name}: min {lo} > max {hi}", line)
        if not lo <= default <= hi:
            raise ProgramError(f"{name}: default {default} outside [{lo}, {hi}]", line)
        if step <= 0:
            raise ProgramError(f"{name}: step must be > 0", line)
        topology = (
            unit == ""
            and float(step) == 1.0
            and all(isinstance(v, int) or float(v).is_integer() for v in (default, lo, hi))
        )
        specs.append(
            ParamSpec(
                name=name,
                default=float(default),
                min=float(lo),
                max=float(hi),
                step=float(step),
                unit=unit,
                affects_fit=affects_fit,
                label=label,
                topology=topology,
            )
        )
    return specs


def _typed(value: float, spec: ParamSpec) -> float:
    """Topology knobs are integers inside the program (range(), counts)."""
    return round(value) if spec.topology else float(value)


def defaults(code: str) -> dict[str, float]:
    """Default value of every parameter (topology knobs as int)."""
    return {s.name: _typed(s.default, s) for s in parse_params(code)}


def closest_names(name: str, specs: list[ParamSpec], n: int = 3) -> list[str]:
    return difflib.get_close_matches(name, [s.name for s in specs], n=n, cutoff=0.4)


def clamp(values: Mapping[str, float], specs: list[ParamSpec]) -> tuple[dict[str, float], dict[str, float]]:
    """Fill missing params with defaults and clamp to [min, max]; topology knobs are rounded to int.

    Returns ``(clamped, changed)`` where ``changed`` maps each requested param whose value had to change to its new value.
    Unknown names raise UnknownParamError with the closest valid names.
    """
    by_name = {s.name: s for s in specs}
    unknown = [k for k in values if k not in by_name]
    if unknown:
        raise UnknownParamError(unknown, {k: closest_names(k, specs) for k in unknown})
    out: dict[str, float] = {}
    changed: dict[str, float] = {}
    for s in specs:
        if s.name not in values:
            out[s.name] = _typed(s.default, s)
            continue
        raw = values[s.name]
        try:
            v = float(raw)
        except (TypeError, ValueError) as e:
            raise ProgramError(f"{s.name}: value {raw!r} is not a number") from e
        if not math.isfinite(v):
            v = s.default
        v = min(max(v, s.min), s.max)
        typed = _typed(v, s)
        out[s.name] = typed
        if typed != float(raw):
            changed[s.name] = typed
    return out, changed


def params_sha(values: Mapping[str, float]) -> str:
    """Stable hash of a parameter assignment (sorted names, repr of floats)."""
    blob = ";".join(f"{k}={float(values[k])!r}" for k in sorted(values))
    return hashlib.sha256(blob.encode()).hexdigest()


def module_literals(code: str, names: tuple[str, ...]) -> dict[str, Any]:
    """Literal values of selected top-level assignments (FAMILY, TITLE, MEASURE_MAP, ...), parsed without exec."""
    tree = ast.parse(code)
    out: dict[str, Any] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id in names:
                    out[t.id] = ast.literal_eval(node.value)
        elif (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id in names
            and node.value is not None
        ):
            out[node.target.id] = ast.literal_eval(node.value)
    return out


def set_defaults(code: str, values: Mapping[str, float]) -> str:
    """Return the program with the PARAMS defaults replaced by `values` (clamped first), so a downloaded part.py
    rebuilds exactly the baked variant. Only the default literal of each tuple is rewritten; formatting is kept."""
    specs = parse_params(code)
    clamped, _ = clamp(values, specs)
    tree = ast.parse(code)
    node = _find_params_node(tree)
    if not isinstance(node, ast.Dict):
        raise ProgramError("PARAMS must be a dict literal")
    lines = code.splitlines(keepends=True)
    offsets = [0]
    for ln in lines:
        offsets.append(offsets[-1] + len(ln.encode("utf-8")))
    edits: list[tuple[int, int, str]] = []
    for key, val in zip(node.keys, node.values, strict=True):
        if not isinstance(key, ast.Constant) or not isinstance(val, ast.Tuple) or key.value not in clamped:
            continue
        d = val.elts[0]
        if d.end_lineno is None or d.end_col_offset is None:
            continue
        start = offsets[d.lineno - 1] + d.col_offset
        end = offsets[d.end_lineno - 1] + d.end_col_offset
        v = clamped[key.value]
        edits.append((start, end, repr(int(v)) if isinstance(v, int) else repr(round(float(v), 6))))
    raw = code.encode("utf-8")
    for start, end, text in sorted(edits, reverse=True):
        raw = raw[:start] + text.encode("utf-8") + raw[end:]
    return raw.decode("utf-8")
