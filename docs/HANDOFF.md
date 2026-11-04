# Handoff: what only the project owner can do

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

### Photo day: commands in order

1. Put the phone exports in one folder (any folder, e.g. `~/photos-nov4/`) and name each file `<part>_top.jpg`,
   `<part>_side.jpg`, `<part>_context.jpg` (part ids: lowercase, digits, `-`, `_`). Reference objects use the object
   name and a number: `id1_card_top_1.jpg`, `sd_card_side_1.jpg`, `lego_2x4_top_3.jpg`, `aa_cell_top_2.jpg`. If renaming
   is a pain, keep the camera names and add a `parts.csv` in the same folder instead (`file,part,view` per line, e.g.
   `IMG_1234.jpg,cupboard-latch,top`). HEIC does not work: set the iPhone to **Most Compatible** or export as JPEG.
2. Bring them in (`ARGS=--dry-run` first shows what would happen):
   ```bash
   make real-intake FROM=~/photos-nov4
   ```
   It writes `data/real/<part>/{top,side,context}.jpg` and `data/real/reference_objects/<object>/<view>_<n>.jpg`. Location,
   dates and device fields are stripped; the orientation and focal-length tags stay (the 35 mm focal length feeds
   the camera estimate) and the JPEG pixels are not re-encoded (`ARGS=--reencode` writes upright re-encoded copies
   instead). Each new part gets a `gt.yaml` template full of `TODO`s. An existing `gt.yaml` is never overwritten; an
   existing photo is only replaced with `ARGS=--force`.
3. Fill every `gt.yaml` with the ruler readings (format above; `length` is the longer side seen from above).
4. Check everything offline, no model calls, no spend:
   ```bash
   make real-check                 # table + one line per thing to fix; exit 1 if any folder is unusable
   make real-check ARGS=--json     # the same as JSON
   ```
   It validates each `gt.yaml` (ruler source, uncertainty, positive mm, holes list, values over 300 mm or under 1 mm,
   plate thicker than the part) and runs the same capture gate as `/fix` on every photo (markers, blur, tilt, glare,
   moiré, exposure, scale). A failed top photo or reference photo makes the folder unusable ("retake top"); a failed
   side photo is a warning, because the job drops it and goes on with the top view. A rough threshold-mask measurement
   (no model) checks that the part is found and flags a ruler reading that is far off (cm typed as mm, swapped
   photos); those lines are advisory. Retake or fix, then run it again until every row says `ok`.
5. Freeze the split **after** the `gt.yaml` files are final (the held-out hash covers their bytes):
   ```bash
   uv run python -m eval.splits assign
   ```
6. Run the real parts and reference photos live with a spend cap (the cap stops new runs once finished ones cost that
   much; `--configs` narrows which configs run):
   ```bash
   make smoke
   PROVIDER_MODE=live uv run python -m eval.run --live --suite real_ruler --suite reference_objects --max-usd 10
   ```
7. Rebuild every table from all stored runs (live runs win over mock) and the README blocks:
   ```bash
   make bench
   ```

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

- **Be the reviewer (10–20 min, worth it).** `make dev`, open `/review`. For each job: look at the photo with the model
  drawn on it. **A** if it is right (tick the rules worth keeping), **I** to click where it is wrong and say what (a
  reviewer round runs live, roughly $0.05–0.50 each), **R** with a reason if it is hopeless. Your decisions are the
  only source of the judge-vs-person agreement numbers and of the family rules, so a dozen honest reviews matter more
  than speed. Notes in plain words are fine ("this corner was square", "hole is for an M3 screw"). Fill the
  "Why it matters" box when you can ("so the cover closes"): the reason is what later parts learn from. Paste a screenshot
  (Ctrl+V) of how the part should look if that is easier than words. `/review/log` shows every piece of feedback and
  whether the next round fixed it. The hinge leaf opens
  first: a recorded four-round chain (my test reviews, labelled) whose round 4 verified and waits for your decision.

- Real 3D prints: order the demo parts' STLs online only if you want to (Robu.in, Makenica, Zbotic, iamrapid, NIT lab). Never
  claim a print that wasn't made.
