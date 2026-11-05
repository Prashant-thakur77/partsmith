from __future__ import annotations

import math
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor

import pytest
from partsmith_schemas.partspec import Family

from services.agent.templates import BENCH_TEMPLATES, Template, all_templates, for_family, get_template, list_templates
from services.geom_worker.policy import check_code
from services.geom_worker.sandbox import ExecResult, WarmPool, run_program

BENCH_NAMES = {
    "clip", "knob", "l_bracket", "hook", "spacer", "battery_cover", "caster_wheel", "cupboard_latch", "cable_clip",
    "hinge_leaf",
}  # fmt: skip
NEWER_NAMES = {
    "sliding_battery_door", "drawer_runner", "hinge_pin_bracket", "curtain_ring", "pointer_knob", "lug_cap", "spur_gear",
    "shelf_pin", "chair_glide", "desk_grommet",
}  # fmt: skip
NAMES = BENCH_NAMES | NEWER_NAMES
WORKERS = 2


@pytest.fixture(scope="module")
def tpool() -> Iterator[WarmPool]:
    p = WarmPool(size=WORKERS)
    yield p
    p.close()


def _run(pool: WarmPool, t: Template, params: dict[str, float]) -> ExecResult:
    r = run_program(t.code, params, pool=pool, outputs=(), features=False, timeout_s=30)
    r.cleanup()
    return r


def _run_many(pool: WarmPool, jobs: list[tuple[Template, dict[str, float]]]) -> list[ExecResult]:
    with ThreadPoolExecutor(WORKERS) as ex:
        return list(ex.map(lambda j: _run(pool, j[0], j[1]), jobs))


def test_registry_has_the_ten_families() -> None:
    assert {t.name for t in all_templates()} == NAMES
    assert len({t.family for t in all_templates()}) == 11
    assert sorted(t.name for t in for_family("bracket")) == ["drawer_runner", "l_bracket"]
    assert get_template("knob").family == Family.knob
    with pytest.raises(KeyError, match="closest: knob"):
        get_template("knobb")


def test_seeded_suites_still_draw_from_the_ten_the_stored_runs_used() -> None:
    assert BENCH_TEMPLATES == BENCH_NAMES
    assert [t.name for t in list_templates()] == sorted(BENCH_NAMES)


@pytest.mark.parametrize("name", sorted(NAMES))
def test_template_metadata_and_policy(name: str) -> None:
    t = get_template(name)
    assert check_code(t.code) == []
    assert t.title and t.summary and t.tags
    assert t.topology_knobs, "every template needs a topology knob"
    assert {"length", "width", "thickness"} <= set(t.measure_map)
    names = {p.name for p in t.params}
    assert set(t.measure_map.values()) <= names
    for p in t.params:
        assert p.min <= p.default <= p.max and p.label
        if p.unit == "mm":
            assert p.max <= 200, "units are millimetres"
    lp = t.param(t.measure_map["length"])
    assert lp.min <= lp.default - 1 and lp.default + 1 <= lp.max  # room for the +/-1 mm self-check


def test_every_template_builds_at_defaults(tpool: WarmPool) -> None:
    ts = all_templates()
    for t, r in zip(ts, _run_many(tpool, [(t, t.defaults) for t in ts]), strict=True):
        assert r.ok, f"{t.name}: {r.error}"
        assert r.solid_info is not None and r.solid_info.valid and r.solid_info.n_solids == 1, t.name
        assert r.mesh is not None and r.mesh.trimesh().is_watertight, t.name
        assert r.solid_info.bbox_mm[2] == pytest.approx(0.0, abs=1e-6), f"{t.name}: mounting face must be Z=0"


@pytest.mark.slow
def test_every_param_corner_builds_a_valid_single_solid(tpool: WarmPool) -> None:
    jobs: list[tuple[Template, dict[str, float]]] = []
    for t in all_templates():
        for p in t.params:
            for v in (p.min, p.max):
                jobs.append((t, {**t.defaults, p.name: v}))
    failures = []
    for (t, params), r in zip(jobs, _run_many(tpool, jobs), strict=True):
        changed = {k: v for k, v in params.items() if v != t.defaults[k]}
        if not r.ok or r.solid_info is None or not r.solid_info.valid or r.solid_info.n_solids != 1:
            failures.append(f"{t.name} {changed}: {r.error.short() if r.error else r.solid_info}")
    assert not failures, "\n".join(failures)


@pytest.mark.slow
def test_topology_knobs_change_the_face_count(tpool: WarmPool) -> None:
    jobs: list[tuple[Template, dict[str, float]]] = []
    labels = []
    for t in all_templates():
        for k in t.topology_knobs:
            p = t.param(k)
            jobs += [(t, {**t.defaults, k: p.min}), (t, {**t.defaults, k: p.max})]
            labels.append(f"{t.name}.{k}")
    res = _run_many(tpool, jobs)
    same = []
    for i, label in enumerate(labels):
        lo, hi = res[2 * i], res[2 * i + 1]
        assert lo.solid_info is not None and hi.solid_info is not None, label
        if lo.solid_info.n_faces == hi.solid_info.n_faces:
            same.append(f"{label}: {lo.solid_info.n_faces} faces at min and max")
    assert not same, "\n".join(same)


