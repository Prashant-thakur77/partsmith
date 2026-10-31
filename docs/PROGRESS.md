# Progress log

Newest entries at the bottom. Each entry: what was done, evidence (command + output), what's next.
A fresh session should read this file, `docs/ARCHITECTURE.md`, `docs/API.md` and `docs/DECISIONS.md`, then continue from "Next".

## 2026-10-27 — Bootstrap (PLAN §0.2)

- `.gitignore` checked before any `git add`: `git status --ignored` lists `.env`, `PLAN.md`, `KICKOFF_PROMPT.md`,
  `docs/REUSE_LOG.md` as ignored; `git check-ignore -v PLAN.md .env` matches both.
- Tools: uv 0.10.9, Node 22, pnpm, gh (logged in), make present; installed modal 1.6.2, gitleaks 8.30.1, Muse Code 1.4.13.
- Repo is local only (no GitHub repo created, nothing pushed) by instruction.
- Contracts written: `packages/schemas/partsmith_schemas`, `docs/ARCHITECTURE.md`, `docs/API.md`, `docs/DECISIONS.md`.

## Work plan (waves)

1. Wave 1 (parallel): metrology + mats · geom worker + verifier + 10 templates · providers + Modal infra + smoke · web app shell.
2. Wave 2: synthetic generator + reference objects · agent loop + jobs + replays + CLI · API + registry + bake cache + MCP.
3. Wave 3: eval benches + reports · web ↔ API integration · screenshots/axe review · QUALITY.md · HANDOFF.md.

## 2026-10-27 — Wave 1 results

- **Spike (PLAN §0.2 step 5):** `spikes/golden_path.py` reproduced on this machine — correct code IoU 0.9995 / Hausdorff 0.125 mm,
  deliberately wrong draft IoU 0.962 / HD95 0.523 mm (synthetic photo).
- **Providers** (`c2d834e`): `uv run pytest services/agent/providers services/media tools/tests` → 69 passed; `make smoke` with zero keys →
  `0 live ✅ · 12 missing ⚠️ (mock) · 0 failed ❌`, exit 0. No live call has been made (no keys).
- **Metrology** (`0002f31`): `uv run pytest services/metrology tools/mat tools/calib` → 69 passed. Synthetic accuracy (not a bench result):
  1 mm and 8 mm plates measured within 0.06 mm with height correction; uncorrected 8 mm plate off by 1.77 mm (the test asserts the
  correction helps by > 4×). Real phone photos and live SAM 3.1 are untested.
- **Geometry** (geom worker, verifier, 10 templates): `uv run pytest services/geom_worker services/verifier services/agent/templates`
  → 114 passed (fast + slow). **Phase 2 exit gate:** `uv run python -m services.verifier.selfcheck` → 10/10 templates pass
  (self-consistency Hausdorff ≤ 0.05 mm vs 0.15 mm limit; ±1 mm length perturbation detected with the right sign, never verified).
  Synthetic measurements derived from each template's own silhouette.
- **Web app** (`apps/web`, Next.js 15 / React 19 / Tailwind 4): `pnpm typecheck`, `pnpm lint` clean; `pnpm build` OK (19 routes);
  Playwright 92 passed / 24 skipped (functional flows run in desktop-light only) with axe (0 serious/critical) on desktop+mobile ×
  light+dark. Built against route-mocked fixtures only — real-backend integration is wave 3.
- **Agent loop** (orchestrator, mock brain, guards, service facade, CLI): `uv run pytest services/agent/tests` → 32 passed (13 slow).
  Mock mode, rendered top-only samples (latch, spacer, cover) verify in 2–3 rounds and replay to identical detail. On the synthetic
  top+side JPEG samples most runs ended best-effort: side-view IoU gate unreachable for thin profiles and see-through holes lost in
  thick parts → camera-frame verification + see-through hole fitting assigned (in progress).
