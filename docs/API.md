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
`PARTSMITH_CORS_ORIGINS` (default `http://localhost:3000,http://127.0.0.1:3000`); WebSocket routes check `Origin`
against the same list.

**Errors** always use one envelope with a 4xx/5xx status:
`{"error": {"code": str, "message": str, "closest_matches"?: [str]}}`. `closest_matches` is present when the request
named something that does not exist (slug, parameter, mat, sample, job, format, queue item). Codes in use:
`not_found`, `validation_error`, `bad_param`, `unknown_param`, `bad_format`, `part_not_found`, `job_not_found`,
`mat_not_found`, `sample_not_found`, `blob_not_found`, `bake_not_found`, `bake_failed`, `steer_not_found`,
`slug_not_in_queue`, `bad_review`, `slug_taken`, `not_finished`, `no_pending_question`, `no_program`,
`no_model_outline`, `no_preview_source`, `measure_failed`, `invalid_request`, `report_file_not_found`, `bad_image`,
`too_small`, `too_large`, `empty_upload`, `unsupported_media_type`, `not_printable`, `rate_limited`,
`agent_unavailable`, `not_implemented`, `internal_error`, `admin_required`, `needs_ack`, `not_shippable`,
`unknown_preset`, `need_not_found`, `lesson_not_found`, `batch_not_found`, `no_measurements`, `busy`, `bad_frame`,
`provider_error`, `passport_not_found`.

**Export gate** (`services/registry/gate.py` over `services.verifier.ship.can_ship`): job publish, job-part downloads
(`/jobs/{id}/bake?download=1`), published-part downloads (`/parts/{slug}/bake?download=1`), both for any format but
`view` (a preview), `/parts/{slug}/bundle.zip`, the MCP `bake` tool and the content-addressed links (`/blobs/<key>`, `/bakes/<key>/<file>`)
for printable files. Verified
ships; best effort answers `409 needs_ack` with the plain-words reason until the request repeats with `ack=1`; failed,
unfinished, malformed or self-contradicting records answer `409 not_shippable`. Responses that pass carry
`"ship": {"status": "verified"|"best_effort"|"blocked", "reason", "needs_ack", "source"}`; part detail always
carries it, so a client can show the decision before anyone clicks download. A job that lacks the state an action needs (no part program,
no model outline, nothing to preview) answers `409` with the matching code, never a 500.

**Uploads**: photos must be JPEG, PNG or WebP, ≤ 25 MB and ≤ 60 MP, ≥ 200 px on the short side, and must fully decode.
GPS metadata is removed before anything is stored: JPEG pixels are kept byte-for-byte (only the EXIF GPS directory and XMP
packets are dropped; camera fields such as focal length stay), PNG/WebP are re-saved as PNG without metadata. The EXIF
Orientation is honoured everywhere, as a browser does: a JPEG keeps its tag (and every server decode applies it), a PNG/WebP
is saved upright, and a JPEG whose EXIF block cannot be kept is re-encoded upright. Pixel coordinates in requests (`points`)
and responses are in that displayed frame. Audio:
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
| GET | `/blobs/{key}?ack=` | content-addressed blob (`key` = sha256 hex + extension); content type from the extension. Previews (images, GLB, JSON, code) are open with `Cache-Control: public, max-age=31536000, immutable` and an `ETag` (304 on `If-None-Match`). Printable files (`.stl`/`.3mf`/`.step`/`.zip`) go through the export gate of the job or part that produced them: verified ships, best effort answers `409 needs_ack` until `ack=1`, failed or unowned answers `409 not_shippable`; gated files are served `private, no-cache` (the gate runs before the 304 check). The job's fit-test coupon is open |
| GET | `/bakes/{cache_key}/{name}?ack=` | a baked file; `part.stl`, `part.step`, `part.3mf` are gated like `/blobs` (owner = the part or job that requested the bake, else the registry part whose program built it); `part.glb`, `view.json`, `part.py` are open with immutable cache headers |

