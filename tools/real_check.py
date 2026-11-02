"""Photo day: bring phone exports into `data/real/` and check every folder offline before a bench run.

    python -m tools.real_check check  [--root data/real] [--json] [--no-part-check]   (= make real-check)
    python -m tools.real_check intake FROM [--root data/real] [--reencode] [--force] [--dry-run]   (= make real-intake)

`check` makes no model calls. For every `data/real/<part>/` and `data/real/reference_objects/<object>/` it validates
gt.yaml (ruler ground truth, mm, plausible values) and runs on each photo the same capture gate the /fix job runs
before any paid call (markers, reprojection, blur, tilt, exposure, glare, moiré, scale; EXIF orientation applied the
way every decode applies it). A second, advisory pass measures the photo with the deterministic threshold segmenter
(no model) to check that the part is found, stands clear of the markers and lies alone on the stage, and to compare a
rough length/width with gt.yaml (catches a typo or swapped photos; SAM 3.1 does the real cut). Exit code 1 when any
folder is unusable (the bench would skip it or the job would refuse its top photo).

`intake` copies a loose folder of phone photos into the layout the bench reads. Which photo is which comes from
`FROM/parts.csv` (`file,part,view`, header optional) or else from file names `<part>_<view>[_<n>].<ext>` with view
`top`, `side` or `context` (e.g. `cupboard-latch_top.jpg`, `id1_card_top_3.jpg`). A part named like a reference object
(`id1_card`, `sd_card`, `lego_2x4`, `aa_cell`) goes to `reference_objects/<object>/<view>_<n>.jpg`. Privacy: the EXIF
block is rewritten to keep only the orientation and the focal-length tags (camera intrinsics are estimated from the
35 mm focal length); GPS, dates, device and serial fields, XMP and maker notes are dropped. JPEG pixels are kept as
they are by default (re-encoding costs measurement accuracy, the same rule as the /fix upload); `--reencode`, or a
PNG/WebP input, writes an upright JPEG (quality 95, 4:4:4) instead. HEIC photos need converting to JPEG first. A
gt.yaml template with TODO values is written next to new part photos; an existing gt.yaml is never touched.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import re
import sys
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

import yaml

ROOT = Path(__file__).resolve().parents[1]
REAL_DIR = ROOT / "data" / "real"
REF_DIR_NAME = "reference_objects"
PART_VIEWS = ("top", "side", "context")
GATED_VIEWS = ("top", "side")
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif"}
HEIC_BRANDS = {b"heic", b"heix", b"hevc", b"hevx", b"heim", b"heis", b"mif1", b"msf1", b"avif"}
HEIC_HINT = (
    "convert it to JPEG first (iPhone: Settings > Camera > Formats > Most Compatible, or share/export as JPEG; "
    "Linux: `heif-convert in.heic out.jpg`)"
)
PART_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
NAMED = re.compile(r"^(?P<part>.+?)[_-](?P<view>top|side|context)(?:[_-]?(?P<n>\d+))?$", re.IGNORECASE)
GT_DIMS = ("length", "width", "thickness")
DIM_MAX_MM = 300.0
DIM_MIN_MM = 1.0
UNC_TYPICAL_MM = (0.5, 2.0)
# The rough photo measurement (threshold segmenter, no model) is only a typo / swapped-photo / cm-for-mm check: it is
# flagged when it disagrees with the ruler by more than both of these (tall parts read a few mm wide from above).
ROUGH_ABS_MM = 5.0
ROUGH_REL = 0.30
MIN_SIDE_PX = 200
JPEG_QUALITY = 95
ORIENTATION_TAG = 0x0112
EXIF_IFD = 0x8769
KEEP_EXIF_TAGS = (0x920A, 0xA405)  # FocalLength, FocalLengthIn35mmFilm

Level = Literal["error", "warn"]


@dataclass
class Issue:
    level: Level
    where: str  # "top", "side", "context", "gt.yaml", "folder" or a reference photo's file name
    message: str
    fix: str = ""


@dataclass
class PhotoReport:
    file: str
    view: str
    exif_orientation: int = 1
    size_px: tuple[int, int] | None = None
    markers: int | None = None
    markers_total: int | None = None
    tilt_deg: float | None = None
    gate_passed: bool | None = None
    checks: list[dict[str, Any]] = field(default_factory=list)
    part_checks: list[dict[str, Any]] = field(default_factory=list)
    rough_mm: dict[str, float] = field(default_factory=dict)


@dataclass
class FolderReport:
    name: str
    kind: Literal["part", "reference"]
    path: str
    photos: list[PhotoReport] = field(default_factory=list)
    gt_ok: bool | None = None  # None: no gt.yaml expected (reference objects)
    issues: list[Issue] = field(default_factory=list)

    @property
    def usable(self) -> bool:
        return not any(i.level == "error" for i in self.issues)

    def add(self, level: Level, where: str, message: str, fix: str = "") -> None:
        self.issues.append(Issue(level, where, message, fix))

    def to_json(self) -> dict[str, Any]:
        d = asdict(self)
        d["usable"] = self.usable
        return d


# ------------------------------------------------------------------------------------------------------- file sniffing


def is_heic(data: bytes) -> bool:
    """HEIF/HEIC/AVIF container (ISO BMFF `ftyp` box with an image brand), whatever the file is called."""
    return len(data) >= 12 and data[4:8] == b"ftyp" and data[8:12] in HEIC_BRANDS


def image_format(data: bytes) -> str | None:
    """PIL format name (JPEG, PNG, WEBP, ...) after a full decode; None when the bytes do not decode."""
    from PIL import Image

    try:
        with Image.open(io.BytesIO(data)) as im:
            fmt = im.format
            im.load()
    except Exception:
        return None
    return fmt


def has_gps(data: bytes) -> bool:
    from PIL import Image

    try:
        with Image.open(io.BytesIO(data)) as im:
            return 0x8825 in im.getexif()
    except Exception:
        return False


# ------------------------------------------------------------------------------------------------------------ gt.yaml


def _num(v: Any) -> float | None:
    if isinstance(v, bool) or not isinstance(v, int | float):
        return None
    f = float(v)
    return f if math.isfinite(f) else None


def check_gt(path: Path, rep: FolderReport) -> dict[str, Any]:
    """Validate a part's gt.yaml into `rep`; returns the parsed values the photo checks use."""
    where = "gt.yaml"
    n_err = sum(i.level == "error" for i in rep.issues)
    out: dict[str, Any] = {}
    if not path.exists():
        rep.add("error", where, "missing: the bench skips a part without ground truth",
                "measure with a ruler and write gt.yaml (`make real-intake` writes a template)")  # fmt: skip
        rep.gt_ok = False
        return out
    text = path.read_text(encoding="utf-8", errors="replace")
    try:
        raw = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None)
        at = f" (line {mark.line + 1})" if mark is not None else ""
        rep.add("error", where, f"does not parse as YAML{at}", "fix the YAML syntax")
        rep.gt_ok = False
        return out
    if not isinstance(raw, dict):
        rep.add("error", where, "is not a YAML mapping", "start from the template in docs/HANDOFF.md")
        rep.gt_ok = False
        return out
    if re.search(r"\bTODO\b", _strip_comments(text)):
        rep.add("error", where, "still has TODO values", "replace every TODO with a ruler reading in mm")
    src = raw.get("gt_source")
    if src != "ruler":
        rep.add("error", where, f"gt_source is {src!r}: the real-part bench only reads `gt_source: ruler`",
                "set `gt_source: ruler` (never call a ruler reading caliper accuracy)")  # fmt: skip
    unc = _num(raw.get("uncertainty_mm"))
    if "uncertainty_mm" not in raw:
        rep.add("error", where, "uncertainty_mm is missing", "add `uncertainty_mm: 0.5` (school ruler)")
    elif unc is None or unc <= 0:
        rep.add("error", where, f"uncertainty_mm must be a positive number, got {raw.get('uncertainty_mm')!r}")
    elif not UNC_TYPICAL_MM[0] <= unc <= UNC_TYPICAL_MM[1]:
        rep.add("warn", where, f"uncertainty_mm {unc:g} is outside the usual {UNC_TYPICAL_MM[0]:g}–"
                f"{UNC_TYPICAL_MM[1]:g} mm of a ruler reading", "use 0.5 unless you have a reason")  # fmt: skip
    dims_raw = raw.get("dims")
    dims: dict[str, float] = {}
    if not isinstance(dims_raw, dict):
        rep.add(
            "error", where, "dims is missing or not a mapping", "add `dims: {length: .., width: .., thickness: ..}`"
        )
    else:
        for k, v in dims_raw.items():
            if k not in GT_DIMS:
                rep.add("warn", where, f"dims.{k} is not scored (the bench reads length, width, thickness)")
                continue
            f = _num(v)
            if f is None or f <= 0:
                if not (isinstance(v, str) and "TODO" in v):
                    rep.add("error", where, f"dims.{k} must be a positive number in mm, got {v!r}")
                continue
            dims[k] = f
            if f > DIM_MAX_MM:
                rep.add("warn", where, f"dims.{k} = {f:g} mm is over {DIM_MAX_MM:g} mm (cm or inches by mistake?)")
            elif f < DIM_MIN_MM:
                rep.add("warn", where, f"dims.{k} = {f:g} mm is under {DIM_MIN_MM:g} mm (cm by mistake?)")
        for k in ("length", "width"):
            if k not in dims_raw:
                rep.add("error", where, f"dims.{k} is missing: the top view is scored on length and width")
        if "length" in dims and "width" in dims and dims["length"] < dims["width"]:
            rep.add("warn", where, f"length {dims['length']:g} < width {dims['width']:g}: length is the longer side "
                    "seen from above", "swap them")  # fmt: skip
    holes = raw.get("holes", [])
    diameters: list[float] = []
    if holes is None:
        holes = []
    if not isinstance(holes, list):
        rep.add("error", where, "holes must be a list, e.g. `holes: [{diameter: 4.0}]` (or `holes: []`)")
    else:
        for i, h in enumerate(holes):
            d = _num(h.get("diameter")) if isinstance(h, dict) else None
            if d is None or d <= 0:
                rep.add("error", where, f"holes[{i}] must be a mapping with a positive `diameter` in mm, got {h!r}")
                continue
            diameters.append(d)
            if d < DIM_MIN_MM:
                rep.add("warn", where, f"holes[{i}].diameter = {d:g} mm is under {DIM_MIN_MM:g} mm")
            if "width" in dims and d >= dims["width"]:
                rep.add("warn", where, f"holes[{i}].diameter {d:g} mm is not smaller than the width {dims['width']:g}")
    ut = raw.get("user_thickness_mm")
    thick: float | None = None
    if ut is not None:
        thick = _num(ut)
        if thick is None or thick <= 0:
            if not (isinstance(ut, str) and "TODO" in ut):
                rep.add("error", where, f"user_thickness_mm must be a positive number in mm, got {ut!r}")
            thick = None
    if thick is not None and "thickness" in dims and thick > dims["thickness"] + (unc or 0.5):
        rep.add("warn", where, f"user_thickness_mm {thick:g} is more than the overall thickness "
                f"{dims['thickness']:g}: the plate cannot be thicker than the whole part", "check both readings")  # fmt: skip
    if thick is None and not (isinstance(ut, str) and "TODO" in ut):
        rep.add("warn", where, "no user_thickness_mm: the full-loop bench then gives the job no thickness (it takes "
                "its default answer)", "add the plate thickness you would type into /fix")  # fmt: skip
    mat_id = raw.get("mat_id")
    if mat_id is not None:
        from services.metrology.mats import get_mat

        try:
            get_mat(str(mat_id))
            out["mat_id"] = str(mat_id)
        except KeyError as exc:
            rep.add("error", where, str(exc).strip("'\""), "fix mat_id or delete the line (the mat is auto-detected)")
    rep.gt_ok = sum(i.level == "error" for i in rep.issues) == n_err
    out.update(dims=dims, holes=diameters, thickness_mm=thick if thick is not None else dims.get("thickness"))
    return out


