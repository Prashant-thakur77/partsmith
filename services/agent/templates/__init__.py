"""Hand-written family templates: standalone part programs with module-level metadata.

Each ``<name>.py`` in this directory is a complete part program (``PARAMS``, ``build(p)``, ``result``) plus metadata
constants: ``FAMILY``, ``TITLE``, ``SUMMARY``, ``TAGS`` and ``MEASURE_MAP`` (measured quantity -> the parameter that
controls it, e.g. ``"length": "length"``, ``"hole_1.diameter": "hole_d"``). Programs are read as text and parsed
without executing them; they only ever run inside the geometry sandbox.
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path

from partsmith_schemas.partspec import Family
from partsmith_schemas.verification import ParamSpec

from services.geom_worker.program import code_sha, module_literals, parse_params

TEMPLATE_DIR = Path(__file__).resolve().parent
_META = ("FAMILY", "TITLE", "SUMMARY", "TAGS", "MEASURE_MAP")
# A seeded suite picks its parts by position in this list, so a new template here would change which samples a seed
# produces and every stored run would stop matching its suite. Newer templates stay out until the bench is rerun.
BENCH_TEMPLATES = frozenset(
    {
        "battery_cover",
        "cable_clip",
        "caster_wheel",
        "clip",
        "cupboard_latch",
        "hinge_leaf",
        "hook",
        "knob",
        "l_bracket",
        "spacer",
    }
)


@dataclass(frozen=True)
class Template:
    name: str
    family: Family
    title: str
    summary: str
    tags: tuple[str, ...]
    code: str
    params: tuple[ParamSpec, ...]
    measure_map: dict[str, str]
    code_sha: str
    # Optional REGIONS: knob -> boxes in the model's normalised frame where that knob moves the outline, as
    # (plane, a0, a1, b0, b1, effect): plane "xy" (top) / "xz" / "yz" (side); x, y in [-1, 1] of the bounding box
    # half-sizes, z in [0, 1] of the height; effect +1 = raising the knob adds material there, -1 removes, 0 unknown.
    regions: dict[str, tuple[tuple[str, float, float, float, float, int], ...]] = field(default_factory=dict)

    @property
    def defaults(self) -> dict[str, float]:
        return {p.name: (int(p.default) if p.topology else p.default) for p in self.params}

    @property
    def topology_knobs(self) -> list[str]:
        return [p.name for p in self.params if p.topology]

    def param(self, name: str) -> ParamSpec:
        for p in self.params:
            if p.name == name:
                return p
        raise KeyError(name)


def _load(path: Path) -> Template:
    code = path.read_text(encoding="utf-8")
    meta = module_literals(code, _META)
    missing = [k for k in _META if k not in meta]
    if missing:
        raise ValueError(f"template {path.name} lacks {', '.join(missing)}")
    params = tuple(parse_params(code))
    names = {p.name for p in params}
    bad = [v for v in meta["MEASURE_MAP"].values() if v not in names]
    if bad:
        raise ValueError(f"template {path.name}: MEASURE_MAP points at unknown params {bad}")
    regions_lit = module_literals(code, ("REGIONS",)).get("REGIONS") or {}
    bad_r = [k for k in regions_lit if k not in names]
    if bad_r:
        raise ValueError(f"template {path.name}: REGIONS names unknown params {bad_r}")
    regions = {
        str(k): tuple((str(b[0]), float(b[1]), float(b[2]), float(b[3]), float(b[4]), int(b[5])) for b in v)
        for k, v in regions_lit.items()
    }
    return Template(
        name=path.stem,
        family=Family(meta["FAMILY"]),
        title=str(meta["TITLE"]),
        summary=" ".join(str(meta["SUMMARY"]).split()),
        tags=tuple(str(t) for t in meta["TAGS"]),
        code=code,
        params=params,
        measure_map={str(k): str(v) for k, v in meta["MEASURE_MAP"].items()},
        code_sha=code_sha(code),
        regions=regions,
    )


@cache
def _all() -> dict[str, Template]:
    files = sorted(p for p in TEMPLATE_DIR.glob("*.py") if p.stem != "__init__")
    return {p.stem: _load(p) for p in files}


def knobs_at(template: Template, plane: str, a: float, b: float, margin: float = 0.05) -> list[str]:
    """Knobs whose REGIONS box on `plane` contains the normalised point (a, b)."""
    out = []
    for name, boxes in template.regions.items():
        for pl, a0, a1, b0, b1, _ in boxes:
            if pl == plane and a0 - margin <= a <= a1 + margin and b0 - margin <= b <= b1 + margin:
                out.append(name)
                break
    return out


def list_templates() -> list[Template]:
    """The bench's ten templates, sorted by name: what the agent plans with and what the seeded suites draw from."""
    return [t for t in _all().values() if t.name in BENCH_TEMPLATES]


def all_templates() -> list[Template]:
    """Every template, sorted by name: the catalogue people browse, bake and describe parts from."""
    return list(_all().values())


def get_template(name: str) -> Template:
    """Template by name; unknown names raise KeyError listing the closest names."""
    t = _all().get(name)
    if t is None:
        close = difflib.get_close_matches(name, list(_all()), n=3, cutoff=0.3)
        raise KeyError(f"no template {name!r}" + (f" (closest: {', '.join(close)})" if close else ""))
    return t


def for_family(family: Family | str) -> list[Template]:
    """Templates whose FAMILY matches (e.g. "bracket" -> l_bracket)."""
    fam = Family(family)
    return [t for t in _all().values() if t.family == fam]


__all__ = [
    "BENCH_TEMPLATES",
    "TEMPLATE_DIR",
    "Template",
    "all_templates",
    "for_family",
    "get_template",
    "knobs_at",
    "list_templates",
]