## Jobs
| Method | Path | Body / Returns |
|---|---|---|
| POST | `/jobs/fix` | multipart: `top` (file, required), `side`, `mating` (files, optional), `orbit` (optional 5–10 s walk-around clip, MP4/MOV/WebM ≤ 60 MB), `narration` (optional voice note about the clip, audio ≤ 15 MB, sent with `orbit`), `city` (optional, for nearby print shops on the buy-or-print card), `intent`, `mat_kind` (`screen`\|`paper`), `thickness_mm`, `family_hint`, `screen_px_per_mm`, `points` (optional JSON, see below) → `JobSummary` |
| GET | `/jobs/demo/samples` | `[{"id": str, "title": str, "family_hint": str\|null, "kind": "template"\|"reference_object"}]` — bundled **synthetic** samples |
| POST | `/jobs/demo` | `{"sample": str}` → `JobSummary` — runs a bundled **synthetic** sample (labelled synthetic everywhere); unknown ids → `404 sample_not_found` + closest |
| GET | `/jobs?limit=&include_replays=&kind=` | `[JobSummary]` (newest first) |
| GET | `/jobs/{id}` | `JobDetail = {"passport": PassportLink, "summary": JobSummary, "events": [Event], "partspec": PartSpec\|null, "measurements": {view: Measurements}, "verification": Verification\|null, "code": str\|null, "params": [ParamSpec], "values": {name: float}, "artifacts": {kind: url}, "question": QuestionEvent\|null}` |
| GET | `/jobs/{id}/events` | **SSE**: one `data: <Event JSON>` per event (`id:` = seq). Agentic fix rounds add `thought` (`{"stage","model","text","iter","mode"}`), `tool_call` (`{"stage","name","args","result","ok","ms","iter","mode"}`) and `focus` (`{"feature","view","at_mm","label","iter"}`, a location code picked from the verifier's worst residual) events; `iter` on `thought`/`tool_call` is the agent's turn within its session, on `focus` the fix round; `mode` is `live`\|`replay`\|`mock`, and a mock run's thoughts come from the deterministic policy (`model: "mock fix agent"`, text ending "(deterministic mock)"). A job that verifies on its first build runs no agent and has none of them. Replays all past events first, then live ones. Ends after `done` — unless `?follow=1`: then the stream stays open (up to 30 min, keep-alives every 15 s) and delivers events appended after `done`, such as a fit check uploaded from a phone. `?from_seq=` (or the `Last-Event-ID` header) resumes. Events keep their original `ts` (the replay player paces on ts gaps). A `: keep-alive` comment is sent after 15 s without events; the stream starts with `retry: 3000`. Headers: `Cache-Control: no-cache, no-transform`, `X-Accel-Buffering: no` |
| POST | `/jobs/{id}/answer` | `{"id": str, "value": str\|float, "via": "text"\|"voice"}` → `JobSummary` (resumes a paused job; `409 no_pending_question` otherwise) |
| POST | `/jobs/{id}/edit` | JSON `{"text": str}` or multipart `audio` (+ optional `text`) → `{"transcript": str, "edits": [{"param","from","to","reason"}], "not_understood": [str], "confidence": float, "mode": str, "bake": BakeResult}` (voice/text edit; clamped to PARAMS) |
| POST | `/jobs/{id}/preview` | → `{"url": str, "label": "AI preview", "mode": str}` (Muse Image "see the fix") |
| GET | `/jobs/{id}/fit-outline?mat_id=` | `409 no_model_outline` when the job has no model outline (Steer lanes, failed runs); otherwise `{"mat_id": str, "outline_mm": [[x,y]], "holes": [{"center_mm":[x,y],"diameter_mm":float}], "dims": [{"label": str, "from_mm":[x,y], "to_mm":[x,y], "value_mm": float}], "placement": {"cx_mm","cy_mm","theta_deg"}}` in the **mat frame** (`mat_id` default `screen-m`) |
| POST | `/jobs/{id}/fit-check` | multipart `photo`, `mat_id` → `FitCheckResult = {"passed": bool, "iou": float, "hausdorff_mm": float\|null, "mean_mm": float\|null, "reasons": [str], "overlay_url": str, "capture": CaptureReport}`; `hausdorff_mm` / `mean_mm` are `null` when nothing could be compared (no mat markers or no part found on the outline; then `passed: false`, `iou: 0` and `reasons` says what to retake), and `fit_check_hausdorff_mm` is not emitted. **Live update:** the job also gets metric events `fit_check_passed` (1/0), `fit_check_iou`, `fit_check_hausdorff_mm` and a `measure_overlay` artifact labelled `fit check on <mat>: PASS\|FAIL`, so a page following `/events?follow=1` (the laptop showing the outline) turns green when a phone uploads |
| GET | `/jobs/{id}/bake?<param>=<value>&format=…[&preset=][&download=1]` | re-bake the job's current part program before it is published → `BakeResult` (same shape as part bakes; `&download=1` returns the first format's file through the export gate, `&ack=1` for best effort). `preset=<id>` applies a fit preset on top of the job's current values and the knobs by the same server rule as part bakes (`"preset": {"id","title","delta_mm","changes","source","label","reports","preset_delta_mm"}` in the result; unknown id → `422 unknown_preset` + closest). `fit_session=<device id>` uses that device's learned coupon clearance instead of the preset's. `passport=1` debosses the job's passport id (see "Repair passport") |
| GET | `/jobs/{id}/presets` | same shape as `/parts/{slug}/presets` with `"job_id"` instead of `"slug"`; `changes` are computed on the job's current values. `409 no_program` until the job has a part program |
| POST | `/jobs/{id}/publish` | **admin**. `{"slug"?: str, "ack"?: bool}` (or `?ack=1`) → export gate, then part detail (+ `"ship"`) (as `GET /parts/{slug}`) + `"publish": {"slug","action": "created"\|"updated"\|"unchanged"\|"renamed","requested_slug","duplicate_of","version"}`; the job must be `done`; origin is preserved; thumbnails are rendered here. Publishing dedupes (see Registry) |
| POST | `/jobs/{id}/cancel` | → `JobSummary` after the cancel took effect (`status: "cancelled"`); if the job has not stopped within 3 s the response says `status: "cancelling"` (it stops at its next check). Finished jobs are returned unchanged |
| GET | `/jobs/{id}/impact` | `{"job_id","label":"estimate","minutes_to_file": {"minutes","started_at","file_at","kind","waited_for_answer"}\|null, "filament": {"material":"PLA","grams","volume_mm3","density_g_cm3","source"}\|null, "cost": [{"currency","amount","price_per_kg"}], "print_minutes_est": float\|null, "assumptions": [str], "notes": [str], "replay": bool}`. From event timestamps and the baked mesh (facts.json `mass_g_pla`, else verified volume × PLA density); spool price assumed (`PARTSMITH_PLA_INR_PER_KG`, `PARTSMITH_PLA_USD_PER_KG`) |
| WS | `/jobs/{id}/voice/live` | Live voice edits. Client → server: binary frames of raw PCM s16le, mono, 16 kHz (about 100 ms each, ≤ 64 KB, even byte count); text `{"type":"stop"}` or `{"type":"ping"}`. Server → client (JSON, `type`): `ready{mode, model, keywords, language_bias, sample_rate, encoding, channels, max_seconds, max_bytes, mock_script?, note?}`, `speech_start`/`speech_end{turn_id, mode}`, `partial`/`final{text, turn_id, mode}`, `edit{turn_id, result: <POST /edit shape> + transcript_mode}`, `edit_error{turn_id, code, message}`, `capped{reason: "time"\|"size", limit}`, `warning{code, message}`, `error{code, message}`, `pong`, `closed{reason, seconds, bytes, finals, edits}`. Each final runs the same mapping and guards as `POST /jobs/{id}/edit`. Limits: 60 s and about 2.1 MB per session, 8 concurrent sessions (`busy`, close 1013). Errors: `job_not_found`, `no_program` (close 1008), `bad_frame` (1003), `provider_error` (1011). Without a voice key the session is the labelled mock (a scripted Hinglish utterance that fits the job's knobs) |
| POST | `/fit-reports/coupon` | `{"preset","session" (8–64 of [A-Za-z0-9_-], a random device id),"features":[{"feature","fit":"tight"\|"ok"\|"loose","amount":"barely"\|"very"\|null}] (1–8),"job_id"?,"slug"?}` → `{"id","accepted","learned": LearnedClearance}`; `422 unknown_preset` + closest; unknown slug/job → 404 |
| GET | `/fit-reports/coupon?session=` | `[LearnedClearance]` for every preset |
| GET | `/fit-reports/coupon/{preset_id}?session=` | `LearnedClearance = {"preset","title","material","process","preset_clearance_mm","clearance_mm","range_mm":[lo,hi],"source":"learned"\|"preset","reports","feature_reports","label","rule","recent":[{"feature","fit","amount","base_mm","proposal_mm","created_at"}]}` |
| GET | `/jobs/{id}/run.jsonl` | the raw run log (`application/x-ndjson`) |
| POST | `/transcribe` | multipart `audio`, `language_hint?` → `{"text": str, "mode": "live"\|"mock"\|"replay", "language": str\|null, "model": str, "note": str}` (fix intent and spoken answers; mock transcripts say so in `note`) |
| GET | `/replays` | `[{"id": str, "title": str, "origin": DataOrigin, "provider_mode": str, "verified": bool, "max_error_mm": float\|null, "iterations": int}]` |
| GET | `/jobs/{id}/buy-or-print` | `BuyOrPrint` (below): the stored card, or the print side computed now with `lookup: null` (a GET never starts a search). `409 no_program` before the job has a part program |
| POST | `/jobs/{id}/buy-or-print` | `{"city"?: str}` → `BuyOrPrint` after a lookup (search grounding; `buy_lookup` model_call on the job, cost counted there); stored as the job's card. `409 not_finished` / `409 no_program` |
| GET | `/jobs/{id}/mate-fit` | `MateFitResult` (below, the job's `mate_fit.json`): the mates measured on the "where it fits" photo and how the model fits them. `preset=` (a fit preset id) and/or `fit_session=` (device id) recompute only the "after printing on …" note with that preset and the clearance the device's coupon reports taught; the CAD and the measured mate never change. `404 no_mate_fit` without a mating photo, `422 unknown_preset` |

`points` = feature taps in photo pixels as displayed (EXIF orientation applied, i.e. the browser's frame), `{"top": [{"x": float, "y": float, "kind": "hole"|"slot"|"tab"|"broken_edge"|"exclude", "id"?: str}], "mating"?: [{"x", "y", "kind": "mate_hole"|"mate_peg"|"mate_slot"|"exclude", "id"?}]}`
(`kind` defaults to `hole` on the top photo and `mate_hole` on the mating photo, at most 32 points per photo; mating
taps need the `mating` photo, else `422 invalid_points`). Each feature tap becomes a point prompt for the segmenter and the feature is
measured by code; a tap never sets a dimension. An `exclude` tap marks something that is not the part (a finger, glare,
clutter): it is not a feature but a negative point sent with every point prompt whose crop holds it. A `broken_edge` tap
also lets the length question ask only for the missing piece (see "A broken end of unknown length"). Malformed input →
`422 invalid_points`; a clip that is not MP4/MOV/WebM → `415`.

**Negative points and mask confidence (SAM 3.1).** Every point prompt carries negative points besides its positive one:
the centres of the mat markers inside its crop (nearest first, at most 4; the crop reaches the nearest marker within
60 mm), the user's `exclude` taps, and, when the capture gate flagged glare on that photo, a pixel in the largest
blown-out blob on the part; a negative closer than 1.5 mm to the positive point is dropped (at most 8 per prompt). Requests
ask for confidence (`metadata.include_confidence: "true"`). Each mask's confidence `c` widens the ±σ of every value measured
from it, `σ_eff = σ × (1 + 2 × (1 − c))` (unchanged at c = 1, doubled at 0.5); below `c = 0.5` a pointed feature is not used
and its log line asks for a retake in plain words (agent tool `segment_points` returns `sigma_mm`, `confidence`,
`retake`). The part's outline mask does the same when it comes from SAM: its `Measurements` values are widened and the
capture report gains a `mask_confidence` check (`warn` below 0.5, never `fail`); on the top photo the job then asks
`capture.retake.mask` (`continue` | `retake`, default `continue`). Deterministic stand-ins (threshold, flood fill) have no
confidence and change nothing; mock point masks carry a labelled edge-contrast proxy (`mask_source` `mock-flood`, evidence
note "MOCK: edge-contrast proxy, not SAM"). σ is reported uncertainty only: the verifier's thresholds never read it.

**Narrated walk-around.** When the `orbit` clip has a sound track, or a short voice note comes with it (service view
`narration`: wav/webm/ogg/mp3/m4a), Muse Spark (`narrate` stage, video + audio understanding; the note is transcribed
first) returns the part's function, the mating feature, the break and, per feature it hears about, a time in the clip
and a pixel in that frame. Code decodes that frame, finds the mat in it, and keeps a point only when it is inside the
frame, on the part there (holes filled) and on the part's footprint on the mat (the walk-around's own footprint, else
the top photo's); each kept point becomes a SAM 3.1 point prompt on that frame and is measured like a tap (evidence note
`pointed by Spark (narration)`). Narrated holes merge into the top view by the tap rules only when the part sits where
the top photo saw it (footprint IoU ≥ 0.8); a part moved between photo and clip keeps them in the report only. The words go to the understand stage as steering, labelled as such; the narration
never sets a number. The job stores `narration.json` (`{"narration", "points": [{..., "ok", "reason", "frame_index"}],
"measured", "merged", "same_placement"}`) and an artifact `narration`; dropped points are logged with the reason. Mock: labelled
(`MOCK — no model watched the clip`), built from the typed intent and the clip's size/length only.

**Fits where it goes (mating photo).** The `mating` photo is taken on the same mat and passes the same capture gate in
the `capture` stage (a photo that fails is dropped with a warning and nothing is checked). In the `measure` stage each
mating tap (`mate_hole`: a socket or bore the part goes into; `mate_peg`: a shaft or pin it goes onto; `mate_slot`: a
slot or a panel edge it clips into) becomes a SAM 3.1 point prompt (negatives as above, plus `exclude` taps on that
photo) and code measures it in mm: a socket is a circle fit, or, when the mat shows through it, a lens fit that solves
the plate height from the photo; a shaft lying on its side is read from its two edges with the round section solved
exactly for the camera position; a slot or panel edge is the distance between its two long sides. Readings that cannot
know how high the edge stands carry a stated parallax allowance (an edge 0–3 mm above the mat: the value moves by half
that parallax and ±σ covers the rest); mask confidence widens σ and below 0.5 asks for a retake. Without taps Spark 1.3
points at the mate (`mate_points` model_call; pixels only, kept only on the mat's stage; mock: the code's own pick,
labelled `MOCK: …`). The stage label says what was measured ("mating: shaft Ø6.00 ± 0.01 mm"); artifacts
`mate_overlay` (png) and, after the verdict, `mate_fit` (json). In the final verdict each mate meets one model feature,
measured on the CAD solid: a shaft ↔ a declared `interfaces(p)` bore for a shaft/axle/pin/cable (else any interface,
else the model hole closest in size); a socket ↔ the narrowest outer width of the footprint; a slot opening ↔ the
plate thickness; a panel edge ↔ a declared panel gap. The diametral clearance c (receiver − what goes in) is classified
with the functional probes' classes (`does not fit` < 0 ≤ `press fit` < 0.1 ≤ `sliding fit` ≤ 0.3 < `loose fit` ≤ 0.6 <
`very loose`), also at c ± σ, plus "after printing on <preset>": internal fits print the preset's clearance small (its
documented delta, or the device's learned clearance via this route), with the preset applied they print back to c;
outer sizes print as modelled. The verdict gains P1 tests `fit.mate.<id>` (value = c, expected 0; never in the pass
rule) and one reason line "Fits where it goes …" / "Does not fit where it goes …"; `verified` is unchanged. When a fit
test says it does not fit, the export gate's reason ends with "Warning: it does not fit where it goes — …" (the
decision is unchanged). `MateFitResult = {"view": "mating", "capture": CaptureReport|null, "mates": [MateMeasurement],
"fits": [MateFit], "preset": str|null, "notes": [str], "origin"}`; `MateMeasurement = {"id", "kind", "point_px",
"point_source": "user"|"model"|"mock", "ok", "material": "opening"|"material", "shape": "round"|"strip"|"region",
"size": Measured, "length": Measured|null, "method", "center_mm", "outline_mm", "mask_source", "confidence", "retake",
"reason"}`; `MateFit = {"mate_id", "mate_kind", "model_feature", "model_feature_source":
"interface"|"nearest_hole"|"outer_size"|"plate_thickness"|"none", "model_feature_note", "model_mm", "mate_mm",
"mate_sigma_mm", "clearance_mm", "clearance_sigma_mm", "fit", "fit_low", "fit_high", "passed", "printed": PrintedFit,
"text"}`. No mating photo: nothing runs and nothing changes.

