/**
 * Round-2 endpoints that the web app feature-detects (see capabilities.ts). Paths live here in one place; every response
 * is still validated with Zod, and a shape mismatch surfaces as a contract error (never swallowed, never faked).
 */
import { z } from "zod/mini";
import { adminToken } from "./admin";
import { API_PREFIX, ApiError, ApiOfflineError, ApiSchemaError } from "./api";

export const R2 = {
  lessons: "/lessons",
  lessonPromote: "/lessons/{id}/promote",
  lessonReject: "/lessons/{id}/reject",
  batches: "/batches",
  batch: "/batches/{id}",
  batchJobs: "/batches/{id}/jobs",
  batchSheet: "/batches/{id}/sheet.pdf",
  needVote: "/needs/{id}/vote",
  presets: "/presets",
} as const;

async function call<S extends z.ZodMiniType>(schema: S, path: string, init?: RequestInit): Promise<z.output<S>> {
  let res: Response;
  const token = typeof window !== "undefined" ? adminToken() : null;
  try {
    res = await fetch(`${API_PREFIX}${path}`, {
      ...init,
      headers: { Accept: "application/json", ...(token ? { Authorization: `Bearer ${token}` } : {}), ...(init?.headers ?? {}) },
    });
  } catch (e) {
    throw new ApiOfflineError(e);
  }
  const text = await res.text();
  let body: unknown;
  try {
    body = text ? JSON.parse(text) : undefined;
  } catch {
    body = undefined;
  }
  if (!res.ok) {
    const err = (body as { error?: { code?: string; message?: string } } | undefined)?.error;
    throw new ApiError(res.status, err?.code ?? `http_${res.status}`, err?.message ?? text.slice(0, 200));
  }
  const parsed = schema.safeParse(body);
  if (!parsed.success) throw new ApiSchemaError(path, parsed.error.issues.slice(0, 3).map((i) => `${i.path.join(".")}: ${i.message}`).join("; "));
  return parsed.data as z.output<S>;
}
const json = (b: unknown): RequestInit => ({ method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(b) });

// ── lessons (docs/API.md: GET /lessons) ─────────────────────────────────────────
const LessonLinkSchema = z.object({ kind: z.string(), id: z.string(), url: z._default(z.string(), ""), page: z._default(z.string(), "") });
export const LessonSchema = z.object({
  id: z.string(),
  scope: z.string(),
  rule: z.string(),
  evidence: z._default(z.record(z.string(), z.unknown()), {}),
  status: z.enum(["candidate", "promoted", "rejected"]),
  promoted_by: z.nullish(z.string()),
  created_at: z._default(z.number(), 0),
  links: z._default(z.array(LessonLinkSchema), []),
});
export type Lesson = z.output<typeof LessonSchema>;
const p = (tpl: string, id: string) => tpl.replace("{id}", encodeURIComponent(id));
export const lessons = () => call(z.array(LessonSchema), R2.lessons);
export const decideLesson = (id: string, action: "promote" | "reject") =>
  call(LessonSchema, p(action === "promote" ? R2.lessonPromote : R2.lessonReject, id), json({}));

// ── repair-shop batches (admin; docs/API.md "Repair-shop batches") ─────────────
export const BatchListItemSchema = z.object({
  id: z.string(),
  name: z.string(),
  created_at: z._default(z.number(), 0),
  customers: z._default(z.int(), 0),
  jobs: z._default(z.int(), 0),
});
const BatchCustomerSchema = z.object({ name: z.string(), contact: z._default(z.string(), ""), jobs: z._default(z.array(z.string()), []) });
const num = z.nullish(z.number());
export const BatchRowSchema = z.object({
  customer: z.string(),
  contact: z._default(z.string(), ""),
  job_id: z.string(),
  title: z._default(z.string(), ""),
  status: z.string(),
  verified: z._default(z.boolean(), false),
  max_error_mm: num,
  origin: z._default(z.string(), ""),
  part_slug: z.nullish(z.string()),
  grams_pla: num,
  price_inr: num,
  print_minutes: num,
  material: z.nullish(z.string()),
});
export const BatchSchema = z.object({
  id: z.string(),
  name: z.string(),
  created_at: z._default(z.number(), 0),
  customers: z._default(z.array(BatchCustomerSchema), []),
  rows: z._default(z.array(BatchRowSchema), []),
  price: z.nullish(z.object({ inr_per_g_pla: z.number(), inr_base_per_part: z.number() })),
});
export type BatchListItem = z.output<typeof BatchListItemSchema>;
export type Batch = z.output<typeof BatchSchema>;
export type BatchRow = z.output<typeof BatchRowSchema>;
export const shop = {
  batches: () => call(z.array(BatchListItemSchema), R2.batches),
  create: (name: string, customers: { name: string; contact?: string; jobs: string[] }[] = []) => call(BatchSchema, R2.batches, json({ name, customers })),
  batch: (id: string) => call(BatchSchema, p(R2.batch, id)),
  addJob: (id: string, body: { customer: string; job_id: string; contact?: string }) => call(BatchSchema, p(R2.batchJobs, id), json(body)),
  sheetPath: (id: string) => p(R2.batchSheet, id),
};
