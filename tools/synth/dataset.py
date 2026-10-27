"""SYNTHETIC samples: a part (family template or reference object) photographed on a virtual mat, with exact ground truth.

Folder format (one folder per sample):

- `top.jpg` (and `side.jpg` when the part is also photographed lying on its side) — phone-like JPEGs with an EXIF
  35 mm-equivalent focal length, like a real phone photo;
- `meta.json` — only what a USER would know or say (agents may read it);
- `gt.yaml` — exact ground truth (`gt_source: synthetic_exact`): template + params, named dimensions in mm, camera
  K/R/t, part placement. Hidden from agents: only scorers (`eval/`, tests) call `load_gt`.

Everything is deterministic from the seed (same seed → same params, camera, look, noise, bytes).
"""

from __future__ import annotations

import hashlib
import io
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

import numpy as np
import yaml
from numpy.typing import NDArray
from PIL import Image

from services.metrology import testing as T
from services.metrology.calibrate import intrinsics_from_focal35
from services.metrology.mats import MatSpec, get_mat

from . import geometry as G
from .reference_objects import ReferenceObject, get_reference_object, list_reference_objects
from .render import Look, Surface, render_photo

F64 = NDArray[np.float64]
Kind = Literal["template", "reference_object"]

GENERATOR_VERSION = "synth-1"
PRESETS: tuple[str, ...] = ("clean", "tilt", "blur", "glare", "moire", "low-light", "white-part", "paper")
DIFFICULTY = {
    "clean": "easy",
    "paper": "easy",
    "tilt": "medium",
    "blur": "medium",
    "glare": "hard",
    "moire": "hard",
    "low-light": "hard",
    "white-part": "hard",
}
SCREEN_MATS = ("screen-s", "screen-m", "screen-l")
SCREEN_MAT_WEIGHTS = {"screen-s": 0.15, "screen-m": 0.5, "screen-l": 0.35}
SCREEN_PITCH_MM = {"screen-s": 0.06, "screen-m": 0.1, "screen-l": 0.17}  # phone / tablet / laptop pixel pitch
STAGE_MARGIN_MM = 7.0  # the threshold segmenter models the background on a 4 mm band inside the stage border
PART_COLOURS_BGR: tuple[tuple[int, int, int], ...] = (
    (52, 52, 55),  # dark grey
    (30, 30, 32),  # black
    (150, 92, 32),  # blue
    (40, 42, 185),  # red
    (40, 188, 222),  # yellow
    (62, 138, 52),  # green
    (32, 112, 228),  # orange
)
# Low-contrast plastics: white, light grey and beige on a white stage — the "white-part" hard cases.
LIGHT_PART_COLOURS_BGR: tuple[tuple[int, int, int], ...] = (
    (232, 233, 229),  # white
    (222, 224, 224),  # off-white
    (176, 176, 172),  # light grey
    (168, 190, 206),  # beige
)


@dataclass(frozen=True)
class SampleSpec:
    """What to generate. `params=None` samples template params from the seed; `mat_id=None` picks a mat that fits."""

    kind: Kind
    name: str  # template name or reference-object key
    preset: str = "clean"
    params: Mapping[str, float] | None = None
    views: tuple[str, ...] = ("top", "side")
    mat_id: str | None = None
    size: tuple[int, int] = (3000, 2250)
    jpeg_quality: int = 90
    sample_id: str | None = None
    title: str | None = None


@dataclass(frozen=True)
class SampleMeta:
    """`meta.json`: what a user would know about the photos."""

    id: str
    title: str
    kind: str
    origin: str
    mat_id: str
    family_hint: str
    intent: str
    user_thickness_mm: float | None
    difficulty: str
    augmentations: list[str]
    seed: int
    path: Path | None = None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d.pop("path")
        return d

    @classmethod
    def from_dict(cls, d: Mapping[str, Any], path: Path | None = None) -> SampleMeta:
        return cls(
            id=str(d["id"]),
            title=str(d["title"]),
            kind=str(d["kind"]),
            origin=str(d["origin"]),
            mat_id=str(d["mat_id"]),
            family_hint=str(d["family_hint"]),
            intent=str(d["intent"]),
            user_thickness_mm=None if d.get("user_thickness_mm") is None else float(d["user_thickness_mm"]),
            difficulty=str(d["difficulty"]),
            augmentations=[str(a) for a in d.get("augmentations", [])],
            seed=int(d["seed"]),
            path=path,
        )


