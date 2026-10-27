from __future__ import annotations

from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor

import pytest
from partsmith_schemas.partspec import Family

from services.agent.templates import Template, for_family, get_template, list_templates
from services.geom_worker.policy import check_code
from services.geom_worker.sandbox import ExecResult, WarmPool, run_program

NAMES = {
    "clip", "knob", "l_bracket", "hook", "spacer", "battery_cover", "caster_wheel", "cupboard_latch", "cable_clip",
    "hinge_leaf",
}  # fmt: skip
WORKERS = 4


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
    ts = list_templates()
    assert {t.name for t in ts} == NAMES
    assert len({t.family for t in ts}) == 10
    assert [t.name for t in for_family("bracket")] == ["l_bracket"]
    assert get_template("knob").family == Family.knob
    with pytest.raises(KeyError, match="closest: knob"):
        get_template("knobb")


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
    ts = list_templates()
    for t, r in zip(ts, _run_many(tpool, [(t, t.defaults) for t in ts]), strict=True):
        assert r.ok, f"{t.name}: {r.error}"
        assert r.solid_info is not None and r.solid_info.valid and r.solid_info.n_solids == 1, t.name
        assert r.mesh is not None and r.mesh.trimesh().is_watertight, t.name
        assert r.solid_info.bbox_mm[2] == pytest.approx(0.0, abs=1e-6), f"{t.name}: mounting face must be Z=0"


@pytest.mark.slow
def test_every_param_corner_builds_a_valid_single_solid(tpool: WarmPool) -> None:
    jobs: list[tuple[Template, dict[str, float]]] = []
    for t in list_templates():
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
    for t in list_templates():
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