- **Synthetic data + measure-only bench** (`tools/synth`, `eval/{metrics,stats,measure_only}.py`): 35 tests pass. 16 committed demo
  samples (all templates + 4 reference objects, screen + paper mats, 11 MB). **Phase 1 gate (first honest run): FAIL** —
  `uv run python -m eval.measure_only --n 60 --n-reference 20 --seed 7`: synthetic mean abs error 1.503 mm (N=201; flat parts 0.267 mm,
  tall features 1.741 mm; white-part preset 7.45 mm), synthetic reference-object renders 0.346 mm (N=40, PASS). Real reference
  objects and real ruler parts: pending (no photos). Fixes in progress: see-through holes, shadows, dark screen stage for white parts,
  side views of thin parts, round profiles; camera-frame verification for tall features.
- **API + MCP + registry ops** (`services/api`, `services/mcp`, `services/registry`): 47 tests pass. Every route in docs/API.md,
  SSE with replay + `from_seq`, MCP tools over `/mcp` and stdio, Steer factory, seeding with a publish gate, CPU thumbnails.
  First seed run (mock providers, 5 samples): 1 published (best effort 0.354 mm), 4 best effort at 3–17 mm → blocked on the
  metrology/verifier fixes in progress.
- **Full-loop bench** (`eval/run.py`, `make bench`): 70 mock runs in 5 min 21 s, configs B0/B1/B2/PS/PS-noTemplate/PS-noJudge/
  PS-noHeightCorr on synthetic (n=6) + reference-object renders (n=4); real_ruler pending. Mock pipeline check only. First pass:
  PS synthetic verified 1/6, median 0.10 mm but mean 3.6 mm (glare/white-part failures); `--check-regression` wired for CI.
- **Verifier camera-frame comparison** (`3237b2f`): posed 8 mm plate verifies at Hausdorff 0.07 mm; ±1 mm / Ø+0.4 mm still caught.
- **Metrology round 2:** see-through hole fitting (thick-part holes 0/4 → 4/4 found, Ø error ≈ 0.02–0.03 mm on renders), hidden-hole
  notes, shadow suppression, dark screen stage + `contrast` gate check, thin side views, round profiles. Synthetic measure-only bench
  mean 1.503 → 0.628 mm (flat 0.172, tall features 0.984, side thickness 0.731, reference renders 0.194). Phase 1 gate (≤ 0.4 mm)
  still FAIL on synthetic overall: tall features are a single-photo ambiguity, handled in the full loop by camera-frame verification.
- **Metrology round 3:** dark-stage segmentation (shaded walls stay part, edges at local level), stricter shadow model, gate
  fragmentation after wall joining. Synthetic measure-only mean 0.667 → 0.466 mm (white parts on the dark stage 2.76 → 0.68 mm,
  14/14 accepted; white-on-light correctly rejected 5/6). Side-view thickness of parts with lower features stays ambiguous from
  one photo (reported as a range in notes, σ widened). Measure-only gate (≤ 0.4 mm): synthetic 0.466 FAIL, reference renders 0.170 PASS.
- **API fixes from the live web suite** (`a705786`): atomic job writes, 409 codes, bench gallery files, cancel status, SSE headers,
  forwarded-host links, shared Hinglish synonyms.
- **Verification regression found and fixed:** after camera-frame verification landed, 0/17 demo samples verified. Bisect
  (exported trees per commit) pinned it to comparing the model with the binary mask's ~0.3 mm blur halo instead of the
  sub-pixel edge metrology measures. Fix: compare sub-pixel edges of the photo's soft coverage field and the model's area
  coverage. IoU gate now only for views ≥ 20 mm wide (scale-free mean-distance gate below that; see DECISIONS).
  Demo samples (mock): 5/17 verified (battery cover 0.23, knob 0.41, L-bracket 0.30, AA cell 0.20, spacer 0.10 mm); remaining
  failures are mostly side-view shape errors of templates and the hard white/glare cases. `pytest -m "not live"`: 432 passed.
- **Fresh bench at 1d815f4** (mock pipeline check, `make bench`): synthetic PS median 0.15 mm, mean 0.482 mm [0.15, 0.84],
  verified 2/6; reference objects PS verified 2/4; real parts pending. Measure-only synthetic 0.466 mm, reference renders 0.170 mm.
  README tables regenerated by `tools/readme.py`.
