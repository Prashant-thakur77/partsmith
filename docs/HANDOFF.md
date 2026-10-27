# Handoff: what only Prashant can do

Everything else is built and runs with zero keys (deterministic mocks, labelled). This is the short list of things that need a
human: keys, photos, the video and the submission. Do them roughly in this order.

## 1. Keys (put them in `.env`; never commit it)

`cp .env.example .env`, then fill in:

| Env var | Where to get it | Unlocks |
|---|---|---|
| `MODEL_API_KEY` and `META_API_KEY` (same value) | <https://dev.meta.ai>: claim the $150 hackathon credits (link in the participant guide), add a card, create an API key, set a $150 spend alert | Muse Spark 1.3, Muse Wonder, Muse Image, Muse Voice Transcribe, SAM 3.1 |
| `BASETEN_API_KEY` | <https://baseten.co>: request the hackathon credits ($100 + 2M TPM), then create an API key. Leave `SPARK_OPEN_MODEL` empty: the id is read from `models.list()` | Muse Spark Open, the open-weights builder |
| `FIREWORKS_API_KEY`, `TOGETHER_API_KEY` (optional) | fireworks.ai ($25 credit) / together.ai | Fallbacks for Spark Open (Together also hosts Glimmer) |
| Modal login | `uv tool run modal token new` (opens the browser; request the $100 Modal credit first) | Self-hosting Glimmer and SAM 3 |
| `HF_TOKEN` | huggingface.co → Settings → Access tokens (read). First request access to `facebook/sam3` and `facebook/sam3.1` (gated) | SAM 3 open weights on Modal |
| `GLIMMER_BASE_URL` | printed by `modal deploy infra/modal/glimmer.py` (see `infra/modal/README.md`) | Muse Glimmer 30B judge |
| `SAM3_OPEN_URL` | printed by `modal secret create huggingface HF_TOKEN=…` then `modal deploy infra/modal/sam3.py` | All-open-weights segmentation |
| `PARTSMITH_ADMIN_TOKEN` | any long random string you choose (`openssl rand -hex 24`) | Locks the admin routes (factory approvals, lessons, print-shop batches). Empty means open, which is fine locally but not on a public deploy. In the web app, enter it once under Factory → Admin access |
| `NEXT_PUBLIC_VOTE_URL` | the community-vote gallery link, once it exists | The "vote for PartSmith" banner after a part verifies |

Then check every provider:

```bash
make smoke      # ✅ live call ok · ⚠️ key missing (mock) · ❌ live call failed (with the reason)
```

**One command to switch to live mode and re-run the benches** (records every live call for replays):

```bash
PROVIDER_RECORD=1 make live
```

`make live` runs the smoke check, then `PROVIDER_MODE=live make bench-live`, which re-runs the synthetic, reference-object and
real-part benches with real models and rewrites the README tables. For the all-open-weights row, run the same with
`OPEN_WEIGHTS_ONLY=1`.

## 2. Photos (no printer, caliper or special paper)

Setup, once: open the app on a laptop (or tablet), go to **Calibrate screen**, hold any bank/ID card against the screen and match
the rectangle. Then open **Screen mat** and lay the laptop flat (opened 180°) or use a tablet. Lower the brightness a little and
avoid ceiling-light reflections. Use **Stage: Dark** for white or light-grey parts. Take photos from above with the phone, so
the part and every marker are in frame. The app's capture gate tells you when to retake.

**Reference objects** (known sizes instead of a caliper). For each object, take 5 top photos in different spots on the stage,
with the phone held slightly differently each time:

