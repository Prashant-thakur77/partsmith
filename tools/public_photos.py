"""Test photos made from PUBLIC photographs of real objects: cut out by code and pasted on our rendered screen mat.

The object's pixels and edges are real; the mat, the screen, the phone camera and the lighting on the mat are rendered
(`tools.synth`). So this is neither a phone capture nor a real photo measured, and the reports never count it as one.

Circularity rule: the paste scale comes from ONE published dimension, the object's long side (or, for a second object
in the same photograph, the first object's long side). That dimension is marked `set_by_construction` in gt.yaml and
is left out of every error. Only the other dimensions and features are held out.

The cut-out is flat. It sits on the plane at the thickness the job is told, so the product's height correction maps
it back to the true outline; it has no walls and casts no shadow.

    uv run python -m tools.public_photos build   [--only id] [--preview out.png]
    uv run python -m tools.public_photos photos  FROM   # bring selected originals in, downsized, no metadata

data/public_photos/manifest.yaml lists the samples, data/public_photos/photos/ holds the photographs and
data/public_photos/samples/<id>/{top.jpg,meta.json,gt.yaml} is generated (deterministic from the manifest, gitignored).
"""

from __future__ import annotations

import argparse
import io
import json
import math
import shutil
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import yaml
from numpy.typing import NDArray
from PIL import Image

from services.metrology.mats import MatSpec, get_mat
from tools.synth.dataset import sample_camera, sample_look
from tools.synth.reference_objects import REFERENCE_OBJECTS
from tools.synth.render import finish_photo, local_px_per_mm, render_surface

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "public_photos"
MANIFEST = DATA / "manifest.yaml"
PHOTOS = DATA / "photos"
SAMPLES = DATA / "samples"

GT_SOURCE = "published_spec_pasted"
MAT_ID = "screen-m"
IMAGE_SIZE = (3000, 2250)
JPEG_QUALITY = 90
MAX_PHOTO_SIDE = 1600
SS = 2  # supersampling of the paste
SHADOW_CHROMA = 18.0  # Lab a/b distance from the background below which a darker pixel can be a shadow
SHADOW_MIN_L = 0.35  # shadows are at least this share of the background's lightness
TILT_RANGE_DEG = (0.0, 8.0)
INTENT = "Measure this object lying on the mat and model it as a plain solid."
SCALE_NOTE = "scale set from one published dimension; that dimension is excluded from the errors"

U8 = NDArray[np.uint8]
F32 = NDArray[np.float32]
F64 = NDArray[np.float64]


@dataclass(frozen=True)
class Spec:
    """Published size of an object, mm. Tolerances `tol_*` are the published range around the nominal, when known."""

    key: str
    title: str
    long_mm: float
    short_mm: float
    thickness_mm: float
    tol_short_mm: float | None = None
    hole_mm: float | None = None
    round_outline: bool = False


def _from_reference(key: str) -> Spec:
    ref = REFERENCE_OBJECTS[key]
    w = ref.dim("width")
    return Spec(key, ref.title, ref.dim("length").nominal_mm, w.nominal_mm, ref.user_thickness_mm, w.tol_mm)


OBJECTS: dict[str, Spec] = {
    **{k: _from_reference(k) for k in ("sd_card", "id1_card", "lego_2x4", "aa_cell")},
    "microsd_card": Spec("microsd_card", "microSD card", 15.0, 11.0, 1.0, 0.1),
    "us_dime": Spec("us_dime", "US dime", 17.91, 17.91, 1.35, round_outline=True),
    "yen_5": Spec("yen_5", "Japanese 5 yen coin", 22.0, 22.0, 1.5, hole_mm=5.0, round_outline=True),
}


@dataclass(frozen=True)
class SampleDef:
    id: str
    object: str
    photo: str
    photo_id: int
    region: tuple[int, int, int, int]  # x0, y0, x1, y1 around the object in the stored photo
    seed: int
    stage: str = "light"
    method: str = "grabcut"  # grabcut | threshold
    thresh_k: float = 1.0  # threshold method: multiple of the Otsu level (lower keeps dim faces of the object)
    scale_from: str | None = None  # id of the sample whose long side sets the scale (same photograph)


