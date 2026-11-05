"""Everything the pitch deck shows, generated so no number in it is typed by hand.

    uv run python -m tools.deck_data            ->  apps/web/public/deck/data.json (reads the repo only, no network)
    uv run python -m tools.deck_data --bake     ->  apps/web/public/deck/models/ (real CadQuery variants from a local API)
    uv run python -m tools.deck_data --assets   ->  apps/web/public/deck/img/ and voice.mp4 (from the film's work folder)

`--bake` needs an API on --api (default http://127.0.0.1:8766). Each mesh is a small binary: u32 vertex count, u32 triangle
count, float32 positions, uint32 indices. The browser only swaps these files; it never runs CAD.
"""

from __future__ import annotations

import argparse
import importlib.util
import io
import json
import re
import struct
import subprocess
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DECK = ROOT / "apps/web/public/deck"
WORK = Path.home() / "Videos/partsmith"
RUN = "j_261029_daf26965"

# part -> knob -> values; one knob at a time from the part's defaults. `topology` knobs change the feature count.
KNOBS: dict[str, dict[str, list[float]]] = {
    "battery-cover-45mm": {
        "length": [35.3, 40.3, 45.3, 50.3, 55.3, 60.3, 65.3],
        "width": [22.01, 26.01, 30.01, 34.01, 38.01, 42.01, 46.01],
        "tongue_count": [1, 2, 3],
    },
    "wall-hook-66mm": {
        "reach": [18, 24, 30, 36, 42, 48, 54],
        "hole_count": [1, 2, 3],
        "arm_thickness": [3.5, 4.5, 6, 7, 8, 9, 10],
    },
    "shelf-panel-clip-44mm": {
        "arm_height": [4, 5.5, 7, 9, 11, 14, 17],
        "hole_d": [2.5, 3, 3.55, 4, 4.5, 5, 6],
        "rib_count": [0, 1, 2, 3, 4],
    },
    "spacer-8mm": {
        "height": [3, 5, 8.5, 12, 18, 25, 32],
        "bore_d": [2, 2.5, 3.2, 3.9, 4.5, 5, 6],
        "flat_count": [0, 2, 4, 6],
    },
}
STAR_SLUG = "wall-hook-66mm"
STAR_BASE = {"hole_count": 2.0}
STAR_KNOBS: dict[str, list[float]] = {
    "hole_d": [3.0, 3.5, 4.09, 4.5, 5.0, 5.5, 6.0],
    "length": [56.4, 61.4, 66.4, 71.4, 76.4, 81.4, 86.4],
}
# What the voice take on the deck's voice slide shows (video/record.mjs `say`, read off the recording).
VOICE_TAKE = {
    "transcript": "cover को एक मिलीमीटर लंबा करो",
    "gloss": "make the cover one millimetre longer",
    "confidence_pct": 98,
    "knob": "Length",
    "from_mm": 45.30,
    "to_mm": 46.30,
    "source": "screen recording of a live session, test line in a synthesised voice",
}
# Category summary, no product names. Columns: from one phone photo, true millimetres, editable program, checked before printing.
LANDSCAPE = {
    "columns": [
        "From one phone photo",
        "True millimetres",
        "Editable program",
        "Checked against your part before printing",
    ],
    "rows": [
        {
            "name": "AI image-to-3D",
            "cells": ["Yes", "Guessed", "Mesh", "No"],
            "why": "It infers a shape from a picture, so sizes are a guess, and you get a mesh to work with.",
        },
        {
            "name": "Phone scan apps",
            "cells": ["Many photos", "Rough", "Mesh", "No"],
            "why": "A scan needs many photos of the part, and small plastic parts tend to come out rough.",
        },
        {
            "name": "Text-to-CAD",
            "cells": ["You type it", "If you know them", "Yes", "No"],
            "why": "You get editable CAD, but you supply the sizes, and nothing compares the result with your part.",
        },
        {
            "name": "Part libraries",
            "cells": ["Search only", "Varies", "Varies", "No"],
            "why": "These work well when someone already modelled your exact part. If nobody did, there is nothing to find.",
        },
        {
            "name": "CAD by hand",
            "cells": ["Caliper", "Yes", "Yes", "Print to find out"],
            "why": "It is accurate in skilled hands, but it takes a caliper and CAD skills, and the first real check is often a test print.",
        },
        {
            "name": "PartSmith",
            "cells": ["Yes", "Measured", "Yes", "Yes, by code"],
            "why": "Screen markers set the scale, code measures, an agent writes the program, and the verifier compares it with the photo before export.",
            "ours": True,
        },
    ],
    "finding": "We found none that check the result against your part, in millimetres, before you print.",
    "source": "Category summary from public reviews and product docs, Nov 2026",
    "source_url": "https://all3dp.com/1/do-free-text-to-3d-model-generators-really-work-we-tested-3-of-them",
}
NEXT_STEPS = [
    "Real phone captures on the laptop mat",
    "A printed part in its real place",
    "A dozen reviews by a person",
    "Muse Glimmer on an open-weights GPU",
]


