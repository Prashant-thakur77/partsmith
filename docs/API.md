# REST + SSE API (`/api/v1`)

Server: `services/api/main.py` (`uv run uvicorn services.api.main:app --port 8000`). Interactive docs at `/api/v1/docs`,
OpenAPI 3.1 at `/api/v1/openapi.json`.

Types refer to `packages/schemas/partsmith_schemas` (TypeScript copies in `apps/web/src/lib/schemas.ts`). All lengths are mm.
Anonymous read is allowed. **Admin token:** with `PARTSMITH_ADMIN_TOKEN` set, publishing (`POST /jobs/{id}/publish`),
Steer (`POST /steer`, `POST /steer/{id}/review`), lesson promotion/rejection, request status changes and every
`/batches` route need `Authorization: Bearer <token>` (`401 admin_required` otherwise). Without the variable the server
is in development mode: those routes are open and `/status` reports `"admin": "open (dev)"` (`"token"` when set).
**Usage counter:** every API/MCP call is counted by route template and a salted, truncated sha256 of (IP, user agent);
raw IPs and user agents are never stored (`/stats`).
Writes (POST/PUT/PATCH/DELETE under `/api/v1`) are rate limited per IP
(`PARTSMITH_RATE_LIMIT` per minute, default 120 → `429 rate_limited` with `Retry-After`). CORS allows
`PARTSMITH_CORS_ORIGINS` (default `http://localhost:3000,http://127.0.0.1:3000`).

**Errors** always use one envelope with a 4xx/5xx status:
`{"error": {"code": str, "message": str, "closest_matches"?: [str]}}`. `closest_matches` is present when the request
named something that does not exist (slug, parameter, mat, sample, job, format, queue item). Codes in use:
`not_found`, `validation_error`, `bad_param`, `unknown_param`, `bad_format`, `part_not_found`, `job_not_found`,
`mat_not_found`, `sample_not_found`, `blob_not_found`, `bake_not_found`, `bake_failed`, `steer_not_found`,
`slug_not_in_queue`, `bad_review`, `slug_taken`, `not_finished`, `no_pending_question`, `no_program`,
`no_model_outline`, `no_preview_source`, `measure_failed`, `invalid_request`, `report_file_not_found`, `bad_image`,
`too_small`, `too_large`, `empty_upload`, `unsupported_media_type`, `not_printable`, `rate_limited`,
`agent_unavailable`, `not_implemented`, `internal_error`, `admin_required`, `needs_ack`, `not_shippable`,
`unknown_preset`, `need_not_found`, `lesson_not_found`, `batch_not_found`, `no_measurements`.

**Export gate** (`services/registry/gate.py` over `services.verifier.ship.can_ship`): job publish, job-part downloads
(`/jobs/{id}/bake?download=1`, any format but `view`), `/parts/{slug}/bundle.zip` and the MCP `bake` tool. Verified
ships; best effort answers `409 needs_ack` with the plain-words reason until the request repeats with `ack=1`; failed,
unfinished, malformed or self-contradicting records answer `409 not_shippable`. Responses that pass carry
`"ship": {"status": "verified"|"best_effort"|"blocked", "reason", "needs_ack", "source"}`. A job that lacks the state an action needs (no part program,
no model outline, nothing to preview) answers `409` with the matching code, never a 500.

**Uploads**: photos must be JPEG, PNG or WebP, ≤ 25 MB and ≤ 60 MP, ≥ 200 px on the short side, and must fully decode.
GPS metadata is removed before anything is stored: JPEG pixels are kept byte-for-byte (only the EXIF GPS directory and XMP
packets are dropped; camera fields such as focal length stay), PNG/WebP are re-saved as PNG without metadata. Audio:
wav/webm/ogg/mp3/m4a/aac/flac, ≤ 15 MB.

## System
| Method | Path | Returns |
|---|---|---|
| GET | `/health` | `{"ok": true, "version": str}` |
| GET | `/status` | `Status` (below) |
| GET | `/status/open-weights` | `{"status": "ok"\|"partial"\|"pending", "summary": providers.open_weights_summary() \| null, "report": eval/reports/latest/open_weights.json \| null, "stages": [ProviderStatus with open_weights], "notes": [str]}` |
| GET | `/openapi.json` | OpenAPI 3.1 |