- **Deploy (only when you decide to go public: it makes the project public).** Everything is prepared in
  `infra/deploy/`. The submission uses one AWS server with Docker Compose (`infra/deploy/aws/README.md`); the Modal and Vercel
  steps below are an optional alternative (full guide: `infra/deploy/README.md`). The public site needs no model keys:
  the API runs in replay mode (labelled mocks for anything not recorded) with the committed replays, demo samples and
  bench reports baked in.
  1. `make deploy-check` (static checks; builds nothing) and `openssl rand -hex 24` for `PARTSMITH_ADMIN_TOKEN`.
  2. API, either on **Modal**: `modal secret create partsmith-api PARTSMITH_ADMIN_TOKEN=<token>
     PARTSMITH_CORS_ORIGINS=https://<web host> PARTSMITH_WEB_URL=https://<web host> PARTSMITH_PUBLIC_URL=https://<web host>
     PARTSMITH_MCP_ALLOWED_HOSTS=<web host>`, then `modal run infra/deploy/modal_app.py::seed` once and
     `modal deploy infra/deploy/modal_app.py` (prints the API URL); or on **any VM with Docker**: copy
     `infra/deploy/api.env.example` outside the repo, fill in the REQUIRED lines, then
     `docker build -f infra/deploy/Dockerfile -t partsmith-api .` and
     `docker run -d --restart unless-stopped --env-file <that file> -v partsmith-data:/data -p 8000:8000 partsmith-api`,
     with HTTPS in front (e.g. Caddy).
  3. Web on **Vercel**: import the repo, Root Directory `apps/web`, set `NEXT_PUBLIC_API_URL` (the API origin, no
     `/api/v1`) and `NEXT_PUBLIC_SITE_URL` (the Vercel URL), deploy. Redeploy the web whenever the API URL changes.
     Live voice uses a WebSocket, which Vercel rewrites do not carry: also set `NEXT_PUBLIC_VOICE_WS_ORIGIN` to the API
     origin (e.g. `https://<api host>`) and keep the web host in the API's `PARTSMITH_CORS_ORIGINS` (the socket refuses
     other origins). Without it the workspace still has the recorded-clip voice edit. Self-hosted `next start` proxies the
     socket by itself.
  4. Incognito check: `/` → "Try a sample" runs a labelled synthetic sample; `/judges` plays a replay and shows "A lying
     model, caught"; `/models` shows replay/mock for every stage.
  Neon (`DATABASE_URL`) and R2 (`R2_*`) stay optional: SQLite and local disk on the volume work.
- Fit-test coupon learning (only if a print happens): download the coupon from a job's Export menu, print it, then on the
  job or part page answer "How did the coupon fit?" (tight / just right / loose per feature, for your printer + material).
  The next fit-preset bake on that browser uses the learned clearance and says "learned from N coupon reports". Nothing is
  pre-filled: with no reports the presets stay the documented starting points.
- Impact panel prices: filament cost on the job page uses an assumed PLA spool price (₹1200 / $20 per kg, shown under
  "How these are computed"). Set `PARTSMITH_PLA_INR_PER_KG` / `PARTSMITH_PLA_USD_PER_KG` on the API to your local price.
