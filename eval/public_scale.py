"""Real-camera scale check: how well does a flat-plane marker fit hold on real lenses and real printed paper?

Public real camera photos of printed marker boards with a documented layout. A homography is fitted to the corners of
the OUTER markers only, with the same code the product fits its mat with (`calibrate.fit_plane_homography`, detector
settings and sub-pixel corner refinement included). It then predicts the INNER markers' corners, which the fit never
saw. The error is measured on the board plane, in units where the board's long side is 100: the same number is the
% of span and the mm over a 100 mm span.

This is not a phone-on-laptop-screen test and not a measurement of a part. The boards' printed size is unknown, so
every number is relative; the mm figure is the relative error applied to a 100 mm span on our mat.

    uv run python -m eval.public_scale            # no keys, no model; needs the photos in var/public_photos/
    uv run python -m eval.public_scale --download # first fetches them by the URLs in the gitignored sources file
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import urllib.request
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import cv2
import numpy as np
from numpy.typing import NDArray

from services.metrology.calibrate import _detector, _gray, _refine_corners, apply_h, fit_plane_homography

from .stats import cluster_bootstrap_mean

REPO = Path(__file__).resolve().parents[1]
PHOTO_DIR = REPO / "var" / "public_photos" / "raw" / "scale"
SOURCES = REPO / "var" / "public_photos" / "scale_sources.json"  # gitignored: {id: url}
REPORT_DIR = REPO / "eval" / "reports" / "latest"
SPAN = 100.0  # the board's long side, in plane units
CI_SEED = 0

F64 = NDArray[np.float64]

SCOPE = (
    "Measures how well a flat-plane marker fit holds on real lenses and real printed paper. It says nothing about a "
    "phone photographing a laptop screen, nothing about measuring a part, and these photos are not counted as real "
    "photos measured. The boards' printed size is unknown, so all numbers are relative; the mm figure is the relative "
    "error applied to a 100 mm span on our mat, not a measured length."
)


@dataclass(frozen=True)
class Board:
    """A documented board layout: grid (marker side `a`, gap `b`) or checker (square side `a`, marker side `b`)."""

    photo_id: str
    kind: str  # grid | checker
    size: tuple[int, int]  # columns, rows
    a: float
    b: float
    dictionary: str  # a cv2.aruco predefined name, or "file:<source id>" for a dictionary published with the photo
    note: str = ""


BOARDS = (
    Board("scale-1", "grid", (5, 7), 100.0, 10.0, "file:scale-dict", "grid board on a desk"),
    Board("scale-2", "checker", (5, 7), 0.04, 0.02, "DICT_6X6_250", "checker board on a desk"),
    Board("scale-3", "checker", (5, 7), 0.04, 0.02, "DICT_6X6_250", "checker board, partly covered"),
)
# A second marker size that the checker board's documentation also mentions (for making a board, not for these
# photos). A much worse fit under it shows the check can tell a wrong layout from the right one.
ALT_MARKER = {"checker": 0.024}
MIN_LAYOUT_INLIER_SHARE = 0.9  # of the outer corners; below this the documented layout does not describe the print
RATIO_SCAN = tuple(round(0.05 + 0.01 * k, 2) for k in range(36))  # grid gap / marker side
EXCLUDED = (
    {"photo_id": "scale-x1", "reason": "loose markers with no documented layout: no held-out truth"},
    {"photo_id": "scale-x2", "reason": "marker diamonds with no documented layout between them: no held-out truth"},
)


def load_dictionary(name: str, photo_dir: Path = PHOTO_DIR) -> cv2.aruco.Dictionary:
    if name.startswith("file:"):
        fs = cv2.FileStorage(str(photo_dir / f"{name.removeprefix('file:')}.yml"), cv2.FILE_STORAGE_READ)
        d = cv2.aruco.Dictionary()
        d.readDictionary(fs.root())
        return d
    return cv2.aruco.getPredefinedDictionary(getattr(cv2.aruco, name))


def board_layout(board: Board, dictionary: cv2.aruco.Dictionary, *, marker: float | None = None) -> dict[int, F64]:
    """{marker id: 4 corners} on the board plane, scaled so that the long side of the board is SPAN."""
    if board.kind == "grid":
        cv_board: cv2.aruco.Board = cv2.aruco.GridBoard(board.size, board.a, board.b, dictionary)
        long_side = max(n * board.a + (n - 1) * board.b for n in board.size)
    else:
        cv_board = cv2.aruco.CharucoBoard(board.size, board.a, board.b if marker is None else marker, dictionary)
        long_side = max(board.size) * board.a
    pts = cv_board.getObjPoints()
    ids = np.asarray(cv_board.getIds()).ravel()
    return {int(i): np.asarray(p, dtype=np.float64)[:, :2] * SPAN / long_side for i, p in zip(ids, pts, strict=True)}


def outer_ids(layout: Mapping[int, F64]) -> set[int]:
    """Markers in the board's outer ring: their centre is within half a cell of the layout's edge columns or rows."""
    centres = {i: c.mean(axis=0) for i, c in layout.items()}
    arr = np.array(list(centres.values()))
    lo, hi = arr.min(axis=0), arr.max(axis=0)
    xs = np.unique(np.round(arr[:, 0], 6))
    ys = np.unique(np.round(arr[:, 1], 6))
    tol = 0.5 * min(float(np.min(np.diff(xs))), float(np.min(np.diff(ys))))
    out = set()
    for i, c in centres.items():
        if abs(c[0] - lo[0]) < tol or abs(c[0] - hi[0]) < tol or abs(c[1] - lo[1]) < tol or abs(c[1] - hi[1]) < tol:
            out.add(i)
    return out


def detect_corners(img: NDArray[np.uint8], dictionary: cv2.aruco.Dictionary) -> dict[int, F64]:
    """{marker id: 4 refined corners in px}, with the product's detector settings and sub-pixel refinement."""
    gray = _gray(img)
    corners, ids, _ = _detector(dictionary).detectMarkers(gray)
    if ids is None or len(ids) == 0:
        return {}
    raw = np.stack([np.asarray(c, dtype=np.float64).reshape(4, 2) for c in corners])
    refined = _refine_corners(gray, raw)
    return {int(i): refined[k] for k, i in enumerate(ids.ravel())}


