/**
 * Test-only API fixtures shaped exactly like docs/API.md, served by Playwright route mocking.
 * All values are invented for UI tests and never ship (src/ must not import from e2e/).
 */
import { fileURLToPath as __f2p } from "node:url";
import { dirname as __dn } from "node:path";
const __dirname = __dn(__f2p(import.meta.url));
import { readFileSync } from "node:fs";
import { join } from "node:path";
import type { Page, Route } from "@playwright/test";

const GEN = join(__dirname, "generated");
const MATS = join(__dirname, "..", "..", "public", "mats");
type Tpl = { title: string; summary: string; tags: string[]; params: Record<string, unknown>[]; defaults: Record<string, number>; code: string };
const templates = JSON.parse(readFileSync(join(GEN, "templates.json"), "utf8")) as Record<string, Tpl>;
const lb = templates["l-bracket"]!;
const cc = templates["cable-clip"]!;

const A = "/api/v1/files";
const NOW = 1_793_100_000;

export const status = {
  mode: "mock",
  providers: [
    { stage: "measure", role: "Segmenter", provider: "meta", model: "sam-3.1", mode: "mock", key_env: "MODEL_API_KEY", key_present: false, open_weights: false, where: "Meta Model API", note: "MODEL_API_KEY missing → deterministic mock" },
    { stage: "understand", role: "Reader", provider: "meta", model: "muse-spark-1.3", mode: "mock", key_env: "MODEL_API_KEY", key_present: false, open_weights: false, where: "Meta Model API", note: "MODEL_API_KEY missing → deterministic mock" },
    { stage: "build", role: "Builder", provider: "baseten", model: "meta-models/muse-spark-open-1026", mode: "mock", key_env: "BASETEN_API_KEY", key_present: false, open_weights: true, where: "Baseten", note: "BASETEN_API_KEY missing → deterministic mock" },
    { stage: "judge", role: "Judge", provider: "llama.cpp", model: "muse-glimmer-30b-q4_k_m", mode: "mock", key_env: "GLIMMER_BASE_URL", key_present: false, open_weights: true, where: "Modal GPU", note: "GLIMMER_BASE_URL missing → deterministic mock" },
    { stage: "plan", role: "Planner", provider: "meta", model: "muse-wonder-1.0", mode: "mock", key_env: "MODEL_API_KEY", key_present: false, open_weights: false, where: "Meta Model API", note: "" },
    { stage: "voice", role: "Transcriber", provider: "meta", model: "muse-voice-transcribe-1.0", mode: "mock", key_env: "MODEL_API_KEY", key_present: false, open_weights: false, where: "Meta Model API", note: "" },
  ],
  warnings: ["No API keys configured: every model stage is a deterministic mock."],
  jobs: { total: 12, verified: 9 },
  cost: { usd_total: 0, usd_per_job_mean: 0, n_jobs: 12 },
};

export const stats = { parts: 14, verified: 11, synthetic: 9, real: 5, jobs: 12, grams_pla: 86.4 };

const verification = {
  verified: true,
  status: "verified",
  reasons: ["All silhouettes within 0.5 mm", "6 of 6 part tests passed"],
  thresholds: { hausdorff_mm: 0.5, iou: 0.97 },
  views: [{ view: "top", iou: 0.9874, hausdorff_mm: 0.31, hd95_mm: 0.22, mean_mm: 0.09, worst_point_mm: [12.1, -4.0], over_area_mm2: 1.2, under_area_mm2: 0.8 }],
  residuals: [
    { feature_id: "hole_1", quantity: "diameter", measured_mm: 4.52, model_mm: 4.5, delta_mm: -0.02, tol_mm: 0.15, passed: true },
    { feature_id: "outline", quantity: "length", measured_mm: 40.12, model_mm: 40.0, delta_mm: -0.12, tol_mm: 0.3, passed: true },
    { feature_id: "outline", quantity: "width", measured_mm: 19.94, model_mm: 20.0, delta_mm: 0.06, tol_mm: 0.3, passed: true },
    { feature_id: "hole_1", quantity: "center_x", measured_mm: -9.81, model_mm: -10.0, delta_mm: -0.19, tol_mm: 0.15, passed: false },
  ],
  tests: [
    { id: "t1", description: "hole_1 Ø == 4.50 ± 0.15", value: 4.5, expected: 4.52, tol: 0.15, passed: true, priority: "P0" },
    { id: "t2", description: "bbox.x == 40.0 ± 0.3", value: 40.0, expected: 40.12, tol: 0.3, passed: true, priority: "P0" },
    { id: "t3", description: "single watertight solid", value: null, expected: null, tol: null, passed: true, priority: "P0" },
  ],
  validity: { is_valid: true, single_solid: true, watertight: true, volume_mm3: 5120.4, bbox_mm: [40, 20, 30], min_wall_mm: 2.8, issues: [] },
  vetoes: [],
  max_error_mm: 0.31,
  origin: "synthetic",
  versions: { verifier: "0.1.0" },
  hashes: { code: "sha256:ab12cd34ef56" },
  ms: 412,
};

