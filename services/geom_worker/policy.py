"""AST allowlist for part programs. Pure: no imports of cadquery, nothing is executed.

Rules: only ``import cadquery as cq``, ``import math`` and ``from math import ...``; allowlisted builtins only;
no dunder or private names; no attribute that reaches files, processes, frames or the OCP layer. Unbounded loops are
allowed here and stopped by the child's CPU limit.
"""

from __future__ import annotations

import ast
import builtins
from dataclasses import dataclass

MAX_CODE_CHARS = 200_000
MAX_AST_NODES = 60_000

# Builtins the restricted interpreter provides. Everything else in `builtins` is rejected by name.
SAFE_BUILTINS: frozenset[str] = frozenset(
    {
        "abs", "all", "any", "bool", "callable", "chr", "dict", "divmod", "enumerate", "filter", "float", "frozenset",
        "int", "isinstance", "iter", "len", "list", "map", "max", "min", "next", "ord", "pow", "print", "range",
        "repr", "reversed", "round", "set", "slice", "sorted", "str", "sum", "tuple", "zip",
        "True", "False", "None", "NotImplemented", "Ellipsis",
        "ArithmeticError", "AssertionError", "Exception", "IndexError", "KeyError", "LookupError", "RuntimeError",
        "StopIteration", "TypeError", "ValueError", "ZeroDivisionError",
    }
)  # fmt: skip

FORBIDDEN_NAMES: frozenset[str] = frozenset(
    {
        "open", "exec", "eval", "compile", "__import__", "globals", "locals", "vars", "getattr", "setattr",
        "delattr", "hasattr", "input", "breakpoint", "help", "memoryview", "type", "object", "super", "id",
        "classmethod", "staticmethod", "property", "exit", "quit", "format", "bytearray", "bytes",
    }
)  # fmt: skip

# Attributes that reach files, processes, interpreter frames or the raw OCP layer.
FORBIDDEN_ATTRS: frozenset[str] = frozenset(
    {
        "format", "format_map", "mro", "exporters", "importers", "occ_impl", "cqgi", "vis", "wrapped", "toOCC",
        "save", "show", "display", "system", "popen", "environ", "modules", "builtins", "globals", "locals",
        "ctypes", "subprocess", "os", "sys", "socket", "eval", "exec", "compile", "open", "load", "loads",
        "getattr", "setattr", "delattr", "toSvg", "toVtkPolyData", "dump", "dumps", "write", "read",
    }
)  # fmt: skip
FORBIDDEN_ATTR_PREFIXES: tuple[str, ...] = ("_", "f_", "gi_", "cr_", "ag_", "tb_", "co_", "func_", "export", "import")

# Top-level names reachable as ``cq.<name>``.
CQ_ALLOWED: frozenset[str] = frozenset(
    {
        "Workplane", "Sketch", "Vector", "Location", "Plane", "Matrix", "Shape", "Solid", "Face", "Edge", "Wire",
        "Shell", "Compound", "Vertex", "selectors", "Selector", "NearestToPointSelector", "BoxSelector",
        "DirectionMinMaxSelector", "ParallelDirSelector", "PerpendicularDirSelector", "TypeSelector",
        "StringSyntaxSelector", "Color",
    }
)  # fmt: skip

ALLOWED_MODULES = {"cadquery": "cq", "math": None}

_FORBIDDEN_NODES: dict[type[ast.AST], str] = {
    ast.ClassDef: "class definitions are not allowed",
    ast.Global: "'global' is not allowed",
    ast.Nonlocal: "'nonlocal' is not allowed",
    ast.AsyncFunctionDef: "async code is not allowed",
    ast.Await: "async code is not allowed",
    ast.AsyncFor: "async code is not allowed",
    ast.AsyncWith: "async code is not allowed",
    ast.With: "'with' blocks are not allowed",
    ast.Yield: "generators are not allowed",
    ast.YieldFrom: "generators are not allowed",
}


@dataclass(frozen=True)
class Violation:
    """One reason the program may not run. `line`/`col` are 1-based / 0-based like Python's own errors."""

    line: int
    col: int
    message: str
    kind: str = "policy"  # "policy" | "syntax"

    def to_dict(self) -> dict[str, object]:
        return {"line": self.line, "col": self.col, "message": self.message, "kind": self.kind}


