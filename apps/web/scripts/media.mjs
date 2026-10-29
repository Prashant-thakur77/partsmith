#!/usr/bin/env node
/**
 * README media, recorded from the real app: docs/media/hero.gif, docs/media/grid.png and one PNG per grid tile.
 *
 * Run it through `make media`, which starts the API in replay mode (no keys, scratch PARTSMITH_HOME) and `next start`,
 * then calls this script and stops both. Every number in the media is whatever the app shows for the committed replays
 * (`data/replays`); this script never edits page content. ffmpeg builds the GIF (palettegen/paletteuse) and burns a
 * "REPLAY · live models" (or "mock providers", from the replay's own summary) corner label when a DejaVu font is installed.
 *
 * Env: MEDIA_WEB_URL (default http://127.0.0.1:3765), MEDIA_OUT (default <repo>/docs/media), MEDIA_TMP (frame scratch
 * dir; default a fresh temp dir, deleted at the end).
 */
import { chromium } from "@playwright/test";
import { execFileSync } from "node:child_process";
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, statSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const REPO = resolve(dirname(fileURLToPath(import.meta.url)), "../../..");
const BASE = (process.env.MEDIA_WEB_URL ?? "http://127.0.0.1:3765").replace(/\/$/, "");
const OUT = resolve(process.env.MEDIA_OUT ?? join(REPO, "docs/media"));
const OWN_TMP = !process.env.MEDIA_TMP;
const TMP = process.env.MEDIA_TMP ? resolve(process.env.MEDIA_TMP) : mkdtempSync(join(tmpdir(), "partsmith-media-"));
const FONT = ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf"].find((f) => existsSync(f));

const HERO_SAMPLE = "demo-battery-cover"; // a live run that fails its first build and verifies after two fixes
const CLIP_SAMPLE = "demo-l-bracket"; // the committed sample with a walk-around clip (fix-upload tile)
const VIEW = { width: 1280, height: 960 }; // hero frames, scaled to 960 px wide in the GIF
const GIF_WIDTH = 960;
const GIF_FPS = 12;

const LIMITS = { hero: 6e6, grid: 1.5e6, total: 10e6 };

function log(msg) {
  process.stdout.write(`media: ${msg}\n`);
}

function replayId(sample) {
  const index = JSON.parse(readFileSync(join(REPO, "data/replays/seed_index.json"), "utf8"));
  const id = index[sample];
  if (!id) throw new Error(`${sample} is not in data/replays/seed_index.json`);
  return id;
}

/** What the stored run says about itself: its provider mode ("live" / "mock") and title. */
function replaySummary(id) {
  const s = JSON.parse(readFileSync(join(REPO, "data/replays", id, "summary.json"), "utf8"));
  const mode = s.provider_mode === "live" ? "live models" : s.provider_mode === "mock" ? "mock providers" : `${s.provider_mode} providers`;
  return { mode, title: String(s.title ?? "").replace(/ \(synthetic sample\)$/, "") };
}

/** Wait until the page has no loading placeholders (skeletons announce themselves as role=status "Loading …"). */
async function settled(page, extraMs = 400) {
  await page.waitForLoadState("networkidle");
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
    await page.mouse.move(1, 1); // and no tooltip left on the toolbar
    await page.waitForTimeout(900);
  }
}

function failOnErrors(errors, where) {
  const real = errors.filter((e) => !/Download the React DevTools|GPU stall|WebGL|swiftshader|Failed to load resource/i.test(e));
  if (real.length) log(`console errors on ${where} (check the media):\n  ${real.join("\n  ")}`);
}

// ------------------------------------------------------------------------------------------------------------ hero

/**
 * Hero frames: the /judges replay player stepped through the stored hero run (error chart falls from the first
 * build to the verified round), then the job workspace: verified badge, the fail → fix strip with three rounds' overlays
 * opened (first build, a middle round, the verified one), and the 3D model with the error chart.
 * Returns [{file, seconds}] in order.
 */
