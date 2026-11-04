# Changelog

Dates are Eastern Time, and each version points at the commit it describes. Everything was built during the hackathon, which
started on 2026-10-26 at 12:00 ET.

## v1.0.0 — the submission

Added since v0.8.0:

- `public_photos` suite and a real-camera marker-scale check, kept apart from real photos.
- `make proof`: every gate into `eval/reports/latest/tests.json` and `docs/PROOF.md`. `make rebake` times a knob change.
- A demo film built from code in `video/`, and an interactive deck on `/deck`.
- Live voice fixes: labels over the service's keyword limit no longer drop a session to the file endpoint, speaker tags no
  longer reach transcripts, and an empty final turn no longer overwrites what was heard.
- A README with every verified miss listed, charts, flowcharts, all limits, and a verify-it-yourself guide.
- Contribution, security and conduct files, and issue templates.

## v0.8.0 — 2026-11-02 (`1f77aad`): ready for real photos

`make real-intake` and `make real-check` for a day of photos, a small-hole supports rule, and refreshed README, docs and media.

## v0.7.0 — 2026-10-31 (`82c295a`): admin console and honest numbers

Admin console, landing drawings, describe a part, playground, search coverage and the spend cap on anonymous pages. One count
vocabulary across pages, job pages that name the real failure, judge vetoes shown, fix-loop guardrails, grouped attempts and a
visible fit check.

## v0.6.0 — 2026-10-30 (`961366f`): human review

The review loop with reviewer rounds, pins on the photo, a judge scorecard, family rules that need a person's tick, a feedback
log, pasted screenshots and labelled test reviews.

## v0.5.0 — 2026-10-29 (`2b9be58`): first live runs

The first live runs and live bench on Meta's models, slow-route fallback, a daily spend cap, fits-where-it-goes, the repair
passport and a draft film target.

## v0.4.0 — 2026-10-28 (`b73fd05`): measuring what one photo cannot

Bounded top views, buy-or-print, narrated walk-around, live voice edits, coupon learning, the lying model on `/judges`, deploy
files, stated lengths, SAM negatives and confidence, value sources in 3D and the fail-to-fix strip.

## v0.3.0 — 2026-10-27 (`4fe55c1`): an agent that drives the instrument

SAM point and video prompts, cited specs, Muse Image completion with a code gate, the agentic fixer over our own tools, one
export gate with a lying-model suite, program-vs-mesh, control and red-team suites, a failure taxonomy and refusal of flexible
and organic objects.

## v0.2.0 — 2026-10-27 (`a670417`): verification that holds

Camera-frame comparison, like-for-like part tests, sub-pixel edges, see-through holes, dark-stage capture, a full-loop bench with
baselines and ablations, real-part split freezing, replays for the judge path and a quality scorecard.

## v0.1.0 — 2026-10-27 (`948360f`): the core loop

Typed contracts, the provider layer, screen and paper mats, card scale, capture gate and parallax-corrected measurement, a
sandboxed CadQuery worker, the deterministic verifier and family templates, the web app, the bounded fix loop with a mock brain,
a synthetic photo generator with exact ground truth, REST with SSE, MCP and the registry. All of it runs with no keys.
