"""Bake a part program into files, with a content-addressed cache (PLAN §4.2 "live knob rebuild").

Cache key = sha256(code sha, version, sorted clamped params, sorted formats). A hit returns the stored files without
touching the CAD kernel. Each bake also computes printing facts from the mesh:

- mass: SOLID-volume mass at 100 % infill, volume x density (PLA 1.24 g/cm^3, PETG 1.27 g/cm^3). A real print with
  shells and partial infill weighs less.
- print time (rough estimate): minutes = (V / 8 mm^3/s + n_layers x 4 s) / 60, with n_layers = height / 0.2 mm in the
  recommended orientation. 8 mm^3/s is a 0.4 mm nozzle at 0.2 mm layers and 100 mm/s. It assumes 100 % infill.
- supports: for each of the six axis-aligned orientations, the area of faces pointing down more steeply than 45 deg
  that are not on the bed. Recommended orientation = least overhang (then more bed contact, then lower height).
  Supports are needed when that area exceeds 4 mm^2 (small horizontal holes count, although they often bridge).
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import time
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from partsmith_schemas.registry import BakeResult, PartFacts

from services.common.paths import bakes_dir
from services.geom_worker.program import clamp, code_sha, parse_params, set_defaults
from services.geom_worker.sandbox import ExecError, Mesh, WarmPool, run_program

FORMATS = ("stl", "step", "3mf", "glb", "view", "py")
FILE_NAMES = {"stl": "part.stl", "step": "part.step", "3mf": "part.3mf", "glb": "part.glb", "view": "view.json",
              "py": "part.py"}  # fmt: skip
DENSITY_G_CM3 = {"PLA": 1.24, "PETG": 1.27}
FLOW_MM3_S = 8.0
LAYER_MM = 0.2
LAYER_OVERHEAD_S = 4.0
OVERHANG_COS = float(np.cos(np.radians(45.0)))
SUPPORT_AREA_MM2 = 4.0
BED_TOL_MM = 0.1

FACT_NOTES = {
    "mass": "solid-volume mass at 100 % infill (volume x density: PLA 1.24, PETG 1.27 g/cm^3); a real print weighs less",
    "print_minutes_est": "rough estimate: (volume / 8 mm^3/s + layers x 4 s) / 60, 0.2 mm layers, 100 % infill",
    "supports_needed": "faces steeper than 45 deg overhang, off the bed, over 4 mm^2 in the recommended orientation",
    "orientation": "axis-aligned orientation with the least overhang area",
}

# down direction (unit vector in the CAD frame) -> human label
ORIENTATIONS: dict[str, tuple[tuple[float, float, float], str]] = {
    "-Z": ((0.0, 0.0, -1.0), "mounting face (Z=0) on the bed, as modelled"),
    "+Z": ((0.0, 0.0, 1.0), "upside down (top face on the bed)"),
    "-X": ((-1.0, 0.0, 0.0), "-X end on the bed"),
    "+X": ((1.0, 0.0, 0.0), "+X end on the bed"),
    "-Y": ((0.0, -1.0, 0.0), "-Y side on the bed"),
    "+Y": ((0.0, 1.0, 0.0), "+Y side on the bed"),
}


class BakeError(RuntimeError):
    """The program failed to build; `.error` carries the sandbox error (kind, line, message)."""

    def __init__(self, error: ExecError) -> None:
        super().__init__(error.short())
        self.error = error


@dataclass
class BakeOutput:
    cache_key: str
    cache_hit: bool
    ms: int
    files: dict[str, Path]
    params: dict[str, float]
    clamped: dict[str, float]
    facts: PartFacts | None
    version: int
    code_sha: str
    facts_notes: dict[str, str] = field(default_factory=lambda: dict(FACT_NOTES))
    overhang_mm2: dict[str, float] = field(default_factory=dict)

    def to_bake_result(self, part_slug: str, url_for: Callable[[str, Path], str]) -> BakeResult:
        """Registry contract: file URLs come from the caller (the API knows its routes)."""
        return BakeResult(
            cache_key=self.cache_key,
            part_slug=part_slug,
            version=self.version,
            params=self.params,
            clamped=self.clamped,
            artifacts={fmt: url_for(fmt, p) for fmt, p in self.files.items()},
            facts=self.facts,
            cache_hit=self.cache_hit,
            ms=self.ms,
        )


def cache_key(code: str, version: int, params: Mapping[str, float], formats: Iterable[str]) -> str:
    blob = json.dumps(
        {
            "code_sha": code_sha(code),
            "version": int(version),
            "params": [[k, float(params[k])] for k in sorted(params)],
            "formats": sorted(set(formats)),
        },
        separators=(",", ":"),
    )
    return hashlib.sha256(blob.encode()).hexdigest()


def overhang_areas(mesh: Mesh) -> tuple[dict[str, float], dict[str, float], dict[str, float]]:
    """Per orientation: (overhang area mm^2, bed contact area mm^2, build height mm)."""
    v = mesh.vertices
    tri = v[mesh.faces]
    cross = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    area = np.linalg.norm(cross, axis=1) / 2
    normals = np.divide(cross, 2 * area[:, None], out=np.zeros_like(cross), where=area[:, None] > 0)
    over: dict[str, float] = {}
    bed: dict[str, float] = {}
    height: dict[str, float] = {}
    for name, (down, _) in ORIENTATIONS.items():
        d = np.asarray(down)
        h_v = v @ -d  # height above the bed (bed at the minimum)
        h_v = h_v - h_v.min()
        h_tri = h_v[mesh.faces]
        facing_down = normals @ d
        on_bed = h_tri.max(axis=1) <= BED_TOL_MM
        over[name] = float(area[(facing_down >= OVERHANG_COS) & ~on_bed].sum())
        bed[name] = float(area[(facing_down >= 0.999) & on_bed].sum())
        height[name] = float(h_v.max())
    return over, bed, height


def part_facts(volume_mm3: float, mesh: Mesh) -> tuple[PartFacts, dict[str, float]]:
    over, bed, height = overhang_areas(mesh)
    best = min(ORIENTATIONS, key=lambda k: (round(over[k], 1), -round(bed[k], 1), height[k]))
    size = mesh.vertices.max(axis=0) - mesh.vertices.min(axis=0)
    layers = height[best] / LAYER_MM
    minutes = (volume_mm3 / FLOW_MM3_S + layers * LAYER_OVERHEAD_S) / 60.0
    cm3 = volume_mm3 / 1000.0
    facts = PartFacts(
        bbox_mm=(float(size[0]), float(size[1]), float(size[2])),
        volume_mm3=float(volume_mm3),
        mass_g_pla=round(cm3 * DENSITY_G_CM3["PLA"], 2),
        mass_g_petg=round(cm3 * DENSITY_G_CM3["PETG"], 2),
        print_minutes_est=round(minutes, 1),
        supports_needed=over[best] > SUPPORT_AREA_MM2,
        orientation=f"{best}: {ORIENTATIONS[best][1]}",
    )
    return facts, over


def _from_manifest(d: Path, t0: float) -> BakeOutput:
    m = json.loads((d / "manifest.json").read_text())
    return BakeOutput(
        cache_key=m["cache_key"],
        cache_hit=True,
        ms=int((time.perf_counter() - t0) * 1000),
        files={fmt: d / name for fmt, name in m["files"].items()},
        params=m["params"],
        clamped=m["clamped"],
        facts=PartFacts.model_validate(m["facts"]) if m.get("facts") else None,
        version=m["version"],
        code_sha=m["code_sha"],
        facts_notes=m.get("facts_notes", dict(FACT_NOTES)),
        overhang_mm2=m.get("overhang_mm2", {}),
    )


def bake(
    code: str,
    params: Mapping[str, float] | None = None,
    formats: Iterable[str] = ("stl", "step", "view"),
    *,
    version: int = 1,
    pool: WarmPool | None = None,
    timeout_s: float = 20.0,
    root: Path | None = None,
) -> BakeOutput:
    """Build (or fetch from cache) the requested formats for `params` (clamped to PARAMS ranges).

    Raises BakeError when the program fails, program.UnknownParamError for unknown parameter names and ValueError
    for unknown formats.
    """
    t0 = time.perf_counter()
    fmts = sorted(set(formats))
    bad = [f for f in fmts if f not in FORMATS]
    if bad:
        raise ValueError(f"unknown format(s) {bad}; choose from {list(FORMATS)}")
    specs = parse_params(code)
    values, changed = clamp(params or {}, specs)
    key = cache_key(code, version, values, fmts)
    base = root or bakes_dir()
    final = base / key[:2] / key
    if (final / "manifest.json").exists():
        return _from_manifest(final, t0)

    res = run_program(code, values, outputs=[f for f in fmts if f != "py"], features=False, pool=pool,
                      timeout_s=timeout_s)  # fmt: skip
    try:
        if not res.ok or res.mesh is None or res.solid_info is None:
            raise BakeError(res.error or ExecError(kind="runtime", message="the program produced no mesh"))
        facts, over = part_facts(res.solid_info.volume_mm3, res.mesh)
        final.parent.mkdir(parents=True, exist_ok=True)
        tmp = Path(tempfile.mkdtemp(prefix=f".{key[:8]}-", dir=final.parent))
        files: dict[str, str] = {}
        for fmt in fmts:
            name = FILE_NAMES[fmt]
            if fmt == "py":
                (tmp / name).write_text(set_defaults(code, values), encoding="utf-8")
            elif fmt in res.artifacts:
                shutil.copyfile(res.artifacts[fmt], tmp / name)
            else:
                continue
            files[fmt] = name
        manifest = {
            "cache_key": key,
            "code_sha": res.code_sha,
            "version": version,
            "params": values,
            "clamped": changed,
            "files": files,
            "facts": facts.model_dump(mode="json"),
            "facts_notes": FACT_NOTES,
            "overhang_mm2": {k: round(v, 2) for k, v in over.items()},
            "build_ms": res.ms,
            "warnings": res.warnings,
            "versions": res.versions,
        }
        (tmp / "manifest.json").write_text(json.dumps(manifest, indent=1))
        try:
            os.replace(tmp, final)
        except OSError:  # another worker baked the same key first; keep theirs
            shutil.rmtree(tmp, ignore_errors=True)
    finally:
        res.cleanup()
    out = _from_manifest(final, t0)
    out.cache_hit = False
    return out