| Object | Folder | Extra |
|---|---|---|
| Bank/ID card (any ID-1 card; cover the numbers) | `data/real/reference_objects/id1_card/` | — |
| Full-size SD card | `data/real/reference_objects/sd_card/` | 2 photos lying on its long edge, file names containing `side` |
| LEGO 2×4 brick | `data/real/reference_objects/lego_2x4/` | 2 photos on its side, names containing `side` |
| AA battery | `data/real/reference_objects/aa_cell/` | — (loose spec; that's expected) |

**Real broken parts** (target ≥ 30; 10 are enough to start). Make one folder per part, `data/real/<part_id>/`, containing:
- `top.jpg`: the part lying flat on the stage;
- `side.jpg`: the same part laid on its side (optional but helps);
- `context.jpg` (optional): where the part belongs;
- `gt.yaml`: school-ruler measurements, see the format below. Always `gt_source: ruler`; never call it caliper accuracy.

```yaml
gt_source: ruler
uncertainty_mm: 0.5
user_thickness_mm: 3.0
dims: {length: 42.0, width: 18.5, thickness: 3.0}
holes: [{diameter: 4.0}]
```

Good candidates: cupboard latches, cooler or caster wheels, bucket-handle clips, charger clips, appliance knobs, battery covers,
cable clips, hooks, spacers. Avoid medical, vehicle-safety and weapon parts (the app refuses them).
After adding parts: `uv run python -m eval.splits assign` (10 dev, the rest held-out; held-out is frozen by hash), then `make bench`.

**Walk-around clip (heights):** for parts with tall features (hooks, knobs, latches), also record a 5–10 s video circling the
part on the mat, with the phone tilted about 45° and every marker mostly in frame. Upload it in the **Walk-around clip** slot on
`/fix`. On the same page you can tap holes, slots or the broken edge on the photo, so SAM 3.1 cuts exactly that feature.

**Phone + laptop:** on `/fix` (and on the mat and fit-check pages) scan the QR code with the phone. The phone uploads and the laptop
follows the job live, so you don't need to move files around.

**Impact log:** after each real repair, add one entry to `data/impact/sessions.yaml` (price of a replacement with its source URL,
or "not stocked"; the job id; fit result; grams if printed). `uv run python -m eval.impact` totals it for the README. Never
invent an entry.

**Screen fit check (the video's payoff shot):** run a job on a real part, open **Screen fit check**, lay the part on the pink 1:1
outline and photograph it. The app shows pass or fail.

## 3. Optional

- Real 3D prints: order the demo parts' STLs online only if you want to (Robu.in, Makenica, Zbotic, iamrapid, NIT lab). Never
  claim a print that wasn't made.
- Deploy: Vercel for `apps/web`, the API on Modal or any VM; Neon (`DATABASE_URL`) and R2 (`R2_*`) are optional, since SQLite and
  local disk work.
- Hackathon Discord: post the questions in `docs/FAQ_ANSWERS.md` and log the answers there.
- `LICENSE`: the README says MIT, but there is no LICENSE file yet (agents don't write licence text in this repo). Add one
  if you keep that line.
- Muse Code: it's installed (`muse`). Using it for some of the remaining work and saving session excerpts in
  `docs/BUILT_WITH_MUSE_CODE.md` makes the "Muse Code" row of the Meta tooling table real. Today that row isn't claimed.

## 4. Video (≤ 3:00)

| Time | Shot | Proof on screen |
|---|---|---|
| 0:00–0:12 | The broken part where it belongs (hostel cupboard latch, cooler wheel…); "₹2 part, nobody stocks it" | Real object, real place |
| 0:12–0:30 | Bank card on the laptop screen (calibration), part on the screen mat, phone above; capture gate ticks | Capture-gate reasons |
| 0:30–0:50 | Mask draws in, mm dimension lines; Spark points at a hole, SAM 3.1 cuts it, the mm value appears; the broken region is marked | measured / cited / inferred labels |
| 0:50–1:35 | The loop: the Agent tab shows Spark's thoughts and tool calls; the 3D view flies to where it is looking; error chart steps down | Numbers from verification.json |
| 1:35–1:55 | Hindi-English voice edit ("hook ko 1 mm mota karo") → knobs move; a cited spec footnote from Muse Wonder | Transcript + diff + source URL |
| 1:55–2:10 | Muse Image completes the broken corner, the code gate says "accepted" (labelled AI image) | Gate badge |
| 2:10–2:30 | **Screen fit check:** the 1:1 outline appears, the real part is laid on it, the overlay turns green, in one take | Verifier overlay numbers |
| 2:30–2:48 | Bench tables (synthetic exact · reference objects vs spec · real parts vs ruler) | N, CI, GT source |
| 2:48–3:00 | Registry + MCP: an agent asks for "cooler wheel 32 mm" → STL | Live site |

Label replays as replays. Every number shown must come from the app or `eval/reports/latest`.

## 5. Submission (Cerebral Valley platform, before Wed Nov 4 2026, 9:00 PM ET)

1. Create the GitHub repo and push: `gh repo create partsmith --public --source=. --push`. Run `make gitleaks` first, then check
   that `git ls-files | grep -E 'PLAN.md|KICKOFF_PROMPT.md|REUSE_LOG.md|\.env$'` prints nothing.
2. Write the README **Credits** section (use the gitignored `docs/REUSE_LOG.md`).
3. Upload the video, then submit: problem statement **Push the Frontier**. Claim the bonus prizes with evidence links:
   Open Weights → `/models` + `eval/reports/latest/open_weights.json` + bench open-weights rows; Agentic → the workspace Agent
   tab (thoughts, tool calls, focus) + a factory run; Creative → Muse Image broken-region completion with its code gate,
   see-the-fix preview and install card; Viral → X post link.
4. Post on X (clip + thread), and do the community-vote outreach.
5. Open the repo, the video and the live URL in an incognito window, then save the submission confirmation screenshot.