@dataclass(frozen=True)
class Sample:
    meta: SampleMeta
    photos: dict[str, bytes]  # view -> JPEG bytes


@dataclass(frozen=True)
class GTDim:
    name: str
    view: str
    value_mm: float
    center_mat_mm: tuple[float, float] | None = None  # holes: axis position on the mat (top view), for matching


@dataclass(frozen=True)
class GroundTruth:
    """`gt.yaml` (scorers only)."""

    sample_id: str
    gt_source: str
    kind: str
    name: str
    mat_id: str
    dims: list[GTDim]
    raw: dict[str, Any] = field(default_factory=dict)

    def dim(self, name: str, view: str | None = None) -> GTDim | None:
        for d in self.dims:
            if d.name == name and (view is None or d.view == view):
                return d
        return None

    def dims_for(self, view: str) -> list[GTDim]:
        return [d for d in self.dims if d.view == view]


# ---------------------------------------------------------------- sampling


def _round_step(x: float, step: float) -> float:
    return round(round(x / step) * step, 6) if step > 0 else x


def sample_params(template_name: str, rng: np.random.Generator) -> dict[str, float]:
    """Template params near the defaults (±25 % log-uniform, clipped to the PARAMS range, snapped to the step);
    topology knobs move by at most one from the default."""
    from services.agent.templates import get_template

    t = get_template(template_name)
    out: dict[str, float] = {}
    for p in t.params:
        if p.topology:
            k = int(p.default) + int(rng.integers(-1, 2))
            out[p.name] = float(min(max(k, int(p.min)), int(p.max)))
        else:
            x = p.default * math.exp(float(rng.uniform(-0.25, 0.25))) if p.default > 0 else p.default
            out[p.name] = float(min(max(_round_step(x, p.step), p.min), p.max))
    return out


def ruler_thickness(x_mm: float) -> float:
    """What a user reads off a school ruler: nearest 0.5 mm (never below 0.5)."""
    return max(0.5, round(x_mm * 2) / 2)


def _hull_xy(v: F64) -> F64:
    from scipy.spatial import ConvexHull

    p = np.asarray(v, dtype=np.float64)[:, :2]
    return np.asarray(p[ConvexHull(p).vertices], dtype=np.float64)


def _fits(hull_cad: F64, yaw_deg: float, mat: MatSpec, margin: float) -> tuple[float, float, float, float] | None:
    """Allowed range of the CAD origin on the mat for this yaw, or None if the part does not fit."""
    pl = G.Placement((0.0, 0.0), yaw_deg)
    p = pl.apply_xy(hull_cad)
    st = mat.stage.inset(margin)
    lo_x, hi_x = st.x_mm - p[:, 0].min(), st.x2_mm - p[:, 0].max()
    lo_y, hi_y = st.y_mm - p[:, 1].min(), st.y2_mm - p[:, 1].max()
    if hi_x < lo_x or hi_y < lo_y:
        return None
    return lo_x, hi_x, lo_y, hi_y


def place(hull_cad: F64, mat: MatSpec, rng: np.random.Generator, margin: float) -> G.Placement | None:
    for _ in range(60):
        yaw = float(rng.uniform(0, 360))
        box = _fits(hull_cad, yaw, mat, margin)
        if box is not None:
            x = float(rng.uniform(box[0], box[1]))
            y = float(rng.uniform(box[2], box[3]))
            return G.Placement((round(x, 4), round(y, 4)), round(yaw, 4))
    return None