- Hackathon Discord: post the questions in `docs/FAQ_ANSWERS.md` and log the answers there.
- `LICENSE`: the README says MIT, but there is no LICENSE file yet (agents don't write licence text in this repo). Add one
  if you keep that line.
- Muse Code: it's installed (`muse`). Using it for some of the remaining work and saving session excerpts in
  `docs/BUILT_WITH_MUSE_CODE.md` makes the "Muse Code" row of the Meta tooling table real. Today that row isn't claimed.

## 4. Video (≤ 3:00) and the X post

**Rules for every frame.** Every number on screen or in a caption comes from the app (job page, `verification.json`) or from
`eval/reports/latest/*.json`; the table below names the source next to each one. Replays, synthetic samples, mocks and AI
images keep their on-screen labels (REPLAY / SYNTHETIC / MOCK / AI preview); never crop a label out. A beat that needs
something that does not exist yet (a print, a live key) is skipped, not faked. No other products are named.

A screen-only draft is generated by `make video` (replay mode, no keys; captions burned in, plus an `.srt` and a beat
list in `var/video/`). It skips the beats below that need a real-world shot and is the template for the final cut.

**Before recording:** live keys in `.env` and `make smoke` green (the realtime voice, walk-around and buy-or-print beats
must show live calls: no MOCK badge in those shots); one real broken part with its ruler `gt.yaml`; laptop at 100 % zoom
with the screen mat calibrated (`/calibrate`); phone screen recording on; OBS or similar on the laptop with a visible clock.

### Storyboard (3:00)

| Time | Beat | On screen (the proof) | Needs a real-world shot? | Burned-in caption |
|---|---|---|---|---|
| 0:00–0:03 | **Payoff first:** the replacement part fitted where the broken one was (drawer, latch, clip), hand closes the drawer | The part itself | **Yes**, only once a print exists. Without a print, open on the screen fit check turning green with the real part on the 1:1 outline (step 2:10 of an earlier run) and say "fit check", not "printed" | "This part was a photo <N> minutes ago", N = the impact panel's photo→file minutes for that job (`GET /jobs/{id}/impact`); without it, "Fitted replacement, from a photo" |
| 0:03–0:10 | **One-line pitch** over the broken part next to the fixed one | Both parts side by side | Yes (same shoot) | "Photo of a broken part → a measured, verified, printable replacement. No caliper: your laptop screen is the ruler." |
| 0:10–1:10 | **One unbroken real run** (screen recording, no cuts; speed-ups allowed only with a visible "4×" tag): phone photo of the part on the laptop's screen mat → capture gate ticks → mask + mm dimension lines → the agent's loop (Agent tab: thoughts, tool calls) → error chart steps down → **VERIFIED** → export menu | Job page clock and job id visible; max error and threshold from `verification.json` (threshold: `eval/reports/latest/provenance.json` → `thresholds.HAUSDORFF_PASS_MM`) | Yes: the phone shot of the part on the screen (hands, real room) for the first 10 s, then the laptop recording | "Screen shows a known grid → millimetres" · "Agent writes CAD code" · "Verifier compares model to photo" · "Export unlocks only when it passes" |
| 1:10–1:25 | **A lying model, caught** (`/judges` → "A lying model, caught"): the model claims "verified", the verifier's red overlay disagrees, the export button stays locked | Overlay + blocked export; the attempts/blocked counts from `eval/reports/latest/bypass.json` (`attempts`, `blocked`), read off the page | No | "The model said 'verified'. The code said no." · "<blocked>/<attempts> fake passes blocked" (fill from `bypass.json`) |
| 1:25–1:45 | **Narrated walk-around:** a short phone clip around the part while talking ("this clip holds the drawer rail, the left tab snapped"); the app marks the function, the mating feature and the break on the frames | Walk-around frames with the pointed features; measured heights labelled "measured", the narration labelled as steering only | **Yes** (the clip and the voice) | "Talk while you film: the model listens, the code measures" |
| 1:45–2:00 | **Buy or print:** the card with the cited part price/availability next to filament grams, cost and print time computed from the verified mesh | Citation footnotes (source URLs) on every price; grams/cost/time from the card | No (but needs live search) | "Cited price vs. print cost" (no numbers in the caption unless they are on the card in the same frame) |
| 2:00–2:15 | **Coupon learning:** the printed fit-test coupon on the mating part, answer "tight" → the preset says "learned from N coupon reports" | The learned-clearance line on the job page (`GET /fit-reports/coupon`) | **Yes**, only if a coupon was printed; otherwise drop the beat and give its seconds to 0:10–1:10 | "Your printer's fit, learned from one test print" |
| 2:15–2:30 | **Realtime Hinglish voice:** hands-free mode on the workspace, say "hook ko 1 mm mota karo"; partial words appear while speaking, then the knob moves and the from→to diff shows | Partial transcript line, the LIVE badge (not MOCK), the "Listening 0:0x / 1:00" clock, the applied-edit row (param, from → to) | Yes: face or hands + laptop in one shot so it's clearly spoken live | Hindi subtitle line: "hook ko 1 mm mota karo" → "(make the hook 1 mm thicker)" |
| 2:30–2:45 | **Bench table** (`/results`): synthetic exact · reference objects vs spec · real parts vs ruler, with N, CI and ground-truth source columns | Numbers exactly as `/results` shows them (`eval/reports/latest/report.json` → `tables`) | No | "Scored against ground truth, not vibes" · name the GT source of the row shown |
| 2:45–3:00 | **Registry + MCP:** an agent asks the MCP server for a part by words → gets a variant → STL; end card with the site URL, QR and "Reply with your broken part" | The MCP tool call and the downloaded STL (export gate respected) | No | "Every verified part becomes an open, parametric program" · end card: URL + "Reply with your broken part → /requests" |

**Burned-in captions.** Burn them into the video (many people watch muted; judges may too) and also upload an `.srt`.
Sentence case, at most 2 lines of about 40 characters, white text on a 70 % black box, bottom third, at least 1.5 s on
screen (longer for numbers). Keep captions inside the centre 4:5 area so the vertical cut can reuse them. Every number in a
caption must be on screen in the same frame and come from the source named in the table. Hindi/Hinglish speech gets an
English subtitle in brackets. Labels the app shows (REPLAY, SYNTHETIC, MOCK, AI preview, "best effort") are never covered.

### X post

**Vertical cut (9:16, 20–40 s, captions burned in, sound optional):**

| Time | Shot | Caption |
|---|---|---|
| 0–2 s | Payoff: the fitted part (or the green screen fit check, labelled as such) | "From a photo to a part that fits" |
| 2–6 s | Phone over the laptop screen mat | "No caliper. Your laptop screen is the ruler." |
| 6–18 s | The unbroken run at "4×" (tag visible): mask → mm → agent loop → VERIFIED | "Measured in mm · CAD written by an agent · checked by code" |
| 18–25 s | Lying model, caught (red overlay, locked export) | "The model can't fake a pass" |
| 25–32 s | Hinglish realtime voice edit, knob moves | "hook ko 1 mm mota karo → (make the hook 1 mm thicker)" |
| 32–38 s | End card: URL + QR | "Reply with your broken part" |

**Thread (4 posts):**

1. "Photo of a broken plastic part → a measured, verified, printable replacement. No caliper: your laptop screen is the
   ruler. Built for the Meta Global AI Developer Hackathon. [vertical cut]"
2. "How: the screen shows a grid of known size, so the photo gives millimetres. Meta's SAM 3.1 outlines the part, Muse Spark
   writes parametric CAD, and a verifier compares the model with the photo. Export unlocks only within
   <HAUSDORFF_PASS_MM> mm." (fill from `eval/reports/latest/provenance.json` → `thresholds.HAUSDORFF_PASS_MM`)
3. "We attacked our own verifier with a model that lies about passing: <blocked>/<attempts> fake passes blocked (from
   `eval/reports/latest/bypass.json`). Bench, with ground-truth sources: <site>/results. Code: <repo URL>."
4. "Got a broken clip, latch, knob or wheel? Reply with a photo (part next to a card or ruler). We add each reply to
   <site>/requests; the most-voted get modelled first and land in the open registry."

**Replies → /requests:** this is manual. For each reply with a usable photo, add it on `/requests` ("Add a request", the
words the person used) or `POST /api/v1/needs`, then reply with the request link. Never say a part is "done" until its
job page shows VERIFIED.

## 5. Submission (Cerebral Valley platform, before Wed Nov 4 2026, 9:00 PM ET)

1. Create the GitHub repo and push: `gh repo create partsmith --public --source=. --push`. Run `make gitleaks` first, then check
   that `git ls-files | grep -E '\.env$'` prints nothing.
2. Upload the video, then submit: problem statement **Push the Frontier**. Claim the bonus prizes with evidence links:
   Open Weights → `/models` + `eval/reports/latest/open_weights.json` + bench open-weights rows; Agentic → the workspace Agent
   tab (thoughts, tool calls, focus) + a factory run; Creative → Muse Image broken-region completion with its code gate,
   see-the-fix preview and install card; Viral → X post link.
3. Post on X (clip + thread), and do the community-vote outreach.
4. Open the repo, the video and the live URL in an incognito window, then save the submission confirmation screenshot.