```
Status = {"mode": "live"|"mock"|"replay"|"mixed", "admin": "token"|"open (dev)", "providers": [ProviderStatus], "warnings": [str],
          "jobs": {"total": int, "verified": int},
          "cost": {"usd_total": float, "usd_per_job_mean": float|null, "n_jobs": int},
          "model_calls": [{"stage","provider","model","mode","calls","failed","tokens_in","tokens_out","usd","ms_mean","open_weights"}],
          "open_weights": {"open_weights_only": bool, "stages_live_on_open_weights": [str], "calls_on_open_weights": int,
                           "last_live_call_ts": {provider: float}}}
```
Job and cost aggregates are computed from the `model_call` events of every (non-replay) job on the server.
`ProviderStatus = {"stage": str, "role": str, "provider": str, "model": str, "mode": "live"|"mock"|"replay", "key_env": str|null, "key_present": bool, "open_weights": bool, "where": str, "note": str}`
(e.g. `{"stage":"build","role":"Builder","provider":"baseten","model":"meta-models/muse-spark-open-1026","mode":"mock","key_env":"BASETEN_API_KEY","key_present":false,"open_weights":true,"where":"Baseten","note":"BASETEN_API_KEY missing → deterministic mock"}`)

## Mats and calibration
| Method | Path | Returns |
|---|---|---|
| GET | `/mats` | `[MatLayout]` |
| GET | `/mats/{mat_id}` | `MatLayout` |
| GET | `/mats/{mat_id}/pdf` | plain-paper mat PDF (A4, 100 % scale, 50 mm check ruler); `422 not_printable` for mats that do not fit A4 |

`MatLayout = {"mat_id": str, "kind": "screen"|"paper", "title": str, "width_mm": float, "height_mm": float, "dictionary": "DICT_5X5_100",
"stage": {"x_mm","y_mm","w_mm","h_mm"}, "markers": [{"id": int, "x_mm": float, "y_mm": float, "size_mm": float, "bits": [[0|1]]}],
"min_screen_mm": {"w": float, "h": float}}` — `bits` is the full marker grid **including** the black border (7×7 for 5×5 markers),
row-major, 1 = white. A static copy of every layout is at `apps/web/public/mats/<mat_id>.json`.
Screen calibration (ID-1 card 85.60 × 53.98 mm) happens in the browser and is stored per device (`px_per_mm`, `devicePixelRatio`, screen size).

## Files
| Method | Path | Returns |
|---|---|---|
| GET | `/blobs/{key}` | content-addressed blob (`key` = sha256 hex + extension); content type from the extension, `Cache-Control: public, max-age=31536000, immutable`, `ETag` (304 on `If-None-Match`) |
| GET | `/bakes/{cache_key}/{name}` | a baked file (`part.stl`, `part.step`, `part.3mf`, `part.glb`, `view.json`, `part.py`), immutable cache headers |