def _strip_comments(text: str) -> str:
    return "\n".join(line.split("#", 1)[0] for line in text.splitlines())


# ------------------------------------------------------------------------------------------------------------- photos


def check_photo(
    path: Path,
    view: str,
    rep: FolderReport,
    *,
    where: str,
    mat_id: str | None = None,
    thickness_mm: float | None = None,
    gt_dims: dict[str, float] | None = None,
    part_check: bool = True,
    required: bool = True,
) -> PhotoReport | None:
    """Gate one photo exactly as the /fix capture stage does (`services.agent.orchestrator` `capture`). `required`:
    a failed gate makes the folder unusable (top photos, reference photos); otherwise it is a warning (the job drops
    a side photo that fails and goes on with the top view)."""
    from services.common.images import exif_orientation
    from services.metrology.calibrate import MatNotFoundError, detect_mat, estimate_pose
    from services.metrology.capture_gate import run_gate
    from services.metrology.measure import decode_image

    data = path.read_bytes()
    pr = PhotoReport(file=path.name, view=view)
    if is_heic(data):
        rep.add("error", where, f"{path.name} is a HEIC photo, which nothing here reads", HEIC_HINT)
        return None
    fmt = image_format(data)
    if fmt is None:
        rep.add("error", where, f"{path.name} does not decode as an image", "re-export the photo")
        return None
    if fmt != "JPEG":
        rep.add("warn", where, f"{path.name} is a {fmt} file with a .jpg name",
                "run `make real-intake` on the original to write a real JPEG")  # fmt: skip
    if has_gps(data):
        rep.add("warn", where, f"{path.name} carries a GPS location in its EXIF",
                "bring it in with `make real-intake` (strips location, dates and device fields)")  # fmt: skip
    pr.exif_orientation = exif_orientation(data)
    img = decode_image(data)
    pr.size_px = (int(img.shape[1]), int(img.shape[0]))
    if min(pr.size_px) < MIN_SIDE_PX:
        rep.add("error", where, f"{path.name} is only {pr.size_px[0]}x{pr.size_px[1]} px", "send the full-size photo")
        return pr
    if view == "context":
        return pr
    try:
        det = detect_mat(img, mat_id=mat_id)
    except MatNotFoundError:
        det = None
    pose = None
    if det is not None:
        pr.markers, pr.markers_total = det.n_markers, len(det.mat.markers)
        try:
            pose = estimate_pose(det)
            pr.tilt_deg = round(float(pose.tilt_deg), 1)
        except Exception:
            pose = None
    gate = run_gate(img, det, None, pose=pose)
    pr.gate_passed = gate.passed
    pr.checks = [c.model_dump(mode="json") for c in gate.checks]
    if not gate.passed:
        level: Level = "error" if required else "warn"
        what = "" if required else " (the job would drop it and use the top view only)"
        rep.add(level, where, f"capture gate refuses {path.name}{what}: {gate.retake_reason}", f"retake {where}")
    for c in gate.checks:
        if c.severity == "warn":
            rep.add("warn", where, f"{c.name}: {c.reason}")
    if part_check and det is not None:
        _part_check(data, view, pr, rep, where=where, mat_id=mat_id, thickness_mm=thickness_mm, gt_dims=gt_dims)
    return pr


