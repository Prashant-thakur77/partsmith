from __future__ import annotations

import pytest

from services.geom_worker.policy import check_code


def _messages(code: str) -> list[str]:
    return [v.message for v in check_code(code)]


def test_allowed_program_passes(plate_code: str) -> None:
    assert check_code(plate_code) == []


def test_allowed_imports_and_helpers() -> None:
    code = (
        "import math\nfrom math import pi, cos\nimport cadquery as cq\n"
        "def f(n):\n    return [cos(pi * i / n) for i in range(n)]\n"
        "for _ in range(2):\n    pass\n"
        "try:\n    x = cq.Workplane().box(1, 1, 1)\nexcept Exception:\n    x = None\n"
    )
    assert check_code(code) == []


@pytest.mark.parametrize(
    "code, needle",
    [
        ("import os", "import of 'os'"),
        ("import subprocess as sp", "import of 'subprocess'"),
        ("from os import path", "from os import"),
        ("import cadquery", "import cadquery as cq"),
        ("open('/etc/passwd')", "'open' is not allowed"),
        ("exec('1')", "'exec' is not allowed"),
        ("eval('1')", "'eval' is not allowed"),
        ("compile('1', 'a', 'exec')", "'compile' is not allowed"),
        ("__import__('os')", "names starting with '_'"),
        ("getattr(1, 'real')", "'getattr' is not allowed"),
        ("globals()", "'globals' is not allowed"),
        ("vars()", "'vars' is not allowed"),
        ("breakpoint()", "'breakpoint' is not allowed"),
        ("memoryview(b'')", "'memoryview' is not allowed"),
        ("x = (1).__class__", "attribute '.__class__'"),
        ("x = [].__class__.__mro__", "attribute '.__class__'"),
        ("x = '{0.__class__}'.format(1)", "attribute '.format'"),
        ("import cadquery as cq\ncq.exporters.export(None, '/tmp/x')", "attribute '.exporters'"),
        ("import cadquery as cq\ncq.Workplane().box(1,1,1).val().exportStl('/tmp/x')", "attribute '.exportStl'"),
        ("import cadquery as cq\ncq.occ_impl", "attribute '.occ_impl'"),
        ("import cadquery as cq\ncq.cqgi", "attribute '.cqgi'"),
        ("import cadquery as cq\nx = cq.Workplane().val().wrapped", "attribute '.wrapped'"),
        ("def g():\n    yield 1\nx = g().gi_frame", "generators are not allowed"),
        ("class A:\n    pass", "class definitions"),
        ("with x:\n    pass", "'with' blocks"),
        ("type(1)", "'type' is not allowed"),
        ("x = __builtins__", "names starting with '_'"),
        ("_secret = 1", "names starting with '_'"),
    ],
)
def test_policy_violations(code: str, needle: str) -> None:
    msgs = _messages(code)
    assert any(needle in m for m in msgs), msgs


def test_violation_has_position() -> None:
    v = check_code("x = 1\n\nimport os\n")[0]
    assert (v.line, v.col, v.kind) == (3, 0, "policy")


def test_syntax_error_reports_line() -> None:
    v = check_code("x = 1\ny = (\n")
    assert len(v) == 1 and v[0].kind == "syntax" and v[0].line == 2


def test_unicode_lookalike_names_are_normalised() -> None:
    # Python NFKC-normalises identifiers: bold maths letters spell plain "open".
    assert any("'open' is not allowed" in m for m in _messages("\U0001d428\U0001d429\U0001d41e\U0001d427('x')"))


def test_too_long_program_rejected() -> None:
    assert "too long" in _messages("x = 1\n" * 50_000)[0]
