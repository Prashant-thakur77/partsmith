#!/usr/bin/env node
/**
 * README flowcharts, hand-drawn: docs/diagrams/<name>.excalidraw (open and edit at excalidraw.com) and docs/media/flow-<name>.png.
 * Each diagram below is plain data: nodes on a grid, edges between them. The Excalidraw library renders it in a headless browser.
 *
 *   node apps/web/scripts/diagrams.mjs   (make diagrams)
 */
import { chromium } from "@playwright/test";
import { mkdirSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const REPO = resolve(dirname(fileURLToPath(import.meta.url)), "../../..");
const SRC = join(REPO, "docs/diagrams");
const OUT = join(REPO, "docs/media");
const UTILS = "https://unpkg.com/@excalidraw/utils@0.1.2/dist/excalidraw-utils.min.js";
const FONT = "https://unpkg.com/@excalidraw/excalidraw@0.17.6/dist/excalidraw-assets/Virgil.woff2";

// Meaning of a colour, the same in every diagram.
const KIND = {
  input: { fill: "#fff3bf" }, // what a person brings or does
  person: { fill: "#b2f2bb" }, // a person decides
  model: { fill: "#ffd8a8" }, // a Meta model proposes
  code: { fill: "#a5d8ff" }, // plain code decides
  good: { fill: "#8ce99a" }, // the good outcome
  warn: { fill: "#ffec99" }, // allowed, with a warning
  bad: { fill: "#ffc9c9" }, // stopped
  store: { fill: "#e9ecef" }, // files and data
  note: { fill: "transparent" },
};
const LEGEND = [["model", "Meta model proposes"], ["code", "Plain code decides"], ["person", "A person decides"], ["store", "Files and data"]];

const FONT_SIZE = 22;
const CHAR = 0.56; // average glyph width of the hand-drawn font, in font sizes
const LINE = 1.25;

let seed = 1000;
function base(id, type, x, y, width, height, extra = {}) {
  seed += 7;
  return {
    id, type, x, y, width, height, angle: 0, strokeColor: "#1e1e1e", backgroundColor: "transparent", fillStyle: "solid", strokeWidth: 2,
    strokeStyle: "solid", roughness: 1, opacity: 100, groupIds: [], frameId: null, roundness: type === "rectangle" ? { type: 3 } : null,
    seed, version: 1, versionNonce: seed * 3, isDeleted: false, boundElements: [], updated: 1793000000000, link: null, locked: false, ...extra,
  };
}
function textEl(id, text, x, y, size, extra = {}) {
  const lines = text.split("\n");
  const width = Math.max(...lines.map((l) => l.length)) * size * CHAR;
  const height = lines.length * size * LINE;
  return base(id, "text", x, y, width, height, {
    text, originalText: text, fontSize: size, fontFamily: 1, textAlign: "center", verticalAlign: "middle", containerId: null, lineHeight: LINE,
    baseline: Math.round(height - size * 0.3), roundness: null, ...extra,
  });
}

/** Where the straight line from the box centre towards (tx, ty) leaves the box. */
function edgePoint(b, tx, ty, pad = 8) {
  const cx = b.x + b.width / 2;
  const cy = b.y + b.height / 2;
  const dx = tx - cx;
  const dy = ty - cy;
  if (dx === 0 && dy === 0) return [cx, cy];
  const halfW = b.width / 2 + pad;
  const halfH = b.height / 2 + pad;
  const k = b.type === "diamond" ? 1 / (Math.abs(dx) / halfW + Math.abs(dy) / halfH) : Math.min(halfW / Math.abs(dx || 1e-6), halfH / Math.abs(dy || 1e-6));
  return [cx + dx * k, cy + dy * k];
}

function build({ nodes, edges, colW = 360, rowH = 170, legend = true, title }) {
  seed = 1000;
  const els = [];
  const boxes = {};
  for (const n of nodes) {
    const lines = n.text.split("\n");
    const tw = Math.max(...lines.map((l) => l.length)) * FONT_SIZE * CHAR;
    const th = lines.length * FONT_SIZE * LINE;
    const diamond = n.shape === "diamond";
    const w = n.w ?? Math.max(tw + (diamond ? 150 : 44), diamond ? 280 : 170);
    const h = n.h ?? Math.max(th + (diamond ? 100 : 34), diamond ? 140 : 76);
    const x = n.col * colW - w / 2;
    const y = n.row * rowH - h / 2;
    const box = base(n.id, diamond ? "diamond" : n.shape === "ellipse" ? "ellipse" : "rectangle", x, y, w, h, {
      backgroundColor: KIND[n.kind ?? "code"].fill, roundness: diamond || n.shape === "ellipse" ? { type: 2 } : { type: 3 },
    });
    if (n.kind === "note") box.strokeStyle = "dashed";
    const label = textEl(`${n.id}-t`, n.text, x + (w - tw) / 2, y + (h - th) / 2, FONT_SIZE, { containerId: n.id });
    box.boundElements.push({ type: "text", id: label.id });
    boxes[n.id] = box;
    els.push(box, label);
  }
  edges.forEach((e, i) => {
    const a = boxes[e.from];
    const b = boxes[e.to];
    if (!a || !b) throw new Error(`edge ${e.from} -> ${e.to}`);
    const via = e.via ? e.via.map(([c, r]) => [c * colW, r * rowH]) : [];
    const ac = [a.x + a.width / 2, a.y + a.height / 2];
    const bc = [b.x + b.width / 2, b.y + b.height / 2];
    const first = via[0] ?? bc;
    const last = via.at(-1) ?? ac;
    const [sx, sy] = edgePoint(a, first[0], first[1]);
    const [tx, ty] = edgePoint(b, last[0], last[1]);
    const pts = [[sx, sy], ...via, [tx, ty]];
    const xs = pts.map((p) => p[0]);
    const ys = pts.map((p) => p[1]);
    const arrow = base(`e${i}`, "arrow", sx, sy, Math.max(...xs) - Math.min(...xs), Math.max(...ys) - Math.min(...ys), {
      points: pts.map(([x, y]) => [x - sx, y - sy]), lastCommittedPoint: null, startArrowhead: null, endArrowhead: "arrow",
      startBinding: { elementId: a.id, focus: 0, gap: 8 }, endBinding: { elementId: b.id, focus: 0, gap: 8 },
      strokeStyle: e.dash ? "dashed" : "solid", roundness: via.length ? { type: 2 } : null, strokeColor: e.color ?? "#1e1e1e",
    });
    a.boundElements.push({ type: "arrow", id: arrow.id });
    b.boundElements.push({ type: "arrow", id: arrow.id });
    els.push(arrow);
    if (e.label) {
      const size = 18;
      const lines = e.label.split("\n");
      const w = Math.max(...lines.map((l) => l.length)) * size * CHAR;
      const h = lines.length * size * LINE;
      const mid = pts[Math.floor((pts.length - 1) / 2)];
      const nxt = pts[Math.floor((pts.length - 1) / 2) + 1];
      const f = e.at ?? 0.5;
      const lx = mid[0] + (nxt[0] - mid[0]) * f + (e.dx ?? 0);
      const ly = mid[1] + (nxt[1] - mid[1]) * f + (e.dy ?? 0);
      els.push(textEl(`e${i}-l`, e.label, lx - w / 2, ly - h / 2, size, { strokeColor: e.color ?? "#343a40" }));
    }
  });
  const minX = Math.min(...Object.values(boxes).map((b) => b.x));
  const minY = Math.min(...Object.values(boxes).map((b) => b.y));
  if (title) els.push(textEl("title", title, minX, minY - 92, 32, { textAlign: "left" }));
  if (legend) {
    const maxY = Math.max(...Object.values(boxes).map((b) => b.y + b.height));
    let x = minX;
    LEGEND.forEach(([k, label], i) => {
      els.push(base(`lg${i}`, "rectangle", x, maxY + 50, 34, 26, { backgroundColor: KIND[k].fill, roundness: { type: 3 } }));
      const t = textEl(`lgt${i}`, label, x + 44, maxY + 50, 20, { textAlign: "left" });
      els.push(t);
      x += 44 + t.width + 44;
    });
  }
  return els;
}

const DIAGRAMS = {
  pipeline: {
    title: "From a photo to a part you can print",
    colW: 650,
    rowH: 170,
    nodes: [
      { id: "photo", text: "Phone photo on the screen mat", kind: "input", col: 1, row: 0 },
      { id: "gate", text: "Capture gate\nmarkers, blur, tilt, glare", shape: "diamond", col: 1, row: 1 },
      { id: "retake", text: "Retake, with the reason\nin plain words", kind: "bad", col: 0, row: 1 },
      { id: "metro", text: "Marker scale + part mask become mm\nSAM 3.1 first, threshold fallback", col: 1, row: 2 },
      { id: "spark", text: "Muse Spark 1.3 names the part,\nfinds the break, points at holes", kind: "model", col: 1, row: 3 },
      { id: "wonder", text: "Muse Wonder:\ncited spec values", kind: "model", col: 0, row: 3 },
      { id: "build", text: "Muse Spark Open writes\na CadQuery program", kind: "model", col: 1, row: 4 },
      { id: "sandbox", text: "Sandbox runs it\nno network, limited resources", col: 1, row: 5 },
      { id: "verify", text: "Verifier compares\nmodel and photo", shape: "diamond", col: 1, row: 6.1 },
      { id: "voice", text: "Voice Transcribe:\nHindi and English edits", kind: "model", col: 2, row: 4 },
      { id: "fix", text: "Fix agent reads the gap\nand edits the program", kind: "model", col: 2, row: 5 },
      { id: "export", text: "Export gate\nevery download passes here", shape: "diamond", col: 1, row: 7.4 },
      { id: "stop", text: "No export", kind: "bad", col: 0, row: 7.4 },
      { id: "files", text: "STL, 3MF, STEP, part.py", kind: "good", col: 2, row: 7.4 },
      { id: "review", text: "Person reviews\naccept, improve, reject", kind: "person", col: 2, row: 6.2 },
      { id: "registry", text: "Open registry\nREST and MCP", kind: "store", col: 2, row: 8.5 },
    ],
    edges: [
      { from: "photo", to: "gate" },
      { from: "gate", to: "retake", label: "fails", dy: -20 },
      { from: "gate", to: "metro", label: "passes", dx: 50 },
      { from: "metro", to: "spark" },
      { from: "wonder", to: "spark", dash: true, label: "only cited values", dy: -20 },
      { from: "spark", to: "build" },
      { from: "build", to: "sandbox" },
      { from: "sandbox", to: "verify" },
      { from: "verify", to: "fix", label: "gap too large", dx: 44, dy: 42 },
      { from: "fix", to: "sandbox", label: "new round", dy: -20 },
      { from: "voice", to: "fix", dash: true, label: "clamped to each knob", dx: 112 },
      { from: "verify", to: "export", label: "verified, or best effort\nwhen rounds run out", dx: -128 },
      { from: "export", to: "files", label: "verified, or best effort\nafter your explicit OK", dy: -34 },
      { from: "export", to: "stop", label: "failed", dy: -20 },
      { from: "files", to: "review" },
      { from: "review", to: "fix", label: "improve,\nwith pins on the photo", dx: 120 },
      { from: "files", to: "registry", label: "published", dx: 56 },
    ],
  },
  person: {
    title: "What you actually do",
    colW: 490,
    rowH: 200,
    legend: false,
    nodes: [
      { id: "a", text: "1. Match a bank card\nonce on the screen", kind: "input", col: 0, row: 0 },
      { id: "b", text: "2. The screen draws\nthe mat at true size", kind: "code", col: 1, row: 0 },
      { id: "c", text: "3. Lay the part on it\nand take one photo", kind: "input", col: 2, row: 0 },
      { id: "d", text: "4. Bad photo? It says why\nand asks for a retake", kind: "code", col: 3, row: 0 },
      { id: "e", text: "5. Watch the outline,\nmillimetres and each round", kind: "code", col: 3, row: 1 },
      { id: "f", text: "6. Answer a question, only if\nthe photo can't tell", kind: "person", col: 2, row: 1 },
      { id: "g", text: "7. Verified, or best effort\nwith the reason named", kind: "good", col: 1, row: 1 },
      { id: "h", text: "8. Drag a knob,\nor say the change", kind: "person", col: 0, row: 1 },
      { id: "i", text: "9. Lay the real part on its\ntrue-size outline to check", kind: "person", col: 0, row: 2 },
      { id: "j", text: "10. Download STL, 3MF or STEP\nthrough the export gate", kind: "good", col: 1, row: 2 },
    ],
    edges: [
      { from: "a", to: "b" }, { from: "b", to: "c" }, { from: "c", to: "d" }, { from: "d", to: "e" }, { from: "e", to: "f" },
      { from: "f", to: "g" }, { from: "g", to: "h" }, { from: "h", to: "i" }, { from: "i", to: "j" },
    ],
  },
  loop: {
    title: "The agent loop: code decides which round counts",
    colW: 680,
    rowH: 180,
    nodes: [
      { id: "build", text: "Muse Spark Open writes the program\nfamily template or free code", kind: "model", col: 1, row: 0 },
      { id: "run", text: "Sandbox runs it", col: 1, row: 1 },
      { id: "verify", text: "Verifier compares it\nwith every photo", shape: "diamond", col: 1, row: 2.1 },
      { id: "done", text: "Verified", kind: "good", col: 2, row: 2.1 },
      { id: "best", text: "Best effort: keeps the best round,\nnames the check that failed", kind: "warn", col: 0, row: 2.1 },
      { id: "tools", text: "Fix agent uses the tools:\ninspect residuals, measure, segment,\nrender a candidate, run tests", kind: "model", col: 1, row: 3.4 },
      { id: "edit", text: "Commits a knob or code edit\nthis costs one round", kind: "model", col: 2, row: 3.4 },
      { id: "guard", text: "Guards\nedit caps, no uniform rescale,\nmeasured knobs stay pinned", shape: "diamond", col: 2, row: 4.9, w: 600, h: 230 },
    ],
    edges: [
      { from: "build", to: "run" },
      { from: "run", to: "verify" },
      { from: "verify", to: "done", label: "all limits met", dy: -20 },
      { from: "verify", to: "best", label: "six rounds used, or\ntwo with no progress", dy: -38 },
      { from: "verify", to: "tools", label: "gap too large", dx: 76 },
      { from: "tools", to: "edit" },
      { from: "edit", to: "guard" },
      { from: "guard", to: "tools", label: "refused", dx: -40, dy: 26, color: "#c92a2a" },
      { from: "guard", to: "run", label: "accepted", via: [[2.55, 3.4], [2.55, 1]], at: 0.4, dx: -56 },
    ],
  },
  architecture: {
    title: "How the system fits together",
    colW: 440,
    rowH: 150,
    nodes: [
      { id: "web", text: "Web app\nNext.js", kind: "input", col: 0, row: 0.6 },
      { id: "agents", text: "Coding agents", kind: "input", col: 0, row: 1.8 },
      { id: "api", text: "API\nFastAPI, REST + SSE", col: 1, row: 0.6 },
      { id: "mcp", text: "MCP server", col: 1, row: 1.8 },
      { id: "svc", text: "Job service", col: 2, row: 1.2 },
      { id: "review", text: "Review desk,\nadmin console", kind: "person", col: 2, row: 0 },
      { id: "orch", text: "Orchestrator\nand fix agent", col: 3, row: 1.2 },
      { id: "metro", text: "Metrology\nmarkers + mask = mm", col: 4, row: 0 },
      { id: "geom", text: "CAD sandbox", col: 4, row: 0.85 },
      { id: "ver", text: "Verifier", col: 4, row: 1.55 },
      { id: "prov", text: "Provider layer\nlogs tokens, time, cost;\ndaily spend cap", col: 4, row: 2.45 },
      { id: "meta", text: "Meta Model API\nSAM 3.1, Spark 1.3, Wonder,\nImage, Voice Transcribe", kind: "model", col: 3, row: 3.5 },
      { id: "open", text: "Open weights\nMuse Spark Open (Baseten)", kind: "model", col: 4, row: 3.7 },
      { id: "store", text: "Registry, blobs and run logs\nSQLite or Postgres", kind: "store", col: 1.5, row: 3.5 },
    ],
    edges: [
      { from: "web", to: "api" },
      { from: "agents", to: "mcp" },
      { from: "api", to: "svc" },
      { from: "mcp", to: "svc" },
      { from: "api", to: "review" },
      { from: "review", to: "svc", label: "improve:\na new round", dx: 72 },
      { from: "svc", to: "orch" },
      { from: "orch", to: "metro" },
      { from: "orch", to: "geom" },
      { from: "orch", to: "ver" },
      { from: "orch", to: "prov" },
      { from: "prov", to: "meta" },
      { from: "prov", to: "open" },
      { from: "svc", to: "store" },
    ],
  },
  gate: {
    title: "Verification and the export gate",
    colW: 520,
    rowH: 175,
    nodes: [
      { id: "model", text: "Model from the sandbox", kind: "code", col: 1, row: 0 },
      { id: "render", text: "Render it from each\nphoto's own camera", kind: "code", col: 1, row: 1 },
      { id: "m", text: "Measure model and photo\nwith the same code", kind: "code", col: 1, row: 2 },
      { id: "rule", text: "Required tests pass, outline\ngap and overlap in limits,\non every view?", shape: "diamond", col: 1, row: 3.25, w: 500, h: 200 },
      { id: "claim", text: "A model saying\n\"verified\"", kind: "bad", col: 0, row: 3.25 },
      { id: "b", text: "Best effort", kind: "warn", col: 1, row: 4.6 },
      { id: "v", text: "Verified", kind: "good", col: 2, row: 4.6 },
      { id: "f", text: "Failed", kind: "bad", col: 0, row: 4.6 },
      { id: "gate", text: "Export gate\none code path for every download", shape: "diamond", col: 1, row: 5.8, w: 560, h: 170 },
      { id: "dl", text: "Download", kind: "good", col: 2, row: 6.9 },
      { id: "no", text: "No download", kind: "bad", col: 0, row: 6.9 },
    ],
    edges: [
      { from: "model", to: "render" },
      { from: "render", to: "m" },
      { from: "m", to: "rule" },
      { from: "claim", to: "rule", dash: true, label: "ignored", dy: -20, color: "#c92a2a" },
      { from: "rule", to: "v", label: "yes", dx: 30, dy: -16 },
      { from: "rule", to: "b", label: "valid, but a\nlimit missed", dx: 78 },
      { from: "rule", to: "f", label: "no valid model", dx: -60, dy: -14 },
      { from: "v", to: "gate" },
      { from: "b", to: "gate" },
      { from: "f", to: "gate" },
      { from: "gate", to: "dl", label: "verified, or best effort\nwith your explicit OK", dx: 110, dy: -20 },
      { from: "gate", to: "no", label: "failed", dx: -40, dy: -16 },
    ],
  },
  data: {
    title: "What a job leaves behind",
    colW: 400,
    rowH: 165,
    legend: false,
    nodes: [
      { id: "photos", text: "Photos and clip", kind: "input", col: 0, row: 1 },
      { id: "blobs", text: "blobs/\nby sha256", kind: "store", col: 0, row: 2 },
      { id: "meas", text: "measurements.json\nmm, error, source of each value", kind: "store", col: 1, row: 1 },
      { id: "spec", text: "partspec.json", kind: "store", col: 2, row: 1 },
      { id: "part", text: "part.py\nPARAMS + build(p)", kind: "store", col: 3, row: 1 },
      { id: "files", text: "STL, 3MF, STEP", kind: "good", col: 4, row: 0.3 },
      { id: "vj", text: "verification.json\nwritten only by the verifier", kind: "code", col: 3.2, row: 2.1 },
      { id: "pub", text: "Registry record", kind: "good", col: 4, row: 1.2 },
      { id: "log", text: "run.jsonl: every stage,\ntool call and model call, with cost", kind: "store", col: 1.8, row: 2.6 },
      { id: "replay", text: "Replays on\n/judges and /jobs", kind: "input", col: 0.6, row: 3.2 },
    ],
    edges: [
      { from: "photos", to: "blobs" },
      { from: "photos", to: "meas" },
      { from: "meas", to: "spec" },
      { from: "spec", to: "part" },
      { from: "part", to: "files" },
      { from: "part", to: "vj" },
      { from: "vj", to: "pub" },
      { from: "files", to: "pub" },
      { from: "part", to: "log", dash: true },
      { from: "vj", to: "log", dash: true },
      { from: "log", to: "replay", dash: true },
    ],
  },
};

mkdirSync(SRC, { recursive: true });
const browser = await chromium.launch();
const page = await (await browser.newContext()).newPage();
await page.goto("about:blank");
await page.addStyleTag({ content: `@font-face{font-family:Virgil;src:url(${FONT}) format("woff2")}` });
await page.addScriptTag({ url: UTILS });
await page.evaluate(() => document.fonts.load('20px Virgil'));
for (const [name, d] of Object.entries(DIAGRAMS)) {
  const elements = build(d);
  const scene = { type: "excalidraw", version: 2, source: "partsmith", elements, appState: { viewBackgroundColor: "#ffffff", gridSize: null }, files: {} };
  writeFileSync(join(SRC, `${name}.excalidraw`), `${JSON.stringify(scene, null, 1)}\n`);
  const data = await page.evaluate(async ({ elements }) => {
    const blob = await window.ExcalidrawUtils.exportToBlob({
      elements, appState: { exportBackground: true, viewBackgroundColor: "#ffffff" }, files: {}, mimeType: "image/png", exportPadding: 30,
      getDimensions: (w, h) => ({ width: w * 2, height: h * 2, scale: 2 }),
    });
    const bytes = new Uint8Array(await blob.arrayBuffer());
    let s = "";
    for (const b of bytes) s += String.fromCharCode(b);
    return btoa(s);
  }, { elements });
  writeFileSync(join(OUT, `flow-${name}.png`), Buffer.from(data, "base64"));
  process.stdout.write(`wrote ${name}\n`);
}
await browser.close();