def choose_mat(hulls: Sequence[tuple[F64, float]], surface: Surface, rng: np.random.Generator) -> str | None:
    """A mat whose stage fits every view's footprint (hull, height). Screens: weighted random among those that fit."""
    cands = ["paper-a4"] if surface == "paper" else list(SCREEN_MATS)
    ok = [m for m in cands if all(_fits_any(h, get_mat(m), _margin(hh)) for h, hh in hulls)]
    if not ok:
        return None
    w = np.array([SCREEN_MAT_WEIGHTS.get(m, 1.0) for m in ok])
    return str(ok[int(rng.choice(len(ok), p=w / w.sum()))])


def _margin(height_mm: float) -> float:
    return STAGE_MARGIN_MM + 0.12 * height_mm  # tall edges project outward (parallax)


def _fits_any(hull: F64, mat: MatSpec, margin: float) -> bool:
    return any(_fits(hull, float(y), mat, margin) is not None for y in np.arange(0.0, 180.0, 7.5))


def sample_camera(
    mat: MatSpec, rng: np.random.Generator, *, tilt_range: tuple[float, float], size: tuple[int, int]
) -> tuple[T.Camera, float]:
    """Phone above the mat: height 220–420 mm, the given tilt, random yaw/roll/aim, ≈ 26 mm-equivalent lens.
    Rejection-samples until the whole mat is in frame. Returns (camera, true 35 mm-equivalent focal)."""
    st = mat.stage
    corners = mat.bounds.inset(-3.0).corners()
    w, h = size
    for attempt in range(400):
        f35 = float(rng.uniform(24.0, 28.0))
        K = intrinsics_from_focal35(f35, size)
        lo_h = 220.0 + 0.5 * attempt
        height = float(rng.uniform(min(lo_h, 420.0), 420.0 + max(0.0, attempt - 200.0)))
        tilt = float(rng.uniform(*tilt_range))
        target = (st.x_mm + st.w_mm / 2 + float(rng.normal(0, 8)), st.y_mm + st.h_mm / 2 + float(rng.normal(0, 8)))
        cam = T.camera_above(
            target,
            height_mm=height,
            tilt_deg=tilt,
            azimuth_deg=float(rng.uniform(0, 360)),
            roll_deg=float(rng.uniform(0, 360)),
            f_px=float(K[0, 0]),
            size=size,
        )
        uv = cam.project(np.c_[corners, np.zeros(len(corners))])
        mx, my = 0.03 * w, 0.03 * h
        if (uv[:, 0] > mx).all() and (uv[:, 0] < w - mx).all() and (uv[:, 1] > my).all() and (uv[:, 1] < h - my).all():
            return cam, f35
    raise RuntimeError(f"could not frame mat {mat.mat_id} in a {w}x{h} photo")


BODY_COLOURS_BGR = ((168, 166, 162), (60, 58, 58), (196, 200, 204))  # laptop body: silver, dark, light
TABLE_COLOURS_BGR = ((70, 92, 120), (40, 60, 90), (150, 150, 145), (96, 110, 128))


def _bgr(c: Sequence[float] | NDArray[np.float64]) -> tuple[float, float, float]:
    return (float(c[0]), float(c[1]), float(c[2]))