## Jobs
| Method | Path | Body / Returns |
|---|---|---|
| POST | `/jobs/fix` | multipart: `top` (file, required), `side`, `mating` (files, optional), `orbit` (optional 5–10 s walk-around clip, MP4/MOV/WebM ≤ 60 MB), `intent`, `mat_kind` (`screen`\|`paper`), `thickness_mm`, `family_hint`, `screen_px_per_mm`, `points` (optional JSON, see below) → `JobSummary` |
| GET | `/jobs/demo/samples` | `[{"id": str, "title": str, "family_hint": str\|null, "kind": "template"\|"reference_object"}]` — bundled **synthetic** samples |
| POST | `/jobs/demo` | `{"sample": str}` → `JobSummary` — runs a bundled **synthetic** sample (labelled synthetic everywhere); unknown ids → `404 sample_not_found` + closest |
| GET | `/jobs?limit=&include_replays=&kind=` | `[JobSummary]` (newest first) |
| GET | `/jobs/{id}` | `JobDetail = {"summary": JobSummary, "events": [Event], "partspec": PartSpec\|null, "measurements": {view: Measurements}, "verification": Verification\|null, "code": str\|null, "params": [ParamSpec], "values": {name: float}, "artifacts": {kind: url}, "question": QuestionEvent\|null}` |
| GET | `/jobs/{id}/events` | **SSE**: one `data: <Event JSON>` per event (`id:` = seq). Replays all past events first, then live ones. Ends after `done` — unless `?follow=1`: then the stream stays open (up to 30 min, keep-alives every 15 s) and delivers events appended after `done`, such as a fit check uploaded from a phone. `?from_seq=` (or the `Last-Event-ID` header) resumes. Events keep their original `ts` (the replay player paces on ts gaps). A `: keep-alive` comment is sent after 15 s without events; the stream starts with `retry: 3000`. Headers: `Cache-Control: no-cache, no-transform`, `X-Accel-Buffering: no` |
| POST | `/jobs/{id}/answer` | `{"id": str, "value": str\|float, "via": "text"\|"voice"}` → `JobSummary` (resumes a paused job; `409 no_pending_question` otherwise) |
| POST | `/jobs/{id}/edit` | JSON `{"text": str}` or multipart `audio` (+ optional `text`) → `{"transcript": str, "edits": [{"param","from","to","reason"}], "not_understood": [str], "confidence": float, "mode": str, "bake": BakeResult}` (voice/text edit; clamped to PARAMS) |
| POST | `/jobs/{id}/preview` | → `{"url": str, "label": "AI preview", "mode": str}` (Muse Image "see the fix") |
| GET | `/jobs/{id}/fit-outline?mat_id=` | `409 no_model_outline` when the job has no model outline (Steer lanes, failed runs); otherwise `{"mat_id": str, "outline_mm": [[x,y]], "holes": [{"center_mm":[x,y],"diameter_mm":float}], "dims": [{"label": str, "from_mm":[x,y], "to_mm":[x,y], "value_mm": float}], "placement": {"cx_mm","cy_mm","theta_deg"}}` in the **mat frame** (`mat_id` default `screen-m`) |
| POST | `/jobs/{id}/fit-check` | multipart `photo`, `mat_id` → `FitCheckResult = {"passed": bool, "iou": float, "hausdorff_mm": float, "mean_mm": float, "reasons": [str], "overlay_url": str, "capture": CaptureReport}`. **Live update:** the job also gets metric events `fit_check_passed` (1/0), `fit_check_iou`, `fit_check_hausdorff_mm` and a `measure_overlay` artifact labelled `fit check on <mat>: PASS\|FAIL`, so a page following `/events?follow=1` (the laptop showing the outline) turns green when a phone uploads |
| GET | `/jobs/{id}/bake?<param>=<value>&format=…[&download=1]` | re-bake the job's current part program before it is published → `BakeResult` (same shape as part bakes; `&download=1` returns the first format's file through the export gate, `&ack=1` for best effort) |
| POST | `/jobs/{id}/publish` | **admin**. `{"slug"?: str, "ack"?: bool}` (or `?ack=1`) → export gate, then part detail (+ `"ship"`) (as `GET /parts/{slug}`) + `"publish": {"slug","action": "created"\|"updated"\|"unchanged"\|"renamed","requested_slug","duplicate_of","version"}`; the job must be `done`; origin is preserved; thumbnails are rendered here. Publishing dedupes (see Registry) |
| POST | `/jobs/{id}/cancel` | → `JobSummary` after the cancel took effect (`status: "cancelled"`); if the job has not stopped within 3 s the response says `status: "cancelling"` (it stops at its next check). Finished jobs are returned unchanged |
| GET | `/jobs/{id}/run.jsonl` | the raw run log (`application/x-ndjson`) |
| POST | `/transcribe` | multipart `audio`, `language_hint?` → `{"text": str, "mode": "live"\|"mock"\|"replay", "language": str\|null, "model": str, "note": str}` (fix intent and spoken answers; mock transcripts say so in `note`) |
| GET | `/replays` | `[{"id": str, "title": str, "origin": DataOrigin, "provider_mode": str, "verified": bool, "max_error_mm": float\|null, "iterations": int}]` |

`points` = feature taps in top-photo pixels, `{"top": [{"x": float, "y": float, "kind": "hole"|"slot"|"tab"|"broken_edge", "id"?: str}]}`
(`kind` defaults to `hole`, at most 32 points). Each tap becomes a point prompt for the segmenter and the feature is measured by
code; a tap never sets a dimension. Malformed input → `422 invalid_points`; a clip that is not MP4/MOV/WebM → `415`.