def _facts() -> Any:
    """The film's fact readers, so the deck and the film can never disagree."""
    spec = importlib.util.spec_from_file_location("film_facts", ROOT / "video/facts.py")
    if spec is None or spec.loader is None:
        raise RuntimeError("video/facts.py not found")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def load(path: str) -> Any:
    return json.loads((ROOT / path).read_text())


def run_events(run: str = RUN) -> list[dict[str, Any]]:
    return [
        json.loads(line) for line in (ROOT / f"data/replays/{run}/run.jsonl").read_text().splitlines() if line.strip()
    ]


def minutes_to_file(events: list[dict[str, Any]], created_at: float) -> float:
    """Photo to checked file: the first 3MF export's time minus the job's start, as the job's impact panel computes it."""
    first: float = next(e["ts"] for e in events if e.get("t") == "artifact" and e.get("kind") == "threemf")
    return round((first - created_at) / 60, 2)


def rounds(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The run's own rounds: error, overlap and what the agent changed."""
    out = []
    for e in events:
        if e.get("t") != "iteration":
            continue
        edits = [{"param": x["param"], "from": x["from"], "to": x["to"]} for x in e.get("edits") or []]
        out.append(
            {
                "round": e["iter"],
                "error_mm": round(e["hausdorff_mm"], 2),
                "iou": round(e["iou"], 3),
                "edits": edits,
                "analysis": e.get("analysis", ""),
            }
        )
    return out


def program_lines(run: str = RUN) -> list[str]:
    text = (ROOT / f"data/replays/{run}/part.py").read_text()
    lines = [line.rstrip() for line in text.splitlines() if re.match(r'\s+"\w+": \(', line)]
    return [re.sub(r"\s+", " ", line.strip()) for line in lines]


def meta_where() -> dict[str, list[str]]:
    """file:line links per model, from the README's generated Meta tooling table."""
    readme = (ROOT / "README.md").read_text()
    table = readme.split("<!-- BEGIN:meta-tooling -->")[1].split("<!-- END:meta-tooling -->")[0]
    out: dict[str, list[str]] = {}
    for row in table.splitlines():
        m = re.match(r"\| \*\*(.+?)\*\*", row)
        if m:
            out[m.group(1)] = re.findall(r"\[`([^`]+)`\]", row)[:3]
    return out


def table_row(table: dict[str, Any], config: str = "PS") -> dict[str, Any]:
    return next(r for r in table["rows"] if r.get("config") == config)


def build() -> dict[str, Any]:
    f = _facts()
    report = load("eval/reports/latest/report.json")
    bypass = load("eval/reports/latest/bypass.json")
    thresholds = load("eval/reports/latest/provenance.json")["thresholds"]
    weights = load("eval/reports/latest/open_weights.json")
    mesh = load("eval/reports/latest/program_vs_mesh.json")["summary"]
    links = load("docs/links.json")
    summary = load(f"data/replays/{RUN}/summary.json")
    bop = load(f"data/replays/{RUN}/buy_or_print.json")["prints"][0]
    events = run_events()
    tables = report["tables"]
    syn, single = table_row(tables["synthetic"]), table_row(tables["synthetic"], "B1")
    public_table = report["separate_tables"]["public_photos"]
    public = table_row(public_table)
    where = meta_where()
    models = f.meta_models(weights)
    for m in models:
        key = "Muse Voice Transcribe" if m["name"] == "Voice Transcribe" else m["name"]
        m["where"] = where.get(key, [])
    index_path = DECK / "models/index.json"
    index = json.loads(index_path.read_text()) if index_path.exists() else {}
    images = {p.stem: f"img/bypass-{p.stem}.jpg" for p in (ROOT / "eval/reports/latest/bypass").glob("*.jpg")}
    return {
        "generated_at": report["generated_at"],
        "report_date": report["generated_at"][:10],
        "git_sha": f.git("rev-parse", "--short", "HEAD"),
        "git_first": f.git("log", "--reverse", "--format=%ad", "--date=short").split()[0],
        "limit_mm": thresholds["HAUSDORFF_PASS_MM"],
        "run": {
            **f.stored_run(),
            "rounds_detail": rounds(events),
            "program": program_lines(),
            "minutes_to_file": minutes_to_file(events, summary["created_at"]),
            "filament_usd": bop["filament_cost"]["USD"],
            "assumptions": bop["assumptions"],
        },
        "time": {
            "synthetic": {"median_wall_s": syn["median_wall_s"], "usd_per_job": syn["usd_per_job"], "n": syn["n"]},
            "public": {
                "median_wall_s": public["median_wall_s"],
                "usd_per_job": public["usd_per_job"],
                "n": public["n"],
            },
            "rebake": index.get("rebake"),
        },
        "bypass": {
            "attempts": bypass["attempts"],
            "blocked": bypass["blocked"],
            "suite": bypass["suite"],
            "rows": [
                {
                    **{k: r.get(k) for k in ("id", "attack", "blocked", "blocked_by", "detail")},
                    "image": images.get(r["id"]),
                }
                for r in bypass["rows"]
            ],
        },
        "tests": f.tests(),
        "control": [tables["control"]["headline"]["correct"], tables["control"]["headline"]["n"]],
        "redteam": [tables["redteam"]["headline"]["correct"], tables["redteam"]["headline"]["n"]],
        "synthetic": {
            "n": syn["n"],
            "median_mm": syn["median_abs_err_mm"],
            "single_shot_median_mm": single["median_abs_err_mm"],
            "verified": round(syn["verified_rate"] * syn["n"]),
        },
        "public": {
            "n": public_table["headline"]["n"],
            "median_mm": round(public_table["headline"]["median_abs_err_mm"], 2),
            "verified": round(public["verified_rate"] * public["n"]),
            "verified_but_off": public["verified_but_off"],
        },
        "scale": f.public_scale(),
        "evaluation": f.scale_eval(),
        "audit": f.verified_audit(report),
        "real_parts": tables["real_ruler"].get("n") or 0,
        "mesh": {
            "median_mm": round(mesh["mesh_hole_spacing_shift_median_mm"], 2),
            "knob_median_mm": round(mesh["knob_hole_spacing_shift_median_mm"], 2),
            "max_mm": round(mesh["mesh_hole_spacing_shift_mm"], 2),
            "parts": mesh["parts"],
        },
        "open": {
            "share_pct": round(weights["builder"]["share_tokens_open_weights"] * 100),
            "calls": weights["builder"]["calls_on_open_weights"],
            "total": weights["builder"]["calls"],
        },
        "models": models,
        "registry": index.get("registry"),
        "voice": VOICE_TAKE,
        "landscape": LANDSCAPE,
        "next_steps": NEXT_STEPS,
        "outside": {k: v for k, v in f.OUTSIDE.items()},
        "links": {
            "site": links.get("live_site") or "",
            "video": links.get("video") or "",
            "repo": links.get("repo") or "",
        },
    }


# ------------------------------------------------------------------------------------------------------------- meshes


def encode_mesh(vertices: Any, faces: Any) -> bytes:
    """The deck's binary mesh: u32 vertex count, u32 triangle count, float32 positions, uint32 indices."""
    import numpy as np

    v = np.asarray(vertices, dtype="<f4")
    f = np.asarray(faces, dtype="<u4")
    return struct.pack("<II", len(v), len(f)) + v.tobytes() + f.tobytes()


def decode_counts(blob: bytes) -> tuple[int, int]:
    count = struct.unpack("<II", blob[:8])
    return int(count[0]), int(count[1])


def section_loops(mesh: Any, height: float) -> list[Any]:
    """Closed loops where the plane z = height cuts the mesh, chained from the cut's segments."""
    import numpy as np
    import trimesh

    segments: Any = trimesh.intersections.mesh_plane(  # type: ignore[no-untyped-call]
        mesh, plane_normal=[0, 0, 1], plane_origin=[0, 0, height]
    )
    links: dict[tuple[float, float], list[tuple[float, float]]] = {}
    for a, b in segments:
        ka, kb = (round(float(a[0]), 4), round(float(a[1]), 4)), (round(float(b[0]), 4), round(float(b[1]), 4))
        if ka != kb:
            links.setdefault(ka, []).append(kb)
            links.setdefault(kb, []).append(ka)
    loops, seen = [], set()
    for start in links:
        if start in seen:
            continue
        loop, cur, prev = [start], start, None
        seen.add(start)
        while True:
            nxt = next((n for n in links[cur] if n != prev and n not in seen), None)
            if nxt is None:
                break
            loop.append(nxt)
            seen.add(nxt)
            prev, cur = cur, nxt
        if len(loop) >= 3:
            loops.append(np.array(loop))
    return loops


def holes_in_plate(mesh: Any, height: float) -> list[dict[str, float]]:
    """Round through-holes at one height: every inner loop that closes on itself and is round, largest outline excluded."""
    import numpy as np

    out: list[dict[str, float]] = []
    loops = section_loops(mesh, height)
    if not loops:
        return out
    spans = [float(np.ptp(loop, axis=0).max()) for loop in loops]
    biggest = int(np.argmax(spans))
    for i, loop in enumerate(loops):
        if i == biggest:
            continue
        centre = loop.mean(axis=0)
        radii = np.linalg.norm(loop - centre, axis=1)
        if radii.mean() > 0 and radii.std() / radii.mean() < 0.08:
            out.append(
                {
                    "x": round(float(centre[0]), 3),
                    "y": round(float(centre[1]), 3),
                    "d": round(float(radii.mean() * 2), 3),
                }
            )
    return sorted(out, key=lambda h: h["x"])


def _get(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=180) as res:
        data: bytes = res.read()
    return data


def _bake(api: str, slug: str, params: dict[str, float], out: Path) -> dict[str, Any]:
    import trimesh

    query = "&".join(f"{k}={v:g}" for k, v in params.items())
    bake = json.loads(_get(f"{api}/api/v1/parts/{slug}/bake?{query}&format=stl"))
    mesh: Any = trimesh.load(io.BytesIO(_get(api + bake["artifacts"]["stl"])), file_type="stl", force="mesh")
    mesh.merge_vertices()
    out.write_bytes(encode_mesh(mesh.vertices, mesh.faces))
    low, high = mesh.bounds
    info = {
        "file": str(out.relative_to(DECK)),
        "params": bake["params"],
        "clamped": bake.get("clamped") or {},
        "size_mm": [round(float(high[i] - low[i]), 2) for i in range(3)],
        "triangles": len(mesh.faces),
        "ms": bake.get("ms"),
        "cache_hit": bake.get("cache_hit"),
    }
    if slug == STAR_SLUG:  # the bore is the narrowest cut through the plate (a countersink widens it towards one face)
        thickness = float(bake["params"].get("plate_thickness", 3.0))
        cuts = [holes_in_plate(mesh, float(low[2]) + thickness * k) for k in (0.1, 0.3, 0.5, 0.7, 0.9)]
        info["holes"] = min((c for c in cuts if c), key=lambda c: c[0]["d"], default=[])
    return info


def bake_all(api: str) -> None:
    out = DECK / "models"
    out.mkdir(parents=True, exist_ok=True)
    index: dict[str, Any] = {"parts": {}}
    for slug, knobs in KNOBS.items():
        part = json.loads(_get(f"{api}/api/v1/parts/{slug}"))
        specs = {p["name"]: p for p in part["params"]}
        entry: dict[str, Any] = {
            "title": part["title"],
            "status": part["status"],
            "max_error_mm": round(part["verification"]["max_error_mm"], 2)
            if part.get("verification", {}).get("max_error_mm") is not None
            else None,
            "knobs": {},
        }
        entry["base"] = _bake(api, slug, {}, out / f"{slug}.bin")
        for knob, values in knobs.items():
            spec = specs[knob]
            steps = []
            for v in values:
                info = _bake(api, slug, {knob: v}, out / f"{slug}__{knob}_{v:g}.bin")
                steps.append({"value": v, **info})
            entry["knobs"][knob] = {
                "label": spec.get("label", knob),
                "unit": spec.get("unit") or "",
                "default": spec["default"],
                "topology": bool(spec.get("topology")),
                "steps": steps,
            }
        index["parts"][slug] = entry
        print(slug, sum(len(k["steps"]) for k in entry["knobs"].values()), "variants", flush=True)
    star: dict[str, Any] = {
        "slug": STAR_SLUG,
        "base": _bake(api, STAR_SLUG, STAR_BASE, out / "star-base.bin"),
        "knobs": {},
    }
    for knob, values in STAR_KNOBS.items():
        star["knobs"][knob] = [
            {"value": v, **_bake(api, STAR_SLUG, {**STAR_BASE, knob: v}, out / f"star__{knob}_{v:g}.bin")}
            for v in values
        ]
    index["star"] = star
    index["rebake"] = fresh_rebake(api)
    listing = json.loads(_get(f"{api}/api/v1/parts?limit=100"))["items"]
    index["registry"] = {
        "parts": len(listing),
        "verified": sum(1 for p in listing if p.get("verified")),
        "items": [{"slug": p["slug"], "title": p["title"], "verified": p["verified"]} for p in listing],
    }
    (out / "index.json").write_text(json.dumps(index, indent=1))
    total = sum(p.stat().st_size for p in out.glob("*.bin"))
    print(f"{len(list(out.glob('*.bin')))} meshes, {total / 1e6:.1f} MB")


def fresh_rebake(api: str) -> dict[str, Any]:
    """The time to re-bake a part nobody has asked for at this size: a value no earlier bake used, so no cache answers."""
    for step in range(200):
        value = 47.0 + step * 0.1 + 0.03
        bake = json.loads(_get(f"{api}/api/v1/parts/battery-cover-45mm/bake?length={value:.2f}&format=stl"))
        if not bake.get("cache_hit"):
            return {
                "ms": round(bake["ms"]),
                "cache_hit": False,
                "slug": "battery-cover-45mm",
                "length_mm": round(value, 2),
                "api_mode": "local server, replay mode",
            }
    raise RuntimeError("every bake hit the cache")


# ------------------------------------------------------------------------------------------------------------- assets


def _ffmpeg(*args: str) -> None:
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", *args], check=True)


def _write_photo_crop(photo: Path, overlay: Path, out: Path) -> None:
    """The part of the photo the measured-outline picture shows, in the same frame, so a wipe between them lines up."""
    import cv2

    full: Any = cv2.imread(str(photo))
    over: Any = cv2.imread(str(overlay))
    best: tuple[float, float, tuple[int, int]] = (-1.0, 1.0, (0, 0))
    small = cv2.resize(over, None, fx=0.25, fy=0.25)
    for k in [x / 100 for x in range(50, 201, 2)]:  # overlay pixels per photo pixel
        scaled = cv2.resize(full, None, fx=k * 0.25, fy=k * 0.25)
        if scaled.shape[0] < small.shape[0] or scaled.shape[1] < small.shape[1]:
            continue
        _, score, _, loc = cv2.minMaxLoc(cv2.matchTemplate(scaled, small, cv2.TM_CCOEFF_NORMED))
        if score > best[0]:
            best = (float(score), k, (int(loc[0] * 4), int(loc[1] * 4)))
    score, k, (x, y) = best
    print(f"photo crop: match {score:.3f}, scale {k:.2f}")
    scaled = cv2.resize(full, None, fx=k, fy=k)
    h, w = over.shape[:2]
    cv2.imwrite(str(out), scaled[y : y + h, x : x + w], [cv2.IMWRITE_JPEG_QUALITY, 86])


def copy_assets() -> None:
    img = DECK / "img"
    img.mkdir(parents=True, exist_ok=True)
    stills = WORK / "stills"
    for name in (
        "story-father",
        "story-band",
        "story-snapped",
        "story-shop",
        "story-printer",
        "story-heap",
        "story-resolved",
    ):
        _ffmpeg("-i", str(stills / f"{name}.png"), "-vf", "scale=1600:-2", "-q:v", "4", str(img / f"{name}.jpg"))
    for name in (
        "flow-photo",
        "see-rect",
        "see-mask",
        "see-measure",
        "see-heat1",
        "see-heat2",
        "see-heat3",
        "flow-review",
    ):
        _ffmpeg(
            "-i", str(stills / f"{name}.jpg"), "-vf", "scale='min(1400,iw)':-2", "-q:v", "4", str(img / f"{name}.jpg")
        )
    _ffmpeg("-i", str(stills / "flow-model.png"), str(img / "flow-model.jpg"))
    _write_photo_crop(stills / "flow-photo.jpg", stills / "see-measure.jpg", img / "see-photo-crop.jpg")
    for p in (ROOT / "eval/reports/latest/bypass").glob("*.jpg"):
        _ffmpeg("-i", str(p), "-vf", "scale='min(1000,iw)':-2", "-q:v", "4", str(img / f"bypass-{p.stem}.jpg"))
    marks = json.loads((WORK / "clips/say.marks.json").read_text())
    start = max(0.0, marks["talk"] - 0.4)
    length = marks["applied"] + 3 - start
    _ffmpeg(
        "-ss", f"{start:.2f}", "-t", f"{length:.2f}", "-i", str(WORK / "clips/say.good.mp4"), "-an", "-vf", "crop=540:560:848:145,fps=24", "-c:v", "libx264", "-crf", "26",
        "-preset", "slow", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(DECK / "voice.mp4"),
    )  # fmt: skip


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bake", action="store_true")
    parser.add_argument("--assets", action="store_true")
    parser.add_argument("--api", default="http://127.0.0.1:8766")
    args = parser.parse_args()
    DECK.mkdir(parents=True, exist_ok=True)
    if args.bake:
        bake_all(args.api)
    if args.assets:
        copy_assets()
    (DECK / "data.json").write_text(json.dumps(build(), ensure_ascii=False, indent=1))
    print("wrote", DECK / "data.json")


if __name__ == "__main__":
    main()