def load_manifest(path: Path = MANIFEST) -> list[SampleDef]:
    raw = yaml.safe_load(path.read_text()) if path.exists() else None
    out: list[SampleDef] = []
    for s in (raw or {}).get("samples") or []:
        out.append(
            SampleDef(
                id=str(s["id"]),
                object=str(s["object"]),
                photo=str(s["photo"]),
                photo_id=int(s["photo_id"]),
                region=(int(s["region"][0]), int(s["region"][1]), int(s["region"][2]), int(s["region"][3])),
                seed=int(s["seed"]),
                stage=str(s.get("stage", "light")),
                method=str(s.get("method", "grabcut")),
                thresh_k=float(s.get("thresh_k", 1.0)),
                scale_from=s.get("scale_from"),
            )
        )
    return out


# ------------------------------------------------------------------------------------------------------------ cut-out


def _clean_mask(fg: NDArray[np.bool_], *, keep_holes: bool) -> U8:
    """The largest connected blob with its holes filled (a label can look like background); `keep_holes` keeps the
    largest hole, for an object that has one through-hole."""
    m: U8 = np.asarray(np.asarray(fg, dtype=np.uint8) * 255, dtype=np.uint8)
    k = max(3, int(max(m.shape) / 400) | 1)
    se = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))
    m = np.asarray(cv2.morphologyEx(cv2.morphologyEx(m, cv2.MORPH_OPEN, se), cv2.MORPH_CLOSE, se), dtype=np.uint8)
    n, lab, stats, _ = cv2.connectedComponentsWithStats(m, connectivity=8)
    if n <= 1:
        return np.zeros_like(m)
    biggest = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    blob = np.asarray((lab == biggest) * 255, dtype=np.uint8)
    contours, hier = cv2.findContours(blob, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_NONE)
    out = np.zeros_like(blob)
    for i, c in enumerate(contours):
        if hier[0][i][3] < 0:
            cv2.drawContours(out, [c], -1, 255, cv2.FILLED)
    inner = [c for i, c in enumerate(contours) if hier[0][i][3] >= 0]
    if keep_holes and inner:
        cv2.drawContours(out, [max(inner, key=cv2.contourArea)], -1, 0, cv2.FILLED)
    return out


