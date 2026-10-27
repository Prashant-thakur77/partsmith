/**
 * Live contract check: every read endpoint of a running API must parse with the web app's Zod schemas.
 * Run with `pnpm e2e:live` (needs `uvicorn services.api.main:app` on LIVE_API_URL, default http://localhost:8000).
 */
import { expect, test } from "@playwright/test";
import { z } from "zod/mini";
import * as R2 from "../../src/lib/api-r2";
import * as S from "../../src/lib/api-types";
import { PresetListSchema } from "../../src/components/jobs/fit-presets";

const API = `${(process.env.LIVE_API_URL ?? "http://localhost:8000").replace(/\/$/, "")}/api/v1`;

const ADMIN = process.env.PARTSMITH_ADMIN_TOKEN;
async function check<T extends z.ZodMiniType>(request: import("@playwright/test").APIRequestContext, path: string, schema: T): Promise<z.output<T>> {
  const res = await request.get(`${API}${path}`, ADMIN ? { headers: { Authorization: `Bearer ${ADMIN}` } } : undefined);
  expect(res.status(), `${path} status`).toBeLessThan(400);
  const body: unknown = await res.json();
  const parsed = schema.safeParse(body);
  expect(parsed.success, `${path}: ${parsed.success ? "" : JSON.stringify(parsed.error.issues.slice(0, 5), null, 1)}`).toBe(true);
  return parsed.data as z.output<T>;
}

test.describe.configure({ mode: "serial" });

test("system, registry and bench endpoints match the web contract", async ({ request }) => {
  await check(request, "/health", S.HealthSchema);
  await check(request, "/status", S.StatusSchema);
  await check(request, "/stats", S.StatsSchema);
  await check(request, "/families", z.array(S.FamilySchema));
  await check(request, "/mats", z.array(S.MatLayoutSchema));
  await check(request, "/bench", S.BenchReportSchema);
  await check(request, "/needs", z.array(S.NeedSchema));
  await check(request, "/replays", z.array(S.ReplaySchema));
  await check(request, "/jobs/demo/samples", z.array(S.DemoSampleSchema));
  await check(request, "/steer?limit=5", z.array(S.SteerSummarySchema));
  const list = await check(request, "/parts?limit=50", S.PartListSchema);
  expect(list.items.length, "seeded registry").toBeGreaterThan(0);
  for (const card of list.items) {
    const part = await check(request, `/parts/${card.slug}`, S.PartRecordSchema);
    await check(request, `/parts/${card.slug}/params`, z.array(S.ParamSpecSchema));
    await check(request, `/parts/${card.slug}/matching`, z.array(S.PartCardSchema));
    const first = part.params.find((p) => !p.topology);
    if (first) {
      const v = Math.min(first.max, first.default + first.step);
      await check(request, `/parts/${card.slug}/bake?${first.name}=${v}&format=view`, S.BakeResultSchema);
    }
    await check(request, `/parts/${card.slug}/variant?want=${encodeURIComponent("2 mm taller")}`, S.VariantResultSchema);
  }
});

test("part downloads, AR glb, template PDF and thumbnails resolve", async ({ request }) => {
  const list = await check(request, "/parts?limit=3", S.PartListSchema);
  const origin = API.replace(/\/api\/v1$/, "");
  for (const card of list.items) {
    const part = await check(request, `/parts/${card.slug}`, S.PartRecordSchema);
    const urls = [...Object.values(part.artifacts), `/api/v1/parts/${card.slug}/template.pdf`, `/api/v1/parts/${card.slug}/thumbnail.png?scale=2`];
    if (part.thumbnail_url) urls.push(part.thumbnail_url);
    for (const u of urls) {
      const r = await request.get(u.startsWith("http") ? u : `${origin}${u}`, { timeout: 60_000 });
      expect(r.status(), u).toBe(200);
      expect((await r.body()).length, u).toBeGreaterThan(100);
    }
  }
});

test("job detail and SSE events match the web contract", async ({ request }) => {
  const jobs = await check(request, "/jobs?limit=10", z.array(S.JobSummarySchema));
  for (const j of jobs.slice(0, 5)) {
    await check(request, `/jobs/${j.id}`, S.JobDetailSchema);
    const res = await request.get(`${API}/jobs/${j.id}/events`, { timeout: 30_000 });
    const lines = (await res.text()).split("\n").filter((l) => l.startsWith("data: "));
    expect(lines.length).toBeGreaterThan(0);
    for (const l of lines) {
      const parsed = S.EventSchema.safeParse(JSON.parse(l.slice(6)));
      expect(parsed.success, `${j.id} event: ${l.slice(0, 200)} ${parsed.success ? "" : JSON.stringify(parsed.error.issues.slice(0, 3))}`).toBe(true);
    }
    // Steer lanes have no photo outline (the API currently answers 500 there — reported as a backend bug).
    if (j.status === "done" && j.kind === "fix") await check(request, `/jobs/${j.id}/fit-outline?mat_id=screen-m`, S.FitOutlineSchema);
  }
});

test("round-2 endpoints match the web contract", async ({ request }) => {
  const doc = (await (await request.get(`${API}/openapi.json`)).json()) as { paths: Record<string, Record<string, unknown>> };
  for (const p of ["/presets", "/parts/{slug}/presets", "/parts/{slug}/bundle.zip", "/parts/{slug}/card.png", "/lessons", "/batches", "/needs/{id}/vote"])
    expect(Object.keys(doc.paths).some((k) => k.replace(/\{[^}]*\}/g, "{}") === `/api/v1${p}`.replace(/\{[^}]*\}/g, "{}")), `openapi has ${p}`).toBeTruthy();
  await check(request, "/presets", PresetListSchema);
  await check(request, "/lessons", z.array(R2.LessonSchema));
  await check(request, "/batches", z.array(R2.BatchListItemSchema));
  const list = await check(request, "/parts?limit=5", S.PartListSchema);
  const card = list.items.find((c) => c.verified) ?? list.items[0]!;
  await check(request, `/parts/${card.slug}/presets`, z.object({ slug: z.string(), fit_knobs: z.array(z.string()) }));
  const png = await request.get(`${API}/parts/${card.slug}/card.png`);
  expect(png.status()).toBe(200);
  expect(png.headers()["content-type"]).toContain("image/png");
  const zip = await request.get(`${API}/parts/${card.slug}/bundle.zip?ack=1`);
  expect(zip.status(), "bundle.zip").toBe(200);
  expect((await zip.body()).subarray(0, 2).toString()).toBe("PK");
  const status = await check(request, "/status", S.StatusSchema);
  expect(["token", "open (dev)"]).toContain(status.admin);
});