**Buy or print.** `BuyOrPrint = {"job_id", "slug", "title", "status" (copied from the verification, never changed),
"prints": [PrintEstimate], "lookup": BuyLookup|null, "mode": "live"|"mock"|"replay", "created_at", "notes": [str]}`.
`PrintEstimate = {"material": "PLA"|"PETG", "volume_mm3", "grams", "print_minutes", "filament_cost": {currency: float},
"price_per_kg": {currency: float}, "assumptions": [str]}` — code only: grams = solid volume × density (PLA 1.24,
PETG 1.27 g/cm³; 100 % infill, an upper bound), minutes = the part-facts estimate, cost = grams × an assumed spool
price (INR 1200 / USD 20 per kg PLA, INR 1400 / USD 22 PETG; assumptions, not quotes). `BuyLookup = {"query", "city",
"oem": {"name","number","url","quote"}|null, "offers": [{"seller","price","currency","url","quote","title",
"availability"}], "places": [{"name","kind": "print_shop"|"repair_cafe"|"maker_space"|"other","url","quote","city"}],
"dropped": [str], "searched", "queries", "mode", "provider", "model", "usd", "label"}`. The lookup is Muse Wonder
(fallback Spark 1.3) with web search and the job's city as the search location. Code drops every offer, place and OEM
name without an http(s) URL the search returned and a quote from that page, every price that does not appear in its
quote or has no ISO currency, and places when no city was given; each drop is listed in `dropped`. A price is never
shown without its link. Mock: no seller and no price (`label` "MOCK — no web search ran"). A fix job builds its card
after packaging (stage `package`, label "Buy or print: …"); it never blocks or changes verification.