def sample_look(preset: str, surface: Surface, mat_id: str, rng: np.random.Generator) -> Look:
    """Appearance for one photo of the given preset (all randomness from `rng`)."""
    u = rng.uniform
    look = Look(surface=surface)
    if surface == "screen":
        cast = np.array([1.0 + u(-0.02, 0.07), 1.0 + u(-0.03, 0.03), 1.0 + u(-0.07, 0.02)])
        look.white_bgr = _bgr(np.clip(np.array([236.0, 234.0, 230.0]) * cast, 0, 252))
        k = u(26, 42)
        look.black_bgr = (k + u(0, 4), k, k)
        look.screen_margin_mm = u(3, 14)
        look.bezel_mm = u(5, 12)
        look.pixel_pitch_mm = SCREEN_PITCH_MM.get(mat_id, 0.1)
        look.grid_amp = u(0.02, 0.06)
        look.backlight_var = u(0.01, 0.04)
        look.shadow_strength = u(0.03, 0.08)
        look.contact_strength = u(0.04, 0.08)
        look.shadow_soft_mm = u(2.0, 4.0)
        look.body_bgr = _bgr(BODY_COLOURS_BGR[int(rng.integers(len(BODY_COLOURS_BGR)))])
    else:
        base = u(205, 228)
        look.white_bgr = (base - u(6, 14), base - u(0, 5), base)
        k = u(28, 45)
        look.black_bgr = (k, k, k + u(0, 3))
        look.paper_texture = u(2.5, 5.0)
        look.lamp_gradient = u(0.06, 0.18)
        look.lamp_dir_deg = u(0, 360)
        look.shadow_strength = u(0.14, 0.28)
        look.contact_strength = u(0.08, 0.14)
        look.shadow_soft_mm = u(1.5, 3.0)
    look.table_bgr = _bgr(TABLE_COLOURS_BGR[int(rng.integers(len(TABLE_COLOURS_BGR)))])
    colour = PART_COLOURS_BGR[int(rng.integers(len(PART_COLOURS_BGR)))]
    look.part_bgr = _bgr(colour)
    az, el = math.radians(u(0, 360)), math.radians(u(50, 80))
    look.light_dir = (math.cos(el) * math.cos(az), math.cos(el) * math.sin(az), -math.sin(el))
    look.ambient = u(0.3, 0.42)
    look.diffuse = u(0.88, 1.0) - look.ambient  # a face turned to the light shows about its albedo, never more
    look.specular, look.shininess = u(0.05, 0.15), u(12, 40)
    look.vignette = u(0.06, 0.2)
    look.blur_px = u(0.3, 0.6)
    look.noise_read, look.noise_shot = u(0.8, 1.8), u(0.03, 0.08)
    if preset == "blur":
        look.blur_px = u(1.4, 2.4)
    elif preset == "glare" and surface == "screen":
        look.glare = (u(20, 180), u(20, 110), u(70, 160), u(8, 22), u(0, 180))
        look.glare_strength = u(0.55, 0.85)
    elif preset == "moire" and surface == "screen":
        look.grid_amp = u(0.25, 0.4)
        look.moire_amp = u(6, 12)
        look.moire_period_px = u(6, 14)
        look.moire_angle_deg = u(0, 180)
    elif preset == "low-light":
        look.exposure = u(0.42, 0.6)
        look.noise_read, look.noise_shot = u(2.5, 3.5), u(0.15, 0.25)
        look.wb_gain = (u(0.8, 0.9), 1.0, u(1.08, 1.18))
    elif preset == "white-part":
        light = LIGHT_PART_COLOURS_BGR[int(rng.integers(len(LIGHT_PART_COLOURS_BGR)))]
        look.part_bgr = _bgr(light)
    return look


# ---------------------------------------------------------------- part resolution


@dataclass
class _Part:
    mesh: G.PartMesh
    title: str
    family_hint: str
    intent: str
    user_thickness_mm: float
    template: str | None
    ref: ReferenceObject | None


def _resolve_part(spec: SampleSpec, rng: np.random.Generator) -> _Part:
    if spec.kind == "reference_object":
        ref = get_reference_object(spec.name)
        mesh = G.build_mesh(ref.code, None, cache_key=f"ref:{ref.key}")
        return _Part(
            mesh,
            ref.title,
            ref.family_hint,
            f"Measure this {ref.title} (reference object).",
            ref.user_thickness_mm,
            None,
            ref,
        )
    from services.agent.templates import get_template

    t = get_template(spec.name)
    last: Exception | None = None
    for _ in range(8):
        params = dict(spec.params) if spec.params is not None else sample_params(t.name, rng)
        try:
            mesh = G.build_mesh(t.code, params, cache_key=f"tpl:{t.name}:{t.code_sha}")
        except G.BuildError as e:
            last = e
            if spec.params is not None:
                break
            continue
        thick_param = t.measure_map.get("thickness")
        thick = mesh.params.get(thick_param, mesh.height_mm) if thick_param else mesh.height_mm
        return _Part(
            mesh,
            t.title,
            t.family.value,
            f"Make a replacement for this broken {t.title.lower()}.",
            ruler_thickness(thick),
            t.name,
            None,
        )
    raise G.BuildError(f"template {spec.name}: no valid build ({last})")