def cut_out(
    img: U8,
    region: tuple[int, int, int, int],
    *,
    method: str = "grabcut",
    keep_holes: bool = False,
    thresh_k: float = 1.0,
) -> U8:
    """Foreground mask (0/255, full photo) of the object inside `region`, with no model involved."""
    x0, y0, x1, y1 = region
    crop = img[y0:y1, x0:x1]
    if method == "threshold":
        lab = cv2.cvtColor(crop, cv2.COLOR_BGR2LAB).astype(np.float32)
        ring = max(4, min(crop.shape[:2]) // 40)
        edge = np.concatenate(
            [
                lab[:ring].reshape(-1, 3),
                lab[-ring:].reshape(-1, 3),
                lab[:, :ring].reshape(-1, 3),
                lab[:, -ring:].reshape(-1, 3),
            ]
        )
        bg = np.median(edge, axis=0)
        d = np.linalg.norm(lab - bg, axis=2)
        # a cast shadow keeps the background's colour and is only darker: it belongs to the background
        near_bg_colour = np.linalg.norm(lab[..., 1:] - bg[1:], axis=2) < SHADOW_CHROMA
        shadow = near_bg_colour & (lab[..., 0] < bg[0]) & (lab[..., 0] > SHADOW_MIN_L * bg[0])
        d[shadow] = 0.0
        d8 = np.asarray(np.clip(d * 255.0 / max(float(d.max()), 1.0), 0, 255), dtype=np.uint8)
        level, _ = cv2.threshold(d8, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        fg = d8 > level * thresh_k
    else:
        margin = max(4, min(crop.shape[:2]) // 50)
        rect = (margin, margin, crop.shape[1] - 2 * margin, crop.shape[0] - 2 * margin)
        gc = np.zeros(crop.shape[:2], np.uint8)
        bgd, fgd = np.zeros((1, 65), np.float64), np.zeros((1, 65), np.float64)
        cv2.setRNGSeed(0)
        cv2.grabCut(crop, gc, rect, bgd, fgd, 6, cv2.GC_INIT_WITH_RECT)
        fg = (gc == cv2.GC_FGD) | (gc == cv2.GC_PR_FGD)
    full = np.zeros(img.shape[:2], bool)
    full[y0:y1, x0:x1] = fg
    return _clean_mask(full, keep_holes=keep_holes)


def _sample_mask(photo: U8, sd: SampleDef) -> U8:
    has_hole = OBJECTS[sd.object].hole_mm is not None
    return cut_out(photo, sd.region, method=sd.method, keep_holes=has_hole, thresh_k=sd.thresh_k)


def mask_box(mask: U8) -> tuple[float, float, tuple[float, float], float]:
    """(long px, short px, centre, angle of the long side in deg) of the mask's minimum-area rectangle."""
    pts = cv2.findNonZero(mask)
    if pts is None:
        raise ValueError("empty mask")
    (cx, cy), (w, h), ang = cv2.minAreaRect(pts)
    # findNonZero gives pixel centres: the outline is half a pixel further out on each side
    w, h = w + 1.0, h + 1.0
    return (w, h, (cx, cy), ang) if w >= h else (h, w, (cx, cy), ang + 90.0)


# ---------------------------------------------------------------------------------------------------------- composite


def place_on_stage(
    mat: MatSpec, long_mm: float, short_mm: float, rng: np.random.Generator
) -> tuple[float, float, float]:
    """(centre x, centre y, rotation deg) on the mat: a small seeded offset and turn, staying inside the stage."""
    st = mat.stage
    turn = float(rng.uniform(-20.0, 20.0))
    t = math.radians(turn)
    half_x = 0.5 * (long_mm * abs(math.cos(t)) + short_mm * abs(math.sin(t))) + 3.0
    half_y = 0.5 * (long_mm * abs(math.sin(t)) + short_mm * abs(math.cos(t))) + 3.0
    room_x, room_y = max(0.0, st.w_mm / 2 - half_x), max(0.0, st.h_mm / 2 - half_y)
    cx = st.x_mm + st.w_mm / 2 + float(rng.uniform(-min(room_x, 25.0), min(room_x, 25.0)))
    cy = st.y_mm + st.h_mm / 2 + float(rng.uniform(-min(room_y, 15.0), min(room_y, 15.0)))
    return cx, cy, turn


def source_to_mat(
    centre_px: tuple[float, float], angle_deg: float, mm_per_px: float, place: tuple[float, float, float]
) -> F64:
    """3×3 similarity: photograph px → mat mm, long side along the mat's x axis, then the seeded turn."""
    a = math.radians(place[2] - angle_deg)
    c, s = math.cos(a) * mm_per_px, math.sin(a) * mm_per_px
    tx = place[0] - (c * centre_px[0] - s * centre_px[1])
    ty = place[1] - (s * centre_px[0] + c * centre_px[1])
    return np.array([[c, -s, tx], [s, c, ty], [0.0, 0.0, 1.0]], dtype=np.float64)


def paste(surface: F32, photo: U8, mask: U8, H_src_to_img: F64, src_px_per_img_px: float) -> F32:
    """Alpha-blend the cut-out into the rendered surface: area-filtered first, so the edge is a real camera-like edge."""
    h, w = surface.shape[:2]
    alpha = np.asarray(mask, dtype=np.float32) / 255.0
    prem = np.asarray(photo, dtype=np.float32) * alpha[..., None]
    pre = max(1.0, src_px_per_img_px / SS)
    if pre > 1.0:
        size = (max(1, round(photo.shape[1] / pre)), max(1, round(photo.shape[0] / pre)))
        fx, fy = size[0] / photo.shape[1], size[1] / photo.shape[0]
        prem = np.asarray(cv2.resize(prem, size, interpolation=cv2.INTER_AREA), dtype=np.float32)
        alpha = np.asarray(cv2.resize(alpha, size, interpolation=cv2.INTER_AREA), dtype=np.float32)
        # pixel centres: resizing maps x to (x + 0.5) * f - 0.5
        down = np.array([[fx, 0, 0.5 * fx - 0.5], [0, fy, 0.5 * fy - 0.5], [0, 0, 1.0]], dtype=np.float64)
        H_src_to_img = H_src_to_img @ np.linalg.inv(down)
    up = np.array([[SS, 0, 0.5 * SS - 0.5], [0, SS, 0.5 * SS - 0.5], [0, 0, 1.0]], dtype=np.float64)
    H = up @ H_src_to_img
    big = (w * SS, h * SS)
    wp = cv2.warpPerspective(prem, H, big, flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT)
    wa = cv2.warpPerspective(alpha, H, big, flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT)
    wp = cv2.resize(wp, (w, h), interpolation=cv2.INTER_AREA)
    wa = cv2.resize(wa, (w, h), interpolation=cv2.INTER_AREA)
    return np.asarray(surface * (1.0 - wa[..., None]) + wp, dtype=np.float32)


def _jpeg(img: U8, focal35: float) -> bytes:
    im = Image.fromarray(np.ascontiguousarray(img[..., ::-1]))
    exif = Image.Exif()
    exif[0x010E] = "COMPOSITE: public photograph cut out and pasted on a rendered mat, not a phone capture"
    exif.get_ifd(0x8769)[0xA405] = round(focal35)
    buf = io.BytesIO()
    im.save(buf, format="JPEG", quality=JPEG_QUALITY, exif=exif.tobytes())
    return buf.getvalue()


def gt_for(spec: Spec, *, scale_from_self: bool) -> list[dict[str, Any]]:
    """Ground-truth rows. With the scale taken from the object itself, its long side is not held out."""
    length: dict[str, Any] = {"name": "length", "value_mm": spec.long_mm}
    if scale_from_self:
        length["set_by_construction"] = True
    width: dict[str, Any] = {"name": "width", "value_mm": spec.short_mm}
    if spec.tol_short_mm is not None:
        width.update(lo_mm=spec.short_mm - spec.tol_short_mm, hi_mm=spec.short_mm + spec.tol_short_mm)
    rows = [length, width]
    if spec.hole_mm is not None:
        rows.append({"name": "hole_1.diameter", "value_mm": spec.hole_mm})
    return rows


def scored_rows(rows: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    return [r for r in rows if not r.get("set_by_construction")]


def build_sample(
    sd: SampleDef, *, by_id: dict[str, SampleDef], photos: Path = PHOTOS, out_root: Path = SAMPLES
) -> dict[str, Any]:
    spec = OBJECTS[sd.object]
    raw = cv2.imread(str(photos / sd.photo), cv2.IMREAD_COLOR)
    if raw is None:
        raise FileNotFoundError(photos / sd.photo)
    photo: U8 = np.asarray(raw, dtype=np.uint8)
    mask = _sample_mask(photo, sd)
    long_px, short_px, centre, angle = mask_box(mask)
    if sd.scale_from is None:
        scale_long_px, scale_long_mm = long_px, spec.long_mm
    else:
        ref = by_id[sd.scale_from]
        if ref.photo != sd.photo:
            raise ValueError(f"{sd.id}: scale_from must be in the same photograph")
        scale_long_px, scale_long_mm = mask_box(_sample_mask(photo, ref))[0], OBJECTS[ref.object].long_mm
    mm_per_px = scale_long_mm / scale_long_px

    mat = get_mat(MAT_ID)
    rng = np.random.default_rng(sd.seed)
    look = sample_look("clean", "screen", MAT_ID, rng, sd.stage)
    cam, f35 = sample_camera(mat, rng, tilt_range=TILT_RANGE_DEG, size=IMAGE_SIZE)
    surf, _, _ = render_surface(MAT_ID, cam, look, rng)
    place = place_on_stage(mat, long_px * mm_per_px, short_px * mm_per_px, rng)
    H_src_to_mat = source_to_mat(centre, angle, mm_per_px, place)
    H_src_to_img = cam.H_mat_to_img(spec.thickness_mm) @ H_src_to_mat
    src_per_img = (1.0 / mm_per_px) / local_px_per_mm(cam)
    img = finish_photo(paste(surf, photo, mask, H_src_to_img, src_per_img), look, rng)

    out = out_root / sd.id
    out.mkdir(parents=True, exist_ok=True)
    (out / "top.jpg").write_bytes(_jpeg(img, f35))
    meta = {
        "id": sd.id,
        "kind": "public_photo",
        "source": "public_photo",
        "user_thickness_mm": spec.thickness_mm,
        "mat_id": None,
        "intent": INTENT,
    }
    (out / "meta.json").write_text(json.dumps(meta, indent=1) + "\n")
    gt = {
        "gt_source": GT_SOURCE,
        "source": "public_photo",
        "object": spec.key,
        "title": spec.title,
        "photo_id": sd.photo_id,
        "scale_set_by": "long side of this object" if sd.scale_from is None else f"long side of {sd.scale_from}",
        "dims": gt_for(spec, scale_from_self=sd.scale_from is None),
        "cutout": {
            "long_px": round(long_px, 2),
            "short_px": round(short_px, 2),
            "mm_per_px": round(mm_per_px, 5),
            "short_mm": round(short_px * mm_per_px, 3),
            "long_mm": round(long_px * mm_per_px, 3),
        },
    }
    (out / "gt.yaml").write_text(yaml.safe_dump(gt, sort_keys=False))
    return gt


def build_all(samples: Sequence[SampleDef], *, photos: Path = PHOTOS, out_root: Path = SAMPLES) -> list[dict[str, Any]]:
    by_id = {s.id: s for s in load_manifest()} | {s.id: s for s in samples}
    return [build_sample(s, by_id=by_id, photos=photos, out_root=out_root) for s in samples]


def ensure_samples(samples: Sequence[SampleDef] | None = None) -> Path:
    """Generate any sample folder that is missing (the composites are deterministic from the manifest and seeds)."""
    chosen = load_manifest() if samples is None else list(samples)
    missing = [
        s for s in chosen if not (SAMPLES / s.id / "gt.yaml").exists() or not (SAMPLES / s.id / "top.jpg").exists()
    ]
    if missing:
        build_all(missing)
    return SAMPLES


def preview(samples: Sequence[SampleDef], out: Path, *, photos: Path = PHOTOS, cell: int = 480) -> None:
    """Contact sheet for inspection: the mask outline on each photograph, next to the composite."""
    rows = []
    for s in samples:
        photo: U8 = np.asarray(cv2.imread(str(photos / s.photo)), dtype=np.uint8)
        mask = _sample_mask(photo, s)
        vis = photo.copy()
        cnts, _ = cv2.findContours(mask, cv2.RETR_LIST, cv2.CHAIN_APPROX_NONE)
        cv2.drawContours(vis, cnts, -1, (0, 255, 0), max(1, max(photo.shape[:2]) // 600))
        vis = vis[s.region[1] : s.region[3], s.region[0] : s.region[2]]
        comp = cv2.imread(str(SAMPLES / s.id / "top.jpg"))
        panes = []
        for im in (vis, comp):
            if im is None:
                im = np.zeros((10, 10, 3), np.uint8)
            f = cell / max(im.shape[:2])
            small = cv2.resize(im, None, fx=f, fy=f, interpolation=cv2.INTER_AREA)
            pane = np.full((cell, cell, 3), 255, np.uint8)
            pane[: small.shape[0], : small.shape[1]] = small
            cv2.putText(pane, s.id, (4, 16), 0, 0.5, (0, 0, 220), 1)
            panes.append(pane)
        rows.append(np.hstack(panes))
    rows += [np.full_like(rows[0], 255)] if len(rows) % 2 else []
    grid = [np.hstack(rows[i : i + 2]) for i in range(0, len(rows), 2)]
    out.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(out), np.vstack(grid))


def bring_photos(src: Path, dest: Path = PHOTOS) -> list[str]:
    """Copy selected originals `<id>.*` into the repo: downsized to MAX_PHOTO_SIDE, upright, without any metadata."""
    from PIL import ImageOps

    dest.mkdir(parents=True, exist_ok=True)
    got = []
    for p in sorted(src.iterdir()):
        if not p.is_file():
            continue
        with Image.open(p) as raw:
            im = ImageOps.exif_transpose(raw).convert("RGB")
            im.thumbnail((MAX_PHOTO_SIDE, MAX_PHOTO_SIDE), Image.Resampling.LANCZOS)
            im.save(dest / f"{p.stem}.jpg", format="JPEG", quality=92, subsampling=0)
        got.append(p.stem)
    return got


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m tools.public_photos", description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="generate data/public_photos/samples/ from the manifest")
    b.add_argument("--only", action="append", default=None)
    b.add_argument("--preview", type=Path, default=None)
    b.add_argument("--preview-only", action="store_true")
    p = sub.add_parser("photos", help="bring selected originals in (downsized, no metadata)")
    p.add_argument("src", type=Path)
    a = ap.parse_args(argv)
    if a.cmd == "photos":
        print(", ".join(bring_photos(a.src)))
        return 0
    samples = [s for s in load_manifest() if not a.only or s.id in a.only]
    if not a.preview_only:
        if not a.only and SAMPLES.exists():
            shutil.rmtree(SAMPLES)
        for gt, s in zip(build_all(samples), samples, strict=True):
            c = gt["cutout"]
            print(f"{s.id:20s} long {c['long_mm']:7.2f} short {c['short_mm']:7.2f} mm  scale: {gt['scale_set_by']}")
    if a.preview:
        preview(samples, a.preview)
    return 0


if __name__ == "__main__":
    sys.exit(main())
