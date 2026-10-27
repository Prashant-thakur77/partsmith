from __future__ import annotations

from collections.abc import Iterator

import pytest

from eval.program_vs_mesh import Part, render_md, run_part, scaled_program, summarize, template_parts
from services.geom_worker.policy import check_code
from services.geom_worker.sandbox import WarmPool, run_program


@pytest.fixture(scope="module")
def pool() -> Iterator[WarmPool]:
    p = WarmPool(size=1)
    yield p
    p.close()


def _part(name: str) -> Part:
    return next(p for p in template_parts() if p.name == name)


def test_scaled_program_is_a_valid_program_and_scales_uniformly(pool: WarmPool) -> None:
    part = _part("spacer")
    code = scaled_program(part.code, 1.5)
    assert check_code(code) == []
    base = run_program(part.code, part.defaults, pool=pool, outputs=())
    big = run_program(code, part.defaults, pool=pool, outputs=())
    base.cleanup()
    big.cleanup()
    assert base.solid_info is not None and big.solid_info is not None
    assert big.solid_info.volume_mm3 == pytest.approx(base.solid_info.volume_mm3 * 1.5**3, rel=1e-6)
    assert big.solid_info.bbox_mm[2] == pytest.approx(0.0, abs=1e-9)  # still on the mounting face


def test_knob_edit_vs_mesh_scaling_on_the_spacer(pool: WarmPool) -> None:
    rows = run_part(_part("spacer"), pool)
    m4 = {r.way: r for r in rows if r.intent.startswith("M4")}
    knob, mesh = m4["knob edit"], m4["mesh scaling"]
    assert knob.achieved_mm == pytest.approx(4.5, abs=1e-6) and mesh.achieved_mm == pytest.approx(4.5, abs=1e-6)
    assert knob.collateral_mm == pytest.approx(0.0, abs=1e-6)  # only the bore changed
    assert mesh.scale == pytest.approx(4.5 / 3.4, rel=1e-6)
    assert mesh.collateral_mm is not None and mesh.collateral_mm > 2.0  # outer Ø and height grew by 32 %
    s = summarize(rows)
    assert "mesh scaling" in s["headline"] and s["rows"] == len(rows)
    assert "| spacer | M4 hole" in render_md(s, rows)
