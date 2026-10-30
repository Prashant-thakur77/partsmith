# Human review loop — implementation plan

> Steps use checkbox (`- [ ]`) syntax. Built in two parallel lanes (backend Tasks 1–5, web Task 6) and landed as one
> commit.

**Goal:** a person reviews every finished fix job (accept / improve with pins / reject), improve runs a linked reviewer
round, the judge adds a 1–5 scorecard, and the reviewer's notes become family rules the builder uses next time.

**Architecture:** a reviewer round is a new fix job (`RunOptions.review`) that starts from the parent's program and
feeds the pins to the fixer; review state lives in `$PARTSMITH_HOME/reviews/`; a new `services/review/` package holds
pins maths, the store and the decisions; `/api/v1/review/*` routes; a `/review` web page.

**Tech stack:** Python 3.12 (FastAPI, pydantic, numpy, OpenCV), Next.js 15 / React 19 / TS strict / zod-mini /
react-query, node:test and Playwright.

**Spec:** `docs/design/human-review.md`

## Global constraints
- Model proposes, code decides: nothing here sets `verified`; accept is a separate human sign-off.
- mm everywhere (`_mm` suffixes); every shown number computed by code.
- Writes need `require_admin`; never write under `data/replays/` (review state goes to `$PARTSMITH_HOME/reviews/`).
- Every model call through `services/agent/providers` (stage names `judge`, `review_rules`), mock mode labelled.
- No network in tests; mypy strict, ruff, tsc, eslint clean. Run Python with `export VIRTUAL_ENV=` and `uv run`.
- No credits/reference names anywhere (repo rule 8).

## Review focus
1. Improve on a **replay** job → follow-up is a live/mock job in `var/`, the replay dir is untouched (test in Task 4).
2. Improve on a job whose follow-up is still **running** → 409 `review_busy`, no second child (Task 4).
3. A pin **off the part / outside the image** (u,v outside 0–1, or no outline within 3 mm) → 422 for out-of-range;
   in-range but far → kept, mismatch `null`, note still given to the fixer (Tasks 2, 4).
4. **Judge unavailable** (provider error) → scorecard absent (`null`), review still works, agreement counts skip it
   (Tasks 1, 4).
5. Accept with **zero ticked rules** / reject with empty reason → accept fine; reject needs a reason (422) (Task 4).

---

### Task 1: Judge scorecard (backend)

**Files:** modify `services/agent/orchestrator.py` (JUDGE_SCHEMA ~123, `run_judge` 2158, `judge` 2201),
`services/agent/mock_brain.py` (`judge` ~1116), `services/agent/providers/routing.py` (~139),
create `services/agent/prompts/judge.v2.md` (keep v1 file), `packages/schemas/partsmith_schemas/verification.py`
(add `JudgeScore`). Tests: `services/agent/tests/test_judge_scores.py`, routing test in
`services/agent/providers/tests/`.

**Produces:**
- `JudgeScore(Strict)`: `criterion: Literal["outline","features","printability","fit"]`, `score: int` (1–5),
  `reason: str` (≤ 200 chars).
- `run_judge` returns `JudgeResult` (dataclass in orchestrator): `vetoes: list[JudgeVeto]`, `scores: list[JudgeScore]`,
  `notes: str`, `model: str | None`, `mode: str`. `self.vetoes` keeps its meaning.
- Artifact `judge.json` in the job dir: `{"model", "mode", "scores": [...], "vetoes": [...], "notes"}`; written each
  time the judge runs (last one wins). A `MetricEvent` per criterion is NOT needed; the StageEvent label adds
  `"scores o4 f3 p5 u4"` style summary.
- Product-path judge chain = Glimmer chain then `SPARK_13`; open-weights chain unchanged.

- [ ] Test `test_judge_scores_parsed_and_saved`: mock mode fix job (existing fixture/sample used by
  `test_fix_e2e.py`) → `judge.json` exists, 4 scores, each 1–5, `mode == "mock"`.
- [ ] Test `test_bad_scores_dropped`: a fake provider reply with `{"criterion":"outline","score":9}` and an unknown
  criterion → both dropped, valid ones kept, no exception.
- [ ] Test `test_judge_provider_error_gives_no_scorecard`: provider raises → `judge.json` not written (or `scores: []`),
  job still finishes.
- [ ] Test (routing) `test_product_judge_falls_back_to_spark_13`: Meta key set, no Glimmer/Together env → resolved
  judge route is `muse-spark-1.3`; open mode → mock.