const facts = { bbox_mm: [40, 20, 30], volume_mm3: 5120.4, mass_g_pla: 6.35, mass_g_petg: 6.5, print_minutes_est: 38, supports_needed: false, orientation: "base leg down" };

export const partCards = [
  { slug: "l-bracket", title: lb.title, family: "bracket", status: "verified", origin: "synthetic", max_error_mm: 0.31, thumbnail_url: `${A}/thumb.png`, params_count: lb.params.length, topology_knobs: ["base_holes", "wall_holes", "gusset_count"] },
  { slug: "cable-clip", title: cc.title, family: "cable_clip", status: "verified", origin: "real", max_error_mm: 0.42, thumbnail_url: null, params_count: cc.params.length, topology_knobs: [] },
  { slug: "cupboard-latch", title: "Cupboard latch", family: "latch", status: "best_effort", origin: "real", max_error_mm: 0.83, thumbnail_url: `${A}/thumb.png`, params_count: 7, topology_knobs: [] },
  { slug: "caster-wheel-32", title: "Caster wheel 32 mm", family: "wheel", status: "verified", origin: "reference_object", max_error_mm: 0.27, thumbnail_url: `${A}/thumb.png`, params_count: 6, topology_knobs: ["spoke_count"] },
];

function partRecord(slug: string) {
  const t = slug === "cable-clip" ? cc : lb;
  const card = partCards.find((c) => c.slug === slug) ?? partCards[0]!;
  return {
    id: `part_${slug}`,
    slug,
    title: t.title,
    family: card.family,
    summary: t.summary,
    tags: t.tags,
    version: 2,
    status: card.status,
    params: t.params,
    defaults: t.defaults,
    code: t.code,
    code_sha: "sha256:9f2c1a7be0d4c3e1",
    verification: { ...verification, origin: card.origin },
    provenance: { origin: card.origin, job_id: "job_demo_1", photo_shas: ["sha256:5be1c0ffee"], builder_model: "meta-models/muse-spark-open-1026", provider_mode: "mock", created_by: "partsmith", forked_from: null, note: "" },
    facts,
    licence: "CC-BY-4.0",
    created_at: NOW - 3600 * 5,
    mating: [],
    artifacts: { view: `${A}/view-${slug === "cable-clip" ? "cable-clip" : "l-bracket"}.json`, verification: `${A}/verification.json`, glb: `${A}/part.glb` },
    lineage: [{ slug, version: 1, note: "first verified build", created_at: NOW - 86400 }],
  };
}

export function bakeResult(slug: string, params: Record<string, number>, cacheHit = false) {
  return {
    cache_key: "k_" + Object.values(params).join("_"),
    part_slug: slug,
    version: 2,
    params,
    clamped: {},
    artifacts: { view: `${A}/view-l-bracket-variant.json`, stl: `${A}/part.stl` },
    facts: { ...facts, mass_g_pla: 8.1 },
    cache_hit: cacheHit,
    ms: cacheHit ? 3 : 640,
  };
}

const jobSummary = {
  id: "job_demo_1",
  kind: "fix",
  status: "done",
  created_at: NOW - 600,
  updated_at: NOW - 400,
  title: "L-bracket (synthetic sample)",
  origin: "synthetic",
  provider_mode: "mock",
  verified: true,
  max_error_mm: 0.31,
  iterations: 3,
  cost_usd: 0,
  part_slug: "l-bracket",
  is_replay: false,
};

let seq = 0;
const ev = (e: Record<string, unknown>) => ({ job: "job_demo_1", seq: seq++, ts: NOW - 600 + seq * 2, ctx: "c1", ...e });
const call = (stage: string, model: string, provider = "meta") => ev({ t: "model_call", provider, model, stage, mode: "mock", tokens_in: 1840, tokens_out: 420, ms: 12, usd: 0, ok: true });
const art = (kind: string, file: string, iter?: number) => ev({ t: "artifact", kind, sha: `sha_${kind}`, url: `${A}/${file}`, iter: iter ?? null, label: "" });