def _part_check(
    data: bytes,
    view: str,
    pr: PhotoReport,
    rep: FolderReport,
    *,
    where: str,
    mat_id: str | None,
    thickness_mm: float | None,
    gt_dims: dict[str, float] | None,
) -> None:
    """Advisory: the deterministic threshold segmenter (no model) finds the part, the mask-based gate checks run, and
    a rough top-view length/width is compared with gt.yaml. SAM 3.1 makes the real cut, so nothing here is an error."""
    from services.metrology.measure import measure_photo
    from services.metrology.segment import ThresholdSegmenter

    note = "(rough check with the threshold mask, no model; SAM 3.1 may still cut it)"
    try:
        mo = measure_photo(data, view, segmenter=ThresholdSegmenter(), thickness_mm=thickness_mm, mat_id=mat_id)
    except Exception as exc:  # advisory only: never let it hide the gate result
        rep.add("warn", where, f"part check could not run ({type(exc).__name__}) {note}")
        return
    part = [c for c in mo.result.capture.checks if c.name in ("coverage", "contrast", "single_part")]
    pr.part_checks = [c.model_dump(mode="json") for c in part]
    for c in part:
        if c.severity == "fail":
            rep.add("warn", where, f"{c.name}: {c.reason} {note}")
    m = mo.result.measurements
    if mo.footprint_mat is None or m is None:
        rep.add("warn", where, f"no part found on the stage {note}", f"check that the part is on the stage in {where}")
        return
    pr.rough_mm = {"length": round(m.length.value, 1), "width": round(m.width.value, 1)}
    if view != "top" or not gt_dims:
        return
    for k in ("length", "width"):
        if k not in gt_dims:
            continue
        g, r = gt_dims[k], pr.rough_mm[k]
        if abs(r - g) > max(ROUGH_ABS_MM, ROUGH_REL * g):
            rep.add("warn", "gt.yaml", f"dims.{k} {g:g} mm vs about {r:g} mm in top.jpg {note}",
                    f"re-check the ruler reading of {k} (or that top.jpg shows this part)")  # fmt: skip


