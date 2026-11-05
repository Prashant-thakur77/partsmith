"""The evidence behind `/proof` as one response: each suite with its n, confidence interval, ground truth, source file and
the command that reproduces it, every test gate, and what has not been tested. Read only from `eval/reports/latest`; a file
that has not been generated gives an empty section, never a number typed in here.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from fastapi import APIRouter

from services.common.paths import REPO_ROOT

router = APIRouter(prefix="/api/v1", tags=["bench"])

REPORTS = REPO_ROOT / "eval" / "reports" / "latest"
LATEST = "eval/reports/latest"


def _load(name: str) -> dict[str, Any]:
    try:
        data = json.loads((REPORTS / name).read_text())
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _ps_row(table: Mapping[str, Any]) -> dict[str, Any]:
    return next((r for r in table.get("rows") or [] if r.get("config") == "PS"), {})


def _row(table: Mapping[str, Any], config: str) -> dict[str, Any]:
    return next((r for r in table.get("rows") or [] if r.get("config") == config), {})


def _mm(v: Any) -> str | None:
    return f"{round(float(v), 2):g} mm" if isinstance(v, int | float) else None


def _errors(report: Mapping[str, Any]) -> list[dict[str, Any]]:
    """The full-loop tables: median error per dimension against the suite's own ground truth."""
    out = []
    tables = report.get("tables") or {}
    separate = report.get("separate_tables") or {}
    suites = (
        ("synthetic", tables.get("synthetic"), "Rendered photos", "Exact: the mesh each photo was rendered from.",
         "Rendered from our own part templates, so this tests the pipeline, not real lighting or real plastic.", "make bench"),
        ("reference_objects", tables.get("reference_objects"), "Reference objects, rendered", "Published sizes of a card, an SD card, a LEGO brick and an AA cell.",
         "Renders of objects with known sizes, not photos of them.", "make bench"),
        ("public_photos", separate.get("public_photos"), "Real objects in public photos", "Published sizes of each object.",
         "Real photographs pasted on a rendered mat, not phone captures, so they never count as real photos measured.", "uv run python -m eval.public_photos"),
    )  # fmt: skip
    for key, table, title, truth, label, command in suites:
        if not table:
            continue
        row = _ps_row(table)
        if not row:
            continue
        out.append(
            {
                "id": key,
                "title": title,
                "headline": _mm(row.get("median_abs_err_mm")),
                "what": "median error per dimension, full loop",
                "n": row.get("n"),
                "ci": row.get("mean_ci95"),
                "ci_of": "95 % interval of the mean error",
                "ground_truth": truth,
                "label": label,
                "detail": f"{round(float(row.get('verified_rate') or 0) * int(row.get('n') or 0))} of {row.get('n')} verified; "
                f"{row.get('verified_but_off')} verified parts were over 0.5 mm off",
                "source": f"{LATEST}/report.json",
                "command": command,
            }
        )
    single = _row(tables.get("synthetic") or {}, "B1")
    loop = _ps_row(tables.get("synthetic") or {})
    if single and loop:
        out.append(
            {
                "id": "single_vs_loop",
                "title": "Single shot against the full loop",
                "headline": f"{single.get('median_abs_err_mm')} → {loop.get('median_abs_err_mm')} mm",
                "what": "median error per dimension, same photos",
                "n": loop.get("n"),
                "ci": None,
                "ci_of": None,
                "ground_truth": "Exact: the mesh each photo was rendered from.",
                "label": "Rendered photos.",
                "detail": f"Verified: {single.get('verified_but_off', '').split('/')[-1]} of {single.get('n')} with one shot, "
                f"{loop.get('verified_but_off', '').split('/')[-1]} of {loop.get('n')} with the loop",
                "source": f"{LATEST}/report.json",
                "command": "make bench",
            }
        )
    return out