## Measure / verify (stateless)
| Method | Path | Body / Returns |
|---|---|---|
| POST | `/measure` | multipart `photo`, `view` (`top`\|`side`), `mat_kind`, `thickness_mm?`, `mat_id?` → `MeasureResult` + `overlay_url` |
| POST | `/verify` | `{"part": slug, "params": {}, "measurements": Measurements \| {view: Measurements}}` or `{"part", "params", "job_id"}` (verify against that job's measured photos) → `Verification` + `"functional"` (probe summary: screws that pass each hole, interface fits, printability; never part of the pass rule) (the part program runs in the sandbox; code decides `verified`) |

## Registry
| Method | Path | Returns |
|---|---|---|
| GET | `/parts?q=&family=&verified=&origin=&sort=&cursor=&limit=&role=` | `{"items": [PartCard], "next_cursor": str\|null, "total": int}`; `role` = `part` (default: functional parts) \| `reference` (bench reference objects, tag `role:reference`) \| `all`; `sort` = `relevance` (default) \| `newest` \| `error` (smallest max error first) \| `title`; `limit` ≤ 100; `cursor` is opaque |
| GET | `/parts/{slug}` | part detail (below) |
| GET | `/parts/{slug}/params` | `[ParamSpec]` |
| GET | `/parts/{slug}/bake?<param>=<value>&format=stl\|3mf\|step\|glb\|view\|py` | `BakeResult` + `facts_notes` (or the file with `&download=1`). `format` may repeat or be comma-separated (default `stl,step,view`; `formats=` also accepted). Out-of-range values are clamped and listed in `clamped`; unknown knobs → `422 unknown_param` + closest. Identical requests are cache hits (`cache_hit: true`). `preset=<id>` applies a fit preset after the knob values (`"preset": {"id","title","delta_mm","changes"}` in the result) |
| GET | `/parts/{slug}/presets` | `{"slug", "fit_knobs": [str], "presets": [{"id","title","material","process","nozzle_mm","delta_mm","note","changes": [{"param","from","to","delta_mm"}]}], "note"}` |
| GET | `/presets` | the 7 fit presets: `pla-fdm-0.4` (+0.20 mm), `petg-fdm-0.4` (+0.25), `abs-fdm-0.4` (+0.30), `pla-fdm-0.6` (+0.30), `petg-fdm-0.6` (+0.35), `abs-fdm-0.6` (+0.40), `resin-sla` (+0.10). A preset adds its clearance only to `affects_fit` mm knobs that are internal fits (hole, bore, pivot, pin, cable, gap, clearance, slot); outer dimensions never change. Documented starting points, not measurements |
| GET | `/parts/{slug}/bundle.zip?<params>&preset=&ack=` | zip `<slug>/`: `part.py` (defaults baked to the values), `part.step`, `part.stl`, `part.3mf`, `verification.json` (record + sha256 of every file + ship decision), `README.md` (how to print, measured vs not measured, licence), `LICENSE`, `index.html` (offline viewer, mesh inline, three.js from a CDN). Export gate applies |
| GET | `/parts/{slug}/card.png` | 1200×630 share card (og:image): thumbnail, title, "Verified · 0.31 mm" / "Best effort · …" / "Not verified", origin badge, size and grams |
| GET | `/embed/{slug}?<params>` (root, not under `/api/v1`) | minimal HTML viewer for iframes (`Content-Security-Policy: frame-ancestors *`) |
| GET | `/parts/{slug}/variant?want=<plain words>` | `VariantResult` + `bake_url` |
| GET | `/parts/{slug}/matching` | `[PartCard + {"reason": str}]` — declared mating parts, then shared interface dimensions (same screw hole/pin/bore/cable Ø within 0.05 mm), then same family |
| GET | `/parts/{slug}/template.pdf?<params>` | 1:1 paper template PDF (top silhouette, through-holes, overall dimensions, 50 mm check ruler) |
| GET | `/parts/{slug}/thumbnail.png?scale=1\|2` | isometric thumbnail (640×480 or 1280×960, transparent PNG); rendered on first request when the part has none yet |
| POST | `/parts/{slug}/feedback` | `{"result": "fits"\|"tight"\|"loose"\|"pass"\|"fail", "kind": "print"\|"screen_fit", "note": str}` → `{"id","slug","result","kind"}` ("Did it fit?" — lessons evidence) |
| GET | `/families` | `[{"family": str, "title": str, "count": int, "verified": int}]` (template families with no parts yet are listed with count 0) |
| POST | `/needs` | JSON `{"query": str}` or multipart `query` + optional `photo` → `Request = Need + {"photo_url": str\|null, "counted": bool}`. Asking for an existing request (same words, any case) votes for it, once per client |
| GET | `/needs?limit=&status=` | `[Request]` (most votes first; `status` = `open`\|`in_progress`\|`fulfilled`) |
| POST | `/needs/{id}/vote` | → `Request` with `counted` (one vote per client fingerprint) |
| PATCH | `/needs/{id}` | **admin**. `{"status": "open"\|"in_progress"\|"fulfilled"}` → `Request` |
| GET | `/lessons?status=&scope=` | `[{"id","scope","rule","evidence","status": "candidate"\|"promoted"\|"rejected","promoted_by","created_at","links": [{"kind": "job"\|"part"\|"fit_report","id","url","page"}]}]` |
| POST | `/lessons/{id}/promote`, `/lessons/{id}/reject` | **admin**. `{"by"?: str}` → the lesson. Only promoted lessons reach future builds |
| GET | `/stats` | `{"parts": int, "verified": int, "synthetic": int, "real": int, "reference_object": int, "reference": int, "jobs": int, "grams_pla": float, "calls_total": int, "mcp_calls": int, "distinct_clients": int, "last_7d": {"calls","mcp_calls","distinct_clients"}, "usage": {… + "top_routes": [{"route","calls"}]}}` — computed from the DB |

`PartCard = {"slug","title","family","status","origin","verified","max_error_mm","thumbnail_url","thumbnail_2x_url","params_count","topology_knobs": [str],"summary","bbox_mm": [x,y,z]|null}`

Part detail = `PartRecord` + `{"artifacts": {"stl","step","3mf","glb","view","py": url}, "lineage": [Lineage], "thumbnail_url", "thumbnail_2x_url", "facts_notes": {fact: how it is computed}, "fit_reports": [...], "origin": DataOrigin, "verified": bool}`.
Artifact URLs are stable (`/parts/{slug}/bake?format=<fmt>&download=1`, default params, cached after the first bake).
**Publishing dedupes** (`services/registry/publish.py::publish_part`, used by Steer approvals, job publishes and the
seed): a part's identity is its program with PARAMS defaults normalised + its clamped values. An identical part returns
the existing record (`unchanged`), or updates it with `version + 1` when its verification/facts/title changed
(`updated`). A different part whose slug is taken gets a suffix from the knobs that differ, e.g.
`cable-clip-50mm-3ch` (`renamed`), and `forked_from` = the taken slug when it is the same program.

`Lineage = {"slug": str, "version": int, "relation": "forked_from"|"variant_of", "title": str}` — `forked_from`: this part
was forked from `slug`; `variant_of`: `slug` is a variant forked from this part.

`VariantResult = {"params": {name: float}, "applied": [str], "not_applied": [str], "confidence": float, "mode": "live"|"mock"|"replay"}`.
The `variant` stage (Muse Spark) proposes edits; code decides: unknown knob names map to the closest real knob when the
match is clear (else they go to `not_applied`), every value is clamped and snapped to its range/step, and uniform
rescaling (a `scale` knob, or three or more mm dimensions changed by one common factor) is refused. The deterministic
mock understands "M4 hole" (ISO 273 medium clearance), "2 mm taller", "for a 25 mm rail", "for an 8 mm cable", "3 ribs",
"no gussets", "40 mm diameter", "6 mm shaft". Confidence is capped at 0.75 when something was not applied.

## Steer (factory)
| Method | Path | Body / Returns |
|---|---|---|
| POST | `/steer` | **admin**. `{"brief": str, "count": int (1..24)}` → `{"id": str}` (Muse Wonder plans a kit; builder lanes run in the background) |
| GET | `/steer?limit=` | `[{"id","brief","count","status","created_at","family_title","pending","published"}]` |
| GET | `/steer/{id}` | `SteerState` (below) |
| POST | `/steer/{id}/review` | **admin**. `{"slug": str, "action": "approve"\|"send_back"\|"reject", "note": str}` → the updated `SteerState` |

```
SteerState = {"id", "brief", "count", "status": "planning"|"building"|"reviewing"|"done"|"failed", "created_at", "updated_at",
  "family_title": str, "planner": {"provider","model","mode"}|null, "plan_job_id": str|null, "plan_notes": [str], "label": str,
  "plan": [{"slug","title","family","template","params","why"}],
  "lanes": [{"slug","status": "queued"|"running"|"done"|"failed","job_id","verified","max_error_mm","error"?}],
  "queue": [{"slug","title","family","status": "building"|"pending_review"|"published"|"sent_back"|"rejected"|"failed",
             "job_id","verified","max_error_mm","params","note","published_slug"?,"publish_action"?}],
  "history": [{"slug","action","note","ts","applied"?,"not_applied"?}]}
```
Plans are checked by code (real templates only, params clamped, unique slugs). Each lane is a `kind="steer"` job that
executes the template at the planned parameters and verifies it against its **own rendered silhouette** — a labelled
SYNTHETIC self-check, not a photo. `approve` publishes to the registry (origin `synthetic`); `send_back` applies the note as a
plain-words change through the variant guard and rebuilds the lane; `reject` drops it.

## Repair-shop batches (all admin)
| Method | Path | Body / Returns |
|---|---|---|
| POST | `/batches` | `{"name": str, "customers": [{"name", "contact"?, "jobs": [job id]}]}` → `Batch` |
| GET | `/batches` | `[{"id","name","created_at","customers","jobs"}]` |
| GET | `/batches/{id}` | `Batch = {"id","name","created_at","customers": [...], "rows": [{"customer","contact","job_id","title","status","verified","max_error_mm","origin","part_slug","grams_pla","price_inr","orientation","supports","print_minutes","material","layer_mm","walls","infill_percent"}], "price": {"inr_per_g_pla","inr_base_per_part"}}` |
| POST | `/batches/{id}/jobs` | `{"customer": str, "job_id": str, "contact"?: str}` → `Batch` |
| GET | `/batches/{id}/sheet.pdf` | A4 job sheet, one section per customer: part, code-decided status and max error, print settings, grams, price |

Price estimate = PLA grams × `PARTSMITH_PRICE_PER_G_INR` (default 3) + `PARTSMITH_PRICE_BASE_INR` per part (default 0);
the sheet prints the rate used.

## Registry clean-up
Seeded parts are named from their own knobs ("Cupboard door latch, 52 mm" → `cupboard-door-latch-52mm`), never from the
sample folder; `seed()` renames older `demo-…` slugs. Reference objects (ID-1 card, SD card, LEGO brick, AA cell) are
bench-only: tag `role:reference`, hidden from `/parts`, `/families`, matching, MCP search and llms.txt, still reachable
by slug and with `role=reference`.

## Bench
| Method | Path | Returns |
|---|---|---|
| GET | `/bench` | latest `eval/reports/latest/report.json` with `"status": "ok"`, or a `"status": "pending"` payload of the same shape. Both carry `"evidence": {"bypass", "program_vs_mesh", "impact", "open_weights"}` — the side reports in `eval/reports/latest/` (null until their script runs) |
| GET | `/bench/files/{path}` | a report file under `eval/reports/` (png/jpg/svg/json/md/csv/txt; no traversal, no hidden files) |

`failures[].overlay_url` is the overlay blob when it exists, else `/api/v1/bench/files/<report dir>/<overlay_file>`, else `null`.
`{"status", "generated_at", "git_sha", "tables": {"synthetic"|"reference_objects"|"real_ruler": BenchTable}, "runs": [...], "failures": [{"title","reason","overlay_url"}]}`;
`BenchTable = {"n": int, "ground_truth": "synthetic_exact"|"reference_spec"|"ruler", "ci": ..., "columns": [str], "rows": [...], "headline": {"median_abs_err_mm": float|null, ...}, "status": "ok"|"pending", "note": str}`.

## Agent docs and MCP
- `/llms.txt` and `/prompt.txt` (also under `/api/v1/`): generated from the live registry and this route list (the web
  app proxies them). Absolute links use `X-Forwarded-Host` / `X-Forwarded-Proto` when present (validated), else
  `PARTSMITH_PUBLIC_URL`, else the request's own origin.
- MCP over streamable HTTP at **`/mcp`** on the same app (stateless, JSON responses; DNS-rebinding protection allows
  localhost, extend with `PARTSMITH_MCP_ALLOWED_HOSTS`). stdio: `uv run python -m services.mcp --stdio`. Tools and client
  configs: `services/mcp/README.md`.