def _face_colours(part: _Part, look: Look, faces_cad_centroids: F64) -> F64 | None:
    if part.ref is None or part.ref.accent_bgr is None:
        return None
    x = faces_cad_centroids[:, 0]
    L = float(part.mesh.vertices[:, 0].max() - part.mesh.vertices[:, 0].min())
    end = np.abs(x) > L / 2 - 1.3
    col = np.tile(np.asarray(look.part_bgr, dtype=np.float64), (len(x), 1))
    col[end] = part.ref.accent_bgr
    return col


# ---------------------------------------------------------------- writing


def _jpeg_bytes(img_bgr: NDArray[np.uint8], quality: int, focal35: int) -> bytes:
    im = Image.fromarray(np.ascontiguousarray(img_bgr[..., ::-1]))
    exif = Image.Exif()
    exif[0x010E] = "SYNTHETIC render (PartSmith synthetic data generator)"  # ImageDescription
    exif[0x0131] = f"partsmith {GENERATOR_VERSION}"  # Software
    exif.get_ifd(0x8769)[0xA405] = int(focal35)  # FocalLengthIn35mmFilm
    buf = io.BytesIO()
    im.save(buf, format="JPEG", quality=int(quality), exif=exif.tobytes(), optimize=False)
    return buf.getvalue()


def _r(x: float, nd: int = 6) -> float:
    return float(round(float(x), nd))


def _mat_list(a: F64, nd: int = 6) -> list[list[float]]:
    return [[_r(v, nd) for v in row] for row in np.asarray(a, dtype=np.float64).reshape(-1, np.shape(a)[-1])]


def default_sample_id(spec: SampleSpec, seed: int) -> str:
    prefix = "ref" if spec.kind == "reference_object" else "syn"
    return f"{prefix}-{spec.name.replace('_', '-')}-{spec.preset}-s{seed}"