# ------------------------------------------------------------------------------------------------------------ folders


def _photo_variants(d: Path, view: str) -> list[Path]:
    """Files that look like `view` but are not the exact `view.jpg` the bench reads (TOP.JPG, top.jpeg, top.heic)."""
    return sorted(
        p for p in d.iterdir()
        if p.is_file() and p.stem.lower() == view and p.suffix.lower() in IMAGE_EXTS and p.name != f"{view}.jpg"
    )  # fmt: skip


def check_part(d: Path, *, part_check: bool = True) -> FolderReport:
    rep = FolderReport(name=d.name, kind="part", path=str(d))
    if not PART_ID.match(d.name):
        rep.add("warn", "folder", f"folder name {d.name!r} is not a plain id (lowercase letters, digits, - and _)")
    gt = check_gt(d / "gt.yaml", rep)
    dims: dict[str, float] = gt.get("dims", {})
    for view in PART_VIEWS:
        p = d / f"{view}.jpg"
        for v in _photo_variants(d, view):
            hint = HEIC_HINT if v.suffix.lower() in (".heic", ".heif") else f"rename or convert it to {view}.jpg"
            rep.add("error" if view == "top" and not p.exists() else "warn", view,
                    f"{v.name} is not read: the bench reads only {view}.jpg", hint)  # fmt: skip
        if not p.exists():
            if view == "top" and not _photo_variants(d, view):
                rep.add("error", "top", "top.jpg is missing (the part lying flat on the stage)", "take the top photo")
            continue
        if view == "side":
            thick = dims.get("width")  # the side view's top face is the width seen from above
            if "thickness" not in dims:
                rep.add("warn", "side", "side.jpg is not scored without dims.thickness in gt.yaml")
        else:
            thick = gt.get("thickness_mm")
        pr = check_photo(p, view, rep, where=view, mat_id=gt.get("mat_id"), thickness_mm=thick, gt_dims=dims,
                         part_check=part_check, required=view == "top")  # fmt: skip
        if pr is not None:
            rep.photos.append(pr)
    known = {"gt.yaml", *(f"{v}.jpg" for v in PART_VIEWS)}
    for p in sorted(d.iterdir()):
        if p.name in known or p.name.startswith(".") or p.stem.lower() in PART_VIEWS:
            continue
        rep.add("warn", "folder", f"{p.name} is ignored by the bench")
    return rep


