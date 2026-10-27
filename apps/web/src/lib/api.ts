/**
 * Typed client for the PartSmith REST API (`/api/v1`, docs/API.md).
 * Every response is validated with Zod; failures surface as `ApiError` (HTTP error body) or `ApiOfflineError`
 * (backend unreachable). The browser calls the same-origin `/api/v1` path, which next.config.ts rewrites to the API.
 */
import type { z } from "zod";
import {
  ApiErrorBodySchema,
  BakeResultSchema,
  BenchReportSchema,
  EditResultSchema,
  FamilySchema,
  FitCheckResultSchema,
  FitOutlineSchema,
  HealthSchema,
  JobDetailSchema,
  JobSummarySchema,
  MatLayoutSchema,
  MeasureResultSchema,
  NeedSchema,
  ParamSpecSchema,
  PartCardSchema,
  PartListSchema,
  PartRecordSchema,
  PreviewResultSchema,
  ReplaySchema,
  StatsSchema,
  StatusSchema,
  SteerRunSchema,
  VariantResultSchema,
  VerificationSchema,
  type Measurements,
} from "./api-types";

export const API_PREFIX = "/api/v1";

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
    readonly closestMatches: string[] = [],
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export class ApiOfflineError extends Error {
  constructor(override readonly cause?: unknown) {
    super("The PartSmith API is not reachable.");
    this.name = "ApiOfflineError";
  }
}

export class ApiSchemaError extends Error {
  constructor(
    readonly path: string,
    readonly issues: string,
  ) {
    super(`Unexpected response shape from ${path}: ${issues}`);
    this.name = "ApiSchemaError";
  }
}

export function isOffline(err: unknown): boolean {
  return err instanceof ApiOfflineError || (err instanceof ApiError && (err.status === 502 || err.status === 503 || err.status === 504));
}

function base(): string {
  if (typeof window !== "undefined") return API_PREFIX;
  return `${(process.env.API_URL ?? "http://localhost:8000").replace(/\/$/, "")}${API_PREFIX}`;
}

/** Absolute-or-relative URL for an API path; artifact URLs returned by the API are passed through unchanged. */
export function apiUrl(path: string, query?: Record<string, string | number | boolean | null | undefined>): string {
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(query ?? {})) if (v !== undefined && v !== null && v !== "") qs.set(k, String(v));
  const q = qs.toString();
  return `${base()}${path}${q ? `?${q}` : ""}`;
}

/** Resolve an artifact URL from the API (may be absolute, `/api/v1/...` or relative to the API prefix). */
export function artifactUrl(url: string | null | undefined): string | undefined {
  if (!url) return undefined;
  if (/^(https?:|data:|blob:)/.test(url) || url.startsWith("/")) return url;
  return `${API_PREFIX}/${url}`;
}

async function request<S extends z.ZodType>(
  schema: S,
  path: string,
  init?: RequestInit & { query?: Record<string, string | number | boolean | null | undefined> },
): Promise<z.output<S>> {
  const { query, ...rest } = init ?? {};
  const url = apiUrl(path, query);
  let res: Response;
  try {
    res = await fetch(url, { ...rest, headers: { Accept: "application/json", ...(rest.headers ?? {}) } });
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") throw err;
    throw new ApiOfflineError(err);
  }
  const text = await res.text();
  let body: unknown = undefined;
  try {
    body = text ? JSON.parse(text) : undefined;
  } catch {
    body = undefined;
  }
  if (!res.ok) {
    const parsed = ApiErrorBodySchema.safeParse(body);
    if (parsed.success) {
      throw new ApiError(res.status, parsed.data.error.code, parsed.data.error.message, parsed.data.error.closest_matches ?? []);
    }
    // The Next dev/prod proxy answers 500 with a plain body when the API process is down.
    if ((res.status === 500 || res.status >= 502) && body === undefined) throw new ApiOfflineError(text);
    throw new ApiError(res.status, `http_${res.status}`, text.slice(0, 200) || res.statusText);
  }
  const parsed = schema.safeParse(body);
  if (!parsed.success) {
    throw new ApiSchemaError(path, parsed.error.issues.slice(0, 3).map((i) => `${i.path.join(".")}: ${i.message}`).join("; "));
  }
  return parsed.data;
}