export const jobEvents = [
  ev({ t: "stage", stage: "capture", status: "start", label: "" }),
  art("photo", "photo.png"),
  ev({ t: "stage", stage: "capture", status: "ok", ms: 180, label: "21 of 24 markers found · sharp · tilt 3°" }),
  ev({ t: "stage", stage: "measure", status: "start", label: "" }),
  call("measure", "sam-3.1"),
  art("mask_overlay", "mask.png"),
  art("measure_overlay", "measure.png"),
  ev({ t: "stage", stage: "measure", status: "ok", ms: 920, label: "40.12 × 19.94 mm, 2 holes" }),
  ev({ t: "stage", stage: "understand", status: "start" }),
  call("understand", "muse-spark-1.3"),
  ev({ t: "stage", stage: "understand", status: "ok", ms: 1300, label: "L-bracket, two screw holes in each leg" }),
  ev({ t: "stage", stage: "build", status: "start" }),
  call("build", "meta-models/muse-spark-open-1026", "baseten"),
  ev({ t: "stage", stage: "build", status: "ok", ms: 2100, label: "template: l_bracket" }),
  ev({ t: "stage", stage: "execute", status: "ok", ms: 640, label: "sandbox ok" }),
  ev({ t: "iteration", iter: 1, strategy: "template", edits: [{ param: "length", to: 38 }], analysis: "Initial fit from template defaults.", diff: "", hausdorff_mm: 1.84, iou: 0.912, passed_tests: 3, total_tests: 6 }),
  ev({ t: "metric", iter: 1, name: "hausdorff_mm", value: 1.84, threshold: 0.5, unit: "mm" }),
  ev({ t: "stage", stage: "fix", status: "ok", ms: 800, label: "length +2.1 mm, hole_d +0.3 mm", iter: 2 }),
  ev({ t: "iteration", iter: 2, strategy: "template", edits: [{ param: "length", from: 38, to: 40.1 }], analysis: "Base leg was 2.1 mm short; holes slightly small.", diff: "--- a/part.py\n+++ b/part.py\n@@ -21,3 +21,3 @@\n-    \"length\": (38.0, 18.0, 120.0, 0.1, \"mm\", True, \"Base leg length\"),\n+    \"length\": (40.1, 18.0, 120.0, 0.1, \"mm\", True, \"Base leg length\"),\n", hausdorff_mm: 0.71, iou: 0.958, passed_tests: 5, total_tests: 6 }),
  ev({ t: "metric", iter: 2, name: "hausdorff_mm", value: 0.71, threshold: 0.5, unit: "mm" }),
  ev({ t: "iteration", iter: 3, strategy: "template", edits: [{ param: "hole_d", from: 4.2, to: 4.5 }], analysis: "Hole diameter matched to the measured 4.52 mm.", diff: "--- a/part.py\n+++ b/part.py\n@@ -25,1 +25,1 @@\n-    \"hole_d\": (4.2, 2.5, 7.0, 0.05, \"mm\", True, \"Screw hole diameter\"),\n+    \"hole_d\": (4.5, 2.5, 7.0, 0.05, \"mm\", True, \"Screw hole diameter\"),\n", hausdorff_mm: 0.31, iou: 0.9874, passed_tests: 6, total_tests: 6 }),
  ev({ t: "metric", iter: 3, name: "hausdorff_mm", value: 0.31, threshold: 0.5, unit: "mm" }),
  art("render_overlay", "render.png", 3),
  art("residual_heatmap", "heatmap.png", 3),
  art("view", "view-l-bracket.json", 3),
  ev({ t: "stage", stage: "verify", status: "ok", ms: 410, label: "0.31 mm max error · 6/6 tests", iter: 3 }),
  ev({ t: "stage", stage: "judge", status: "ok", ms: 900, label: "no vetoes" }),
  call("judge", "muse-glimmer-30b-q4_k_m", "llama.cpp"),
  ev({ t: "stage", stage: "package", status: "ok", ms: 300, label: "STL, 3MF, STEP, part.py" }),
  art("stl", "part.stl"),
  art("step", "part.step"),
  art("code", "part.py"),
  art("verification", "verification.json"),
  ev({ t: "done", verified: true, status: "verified", summary: { max_error_mm: 0.31 } }),
];

