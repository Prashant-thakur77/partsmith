"""Bake a part program into files, with a content-addressed cache.

Cache key = sha256(code sha, version, sorted clamped params, sorted formats). A hit returns the stored files without
touching the CAD kernel. Each bake also computes printing facts from the mesh:

- mass: SOLID-volume mass at 100 % infill, volume x density (PLA 1.24 g/cm^3, PETG 1.27 g/cm^3). A real print with
  shells and partial infill weighs less.
- print time (rough estimate): minutes = (V / 8 mm^3/s + n_layers x 4 s) / 60, with n_layers = height / 0.2 mm in the
  recommended orientation. 8 mm^3/s is a 0.4 mm nozzle at 0.2 mm layers and 100 mm/s. It assumes 100 % infill.
- supports: for each of the six axis-aligned orientations, the area of faces pointing down more steeply than 45 deg
  (with a 1 deg margin, so 45 deg chamfers do not count) that are not on the bed. Recommended orientation = least overhang (then more bed contact, then lower height).
  Supports are needed when that area exceeds 4 mm^2. The top arcs of a horizontal hole up to 6 mm across bridge
  fine, so they are not counted.

`passport=<id>` (off unless asked for; benches and the job pipeline never pass it) debosses the id into the part after
the program ran (`passport_mark.py`, trusted code in the sandbox child) and keys the cache on it; the mark's report is
stored in the manifest (`BakeOutput.passport`, `passport_report(cache_key)`).
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import shutil
import tempfile
import time
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

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
# A face overhangs when it points down MORE steeply than 45 deg. A 45 deg chamfer prints without supports, and its
# tessellated facets land a hair either side of 45 deg, so the cut-off sits 1 deg past it.
OVERHANG_LIMIT_DEG = 45.0
OVERHANG_MARGIN_DEG = 1.0
OVERHANG_COS = float(np.cos(np.radians(OVERHANG_LIMIT_DEG - OVERHANG_MARGIN_DEG)))
# Bump when the facts rules change: a cached bake made under older rules gets its facts recomputed from its STL.
FACTS_RULE = 4
SUPPORT_AREA_MM2 = 4.0
BED_TOL_MM = 0.1
# A sloped edge at the bed (the bottom fillet of a wheel lying flat, a chamfer steeper than 45 deg) that tops out within
# BED_EDGE_MM of the plate prints as a few first layers stepping outwards, not as an overhang that needs supports. It
# is left out when it is small next to the bed contact (at most BED_EDGE_SHARE of it); a flat ceiling at that height
# (a bridge, facing straight down) still counts.
BED_EDGE_MM = 2.0
BED_EDGE_SHARE = 0.25
FLAT_COS = 0.999
# The top arc of a horizontal hole up to SMALL_HOLE_MAX_DIAMETER_MM across bridges without supports. An overhanging
# patch is such an arc when it fits a concave cylinder (normals pointing at one axis) of at most that diameter, with
# the axis level with the bed and the arc centred on "straight down"; a patch joined to other overhangs (a hole in an
# overhanging ceiling) does not fit, so it still counts.
SMALL_HOLE_MAX_DIAMETER_MM = 6.0
HOLE_FIT_TOL_MM = 0.1
HOLE_AXIS_LEVEL = 0.05  # |axis . down|: the axis is level with the bed
HOLE_ARC_CENTRED_COS = float(np.cos(np.radians(15.0)))  # mean normal of the arc within 15 deg of straight down
HOLE_MIN_SPREAD = 0.15  # rms sideways spread of the normals: a flat patch has none and is not an arc

FACT_NOTES = {
    "mass": "solid-volume mass at 100 % infill (volume x density: PLA 1.24, PETG 1.27 g/cm^3); a real print weighs less",
    "print_minutes_est": "rough estimate: (volume / 8 mm^3/s + layers x 4 s) / 60, 0.2 mm layers, 100 % infill",
    "supports_needed": "faces steeper than 45 deg overhang, off the bed, over 4 mm^2 in the recommended orientation; a "
    "small sloped edge (fillet or chamfer) that tops out within 2 mm of the bed and the top arcs of horizontal holes up "
    "to 6 mm across (they bridge) are not counted",
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
    passport: dict[str, Any] | None = None

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


def cache_key(
    code: str, version: int, params: Mapping[str, float], formats: Iterable[str], passport: str | None = None
) -> str:
    doc: dict[str, Any] = {
        "code_sha": code_sha(code),
        "version": int(version),
        "params": [[k, float(params[k])] for k in sorted(params)],
        "formats": sorted(set(formats)),
    }
    if passport:  # only marked bakes carry the key, so every unmarked key stays what it was
        doc["passport"] = passport
    return hashlib.sha256(json.dumps(doc, separators=(",", ":")).encode()).hexdigest()


def _patches(faces: np.ndarray[Any, Any], sel: np.ndarray[Any, Any]) -> list[np.ndarray[Any, Any]]:
    """Face indices of `sel`, grouped into patches that share an edge (the mesh's vertices are merged)."""
    from scipy.sparse import coo_matrix
    from scipy.sparse.csgraph import connected_components

    idx = np.flatnonzero(sel)
    if idx.size == 0:
        return []
    f = faces[idx]
    edges = np.sort(np.concatenate([f[:, [0, 1]], f[:, [1, 2]], f[:, [2, 0]]]), axis=1)
    owner = np.tile(np.arange(idx.size), 3)
    key = edges[:, 0] * (int(faces.max()) + 1) + edges[:, 1]
    order = np.argsort(key, kind="stable")
    shared = key[order][1:] == key[order][:-1]
    a, b = owner[order][:-1][shared], owner[order][1:][shared]
    graph = coo_matrix((np.ones(a.size), (a, b)), shape=(idx.size, idx.size))
    n, labels = connected_components(graph, directed=False)
    return [idx[labels == i] for i in range(n)]


def small_hole_arc(centroids: np.ndarray[Any, Any], normals: np.ndarray[Any, Any], down: np.ndarray[Any, Any]) -> bool:
    """True when an overhanging patch is the top arc of a horizontal hole of at most SMALL_HOLE_MAX_DIAMETER_MM: its
    normals lie in one plane (cylinder axis = that plane's normal, level with the bed), point at a common axis from a
    radius <= 3 mm (concave: a hole, not a boss) and centre on straight down."""
    if len(normals) < 3:
        return False
    mean = normals.mean(axis=0)
    if float(mean @ down) < HOLE_ARC_CENTRED_COS * float(np.linalg.norm(mean)):
        return False
    _, sv, vt = np.linalg.svd(normals, full_matrices=False)
    if sv[1] / np.sqrt(len(normals)) < HOLE_MIN_SPREAD:
        return False
    axis = vt[-1]
    if abs(float(axis @ down)) > HOLE_AXIS_LEVEL:
        return False
    u = np.cross(axis, down)
    u /= np.linalg.norm(u)
    w = np.cross(axis, u)
    p = np.c_[centroids @ u, centroids @ w].ravel()
    n2 = np.c_[normals @ u, normals @ w]
    # every face centroid p_i = c - r n_i (c the axis in the cross-section plane, r the radius)
    m = np.zeros((2 * len(normals), 3))
    m[0::2, 0] = 1.0
    m[1::2, 1] = 1.0
    m[0::2, 2] = -n2[:, 0]
    m[1::2, 2] = -n2[:, 1]
    sol = np.linalg.lstsq(m, p, rcond=None)[0]
    r = float(sol[2])
    fit = float(np.abs(m @ sol - p).max())
    return 0.0 < r <= SMALL_HOLE_MAX_DIAMETER_MM / 2 + HOLE_FIT_TOL_MM / 2 and fit <= HOLE_FIT_TOL_MM


def overhang_areas(mesh: Mesh) -> tuple[dict[str, float], dict[str, float], dict[str, float]]:
    """Per orientation: (overhang area mm^2, bed contact area mm^2, build height mm)."""
    v = mesh.vertices
    tri = v[mesh.faces]
    cross = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    area = np.linalg.norm(cross, axis=1) / 2
    normals = np.divide(cross, 2 * area[:, None], out=np.zeros_like(cross), where=area[:, None] > 0)
    centroids = tri.mean(axis=1)
    over: dict[str, float] = {}
    bed: dict[str, float] = {}
    height: dict[str, float] = {}
    for name, (down, _) in ORIENTATIONS.items():
        d = np.asarray(down)
        h_v = v @ -d  # height above the bed (bed at the minimum)
        h_v = h_v - h_v.min()
        h_tri = h_v[mesh.faces]
        facing_down = normals @ d
        top = h_tri.max(axis=1)
        on_bed = top <= BED_TOL_MM
        steep = (facing_down >= OVERHANG_COS) & ~on_bed
        contact = float(area[(facing_down >= FLAT_COS) & on_bed].sum())
        edge = steep & (top <= BED_EDGE_MM) & (facing_down < FLAT_COS)
        if float(area[edge].sum()) <= BED_EDGE_SHARE * contact:
            steep &= ~edge
        for patch in _patches(mesh.faces, steep):
            if small_hole_arc(centroids[patch], normals[patch], d):
                steep[patch] = False
        over[name] = float(area[steep].sum())
        bed[name] = contact
        height[name] = float(h_v.max())
    return over, bed, height


def part_facts(volume_mm3: float, mesh: Mesh) -> tuple[PartFacts, dict[str, float]]:
    over, bed, height = overhang_areas(mesh)
    # overhang differences under SUPPORT_AREA_MM2 are ties (a tessellation hair should not stand a bracket on its end)
    best = min(ORIENTATIONS, key=lambda k: (int(over[k] // SUPPORT_AREA_MM2), -round(bed[k], 1), height[k]))
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
    if m.get("facts") and m.get("facts_rule") != FACTS_RULE:
        m = _refresh_facts(d, m)
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
        passport=m.get("passport"),
    )


def _refresh_facts(d: Path, m: dict[str, Any]) -> dict[str, Any]:
    """Recompute a cached bake's facts under the current rules from its STL (same mesh, same volume); left as it was
    when the bake has no STL or the STL does not load."""
    stl = d / m.get("files", {}).get("stl", "")
    if not stl.is_file():
        return m
    try:
        import trimesh

        tm = trimesh.load_mesh(stl, file_type="stl", process=True)
        mesh = Mesh(vertices=np.asarray(tm.vertices, dtype=np.float64), faces=np.asarray(tm.faces, dtype=np.int64))
        facts, over = part_facts(float(m["facts"]["volume_mm3"]), mesh)
    except Exception:
        return m
    m = {**m, "facts": facts.model_dump(mode="json"), "facts_notes": FACT_NOTES, "facts_rule": FACTS_RULE,
         "overhang_mm2": {k: round(v, 2) for k, v in over.items()}}  # fmt: skip
    with contextlib.suppress(OSError):  # a read-only cache still answers with the refreshed facts
        (d / "manifest.json").write_text(json.dumps(m, indent=1))
    return m


def passport_report(key: str, root: Path | None = None) -> dict[str, Any] | None:
    """The passport mark's report stored with a bake (None for an unmarked or unknown bake)."""
    if len(key) != 64 or any(c not in "0123456789abcdef" for c in key):
        return None
    f = (root or bakes_dir()) / key[:2] / key / "manifest.json"
    if not f.exists():
        return None
    rep = json.loads(f.read_text()).get("passport")
    return rep if isinstance(rep, dict) else None


def bake(
    code: str,
    params: Mapping[str, float] | None = None,
    formats: Iterable[str] = ("stl", "step", "view"),
    *,
    version: int = 1,
    pool: WarmPool | None = None,
    timeout_s: float = 20.0,
    root: Path | None = None,
    passport: str | None = None,
) -> BakeOutput:
    """Build (or fetch from cache) the requested formats for `params` (clamped to PARAMS ranges). `passport`
    debosses that id into the part where it is safe (see the module docstring); unset, nothing changes.

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
    key = cache_key(code, version, values, fmts, passport)
    base = root or bakes_dir()
    final = base / key[:2] / key
    if (final / "manifest.json").exists():
        return _from_manifest(final, t0)

    res = run_program(code, values, outputs=[f for f in fmts if f != "py"], features=False, pool=pool,
                      timeout_s=timeout_s, passport=passport)  # fmt: skip
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
            "facts_rule": FACTS_RULE,
            "overhang_mm2": {k: round(v, 2) for k, v in over.items()},
            "build_ms": res.ms,
            "warnings": res.warnings,
            "versions": res.versions,
        }
        if passport:
            manifest["passport"] = res.passport or {"text": passport, "applied": False, "reason": "no report"}
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
