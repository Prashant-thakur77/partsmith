# Human review loop — design (Oct 30 2026)

## Why
The pipeline already chains task agents (capture check → SAM 3.1 measures → Muse Spark understands → Spark Open builds
and fixes → code verifies → judge vetoes → package). What is missing is the person at the end: someone who looks at the
result, points at what is wrong, and either accepts it, sends it back with notes, or rejects it — and a memory that keeps
those notes so the next part of the same kind does not repeat the mistake.

The verifier only knows what the photo shows. A person knows things the photo cannot: the broken corner was square, this
hole is for an M3 screw, that face is the one that clips in. Review is how that knowledge gets in.

## Goals
1. **Judge scorecard.** The judge keeps its vetoes and also scores four criteria 1–5 with one sentence each: outline,
   features, printability, fit for use. Advisory only.
2. **Review queue at `/review`** (admin). Every finished fix job waits there with photo + model overlay, the code's
   verdict in mm, the judge's scorecard, what each agent did, and what it cost.
3. **Three decisions**, keyboard A / I / R:
   - **Accept** — the person's sign-off is recorded; the part may be published; lessons from the notes can be kept.
   - **Improve** — pins clicked on the photo, each with a note, plus an optional general note (typed or spoken). Starts
     a reviewer round: a new job linked to the first that starts from its model and runs fix rounds with the notes.
     It comes back to the queue as "round 2" with the history.
   - **Reject** — a short reason; kept as a negative lesson candidate and in the failure gallery.
4. **Memory of suggestions.** Every note is kept with its evidence. On accept, the reviewer ticks which notes become
   rules for that family; those are injected into future builder and fixer prompts for that family. Each rule shows
   where it came from and how later reviews of jobs that used it went.
5. **Judge-vs-person agreement**, computed by code from the reviews (n and kappa shown, labelled with the reviewer count).

## Non-goals
- Pins on the 3D model (v1 pins go on the rectified photo, which already shows the model outline overlaid).
- Multi-user accounts or roles beyond the existing admin token.
- Reopening a finished job in place (jobs stay immutable; a reviewer round is a new linked job).

## Anti-goals (would make this a failure even if it works)
- A model or a person setting `verified`. Accept is a human sign-off, shown next to the code verdict, never instead of
  it. An unverified part accepted by a person publishes as "best effort, accepted by a person".
- Notes that silently change everything: a rule is used only for its family, only after a person ticks it, and always
  carries the job it came from.
- Hand-typed numbers. Pin before/after mismatch, agreement and kappa all come from code.
- Writing into committed replays (`data/replays/`). Review state lives under `$PARTSMITH_HOME`.

## Design

### Reviewer round = a linked follow-up job
`RunOptions.review = ReviewRound(parent_job, round, pins, note)`. The follow-up job reuses the parent's photos
(`photo_shas`), runs capture + measure again (same photos → same mat frame), then **skips understand/ask/plan** by
loading the parent's `partspec.json`, template and stated values, and builds the parent's `part.py` + `values.json` as
round 1 ("start from the reviewed model"). The fixer — agent mode and pipeline mode both — then gets the reviewer notes:

- in the prompt history: `Reviewer pin 1 at (x, y) mm near hole_2: "should be further left" — local mismatch 0.84 mm`;
- as evidence images: photo | model crops around each pin with a numbered red ring drawn on both (marks on the image
  ground the model on the right spot);
- at least one fix round runs even if the parent already verified (the person says something is wrong).

Then judge → final verification → package → learn as usual. The job's input carries `parent_job` so the UI can show
the chain. Replays can be reviewed; improving one starts a live job from the replay's photos.

### Pins
The web sends pins as normalised coordinates (0–1) on the rectified top image. The server converts to mat mm with the
parent's `rectified.json` (`px_per_mm`, `origin_mm`, original size), then to part-frame mm with `part_to_mat`. Stored in
mat mm (stable across re-measure); converted into the follow-up job's part frame with its own `part_to_mat`.

**Local mismatch at a pin** (code): within a 3 mm disc around the pin in the top view, the larger of the photo-outside-
model and model-outside-photo edge distances, from the verifier's masks. Measured on the parent and on the follow-up,
so each note gets a before → after number.

### Judge scorecard
`JUDGE_SCHEMA` gains `scores: [{criterion, score 1–5, reason}]`; vetoes unchanged. Saved to `judge.json` (not to
`verification.json` — the judge's opinion is not the code's verdict) and shown on the job page and the review page.
Route: Glimmer first; in the product path Spark 1.3 on the Meta API when Glimmer is not deployed (labelled with the
model that judged). The open-weights path stays Glimmer-only. The mock judge returns rule-based scores, labelled mock.

### Review store
`$PARTSMITH_HOME/reviews/<root_job>.json`: chain of rounds `{job_id, decision, pins, note, reason, at, verdict
snapshot, judge snapshot, pin outcomes}` and a status `waiting | improving | accepted | rejected`. Queue = finished
fix jobs (done, not refused/cancelled, not reference checks) without a decision on their latest round.

### Memory
- Improve: each note becomes a lesson candidate with evidence (job, pin, feature, before/after mismatch).
- Accept: for each note in the chain, Spark 1.3 drafts a general rule for the family from the note and its evidence
  (model proposes; mock = the note itself, scoped). The reviewer edits/ticks; ticked rules are promoted (human approval
  is the existing promotion rule), unticked stay candidates.
- Reject: the reason becomes a candidate.
- Each job records which promoted rules it was given (`lessons_used.json`). The lessons page shows per rule: used in N
  jobs; later reviews accepted / improved / rejected — so a rule that does not help is visible and can be retired.

### API (all writes admin)
- `GET /review/queue` → items with status, round, verdict, judge scores, cost.
- `GET /review/{job_id}` → chain, pins, outcomes, drafted rules.
- `POST /review/{job_id}` `{action: accept|improve|reject, pins: [{u, v, note}], note, reason, rules: [{text, keep}],
  publish}` → state (improve returns the follow-up job id).
- `GET /review/stats` → agreement counts and kappa computed from the store.

### Web
- `/review` page: queue list, detail with pin photo, verdict, scorecard, agent timeline, cost, round history; keys
  j/k, A, I, R; admin lock when a token is set.
- Job page: scorecard card and review status badge with a link.
- Lessons page: origin and track record per rule.

## Constraints
Events for new stages, mypy strict / tsc / lint clean, tests with no network, mm everywhere, admin token for writes.