def _gates(report: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Outcome suites: did the system do the expected thing."""
    out = []
    tables = report.get("tables") or {}
    bypass = _load("bypass.json")
    if bypass.get("attempts"):
        out.append(
            {
                "id": "bypass",
                "title": "A model that lies",
                "headline": f"{bypass.get('blocked')}/{bypass.get('attempts')} blocked",
                "what": "attacks where a model claims a wrong part passed",
                "n": bypass.get("attempts"),
                "ci": None,
                "ci_of": None,
                "ground_truth": "The part is wrong by construction, so the right answer is always to block it.",
                "label": "Scripted attacks on the real verifier and export check; no model calls.",
                "detail": None,
                "source": f"{LATEST}/bypass.json",
                "command": "uv run python -m eval.bypass",
            }
        )
    for key, title, what, truth in (
        ("redteam", "Bad photos", "photos that must be rejected or refused", "Each photo has an expected outcome set in advance."),
        ("control", "Intact parts", "normal photos that must be accepted", "Each photo has an expected outcome set in advance."),
    ):  # fmt: skip
        head = (tables.get(key) or {}).get("headline") or {}
        if not head.get("n"):
            continue
        out.append(
            {
                "id": key,
                "title": title,
                "headline": f"{head.get('correct')}/{head.get('n')} correct",
                "what": what,
                "n": head.get("n"),
                "ci": head.get("ci95"),
                "ci_of": "95 % Wilson interval",
                "ground_truth": truth,
                "label": "Rendered photos.",
                "detail": None,
                "source": f"{LATEST}/report.json",
                "command": "make bench",
            }
        )
    return out


def _instruments() -> list[dict[str, Any]]:
    """Checks on the measuring and on the program itself."""
    out = []
    scale = (_load("public_scale.json").get("summary")) or {}
    if scale.get("n_corners"):
        ci = scale.get("ci95_pct") or []
        out.append(
            {
                "id": "public_scale",
                "title": "Marker scale on real camera photos",
                "headline": f"{round(float(scale['mean_err_pct']), 2):g} %",
                "what": f"held-out corner error, about {round(float(scale.get('mean_err_mm_over_100mm') or 0), 2):g} mm over a 100 mm span",
                "n": scale.get("n_corners"),
                "ci": f"[{ci[0]}, {ci[1]}] %" if len(ci) == 2 else None,
                "ci_of": "95 % interval over held-out markers",
                "ground_truth": "The documented layout of each printed board.",
                "label": f"{scale.get('n_photos')} public photos of printed boards. Says nothing about a phone photographing a laptop screen.",
                "detail": None,
                "source": f"{LATEST}/public_scale.json",
                "command": "uv run python -m eval.public_scale",
            }
        )
    mesh = (_load("program_vs_mesh.json").get("summary")) or {}
    if mesh.get("parts"):
        out.append(
            {
                "id": "program_vs_mesh",
                "title": "Stretching a mesh against turning a knob",
                "headline": f"{round(float(mesh['mesh_hole_spacing_shift_median_mm']), 2):g} mm against {round(float(mesh['knob_hole_spacing_shift_median_mm']), 2):g} mm",
                "what": "median shift in hole spacing for one hole edit",
                "n": mesh.get("parts"),
                "ci": None,
                "ci_of": None,
                "ground_truth": "Each variant built in the sandbox and measured by the verifier's solid features.",
                "label": f"Pure code, no models; {mesh.get('rows')} edits across {mesh.get('parts')} parts.",
                "detail": f"Worst case: {round(float(mesh.get('mesh_hole_spacing_shift_mm') or 0), 2):g} mm for the mesh, {round(float(mesh.get('knob_hole_spacing_shift_mm') or 0), 2):g} mm for the knob",
                "source": f"{LATEST}/program_vs_mesh.json",
                "command": "uv run python -m eval.program_vs_mesh",
            }
        )
    return out


def _test_gates() -> dict[str, Any]:
    t = _load("tests.json")
    gates = []
    for key, g in (t.get("gates") or {}).items():
        if not isinstance(g, dict):
            continue
        gates.append(
            {
                "id": key,
                "title": g.get("title") or key,
                "status": g.get("status") or "not run",
                "tests": g.get("tests"),
                "passed": g.get("passed"),
                "failed": g.get("failed"),
                "skipped": g.get("skipped"),
                "command": g.get("command"),
            }
        )
    return {
        "generated_at": t.get("generated_at"),
        "git": (t.get("git") or {}).get("sha"),
        "gates": gates,
        "source": f"{LATEST}/tests.json",
    }


def _audit(report: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Every verified full-loop part against ground truth on every size, including the misses."""
    names = {
        "synthetic": "Rendered parts",
        "reference_objects": "Reference objects, rendered",
        "control": "Intact parts, top photo only",
        "public_photos": "Public photos, pasted on a rendered mat",
        "redteam": "Bad or unsuitable photos",
    }
    runs = report.get("runs") or {}
    out = []
    for key, name in names.items():
        rows = (runs.get(key) or {}).get("PS") or []
        if not rows:
            continue
        verified = [r for r in rows if r.get("verified")]
        off = [r for r in verified if (r.get("max_abs_err_mm") or 0) > 0.5]
        out.append(
            {
                "suite": name,
                "runs": len(rows),
                "verified": len(verified),
                "within": len(verified) - len(off),
                "off": len(off),
            }
        )
    return out


def _not_tested(report: Mapping[str, Any]) -> dict[str, Any]:
    from services.review.store import stats

    secs = (report.get("measure_only") or {}).get("sections") or {}
    photos = sum(int((secs.get(k) or {}).get("n_photos") or 0) for k in ("reference_objects_real", "real_parts_ruler"))
    ruler = (report.get("tables") or {}).get("real_ruler") or {}
    parts = int(ruler.get("n") or 0) if ruler.get("status") == "ok" else 0
    try:
        reviewed = stats()
        people, scripted = int(reviewed["n"]), int(reviewed["tests_excluded"])
    except Exception:  # an unavailable review log reads as none counted, never as a guess
        people, scripted = 0, 0
    return {
        "real_phone_photos_measured": photos,
        "real_parts_with_ruler_ground_truth": parts,
        "real_prints_or_repairs_logged": int(_load("impact.json").get("n_sessions") or 0),
        "person_reviewed_rounds": people,
        "scripted_review_decisions": scripted,
    }


def _scale() -> dict[str, Any] | None:
    """The scale evaluation when it has run: fresh live runs, reported with their planned and actual sizes."""
    s = _load("scale.json")
    if not s:
        return None
    keep = ("generated_at", "label", "runs", "planned", "not_run", "statuses", "usd", "wall_s", "tables", "paired_b1_vs_ps",
            "verified_but_off", "understanding", "mask_sources", "sam", "wonder", "voice", "stop")  # fmt: skip
    return {k: s.get(k) for k in keep} | {
        "source": f"{LATEST}/scale.json",
        "command": "uv run python -m eval.scale_report",
    }


@router.get("/proof", summary="The evidence, suite by suite, with sources, commands and what has not been tested")
def proof() -> dict[str, Any]:
    report = _load("report.json")
    return {
        "report_date": str(report.get("generated_at") or "")[:10] or None,
        "report_mode": report.get("label"),
        "errors": _errors(report),
        "outcomes": _gates(report),
        "instruments": _instruments(),
        "tests": _test_gates(),
        "audit": _audit(report),
        "scale": _scale(),
        "not_tested": _not_tested(report),
    }
