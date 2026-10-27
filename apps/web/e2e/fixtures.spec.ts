import { expect, test } from "@playwright/test";
import { z } from "zod/mini";
import * as S from "../src/lib/api-types";
import * as F from "./fixtures/api";

test("mock fixtures satisfy the same Zod contract as the live API", ({}, info) => {
  test.skip(info.project.name !== "desktop-light", "pure check, run once");
  const cases: [string, import("zod/mini").ZodMiniType, unknown][] = [
    ["status", S.StatusSchema, F.status],
    ["stats", S.StatsSchema, F.stats],
    ["parts", S.PartListSchema, { items: F.partCards, next_cursor: null, total: F.partCards.length }],
    ["job detail", S.JobDetailSchema, { ...F.jobDetail, events: F.jobEvents }],
    ["paused detail", S.JobDetailSchema, { ...F.pausedDetail, events: F.pausedEvents }],
    ["bench", S.BenchReportSchema, F.bench],
    ["bench pending", S.BenchReportSchema, F.benchPending],
    ["steer", S.SteerStateSchema, F.steerRun],
    ["samples", z.array(S.DemoSampleSchema), F.demoSamples],
    ["replays", z.array(S.ReplaySchema), F.replays],
    ["fit outline", S.FitOutlineSchema, F.fitOutline],
    ["bake", S.BakeResultSchema, F.bakeResult("l-bracket", { length: 40 })],
  ];
  for (const [name, schema, data] of cases) {
    const r = schema.safeParse(data);
    expect(r.success, `${name}: ${r.success ? "" : JSON.stringify(r.error.issues.slice(0, 3))}`).toBe(true);
  }
});