def check_reference(d: Path, *, part_check: bool = True) -> FolderReport:
    from tools.synth.reference_objects import REFERENCE_OBJECTS

    rep = FolderReport(name=f"{REF_DIR_NAME}/{d.name}", kind="reference", path=str(d))
    ref = REFERENCE_OBJECTS.get(d.name)
    if ref is None:
        rep.add("error", "folder", f"unknown reference object {d.name!r}",
                f"use one of: {', '.join(REFERENCE_OBJECTS)}")  # fmt: skip
        return rep
    photos = sorted(p for p in d.iterdir() if p.is_file() and p.suffix.lower() in IMAGE_EXTS)
    if not photos:
        rep.add("error", "folder", "no photos", "take 5 top photos in different spots on the stage")
    for p in photos:
        if p.suffix.lower() in (".heic", ".heif") or not p.name.lower().endswith((".jpg", ".jpeg")):
            hint = HEIC_HINT if p.suffix.lower() in (".heic", ".heif") else "convert it to .jpg"
            rep.add("error", p.name, f"{p.name} is not read by the bench (JPEG only)", hint)
            continue
        if p.suffix not in (".jpg", ".jpeg"):
            rep.add("error", p.name, f"{p.name}: the bench reads lower-case .jpg / .jpeg only", "rename it")
        view = "side" if "side" in p.stem.lower() else "top"
        thick = ref.user_thickness_mm if view == "top" else ref.dim("width").nominal_mm
        pr = check_photo(p, view, rep, where=p.name, thickness_mm=thick, part_check=part_check)
        if pr is not None:
            rep.photos.append(pr)
    return rep


def check_all(root: Path, *, part_check: bool = True) -> list[FolderReport]:
    reps: list[FolderReport] = []
    if not root.exists():
        return reps
    for d in sorted(p for p in root.iterdir() if p.is_dir() and not p.name.startswith(".")):
        if d.name == REF_DIR_NAME:
            for o in sorted(p for p in d.iterdir() if p.is_dir() and not p.name.startswith(".")):
                reps.append(check_reference(o, part_check=part_check))
        else:
            reps.append(check_part(d, part_check=part_check))
    return reps


# ------------------------------------------------------------------------------------------------------------- output


def _photo_cell(r: FolderReport) -> str:
    if r.kind == "reference":
        ok = sum(1 for p in r.photos if p.gate_passed)
        return f"{ok}/{len(r.photos)} ✓" if r.photos else "✗"
    marks = []
    for v in PART_VIEWS:
        p = next((x for x in r.photos if x.view == v), None)
        if p is not None:
            good = p.gate_passed is not False and not any(i.level == "error" and i.where == v for i in r.issues)
            marks.append(f"{v[0]}{'✓' if good else '✗'}")
    return " ".join(marks) or "✗"


def _markers_cell(r: FolderReport) -> str:
    """Markers found in the worst gated photo (n of the mat's N)."""
    gated = [p for p in r.photos if p.view in GATED_VIEWS]
    if not gated:
        return "-"
    worst = min(gated, key=lambda p: (p.markers or 0) / (p.markers_total or 1))
    return f"{worst.markers or 0}/{worst.markers_total or '?'}"


def _tilt_cell(r: FolderReport) -> str:
    t = [p.tilt_deg for p in r.photos if p.tilt_deg is not None]
    return "-" if not t else f"{max(t):.0f}°"


def render_table(reps: Sequence[FolderReport]) -> str:
    head = ("part", "photos", "markers", "tilt", "issues", "gt", "status")
    rows = []
    for r in reps:
        n_err = sum(i.level == "error" for i in r.issues)
        n_warn = len(r.issues) - n_err
        issues = f"{n_err}E {n_warn}W" if r.issues else "-"
        gt = "-" if r.gt_ok is None else ("✓" if r.gt_ok else "✗")
        rows.append((r.name, _photo_cell(r), _markers_cell(r), _tilt_cell(r), issues, gt,
                     "ok" if r.usable else "UNUSABLE"))  # fmt: skip
    widths = [max(len(h), *(len(row[i]) for row in rows)) for i, h in enumerate(head)]

    def line(cells: Sequence[str]) -> str:
        return "  ".join(c.ljust(w) for c, w in zip(cells, widths, strict=True)).rstrip()

    out = [line(head), line(tuple("-" * w for w in widths))]
    for r, row in zip(reps, rows, strict=True):
        out.append(line(row))
        for i in r.issues:
            tag = "✗" if i.level == "error" else "!"
            fix = f"  → {i.fix}" if i.fix else ""
            out.append(f"    {tag} {i.where}: {i.message}{fix}")
    return "\n".join(out)


