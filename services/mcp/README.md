# PartSmith MCP server

The registry and the photo-to-part pipeline as MCP tools. Same code, two transports:

| Transport | How |
|---|---|
| stdio | `uv run python -m services.mcp --stdio` (run from the repo root) |
| streamable HTTP | `http://localhost:8000/mcp` on the API app (`make api`), or standalone: `uv run python -m services.mcp --http --port 8001` → `http://localhost:8001/mcp` |

No key is needed to browse. Without model keys every model stage runs as a labelled deterministic mock (see `/api/v1/status`).
Absolute URLs in tool results use `PARTSMITH_PUBLIC_URL` (default `http://localhost:8000`) and `PARTSMITH_WEB_URL`
(default `http://localhost:3000`).

## Tools

| Tool | Writes? | What it does |
|---|---|---|
| `search_parts(q, family?, verified?, limit?)` | no | Search; numbers in `q` prefer parts with a matching dimension. Returns `coverage` (0–1, share of the query's words and numbers matched) and `match` good / partial / none with a `hint`; `match: "none"` = nothing close. Bench reference objects are not listed |
| `get_part(slug)` | no | Knobs (min/max/step/unit/topology), verification, provenance (origin), printing facts, download URLs, `ship` (export-gate decision) |
| `get_variant(slug, want)` | no | Plain words → clamped params, `applied`, `not_applied`, `confidence`, `bake_url` |
| `bake(slug, params?, formats?, inline_stl_path?, ack?)` | no | STL/3MF/STEP/GLB/view/py URLs (content-addressed cache); `stl_path` over stdio. Export gate: best-effort parts need `ack=true` after you tell the user the reason; failed parts are refused |
| `verify(slug, job_id, params?)` | no | Runs the deterministic verifier for a registry part against a job's measured photos (IoU, Hausdorff, residuals, tests, `verified`) |
| `get_lessons(status?, family?)` | no | Rules learned from earlier builds with evidence links (default: promoted, i.e. confirmed by a person) |
| `find_matching(slug)` | no | Mating parts, shared interface (same screw/pin/bore Ø), same family — each with a `reason` |
| `list_families()` | no | Families with part and verified counts |
| `measure_photo(image_base64 \| path, view?, thickness_mm?, mat_id?)` | no | Photo on a PartSmith mat → capture report, calibration, measurements in mm |
| `get_job(job_id)` | no | Status, verification, values, artifact URLs, pending question |
| `start_fix_job(top_base64 \| top_path, side_*, intent, thickness_mm?, family_hint?)` | **yes** | Starts the pipeline (spends model budget) |
| `report_need(query)` | **yes** | Records a request for a missing part (repeats add a vote) |

Every tool carries MCP annotations (`readOnlyHint` true except the two write tools). `--read-only`
(or `PARTSMITH_MCP_READ_ONLY=1`) leaves the write tools out. Errors name the closest valid slug or knob. Local file
paths (`path`, `top_path`, `inline_stl_path`) are accepted only over stdio; the HTTP server never reads its own disk.

Example session: `search_parts(q="cable clip 34 mm")` → `get_variant(slug, want="for an 8 mm cable, 3 channels")` →
`bake(slug, params=<params from the variant>, formats=["stl", "step"])`.

## Client configuration

Replace `/path/to/partsmith` with your checkout.

**Claude Code**
```bash
claude mcp add partsmith -- uv run --directory /path/to/partsmith python -m services.mcp --stdio
# or the running API over HTTP:
claude mcp add --transport http partsmith http://localhost:8000/mcp
```

**Muse Code** — `~/.config/muse/settings.json`
```json
{
  "schema_version": 1,
  "mcp_servers": {
    "partsmith": {
      "transport": "stdio",
      "command": "uv",
      "args": ["run", "--directory", "/path/to/partsmith", "python", "-m", "services.mcp", "--stdio"],
      "mode": "optional"
    }
  }
}
```
Over HTTP: `"partsmith": {"transport": "streamable_http", "url": "http://localhost:8000/mcp"}`.
Copy `services/mcp/skill/partsmith/` to `.agents/skills/partsmith/` (project) to give Muse Code the working rules.

**Cursor** — `.cursor/mcp.json` (project) or `~/.cursor/mcp.json`
```json
{
  "mcpServers": {
    "partsmith": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/partsmith", "python", "-m", "services.mcp", "--stdio"]
    }
  }
}
```
Over HTTP: `{"mcpServers": {"partsmith": {"url": "http://localhost:8000/mcp"}}}`.

**VS Code** — `.vscode/mcp.json`
```json
{
  "servers": {
    "partsmith": {
      "type": "stdio",
      "command": "uv",
      "args": ["run", "--directory", "/path/to/partsmith", "python", "-m", "services.mcp", "--stdio"]
    }
  }
}
```
Over HTTP: `{"servers": {"partsmith": {"type": "http", "url": "http://localhost:8000/mcp"}}}`.

## Rules the server gives agents
- Search before you build; reuse a verified part when one fits.
- Never rescale a part to force a fit — change the right knob. `get_variant` refuses uniform rescaling.
- If nothing matches, say so and call `report_need`; never substitute an unrelated part.
- Report which dimensions were measured, stated by the user, or assumed; quote `status` and `max_error_mm` exactly.
- `origin: synthetic` parts were verified against rendered images, not a photo of a real part.

## Tests
`uv run pytest services/mcp -q` calls every tool in-process; `services/api/tests/test_api.py::test_mcp_over_http`
exercises the `/mcp` mount (initialize → tools/list → tools/call).