- [ ] Implement: schema gains `"scores": {"type":"array","items":{criterion enum, score integer 1–5, reason}}` (required
  in v2 prompt output, tolerated missing). Mock scores are rule-based from `mock_context` (outline from hausdorff
  vs 0.5 mm, features from openings match, printability from min wall/validity if in context else 4, fit 3 + note
  "mock"). Prompt v2 = v1 text + the four criteria with anchors (1 = wrong, 3 = usable with fixes, 5 = matches photo)
  and "scores are advice; software decides pass/fail".
- [ ] Run `uv run pytest services/agent -q -m "not slow and not live"`, mypy, ruff → green.

### Task 2: Pins maths and pin evidence (`services/review/pins.py`)

**Files:** create `services/review/__init__.py`, `services/review/pins.py`; test `services/review/tests/test_pins.py`.

**Produces:**
- `Pin` (pydantic `Strict`, in `packages/schemas/partsmith_schemas/review.py`, exported from the package):
  `id: int`, `u: float`, `v: float` (0–1 inclusive, validated), `note: str` (≤ 300 chars).
- `uv_to_mat_mm(u: float, v: float, rect: Mapping[str, Any], size_px: tuple[int, int]) -> tuple[float, float]` —
  `rect` is `rectified.json` (`px_per_mm`, `origin_mm`); `size_px` = (width, height) of the rectified image the job
  produced; uses the same formula as `services/metrology/calibrate.py:148-156`.
- `mat_to_part_mm(pt_mat: tuple[float, float], part_to_mat: Sequence[Sequence[float]]) -> tuple[float, float]`.
- `local_mismatch_mm(vr: ViewResult, pt_part_mm: tuple[float, float], radius_mm: float = 3.0) -> float | None` —
  inside the disc, the max over (photo-edge pixels' distance to the model edge, model-edge pixels' distance to the
  photo edge) using `cv2.distanceTransform` on edges of `vr.photo.mask` / `vr.model_mask` in `vr.photo.frame`;
  pixels in `vr.excluded_mask` ignored; `None` when neither edge passes through the disc.
- `pin_crops(vr: ViewResult, pins: Sequence[tuple[int, tuple[float, float]]], half_mm: float = 6.0) -> list[bytes]` —
  one PNG per pin, photo | model side by side like `evidence.hotspot_crops`, with a red ring (r = 2 mm) and the pin
  number drawn at the same spot on both panes.

- [ ] Tests: round-trip `uv_to_mat_mm` against `calibrate` px→mm on a synthetic rect; `mat_to_part_mm` with a
  rotation+translation matrix; `local_mismatch_mm` on two synthetic squares offset 1.0 mm → 1.0 ± 0.1 at an edge pin,
  `None` far from both edges, 0.0 ± 0.1 on identical masks; `pin_crops` returns PNGs whose red channel has the ring;
  `Pin(u=1.2, ...)` raises.
- [ ] Implement, run the tests, mypy/ruff green.

### Task 3: Reviewer round in the orchestrator

**Files:** modify `services/agent/orchestrator.py` (`RunOptions`, `_run`, `fix_context`/`propose_fix` ~1830-1853,
`agent_fix`, `learn`), `services/agent/agent_loop.py` (first user message), `services/agent/lessons.py`,
`packages/schemas/partsmith_schemas/registry.py` (`JobInput.parent_job: str | None = None`,
`JobInput.review_round: int = 0`), `services/agent/service.py` (`start_review_job`). Tests:
`services/agent/tests/test_review_round.py`.

**Consumes:** Task 2 functions, `Pin`.

**Produces:**
- `ReviewRound` dataclass in orchestrator: `parent_job: str`, `round: int`, `pins: list[Pin]`, `note: str`;
  `RunOptions.review: ReviewRound | None = None`.
- `service.start_review_job(parent_id: str, round: int, pins: list[Pin], note: str, *, sync: bool = False) -> Job` —
  reads the parent (live or replay) via the manager, reuses `photo_shas` (blobs must exist; else `ValueError`), copies
  intent/mat/family/origin/budget, sets `parent_job`/`review_round`, title `"<parent title> · review round N"`.
- In `_run` when `opts.review`: capture → measure → load parent `partspec.json`, template, stated values (no
  understand/ask/plan model calls) → `build_round` with the parent's `part.py` + `values.json`
  (iter label `"reviewed model"`) → resolve pins (Task 2) on this job's top view → at least one fix round even if
  verified → judge → final → package → learn.
- Notes reach the fixer: pipeline `hist_text` and agent-loop first message both get one line per pin
  `Reviewer pin {id} at ({x:.1f}, {y:.1f}) mm: "{note}" — local mismatch {m:.2f} mm` (or "not measurable here") plus
  the general note; `pin_crops` images are appended to the fixer's images.