def _bound_names(tree: ast.AST) -> set[str]:
    """Every name the program binds anywhere (assignments, defs, args, loop targets, imports)."""
    out: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store | ast.Del):
            out.add(node.id)
        elif isinstance(node, ast.FunctionDef | ast.Lambda):
            if isinstance(node, ast.FunctionDef):
                out.add(node.name)
            a = node.args
            for arg in [*a.posonlyargs, *a.args, *a.kwonlyargs, a.vararg, a.kwarg]:
                if arg is not None:
                    out.add(arg.arg)
        elif isinstance(node, ast.alias):
            out.add(node.asname or node.name.split(".")[0])
        elif isinstance(node, ast.ExceptHandler) and node.name:
            out.add(node.name)
    return out


def _bad_identifier(name: str) -> bool:
    return name.startswith("_") and name != "_"


def check_code(code: str) -> list[Violation]:
    """Return every policy violation (empty list = allowed). A syntax error is returned as a single violation."""
    if len(code) > MAX_CODE_CHARS:
        return [Violation(1, 0, f"program is too long ({len(code)} chars > {MAX_CODE_CHARS})")]
    try:
        tree = ast.parse(code, filename="part.py")
    except SyntaxError as e:
        return [Violation(e.lineno or 1, max((e.offset or 1) - 1, 0), f"SyntaxError: {e.msg}", kind="syntax")]
    except (RecursionError, MemoryError, ValueError) as e:
        return [Violation(1, 0, f"program could not be parsed: {type(e).__name__}", kind="syntax")]

    nodes = list(ast.walk(tree))
    if len(nodes) > MAX_AST_NODES:
        return [Violation(1, 0, f"program is too large ({len(nodes)} AST nodes > {MAX_AST_NODES})")]

    out: list[Violation] = []
    bound = _bound_names(tree)
    builtin_names = set(dir(builtins))

    def add(node: ast.AST, msg: str) -> None:
        out.append(Violation(getattr(node, "lineno", 1), getattr(node, "col_offset", 0), msg))

    for node in nodes:
        for bad, msg in _FORBIDDEN_NODES.items():
            if isinstance(node, bad):
                add(node, msg)
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "cadquery":
                    if alias.asname != "cq":
                        add(node, "import cadquery exactly as 'import cadquery as cq'")
                elif alias.name == "math":
                    if alias.asname and _bad_identifier(alias.asname):
                        add(node, f"bad alias {alias.asname!r}")
                else:
                    add(node, f"import of {alias.name!r} is not allowed (only cadquery as cq, math)")
        elif isinstance(node, ast.ImportFrom):
            if node.module != "math" or node.level:
                add(node, f"'from {node.module or '.'} import' is not allowed (only 'from math import ...')")
            for alias in node.names:
                if _bad_identifier(alias.name) or (alias.asname and _bad_identifier(alias.asname)):
                    add(node, f"private name {alias.name!r} is not allowed")
        elif isinstance(node, ast.Name):
            if _bad_identifier(node.id):
                add(node, f"names starting with '_' are not allowed ({node.id!r})")
            elif node.id in FORBIDDEN_NAMES:
                add(node, f"{node.id!r} is not allowed")
            elif node.id in builtin_names and node.id not in SAFE_BUILTINS and node.id not in bound:
                add(node, f"builtin {node.id!r} is not allowed")
        elif isinstance(node, ast.Attribute):
            attr = node.attr
            if attr in FORBIDDEN_ATTRS or attr.startswith(FORBIDDEN_ATTR_PREFIXES):
                add(node, f"attribute '.{attr}' is not allowed")
            elif isinstance(node.value, ast.Name) and node.value.id == "cq" and attr not in CQ_ALLOWED:
                add(node, f"'cq.{attr}' is not in the allowed CadQuery API")
        elif isinstance(node, ast.FunctionDef):
            if _bad_identifier(node.name):
                add(node, f"names starting with '_' are not allowed ({node.name!r})")
            a = node.args
            for arg in [*a.posonlyargs, *a.args, *a.kwonlyargs, a.vararg, a.kwarg]:
                if arg is not None and _bad_identifier(arg.arg):
                    add(arg, f"names starting with '_' are not allowed ({arg.arg!r})")
        elif isinstance(node, ast.keyword) and node.arg and _bad_identifier(node.arg):
            add(node, f"keyword arguments starting with '_' are not allowed ({node.arg!r})")
    # Deduplicate (a node may hit several rules with the same message) and order by position.
    uniq = {(v.line, v.col, v.message): v for v in out}
    return sorted(uniq.values(), key=lambda v: (v.line, v.col))