async function heroFrames(browser, id) {
  const dir = join(TMP, "hero");
  mkdirSync(dir, { recursive: true });
  const frames = [];
  const ctx = await browser.newContext({ viewport: VIEW, colorScheme: "light", reducedMotion: "no-preference" });
  const page = await ctx.newPage();
  const errors = [];
  page.on("console", (m) => m.type() === "error" && errors.push(m.text()));
  page.on("pageerror", (e) => errors.push(e.message));
  const snap = async (seconds) => {
    const file = join(dir, `${String(frames.length).padStart(4, "0")}.png`);
    await page.screenshot({ path: file });
    frames.push({ file, seconds });
  };

  // The run's own events decide where the player pauses: right after each iteration's error is known.
  const detail = await (await page.request.get(`${BASE}/api/v1/jobs/${id}`)).json();
  const events = detail.events;
  const n = events.length;
  const holdAt = new Set(events.map((e, i) => (e.t === "iteration" ? i + 1 : -1)).filter((i) => i > 0));
  const stops = new Set([0, n]);
  for (let i = 0; i <= n; i += 12) stops.add(i);
  for (const i of holdAt) stops.add(i);
  const order = [...stops].sort((a, b) => a - b);

  await page.goto(`${BASE}/judges`);
  await settled(page);
  // the chip label: the name, plus the capture preset when another stored run has the same name (distinctTitles)
  const title = detail.summary.title.replace(/\s*\(.*$/, "");
  const preset = (/\(([^()]*)\)(?:\s*\([^()]*\))?\s*$/.exec(detail.summary.title)?.[1] ?? "")
    .split(",")
    .map((w) => w.trim())
    .filter((w) => w && !/^(synthetic|synthetic sample|replay|real|real photo)$/i.test(w));
  const chips = page.getByRole("radio", { name: preset.length ? `${title} · ${preset.join(", ")}` : title, exact: true });
  await ((await chips.count()) ? chips : page.getByRole("radio", { name: title, exact: true })).click();
  await settled(page, 600);
  await page.evaluate(() => {
    const el = document.getElementById("replay");
    if (el) window.scrollTo(0, el.getBoundingClientRect().top + window.scrollY - 118); // below the sticky nav + replay banner
  });
  const slider = page.getByRole("slider", { name: "Replay position" });
  await slider.focus();
  await page.keyboard.press("Home");
  await page.waitForTimeout(300);
  await snap(0.6);
  let at = 0;
  for (const target of order.slice(1)) {
    for (; at < target; at++) await page.keyboard.press("ArrowRight");
    const iterDone = holdAt.has(target);
    const last = target === n;
    await page.waitForTimeout(iterDone || last ? 650 : 120); // the chart animates a new point for 500 ms
    await snap(last ? 1.1 : iterDone ? 0.4 : 0.08);
  }
  failOnErrors(errors, "/judges");

  // Workspace: the finished run with its fail → fix strip, verified badge and the 3D model.
  errors.length = 0;
  await page.goto(`${BASE}/jobs/${encodeURIComponent(id)}`);
  await settled(page, 800);
  await viewerReady(page);
  await page.mouse.move(0, 0);
  await snap(0.9); // header: verified badge, fail → fix strip
  // Open three rounds of the strip: the first build's overlay (large error), a middle round, the verified one.
  const rounds = page.locator('ol[aria-label="Build rounds, oldest first"] button');
  const count = await rounds.count();
  const picks = [...new Set([0, Math.floor((count - 1) / 2), count - 1])];
  const holds = [1.3, 0.7, 1.3];
  for (const [k, i] of picks.entries()) {
    await rounds.nth(i).click();
    await settled(page, 350);
    await page.mouse.move(0, 0);
    await snap(holds[Math.min(k, holds.length - 1)]);
  }
  await rounds.nth(picks.at(-1)).click(); // close the overlay panel again
  await page.mouse.move(1, 1); // no hover tooltips (the error chart) once the page scrolls under the pointer
  await page.waitForTimeout(300);
  // Scroll so the strip sits under the sticky header and the 3D viewer and error chart are in view.
  const titleTop = await page.evaluate(() => {
    const h = [...document.querySelectorAll("h2")].find((e) => /fail → fix history/i.test(e.textContent ?? ""));
    return h ? h.getBoundingClientRect().top + window.scrollY : 0;
  });
  // The sticky header (nav + hatched replay-mode bar) is translucent. Put the strip's title just under it, so only
  // padding and the gap above the strip sit behind the hatched bar and no text shows through it.
  const barsBottom = await page.evaluate(() => document.querySelector("header")?.getBoundingClientRect().bottom ?? 0);
  const target = Math.max(0, titleTop - barsBottom - 3);
  for (let i = 1; i <= 4; i++) {
    await page.evaluate((y) => window.scrollTo(0, y), Math.round((target * i) / 4));
    await page.waitForTimeout(80);
    await snap(1 / GIF_FPS);
  }
  await page.waitForTimeout(600);
  await snap(1.6);
  failOnErrors(errors, `/jobs/${id}`);
  await ctx.close();
  return frames;
}

function buildGif(frames, out, mode) {
  const list = join(TMP, "hero-frames.txt");
  const seconds = frames.reduce((t, f) => t + f.seconds, 0);
  const lines = [];
  for (const f of frames) lines.push(`file '${f.file}'`, `duration ${f.seconds.toFixed(3)}`);
  lines.push(`file '${frames.at(-1).file}'`); // concat demuxer: the last duration needs a following entry
  writeFileSync(list, lines.join("\n") + "\n");
  const label = join(TMP, "label.txt");
  writeFileSync(label, `REPLAY · ${mode}`);
  const draw = FONT
    ? `,drawtext=fontfile=${FONT}:textfile=${label}:fontsize=15:fontcolor=white:box=1:boxcolor=0x111111@0.82:boxborderw=7:x=w-tw-14:y=h-th-14`
    : "";
  const filter =
    `fps=${GIF_FPS},scale=${GIF_WIDTH}:-1:flags=lanczos${draw},split[a][b];` +
    "[a]palettegen=max_colors=192:stats_mode=diff[p];[b][p]paletteuse=dither=bayer:bayer_scale=4:diff_mode=rectangle";
  execFileSync("ffmpeg", ["-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", list, "-filter_complex", filter, "-t", seconds.toFixed(2), "-loop", "0", out], {
    stdio: "inherit",
  });
  return !!FONT;
}

// ------------------------------------------------------------------------------------------------------------ grid

const TILES = [
  { key: "lie-caught", caption: "A lying model, caught: a scripted model says VERIFIED; the verifier measures the real error and the export is blocked" },
  { key: "value-sources", caption: "Colour by source: each value on the model tinted by where it came from (measured, stated by the user, inferred)" },
  { key: "buy-or-print", caption: "Impact and buy-or-print: grams, minutes and cost computed by code from the mesh, labelled estimate" },
  { key: "fix-upload", caption: "Fix a part: the walk-around clip slot (here the committed synthetic clip) and a voice note about the clip" },
];
const GRID_WIDTH = 1600;

/** Screenshot the union of some elements' boxes (page coordinates), padded, at the context's device scale. */
async function clipShot(page, file, locators, pad = 12) {
  const boxes = [];
  for (const l of locators) {
    await l.scrollIntoViewIfNeeded();
    const b = await l.boundingBox();
    if (!b) throw new Error(`no box for ${l}`);
    const sy = await page.evaluate(() => window.scrollY);
    boxes.push({ x: b.x, y: b.y + sy, r: b.x + b.width, b: b.y + b.height + sy });
  }
  const x = Math.max(0, Math.min(...boxes.map((b) => b.x)) - pad);
  const y = Math.max(0, Math.min(...boxes.map((b) => b.y)) - pad);
  const r = Math.max(...boxes.map((b) => b.r)) + pad;
  const btm = Math.max(...boxes.map((b) => b.b)) + pad;
  // Back to the top: the sticky header would otherwise be drawn over the clip at the current scroll position.
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.mouse.move(1, 1);
  await page.waitForTimeout(400);
  await page.screenshot({ path: file, fullPage: true, clip: { x, y, width: r - x, height: btm - y }, animations: "disabled" });
}

/** Re-encode a PNG to an 8-bit palette (ffmpeg) when it is over `limit` bytes; UI screenshots barely change. */
function shrinkPng(file, limit) {
  if (statSync(file).size <= limit) return;
  const tmp = `${file}.tmp.png`;
  execFileSync("ffmpeg", ["-y", "-loglevel", "error", "-i", file, "-vf", "split[a][b];[a]palettegen=max_colors=256:reserve_transparent=0[p];[b][p]paletteuse=dither=none", tmp]);
  execFileSync("mv", [tmp, file]);
}

async function gridTiles(browser, id) {
  // Desktop width, light theme, 2× pixels so the tiles stay sharp when the grid scales them.
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 }, colorScheme: "light", deviceScaleFactor: 2 });
  const page = await ctx.newPage();
  const errors = [];
  page.on("console", (m) => m.type() === "error" && errors.push(m.text()));
  page.on("pageerror", (e) => errors.push(e.message));
  const file = (key) => join(OUT, `tile-${key}.png`);

  // (a) /judges → A lying model, caught
  await page.goto(`${BASE}/judges`);
  await settled(page);
  await clipShot(page, file("lie-caught"), [page.locator("#lie-caught")]);
  failOnErrors(errors, "/judges");

  // (b) workspace: Colour by source on, the user-stated thickness selected so its evidence shows
  errors.length = 0;
  await page.goto(`${BASE}/jobs/${encodeURIComponent(id)}`);
  await settled(page, 800);
  await viewerReady(page);
  await page.getByRole("switch", { name: "Colour by source" }).click();
  const stated = page.locator("#value-sources button[aria-pressed]").filter({ hasText: /Thickness/ }).first();
  if (await stated.count()) await stated.click();
  await page.waitForTimeout(1500);
  await clipShot(page, file("value-sources"), [page.getByRole("group", { name: "Model" }), page.locator("#value-sources")], 0);

  // (c) impact panel + buy-or-print card (right column of the workspace)
  const card = (re) => page.locator("section").filter({ has: page.locator("h2, h3").filter({ hasText: re }) }).first();
  await clipShot(page, file("buy-or-print"), [page.locator(`section[aria-labelledby="impact-${id}"]`), card(/^Buy or print\?$/)]);
  failOnErrors(errors, `/jobs/${id}`);

  // (d) /fix: the committed synthetic L-bracket photo and walk-around clip in their slots; the tile shows the clip slots
  errors.length = 0;
  await page.goto(`${BASE}/fix`);
  await settled(page);
  const sample = join(REPO, "data/synthetic/samples", CLIP_SAMPLE);
  // The clip slot appears once the API's capabilities say the fix endpoint takes a clip; attach files after that.
  await page.getByRole("heading", { name: /^Walk around it/ }).waitFor({ timeout: 30_000 });
  const video = page.locator("video").first();
  for (let attempt = 0; attempt < 3 && !(await video.isVisible()); attempt++) {
    // an attached slot swaps its input for a preview, so a retry only fills the slots that are still empty
    const photo = page.locator('input[type=file][accept^="image/jpeg"]').first();
    if (await photo.count()) await photo.setInputFiles(join(sample, "top.jpg"));
    const clip = page.locator('input[type=file][accept^="video/"]').first();
    if (await clip.count()) await clip.setInputFiles(join(sample, "orbit.mp4"));
    await settled(page, 1500);
    await video.waitFor({ timeout: 10_000 }).catch(() => undefined);
  }
  await video.waitFor({ timeout: 5_000 });
  // Show a frame of the clip instead of a black box (the preview element only loads metadata).
  await video.evaluate(
    (v) =>
      new Promise((done) => {
        v.addEventListener("seeked", () => done(), { once: true });
        v.currentTime = Math.min(2, (v.duration || 4) / 2);
        setTimeout(done, 3000);
      }),
  );
  await page.waitForTimeout(500);
  const slot = (re) => page.locator("div.rounded-lg").filter({ has: page.locator("h3").filter({ hasText: re }) }).last();
  await clipShot(page, file("fix-upload"), [slot(/^Walk around it/), slot(/^Voice note/)]);
  failOnErrors(errors, "/fix");

  // Compose the 2×2 grid as a tiny local HTML page: in each row both tiles get the same height (flex-grow = aspect).
  const dims = Object.fromEntries(
    TILES.map((t) => {
      const [w, h] = execFileSync("ffprobe", ["-v", "error", "-show_entries", "stream=width,height", "-of", "csv=p=0", file(t.key)], { encoding: "utf8" })
        .trim()
        .split(",")
        .map(Number);
      return [t.key, w / h];
    }),
  );
  const fig = (t, i) =>
    `<figure style="flex:${dims[t.key].toFixed(4)} 1 0"><img src="file://${file(t.key)}"><figcaption><b>${String.fromCharCode(97 + i)}</b>${t.caption}</figcaption></figure>`;
  const rows = [TILES.slice(0, 2), TILES.slice(2, 4)].map((r, k) => `<div class="row">${r.map((t, i) => fig(t, k * 2 + i)).join("")}</div>`).join("");
  const html = `<!doctype html><meta charset="utf-8"><style>
    body{margin:0;background:#f4f4f5;font:16px/1.35 "DejaVu Sans",system-ui,sans-serif;color:#18181b}
    main{width:${GRID_WIDTH}px;box-sizing:border-box;padding:16px;display:flex;flex-direction:column;gap:16px}
    header{font-size:15px;color:#52525b}
    .row{display:flex;gap:16px;align-items:flex-start}
    figure{margin:0;min-width:0;background:#fff;border:1px solid #d4d4d8;border-radius:10px;overflow:hidden}
    img{display:block;width:100%;height:auto;border-bottom:1px solid #e4e4e7}
    figcaption{padding:9px 12px;background:#18181b;color:#fafafa;min-height:44px}
    figcaption b{display:inline-block;margin-right:8px;color:#fb923c}
  </style><main><header>PartSmith web app, replay mode: ${replaySummary(id).mode}, ${replaySummary(id).title} (stored run ${id})</header>${rows}</main>`;
  const htmlFile = join(TMP, "grid.html");
  writeFileSync(htmlFile, html);
  const gp = await browser.newPage({ viewport: { width: GRID_WIDTH, height: 1200 }, deviceScaleFactor: 1 });
  await gp.goto(`file://${htmlFile}`);
  await gp.waitForLoadState("load");
  await gp.waitForTimeout(300);
  await gp.locator("main").screenshot({ path: join(OUT, "grid.png") });
  await gp.close();
  await ctx.close();
  shrinkPng(join(OUT, "grid.png"), LIMITS.grid);
  for (const t of TILES) shrinkPng(file(t.key), 1.2e6);
}