- `review_round.json` in the job dir: `{"parent_job", "round", "note", "pins": [{"id","u","v","note","mat_mm",
  "part_mm","before_mm","after_mm"}]}` — before = round 1 (parent model), after = final best.
- `LogEvent` "Reviewer round N: k pins — …" at start; the extra fix stage labelled "Reviewer round".
- `lessons.promoted_lessons(registry, family) -> list[dict]` (id + rule); the job writes `lessons_used.json`
  `{"family", "lesson_ids": [...]}` whenever promoted rules go into a prompt (builder or fixer).

- [ ] Test `test_review_round_starts_from_parent_model`: mock sync parent job → `start_review_job(..., sync=True)` with
  one pin → child `input.parent_job == parent.id`; no `understand` model_call events in the child; first iteration's
  values equal the parent's `values.json`; `review_round.json` has the pin with `before_mm` and `after_mm` numbers
  or `None`; at least one fix-stage event after the first build.
- [ ] Test `test_reviewer_notes_reach_fixer`: capture `ModelRequest`s for stage `fix` (mock provider hook) → one
  contains `Reviewer pin 1` and the note text.
- [ ] Test `test_review_round_from_replay_writes_no_replay_files`: parent from `data/replays/<some job>` → child in
  `$PARTSMITH_HOME`, replay dir mtime/listing unchanged.
- [ ] Test `test_lessons_used_recorded`: a promoted lesson for the family → `lessons_used.json` lists its id.
- [ ] Implement, run `services/agent` tests + mypy/ruff green.

### Task 4: Review store, decisions, rules memory, agreement (`services/review/store.py`)

**Files:** create `services/review/store.py`, `services/review/rules.py`, prompt
`services/agent/prompts/review_rules.v1.md`, mock in `mock_brain.py`, routing `StageSpec("review_rules", "Rule
writer", "complete", (SPARK_13,), GLIMMER_CHAIN, "low")`. Tests `services/review/tests/test_store.py`,
`test_rules.py`.

**Produces (all return JSON-able dicts; shapes are the API contract in Task 5):**
- `queue(limit: int = 50, include_replays: bool = True) -> list[dict]` — latest round of each chain whose job is a
  finished fix job (`done`; not refused/cancelled; `purpose != "reference_check"`), status `waiting` when its latest
  round has no decision, `improving` while the child runs; accepted/rejected chains listed after, newest first.
- `detail(job_id: str) -> dict` — the chain for any job in it.
- `decide(job_id: str, action: Literal["accept","improve","reject"], *, pins: list[Pin] = [], note: str = "",
  reason: str = "", rules: list[RuleChoice] = [], publish: bool = False) -> dict` — improve needs ≥ 1 pin or a note
  (422 `review_empty`), calls `service.start_review_job`, 409 `review_busy` if the chain's child is not finished;
  reject needs a reason (422); accept stores the human sign-off, promotes ticked rules
  (`registry.add_lesson` + `set_lesson_status(..., "promoted", by="reviewer")`, evidence = chain job ids, pins,
  before/after), keeps unticked as candidates, and with `publish=True` on a non-replay job runs the existing publish
  path with `ack=True` (best-effort parts publish labelled best effort, accepted by a person). Improve notes and
  reject reasons are stored as candidate lessons scoped to the family.
- `RuleChoice(Strict)`: `text: str` (≤ 200), `keep: bool`, `source_pin: int | None`.
- `rules.draft(job_id: str) -> list[dict]` — one `{"text", "source_pin", "scope"}` per note in the chain, via stage
  `review_rules` (Spark 1.3; prompt: family, note, feature near the pin, before/after mm → one general rule ≤ 160
  chars or `"skip"` when the note is one-off); mock returns `"<family>: <note>"`.
- `stats() -> dict` — over chains' rounds with a decision and a judge scorecard: judge_ok = no blocking veto and
  min score ≥ 3; person_ok = accept. Returns `{"n", "agree", "both_ok", "both_not", "judge_ok_person_not",
  "judge_not_person_ok", "kappa" (None when n < 2 or undefined), "reviewers": 1}`.
- `lesson_track(lesson_id: str) -> dict` — `{"used_in": n_jobs, "accepted", "improved", "rejected"}` from reviewed
  jobs whose `lessons_used.json` lists the id.
- State file `$PARTSMITH_HOME/reviews/<root_job>.json`, atomic writes, one lock per root.