def generate_sample(spec: SampleSpec, out_dir: str | Path, *, seed: int) -> Path:
    """Render one sample into `out_dir/<sample_id>/` (top.jpg, optional side.jpg, meta.json, gt.yaml); return that
    folder. Deterministic from `seed`."""
    if spec.preset not in PRESETS:
        raise ValueError(f"unknown preset {spec.preset!r} (known: {', '.join(PRESETS)})")
    rng = np.random.default_rng(np.random.SeedSequence([int(seed), 0x5E7]))
    part = _resolve_part(spec, rng)
    views = [v for v in spec.views if v in ("top", "side")]
    if "top" not in views:
        views.insert(0, "top")
    if part.ref is not None and not part.ref.side_view:
        views = ["top"]
    surface: Surface = "paper" if spec.preset == "paper" else ("paper" if rng.uniform() < 0.2 else "screen")
    if spec.preset in ("glare", "moire"):
        surface = "screen"
    if spec.mat_id is not None:
        surface = "paper" if get_mat(spec.mat_id).kind.value == "paper" else "screen"

    v_top = part.mesh.vertices
    v_side = G.lay_on_side(part.mesh.vertices)
    vert_by_view = {"top": v_top, "side": v_side}
    hulls = [(_hull_xy(vert_by_view[v]), float(vert_by_view[v][:, 2].max())) for v in views]
    mat_id = spec.mat_id or choose_mat(hulls, surface, rng)
    if mat_id is None:
        raise ValueError(f"{spec.name}: the part does not fit any {surface} mat stage")
    mat = get_mat(mat_id)
    sample_id = spec.sample_id or default_sample_id(spec, seed)
    folder = Path(out_dir) / sample_id
    folder.mkdir(parents=True, exist_ok=True)

    faces = part.mesh.faces
    tilt_range = (12.0, 18.0) if spec.preset == "tilt" else (0.0, 8.0)
    gt_views: dict[str, Any] = {}
    files: dict[str, bytes] = {}
    for view in views:
        v_cad = vert_by_view[view]
        hull = _hull_xy(v_cad)
        height = float(v_cad[:, 2].max())
        pl = place(hull, mat, rng, _margin(height))
        if pl is None:
            raise ValueError(f"{spec.name}: {view} view does not fit mat {mat_id}")
        cam, f35 = sample_camera(mat, rng, tilt_range=tilt_range, size=spec.size)
        look = sample_look(spec.preset, surface, mat_id, rng)
        if part.ref is not None and spec.preset != "white-part":
            look.part_bgr = _bgr(part.ref.colour_bgr)
        cen = v_cad[faces].mean(axis=1)
        if view == "side":  # colour lookup in the part's own frame
            cen = part.mesh.vertices[faces].mean(axis=1)
        look.face_bgr = _face_colours(part, look, cen)
        v_mat = pl.apply(v_cad)
        r = render_photo(mat_id, cam, v_mat, faces, look, rng)
        files[f"{view}.jpg"] = _jpeg_bytes(r.image, spec.jpeg_quality, round(f35))
        tilt = math.degrees(math.acos(float(np.clip(cam.R[2, 2], -1, 1))))
        gt_views[view] = {
            "image": f"{view}.jpg",
            "placement": {"center_mm": [_r(c) for c in pl.center_mm], "yaw_deg": _r(pl.yaw_deg)},
            "cad_to_mat": _mat_list(pl.matrix()),
            "part_height_mm": _r(height),
            "camera": {
                "K": _mat_list(cam.K),
                "R": _mat_list(cam.R),
                "t_mm": [_r(x) for x in cam.t],
                "size": list(spec.size),
                "height_mm": _r(cam.height_mm, 3),
                "tilt_deg": _r(tilt, 3),
                "focal35_mm": _r(f35, 4),
                "exif_focal35_mm": round(f35),
            },
            "look": {
                "surface": look.surface,
                "part_bgr": [round(c) for c in look.part_bgr],
                "blur_px": _r(look.blur_px, 3),
                "glare": look.glare is not None,
                "moire_amp": _r(look.moire_amp, 3),
                "exposure": _r(look.exposure, 3),
            },
        }

    dims: list[dict[str, Any]] = []
    top_pl = G.Placement(
        (float(gt_views["top"]["placement"]["center_mm"][0]), float(gt_views["top"]["placement"]["center_mm"][1])),
        float(gt_views["top"]["placement"]["yaw_deg"]),
    )
    for name, val in G.top_dims(part.mesh).items():
        dims.append({"name": name, "view": "top", "value_mm": _r(val)})
    for hole in G.visible_holes(part.mesh):
        c = top_pl.apply_xy(np.array([hole.center_cad_mm]))[0]
        dims.append(
            {
                "name": f"{hole.name}.diameter",
                "view": "top",
                "value_mm": _r(hole.diameter_mm),
                "center_mat_mm": [_r(c[0]), _r(c[1])],
                "center_cad_mm": [_r(x) for x in hole.center_cad_mm],
            }
        )
    sd = G.side_dims(part.mesh)
    if "side" in views:
        dims.append({"name": "thickness", "view": "side", "value_mm": _r(sd["thickness"])})

    preset_augs = [spec.preset] + ([f"surface:{surface}"] if spec.preset != "paper" else [])
    meta = SampleMeta(
        id=sample_id,
        title=spec.title or f"{part.title} (synthetic, {spec.preset})",
        kind=spec.kind,
        origin="synthetic",
        mat_id=mat_id,
        family_hint=part.family_hint,
        intent=part.intent,
        user_thickness_mm=part.user_thickness_mm,
        difficulty=DIFFICULTY[spec.preset],
        augmentations=preset_augs,
        seed=int(seed),
    )
    gt: dict[str, Any] = {
        "gt_source": "synthetic_exact",
        "origin": "synthetic",
        "sample_id": sample_id,
        "kind": spec.kind,
        "name": spec.name,
        "template": part.template,
        "reference_object": part.ref.key if part.ref else None,
        "params": {k: _r(v) for k, v in sorted(part.mesh.params.items())},
        "code_sha": part.mesh.code_sha,
        "mat_id": mat_id,
        "units": "mm",
        "dims": dims,
        "info": {
            "height_mm": _r(part.mesh.height_mm),
            "side_length_mm": _r(sd["side_length"]),
            "user_thickness_mm": part.user_thickness_mm,
            "dim_definitions": "length/width: min-area rectangle of the orthographic top footprint; "
            "hole_k.diameter: see-through openings from above; thickness: short side of the side-view footprint",
        },
        "views": gt_views,
        "generator": {"version": GENERATOR_VERSION, "seed": int(seed), "preset": spec.preset},
    }
    if part.ref is not None:
        gt["spec"] = {
            "loose": part.ref.loose,
            "note": part.ref.spec_note,
            "dims": [asdict(d) for d in part.ref.dims],
        }
    for fname, data in files.items():
        (folder / fname).write_bytes(data)
    for stale in ("top.jpg", "side.jpg"):
        if stale not in files and (folder / stale).exists():
            (folder / stale).unlink()
    (folder / "meta.json").write_text(json.dumps(meta.to_dict(), indent=2) + "\n")
    (folder / "gt.yaml").write_text(yaml.safe_dump(gt, sort_keys=False, width=120, default_flow_style=None))
    return folder