def summary(reps: Sequence[FolderReport]) -> dict[str, Any]:
    parts = [r for r in reps if r.kind == "part"]
    refs = [r for r in reps if r.kind == "reference"]
    return {
        "parts": len(parts),
        "parts_usable": sum(r.usable for r in parts),
        "reference_folders": len(refs),
        "reference_photos": sum(len(r.photos) for r in refs),
        "reference_photos_passing_gate": sum(1 for r in refs for p in r.photos if p.gate_passed),
        "unusable": [r.name for r in reps if not r.usable],
    }


# ------------------------------------------------------------------------------------------------------------- intake


@dataclass
class IntakeItem:
    src: str
    part: str
    view: str
    dest: str = ""
    action: str = ""  # "written", "skipped", "error"
    note: str = ""


@dataclass
class IntakeReport:
    items: list[IntakeItem] = field(default_factory=list)
    templates: list[str] = field(default_factory=list)
    kept_gt: list[str] = field(default_factory=list)
    unmatched: list[str] = field(default_factory=list)
    root: str = ""

    @property
    def ok(self) -> bool:
        return not any(i.action == "error" for i in self.items)


def _norm_part(s: str) -> str:
    return re.sub(r"\s+", "-", s.strip().lower())


def read_mapping(src: Path) -> tuple[list[tuple[Path, str, str, int | None]], list[str]]:
    """[(file, part, view, n)] from FROM/parts.csv, else from `<part>_<view>[_<n>]` file names; and the unmatched."""
    csv_path = src / "parts.csv"
    rows: list[tuple[Path, str, str, int | None]] = []
    unmatched: list[str] = []
    if csv_path.exists():
        with csv_path.open(newline="", encoding="utf-8-sig") as fh:
            for rec in csv.reader(fh):
                cells = [c.strip() for c in rec]
                if not cells or not any(cells) or cells[0].startswith("#"):
                    continue
                if [c.lower() for c in cells[:3]] == ["file", "part", "view"]:
                    continue
                if len(cells) < 3:
                    unmatched.append(f"parts.csv row {rec!r}: needs file,part,view")
                    continue
                part = _norm_part(cells[1])
                for prefix in ("ref:", f"{REF_DIR_NAME}/"):
                    part = part.removeprefix(prefix)
                rows.append((src / cells[0], part, cells[2].lower(), None))
        return rows, unmatched
    for p in sorted(src.iterdir()):
        if not p.is_file() or p.suffix.lower() not in IMAGE_EXTS:
            continue
        m = NAMED.match(p.stem)
        if m is None:
            unmatched.append(p.name)
            continue
        n = int(m["n"]) if m["n"] else None
        rows.append((p, _norm_part(m["part"]), m["view"].lower(), n))
    return rows, unmatched


def _exif_tags(data: bytes) -> tuple[int, dict[int, Any]]:
    """(orientation, the kept Exif-IFD tags) of an encoded photo."""
    from PIL import Image

    from services.common.images import exif_orientation

    keep: dict[int, Any] = {}
    try:
        with Image.open(io.BytesIO(data)) as im:
            sub = im.getexif().get_ifd(EXIF_IFD)
            keep = {t: sub[t] for t in KEEP_EXIF_TAGS if t in sub}
    except Exception:
        keep = {}
    return exif_orientation(data), keep


def _minimal_exif(orientation: int, keep: dict[int, Any]) -> bytes:
    from PIL import Image

    ex = Image.Exif()
    if orientation != 1:
        ex[ORIENTATION_TAG] = orientation
    if keep:
        sub = ex.get_ifd(EXIF_IFD)
        sub.update(keep)
    return ex.tobytes() if (orientation != 1 or keep) else b""