const json = (body: unknown): RequestInit => ({
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

type ParamQuery = Record<string, number>;

export type PartsQuery = {
  q?: string;
  family?: string;
  verified?: boolean;
  sort?: "relevance" | "newest" | "error" | "title";
  cursor?: string | null;
  limit?: number;
};

export type FixJobInput = {
  top: File;
  side?: File | null;
  mating?: File | null;
  intent?: string;
  /** Only to force a mat; the server identifies the mat from the marker ids it sees. */
  matId?: string | null;
  thicknessMm?: number | null;
  familyHint?: string | null;
  screenPxPerMm?: number | null;
};

export type BakeFormat = "stl" | "3mf" | "step" | "glb" | "view" | "py";

export const api = {
  // system
  health: () => request(HealthSchema, "/health"),
  status: () => request(StatusSchema, "/status"),

  // mats
  mats: () => request(MatLayoutSchema.array(), "/mats"),
  mat: (matId: string) => request(MatLayoutSchema, `/mats/${encodeURIComponent(matId)}`),
  matPdfUrl: (matId: string) => apiUrl(`/mats/${encodeURIComponent(matId)}/pdf`),

  // jobs
  createFixJob: (input: FixJobInput) => {
    const fd = new FormData();
    fd.set("top", input.top);
    if (input.side) fd.set("side", input.side);
    if (input.mating) fd.set("mating", input.mating);
    if (input.intent) fd.set("intent", input.intent);
    if (input.matId) fd.set("mat_id", input.matId);
    if (input.thicknessMm != null) fd.set("thickness_mm", String(input.thicknessMm));
    if (input.familyHint) fd.set("family_hint", input.familyHint);
    if (input.screenPxPerMm != null) fd.set("screen_px_per_mm", String(input.screenPxPerMm));
    return request(JobSummarySchema, "/jobs/fix", { method: "POST", body: fd });
  },
  createDemoJob: (sample: string) => request(JobSummarySchema, "/jobs/demo", json({ sample })),
  jobs: (limit = 20) => request(JobSummarySchema.array(), "/jobs", { query: { limit } }),
  job: (id: string) => request(JobDetailSchema, `/jobs/${encodeURIComponent(id)}`),
  jobEventsUrl: (id: string, fromSeq?: number) => apiUrl(`/jobs/${encodeURIComponent(id)}/events`, { from_seq: fromSeq }),
  answer: (id: string, body: { id: string; value: string | number; via: "text" | "voice" }) =>
    request(JobSummarySchema, `/jobs/${encodeURIComponent(id)}/answer`, json(body)),
  editText: (id: string, text: string) => request(EditResultSchema, `/jobs/${encodeURIComponent(id)}/edit`, json({ text })),
  editAudio: (id: string, audio: Blob) => {
    const fd = new FormData();
    fd.set("audio", audio, "edit.webm");
    return request(EditResultSchema, `/jobs/${encodeURIComponent(id)}/edit`, { method: "POST", body: fd });
  },
  preview: (id: string) => request(PreviewResultSchema, `/jobs/${encodeURIComponent(id)}/preview`, { method: "POST" }),
  fitOutline: (id: string, matId: string) =>
    request(FitOutlineSchema, `/jobs/${encodeURIComponent(id)}/fit-outline`, { query: { mat_id: matId } }),
  fitCheck: (id: string, photo: File, matId: string) => {
    const fd = new FormData();
    fd.set("photo", photo);
    fd.set("mat_id", matId);
    return request(FitCheckResultSchema, `/jobs/${encodeURIComponent(id)}/fit-check`, { method: "POST", body: fd });
  },
  runLogUrl: (id: string) => apiUrl(`/jobs/${encodeURIComponent(id)}/run.jsonl`),
  replays: () => request(ReplaySchema.array(), "/replays"),

  // stateless measure / verify
  measure: (photo: File, view: string, opts: { matId?: string | null; thicknessMm?: number } = {}) => {
    const { matId, thicknessMm } = opts;
    const fd = new FormData();
    fd.set("photo", photo);
    fd.set("view", view);
    if (matId) fd.set("mat_id", matId);
    if (thicknessMm != null) fd.set("thickness_mm", String(thicknessMm));
    return request(MeasureResultSchema, "/measure", { method: "POST", body: fd });
  },
  verify: (part: string, params: ParamQuery, measurements: Measurements) =>
    request(VerificationSchema, "/verify", json({ part, params, measurements })),

  // registry
  parts: (q: PartsQuery = {}) =>
    request(PartListSchema, "/parts", {
      query: {
        q: q.q,
        family: q.family,
        verified: q.verified ? "true" : undefined,
        sort: q.sort,
        cursor: q.cursor ?? undefined,
        limit: q.limit,
      },
    }),
  part: (slug: string) => request(PartRecordSchema, `/parts/${encodeURIComponent(slug)}`),
  partParams: (slug: string) => request(ParamSpecSchema.array(), `/parts/${encodeURIComponent(slug)}/params`),
  bake: (slug: string, params: ParamQuery, format: BakeFormat = "view", signal?: AbortSignal) =>
    request(BakeResultSchema, `/parts/${encodeURIComponent(slug)}/bake`, { query: { ...params, format }, signal }),
  bakeDownloadUrl: (slug: string, params: ParamQuery, format: BakeFormat) =>
    apiUrl(`/parts/${encodeURIComponent(slug)}/bake`, { ...params, format, download: 1 }),
  variant: (slug: string, want: string) =>
    request(VariantResultSchema, `/parts/${encodeURIComponent(slug)}/variant`, { query: { want } }),
  matching: (slug: string) => request(PartCardSchema.array(), `/parts/${encodeURIComponent(slug)}/matching`),
  templatePdfUrl: (slug: string, params: ParamQuery) => apiUrl(`/parts/${encodeURIComponent(slug)}/template.pdf`, params),
  families: () => request(FamilySchema.array(), "/families"),
  createNeed: (query: string) => request(NeedSchema, "/needs", json({ query })),
  needs: () => request(NeedSchema.array(), "/needs"),
  stats: () => request(StatsSchema, "/stats"),

  // steer
  steer: (brief: string, count: number) =>
    request(SteerRunSchema.pick({ id: true }), "/steer", json({ brief, count })),
  steerRun: (id: string) => request(SteerRunSchema, `/steer/${encodeURIComponent(id)}`),
  steerReview: (id: string, body: { slug: string; action: "approve" | "send_back" | "reject"; note: string }) =>
    request(SteerRunSchema.partial(), `/steer/${encodeURIComponent(id)}/review`, json(body)),

  // bench
  bench: () => request(BenchReportSchema, "/bench"),
};

export type Api = typeof api;