# ---------------------------------------------------------------- datasets


def sha256_file(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def dataset_specs(
    n: int,
    seed: int,
    presets: Sequence[str] | None = None,
    *,
    n_reference: int = 0,
    size: tuple[int, int] = (3000, 2250),
    jpeg_quality: int = 90,
) -> list[tuple[SampleSpec, int]]:
    """The (spec, seed) list `make_dataset` renders: templates round-robin in a seed-shuffled order, presets cycled,
    then reference objects round-robin. Pure: no rendering."""
    from services.agent.templates import list_templates

    pres = list(presets or PRESETS)
    bad = [p for p in pres if p not in PRESETS]
    if bad:
        raise ValueError(f"unknown presets {bad}")
    rng = np.random.default_rng(np.random.SeedSequence([int(seed), 0xB3]))
    seeds = [int(s) for s in np.random.SeedSequence(int(seed)).generate_state(n + n_reference)]
    names = [t.name for t in list_templates()]
    order = [names[i] for i in rng.permutation(len(names))]
    p_off = int(rng.integers(len(pres)))
    out: list[tuple[SampleSpec, int]] = []
    for i in range(n):
        spec = SampleSpec(
            "template", order[i % len(order)], pres[(i + p_off) % len(pres)], size=size, jpeg_quality=jpeg_quality
        )
        out.append((spec, seeds[i] % 1_000_000))
    refs = [r.key for r in list_reference_objects()]
    ref_presets = [p for p in pres if p != "white-part"] or ["clean"]
    for j in range(n_reference):
        spec = SampleSpec(
            "reference_object",
            refs[j % len(refs)],
            ref_presets[(j // len(refs)) % len(ref_presets)],
            size=size,
            jpeg_quality=jpeg_quality,
        )
        out.append((spec, seeds[n + j] % 1_000_000))
    return out


def make_dataset(
    out_root: str | Path,
    *,
    n: int,
    seed: int,
    presets: Sequence[str] | None = None,
    n_reference: int = 0,
    size: tuple[int, int] = (3000, 2250),
    jpeg_quality: int = 90,
    jobs: int = 1,
    progress: bool = False,
) -> dict[str, Any]:
    """Render `n` template samples (+ `n_reference` reference-object samples) into `out_root` and write
    `out_root/manifest.json` (seeds + sha256 of every file). Returns the manifest. `jobs > 1` renders in parallel
    processes; the output is identical either way."""
    root = Path(out_root)
    root.mkdir(parents=True, exist_ok=True)
    entries: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    specs = dataset_specs(n, seed, presets, n_reference=n_reference, size=size, jpeg_quality=jpeg_quality)
    work = [(spec, s, str(root)) for spec, s in specs]
    if jobs > 1 and len(work) > 1:
        from concurrent.futures import ProcessPoolExecutor

        with ProcessPoolExecutor(max_workers=jobs) as ex:
            results = list(ex.map(_generate_one, work, chunksize=1))
    else:
        results = [_generate_one(w) for w in work]
    for i, ((spec, s), (folder_s, err)) in enumerate(zip(specs, results, strict=True)):
        if folder_s is None:
            failures.append({"name": spec.name, "preset": spec.preset, "seed": s, "error": err})
            continue
        folder = Path(folder_s)
        files = {p.name: sha256_file(p) for p in sorted(folder.iterdir()) if p.is_file()}
        entries.append(
            {"id": folder.name, "kind": spec.kind, "name": spec.name, "preset": spec.preset, "seed": s, "files": files}
        )
        if progress:
            print(f"[{i + 1}/{len(specs)}] {folder.name}", flush=True)
    digest = hashlib.sha256(json.dumps([[e["id"], e["files"]] for e in entries], sort_keys=True).encode()).hexdigest()
    manifest: dict[str, Any] = {
        "origin": "synthetic",
        "generator": GENERATOR_VERSION,
        "seed": int(seed),
        "n": int(n),
        "n_reference": int(n_reference),
        "presets": list(presets or PRESETS),
        "size": list(size),
        "jpeg_quality": int(jpeg_quality),
        "samples": entries,
        "failures": failures,
        "dataset_sha256": digest,
    }
    (root / "manifest.json").write_text(json.dumps(manifest, indent=1) + "\n")
    return manifest


def _generate_one(work: tuple[SampleSpec, int, str]) -> tuple[str | None, str]:
    spec, s, root = work
    try:
        return str(generate_sample(spec, root, seed=s)), ""
    except (G.BuildError, ValueError, RuntimeError) as e:
        return None, str(e)


def list_samples(root: str | Path, *, kind: str | None = None) -> list[SampleMeta]:
    """Every sample folder under `root` (sorted by id); reads meta.json only."""
    out: list[SampleMeta] = []
    r = Path(root)
    if not r.exists():
        return out
    for meta_p in sorted(r.glob("*/meta.json")):
        m = SampleMeta.from_dict(json.loads(meta_p.read_text()), meta_p.parent)
        if kind is None or m.kind == kind:
            out.append(m)
    return out


def load_sample(path: str | Path) -> Sample:
    """meta.json + photo bytes of one sample folder. Never reads gt.yaml (safe to hand to an agent)."""
    p = Path(path)
    meta = SampleMeta.from_dict(json.loads((p / "meta.json").read_text()), p)
    photos = {v: (p / f"{v}.jpg").read_bytes() for v in ("top", "side", "mating") if (p / f"{v}.jpg").exists()}
    return Sample(meta=meta, photos=photos)


def load_gt(path: str | Path) -> GroundTruth:
    """Exact ground truth of a sample (SCORERS ONLY: eval/ and tests; never pass this to an agent)."""
    p = Path(path)
    raw = yaml.safe_load((p / "gt.yaml").read_text())
    dims = [
        GTDim(
            name=str(d["name"]),
            view=str(d["view"]),
            value_mm=float(d["value_mm"]),
            center_mat_mm=(float(d["center_mat_mm"][0]), float(d["center_mat_mm"][1]))
            if d.get("center_mat_mm")
            else None,
        )
        for d in raw.get("dims", [])
    ]
    return GroundTruth(
        sample_id=str(raw["sample_id"]),
        gt_source=str(raw["gt_source"]),
        kind=str(raw["kind"]),
        name=str(raw["name"]),
        mat_id=str(raw["mat_id"]),
        dims=dims,
        raw=raw,
    )