## Measure / verify (stateless)
| Method | Path | Body / Returns |
|---|---|---|
| POST | `/measure` | multipart `photo`, `view` (`top`\|`side`), `mat_kind`, `thickness_mm?`, `mat_id?` → `MeasureResult` + `overlay_url` |
| POST | `/verify` | `{"part": slug, "params": {}, "measurements": Measurements \| {view: Measurements}}` or `{"part", "params", "job_id"}` (verify against that job's measured photos) → `Verification` + `"functional"` (probe summary: screws that pass each hole, interface fits, printability; never part of the pass rule) (the part program runs in the sandbox; code decides `verified`) |

**Observed vs inferred.** A measured value can carry `bound_mm: [low, high]` when the photo cannot pin it down: a thick
part seen only from the top reads its length/width with every edge at the stated height, and an end that sits lower
(a battery's terminal, a rounded end) reads short, so the photo allows anything up to the mat-plane reading. Without a
side view or walk-around frames the verifier then adds P0 tests `bbox.x.height` / `bbox.y.height`: the model must be
within ±0.3 mm of both the full-height reading and the reading for ends at half the height, so such a part stays best
effort until a side photo settles it (the fix loop stops early: no model edit can). `Verification.unchecked` lists
every program knob no test compared with a measured or user-stated value (`{"param", "label", "value", "unit",
"source": "inferred", "note"}`): template defaults and inferred values, labelled not verified whatever the status. A
length the user stated (below) is listed there too, with `"source": "user_stated"`: stated, not observed.

**A broken end of unknown length.** When a located break reaches an end of the footprint (the rule that makes `bbox.x`
informational) and the chosen template has a length knob, the photo cannot give the replacement's length. The job then
takes it from the user, never from a model: (1) the `/fix` intent, parsed by code (unit-aware: "it was 51 mm long",
"about 5.1 cm long", "original length: 51 mm"; mm, cm, inches; "about/around/roughly/~" → ±1 mm, an explicit "± x mm"
wins, otherwise ±0.5 mm for a ruler); else (2) with a `broken_edge` tap, one question `length.missing` that states the
length the photo measures from the intact end up to the tap and asks only for the missing piece (± the tap's 0.5 mm
added in quadrature); else (3) one question `length.original` ("How long was it before it broke? (mm, a ruler is fine) —
or measure the matching intact part, or type 'skip'"). Both questions are `expects: "text"`, default `"skip"`; answers
are a number (mm unless a unit is given) or `skip` (also empty/"don't know"), which keeps the old behaviour (length
inferred, labelled NOT verified). A value outside the template knob's range, or more than 1 mm + σ shorter than the
broken piece in the photo, is refused with a log line and the length stays inferred. An accepted value is
`Measured{source: "user_stated", sigma_mm, evidence.note: "stated by the user (...)"}` (stored as `stated.json`), sets
the length knob, and the guards refuse any fixer or agent edit of that knob. The verifier leaves the strip that length
adds beyond the broken end out of every comparison (like the completed region), adds the P0 consistency test
`bbox.x.stated` (CAD length within ±0.3 mm of the stated value: it can block a part, never pass one), adds no residual
(not in the max error) and says so in `reasons`; the rest of the part verifies on its intact region as before.

## Registry
| Method | Path | Returns |
|---|---|---|
| GET | `/parts?q=&family=&verified=&origin=&sort=&cursor=&limit=&role=` | `{"items": [PartCard], "next_cursor": str\|null, "total": int}`; `role` = `part` (default: functional parts) \| `reference` (bench reference objects, tag `role:reference`) \| `all`; `sort` = `relevance` (default) \| `newest` \| `error` (smallest max error first) \| `title`; `limit` ≤ 100; `cursor` is opaque |
| GET | `/parts/{slug}` | part detail (below) |
| GET | `/parts/{slug}/params` | `[ParamSpec]` |
| GET | `/parts/{slug}/bake?<param>=<value>&format=stl\|3mf\|step\|glb\|view\|py` | `BakeResult` + `facts_notes` (or the file with `&download=1`). `format` may repeat or be comma-separated (default `stl,step,view`; `formats=` also accepted). Out-of-range values are clamped and listed in `clamped`; unknown knobs → `422 unknown_param` + closest. Identical requests are cache hits (`cache_hit: true`). `preset=<id>` applies a fit preset after the knob values (`"preset": {"id","title","delta_mm","changes","source","label","reports","preset_delta_mm"}` in the result); `fit_session=<device id>` uses that device's learned coupon clearance. `&download=1` goes through the export gate like `bundle.zip`: verified downloads, best effort answers `409 needs_ack` until `&ack=1`, failed answers `409 not_shippable`; `format=view` and `format=glb` stay open (the embed and AR viewers' previews). `passport=1` debosses the part's passport id (see "Repair passport") |
| GET | `/parts/{slug}/presets` | `{"slug", "fit_knobs": [str], "presets": [{"id","title","material","process","nozzle_mm","delta_mm","note","changes": [{"param","from","to","delta_mm"}]}], "note"}` |
| GET | `/presets` | the 7 fit presets: `pla-fdm-0.4` (+0.20 mm), `petg-fdm-0.4` (+0.25), `abs-fdm-0.4` (+0.30), `pla-fdm-0.6` (+0.30), `petg-fdm-0.6` (+0.35), `abs-fdm-0.6` (+0.40), `resin-sla` (+0.10). A preset adds its clearance only to `affects_fit` mm knobs that are internal fits (hole, bore, pivot, pin, cable, gap, clearance, slot); outer dimensions never change. Documented starting points, not measurements |
| GET | `/parts/{slug}/bundle.zip?<params>&preset=&ack=` | zip `<slug>/`: `part.py` (defaults baked to the values), `part.step`, `part.stl`, `part.3mf`, `verification.json` (record + sha256 of every file + ship decision), `README.md` (how to print, measured vs not measured, licence), `LICENSE`, `index.html` (offline viewer, mesh inline, three.js from a CDN). Export gate applies |
| GET | `/parts/{slug}/buy-or-print` | `BuyOrPrint` for a published part: the print side from its facts plus the lookup stored on the job it came from (if any); never starts a search |
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

Part detail = `PartRecord` + `{"artifacts": {"stl","step","3mf","glb","view","py": url}, "lineage": [Lineage], "thumbnail_url", "thumbnail_2x_url", "facts_notes": {fact: how it is computed}, "fit_reports": [...], "origin": DataOrigin, "verified": bool, "ship": {"status": "verified"|"best_effort"|"blocked", "reason": str, "needs_ack": bool, "source": str}, "passport": PassportLink}`.
`ship` is the export gate's decision for the part (the same one job publish and `bundle.zip` use; plain-words `reason`).
Artifact URLs are stable (`/parts/{slug}/bake?format=<fmt>&download=1`, default params, cached after the first bake);
for a best-effort part the downloads answer `409 needs_ack` until `&ack=1` is added.
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

## Repair passport
| Method | Path | Returns |
|---|---|---|
| GET | `/passport/{id}` | `Passport` (below); the id is read case-insensitively, dashes and spaces ignored, O as 0 and I/L as 1. Unknown or malformed → `404 passport_not_found` + `closest_matches` (other passport ids) |
| GET | `/passport/{id}/qr.svg`, `/passport/{id}/qr.png` | QR code (error correction M, 4-module quiet zone) encoding `<public origin>/p/{id}` (origin from `X-Forwarded-Host`/`-Proto`, else `PARTSMITH_PUBLIC_URL`, else the request); `Cache-Control: public, max-age=3600` |
| GET | `/p/{id}` (web app) | the passport page: what the part is, its verification, **Reprint** (the passport's `bake_url` through the export gate with a fit preset, this device's learned coupon clearance as `fit_session`, optional `passport=1`) and "It broke in a new place" (`fix_url`, /fix with family and intent prefilled). A job that was never published redirects to `/jobs/{id}` |

**Ids** (`services/registry/passport.py`): 6 symbols of Crockford base32 (30 bits) from a sha256, short enough to
deboss at 4 mm cap height. A published part: `sha256("partsmith-passport/part/<identity>/<version>")` with the publish
dedupe identity (program with PARAMS defaults normalised + clamped values), so the same part has the same id and a new
version a new one; an older version's id still resolves (`superseded: true`; same program and values). A job:
`sha256("partsmith-passport/job/<job id>")`; once the job is published it resolves to its part. No personal data goes
in. Resolution order: current part versions, older versions, jobs (runs and replays on this server); a collision is
named in `notes`. `PassportLink = {"id", "url": "/p/{id}", "qr_svg_url", "qr_png_url"}` (on part detail and job
detail).

`Passport = {"id", "kind": "part"|"job", "url", "title", "family", "slug", "version", "current_version", "superseded",
"job_id", "job_status", "published", "values": {knob: float}, "preset": {"id","title","source": "job_spec"|"default",
"delta_mm"}, "status": "verified"|"best_effort"|"failed"|"unknown", "verified", "max_error_mm", "threshold_mm",
"ship": {"status","reason","needs_ack","source"}, "origin", "page_url", "bake_url", "presets_url", "qr_svg_url",
"qr_png_url", "fix_url", "notes": [str]}`. `preset` is the job's stated material + printer (`fit`), else
`pla-fdm-0.4`; `ship` is the export gate's decision, and `bake_url` is the ordinary gated bake route (best effort
answers `409 needs_ack` until `ack=1`, failed answers `409 not_shippable`).

**The passport mark** (`passport=1` on `/parts/{slug}/bake` and `/jobs/{id}/bake`, off by default; the job pipeline,
publish, bundles and benches never set it). After the sandboxed part program has returned its solid, trusted code in
the same sandbox child (`services/geom_worker/passport_mark.py`) debosses the id 0.4 mm deep (Bitstream Vera Sans from
reportlab, cap height 4 mm) on the largest planar face facing +Z that has a free rectangle of at least 25 × 8 mm
(wider for a wide id) 0.5 mm clear of its edges and holes, 3 mm clear of every declared `interfaces(p)` point, with
≥ 0.8 mm of material under it and no material within 0.3 mm above it. The bottom (mounting) face and the side walls are never used.
Raised text is not offered: it would add 0.4 mm to an outer face whose position is a measured dimension. It then
re-measures: one valid solid, watertight mesh, bounding box, every hole (Ø, centre, depth), plate thickness and
interface gaps unchanged within 0.001 mm, and removed material no more than the text. Any change undoes the mark. The
bake's JSON gains `"passport": PassportMark = {"text", "applied", "reason", "style": "deboss", "depth_mm",
"text_height_mm", "font", "face", "box_mm": {"cx","cy","w","h","angle_deg"}, "free_needed_mm", "removed_mm3",
"checks": [{"name","passed","before","after"}]}`; a download carries `X-PartSmith-Passport: applied <id>` or
`skipped <id>`. Knob values other than the passport's (`<param>=` different from the published or job values) get no
mark (`applied: false`, reason says which knobs): the id would bring back the other values. A preset still applies.
The cache key includes the id only for marked bakes, so every unmarked bake keeps its key. `format=py` is the program
without the mark.

**Repair card.** The job's `repair_card` PDF ends with a "Repair passport" block: a QR code to
`<PARTSMITH_PUBLIC_URL or http://localhost:3000>/p/{id}`, the id in text and "Broke again? Scan to reprint — your
printer's clearance comes with it." (moved to a second page when the first is full).

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