- **Registry seeded + replays:** 12 parts published from the committed samples (6 verified, 6 best effort ≤ 2 mm), all origin
  synthetic. 16 labelled replays in `data/replays` (34 MB after JPEG re-encoding of display images); a fresh `PARTSMITH_HOME`
  serves them with every artifact URL resolving.
- **Web performance:** Lighthouse mobile perf medians 95–97 (/, /parts, part page, /fix), desktop 100, a11y/BP/SEO 100;
  first-load JS 152–176 kB; contract checks kept on every response (zod/mini).
- **Final sweep (2026-10-27):** ruff + format clean; `mypy --strict` clean (194 files); `pytest -m "not live"` (incl. slow) passes;
  web typecheck/lint/build clean; `make smoke` → 12 ⚠️ (mock), exit 0; `make dev` serves every page (200) with 12 seeded parts;
  gitleaks: no leaks; no private files tracked. Scores in `docs/QUALITY.md`; human-only steps in `docs/HANDOFF.md`.

- **Template round:** hinge_leaf knuckle_offset/knuckle_fill + knuckle counting from the outline, hook hole_shift/hole_y/
  hole_spread, pattern knobs probed first. Demo samples (mock): still 6/17 verified; hinge 3.21 → 1.32 mm, clip-tilt 1.71 → 0.78 mm.

## Next (for a fresh session)
1. Keys → `PROVIDER_RECORD=1 make live` (HANDOFF §1); update README via `make bench-live`.
2. Real photos → `data/real/...` → `uv run python -m eval.splits assign` → `make bench`.
3. Remaining offline work: thin side views of hinge-like parts read below the stated plate thickness (metrology); hook
   hole positions are unreliable when a tall arm dominates the top view (needs the side photo in the plate frame); Muse Code notes.

## 2026-10-27 — Round 2 (refinement): research → plan → build

