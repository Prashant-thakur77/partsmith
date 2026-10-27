from __future__ import annotations

import pytest

from services.geom_worker.program import (
    ProgramError,
    UnknownParamError,
    clamp,
    defaults,
    module_literals,
    parse_params,
    set_defaults,
)


def test_parse_params_reads_the_block_without_exec(plate_code: str) -> None:
    specs = parse_params(plate_code)
    assert [s.name for s in specs] == ["length", "width", "thickness", "hole_d", "hole_count"]
    t = specs[2]
    assert (t.default, t.min, t.max, t.step, t.unit, t.affects_fit, t.label) == (
        3.0, 1.2, 8.0, 0.1, "mm", True, "Plate thickness"
    )  # fmt: skip
    assert not t.topology
    assert specs[4].topology and specs[4].unit == ""


def test_parse_params_never_executes_code() -> None:
    code = 'raise SystemExit("ran")\nPARAMS = {"a": (1.0, 0.0, 2.0, 0.1, "mm", True, "A")}\n'
    assert parse_params(code)[0].name == "a"


@pytest.mark.parametrize(
    "block, msg",
    [
        ("PARAMS = {'a': (1.0, 0.0, 2.0)}", "expected"),
        ("PARAMS = {'a': (3.0, 0.0, 2.0, 0.1, 'mm', True, 'A')}", "outside"),
        ("PARAMS = {'a': (1.0, 0.0, 2.0, 0.0, 'mm', True, 'A')}", "step"),
        ("PARAMS = {'a': (1.0, 0.0, 2.0, 0.1, 'in', True, 'A')}", "unit"),
        ("PARAMS = {'a': (x, 0.0, 2.0, 0.1, 'mm', True, 'A')}", "literal"),
        ("PARAMS = {'_a': (1.0, 0.0, 2.0, 0.1, 'mm', True, 'A')}", "bad parameter name"),
        ("X = 1", "no top-level PARAMS"),
    ],
)
def test_parse_params_rejects_malformed(block: str, msg: str) -> None:
    with pytest.raises(ProgramError, match=msg):
        parse_params(block)


def test_defaults_and_clamp(plate_code: str) -> None:
    d = defaults(plate_code)
    assert d["hole_count"] == 2 and isinstance(d["hole_count"], int)
    specs = parse_params(plate_code)
    out, changed = clamp({"length": 500.0, "hole_count": 2.6, "width": 20.0}, specs)
    assert out["length"] == 120.0 and changed["length"] == 120.0
    assert out["hole_count"] == 3 and isinstance(out["hole_count"], int)
    assert "width" not in changed
    assert out["thickness"] == 3.0  # missing -> default


def test_clamp_unknown_param_lists_closest(plate_code: str) -> None:
    with pytest.raises(UnknownParamError) as ei:
        clamp({"lenght": 30.0}, parse_params(plate_code))
    assert ei.value.closest["lenght"][0] == "length"
    assert "closest: length" in str(ei.value)


def test_set_defaults_round_trip(plate_code: str) -> None:
    new = set_defaults(plate_code, {"length": 55.5, "hole_count": 3, "thickness": 99})
    d = defaults(new)
    assert d["length"] == 55.5 and d["hole_count"] == 3 and d["thickness"] == 8.0
    assert new.count("\n") == plate_code.count("\n")


def test_module_literals() -> None:
    code = 'FAMILY = "clip"\nMEASURE_MAP = {"length": "length"}\nOTHER = 1\n'
    assert module_literals(code, ("FAMILY", "MEASURE_MAP")) == {"FAMILY": "clip", "MEASURE_MAP": {"length": "length"}}
