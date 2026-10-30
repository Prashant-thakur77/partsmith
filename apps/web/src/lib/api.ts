/**
 * Typed client for the PartSmith REST API (`/api/v1`, docs/API.md).
 * Every response is validated with Zod; failures surface as `ApiError` (HTTP error body) or `ApiOfflineError`
 * (backend unreachable). The browser calls the same-origin `/api/v1` path, which next.config.ts rewrites to the API.
 */
import { z } from "zod/mini";
import { adminToken } from "./admin";
import {
  ApiErrorBodySchema,
  BakeResultSchema,
  BenchReportSchema,
  BuyOrPrintSchema,
  MateFitResultSchema,
  CouponReportResultSchema,
  JobImpactSchema,
  LearnedClearanceSchema,
  NarrationRecordSchema,
  EditResultSchema,
  FamilySchema,
  FitCheckResultSchema,
  FitOutlineSchema,
  HealthSchema,
  JobDetailSchema,
  JobStatusSchema,
  JobSummarySchema,
  MatLayoutSchema,
  MeasureResultSchema,
  NeedSchema,
  ParamSpecSchema,
  PartCardSchema,
  PartListSchema,
  PartRecordSchema,
  PassportSchema,
  PreviewResultSchema,
  ReplaySchema,
  StatsSchema,
  StatusSchema,
  SteerStateSchema,
  SteerSummarySchema,
  DemoSampleSchema,
  TranscribeResultSchema,
  FeedbackResultSchema,
  VariantResultSchema,
  VerificationSchema,
  type Measurements,
} from "./api-types";
import { apiOrigin } from "./api-origin";
import { pointsPayload, type MateTapKind, type Tap, type TopTapKind } from "./mate-fit";

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
  return `${apiOrigin()}${API_PREFIX}`;
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

