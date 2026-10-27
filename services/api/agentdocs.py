"""`/llms.txt` (reference) and `/prompt.txt` (working instructions for coding agents), generated from the live registry
and the route table, so the numbers in them always match the database."""

from __future__ import annotations

import os

from services.registry import parts as P
from services.registry.store import Registry, get_registry

MCP_TOOLS = [
    ("search_parts", "search the registry (q, family, verified)"),
    ("get_part", "a part's params, verification and printing facts"),
    ("get_variant", "plain words -> clamped params + confidence + a bake URL"),
    ("bake", "params -> STL/3MF/STEP/GLB/part.py URLs (cache hits are free)"),
    ("find_matching", "parts that share an interface (same screw, pin, bore) or family"),
    ("list_families", "families with counts"),
    ("measure_photo", "photo on a PartSmith mat -> millimetres"),
    ("start_fix_job", "photos -> a verified parametric part (writes: starts a job)"),
    ("get_job", "status, verification and artifacts of a job"),
    ("report_need", "ask for a part that does not exist yet (writes: one row)"),
]

RULES = [
    "Search before you build: call search_parts first and reuse a verified part when one fits.",
    "Never rescale a part to force a fit. Change the knob that matters (hole_d, height, cable_d ...).",
    "If nothing matches, say so plainly and call report_need. Do not substitute an unrelated part.",
    "Report which dimensions were measured, which were stated by the user and which were assumed.",
    "Quote verification numbers exactly as returned (max_error_mm, status). 'best_effort' is not 'verified'.",
    "Synthetic parts are labelled origin=synthetic: they were verified against rendered images, not a real photo.",
    "When get_variant confidence is below 0.8, tell the user what was applied and what was not.",
    "Units are millimetres everywhere.",
]


def base_url() -> str:
    return os.environ.get("PARTSMITH_PUBLIC_URL", "http://localhost:8000").rstrip("/")


def llms_txt(reg: Registry | None = None) -> str:
    reg = reg or get_registry()
    stats = reg.stats()
    fams = sorted(reg.families(), key=lambda f: -f["count"])
    parts, total = reg.search("", sort="title", limit=60)
    b = base_url()
    lines = [
        "# PartSmith",
        "",
        "> Photos of a broken plastic part on a calibration mat -> measured millimetres -> a verified, parametric "
        "CadQuery program (STL/3MF/STEP). An open registry of parts that are programs, not meshes.",
        "",
        f"Registry right now: {stats['parts']} parts, {stats['verified']} verified "
        f"({stats['real']} real, {stats['synthetic']} synthetic). Units: mm.",
        "",
        "## Families",
        *[
            f"- {f['family']}: {P.FAMILY_TITLES.get(f['family'], f['family'])} — {f['count']} parts, "
            f"{f['verified']} verified"
            for f in fams
        ],
        "",
        f"## Parts ({len(parts)} of {total})",
    ]
    for p in parts:
        v = p.verification
        err = f", max error {v.max_error_mm:.2f} mm" if v and v.max_error_mm is not None else ""
        knobs = ", ".join(s.name for s in p.params[:8])
        lines.append(
            f"- [{p.title}]({b}/api/v1/parts/{p.slug}): {p.status}, origin {p.provenance.origin.value}{err}; "
            f"knobs: {knobs}"
        )
    lines += [
        "",
        "## REST API (base " + b + "/api/v1, OpenAPI at /api/v1/openapi.json)",
        "- GET /parts?q=&family=&verified=&sort=relevance|newest|error|title&cursor=&limit= — search",
        "- GET /parts/{slug} — record, params, verification, facts, artifact URLs",
        "- GET /parts/{slug}/params — typed knobs (name, default, min, max, step, unit, topology)",
        "- GET /parts/{slug}/bake?<param>=<mm>&format=stl|3mf|step|glb|view|py[&download=1] — build files",
        "- GET /parts/{slug}/variant?want=<plain words> — params + applied + not_applied + confidence",
        "- GET /parts/{slug}/matching — parts that share an interface",
        "- GET /parts/{slug}/template.pdf?<params> — 1:1 paper template",
        "- GET /families · GET /stats · POST /needs {query}",
        "- POST /jobs/fix (multipart top, side?, mating?, intent, thickness_mm) · GET /jobs/{id} · GET /jobs/{id}/events (SSE)",
        "- POST /measure (multipart photo) · POST /verify {part, params, measurements}",
        "",
        "## MCP",
        f"- Streamable HTTP: {b}/mcp",
        "- stdio: `uv run python -m services.mcp --stdio` (from the repo root)",
        *[f"- {name}: {desc}" for name, desc in MCP_TOOLS],
        "",
        "## Rules for agents",
        *[f"- {r}" for r in RULES],
        "",
        f"Working instructions: {b}/prompt.txt",
    ]
    return "\n".join(lines) + "\n"


def prompt_txt(reg: Registry | None = None) -> str:
    reg = reg or get_registry()
    stats = reg.stats()
    b = base_url()
    return (
        "\n".join(
            [
                "You can use PartSmith to find, adapt and build 3D-printable replacement parts.",
                f"Registry: {stats['parts']} parts ({stats['verified']} verified). API: {b}/api/v1 · MCP: {b}/mcp.",
                "",
                "How to work:",
                "1. Browse first: search_parts (or GET /api/v1/parts?q=...) with the object and its size, e.g. 'cable clip 8 mm'.",
                "2. Read the part: get_part gives the knobs (min/max/step), the verification record and printing facts.",
                "3. Adapt with words or numbers: get_variant(slug, want='M4 hole, 2 mm taller'), then bake(slug, params).",
                "   Report `applied` and `not_applied` back to the user; anything not applied did not happen.",
                "4. Download: bake returns URLs for STL, 3MF, STEP, GLB, view.json and part.py (the editable program).",
                "5. No match: say so and call report_need(query). For a broken part with photos, start_fix_job.",
                "",
                "Rules:",
                *[f"- {r}" for r in RULES],
                "- Never print or commit API keys. PartSmith browsing needs none.",
                "",
                f"Reference: {b}/llms.txt",
            ]
        )
        + "\n"
    )