export const jobDetail = {
  summary: jobSummary,
  events: [],
  partspec: {
    family: "bracket",
    units: "mm",
    title: "L-bracket",
    base_profile: { kind: "polyline", points_mm: [[-20, -10], [20, -10], [20, 10], [-20, 10]], source: "measured", sigma_mm: 0.05 },
    thickness: { value: 3, source: "user_stated", sigma_mm: 0 },
    features: [
      { kind: "through_hole", id: "hole_1", center_mm: [-10, 0], diameter: { value: 4.52, source: "measured", sigma_mm: 0.04 } },
      { kind: "through_hole", id: "hole_2", center_mm: [10, 0], diameter: { value: 4.49, source: "measured", sigma_mm: 0.04 } },
    ],
    broken_region: null,
    unknowns: [],
    intent: "Same size, a bit stronger.",
    refusal: null,
  },
  measurements: {
    top: {
      view: "top",
      origin: "synthetic",
      outline_mm: [[-20, -10], [20, -10], [20, 10], [-20, 10]],
      holes: [
        { id: "hole_1", center_mm: [-10, 0], diameter: { value: 4.52, source: "measured", sigma_mm: 0.04 }, roundness_mm: 0.02 },
        { id: "hole_2", center_mm: [10, 0], diameter: { value: 4.49, source: "measured", sigma_mm: 0.04 }, roundness_mm: 0.03 },
      ],
      slots: [],
      length: { value: 40.12, source: "measured", sigma_mm: 0.06 },
      width: { value: 19.94, source: "measured", sigma_mm: 0.06 },
      thickness: { value: 3, source: "user_stated", sigma_mm: 0 },
      area_mm2: 768.2,
      mask_source: "synthetic-gt",
      notes: [],
    },
  },
  verification,
  code: lb.code,
  params: lb.params,
  values: lb.defaults,
  artifacts: { photo: `${A}/photo.png`, view: `${A}/view-l-bracket.json`, stl: `${A}/part.stl`, threemf: `${A}/part.3mf`, step: `${A}/part.step`, code: `${A}/part.py`, verification: `${A}/verification.json` },
  question: null,
};

export const pausedDetail = {
  ...jobDetail,
  summary: { ...jobSummary, id: "job_paused", status: "waiting_for_answer", verified: false, max_error_mm: null, part_slug: null, title: "Mixer knob" },
  verification: null,
  params: [],
  values: {},
  code: null,
  artifacts: { photo: `${A}/photo.png` },
};

export const pausedEvents = [
  { job: "job_paused", seq: 0, ts: NOW, ctx: "", t: "stage", stage: "capture", status: "ok", ms: 150, label: "markers found" },
  { job: "job_paused", seq: 1, ts: NOW + 1, ctx: "", t: "stage", stage: "measure", status: "ok", ms: 800, label: "Ø 34.8 mm" },
  { job: "job_paused", seq: 2, ts: NOW + 2, ctx: "", t: "stage", stage: "ask", status: "start", label: "one hidden size" },
  { job: "job_paused", seq: 3, ts: NOW + 3, ctx: "", t: "question", id: "q_depth", text: "How deep is the D-shaft hole? A rough number is fine.", expects: "number_mm", default: 12, choices: null },
];

export const replays = [
  { id: "job_demo_1", title: "L-bracket (synthetic sample)", origin: "synthetic", provider_mode: "mock", verified: true, max_error_mm: 0.31, iterations: 3 },
];

export const bench = {
  generated_at: "2026-10-27T10:00:00Z",
  git_sha: "a1b2c3d4e5f6",
  tables: {
    synthetic: {
      title: "Synthetic photos",
      n: 40,
      ground_truth: "synthetic_exact",
      ci: "95 % bootstrap",
      columns: ["family", "n", "median_abs_err_mm", "p95_err_mm", "verified_rate"],
      rows: [
        { family: "bracket", n: 10, median_abs_err_mm: 0.11, p95_err_mm: 0.32, verified_rate: 0.9 },
        { family: "clip", n: 10, median_abs_err_mm: 0.14, p95_err_mm: 0.41, verified_rate: 0.8 },
      ],
      median_abs_err_mm: 0.12,
    },
    reference_objects: null,
    real_ruler: null,
  },
  failures: [{ id: "f1", title: "Glossy black clip", reason: "Glare hid the left edge; capture gate should have caught it.", overlay_url: `${A}/heatmap.png` }],
};

