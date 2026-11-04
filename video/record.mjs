// Records the real app as crisp frames (Chrome's screencast, JPEG q92) and writes an exact-timed MP4, plus the moments
// the editor cuts on (marks, in seconds from the first frame).
//   node video/record.mjs <flow> [site]
//   flows: calibrate, replay, job, lie, knobs, fit, review, registry; gfx-<scene> (graphics.html / three.html)
// The app runs in replay mode: every screen shows stored runs, and the app's own REPLAY labels stay in frame.
import { spawnSync } from "node:child_process";
import { mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { createRequire } from "node:module";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const { chromium } = createRequire(path.join(ROOT, "apps/web/package.json"))("@playwright/test");

const FLOW = process.argv[2];
const SITE = process.argv[3] || "http://127.0.0.1:3766";
const WORK = `${process.env.HOME}/Videos/partsmith`;
const OUT = `${WORK}/clips`;
const FRAMES = `${OUT}/frames-${FLOW}`;
const RUN = "j_261029_daf26965"; // the stored live battery-cover run
const HINGE = "j_261029_143b6e19";
rmSync(FRAMES, { recursive: true, force: true });
mkdirSync(FRAMES, { recursive: true });

const MIC = FLOW === "say" ? ["--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream", `--use-file-for-fake-audio-capture=${WORK}/voiceedit/say.wav%noloop`] : [];
const browser = await chromium.launch({ args: ["--use-angle=gl", "--enable-gpu", "--ignore-gpu-blocklist", ...MIC] });
// The site: 1536×864 at 1.25 renders its desktop layout into exactly 1920×1080 pixels. Drawn scenes are laid out at
// 1920×1080 themselves, so they get a window that size at 1×.
const DRAWN = FLOW.startsWith("gfx-");
const ctx = await browser.newContext(
  DRAWN
    ? { viewport: { width: 1920, height: 1080 }, deviceScaleFactor: 1, colorScheme: "light" }
    : { viewport: { width: 1536, height: 864 }, deviceScaleFactor: 1.25, colorScheme: "light", reducedMotion: "no-preference" },
);
await ctx.addInitScript(() => {
  try {
    localStorage.setItem("theme", "light");
  } catch {}
});
if (FLOW === "say") {
  // `next start` does not proxy WebSockets; the deployed site points the socket at the API the same way.
  await ctx.addInitScript(() => {
    const Real = window.WebSocket;
    window.WebSocket = new Proxy(Real, { construct: (t, a) => new t(String(a[0]).replace(":3766", ":8766"), ...a.slice(1)) });
  });
}
const page = await ctx.newPage();
const errors = [];
page.on("pageerror", (e) => errors.push(e.message));
const cdp = await ctx.newCDPSession(page);
const frames = [];
let t0 = null;
cdp.on("Page.screencastFrame", async (f) => {
  const t = f.metadata.timestamp;
  if (t0 === null) t0 = t;
  const file = `${FRAMES}/${String(frames.length).padStart(5, "0")}.jpg`;
  writeFileSync(file, Buffer.from(f.data, "base64"));
  frames.push({ file, t: t - t0 });
  await cdp.send("Page.screencastFrameAck", { sessionId: f.sessionId }).catch(() => {});
});
const marks = {};
// Wall-clock marks on the screencast's clock: frames stop while the page is still, so a frame's time can be stale.
const mark = (name) => {
  marks[name] = t0 === null ? 0 : Date.now() / 1000 - t0;
  console.log("mark", name, marks[name].toFixed(2));
};
const wait = (ms) => page.waitForTimeout(ms);

/** Page has no loading placeholders left. */
async function settled(extra = 500) {
  await page.waitForLoadState("networkidle", { timeout: 10_000 }).catch(() => undefined);
  await page.waitForFunction(() => !document.querySelector('[role="status"][aria-label^="Loading"]'), null, { timeout: 30_000 }).catch(() => undefined);
  await wait(extra);
}

/** A visible cursor with a soft orange halo and a ripple on every click, drawn by the page so it records with it. */
async function cursor() {
  await page.addStyleTag({
    content: `#rec-cursor{position:fixed;left:0;top:0;width:22px;height:22px;margin:-11px 0 0 -11px;border-radius:50%;
      background:rgba(248,97,17,.28);box-shadow:0 0 0 2px rgba(248,97,17,.95),0 0 24px 6px rgba(248,97,17,.25);
      pointer-events:none;z-index:2147483647;transition:transform 120ms cubic-bezier(.16,1,.3,1)}
      #rec-cursor.down{transform:scale(.75)}
      .rec-ripple{position:fixed;width:16px;height:16px;margin:-8px 0 0 -8px;border-radius:50%;border:2px solid rgba(248,97,17,.95);
      pointer-events:none;z-index:2147483646;animation:rec-ripple 600ms cubic-bezier(.16,1,.3,1) forwards}
      @keyframes rec-ripple{to{transform:scale(4);opacity:0}}
      nextjs-portal{display:none!important}`,
  });
  await page.evaluate(() => {
    const dot = Object.assign(document.createElement("div"), { id: "rec-cursor" });
    document.body.append(dot);
    addEventListener("mousemove", (e) => (dot.style.translate = `${e.clientX}px ${e.clientY}px`), true);
    addEventListener(
      "mousedown",
      (e) => {
        dot.classList.add("down");
        const r = Object.assign(document.createElement("div"), { className: "rec-ripple" });
        r.style.left = `${e.clientX}px`;
        r.style.top = `${e.clientY}px`;
        document.body.append(r);
        setTimeout(() => r.remove(), 700);
      },
      true,
    );
    addEventListener("mouseup", () => dot.classList.remove("down"), true);
  });
}

let mouse = { x: 768, y: 600 };
async function moveTo(to, steps = 24) {
  for (let i = 1; i <= steps; i++) {
    const k = 1 - Math.pow(1 - i / steps, 3);
    await page.mouse.move(mouse.x + (to.x - mouse.x) * k, mouse.y + (to.y - mouse.y) * k);
    await wait(14);
  }
  mouse = to;
}
/** Glides the cursor to the middle of *locator*, eased, then clicks it. */
async function press(locator, { click = true } = {}) {
  await locator.scrollIntoViewIfNeeded();
  let box = await locator.boundingBox();
  for (let i = 0; i < 20; i++) {
    await wait(80);
    const next = await locator.boundingBox();
    if (next && box && Math.abs(next.y - box.y) < 0.5) break;
    box = next;
  }
  await moveTo({ x: box.x + box.width / 2, y: box.y + box.height / 2 });
  if (click) {
    await wait(120);
    await page.mouse.down();
    await wait(90);
    await page.mouse.up();
  }
}

/** Eased window scroll so *locator*'s top sits under the sticky header. */
async function scrollUnder(locator, gap = 14, ms = 900) {
  const y = await locator.first().evaluate((el, gap) => {
    const bar = document.querySelector("header")?.getBoundingClientRect().bottom ?? 0;
    return el.getBoundingClientRect().top + window.scrollY - bar - gap;
  }, gap);
  await page.evaluate(
    ([to, ms]) =>
      new Promise((done) => {
        const from = window.scrollY;
        const end = Math.max(0, Math.min(document.documentElement.scrollHeight - innerHeight, to));
        const start = performance.now();
        const step = (now) => {
          const k = Math.min(1, (now - start) / ms);
          window.scrollTo(0, from + (end - from) * (1 - Math.pow(1 - k, 3)));
          if (k < 1) requestAnimationFrame(step);
          else done();
        };
        requestAnimationFrame(step);
      }),
    [y, ms],
  );
  await wait(120);
}

async function begin() {
  await cdp.send("Page.startScreencast", { format: "jpeg", quality: 92, everyNthFrame: 1 });
  await wait(300);
}

async function viewerReady() {
  await page.locator("canvas").first().waitFor({ state: "visible", timeout: 30_000 }).catch(() => undefined);
  await wait(2200);
  const fit = page.getByRole("button", { name: "Fit to view" });
  if (await fit.count()) await fit.first().click();
  await wait(500);
}

const FLOWS = {
  // The screen learns its size from a card, then draws the mat at true scale.
  async calibrate() {
    await page.goto(`${SITE}/calibrate`);
    await settled();
    await cursor();
    await begin();
    mark("start");
    await wait(600);
    const slider = page.getByRole("slider").first();
    const box = await slider.boundingBox();
    await moveTo({ x: box.x + box.width * 0.5, y: box.y + box.height / 2 });
    await page.mouse.down();
    for (let i = 1; i <= 30; i++) {
      await page.mouse.move(box.x + box.width * (0.5 + 0.1 * Math.sin((i / 30) * Math.PI)), box.y + box.height / 2);
      await wait(35);
    }
    await page.mouse.up();
    mouse = { x: box.x + box.width * 0.5, y: box.y + box.height / 2 };
    await wait(3500);
    mark("save");
    await press(page.getByRole("button", { name: /Save calibration/ }));
    await wait(900);
    await page.goto(`${SITE}/mat`);
    await settled(900);
    mark("mat");
    await wait(4500);
    mark("end");
  },
  // The stored run, played back from its log.
  async replay() {
    await page.goto(`${SITE}/judges`);
    await settled();
    await cursor();
    const replay = page.locator("#replay");
    await scrollUnder(page.getByRole("heading", { name: "Watch a recorded run" }), 14, 1);
    await begin();
    mark("start");
    await press(page.getByRole("button", { name: /^Battery compartment cover/ }).first());
    await settled(400);
    const player = replay.locator("div.rounded-xl").filter({ has: page.getByRole("slider", { name: "Replay position" }) }).first();
    await scrollUnder(player, 8, 700);
    await press(player.getByRole("radio", { name: "2×" }).or(player.getByRole("button", { name: "2×" })).first());
    await wait(200);
    mark("play");
    await press(player.getByRole("button", { name: "Play" }));
    await moveTo({ x: 1500, y: 110 });
    const now = player.locator("div.min-h-10 p").first();
    const seen = new Set();
    const stages = [["measure", /^Measure in millimetres/], ["write", /^Write the CAD program/], ["compare", /^Compare model to photo/], ["fixing", /^Fix the differences/], ["done", /^Finished/]];
    const deadline = Date.now() + 150_000;
    while (Date.now() < deadline) {
      const text = (await now.textContent().catch(() => "")) ?? "";
      for (const [name, re] of stages) {
        if (re.test(text) && !seen.has(name)) {
          seen.add(name);
          mark(name);
        }
      }
      if (seen.has("done")) break;
      await wait(100);
    }
    await wait(3500);
    mark("end");
  },
  // Fail → fix strip, the overlay of each round, cost card, 3D model, export gate.
  async job() {
    await page.goto(`${SITE}/jobs/${RUN}`);
    await settled(800);
    await viewerReady();
    await cursor();
    await page.evaluate(() => window.scrollTo(0, 0));
    await begin();
    mark("start");
    await wait(1200);
    const strip = page.locator("section").filter({ has: page.locator("h2").filter({ hasText: /fail → fix history/i }) }).first();
    const rounds = strip.locator('ol[aria-label="Build rounds, oldest first"] button');
    mark("round1");
    await press(rounds.first());
    await settled(300);
    await scrollUnder(strip, 6);
    await wait(3500);
    mark("round2");
    await press(rounds.nth(1));
    await settled(300);
    await wait(3000);
    mark("round3");
    await press(rounds.nth(2));
    await settled(300);
    await wait(3000);
    await press(rounds.nth(2));
    await wait(300);
    await page.evaluate(() => window.scrollTo({ top: 0, behavior: "smooth" }));
    await wait(1000);
    mark("verified");
    await wait(600);
    await press(page.getByRole("button", { name: "Export" }).first());
    await wait(3500);
    await page.keyboard.press("Escape");
    await wait(300);
    const canvas = page.locator("canvas").first();
    await canvas.scrollIntoViewIfNeeded();
    await wait(500);
    const b = await canvas.boundingBox();
    await moveTo({ x: b.x + b.width * 0.35, y: b.y + b.height * 0.55 });
    mark("orbit");
    await page.mouse.down();
    for (let i = 1; i <= 90; i++) {
      await page.mouse.move(b.x + b.width * (0.35 + 0.4 * (i / 90)), b.y + b.height * (0.55 - 0.06 * Math.sin((i / 90) * Math.PI)));
      await wait(30);
    }
    await page.mouse.up();
    mouse = { x: b.x + b.width * 0.75, y: b.y + b.height * 0.55 };
    await wait(600);
    mark("cost");
    const bop = page.locator(`section[aria-labelledby="bop-${RUN}"]`);
    await scrollUnder(bop, 10, 1100);
    await wait(500);
    await press(bop.getByText("PLA", { exact: true }).first(), { click: false });
    await wait(6000);
    mark("end");
  },
  // A scripted model claims VERIFIED; the verifier measures it; the export is blocked.
  async lie() {
    await page.goto(`${SITE}/judges`);
    await settled();
    await cursor();
    const lie = page.locator("#lie-caught");
    await scrollUnder(lie, 14, 1);
    await begin();
    mark("start");
    await wait(4000);
    mark("blocked");
    const note = lie.getByText(/^Export blocked:/).first();
    const y = await note.evaluate((el) => el.getBoundingClientRect().top + scrollY);
    await page.evaluate((y) => window.scrollTo({ top: y - 420, behavior: "smooth" }), y);
    await wait(900);
    await press(note, { click: false });
    await wait(9000);
    mark("end");
  },
  // Every part is a program with knobs: drag one, the code and the model change.
  async knobs() {
    await page.goto(`${SITE}/playground`);
    await settled();
    await cursor();
    await begin();
    mark("start");
    await wait(500);
    await press(page.getByRole("link", { name: /Battery compartment cover/ }).or(page.getByRole("button", { name: /Battery compartment cover/ })).first());
    await settled(1800);
    mark("open");
    const slider = page.getByRole("slider").first();
    await slider.scrollIntoViewIfNeeded();
    await wait(500);
    const box = await slider.boundingBox();
    await moveTo({ x: box.x + box.width * 0.45, y: box.y + box.height / 2 });
    await page.mouse.down();
    mark("drag");
    for (let i = 1; i <= 60; i++) {
      await page.mouse.move(box.x + box.width * (0.45 + 0.25 * Math.sin((i / 60) * Math.PI * 0.5)), box.y + box.height / 2);
      await wait(45);
    }
    await page.mouse.up();
    mouse = { x: box.x + box.width * 0.7, y: box.y + box.height / 2 };
    await wait(6000);
    mark("end");
  },
  // A live voice edit: the fake microphone plays a synthesised Hindi-English line; transcription and the knob change are live.
  async say() {
    await page.goto(`${SITE}/jobs/${RUN}`);
    await settled(800);
    await viewerReady();
    await cursor();
    const panel = page.getByTestId("live-voice");
    await scrollUnder(page.getByRole("heading", { name: "Edit by talking" }), 60, 1);
    await begin();
    mark("start");
    await wait(700);
    await press(panel.getByRole("button", { name: "Hands-free" }));
    await wait(500);
    mark("talk");
    await press(panel.getByRole("button", { name: /Start|Listen/i }).last());
    const applied = page.getByText(/^applied$/i).first();
    await applied.waitFor({ state: "visible", timeout: 45000 }).catch(() => undefined);
    mark("applied");
    await wait(1500);
    const stop = panel.getByRole("button", { name: "Stop listening" });
    if (await stop.count()) await press(stop);
    await wait(9000);
    console.log("applied:", /applied\s+\S+\s+[\d.]+\s*→\s*[\d.]+/.exec((await page.locator("body").innerText()).replace(/\s+/g, " "))?.[0]);
    mark("end");
  },
  // The labelled example of the 1:1 outline.
  async fit() {
    await page.goto(`${SITE}/jobs/${RUN}/fit?example=1`);
    await settled(1000);
    await cursor();
    await begin();
    mark("start");
    await wait(7000);
    mark("end");
  },
  // The review desk on the scripted test chain, then the log of what got fixed.
  async review() {
    await page.goto(`${SITE}/review`);
    await settled(1200);
    await cursor();
    await begin();
    mark("start");
    await wait(4000);
    await page.evaluate(() => window.scrollBy({ top: 620, behavior: "smooth" }));
    await wait(5000);
    mark("log");
    await page.goto(`${SITE}/review/log`);
    await settled(900);
    await wait(6000);
    mark("end");
  },
  // Registry, one part's proof, then the agents' page.
  async registry() {
    await page.goto(`${SITE}/parts`);
    await settled(1000);
    await cursor();
    await begin();
    mark("start");
    await wait(2500);
    mark("part");
    await page.goto(`${SITE}/parts/battery-cover-45mm`);
    await settled(1500);
    await wait(3500);
    mark("agents");
    await page.goto(`${SITE}/agents`);
    await settled(700);
    await scrollUnder(page.locator("h2").filter({ hasText: /^Connect over MCP/ }).first(), 14, 1000);
    await wait(5000);
    mark("end");
  },
};

/** A drawn scene: graphics.html or three.html, started on its clock and recorded for the scene's exact length. */
async function drawn(name) {
  const tl = JSON.parse(readFileSync(`${WORK}/build/timeline.json`, "utf8"));
  const s = tl.scenes.find((x) => x.name === name);
  if (!s) throw new Error(`no scene ${name}`);
  const facts = JSON.parse(readFileSync(`${WORK}/build/facts.json`, "utf8"));
  const words = JSON.parse(readFileSync(`${WORK}/audio/words.json`, "utf8"));
  const lines = Object.fromEntries(s.lines.map((l) => [l.id, { start: l.start, dur: l.dur, caption: l.caption, words: words[l.id] }]));
  if (s.visual[1] === "three") {
    const q = new URLSearchParams({ dur: String(s.dur), cues: JSON.stringify(s.cues), err: facts.run.errors.join(",") });
    await page.goto(`${pathToFileURL(path.join(ROOT, "video/three.html"))}?${q}`);
    await page.waitForFunction(() => window.__ready === true, null, { timeout: 60_000 });
  } else {
    const q = new URLSearchParams({ scene: name, dur: String(s.dur), lines: JSON.stringify(lines), facts: JSON.stringify(facts), stills: `file://${WORK}/stills` });
    await page.goto(`${pathToFileURL(path.join(ROOT, "video/graphics.html"))}#${q}`);
    await page.waitForFunction(() => window.__ready === true, null, { timeout: 60_000 });
  }
  await begin();
  mark("start");
  await page.evaluate(() => window.__start());
  await wait(s.dur * 1000 + 300);
  mark("end");
}

if (DRAWN) await drawn(FLOW.slice(4));
else await FLOWS[FLOW]();
await cdp.send("Page.stopScreencast").catch(() => {});
await wait(200);
if (errors.length) console.log("page errors:", errors.slice(0, 5));
const end = marks.end ?? Date.now() / 1000 - t0;
frames.sort((a, b) => a.t - b.t);
const list = frames.map((f, i) => `file '${f.file}'\nduration ${Math.max(0.001, (frames[i + 1]?.t ?? end) - f.t).toFixed(4)}`).join("\n");
writeFileSync(`${FRAMES}/list.txt`, `${list}\nfile '${frames.at(-1).file}'\n`);
const enc = spawnSync("ffmpeg", ["-loglevel", "error", "-y", "-f", "concat", "-safe", "0", "-i", `${FRAMES}/list.txt`, "-vf", "scale=1920:1080:flags=lanczos,fps=30,format=yuv420p", "-c:v", "libx264", "-crf", "16", "-preset", "fast", `${OUT}/${FLOW}.mp4`], { stdio: "inherit" });
if (enc.status !== 0) throw new Error("encode failed; frames kept in " + FRAMES);
rmSync(FRAMES, { recursive: true, force: true });
writeFileSync(`${OUT}/${FLOW}.marks.json`, JSON.stringify(marks, null, 1));
await browser.close();
console.log("wrote", `${OUT}/${FLOW}.mp4`, end.toFixed(1), "s");