def score_photo(corners: Mapping[int, F64], layout: Mapping[int, F64], *, outer_only: bool = False) -> dict[str, Any]:
    """Fit on outer markers, predict inner markers. Errors in plane units (= % of the board's long side).
    `outer_only`: only the fit's residual over every outer corner (RANSAC outliers included)."""
    outer = outer_ids(layout)
    seen = [i for i in sorted(corners) if i in layout]
    fit_ids = [i for i in seen if i in outer]
    test_ids = [i for i in seen if i not in outer]
    res: dict[str, Any] = {
        "markers_detected": len(seen),
        "markers_in_layout": len(layout),
        "fit_markers": len(fit_ids),
        "held_out_markers": len(test_ids),
        "held_out_corners": 4 * len(test_ids),
    }
    if len(fit_ids) < 4 or (not test_ids and not outer_only):
        return {**res, "status": "too few markers", "errors_pct_by_marker": []}
    img_fit = np.concatenate([corners[i] for i in fit_ids])
    plane_fit = np.concatenate([layout[i] for i in fit_ids])
    fit = fit_plane_homography(img_fit, plane_fit)
    if fit is None:
        return {**res, "status": "no plane fit", "errors_pct_by_marker": []}
    H, inliers = fit
    if outer_only:
        all_err = np.linalg.norm(apply_h(H, img_fit) - plane_fit, axis=1)
        return {**res, "fit_all_mean_err_pct": float(all_err.mean())}
    fit_err = np.linalg.norm(apply_h(H, img_fit[inliers]) - plane_fit[inliers], axis=1)
    by_marker = [np.linalg.norm(apply_h(H, corners[i]) - layout[i], axis=1) for i in test_ids]
    flat = np.concatenate(by_marker)
    # px per plane unit near the board's middle: what one pixel is worth in this photo
    mid = np.mean(np.concatenate([layout[i] for i in test_ids]), axis=0, keepdims=True)
    Hi = np.linalg.inv(H)
    du = np.linalg.norm(apply_h(Hi, mid + np.array([[1.0, 0.0]])) - apply_h(Hi, mid))
    dv = np.linalg.norm(apply_h(Hi, mid + np.array([[0.0, 1.0]])) - apply_h(Hi, mid))
    px_per_unit = float(np.sqrt(du * dv))
    return {
        **res,
        "status": "ok",
        "fit_inlier_corners": int(inliers.sum()),
        "fit_corners": len(inliers),
        "fit_mean_err_pct": round(float(fit_err.mean()), 4),
        "mean_err_pct": round(float(flat.mean()), 4),
        "median_err_pct": round(float(np.median(flat)), 4),
        "p90_err_pct": round(float(np.quantile(flat, 0.9)), 4),
        "max_err_pct": round(float(flat.max()), 4),
        "mean_err_px": round(float(flat.mean() * px_per_unit), 3),
        "one_px_in_pct": round(1.0 / px_per_unit, 4),
        "errors_pct_by_marker": [[round(float(v), 5) for v in m] for m in by_marker],
    }