## Review (human in the loop)
| Method | Path | Body / Returns |
|---|---|---|
| GET | `/review/queue?include_replays=&limit=` | `{"items": [QueueItem]}`: waiting first, then running reviewer rounds, then decided chains |
| GET | `/review/{job_id}` | `ReviewDetail` for the chain `job_id` belongs to |
| GET | `/review/stats` | `{"n","agree","both_ok","both_not","judge_ok_person_not","judge_not_person_ok","kappa": float\|null,"reviewers","tests_excluded"}` |
| GET | `/review/feedback?family=&outcome=&by=` | The feedback log: `{"items": [FeedbackEntry], "counts": {outcome: n}, "families": [str]}` |
| POST | `/review/{job_id}/attachments` | **admin**. Multipart `image` (JPEG/PNG/WebP, GPS removed) → `{"key","url"}`; send the key in a decision's `attachments` |
| POST | `/review/{job_id}/rules/draft` | **admin**. No body → `{"rules": [{"text","source_pin","scope"}]}` (stage `review_rules`, one rule per note) |
| POST | `/review/{job_id}` | **admin**. `{"action": "accept"\|"improve"\|"reject", "pins": [{"u","v","note"}], "note", "reason", "rules": [{"text","keep","source_pin"}], "publish": bool, "why": str, "attachments": [key]}` → `{"state": ReviewDetail, "child_job": str\|null, "part_slug": str\|null}` |