def test_declared_interfaces_are_measured_on_the_solid(tpool: WarmPool) -> None:
    """Interface gaps come from ray casts on the built solid; they must equal the parameter that sizes them."""
    expected: dict[str, tuple[str, Callable[[dict[str, float]], float]]] = {
        "clip": ("panel_gap", lambda p: p["arm_height"] - min(max(p["hook_overhang"] * 1.5 + 1.0, 1.5), p["arm_height"] - 1.0)),
        "cable_clip": ("cable_channel", lambda p: p["cable_d"]),
        "knob": ("shaft_bore", lambda p: p["bore_d"]),
        "caster_wheel": ("axle_bore", lambda p: p["bore_d"]),
        "hinge_leaf": ("pin_hole", lambda p: p["pin_d"]),
        "hinge_pin_bracket": ("pin_hole", lambda p: p["pin_d"]),
        "pointer_knob": ("shaft_bore", lambda p: p["bore_d"]),
        "spur_gear": ("shaft_bore", lambda p: p["bore_d"]),
    }  # fmt: skip
    ts = [get_template(n) for n in expected]
    results = []
    for t in ts:
        r = run_program(t.code, t.defaults, pool=tpool, outputs=(), timeout_s=30)
        r.cleanup()
        results.append(r)
    for t, r in zip(ts, results, strict=True):
        iid, fn = expected[t.name]
        itf = {i["id"]: i for i in (r.features or {}).get("interfaces", [])}
        assert iid in itf, (t.name, r.warnings)
        assert itf[iid]["gap_mm"] == pytest.approx(fn(t.defaults), abs=0.02), t.name


def _size(pool: WarmPool, name: str, **values: float) -> tuple[float, float, float]:
    t = get_template(name)
    r = _run(pool, t, {**t.defaults, **values})
    assert r.ok and r.solid_info is not None and r.solid_info.valid and r.solid_info.n_solids == 1, (
        name,
        values,
        r.error,
    )
    x0, y0, z0, x1, y1, z1 = r.solid_info.bbox_mm
    return x1 - x0, y1 - y0, z1 - z0


# (template, knob, axis the knob sizes, what that axis should measure for a knob value): a knob must move the solid by
# what it says, measured on the built solid at both ends of its range and a point between them.
SWEEPS: list[tuple[str, str, int, Callable[[float], float], dict[str, float]]] = [
    ("sliding_battery_door", "length", 0, lambda v: v, {}),
    ("sliding_battery_door", "width", 1, lambda v: v, {}),
    ("drawer_runner", "length", 0, lambda v: v, {}),
    ("drawer_runner", "width", 1, lambda v: v, {}),
    ("drawer_runner", "rail_height", 2, lambda v: v + 3.0, {}),
    ("hinge_pin_bracket", "length", 0, lambda v: v, {}),
    ("hinge_pin_bracket", "width", 1, lambda v: v, {}),
    ("hinge_pin_bracket", "lug_height", 2, lambda v: v + 3.0, {}),
    ("curtain_ring", "inner_d", 0, lambda v: v + 8.0, {}),
    ("curtain_ring", "thickness", 2, lambda v: v, {}),
    ("pointer_knob", "skirt_d", 0, lambda v: v + 5.0, {}),
    ("pointer_knob", "height", 2, lambda v: v, {}),
    ("lug_cap", "outer_d", 0, lambda v: v, {"grip_count": 0}),
    ("lug_cap", "height", 2, lambda v: v, {}),
    # the tips of the two teeth on the x axis, each turned off the axis by half the width of its tip
    ("spur_gear", "pitch_d", 0, lambda v: v * (1 + 2 / 24) * math.cos(0.13 * 2 * math.pi / 24), {}),
    ("spur_gear", "thickness", 2, lambda v: v + 4.0, {}),
    ("shelf_pin", "rest_length", 0, lambda v: v, {}),
    ("shelf_pin", "rest_width", 1, lambda v: v, {}),
    ("shelf_pin", "peg_length", 2, lambda v: v + 2.5, {}),
    ("chair_glide", "sole_d", 0, lambda v: v, {}),
    ("chair_glide", "height", 2, lambda v: v, {}),
    ("desk_grommet", "flange_d", 0, lambda v: v, {}),
    ("desk_grommet", "sleeve_depth", 2, lambda v: v + 2.5, {}),
]


@pytest.mark.parametrize(("name", "knob", "axis", "expected", "fixed"), SWEEPS, ids=[f"{s[0]}-{s[1]}" for s in SWEEPS])
def test_newer_template_knob_sweeps_measure_true(
    tpool: WarmPool, name: str, knob: str, axis: int, expected: Callable[[float], float], fixed: dict[str, float]
) -> None:
    spec = get_template(name).param(knob)
    for value in (spec.min, (spec.min + spec.max) / 2, spec.max):
        assert _size(tpool, name, **fixed, **{knob: value})[axis] == pytest.approx(expected(value), abs=0.05), (
            knob,
            value,
        )


def test_newer_template_presets_build_and_stay_in_range(tpool: WarmPool) -> None:
    from services.registry.examples import presets_for

    for name in sorted(NEWER_NAMES):
        t = get_template(name)
        assert presets_for(name), name
        for preset in presets_for(name):
            for knob, value in preset.values.items():
                spec = t.param(knob)
                assert spec.min <= value <= spec.max, (name, preset.id, knob)
            _size(tpool, name, **preset.values)


def test_a_part_from_a_newer_template_says_so_only_as_a_template() -> None:
    """No stored run has verified these: the catalogue ships them as template bakes, with the reason saying nothing checked them."""
    from services.registry.examples import TEMPLATE_SHIP_REASON, template_card

    assert "nothing compared it with a photo" in TEMPLATE_SHIP_REASON
    for name in sorted(NEWER_NAMES):
        assert template_card(get_template(name))["name"] == name