// ------------------------------------------------------------------------------------------------------------ main

async function main() {
  mkdirSync(OUT, { recursive: true });
  const id = replayId(HERO_SAMPLE);
  log(`replay ${HERO_SAMPLE} = ${id}; web ${BASE}; out ${OUT}`);
  const browser = await chromium.launch({ args: ["--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"] });
  try {
    const only = process.argv[2];
    if (!only || only === "hero") {
      const frames = await heroFrames(browser, id);
      frames.unshift({ ...frames.at(-1), seconds: 1.5 }); // payoff first: open on the verified end state, then show the run
      const labelled = buildGif(frames, join(OUT, "hero.gif"), replaySummary(id).mode);
      log(`hero.gif: ${frames.length} frames, ${frames.reduce((s, f) => s + f.seconds, 0).toFixed(1)} s, corner label ${labelled ? "burned in" : "skipped (no DejaVu font); the page's own replay badge is visible"}`);
    }
    if (!only || only === "grid") await gridTiles(browser, id);
  } finally {
    await browser.close();
    if (OWN_TMP) rmSync(TMP, { recursive: true, force: true });
  }
  let total = 0;
  for (const f of ["hero.gif", "grid.png", ...TILES.map((t) => `tile-${t.key}.png`)]) {
    const p = join(OUT, f);
    if (!existsSync(p)) continue;
    const size = statSync(p).size;
    total += size;
    const limit = f === "hero.gif" ? LIMITS.hero : f === "grid.png" ? LIMITS.grid : Infinity;
    log(`${f.padEnd(24)} ${(size / 1e6).toFixed(2)} MB${size > limit ? `  OVER the ${(limit / 1e6).toFixed(1)} MB limit` : ""}`);
  }
  log(`total ${(total / 1e6).toFixed(2)} MB${total > LIMITS.total ? "  OVER the 10 MB limit" : ""}`);
  if (total > LIMITS.total) process.exitCode = 1;
}

await main();
