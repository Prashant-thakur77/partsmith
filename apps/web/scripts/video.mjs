#!/usr/bin/env node
/**
 * Draft demo video, recorded from the real app: var/video/partsmith-draft.mp4 (H.264, 1280×720) with burned-in captions,
 * the same captions as var/video/partsmith-draft.srt, and var/video/NOTES.md (beats, times, pages, numbers and sources).
 *
 * Run it through `make video`, which starts the API in replay mode (no keys, scratch PARTSMITH_HOME) and `next start`,
 * then calls this script and stops both. It is the screen-only cut of the storyboard in docs/HANDOFF.md §4: beats that need
 * a real-world shot (a print, a phone, a voice) are skipped and listed in NOTES.md. One browser context records the whole
 * walk-through (Playwright recordVideo, WebM); the script marks where each shot starts and ends, ffmpeg cuts those
 * ranges out (page loads stay off screen), adds a plain title and end card and burns the captions in.
 *
 * Every number in a caption is read from the page in the frame it is shown in; this script never edits page content.
 * The pointer is a drawn dot (headless Chromium records no cursor).
 *
 * Env: VIDEO_WEB_URL (default http://127.0.0.1:3766), VIDEO_OUT (default <repo>/var/video), VIDEO_TMP (scratch dir for
 * the WebM and cut segments; default <out>/tmp, deleted at the end).
 */