def fit_gap_ratio(corners: Mapping[int, F64], board: Board, dictionary: cv2.aruco.Dictionary) -> float:
    """The grid gap/marker ratio that best explains the OUTER markers (held-out markers play no part in the choice)."""
    best: tuple[float, float] = (float("inf"), RATIO_SCAN[0])
    for r in RATIO_SCAN:
        layout = board_layout(Board(board.photo_id, "grid", board.size, 100.0, 100.0 * r, board.dictionary), dictionary)
        outer = [i for i in sorted(corners) if i in outer_ids(layout)]
        q = score_photo({i: corners[i] for i in outer}, layout, outer_only=True)
        err = float(q.get("fit_all_mean_err_pct", float("inf")))
        best = min(best, (err, float(r)))
    return best[1]


def analyse_photo(img: NDArray[np.uint8], board: Board, dictionary: cv2.aruco.Dictionary) -> dict[str, Any]:
    corners = detect_corners(img, dictionary)
    out = score_photo(corners, board_layout(board, dictionary))
    alt = ALT_MARKER.get(board.kind)
    if alt is not None:
        wrong = score_photo(corners, board_layout(board, dictionary, marker=alt))
        out["wrong_layout_mean_err_pct"] = wrong.get("mean_err_pct")
    # The outer markers alone decide whether the documented layout describes this print.
    share = out.get("fit_inlier_corners", 0) / max(out.get("fit_corners", 0), 1)
    out["layout_confirmed_by_outer_markers"] = bool(share >= MIN_LAYOUT_INLIER_SHARE)
    if not out["layout_confirmed_by_outer_markers"] and board.kind == "grid":
        r = fit_gap_ratio(corners, board, dictionary)
        layout = board_layout(Board(board.photo_id, "grid", board.size, 100.0, 100.0 * r, board.dictionary), dictionary)
        out["outer_fitted_gap_ratio"] = r
        out["with_outer_fitted_ratio"] = score_photo(corners, layout)
    h, w = img.shape[:2]
    return {
        "photo_id": board.photo_id,
        "note": board.note,
        "image_px": [int(w), int(h)],
        "layout": {"kind": board.kind, "size": list(board.size), "a": board.a, "b": board.b},
        **out,
    }