```
QueueItem = {"job_id", "root_job", "round", "title", "family", "status": "waiting"|"improving"|"accepted"|"rejected",
  "verdict": {"status","max_error_mm","verified"}, "judge": Judge|null, "cost_usd", "chain_cost_usd", "is_replay", "updated_at"}
ReviewDetail = {"root_job", "status", "family", "updated_at", "images": {"rectified","overlay","focus": [u0,v0,u1,v1]|null},
  "rounds": [{"round","job_id","job_status","title","decision": "accept"|"improve"|"reject"|null,"by": "person"|"test"|null,"at","note","reason",
              "pins": [{"id","u","v","note","mat_mm","before_mm","after_mm"}],"verdict","judge","child_job","cost_usd",
              "is_replay","rules","part_slug","lesson_ids"}]}
FeedbackEntry = {"id","root_job","job_id","round","family","title","kind": "pin"|"note"|"picture"|"reject"|"accept",
  "what","why","by","at","photo","picture","where": {"pin","u","v"}|null,"before_mm","after_mm","limit_mm",
  "outcome": "fixed"|"better"|"not_fixed"|"waiting"|"not_measured"|"rejected"|"accepted","next_job",
  "used_in": {"jobs","accepted","improved","rejected"}}
Judge = {"model","mode","scores": [{"criterion": "outline"|"features"|"printability"|"fit","score": 1..5,"reason"}],
  "vetoes": [{"feature","issue","severity"}], "notes"}
```
Pins are normalised (0–1) points on the rectified top photo (`images.rectified`; `images.overlay` is the same photo with
the model drawn on it, same size). `improve` needs a pin or a note and starts a reviewer round: a new fix job
(`input.parent_job`, `input.review_round`) that reuses the photos, starts from the reviewed program and gives the fixer
the notes; its `review_round.json` holds each pin in mat and part mm with code's local mismatch before and after.
`accept` records the sign-off, promotes the ticked rules (unticked stay candidates) and with `publish` publishes the
part (best effort labelled "accepted by a person"; never `verified` unless the verifier said so). `reject` needs a
reason. Errors: 404 `job_not_found`, 409 `review_busy` / `review_decided` / `not_finished`, 422 `review_empty` /
`validation_error`. Job detail carries `judge` and `review` (`{"status","round","root_job"}`); lessons carry `track`.
Review state lives in `$PARTSMITH_HOME/reviews/` (never in committed replays). Chains recorded with the replays
(`data/replays/_reviews/`) are shown read only; a new decision on one is saved locally. API decisions are `by: "person"`;
`by: "test"` (scripts, the developer agent) cannot promote rules or publish and is left out of `stats`.

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