export const families = [
  { family: "bracket", title: "Brackets", count: 4, verified: 3 },
  { family: "cable_clip", title: "Cable clips", count: 3, verified: 3 },
  { family: "latch", title: "Latches", count: 2, verified: 1 },
  { family: "wheel", title: "Wheels", count: 5, verified: 4 },
];

export const steerRun = {
  id: "steer_1",
  brief: "Cupboard hardware kit, 4 mm grid",
  plan: [
    { slug: "kit-latch", title: "Cupboard latch", family: "latch", params: { width: 12 } },
    { slug: "kit-shelf-pin", title: "Shelf support pin", family: "spacer", params: { diameter: 5 } },
    { slug: "kit-hinge-pin", title: "Hinge pin", family: "hinge", params: { length: 30 } },
  ],
  lanes: [
    { slug: "kit-latch", status: "verified", job_id: "job_demo_1", verified: true, max_error_mm: 0.21 },
    { slug: "kit-shelf-pin", status: "verified", job_id: null, verified: true, max_error_mm: 0.18 },
    { slug: "kit-hinge-pin", status: "best_effort", job_id: null, verified: false, max_error_mm: 0.66 },
  ],
  queue: [
    { slug: "kit-latch", title: "Cupboard latch", verified: true, max_error_mm: 0.21, judge: "ok", job_id: "job_demo_1" },
    { slug: "kit-hinge-pin", title: "Hinge pin", verified: false, max_error_mm: 0.66, judge: "pin head too thin" },
  ],
};

export const fitOutline = {
  mat_id: "screen-m",
  outline_mm: [[85, 55], [125, 55], [125, 75], [85, 75]],
  holes: [{ center_mm: [95, 65], diameter_mm: 4.5 }, { center_mm: [115, 65], diameter_mm: 4.5 }],
  dims: [{ label: "L", from_mm: [85, 80], to_mm: [125, 80], value_mm: 40 }],
  placement: { cx_mm: 105, cy_mm: 65, theta_deg: 0 },
};

export const captureOk = {
  passed: true,
  retake_reason: null,
  checks: [
    { name: "markers", passed: true, severity: "ok", value: 21, threshold: 4, reason: "21 markers found" },
    { name: "blur", passed: true, severity: "ok", value: 180, threshold: 60, reason: "Sharp" },
    { name: "tilt", passed: true, severity: "ok", value: 3.1, threshold: 12, reason: "Camera tilt 3°" },
    { name: "glare", passed: true, severity: "warn", value: 0.04, threshold: 0.05, reason: "A little glare near the top edge" },
  ],
};

function sse(events: unknown[]): string {
  return events.map((e) => `id: ${(e as { seq: number }).seq}\ndata: ${JSON.stringify(e)}\n\n`).join("");
}

const json = (route: Route, body: unknown, status = 200) => route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });

export type MockOptions = { offline?: boolean; emptyRegistry?: boolean; noBench?: boolean };