import { chromium } from "@playwright/test";
import { execFileSync } from "node:child_process";
import { existsSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { dirname, join, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const REPO = resolve(dirname(fileURLToPath(import.meta.url)), "../../..");
const BASE = (process.env.VIDEO_WEB_URL ?? "http://127.0.0.1:3766").replace(/\/$/, "");
const OUT = resolve(process.env.VIDEO_OUT ?? join(REPO, "var/video"));
const TMP = resolve(process.env.VIDEO_TMP ?? join(OUT, "tmp"));
const FONT_DIRS = ["/usr/share/fonts/truetype/dejavu", "/usr/share/fonts/TTF"];
const FONT_DIR = FONT_DIRS.find((d) => existsSync(join(d, "DejaVuSans.ttf")));

const RUN_SAMPLE = "demo-battery-cover"; // the stored live run: fails its first build, verifies after two fixes
const VIEW = { width: 1280, height: 720 };
const FPS = 25;
const MAX_SECONDS = 180;
const TITLE = { seconds: 4.5, lines: ["PartSmith", "Draft · screen-only cut · replays of stored live runs"], size: 54 };
const END = { seconds: 6, lines: ["Reply with your broken part → /requests", "URL coming"], size: 42 };

// Captions (docs/HANDOFF.md §4): ≤ 2 lines of ~40 characters, white on a 70 % black box, bottom third, inside the
// centre 4:5 area (576 px wide at 720 px high), at least 1.5 s on screen.
const CAPTION = { maxChars: 40, minSeconds: 1.5, size: 26, marginV: 40, safeWidth: Math.round((VIEW.height * 4) / 5) };

function log(msg) {
  process.stdout.write(`video: ${msg}\n`);
}

function replayId(sample) {
  const index = JSON.parse(readFileSync(join(REPO, "data/replays/seed_index.json"), "utf8"));
  const id = index[sample];
  if (!id) throw new Error(`${sample} is not in data/replays/seed_index.json`);
  return id;
}

/** Wait until the page has no loading placeholders (skeletons announce themselves as role=status "Loading …"). */
async function settled(page, extraMs = 400) {
  // networkidle can stay out of reach when a page keeps a request open (polling, streams); the skeleton check decides.
  await page.waitForLoadState("networkidle", { timeout: 10_000 }).catch(() => undefined);
  await page.waitForFunction(() => !document.querySelector('[role="status"][aria-label^="Loading"]'), null, { timeout: 30_000 });
  await page.waitForTimeout(extraMs);
}

/** The 3D viewer has drawn its first frames; then "Fit to view" centres the model (as a user would). */
async function viewerReady(page) {
  await page.locator("canvas").first().waitFor({ state: "visible", timeout: 30_000 });
  await page.waitForTimeout(2500); // first frames of the three.js scene (software WebGL in headless Chromium)
  const fit = page.getByRole("button", { name: "Fit to view" });
  if (await fit.count()) {
    await fit.first().click();
    await page.waitForTimeout(900);
  }
}

function failOnErrors(errors, where) {
  const real = errors.filter((e) => !/Download the React DevTools|GPU stall|WebGL|swiftshader|Failed to load resource/i.test(e));
  if (real.length) log(`console errors on ${where} (check the video):\n  ${real.join("\n  ")}`);
  errors.length = 0;
}

/** First number before " mm" in a string, as the page prints it (no reformatting). */
function mmOf(text) {
  return /(\d+(?:\.\d+)?)\s*mm/.exec(text ?? "")?.[1] ?? null;
}

// ------------------------------------------------------------------------------------------------------------ motion

// A drawn pointer: a dot that follows mouse events (headless recordings have no cursor), shrinks while pressed and
// fades out when the mouse rests. Also: the sticky header (nav + hatched replay-mode bar) is translucent, so scrolled text
// shows through it and garbles the "Replay mode" label; for the recording it gets an opaque page background under it.
const POINTER = `addEventListener("DOMContentLoaded", () => {
  const css = document.createElement("style");
  css.textContent = "header.sticky > * { background-color: var(--color-bg, #fafafa) !important; }";
  document.head.appendChild(css);
  const c = document.createElement("div");
  c.setAttribute("aria-hidden", "true");
  Object.assign(c.style, { position: "fixed", left: "-9px", top: "-9px", width: "18px", height: "18px", borderRadius: "50%",
    background: "rgba(24,24,27,.35)", border: "2px solid #fff", boxShadow: "0 0 0 1px rgba(0,0,0,.45)", zIndex: "2147483647",
    pointerEvents: "none", transform: "translate(-60px,-60px)", transition: "scale .12s, opacity .4s", opacity: "0" });
  document.body.appendChild(c);
  let idle = 0;
  const at = (e) => {
    c.style.transform = "translate(" + e.clientX + "px," + e.clientY + "px)";
    c.style.opacity = "1";
    clearTimeout(idle);
    idle = setTimeout(() => (c.style.opacity = "0"), 1400);
  };
  addEventListener("mousemove", at, true);
  addEventListener("mousedown", (e) => (at(e), (c.style.scale = "0.7")), true);
  addEventListener("mouseup", () => (c.style.scale = "1"), true);
});`;

const easeInOut = (k) => (k < 0.5 ? 4 * k * k * k : 1 - Math.pow(-2 * k + 2, 3) / 2);

/** Eased window scroll to `y` over `ms` (requestAnimationFrame in the page). */
async function scrollToY(page, y, ms = 1200) {
  await page.evaluate(
    ([to, ms]) =>
      new Promise((done) => {
        const from = window.scrollY;
        const max = document.documentElement.scrollHeight - window.innerHeight;
        const end = Math.max(0, Math.min(max, to));
        const t0 = performance.now();
        const step = (now) => {
          const k = Math.min(1, (now - t0) / ms);
          const e = k < 0.5 ? 4 * k * k * k : 1 - Math.pow(-2 * k + 2, 3) / 2;
          window.scrollTo(0, from + (end - from) * e);
          if (k < 1) requestAnimationFrame(step);
          else done();
        };
        requestAnimationFrame(step);
      }),
    [y, ms],
  );
  await page.waitForTimeout(150);
}

/** Page y that puts `locator`'s top `gap` px under the sticky header (nav + replay-mode bar). */
async function yUnderHeader(page, locator, gap = 14) {
  return locator.evaluate((el, gap) => {
    const bar = document.querySelector("header")?.getBoundingClientRect().bottom ?? 0;
    return el.getBoundingClientRect().top + window.scrollY - bar - gap;
  }, gap);
}

/** Move the drawn pointer to the centre of `locator` (or an offset in it) along an eased path. */
const pointer = { x: VIEW.width * 0.62, y: VIEW.height * 0.8 };
async function glide(page, locator, ms = 700, at = { fx: 0.5, fy: 0.5 }) {
  const b = await locator.boundingBox();
  if (!b) throw new Error(`no box for ${locator}`);
  const to = { x: b.x + b.width * at.fx, y: b.y + b.height * at.fy };
  const steps = Math.max(2, Math.round(ms / 20));
  const from = { ...pointer };
  for (let i = 1; i <= steps; i++) {
    const e = easeInOut(i / steps);
    await page.mouse.move(from.x + (to.x - from.x) * e, from.y + (to.y - from.y) * e);
    await page.waitForTimeout(12);
  }
  Object.assign(pointer, to);
}

async function glideClick(page, locator, ms = 700) {
  await glide(page, locator, ms);
  await page.waitForTimeout(180);
  await page.mouse.down();
  await page.waitForTimeout(90);
  await page.mouse.up();
}

/** Park the pointer somewhere harmless (no hover tooltips) without a visible jump. */
async function park(page, x = VIEW.width - 40, y = VIEW.height - 40) {
  await page.mouse.move(x, y);
  Object.assign(pointer, { x, y });
}

/** Slow horizontal drag on the 3D viewer: orbits the model the way a user would. */
async function orbit(page, canvas, dx = 220, ms = 1800) {
  const b = await canvas.boundingBox();
  if (!b) return;
  const start = { x: b.x + b.width * 0.42, y: b.y + b.height * 0.55 };
  await glide(page, canvas, 500, { fx: 0.42, fy: 0.55 });
  await page.mouse.down();
  const steps = Math.round(ms / 20);
  for (let i = 1; i <= steps; i++) {
    const e = easeInOut(i / steps);
    await page.mouse.move(start.x + dx * e, start.y - 18 * Math.sin(Math.PI * e));
    await page.waitForTimeout(12);
  }
  await page.mouse.up();
  Object.assign(pointer, { x: start.x + dx, y: start.y });
}

// ------------------------------------------------------------------------------------------------------------ takes

/**
 * Shot list on one page: `roll(beat)` starts a shot, `cut()` ends it, `cue(text, s)` starts a caption now (seconds from
 * the recording's first frame). Time between shots (navigation, loading) is cut out of the video.
 */
function takes(t0) {
  const shots = [];
  const now = () => (Date.now() - t0) / 1000;
  return {
    shots,
    roll(beat, page, note) {
      if (shots.at(-1) && shots.at(-1).end == null) throw new Error("roll() while a shot is running");
      shots.push({ beat, page, note, start: now(), end: null, cues: [], numbers: [] });
    },
    cut() {
      shots.at(-1).end = now();
    },
    cue(text, seconds = 3, numbers = []) {
      const s = shots.at(-1);
      if (!s || s.end != null) throw new Error(`cue outside a shot: ${text}`);
      s.cues.push({ at: now(), text, seconds: Math.max(seconds, CAPTION.minSeconds) });
      s.numbers.push(...numbers);
    },
  };
}

/** The whole walk-through in one recorded page. Returns the shot list (times relative to the WebM's first frame). */
async function record(browser, id) {
  mkdirSync(join(TMP, "webm"), { recursive: true });
  const ctx = await browser.newContext({
    viewport: VIEW,
    colorScheme: "light",
    reducedMotion: "no-preference",
    recordVideo: { dir: join(TMP, "webm"), size: VIEW },
  });
  await ctx.addInitScript(POINTER);
  const page = await ctx.newPage();
  const t = takes(Date.now());
  const errors = [];
  page.on("console", (m) => m.type() === "error" && errors.push(m.text()));
  page.on("pageerror", (e) => errors.push(e.message));
  const hold = (ms) => page.waitForTimeout(ms);
  const job = `/jobs/${encodeURIComponent(id)}`;

  // ---- Main run, part 1: /judges "Replay a run", the stored battery-cover run played back from its run log.
  await page.goto(`${BASE}/judges`);
  await settled(page);
  await park(page);
  t.roll("run", "/judges → Replay a run", "Stored live run, chip “Battery compartment cover · clean”, played at the player's 2× setting");
  await hold(900);
  const replay = page.locator("#replay");
  await scrollToY(page, await yUnderHeader(page, page.getByRole("heading", { name: "Replay a run" })), 1400);
  t.cue("A stored live run, replayed\nfrom its run log", 3.2);
  await hold(500);
  const chip = page.getByRole("radio", { name: "Battery compartment cover · clean", exact: true });
  await glideClick(page, chip);
  await settled(page, 500);
  // The player under the chips: its header (REPLAY · synthetic · LIVE) to its controls (Play, speed) above the captions.
  const player = replay.locator("div.rounded-xl").filter({ has: page.getByRole("slider", { name: "Replay position" }) }).first();
  await scrollToY(page, await yUnderHeader(page, player, 8), 900);
  await hold(600);
  await glideClick(page, player.getByRole("radio", { name: "2×" }), 600);
  await hold(400);
  await glideClick(page, player.getByRole("button", { name: "Play" }), 500);
  await park(page, VIEW.width - 40, 120);
  // Captions follow the player's own "Now" line, so each one appears while its stage is on screen.
  const nowLine = player.locator('[aria-live="polite"] p');
  const stageCues = [
    [/^Measure in millimetres/, "Known mat grid in the photo\n→ millimetres", 3.5],
    [/^(Write the CAD program|Run it in the sandbox)/, "The agent writes CAD code;\nit runs in a sandbox", 3.5],
    [/^Compare model to photo/, "The verifier compares the\nmodel with the photo", 3.5],
    [/^Fix the differences/, "Over the limit: the agent\nfixes it and builds again", 3.5],
  ];
  const deadline = Date.now() + 120_000;
  let lastCue = 0;
  while (Date.now() < deadline) {
    const now = (await nowLine.textContent()) ?? "";
    if (/^Finished/.test(now)) break;
    // A stage that shows up while the previous caption is still on screen waits for it (and drops the ones before it).
    const next = stageCues.findIndex(([re]) => re.test(now));
    if (next >= 0) stageCues[next].seen = true;
    const due = stageCues.findIndex((c) => c.seen);
    if (due >= 0 && Date.now() - lastCue > 4000) {
      const [, text, s] = stageCues.splice(0, due + 1).at(-1);
      t.cue(text, s);
      lastCue = Date.now();
    }
    await hold(100);
  }
  await hold(700);
  t.cue("Finished: the verifier's result\nfrom the stored run", 3);
  await hold(3000);
  await glide(page, player.getByRole("link", { name: "Open full workspace" }), 700);
  await hold(250);
  t.cut();
  failOnErrors(errors, "/judges");

  // ---- Main run, part 2: the job workspace. Fail → fix strip, overlays, error chart, 3D model, Agent tab, Export.
  await page.goto(`${BASE}${job}`);
  await settled(page, 800);
  await viewerReady(page);
  await park(page);
  t.roll("run", `${job} (workspace)`, "Verified badge, fail → fix strip, round overlays, 3D model, error chart, Agent tab, export menu");
  await hold(1200);
  const strip = page.locator("section").filter({ has: page.locator("h2").filter({ hasText: /fail → fix history/i }) }).first();
  const rounds = strip.locator('ol[aria-label="Build rounds, oldest first"] button');
  const n = await rounds.count();
  const roundMm = [];
  for (let i = 0; i < n; i++) roundMm.push(/(\d+(?:\.\d+)?)\s*mm\s*max error/i.exec((await rounds.nth(i).innerText()).replace(/\s+/g, " "))?.[1]);
  const stripText = await strip.innerText();
  const limitMm = mmOf(/limit\s+\d+(?:\.\d+)?\s*mm/i.exec(stripText)?.[0]);
  const fixes = /\((\d+) fix(?:es)?\)/i.exec(stripText)?.[1]; // "Verified after 3 rounds (2 fixes)"
  const path = roundMm.join(" → ");
  t.cue(`Fail → fix: ${path} mm\n(limit ${limitMm} mm)`, 4.5, [`${path} mm, limit ${limitMm} mm (fail → fix strip, from the run's iterations)`]);
  await hold(2600);
  await glideClick(page, rounds.first());
  await settled(page, 300);
  await park(page, VIEW.width - 40, 140);
  await scrollToY(page, await yUnderHeader(page, strip, 6), 900);
  t.cue(`First build: ${roundMm[0]} mm off\nthe photo, not verified`, 3.5, [`${roundMm[0]} mm (round 1 tile)`]);
  await hold(3600);
  await glideClick(page, rounds.nth(n - 1));
  await settled(page, 300);
  await park(page, VIEW.width - 40, 140);
  t.cue(`After ${fixes} fixes: ${roundMm[n - 1]} mm,\nunder the ${limitMm} mm limit`, 3.5, [`${fixes} fixes, ${roundMm[n - 1]} mm and ${limitMm} mm (round ${n} tile, strip header)`]);
  await hold(3600);
  await glideClick(page, rounds.nth(n - 1)); // close the overlay panel again
  await park(page, VIEW.width - 40, 140);
  await hold(400);
  // The 3D model and the error chart, side by side under the strip.
  await scrollToY(page, await yUnderHeader(page, strip, 4) + (await strip.boundingBox()).height + 4, 1300);
  t.cue("Error per round, and the\nverified CAD model in 3D", 3.5);
  await hold(1200);
  await orbit(page, page.locator("canvas").first());
  await hold(1600);
  // The Agent tab: the tool calls behind each fix.
  const agentTab = page.getByRole("tab", { name: /^Agent/ }).first();
  if (await agentTab.count()) {
    await scrollToY(page, await yUnderHeader(page, agentTab, 10), 1400);
    await glideClick(page, agentTab, 500);
    await park(page, VIEW.width - 40, 140);
    t.cue("Agent tab: what it looked at\nand every tool call", 3.5);
    await hold(3800);
  }
  // Export: one click once verified.
  await scrollToY(page, 0, 1400);
  const exportBtn = page.getByRole("button", { name: "Export" }).first();
  await glideClick(page, exportBtn);
  await hold(500);
  t.cue("Export unlocks only when\nthe verifier passes it", 3.5);
  await hold(3400);
  await page.keyboard.press("Escape");
  await hold(500);
  t.cut();
  failOnErrors(errors, job);

  // ---- A lying model, caught (/judges): a scripted model claims VERIFIED; the verifier measures, the export is blocked.
  await page.goto(`${BASE}/judges`);
  await settled(page);
  await park(page);
  const lie = page.locator("#lie-caught");
  await page.evaluate((y) => window.scrollTo(0, y), (await yUnderHeader(page, lie)) - 260);
  await hold(300);
  t.roll("lie", "/judges → A lying model, caught", "Scripted mock attacks (no model call), labelled as such on the page");
  await hold(600);
  await scrollToY(page, await yUnderHeader(page, lie), 1200);
  const tally = lie.locator("p").filter({ hasText: /lying-model attacks blocked by code/ }).first();
  const [, blocked, attempts] = /(\d+)\s*\/\s*(\d+)/.exec((await tally.textContent()) ?? "") ?? [];
  t.cue("The model said “verified”.\nThe code said no.", 3.2);
  await hold(3400);
  t.cue(`${blocked}/${attempts} fake passes blocked`, 3.2, [`${blocked}/${attempts} (section tally, eval/reports/latest/bypass.json)`]);
  await hold(3400);
  const blockedNote = lie.getByText(/^Export blocked:/).first();
  await scrollToY(page, (await yUnderHeader(page, blockedNote, 0)) - 330, 1600);
  t.cue("The verifier measures the real\nerror; the export stays blocked", 3.8);
  await hold(4200);
  t.cut();
  failOnErrors(errors, "/judges");

  // ---- Buy or print (same job): the card is LIVE in the stored run; grams, minutes and cost computed from the mesh.
  await page.goto(`${BASE}${job}`);
  await settled(page, 800);
  await viewerReady(page);
  await park(page);
  const impact = page.locator(`section[aria-labelledby="impact-${id}"]`);
  await page.evaluate((y) => window.scrollTo(0, y), (await yUnderHeader(page, impact)) - 240);
  await hold(300);
  t.roll("buy", `${job} → Impact + Buy or print?`, "Card labelled LIVE (stored live run); print figures labelled estimate");
  await hold(500);
  await scrollToY(page, await yUnderHeader(page, impact, 10), 1200);
  const bop = page.locator(`section[aria-labelledby="bop-${id}"]`);
  t.cue("Buy or print: print weight, time\nand cost computed from the mesh", 4);
  await hold(600);
  await glide(page, bop.getByText("PLA", { exact: true }).first(), 900);
  await hold(3400);
  const buyText = ((await bop.textContent()) ?? "").replace(/\s+/g, " ");
  const noPrice = /no price with a cited page/i.test(buyText);
  t.cue(noPrice ? "No cited price was found,\nso no price is shown" : "Cited price vs. print cost", 3.5);
  await hold(3900);
  t.cut();
  failOnErrors(errors, `${job} (buy or print)`);

  // ---- Results: the bench tables, each with N, CI and its ground-truth source.
  await page.goto(`${BASE}/results`);
  await settled(page);
  await park(page);
  t.roll("results", "/results", "Bench report eval/reports/latest/report.json (live providers, rebuilt from stored runs)");
  await hold(800);
  t.cue("Scored against ground truth,\nnot vibes", 3.4);
  await hold(3600);
  const h2 = (re) => page.locator("h2").filter({ hasText: re }).first();
  // Lower than the other sections: the next section's ground-truth badge would otherwise sit under the caption.
  await scrollToY(page, await yUnderHeader(page, h2(/^Synthetic photos/), 94), 1500);
  t.cue("Synthetic photos: exact ground\ntruth from the rendered mesh", 3.6);
  await hold(4000);
  await scrollToY(page, await yUnderHeader(page, h2(/^Reference objects/)), 1500);
  t.cue("Reference objects vs their\npublished sizes", 3.4);
  await hold(3800);
  await scrollToY(page, await yUnderHeader(page, h2(/^Real broken parts/)), 1300);
  t.cue("Real parts vs a ruler: not run\nyet, and the page says so", 3.4);
  await hold(3800);
  t.cut();
  failOnErrors(errors, "/results");

  // ---- Registry + agents: REST and MCP for coding agents.
  await page.goto(`${BASE}/agents`);
  await settled(page);
  await park(page);
  t.roll("agents", "/agents", "MCP tools and REST routes (endpoint shown is the local recording server)");
  await hold(800);
  t.cue("Every verified part becomes an\nopen, parametric program", 3.6);
  await hold(3600);
  await scrollToY(page, await yUnderHeader(page, h2(/^Connect over MCP/)), 1500);
  t.cue("Coding agents search, adapt and\nbake parts over MCP", 3.6);
  await hold(4000);
  await scrollToY(page, await yUnderHeader(page, h2(/^REST/)), 1500);
  t.cue("…or plain REST, all lengths\nin millimetres", 3.4);
  await hold(3800);
  t.cut();
  failOnErrors(errors, "/agents");

  await ctx.close(); // flushes the WebM
  const webm = await page.video().path();
  return { webm, shots: t.shots };
}

// ------------------------------------------------------------------------------------------------------------ ffmpeg

function ff(args) {
  execFileSync("ffmpeg", ["-y", "-hide_banner", "-loglevel", "error", ...args], { stdio: "inherit" });
}

const X264 = ["-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p", "-r", String(FPS), "-an"];

/** Plain text card: dark background, the first line large, the rest smaller, centred. */
function card(file, { lines, seconds, size: titleSize }) {
  const font = (bold) => (FONT_DIR ? `fontfile=${join(FONT_DIR, bold ? "DejaVuSans-Bold.ttf" : "DejaVuSans.ttf")}:` : "");
  const draws = lines.map((line, i) => {
    const txt = join(TMP, `card-${relative(TMP, file).replace(/\W/g, "_")}-${i}.txt`);
    writeFileSync(txt, line);
    const size = i === 0 ? titleSize : 28;
    const y = i === 0 ? "h/2-th-18" : `h/2+${18 + (i - 1) * 46}`;
    return `drawtext=${font(i === 0)}textfile=${txt}:fontsize=${size}:fontcolor=${i === 0 ? "white" : "0xd4d4d8"}:x=(w-tw)/2:y=${y}`;
  });
  const fade = `fade=t=in:st=0:d=0.4,fade=t=out:st=${(seconds - 0.4).toFixed(2)}:d=0.4`;
  ff(["-f", "lavfi", "-i", `color=c=0x18181b:s=${VIEW.width}x${VIEW.height}:r=${FPS}:d=${seconds}`, "-vf", [...draws, fade].join(","), ...X264, file]);
}

const ts = (s, sep) => {
  const ms = Math.round(s * 1000);
  const p = (v, w = 2) => String(v).padStart(w, "0");
  return `${p(Math.floor(ms / 3.6e6))}:${p(Math.floor(ms / 6e4) % 60)}:${p(Math.floor(ms / 1000) % 60)}${sep}${p(ms % 1000, 3)}`;
};
const mmss = (s) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`;

/** Caption lines: at most 2, each ≤ CAPTION.maxChars (the shot list writes the breaks). */
function checkCaption(text) {
  const lines = text.split("\n");
  if (lines.length > 2 || lines.some((l) => l.length > CAPTION.maxChars)) throw new Error(`caption too long: ${JSON.stringify(text)}`);
  return lines;
}

function writeSubtitles(cues, srtFile, assFile) {
  const srt = cues.map((c, i) => `${i + 1}\n${ts(c.start, ",")} --> ${ts(c.end, ",")}\n${checkCaption(c.text).join("\n")}\n`).join("\n");
  writeFileSync(srtFile, srt);
  const side = Math.round((VIEW.width - CAPTION.safeWidth) / 2);
  // BorderStyle 4 (libass) = one box behind the whole caption, BackColour &H4D000000 = black at 70 % opacity (ASS alpha
  // 0x4D = 30 % transparent); Outline is the box padding, drawn in a fully transparent OutlineColour.
  const ass = [
    "[Script Info]",
    "ScriptType: v4.00+",
    `PlayResX: ${VIEW.width}`,
    `PlayResY: ${VIEW.height}`,
    "WrapStyle: 2",
    "ScaledBorderAndShadow: yes",
    "",
    "[V4+ Styles]",
    "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
    `Style: Caption,DejaVu Sans,${CAPTION.size},&H00FFFFFF,&H00FFFFFF,&HFF000000,&H4D000000,0,0,0,0,100,100,0,0,4,12,0,2,${side},${side},${CAPTION.marginV},1`,
    "",
    "[Events]",
    "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ...cues.map((c) => `Dialogue: 0,${ts(c.start, ".").slice(1, -1)},${ts(c.end, ".").slice(1, -1)},Caption,,0,0,0,,${checkCaption(c.text).join("\\N")}`),
  ];
  writeFileSync(assFile, ass.join("\n") + "\n");
}

/** Cut the shots out of the WebM, add the cards, burn the captions. Returns the timeline for NOTES.md. */
function stitch(webm, shots) {
  const segs = [];
  const parts = [];
  const cues = [];
  let at = 0;
  const title = join(TMP, "title.mp4");
  card(title, TITLE);
  parts.push(title);
  segs.push({ beat: "title", page: "ffmpeg text card", note: TITLE.lines.join(" · "), from: 0, to: TITLE.seconds, numbers: [] });
  at += TITLE.seconds;
  shots.forEach((s, i) => {
    const file = join(TMP, `shot-${String(i).padStart(2, "0")}.mp4`);
    const seconds = s.end - s.start;
    ff(["-i", webm, "-ss", s.start.toFixed(3), "-t", seconds.toFixed(3), "-vf", `fps=${FPS},scale=${VIEW.width}:${VIEW.height}:flags=lanczos`, ...X264, file]);
    parts.push(file);
    s.cues.forEach((c, k) => {
      const start = at + (c.at - s.start);
      const nextAt = k + 1 < s.cues.length ? at + (s.cues[k + 1].at - s.start) - 0.08 : at + seconds - 0.1;
      const end = Math.min(start + c.seconds, nextAt);
      if (end - start < CAPTION.minSeconds) log(`caption shorter than ${CAPTION.minSeconds} s: ${JSON.stringify(c.text)}`);
      cues.push({ start, end, text: c.text });
    });
    segs.push({ beat: s.beat, page: s.page, note: s.note, from: at, to: at + seconds, numbers: s.numbers, cues: cues.slice(cues.length - s.cues.length) });
    at += seconds;
  });
  const end = join(TMP, "end.mp4");
  card(end, END);
  parts.push(end);
  segs.push({ beat: "end", page: "ffmpeg text card", note: END.lines.join(" · "), from: at, to: at + END.seconds, numbers: [] });

  const list = join(TMP, "parts.txt");
  writeFileSync(list, parts.map((p) => `file '${p}'`).join("\n") + "\n");
  const joined = join(TMP, "joined.mp4");
  ff(["-f", "concat", "-safe", "0", "-i", list, "-c", "copy", joined]);
  const srt = join(OUT, "partsmith-draft.srt");
  const ass = join(TMP, "captions.ass");
  writeSubtitles(cues, srt, ass);
  const fonts = FONT_DIR ? `:fontsdir=${FONT_DIR}` : "";
  ff(["-i", joined, "-vf", `ass=${ass}${fonts}`, "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p", "-movflags", "+faststart", "-an", join(OUT, "partsmith-draft.mp4")]);
  return segs;
}

// ------------------------------------------------------------------------------------------------------------ notes

const SKIPPED = [
  ["0:00–0:03", "Payoff first (the fitted replacement, or the screen fit check with the real part)", "needs a print or a real part on the 1:1 outline"],
  ["0:03–0:10", "One-line pitch over the broken part next to the fixed one", "needs both physical parts"],
  ["0:10–0:20 (first part of the real run)", "Phone photo of the part on the laptop's screen mat, capture gate", "needs the phone shot; the stored run is a synthetic photo, so the cut opens on the replay player instead"],
  ["1:25–1:45", "Narrated walk-around clip", "needs a real phone clip and live voice"],
  ["2:00–2:15", "Coupon learning", "needs a printed fit-test coupon"],
  ["2:15–2:30", "Realtime Hinglish voice edit", "needs live keys and a live voice in shot (no MOCK badge)"],
  ["2:45–3:00 (part)", "An agent calling the MCP server and downloading an STL; site URL and QR on the end card", "the scratch registry is empty (no seeded parts) and no site is deployed; the cut shows /agents and an end card saying “URL coming”"],
];

function writeNotes(segs, id, duration) {
  const rows = segs.map((s) => `| ${mmss(s.from)}–${mmss(s.to)} (${s.from.toFixed(1)}–${s.to.toFixed(1)} s) | ${s.beat} | ${s.page} | ${s.note} | ${s.numbers.length ? s.numbers.join("; ") : "none in captions"} |`);
  const caps = segs.flatMap((s) => (s.cues ?? []).map((c) => `- ${ts(c.start, ".").slice(3, -1)} → ${ts(c.end, ".").slice(3, -1)}: ${c.text.replace(/\n/g, " ")}`));
  const md = `# PartSmith draft video (screen-only cut)

Generated by \`make video\` (apps/web/scripts/video.mjs) from the web app in replay mode: API with PROVIDER_MODE=replay,
no .env, scratch PARTSMITH_HOME. Stored run: ${id} (data/replays/${id}, provider_mode live, synthetic input photo).
Duration: ${duration.toFixed(2)} s (ffprobe). Placeholder for the final video: real-world shots, voice and the site URL
are added later.

Every number in a caption is read from the page at recording time, in the frame where the caption shows it. Numbers on
screen are the app's own (job page and verification.json via the API, /results from eval/reports/latest/report.json,
the lying-model tally from eval/reports/latest/bypass.json). The app's REPLAY / SYNTHETIC / LIVE / MOCK labels stay in
frame. The pointer is a drawn dot. The replay player runs at its 2× setting (it also caps each gap between events at
1.2 s, so it is faster than real time); the selected 2× button is visible while it plays. The sticky header gets an opaque
background in the recording so scrolled text does not show through the "Replay mode" bar.
Known overlap: in two workspace shots the caption box sits over part of the 3D viewer's "Agent is looking at" chip
(not a provenance label).

## Beats

| Time | Beat | Page recorded | What is shown | Numbers in captions (source) |
|---|---|---|---|---|
${rows.join("\n")}

## Captions

${caps.join("\n")}

## Skipped storyboard beats (need real-world footage or things that do not exist yet)

${SKIPPED.map(([t, b, why]) => `- ${t}: ${b}. Skipped: ${why}.`).join("\n")}

Their seconds went to the main run (replay player + workspace).
`;
  writeFileSync(join(OUT, "NOTES.md"), md);
}

// ------------------------------------------------------------------------------------------------------------ main

async function main() {
  mkdirSync(OUT, { recursive: true });
  mkdirSync(TMP, { recursive: true });
  const id = replayId(RUN_SAMPLE);
  log(`replay ${RUN_SAMPLE} = ${id}; web ${BASE}; out ${OUT}`);
  const browser = await chromium.launch({ args: ["--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"] });
  let rec;
  try {
    rec = await record(browser, id);
  } finally {
    await browser.close();
  }
  try {
    const segs = stitch(rec.webm, rec.shots);
    const out = join(OUT, "partsmith-draft.mp4");
    const duration = Number(execFileSync("ffprobe", ["-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", out], { encoding: "utf8" }).trim());
    writeNotes(segs, id, duration);
    for (const s of segs) log(`${mmss(s.from)}–${mmss(s.to)}  ${s.beat.padEnd(8)} ${s.page}`);
    log(`partsmith-draft.mp4 ${duration.toFixed(2)} s${duration > MAX_SECONDS ? `  OVER the ${MAX_SECONDS} s limit` : ""}; partsmith-draft.srt; NOTES.md`);
    if (duration > MAX_SECONDS) process.exitCode = 1;
  } finally {
    if (!process.env.VIDEO_KEEP_TMP) rmSync(TMP, { recursive: true, force: true });
  }
}

await main();