`evidence.bypass.caught[]` = `{id, attack, claim, claim_source, verifier: {verified, status, max_error_mm, threshold_mm, top_hausdorff_mm, top_iou, failed_tests, reasons}, export: {ok, requires_ack, status, reason, gate}, overlay (path under eval/reports, served by /bench/files), overlay_px, overlay_note}` — the lying-model moments shown on /judges.

`failures[].overlay_url` is the overlay blob when it exists, else `/api/v1/bench/files/<report dir>/<overlay_file>`, else `null`.
`{"status", "generated_at", "git_sha", "tables": {"synthetic"|"reference_objects"|"real_ruler"|"control"|"redteam": BenchTable}, "runs": [...], "failures": [{"title","reason","overlay_url"}]}`;
`BenchTable = {"n": int, "ground_truth": GroundTruthSource, "ci": ..., "columns": [str], "rows": [...], "headline": {...}, "status": "ok"|"pending", "mode": str, "note": str}`.
`GroundTruthSource` = `"synthetic_exact"|"reference_spec"|"ruler"|"caliper"|"expected_outcome"`. Tables are never merged.

- **Dimension tables** (`synthetic` → `synthetic_exact`, `reference_objects` → `reference_spec`, `real_ruler` →
  `ruler`): rows are per-sample mm errors; headline `{"median_abs_err_mm": float|null, ...}`.
