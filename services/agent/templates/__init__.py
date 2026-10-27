"""Hand-written family templates: standalone part programs (PLAN §6.4) with module-level metadata.

Each ``<name>.py`` in this directory is a complete part program (``PARAMS``, ``build(p)``, ``result``) plus metadata
constants: ``FAMILY``, ``TITLE``, ``SUMMARY``, ``TAGS`` and ``MEASURE_MAP`` (measured quantity -> the parameter that
controls it, e.g. ``"length": "length"``, ``"hole_1.diameter": "hole_d"``). Programs are read as text and parsed
without executing them; they only ever run inside the geometry sandbox.
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass
from functools import cache
from pathlib import Path

from partsmith_schemas.partspec import Family
from partsmith_schemas.verification import ParamSpec

from services.geom_worker.program import code_sha, module_literals, parse_params

TEMPLATE_DIR = Path(__file__).resolve().parent
_META = ("FAMILY", "TITLE", "SUMMARY", "TAGS", "MEASURE_MAP")


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
    )


@cache
def _all() -> dict[str, Template]:
    files = sorted(p for p in TEMPLATE_DIR.glob("*.py") if p.stem != "__init__")
    return {p.stem: _load(p) for p in files}


def list_templates() -> list[Template]:
    """Every template, sorted by name."""
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


__all__ = ["TEMPLATE_DIR", "Template", "for_family", "get_template", "list_templates"]
