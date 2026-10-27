/**
 * Live contract check: every read endpoint of a running API must parse with the web app's Zod schemas.
 * Run with `pnpm e2e:live` (needs `uvicorn services.api.main:app` on LIVE_API_URL, default http://localhost:8000).
 */
import { expect, test } from "@playwright/test";
import type { z } from "zod";
import * as S from "../../src/lib/api-types";

const API = `${(process.env.LIVE_API_URL ?? "http://localhost:8000").replace(/\/$/, "")}/api/v1`;

async function check<T extends z.ZodType>(request: import("@playwright/test").APIRequestContext, path: string, schema: T): Promise<z.output<T>> {
  const res = await request.get(`${API}${path}`);
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
  await check(request, "/families", S.FamilySchema.array());
  await check(request, "/mats", S.MatLayoutSchema.array());
  await check(request, "/bench", S.BenchReportSchema);
  await check(request, "/needs", S.NeedSchema.array());
  await check(request, "/replays", S.ReplaySchema.array());
  await check(request, "/jobs/demo/samples", S.DemoSampleSchema.array());
  await check(request, "/steer?limit=5", S.SteerSummarySchema.array());
  const list = await check(request, "/parts?limit=50", S.PartListSchema);
  expect(list.items.length, "seeded registry").toBeGreaterThan(0);
  for (const card of list.items) {
    const part = await check(request, `/parts/${card.slug}`, S.PartRecordSchema);
    await check(request, `/parts/${card.slug}/params`, S.ParamSpecSchema.array());
    await check(request, `/parts/${card.slug}/matching`, S.PartCardSchema.array());
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
  const jobs = await check(request, "/jobs?limit=10", S.JobSummarySchema.array());
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
