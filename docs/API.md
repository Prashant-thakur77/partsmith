# REST + SSE API (`/api/v1`)

Types refer to `packages/schemas/partsmith_schemas` (TypeScript copies in `apps/web/src/lib/schemas.ts`). All lengths are mm.
Anonymous read is allowed. Errors: `{"error": {"code": str, "message": str, "closest_matches"?: [str]}}` with a 4xx/5xx status.

## System
| Method | Path | Returns |
|---|---|---|
| GET | `/health` | `{"ok": true, "version": str}` |
| GET | `/status` | `{"mode": "live"\|"mock"\|"replay"\|"mixed", "providers": [ProviderStatus], "warnings": [str], "jobs": {"total": int, "verified": int}, "cost": {"usd_total": float, "usd_per_job_mean": float\|null, "n_jobs": int}}` |
| GET | `/openapi.json` | OpenAPI 3.1 |

`ProviderStatus = {"stage": str, "role": str, "provider": str, "model": str, "mode": "live"|"mock"|"replay", "key_env": str|null, "key_present": bool, "open_weights": bool, "where": str, "note": str}`
(e.g. `{"stage":"build","role":"Builder","provider":"baseten","model":"meta-models/muse-spark-open-1026","mode":"mock","key_env":"BASETEN_API_KEY","key_present":false,"open_weights":true,"where":"Baseten","note":"BASETEN_API_KEY missing → deterministic mock"}`)

## Mats and calibration
| Method | Path | Returns |
|---|---|---|
| GET | `/mats` | `[MatLayout]` |
| GET | `/mats/{mat_id}` | `MatLayout` |
| GET | `/mats/{mat_id}/pdf` | plain-paper mat PDF (A4, 100 % scale, 50 mm check ruler) |

`MatLayout = {"mat_id": str, "kind": "screen"|"paper", "title": str, "width_mm": float, "height_mm": float, "dictionary": "DICT_5X5_100",
"stage": {"x_mm","y_mm","w_mm","h_mm"}, "markers": [{"id": int, "x_mm": float, "y_mm": float, "size_mm": float, "bits": [[0|1]]}],
"min_screen_mm": {"w": float, "h": float}}` — `bits` is the full marker grid **including** the black border (7×7 for 5×5 markers),
row-major, 1 = white. A static copy of every layout is at `apps/web/public/mats/<mat_id>.json`.
Screen calibration (ID-1 card 85.60 × 53.98 mm) happens in the browser and is stored per device (`px_per_mm`, `devicePixelRatio`, screen size).

## Jobs
| Method | Path | Body / Returns |
|---|---|---|
| POST | `/jobs/fix` | multipart: `top` (file, required), `side`, `mating` (files, optional), `intent`, `mat_kind`, `thickness_mm`, `family_hint` → `JobSummary` |
| POST | `/jobs/demo` | `{"sample": str}` → `JobSummary` — runs a bundled **synthetic** sample (labelled synthetic everywhere) |
| GET | `/jobs?limit=` | `[JobSummary]` |
| GET | `/jobs/{id}` | `JobDetail = {"summary": JobSummary, "events": [Event], "partspec": PartSpec\|null, "measurements": {view: Measurements}, "verification": Verification\|null, "code": str\|null, "params": [ParamSpec], "values": {name: float}, "artifacts": {kind: url}, "question": QuestionEvent\|null}` |
| GET | `/jobs/{id}/events` | **SSE**: one `data: <Event JSON>` per event (`id:` = seq). Replays all past events first, then live ones. Ends after `done`. `?from_seq=` resumes |
| POST | `/jobs/{id}/answer` | `{"id": str, "value": str\|float, "via": "text"\|"voice"}` → `JobSummary` (resumes a paused job) |
| POST | `/jobs/{id}/edit` | `{"text": str}` or multipart `audio` → `{"transcript": str, "edits": [{"param","from","to","reason"}], "not_understood": [str], "confidence": float, "mode": str, "bake": BakeResult}` (voice/text edit; clamped to PARAMS) |
| POST | `/jobs/{id}/preview` | → `{"url": str, "label": "AI preview", "mode": str}` (Muse Image "see the fix") |
| GET | `/jobs/{id}/fit-outline?mat_id=` | `{"mat_id": str, "outline_mm": [[x,y]], "holes": [{"center_mm":[x,y],"diameter_mm":float}], "dims": [{"label": str, "from_mm":[x,y], "to_mm":[x,y], "value_mm": float}], "placement": {"cx_mm","cy_mm","theta_deg"}}` in the **mat frame** |
| POST | `/jobs/{id}/fit-check` | multipart `photo`, `mat_id` → `FitCheckResult = {"passed": bool, "iou": float, "hausdorff_mm": float, "mean_mm": float, "reasons": [str], "overlay_url": str, "capture": CaptureReport}` |
| GET | `/jobs/{id}/run.jsonl` | the raw run log |
| GET | `/replays` | `[{"id": str, "title": str, "origin": DataOrigin, "provider_mode": str, "verified": bool, "max_error_mm": float\|null, "iterations": int}]` |

## Measure / verify (stateless)
| POST | `/measure` | multipart `photo`, `view`, `mat_kind`, `thickness_mm?` → `MeasureResult` + `overlay_url` |
| POST | `/verify` | `{"part": slug, "params": {}, "measurements": Measurements}` → `Verification` |

## Registry
| Method | Path | Returns |
|---|---|---|
| GET | `/parts?q=&family=&verified=&sort=&cursor=&limit=` | `{"items": [PartCard], "next_cursor": str\|null, "total": int}` |
| GET | `/parts/{slug}` | `PartRecord` + `"artifacts": {format: url}` + `"lineage": [...]` |
| GET | `/parts/{slug}/params` | `[ParamSpec]` |
| GET | `/parts/{slug}/bake?<param>=<value>&format=stl\|3mf\|step\|glb\|view\|py` | `BakeResult` (or the file with `&download=1`) |
| GET | `/parts/{slug}/variant?want=<plain words>` | `VariantResult` |
| GET | `/parts/{slug}/matching` | `[PartCard]` |
| GET | `/parts/{slug}/template.pdf?<params>` | 1:1 paper template PDF |
| GET | `/families` | `[{"family": str, "title": str, "count": int, "verified": int}]` |
| POST | `/needs` | `{"query": str}` → `Need` |
| GET | `/needs` | `[Need]` |
| GET | `/stats` | `{"parts": int, "verified": int, "synthetic": int, "real": int, "jobs": int, "grams_pla": float}` — computed from the DB |

`PartCard = {"slug","title","family","status","origin","max_error_mm","thumbnail_url","params_count","topology_knobs": [str]}`

## Steer (factory)
| POST | `/steer` | `{"brief": str, "count": int}` → `{"id": str}` (Muse Wonder plans a family; builder lanes run) |
| GET | `/steer/{id}` | `{"id","brief","plan": [{"slug","title","family","params"}], "lanes": [{"slug","status","job_id","verified","max_error_mm"}], "queue": [...]}` |
| POST | `/steer/{id}/review` | `{"slug": str, "action": "approve"\|"send_back"\|"reject", "note": str}` |

## Bench
| GET | `/bench` | latest `eval/reports/latest/report.json` (`{"generated_at", "git_sha", "tables": {"synthetic": ..., "reference_objects": ..., "real_ruler": ...}, "runs": ..., "failures": [...]}`) |

## Agent docs
`/llms.txt`, `/prompt.txt` served by the web app (generated from the registry + this file).