def summarise(photos: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Pooled held-out error. CI: bootstrap over markers (a marker's four corners are correlated)."""
    used = [p for p in photos if p.get("errors_pct_by_marker")]
    groups = [m for p in used for m in p["errors_pct_by_marker"]]
    if not groups:
        return {"status": "pending", "n_photos": len(photos), "n_corners": 0}
    flat = [v for g in groups for v in g]
    lo, hi = cluster_bootstrap_mean(groups, seed=CI_SEED)
    mean = float(np.mean(flat))
    return {
        "status": "ok",
        "photos": [p["photo_id"] for p in used],
        "n_photos": len(used),
        "n_markers": len(groups),
        "n_corners": len(flat),
        "mean_err_pct": round(mean, 3),
        "ci95_pct": [round(lo, 3), round(hi, 3)],
        "median_err_pct": round(float(np.median(flat)), 3),
        "max_err_pct": round(max(flat), 3),
        "mean_err_mm_over_100mm": round(mean * 100.0 / SPAN, 3),
        "ci95_mm_over_100mm": [round(lo * 100.0 / SPAN, 3), round(hi * 100.0 / SPAN, 3)],
        "ci_method": "percentile bootstrap over held-out markers, 2000 resamples, seeded; not over photos",
    }


def _summary_line(s: Mapping[str, Any]) -> str:
    return (
        f"{s['mean_err_pct']} % of span (95 % CI {s['ci95_pct'][0]} to {s['ci95_pct'][1]}), median "
        f"{s['median_err_pct']} %, max {s['max_err_pct']} %; n = {s['n_corners']} corners on {s['n_markers']} markers "
        f"in {s['n_photos']} photos ({', '.join(s['photos'])}); over a 100 mm span on our mat "
        f"{s['mean_err_mm_over_100mm']} mm (CI {s['ci95_mm_over_100mm'][0]} to {s['ci95_mm_over_100mm'][1]})"
    )


def to_markdown(rep: Mapping[str, Any]) -> str:
    s = rep["summary"]
    L = ["# Real-camera scale check (public photos of printed boards)", "", rep["scope"], ""]
    if s["status"] == "ok":
        L += [
            f"**Layout confirmed by its outer markers:** {_summary_line(s)}. CI: {s['ci_method']}.",
            "",
            f"Every photo with its documented layout, as written: {_summary_line(rep['summary_documented_as_written'])}.",
            "",
            f"With the grid board's gap ratio fitted on outer markers only: {_summary_line(rep['summary_outer_fitted'])}.",
            "",
            rep["layout_finding"],
            "",
            "| photo | size px | fit markers | outer inliers | held-out corners | mean % | max % | mean px | 1 px = % |",
            "|---|---|---|---|---:|---:|---:|---:|---:|",
        ]
        for p in rep["photos"]:
            L.append(
                f"| {p['photo_id']} | {p['image_px'][0]}×{p['image_px'][1]} | {p['fit_markers']} | "
                f"{p.get('fit_inlier_corners', '-')}/{p.get('fit_corners', '-')} | {p['held_out_corners']} | {p.get('mean_err_pct', '-')} | {p.get('max_err_pct', '-')} | "
                f"{p.get('mean_err_px', '-')} | {p.get('one_px_in_pct', '-')} |"
            )
        L += ["", "Photos left out:"] + [f"- {e['photo_id']}: {e['reason']}" for e in rep["excluded"]]
        for p in rep["photos"]:
            if p.get("wrong_layout_mean_err_pct") is not None:
                L.append(
                    f"\nControl: on {p['photo_id']} a wrong marker size in the layout gives "
                    f"{p['wrong_layout_mean_err_pct']} % against {p.get('mean_err_pct')} % with the documented one."
                )
    else:
        L.append("No photos available: nothing measured.")
    return "\n".join(L) + "\n"


def build_report(photo_dir: Path = PHOTO_DIR) -> dict[str, Any]:
    photos: list[dict[str, Any]] = []
    missing: list[str] = []
    for b in BOARDS:
        path = photo_dir / f"{b.photo_id}.jpg"
        if not path.exists():
            missing.append(b.photo_id)
            continue
        img = cast("NDArray[np.uint8]", cv2.imread(str(path), cv2.IMREAD_COLOR))
        photos.append(analyse_photo(img, b, load_dictionary(b.dictionary, photo_dir)))
    confirmed = [p for p in photos if p.get("layout_confirmed_by_outer_markers")]
    fitted = [{**p, **p.get("with_outer_fitted_ratio", {})} for p in photos]
    rejected = [p for p in photos if not p.get("layout_confirmed_by_outer_markers")]
    finding = "; ".join(
        f"{p['photo_id']}: the documented layout fits only {p.get('fit_inlier_corners', 0)}/{p.get('fit_corners', 0)} "
        f"outer corners, so it does not describe this print ({p.get('mean_err_pct')} % held-out as written). The outer "
        f"markers alone give a gap ratio of {p.get('outer_fitted_gap_ratio')} "
        f"({p.get('with_outer_fitted_ratio', {}).get('mean_err_pct')} % held-out). That photo is left out of the "
        "headline because its layout is estimated, not documented"
        for p in rejected
    )
    return {
        "generated_at": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "source": "public_photo",
        "ground_truth": "documented board layout (held-out inner markers); printed size unknown",
        "scope": SCOPE,
        "counts_as_real_photos_measured": 0,
        "summary": summarise(confirmed),
        "summary_documented_as_written": summarise(photos),
        "summary_outer_fitted": summarise(fitted),
        "layout_finding": finding or "every documented layout was confirmed by its outer markers",
        "photos": photos,
        "missing": missing,
        "excluded": list(EXCLUDED),
    }


def download(sources: Path = SOURCES, photo_dir: Path = PHOTO_DIR) -> list[str]:
    """Fetch every file named in the gitignored sources file ({id: url}) into its own data folder."""
    photo_dir.mkdir(parents=True, exist_ok=True)
    got: list[str] = []
    for key, url in json.loads(sources.read_text()).items():
        ext = Path(url).suffix.lower()
        dest = photo_dir / f"{key}{ext}"
        if dest.exists():
            continue
        req = urllib.request.Request(url, headers={"User-Agent": "PartSmithBench/0.1"})
        with urllib.request.urlopen(req, timeout=60) as r:
            dest.write_bytes(r.read())
        got.append(key)
    return got


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m eval.public_scale", description=__doc__.split("\n\n")[0])
    ap.add_argument("--download", action="store_true", help="fetch the photos by the URLs in the sources file first")
    ap.add_argument("--out", type=Path, default=REPORT_DIR)
    a = ap.parse_args(argv)
    if a.download:
        if not SOURCES.exists():
            print(f"no {SOURCES.relative_to(REPO)}: the source URLs are not kept in the repo", file=sys.stderr)
            return 2
        download()
    rep = build_report()
    if rep["summary_documented_as_written"]["status"] != "ok":
        print("public_scale: no photos in var/public_photos/raw/scale (kept the stored report)", file=sys.stderr)
        return 0
    a.out.mkdir(parents=True, exist_ok=True)
    (a.out / "public_scale.json").write_text(json.dumps(rep, indent=1) + "\n")
    (a.out / "public_scale.md").write_text(to_markdown(rep))
    s = rep["summary"]
    print(
        f"public_scale (layout confirmed): held-out corner error {s['mean_err_pct']} % of span, CI {s['ci95_pct']}, "
        f"n={s['n_corners']} corners / {s['n_markers']} markers / {s['n_photos']} photos; "
        f"= {s['mean_err_mm_over_100mm']} mm over 100 mm"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