- **Gate tables** (`control`, `redteam` → `ground_truth: "expected_outcome"`): the ground truth is the expected
  accept / reject / refuse outcome of each case, **not a mm value**. `columns` =
  `["case","expected","expected_checks","outcome","failed_checks","correct"]`; `expected` is `accept` (control) or
  `reject` / `refuse` (red team); `correct` is whether the outcome matched. Headline: `{"correct", "n",
  "correct_rate", "ci95"}` (95 % Wilson), plus for `control` `false_reject_rate`, `false_reject_ci95`, `pass_at_0_5`,
  and for `redteam` `reject_expected`, `refuse_expected`, `reject_correct`, `refuse_correct`. With no stored runs the
  table is `status: "pending"` with empty `rows` and `headline: {"correct_rate": null}`.

## Agent docs and MCP
- `/llms.txt` and `/prompt.txt` (also under `/api/v1/`): generated from the live registry and this route list (the web
  app proxies them). Absolute links use `X-Forwarded-Host` / `X-Forwarded-Proto` when present (validated), else
  `PARTSMITH_PUBLIC_URL`, else the request's own origin.
- MCP over streamable HTTP at **`/mcp`** on the same app (stateless, JSON responses; DNS-rebinding protection allows
  localhost, extend with `PARTSMITH_MCP_ALLOWED_HOSTS`). stdio: `uv run python -m services.mcp --stdio`. Tools and client
  configs: `services/mcp/README.md`.