/** Route every `/api/v1/*` call to fixtures. Returns a log of requested paths for assertions. */
export async function mockApi(page: Page, opts: MockOptions = {}): Promise<string[]> {
  const log: string[] = [];
  await page.route("**/api/v1/**", async (route) => {
    const url = new URL(route.request().url());
    const path = url.pathname.replace(/^\/api\/v1/, "");
    const method = route.request().method();
    log.push(`${method} ${path}${url.search}`);
    if (opts.offline) return route.fulfill({ status: 502, body: "" });

    if (path.startsWith("/files/")) {
      const name = path.slice("/files/".length);
      if (name.endsWith(".json") && name.startsWith("view-")) return route.fulfill({ status: 200, contentType: "application/json", body: readFileSync(join(GEN, name)) });
      if (name.endsWith(".png")) return route.fulfill({ status: 200, contentType: "image/png", body: readFileSync(join(GEN, name)) });
      if (name === "verification.json") return json(route, verification);
      return route.fulfill({ status: 200, contentType: "application/octet-stream", body: "fixture" });
    }
    if (path === "/openapi.json") return json(route, { openapi: "3.1.0", info: { title: "PartSmith", version: "0.1.0" }, paths: {} });
    if (path === "/health") return json(route, { ok: true, version: "0.1.0" });
    if (path === "/status") return json(route, status);
    if (path === "/stats") return json(route, stats);
    if (path === "/families") return json(route, families);
    if (path === "/mats") {
      const index = JSON.parse(readFileSync(join(MATS, "index.json"), "utf8")) as { mat_id: string }[];
      return json(route, index.map((m) => JSON.parse(readFileSync(join(MATS, `${m.mat_id}.json`), "utf8"))));
    }
    if (path === "/parts") {
      if (opts.emptyRegistry) return json(route, { items: [], next_cursor: null, total: 0 });
      const q = url.searchParams.get("q");
      const fam = url.searchParams.get("family");
      let items = partCards;
      if (q) items = items.filter((p) => p.title.toLowerCase().includes(q.toLowerCase()));
      if (fam) items = items.filter((p) => p.family === fam);
      if (url.searchParams.get("verified") === "true") items = items.filter((p) => p.status === "verified");
      return json(route, { items, next_cursor: null, total: items.length });
    }
    const part = path.match(/^\/parts\/([^/]+)(\/[a-z.]+)?$/);
    if (part) {
      const slug = decodeURIComponent(part[1]!);
      const sub = part[2];
      if (!sub) {
        if (!partCards.some((c) => c.slug === slug)) return json(route, { error: { code: "not_found", message: `no part ${slug}`, closest_matches: ["l-bracket"] } }, 404);
        return json(route, partRecord(slug));
      }
      if (sub === "/bake") {
        const params: Record<string, number> = {};
        url.searchParams.forEach((v, k) => {
          if (k !== "format" && k !== "download") params[k] = Number(v);
        });
        return json(route, bakeResult(slug, params));
      }
      if (sub === "/matching") return json(route, partCards.filter((c) => c.slug !== slug).slice(0, 3));
      if (sub === "/params") return json(route, partRecord(slug).params);
      if (sub === "/variant") return json(route, { params: { thickness: 5 }, applied: ["thickness 3.0 → 5.0 mm"], not_applied: ["make it blue"], confidence: 0.82, mode: "mock" });
    }
    if (path === "/needs" && method === "POST") return json(route, { id: "need_1", query: JSON.parse(route.request().postData() ?? "{}").query, votes: 1, status: "open", created_at: NOW });
    if (path === "/jobs" && method === "GET") return json(route, [jobSummary, pausedDetail.summary]);
    if (path === "/jobs/demo" && method === "POST") return json(route, jobSummary);
    if (path === "/jobs/fix" && method === "POST") return json(route, jobSummary);
    if (path === "/replays") return json(route, replays);
    if (path === "/measure") return json(route, { capture: captureOk, calibration: null, measurements: null, overlay_url: `${A}/measure.png` });
    if (path === "/bench") return opts.noBench ? json(route, { error: { code: "not_found", message: "no report" } }, 404) : json(route, bench);
    if (path === "/steer" && method === "POST") return json(route, { id: "steer_1" });
    if (path === "/steer/steer_1") return json(route, steerRun);
    if (path === "/steer/steer_1/review") return json(route, steerRun);

    const job = path.match(/^\/jobs\/([^/]+)(\/[a-z.-]+)?$/);
    if (job) {
      const id = job[1]!;
      const sub = job[2];
      const paused = id === "job_paused";
      if (!sub) return json(route, paused ? pausedDetail : { ...jobDetail, events: jobEvents.slice(0, 4) });
      if (sub === "/events") {
        return route.fulfill({ status: 200, contentType: "text/event-stream", headers: { "Cache-Control": "no-cache" }, body: sse(paused ? pausedEvents : jobEvents) });
      }
      if (sub === "/answer") return json(route, { ...pausedDetail.summary, status: "running" });
      if (sub === "/edit")
        return json(route, { transcript: "make it 1 mm thicker", edits: [{ param: "thickness", from: 3, to: 4, reason: "thicker" }], not_understood: [], confidence: 0.9, mode: "mock", bake: bakeResult("l-bracket", { thickness: 4 }) });
      if (sub === "/preview") return json(route, { url: `${A}/render.png`, label: "AI preview", mode: "mock" });
      if (sub === "/fit-outline") return json(route, fitOutline);
      if (sub === "/fit-check")
        return json(route, { passed: true, iou: 0.981, hausdorff_mm: 0.38, mean_mm: 0.12, reasons: ["Outline and part agree within 0.5 mm"], overlay_url: `${A}/render.png`, capture: captureOk });
    }
    return json(route, { error: { code: "not_mocked", message: `${method} ${path}` } }, 404);
  });
  return log;
}

export const CALIBRATION = { px_per_mm: 3.7795, dpr: 1, screen_w: 1440, screen_h: 900, card_w_px: 323.53, card_h_px: 204.03, calibrated_at: NOW * 1000 };
