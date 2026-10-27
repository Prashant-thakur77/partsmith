"""PartSmith MCP server: the registry and the fix pipeline as tools for coding agents.

Transports: stdio (`python -m services.mcp --stdio`) and streamable HTTP (mounted at `/mcp` on the API app, or
`python -m services.mcp --http --port 8001`). Every tool is read-only except `start_fix_job` and `report_need`, which
say so in their annotations; `--read-only` (or PARTSMITH_MCP_READ_ONLY=1) leaves them out. Errors name the closest
valid slugs/parameters. Local file paths are accepted only over stdio (the HTTP server never reads its own disk).
"""

from __future__ import annotations

import base64
import binascii
import importlib
import os
from pathlib import Path
from typing import Annotated, Any
from urllib.parse import urlencode

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from partsmith_schemas import JobInput
from partsmith_schemas.partspec import Family
from pydantic import Field

from services.api import agentdocs
from services.geom_worker.bake import BakeError
from services.geom_worker.program import ProgramError, UnknownParamError
from services.registry import parts as P
from services.registry.store import get_registry

READ_ONLY = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False)
WRITES = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False)
MAX_INLINE_BYTES = 25 * 1024 * 1024

INSTRUCTIONS = (
    "PartSmith: a registry of 3D-printable functional parts that are parametric CadQuery programs (units: mm), plus a "
    "photo-to-part pipeline. Search before you build. Never rescale a part to force a fit: change the right knob "
    "(get_variant maps plain words to knobs and clamps them). If nothing matches, say so and call report_need. "
    "Report which dimensions were measured vs assumed, and quote verification status and max_error_mm exactly."
)


def _abs(url: str) -> str:
    return agentdocs.base_url() + url if url.startswith("/") else url


def _web(path: str) -> str:
    return os.environ.get("PARTSMITH_WEB_URL", "http://localhost:3000").rstrip("/") + path


def _svc() -> Any:
    try:
        return importlib.import_module("services.agent.service")
    except ImportError as exc:
        raise ToolError("the PartSmith agent service is not available in this build") from exc


def _part(slug: str) -> Any:
    try:
        return P.require_part(slug)
    except P.PartNotFound as exc:
        hint = f" Closest slugs: {', '.join(exc.closest)}." if exc.closest else " Try search_parts."
        raise ToolError(f"No part {slug!r}.{hint}") from exc


def _card(part: Any) -> dict[str, Any]:
    c = P.part_card(part)
    c["thumbnail_url"] = _abs(c["thumbnail_url"])
    c["thumbnail_2x_url"] = _abs(c["thumbnail_2x_url"])
    c["url"] = _abs(f"/api/v1/parts/{part.slug}")
    c["page"] = _web(f"/parts/{part.slug}")
    return c