Research: gap analysis against past winning entries, deep Meta capability study (summaries drove PLAN.md §20, private).
Plan highlights: Spark tool-calling agent operates our metrology/verifier (code still decides); Spark points → SAM 3.1 point
prompts → feature fits; phone orbit video → SAM 3.1 video tracking + per-frame ArUco poses → multi-view verification and
visual-hull height; Muse Image completes broken regions behind a code gate; Muse Wonder web search for cited OEM specs;
realtime voice; Glimmer judge on hotspot crops; single export gate + lying-brain test; functional probe tests; measured
program-vs-mesh; registry clean-up, zip/embed, presets, admin token, requests/lessons, usage counter, open-weights evidence
pack, QR phone handoff, repair-shop batches, share cards, Hinglish UI, landing replay loop; red-team/control suites, failure
taxonomy, provenance, impact log.
Schemas (`732ee27`): Source.cited + Citation, thought/tool_call/focus events, orbit view, new artifact kinds.
Seven workstreams in flight: providers, verifier, synth/eval, API/registry, metrology, web, agent loop.
- **Interruption (Oct 27 late):** earlyoom killed the VS Code process hosting the session while 7 workers ran tests/renders/
  builds in parallel on a 15 GB machine. Round-2 work is partially in the working tree (uncommitted). New rule: at most 2 workers
  at a time, `--jobs 2` / `NPROC=2`, no Playwright/Lighthouse/next build while Python benches run.
  Resume order: (1) providers + metrology, (2) verifier + agent loop, (3) API/registry + synth/eval, (4) web. Each worker checks
  its own partial edits (`git status`) and finishes its round-2 task (PLAN.md §20; brief in the lead's scratchpad ROUND2_BRIEF.md).
- **Round 2 committed (Oct 28, 2 workers at a time):** metrology points/orbit/recon gate (`11c3ed1`, `4d7ab79`: orbit height
  within ~0.3 mm on demo clips, single_part check); providers tool loop + SAM points/video + Wonder citations + Muse Image
  edits + realtime voice (`25042a8`); verifier probes + can_ship + 16/16 lying-brain + program-vs-mesh 2.77 mm vs 0.00 mm
  (`66078af`), orbit views + broken-region verification (`cc3fed8`); API/registry catalogue, export gate, bundles, presets,
  requests, lessons, batches, usage, open-weights endpoint (`fc0cf16`); agentic fixer (`ef58595`, same 6 verified as the
  pipeline, lower error on 6 more); synth orbit clips/broken parts/red-team/taxonomy/provenance (`51174b5`); refusals + upload
  fields (`061ce7c`, red-team 9/10, control 6/6).
- **Web round 2 (`dccb06e`):** QR two-device fit flow, Agent tab (thought/tool/focus), cited footnotes, orbit + tap-to-point
  capture, three-state export gate, requests/lessons/shop/factory, presets, share cards, Hinglish, landing replay loop;
  133 e2e passed (75 skipped by design), e2e:live 9/9, Lighthouse mobile 95–97 / a11y 100.
- **Backend gaps + fresh evidence (Oct 28):** fit-check nulls in the contract, `expected_outcome` ground truth, mock agent
  events labelled mock, job presets, `ship` on part detail and the bake download gated (GLB/view stay previews), one EXIF-aware
  decoder for every photo path. `single_part` now stops the job and glare on the stage no longer counts as a second object
  (red-team 10/10, control 6/6, no false `single_part` on 112 one-part photos). Reference objects named from their sample.
  Fresh mock seed with refreshed replays: 15 of 19 replays show the agent's thoughts, tool calls and focus; replays 58 MB.
  Fresh mock bench + measurement bench (synthetic 0.468 mm, reference renders 0.178 mm). README rewritten judge-first
  (proposes→decides table, generated evidence block, every Meta use with file:line, written-but-not-claimed).
- **Weak spots seen in the fresh seed (mock):** broken-part demos stay far off (cover tab 2.28 mm, latch corner 3.87 mm, hook
  tip 13.56 mm) and are not published; white parts 2.9–3.4 mm; the glare clip correctly fails capture.
- **Broken-part loop (Oct 28):** `BrokenRegion.kind = "height"` (break height from the side photo), end-to-end mirror and
  frame-snapped axis, no free-code switch for broken parts, informational length/width residuals kept out of the max error,
  clipped-contour and per-piece side-band fixes in the verifier. Fresh mock seed: cover tab 2.28 → 1.195, latch corner
  3.87 → 1.402, hook tip 13.56 → 0.681 mm (all best effort, 6 of 19 verified as before). Lying-brain suite gains a fake
  break (17/17). Bench tables gain `verified_but_off` (reference objects 1/2 verified but > 0.5 mm off).
- **Round 3 (Oct 28, research → plan → build):** research on recent winners, demo guidance, photo-to-CAD tools and the newest
  Meta capabilities set the plan: real evidence first, one memorable proof moment, new load-bearing Meta features. Built (mock
  mode, live once credits are confirmed): a thick part seen only from the top is bounded instead of verified (the AA cell
  that verified 0.56 mm short is now best effort; `verified_but_off` 0/2 synthetic, 0/1 reference objects), unchecked knobs
  labelled; buy-or-print card (cited offers only, code-computed print side); narrated walk-around (Spark video + audio points
  → SAM point prompts, checked by code); realtime Hindi/English voice relayed by the API; fit-test coupon that learns the
  printer's clearance; impact panel; "a lying model, caught" on /judges; printable files gated at every URL; deploy files
  (replay mode by default, `make deploy-check`); open-in-slicer links; video storyboard and X script in HANDOFF. Keys in
  `.env`: Meta, Baseten (smoke ✅), Hugging Face (SAM 3 gated access approved).
- **Next:** live runs once the Meta credits show → Modal deploys → real photos and a print from Prashant → reseed, bench,
  re-score.
- **First live runs (Oct 29, `95790e6`):** `make smoke` 8/8 ✅ live (Spark 1.3, Wonder, Image, Voice file + realtime, SAM 3.1,
  Spark Open `-1026` on Baseten). First live seed of the 19 demos, $6.31 in total: 4 verified (spacer 0.077, ID-1 card 0.180,
  battery cover 0.249, broken hook tip 0.491 mm), AA cell and SD card refused by the model, broken latch failed (no solid).
  Live fixes: SAM confidence inside the mask token, stale `previous_response_id` on the install card, hinted template for
  broken/tall parts. Fits-where-it-goes (mating-part check) and the repair passport landed in the same commit.
- **Live lessons, round 2 (Oct 29):** seven code checks built from recorded live runs (reference checks never refused, a
  model-proposed break kept only with evidence besides the model, hinted templates for intact parts, template mode fills
  PARAMS only, hollow free code rebuilt once, the fixer told which pass rule fails, countersink rims not taken as through-holes),
  12 single-sample live reruns for $3.13. A slow route goes to the back of its chain per stage (Baseten Spark Open went from
  8 s to 28 s median per fixer turn, up to 318 s; the fallback is Spark 1.3 on the Meta API at the same price; it fired live
  three times). A point-found hole must be a clean circle on the part (the latch corner's Ø25.9 mm fit on a 17 mm part).
- **Second live seed (Oct 29), $7.82 + $0.55 for the latch-corner rerun after the hole fix:** 6 verified (spacer 0.077, ID-1
  card 0.187, battery cover 0.387, broken hook tip 0.426, SD card 0.468, panel clip 0.496 mm); closer but best effort:
  L-bracket 3.10 → 0.431, LEGO 7.90 → 0.558, cupboard latch 1.95 → 0.764, cover tab 2.50 → 1.105, white cover 2.98 → 1.161,
  knob 0.498, AA cell 0.204 (top view only), caster 0.633. Worse: cable clip 0.91 → 1.761, hinge leaf 2.70 → 3.684 (template
  rule; the worker's rerun also gave 3.76), hook 4.04 → 4.696. Latch corner 8.57 mm: the SAM top mask closes the countersunk
  pivot hole that the threshold mask sees through. Glare clip fails capture by design. Replays: 19 of 19 stored are live.
- **First live bench (Oct 29–30, `eval/reports/2026-10-30`, $10.30 for 76 runs):** two invocations with a spend cap
  (`--max-usd`), tables rebuilt with `--from-runs --mode live`. Synthetic (n = 12): PS median 0.10 mm, mean 0.604 mm,
  $0.21 per job; B1 single shot 0.18 / 0.856 mm; PS-noTemplate 0.23 / 0.914 mm; pass@0.5 3/12 vs 1/12 vs 1/12 (CIs
  overlap). Verified but > 0.5 mm off: PS 0/2, B1 0/1, PS-noTemplate 1/2. Reference renders (n = 8): every config 6/8
  within 0.5 mm; PS verifies 4/8, B1 2/8, none of them off. Control 6/6 (no false rejects), red-team 10/10. Judge and
  capture triage still ran as labelled mocks (Glimmer not deployed). Also: through-holes a model mask closed come back
  from the colour threshold (replay of the latch corner: the outline gains the pivot hole, 8.58 → 2.48 mm there).
- **Latch corner live rerun with the threshold openings ($0.55):** the outline now has the pivot hole; 8.57 → 4.32 mm,
  the rest is at the broken corner (best effort, not published). README hero GIF and screenshot grid re-recorded from the
  stored live battery-cover run (fails its first build, verifies after two fixes); the corner label and grid header now
  come from the replay's own provider mode. /judges replay chips that share a name show their capture preset.
- **Draft demo video (Oct 30):** `make video` records a screen-only cut from the app in replay mode (2:25, captions
  burned in + `.srt` + beat list in `var/video/`, numbers read from the page while recording); beats that need real-world
  footage are skipped and listed. Fixes found while recording: control/red-team headlines on /results printed counts as
  millimetres ("6.00 mm" for 6/6); `report.json` held `NaN` (not strict JSON; now null); a report rebuilt from stored runs
  named the rebuild's commit instead of the runs' (runs now record their commit); the replay trace follows the newest
  stage while playing; the mate-fit card no longer asks the API for jobs without a mating photo (404 noise); the sticky
  nav row is nearly opaque.
- **Human review loop (Oct 30):** every finished job waits on `/review` (photo with the model drawn on it, zoom to the
  part, verdict, judge scorecard, agents and cost, round history). Accept records a person's sign-off (never `verified`),
  improve sends pins + notes into a reviewer round (a linked job that starts from the reviewed model; the fixer gets the
  notes, pin crops with numbered rings and code's local mismatch), reject keeps the reason. The judge now also scores
  outline / features / printability / fit 1–5 (advice; Spark 1.3 until Glimmer is up). On accept, Muse Spark drafts
  family rules from the notes and only the ticked ones reach future builder and fixer prompts; `/lessons` shows each
  rule's later reviews; `/review` shows judge-vs-person agreement and κ. First live reviewer round on the hinge leaf
  ($0.39): pins 3.20 → 0.05 and 2.85 → 0.25 mm, job 3.68 → 1.15 mm, still best effort. Also removed a duplicated README
  section.
- **Review loop, second pass (Oct 30):** every decision records who made it; developer-agent test reviews run the same
  flow but never promote a rule, publish, or count in agreement and rule track records, and the page labels them. Live
  hinge-leaf chain, four rounds, $1.41: 3.68 → 1.15 → 0.38 mm → verified at 0.376 mm. Round 3 measured inside the
  limits but the live judge vetoed "flat tabs, no barrels": it had only seen the model's top silhouette, and its prompt
  promised a side photo that was never attached. The judge now gets a shaded 3D view (`services/verifier/shade.py`) and
  the side photo; re-asked, it scored 5/5/5/5 with no veto, and round 4 verified. The chain is recorded with the replays
  (`data/replays/_reviews/`), round 4 left for a person to accept. Pin photo zooms to the part; a flaky review e2e came
  from a mock API that forgot decisions.
- **Easier review and the feedback log (Oct 30):** a fresh-eyes audit of every page (desktop + phone) found 15
  problems; fixed: a 5-item nav plus a "How it works" page with a glossary, an
  opaque replay banner (a class-merge bug had dropped its background), no CLI commands shown to visitors, job pages say
  which round was kept and which tries were discarded, one plain provenance chip ("Recorded run · live models"), plain
  sentences above every results table, env diagnostics only for admins, a shorter /fix, curated replay cards. The review
  page puts the photo ("Should look like") next to the 3D model ("Agent made"), shows the round story, says why a part
  fails and circles the verifier's biggest gap on the photo; Improve leads when the code has not passed a part; the
  decision bar takes a pasted screenshot and a "why it matters". New `/review/log`: every send-back and rejection with
  what, why, a close-up of the pin and what code measured next; a person's fixed feedback (with its reason) is given to
  later jobs of that family and each entry shows how those jobs' reviews went. `/mcp` answers a browser at once.
- **Admin console (Oct 31):** `/admin` with Overview (pass rate, rounds to verify, max-error median/p90, send-back
  reasons with people and tests apart, queue, parts, requests, cost by stage and model, today's spend against the cap),
  Parts (publish checks computed by code, withdraw / put back with a reason), Rules (taught rules and fed-back feedback
  with the jobs that used them, switch off / on), Audit (append-only log of every admin write) and Demand. `/review`
  queue filters (kind, status, decided by). Footer link only.
- **Quick wins (Oct 31):** search `coverage` + `match` (good / partial / none) with a hint on `/parts` and MCP
  `search_parts`; missed searches logged without client data and listed by `GET /demand`; `/parts/{slug}/verification.json`
  and `/params.json` (Data tab on the part page); downloads named `partsmith-<slug>-<changed knobs>.<ext>`; a category
  comparison on `/how`; a per-job Cost card from the job's own `model_call` events; "Sizes the photo can't see" on /fix
  (user-stated, used by the builder, checked against the program, never verified); material and load notes for hinge,
  bracket, latch, clip and hook parts.
- **Hardening (Oct 31):** daily spend cap for live model calls (`PARTSMITH_DAILY_USD_CAP`, shown on `/status` and the admin
  overview); intermittent hydration error #418 fixed site-wide; `/jobs` rows show the measured photo cropped to the part
  (`/jobs/{id}/thumbnail.jpg`) and the max gap; `/models` opens with the photo → part pipeline coloured by model; withdrawn
  parts say so on their page.
- **Next:** real photos, a dozen honest reviews on `/review`, Modal login and deploy go-ahead from Prashant; the final video with real-world shots.