/** Validated fetch against `/api/v1` with the admin token attached when one is stored (used by api-review.ts too). */
export async function request<S extends z.ZodMiniType>(
  schema: S,
  path: string,
  init?: RequestInit & { query?: Record<string, string | number | boolean | null | undefined> },
): Promise<z.output<S>> {
  const { query, ...rest } = init ?? {};
  const url = apiUrl(path, query);
  let res: Response;
  try {
    // Server-side calls (SSR prefetch) must never hang a page render.
    const signal = rest.signal ?? (typeof window === "undefined" ? AbortSignal.timeout(3000) : undefined);
    const token = adminToken();
    res = await fetch(url, {
      ...rest,
      signal,
      headers: { Accept: "application/json", ...(token ? { Authorization: `Bearer ${token}` } : {}), ...(rest.headers ?? {}) },
    });
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
  matKind: "screen" | "paper";
  /** Only to force a mat; the server identifies the mat from the marker ids it sees. */
  matId?: string | null;
  thicknessMm?: number | null;
  familyHint?: string | null;
  screenPxPerMm?: number | null;
  /** Optional 6–8 s orbit clip ("walk around it", MP4/MOV/WebM); only sent when the server accepts an `orbit` field. */
  orbit?: File | null;
  /** Tap-to-point feature hints on the top photo (image pixels + kind); a tap is a segmenter prompt, never a dimension. */
  points?: Tap<TopTapKind>[] | null;
  /** Taps on the "where it fits" photo: the socket, shaft or slot the part fits (sent as `points.mating`). */
  matingPoints?: Tap<MateTapKind>[] | null;
  /** Optional voice note about the walk-around clip (the narration steers; it never sets a number). */
  narration?: File | null;
  /** Optional city for nearby print shops on the buy-or-print card. */
  city?: string | null;
};

export type BakeFormat = "stl" | "3mf" | "step" | "glb" | "view" | "py";

function audioName(b: Blob): string {
  const t = b.type;
  const ext = t.includes("ogg") ? "ogg" : t.includes("mp4") || t.includes("m4a") ? "m4a" : t.includes("mpeg") ? "mp3" : t.includes("wav") ? "wav" : "webm";
  return `audio.${ext}`;
}

export const api = {
  // system
  health: () => request(HealthSchema, "/health"),
  status: () => request(StatusSchema, "/status"),

  // mats
  mats: () => request(z.array(MatLayoutSchema), "/mats"),
  mat: (matId: string) => request(MatLayoutSchema, `/mats/${encodeURIComponent(matId)}`),
  matPdfUrl: (matId: string) => apiUrl(`/mats/${encodeURIComponent(matId)}/pdf`),

  // jobs
  createFixJob: (input: FixJobInput) => {
    const fd = new FormData();
    fd.set("top", input.top);
    if (input.side) fd.set("side", input.side);
    if (input.mating) fd.set("mating", input.mating);
    if (input.intent) fd.set("intent", input.intent);
    fd.set("mat_kind", input.matKind);
    if (input.matId) fd.set("mat_id", input.matId);
    if (input.thicknessMm != null) fd.set("thickness_mm", String(input.thicknessMm));
    if (input.familyHint) fd.set("family_hint", input.familyHint);
    if (input.screenPxPerMm != null) fd.set("screen_px_per_mm", String(input.screenPxPerMm));
    if (input.orbit) fd.set("orbit", input.orbit);
    const points = pointsPayload(input.points, input.mating ? input.matingPoints : null);
    if (points) fd.set("points", points);
    if (input.narration) fd.set("narration", input.narration);
    if (input.city) fd.set("city", input.city);
    return request(JobSummarySchema, "/jobs/fix", { method: "POST", body: fd });
  },
  demoSamples: () => request(z.array(DemoSampleSchema), "/jobs/demo/samples"),
  createDemoJob: (sample: string) => request(JobSummarySchema, "/jobs/demo", json({ sample })),
  jobs: (limit = 20, includeReplays = false) =>
    request(z.array(JobSummarySchema), "/jobs", { query: { limit, include_replays: includeReplays ? "true" : undefined } }),
  job: (id: string) => request(JobDetailSchema, `/jobs/${encodeURIComponent(id)}`),
  jobEventsUrl: (id: string, fromSeq?: number) => apiUrl(`/jobs/${encodeURIComponent(id)}/events`, { from_seq: fromSeq }),
  answer: (id: string, body: { id: string; value: string | number; via: "text" | "voice" }) =>
    request(JobSummarySchema, `/jobs/${encodeURIComponent(id)}/answer`, json(body)),
  editText: (id: string, text: string) => request(EditResultSchema, `/jobs/${encodeURIComponent(id)}/edit`, json({ text })),
  editAudio: (id: string, audio: Blob) => {
    const fd = new FormData();
    fd.set("audio", audio, audioName(audio));
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
  jobBake: (id: string, params: ParamQuery, format: BakeFormat = "view", signal?: AbortSignal) =>
    request(BakeResultSchema, `/jobs/${encodeURIComponent(id)}/bake`, { query: { ...params, format }, signal }),
  jobBakeDownloadUrl: (id: string, params: ParamQuery, format: BakeFormat) =>
    apiUrl(`/jobs/${encodeURIComponent(id)}/bake`, { ...params, format, download: 1 }),
  publish: (id: string, slug?: string, ack?: boolean) =>
    request(PartRecordSchema, `/jobs/${encodeURIComponent(id)}/publish`, json({ ...(slug ? { slug } : {}), ...(ack ? { ack: true } : {}) })),
  /** `status` is "cancelling" when the job had not stopped within the server's wait (it stops at its next check). */
  cancel: (id: string) =>
    request(z.extend(JobSummarySchema, { status: z.union([JobStatusSchema, z.literal("cancelling")]) }), `/jobs/${encodeURIComponent(id)}/cancel`, {
      method: "POST",
    }),
  transcribe: (audio: Blob, languageHint?: string) => {
    const fd = new FormData();
    fd.set("audio", audio, audioName(audio));
    if (languageHint) fd.set("language_hint", languageHint);
    return request(TranscribeResultSchema, "/transcribe", { method: "POST", body: fd });
  },
  runLogUrl: (id: string) => apiUrl(`/jobs/${encodeURIComponent(id)}/run.jsonl`),
  replays: () => request(z.array(ReplaySchema), "/replays"),

  // stateless measure / verify
  measure: (photo: File, view: "top" | "side", opts: { matKind?: "screen" | "paper"; matId?: string | null; thicknessMm?: number } = {}) => {
    const { matId, thicknessMm, matKind } = opts;
    const fd = new FormData();
    fd.set("photo", photo);
    fd.set("view", view);
    if (matKind) fd.set("mat_kind", matKind);
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
  partParams: (slug: string) => request(z.array(ParamSpecSchema), `/parts/${encodeURIComponent(slug)}/params`),
  bake: (slug: string, params: ParamQuery, format: BakeFormat = "view", signal?: AbortSignal) =>
    request(BakeResultSchema, `/parts/${encodeURIComponent(slug)}/bake`, { query: { ...params, format }, signal }),
  bakeDownloadUrl: (slug: string, params: ParamQuery, format: BakeFormat, ack = false) =>
    apiUrl(`/parts/${encodeURIComponent(slug)}/bake`, { ...params, format, download: 1, ack: ack ? 1 : undefined }),
  variant: (slug: string, want: string) =>
    request(VariantResultSchema, `/parts/${encodeURIComponent(slug)}/variant`, { query: { want } }),
  matching: (slug: string) => request(z.array(PartCardSchema), `/parts/${encodeURIComponent(slug)}/matching`),
  thumbnailUrl: (slug: string, scale: 1 | 2 = 1) => apiUrl(`/parts/${encodeURIComponent(slug)}/thumbnail.png`, { scale }),
  feedback: (slug: string, body: { result: "fits" | "tight" | "loose" | "pass" | "fail"; kind: "print" | "screen_fit"; note: string }) =>
    request(FeedbackResultSchema, `/parts/${encodeURIComponent(slug)}/feedback`, json(body)),
  bundleZipUrl: (slug: string, params: ParamQuery, ack: boolean) =>
    apiUrl(`/parts/${encodeURIComponent(slug)}/bundle.zip`, { ...params, ack: ack ? 1 : undefined }),
  templatePdfUrl: (slug: string, params: ParamQuery) => apiUrl(`/parts/${encodeURIComponent(slug)}/template.pdf`, params),
  families: () => request(z.array(FamilySchema), "/families"),
  createNeed: (query: string, photo?: File | null) => {
    if (!photo) return request(NeedSchema, "/needs", json({ query }));
    const fd = new FormData();
    fd.set("query", query);
    fd.set("photo", photo);
    return request(NeedSchema, "/needs", { method: "POST", body: fd });
  },
  voteNeed: (id: string) => request(NeedSchema, `/needs/${encodeURIComponent(id)}/vote`, { method: "POST" }),
  needs: () => request(z.array(NeedSchema), "/needs"),
  stats: () => request(StatsSchema, "/stats"),

  // steer
  steer: (brief: string, count: number) => request(z.pick(SteerStateSchema, { id: true }), "/steer", json({ brief, count })),
  steerRuns: (limit = 10) => request(z.array(SteerSummarySchema), "/steer", { query: { limit } }),
  steerRun: (id: string) => request(SteerStateSchema, `/steer/${encodeURIComponent(id)}`),
  steerReview: (id: string, body: { slug: string; action: "approve" | "send_back" | "reject"; note: string }) =>
    request(SteerStateSchema, `/steer/${encodeURIComponent(id)}/review`, json(body)),

  // bench
  bench: () => request(BenchReportSchema, "/bench"),

  // round 3: coupon fit learning, impact, buy-or-print
  couponLearned: (session: string | null) =>
    request(z.array(LearnedClearanceSchema), "/fit-reports/coupon", { query: { session } }),
  couponReport: (body: { preset: string; session: string; features: { feature: string; fit: string; amount: string | null }[]; job_id?: string; slug?: string }) =>
    request(CouponReportResultSchema, "/fit-reports/coupon", json(body)),
  jobImpact: (id: string) => request(JobImpactSchema, `/jobs/${encodeURIComponent(id)}/impact`),
  jobBuyOrPrint: (id: string) => request(BuyOrPrintSchema, `/jobs/${encodeURIComponent(id)}/buy-or-print`),
  /** Runs the cited lookup (search grounding) and stores the card; never touches the verification. */
  jobBuyOrPrintLookup: (id: string, city: string | null) =>
    request(BuyOrPrintSchema, `/jobs/${encodeURIComponent(id)}/buy-or-print`, json(city ? { city } : {})),
  partBuyOrPrint: (slug: string) => request(BuyOrPrintSchema, `/parts/${encodeURIComponent(slug)}/buy-or-print`),
  /** The job's "fits where it goes" record; `fitSession` recomputes the printer note with this device's learned clearance. */
  jobMateFit: (id: string, fitSession?: string | null) =>
    request(MateFitResultSchema, `/jobs/${encodeURIComponent(id)}/mate-fit${fitSession ? `?fit_session=${encodeURIComponent(fitSession)}` : ""}`),
  /** Repair passport: what a printed id points at (404 `passport_not_found` + closest ids otherwise). */
  passport: (id: string) => request(PassportSchema, `/passport/${encodeURIComponent(id)}`),
  /** The job's `narration` artifact (an `/api/v1/blobs/...json` URL from the job detail). */
  narration: (artifact: string) => {
    if (!artifact.startsWith(`${API_PREFIX}/`)) return Promise.reject(new Error("narration artifact is not an API URL"));
    return request(NarrationRecordSchema, artifact.slice(API_PREFIX.length));
  },
};

export type Api = typeof api;