def _bytes(path: str | None, b64: str | None, field: str, allow_paths: bool) -> bytes | None:
    if b64:
        try:
            data = base64.b64decode(b64.split(",", 1)[-1], validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ToolError(f"{field}_base64 is not valid base64") from exc
        return data
    if path:
        if not allow_paths:
            raise ToolError(f"{field}_path is only accepted over stdio; send {field}_base64 instead")
        p = Path(path).expanduser()
        if not p.is_file():
            raise ToolError(f"{field}_path {path!r} is not a file")
        if p.stat().st_size > MAX_INLINE_BYTES:
            raise ToolError(f"{field}_path is larger than {MAX_INLINE_BYTES // 2**20} MB")
        return p.read_bytes()
    return None


def _clean(data: bytes, field: str) -> bytes:
    from services.api.errors import ApiError
    from services.api.uploads import clean_image

    try:
        return clean_image(data, field)[0]
    except ApiError as exc:
        raise ToolError(exc.message) from exc


def build_server(*, allow_paths: bool = False, read_only: bool | None = None) -> MCPServer:
    """The MCP server with every PartSmith tool registered. `allow_paths`: accept local file paths (stdio only)."""
    if read_only is None:
        read_only = os.environ.get("PARTSMITH_MCP_READ_ONLY", "0") == "1"
    server: MCPServer = MCPServer(
        name="partsmith",
        title="PartSmith",
        instructions=INSTRUCTIONS,
        version="0.1.0",
        website_url=agentdocs.base_url(),
    )

    @server.tool(annotations=READ_ONLY)
    def search_parts(
        q: Annotated[str, Field(description="What you need, with sizes if known, e.g. 'cable clip 8 mm'")] = "",
        family: Annotated[str | None, Field(description="Family filter, e.g. knob, hook, cable_clip, wheel")] = None,
        verified: Annotated[bool | None, Field(description="Only verified (true) or only unverified (false)")] = None,
        limit: Annotated[int, Field(ge=1, le=50)] = 10,
    ) -> dict[str, Any]:
        """Search the PartSmith registry. Numbers in the query boost parts with a matching default dimension.
        Example: search_parts(q="caster wheel 50 mm"). Returns {items: [card], total, coverage}. coverage="none"
        means nothing matched: say so and offer report_need instead of substituting an unrelated part."""
        items, total = get_registry().search(q, family=family, verified=verified, limit=limit)
        coverage = "none" if not items else ("good" if total >= 1 and q else "browse")
        return {"items": [_card(p) for p in items], "total": total, "coverage": coverage}

    @server.tool(annotations=READ_ONLY)
    def get_part(slug: Annotated[str, Field(description="Part slug from search_parts")]) -> dict[str, Any]:
        """Everything about one part: knobs (name, default, min, max, step, unit, topology), the verification
        record (status, max_error_mm, tests), provenance (origin real/synthetic), printing facts and download URLs.
        Example: get_part(slug="caster-wheel-50")."""
        part = _part(slug)
        d = P.part_detail(part)
        d.pop("code", None)
        d["artifacts"] = {k: _abs(v) for k, v in d["artifacts"].items()}
        d["thumbnail_url"] = _abs(d["thumbnail_url"])
        d["thumbnail_2x_url"] = _abs(d["thumbnail_2x_url"])
        d["page"] = _web(f"/parts/{slug}")
        return d

    @server.tool(annotations=READ_ONLY)
    def get_variant(
        slug: Annotated[str, Field(description="Part slug")],
        want: Annotated[
            str, Field(description="Plain words, e.g. 'M4 hole, 2 mm taller', 'for a 25 mm rail', '3 ribs'")
        ],
    ) -> dict[str, Any]:
        """Map plain words to knob values. Code clamps every value to its range, maps near-miss names to the real
        knob and refuses uniform rescaling. Returns {params, applied, not_applied, confidence, mode, bake_url}.
        If confidence < 0.8 or not_applied is non-empty, tell the user exactly what was and was not applied."""
        _part(slug)
        v = P.variant(slug, want)
        out: dict[str, Any] = v.model_dump(mode="json")
        out["bake_url"] = _abs(f"/api/v1/parts/{slug}/bake?" + urlencode({**v.params, "format": "stl,step,3mf"}))
        return out

    @server.tool(annotations=READ_ONLY)
    def bake(
        slug: Annotated[str, Field(description="Part slug")],
        params: Annotated[
            dict[str, float] | None, Field(description="Knob values in mm (or counts); others keep defaults")
        ] = None,
        formats: Annotated[list[str] | None, Field(description="Any of stl, 3mf, step, glb, view, py")] = None,
        inline_stl_path: Annotated[bool, Field(description="Also return the local STL file path (stdio only)")] = False,
    ) -> dict[str, Any]:
        """Build the part at these parameters and return download URLs (content-addressed: an identical request is a
        free cache hit). `clamped` lists values that had to change to stay in range. Example:
        bake(slug="cable-clip-8", params={"cable_d": 8.0}, formats=["stl", "step"])."""
        part = _part(slug)
        try:
            fmts = P.parse_formats(formats or ["stl", "step", "3mf"])
            out = P.bake_output(part, params or {}, fmts)
        except UnknownParamError as exc:
            raise ToolError(f"{exc}. Valid knobs: {', '.join(p.name for p in part.params)}") from exc
        except (ProgramError, ValueError) as exc:
            raise ToolError(str(exc)) from exc
        except BakeError as exc:
            raise ToolError(f"the part program failed to build: {exc}") from exc
        res: dict[str, Any] = out.to_bake_result(
            slug, lambda fmt, p: _abs(P.bake_url(out.cache_key, p.name))
        ).model_dump(mode="json")
        if inline_stl_path and allow_paths and "stl" in out.files:
            res["stl_path"] = str(out.files["stl"])
        return res

    @server.tool(annotations=READ_ONLY)
    def find_matching(slug: Annotated[str, Field(description="Part slug")]) -> dict[str, Any]:
        """Parts that go with this one: declared mating parts, parts sharing an interface dimension (same screw
        hole, pin or bore within 0.05 mm), then the same family. Each item carries a `reason`."""
        _part(slug)
        return {"items": [dict(_card(p), reason=why) for p, why in P.matching(slug)]}

    @server.tool(annotations=READ_ONLY)
    def list_families() -> dict[str, Any]:
        """Part families with part and verified counts."""
        fams = get_registry().families()
        return {"families": [dict(f, title=P.FAMILY_TITLES.get(f["family"], f["family"])) for f in fams]}

    @server.tool(annotations=READ_ONLY)
    def measure_photo(
        image_base64: Annotated[
            str | None, Field(description="JPEG/PNG/WebP bytes, base64 (data: URLs accepted)")
        ] = None,
        path: Annotated[str | None, Field(description="Local image path (stdio transport only)")] = None,
        view: Annotated[str, Field(description="top or side")] = "top",
        thickness_mm: Annotated[float | None, Field(description="Thickness if the user knows it", gt=0)] = None,
        mat_id: Annotated[str | None, Field(description="Mat id if known, e.g. screen-m, paper-a4")] = None,
    ) -> dict[str, Any]:
        """Measure a part photographed on a PartSmith mat: capture-gate report, calibration and measurements in mm
        (outline, length, width, holes with diameters), each value tagged measured/user_stated/inferred."""
        data = _bytes(path, image_base64, "image", allow_paths)
        if data is None:
            raise ToolError("send image_base64 (or path over stdio)")
        res = dict(_svc().measure(_clean(data, "image"), view, thickness_mm=thickness_mm, mat_id=mat_id))
        if isinstance(res.get("overlay_url"), str):
            res["overlay_url"] = _abs(res["overlay_url"])
        return res

    @server.tool(annotations=READ_ONLY)
    def get_job(job_id: Annotated[str, Field(description="Job id from start_fix_job")]) -> dict[str, Any]:
        """Status of a fix job: summary (status, verified, max_error_mm), verification, params/values, artifact
        URLs and a pending question if the job is waiting for an answer (answer it in the web app)."""
        try:
            d = dict(_svc().job_detail(job_id))
        except KeyError as exc:
            raise ToolError(f"no job {job_id!r}") from exc
        events = d.pop("events", [])
        d.pop("code", None)
        d["events_count"] = len(events)
        d["artifacts"] = {k: _abs(v) for k, v in (d.get("artifacts") or {}).items()}
        d["page"] = _web(f"/jobs/{job_id}")
        return d

    if read_only:
        return server

    @server.tool(annotations=WRITES)
    def start_fix_job(
        top_base64: Annotated[str | None, Field(description="Top-view photo on the mat, base64")] = None,
        top_path: Annotated[str | None, Field(description="Top-view photo path (stdio only)")] = None,
        side_base64: Annotated[str | None, Field(description="Optional side-view photo, base64")] = None,
        side_path: Annotated[str | None, Field(description="Optional side-view photo path (stdio only)")] = None,
        intent: Annotated[
            str, Field(description="What broke / what to change, e.g. 'hook snapped, 1 mm thicker'")
        ] = "",
        thickness_mm: Annotated[float | None, Field(description="Thickness if known", gt=0)] = None,
        family_hint: Annotated[
            str | None, Field(description="clip, knob, bracket, hook, spacer, cover, wheel, ...")
        ] = None,
    ) -> dict[str, Any]:
        """WRITES: start the photo-to-part pipeline (spends model budget). Returns the job summary and a web page
        where the run streams live; poll get_job until status is done."""
        top = _bytes(top_path, top_base64, "top", allow_paths)
        if top is None:
            raise ToolError("a top-view photo is required (top_base64, or top_path over stdio)")
        photos = {"top": _clean(top, "top")}
        side = _bytes(side_path, side_base64, "side", allow_paths)
        if side is not None:
            photos["side"] = _clean(side, "side")
        fam = Family(str(family_hint)) if family_hint in Family.__members__ else None
        job = _svc().start_fix_job(photos, JobInput(intent=intent[:500], thickness_mm=thickness_mm, family_hint=fam))
        return {
            "job": job.summary.model_dump(mode="json"),
            "page": _web(f"/jobs/{job.id}"),
            "events_url": _abs(f"/api/v1/jobs/{job.id}/events"),
        }

    @server.tool(annotations=WRITES)
    def report_need(
        query: Annotated[
            str, Field(description="The part nobody has yet, with sizes, e.g. 'dishwasher rack wheel 22 mm'")
        ],
    ) -> dict[str, Any]:
        """WRITES one row: request a part that is not in the registry (repeat requests add a vote)."""
        q = query.strip()
        if len(q) < 3:
            raise ToolError("describe the part in a few words")
        need: dict[str, Any] = get_registry().add_need(q).model_dump(mode="json")
        return need

    return server


_http_server: MCPServer | None = None


def http_server() -> MCPServer:
    """Process-wide server used for the HTTP mount (no local paths)."""
    global _http_server
    if _http_server is None:
        _http_server = build_server(allow_paths=False)
    return _http_server


if __name__ == "__main__":  # `python -m services.mcp.server` (Makefile `mcp` target) = stdio
    from services.mcp.__main__ import main

    raise SystemExit(main(["--stdio"]))