def jpeg_private_strip(data: bytes) -> bytes:
    """Lossless: the same JPEG scans and tables with only a minimal EXIF block (orientation + focal-length tags); every
    APP1 (EXIF, XMP), APP13 (IPTC), comment and multi-picture (MPF) segment is dropped, and so is anything after the
    primary image (gain maps, depth maps, thumbnails). Raises ValueError when the bytes are not a JPEG it can walk."""
    if data[:2] != b"\xff\xd8":
        raise ValueError("not a JPEG")
    orientation, keep = _exif_tags(data)
    exif = _minimal_exif(orientation, keep)
    head = bytearray()
    body = bytearray()
    i, n = 2, len(data)
    first = True
    while True:
        if i + 4 > n or data[i] != 0xFF:
            raise ValueError("malformed JPEG segment")
        marker = data[i + 1]
        if marker == 0xFF:
            i += 1
            continue
        if marker == 0xDA:  # start of scan: copy to the primary image's end of image
            end = data.find(b"\xff\xd9", i)
            if end < 0:
                raise ValueError("JPEG has no end-of-image marker")
            body += data[i : end + 2]
            break
        seglen = int.from_bytes(data[i + 2 : i + 4], "big")
        seg = data[i : i + 2 + seglen]
        drop = marker in (0xE1, 0xED, 0xFE) or (marker == 0xE2 and seg[4:8] == b"MPF\x00")
        if marker == 0xE0 and first:
            head += seg
        elif not drop:
            body += seg
        first = False
        i += 2 + seglen
    app1 = b""
    if exif:
        if len(exif) + 8 > 0xFFFF:
            raise ValueError("EXIF block too big")
        payload = b"Exif\x00\x00" + exif
        app1 = b"\xff\xe1" + (len(payload) + 2).to_bytes(2, "big") + payload
    return b"\xff\xd8" + bytes(head) + app1 + bytes(body)


def upright_jpeg(data: bytes) -> bytes:
    """Re-encoded, EXIF orientation applied, quality 95 with full-resolution colour; only the focal-length tags kept."""
    from PIL import Image, ImageOps

    _, keep = _exif_tags(data)
    with Image.open(io.BytesIO(data)) as raw:
        im = ImageOps.exif_transpose(raw).convert("RGB")
        buf = io.BytesIO()
        kw: dict[str, Any] = {"quality": JPEG_QUALITY, "subsampling": 0}
        exif = _minimal_exif(1, keep)
        if exif:
            kw["exif"] = b"Exif\x00\x00" + exif
        im.save(buf, format="JPEG", **kw)
    return buf.getvalue()


def clean_photo(data: bytes, *, reencode: bool = False) -> tuple[bytes, str]:
    """(JPEG bytes without private metadata, "lossless" | "re-encoded"). ValueError for HEIC or undecodable input."""
    from services.common.images import oriented_size

    if is_heic(data):
        raise ValueError(f"HEIC photo: {HEIC_HINT}")
    fmt = image_format(data)
    if fmt is None:
        raise ValueError("does not decode as an image")
    if fmt == "JPEG" and not reencode:
        try:
            out = jpeg_private_strip(data)
            same = (
                image_format(out) == "JPEG"
                and oriented_size(out) == oriented_size(data)
                and _exif_tags(out) == _exif_tags(data)
            )
            if same:
                return out, "lossless"
        except ValueError:
            pass
    return upright_jpeg(data), "re-encoded"


GT_TEMPLATE = """\
# Ruler ground truth for {part}. Replace every TODO with a reading in millimetres, then run `make real-check`.
gt_source: ruler          # always ruler (a school ruler, +-0.5 mm); never call it caliper accuracy
uncertainty_mm: 0.5
user_thickness_mm: TODO   # the plate thickness you would type into /fix (the bench gives it to the job)
# mat_id: screen-m        # optional: the mat the photos were taken on (auto-detected when absent)
# intent: Make a replacement for this broken part.
dims:
  length: TODO            # longest side seen from above
  width: TODO             # the other side seen from above
  thickness: TODO         # overall height lying flat (scores side.jpg)
holes: []                 # see-through holes, e.g. [{{diameter: 4.0}}, {{diameter: 4.0}}]
"""


def _next_ref_name(d: Path, view: str, n: int | None) -> Path:
    if n is not None:
        return d / f"{view}_{n}.jpg"
    k = 1
    while (d / f"{view}_{k}.jpg").exists():
        k += 1
    return d / f"{view}_{k}.jpg"