- [ ] Tests: improve → improving → child finishes → child waiting with round 2 and pins outcomes; accept promotes
  ticked rules only; reject without reason → error; improve on running child → busy; improve on replay leaves
  `data/replays` untouched; stats on a hand-built store (2×2 table → known kappa, e.g. agree 3/4 with marginals
  (2,2)/(2,2) → kappa 0.5); `lesson_track` counts; judge missing → round excluded from stats.
- [ ] Implement, tests + mypy/ruff green.

### Task 5: API routes

**Files:** create `services/api/review_routes.py` (router, mounted in `services/api/main.py` like `round2`), tests
`services/api/tests/test_review_api.py`; extend lessons list response with `track` (from `lesson_track`); extend
job detail (`service.detail_of`) with `judge` (judge.json or null) and `review` (`{"status","round","root_job"}` or
null).

**Contract:**
- `GET /api/v1/review/queue?include_replays=1` → `{"items": [QueueItem]}`; QueueItem
  `{job_id, root_job, round, title, family, status, verdict: {status, max_error_mm}, judge: Judge|null, cost_usd,
  is_replay, updated_at}`.
- `GET /api/v1/review/{job_id}` → `{root_job, status, rounds: [Round], images: {rectified, overlay}}`; Round
  `{round, job_id, decision, at, note, reason, pins: [PinOut], verdict, judge, child_job}`; PinOut
  `{id, u, v, note, mat_mm, before_mm, after_mm}` (numbers or null).
- `POST /api/v1/review/{job_id}/rules/draft` (admin) → `{"rules": [{text, source_pin, scope}]}`.
- `POST /api/v1/review/{job_id}` (admin) body `{action, pins, note, reason, rules, publish}` → `{state: Detail,
  child_job: str|null, part_slug: str|null}`.
- `GET /api/v1/review/stats` → stats dict.
- Errors through `ApiError`: 404 `job_not_found`, 409 `review_busy` / `not_finished`, 422 `review_empty` /
  `validation_error`, 401 `admin_required`.
- [ ] Tests with the existing `FakeService` pattern where possible, real store on tmp `PARTSMITH_HOME`; auth on writes;
  each error code once. Green + mypy/ruff.

### Task 6: Web `/review` page and job-page pieces

**Files:** `apps/web/src/lib/api-types.ts` (zod schemas for the contract above + `JudgeScore`), `apps/web/src/lib/
api-review.ts` (client calls, admin token via existing `request()`), create `apps/web/src/app/(site)/review/page.tsx`,
`review-client.tsx`, components `apps/web/src/components/review/pin-photo.tsx`, `judge-scorecard.tsx`,
`round-history.tsx`; nav link "Review" (with waiting count) in the site header; job workspace: scorecard card +
review badge linking to `/review?job=<id>`; lessons page: origin + track line per rule. Tests: node
`apps/web/test/review.test.mjs` (pin u,v from a click on a scaled/zoomed image; scorecard summary text; queue
sorting), Playwright `apps/web/e2e/review.spec.ts` with API fixtures (queue renders, add 2 pins with notes, press I →
POST body has 2 pins; A opens rules drafted, untick one → POST has `keep:false`; R without reason disabled).

- Pin photo: rectified image with the overlay toggle; click adds a numbered pin + note field; pins draggable or
  removable; u,v = click position / rendered image box (independent of zoom); for rounds ≥ 2 show earlier pins
  greyed with before → after mm.
- Keys: j/k move, A accept, I improve, R reject, Esc closes; ignored while typing (copy the Steer queue's handler).
- Scorecard: four rows, 1–5 bar, reason, model + mode badge ("mock" visible), vetoes listed; caption "Advice from
  the judge. Pass/fail comes from the measurements."
- Stats strip on `/review`: "Judge agreed with the reviewer in a/n reviews (κ …)" only when n ≥ 1, with
  "1 reviewer" label.
- [ ] `pnpm -C apps/web test`, `tsc`, `lint`, `pnpm -C apps/web exec playwright test e2e/review.spec.ts` green.

### Task 7: Docs, full gate, live check, one commit (lead)

- [ ] `docs/DECISIONS.md` (reviewer round = linked job; judge scorecard advisory; rules need a person's tick),
  `docs/PROGRESS.md`, `docs/HANDOFF.md` (how to review), README "Human review" section, `docs/API.md` routes.
- [ ] `make test`, mypy, ruff, web tests, full e2e, gitleaks, credit scan.
- [ ] One live check under a $1 cap: review a live demo job → improve with one pin → child verifies or not; record
  cost; accept with one rule ticked.
- [ ] `git commit` once (no attribution lines).