def intake(
    src: Path, root: Path, *, reencode: bool = False, force: bool = False, dry_run: bool = False
) -> IntakeReport:
    from tools.synth.reference_objects import REFERENCE_OBJECTS

    rep = IntakeReport(root=str(root))
    rows, rep.unmatched = read_mapping(src)
    seen: dict[tuple[str, str], str] = {}
    for path, part, view, n in rows:
        item = IntakeItem(src=path.name, part=part, view=view)
        rep.items.append(item)
        is_ref = part in REFERENCE_OBJECTS
        views = GATED_VIEWS if is_ref else PART_VIEWS
        if not path.is_file():
            item.action, item.note = "error", "file not found"
            continue
        if view not in views:
            item.action, item.note = "error", f"view must be one of {', '.join(views)}"
            continue
        if not PART_ID.match(part) or part == REF_DIR_NAME:
            item.action, item.note = "error", "part id must be lowercase letters, digits, - and _"
            continue
        if not is_ref:
            key = (part, view)
            if key in seen:
                item.action, item.note = "error", f"second {view} photo for {part} (first: {seen[key]}); keep one"
                continue
            seen[key] = path.name
        try:
            out, mode = clean_photo(path.read_bytes(), reencode=reencode)
        except ValueError as exc:
            item.action, item.note = "error", str(exc)
            continue
        if is_ref:
            d = root / REF_DIR_NAME / part
            sha = hashlib.sha256(out).hexdigest()
            dup = next((p for p in sorted(d.glob("*.jpg")) if hashlib.sha256(p.read_bytes()).hexdigest() == sha), None)
            if d.exists() and dup is not None:
                item.action, item.dest, item.note = "skipped", str(dup), "already imported"
                continue
            dest = _next_ref_name(d, view, n)
        else:
            d = root / part
            dest = d / f"{view}.jpg"
        item.dest = str(dest)
        if dest.exists() and not force:
            item.action, item.note = "skipped", "exists (--force replaces photos; gt.yaml is never replaced)"
            continue
        item.action, item.note = "written", mode
        if dry_run:
            item.note += " (dry run)"
            continue
        d.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(out)
    for part in sorted({i.part for i in rep.items if i.action == "written" and i.part not in REFERENCE_OBJECTS}):
        gt = root / part / "gt.yaml"
        if gt.exists():
            rep.kept_gt.append(str(gt))
            continue
        rep.templates.append(str(gt))
        if not dry_run:
            gt.write_text(GT_TEMPLATE.format(part=part), encoding="utf-8")
    return rep


def _rel(path: str, root: str) -> str:
    try:
        return str(Path(path).relative_to(root))
    except ValueError:
        return path


def render_intake(rep: IntakeReport) -> str:
    lines = [f"into {rep.root}:"]
    for i in rep.items:
        tag = {"written": "+", "skipped": "=", "error": "✗"}.get(i.action, "?")
        dest = f" → {_rel(i.dest, rep.root)}" if i.dest else ""
        lines.append(f"  {tag} {i.src} [{i.part}/{i.view}]{dest}  {i.note}")
    for u in rep.unmatched:
        lines.append(f"  ? {u}: not matched (name it <part>_<top|side|context>.jpg or list it in parts.csv)")
    for t in rep.templates:
        lines.append(f"  + {_rel(t, rep.root)}  (template: fill the TODO values)")
    for t in rep.kept_gt:
        lines.append(f"  = {_rel(t, rep.root)}  (kept as it is)")
    written = sum(i.action == "written" for i in rep.items)
    errors = sum(i.action == "error" for i in rep.items)
    lines.append(f"{written} photo(s) written, {errors} error(s), {len(rep.unmatched)} unmatched. Next: fill gt.yaml, "
                 "then `make real-check`.")  # fmt: skip
    return "\n".join(lines)


# ---------------------------------------------------------------------------------------------------------------- CLI


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m tools.real_check", description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd")
    c = sub.add_parser("check", help="validate data/real/ offline (no model calls)")
    c.add_argument("--root", type=Path, default=REAL_DIR)
    c.add_argument("--json", action="store_true", help="print JSON instead of the table")
    c.add_argument("--no-part-check", action="store_true", help="skip the threshold-mask part check (faster)")
    i = sub.add_parser("intake", help="copy phone photos from a folder into data/real/")
    i.add_argument("src", type=Path)
    i.add_argument("--root", type=Path, default=REAL_DIR)
    i.add_argument("--reencode", action="store_true", help="always write an upright re-encoded JPEG")
    i.add_argument("--force", action="store_true", help="replace existing photos (never gt.yaml)")
    i.add_argument("--dry-run", action="store_true")
    i.add_argument("--json", action="store_true")
    args = ap.parse_args(list(sys.argv[1:] if argv is None else argv) or ["check"])
    if args.cmd == "intake":
        if not args.src.is_dir():
            print(f"real-intake: {args.src} is not a folder", file=sys.stderr)
            return 2
        irep = intake(args.src, args.root, reencode=args.reencode, force=args.force, dry_run=args.dry_run)
        if args.json:
            print(json.dumps({**asdict(irep), "ok": irep.ok}, indent=1))
        else:
            print(render_intake(irep))
        return 0 if irep.ok else 1
    reps = check_all(args.root, part_check=not args.no_part_check)
    summ = summary(reps)
    if args.json:
        print(json.dumps({"root": str(args.root), "summary": summ, "folders": [r.to_json() for r in reps]}, indent=1))
    elif not reps:
        print(f"real-check: nothing in {args.root} yet (see docs/HANDOFF.md, Photo day)")
    else:
        print(render_table(reps))
        print(f"\n{summ['parts_usable']}/{summ['parts']} parts usable; reference objects: "
              f"{summ['reference_photos_passing_gate']}/{summ['reference_photos']} photos pass the capture gate."
              + (f" Unusable: {', '.join(summ['unusable'])}." if summ["unusable"] else ""))  # fmt: skip
    return 1 if summ["unusable"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
