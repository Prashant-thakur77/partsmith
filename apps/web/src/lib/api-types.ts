/**
 * Runtime-validated API types (Zod) for the `/api/v1` contract in docs/API.md.
 * Shapes mirror `packages/schemas/partsmith_schemas`; every length is millimetres.
 * Parsing happens at the API boundary (src/lib/api.ts) so components only ever see validated data.
 */
import { z } from "zod";

const num = z.number();
const point2 = z.tuple([num, num]);

// ── common ────────────────────────────────────────────────────────────────────
export const SourceSchema = z.enum(["measured", "user_stated", "inferred"]);
export type Source = z.output<typeof SourceSchema>;

export const DataOriginSchema = z.enum(["real", "synthetic", "reference_object", "replay"]);
export type DataOrigin = z.output<typeof DataOriginSchema>;

export const ProviderModeSchema = z.enum(["live", "mock", "replay"]);
export type ProviderMode = z.output<typeof ProviderModeSchema>;

export const GroundTruthSourceSchema = z.enum(["synthetic_exact", "reference_spec", "ruler", "caliper"]);
export type GroundTruthSource = z.output<typeof GroundTruthSourceSchema>;

export const MeasuredSchema = z.object({
  value: num,
  source: SourceSchema.default("measured"),
  sigma_mm: num.default(0),
  evidence: z.object({ view: z.string().nullish(), note: z.string().nullish() }).nullish(),
});
export type Measured = z.output<typeof MeasuredSchema>;

export const ApiErrorBodySchema = z.object({
  error: z.object({ code: z.string(), message: z.string(), closest_matches: z.array(z.string()).optional() }),
});

// ── system ────────────────────────────────────────────────────────────────────
export const HealthSchema = z.object({ ok: z.boolean(), version: z.string() });
export type Health = z.output<typeof HealthSchema>;

export const ProviderStatusSchema = z.object({
  stage: z.string(),
  role: z.string(),
  provider: z.string(),
  model: z.string(),
  mode: ProviderModeSchema,
  key_env: z.string().nullable(),
  key_present: z.boolean(),
  open_weights: z.boolean(),
  where: z.string(),
  note: z.string().default(""),
});
export type ProviderStatus = z.output<typeof ProviderStatusSchema>;

export const StatusSchema = z.object({
  mode: z.enum(["live", "mock", "replay", "mixed"]),
  providers: z.array(ProviderStatusSchema),
  warnings: z.array(z.string()).default([]),
  jobs: z.object({ total: z.number().int(), verified: z.number().int() }),
  cost: z.object({ usd_total: num, usd_per_job_mean: num.nullable(), n_jobs: z.number().int() }),
});
export type Status = z.output<typeof StatusSchema>;

// ── mats ──────────────────────────────────────────────────────────────────────
export const MatMarkerSchema = z.object({
  id: z.number().int(),
  x_mm: num,
  y_mm: num,
  size_mm: num,
  bits: z.array(z.array(z.union([z.literal(0), z.literal(1)]))),
});
export type MatMarker = z.output<typeof MatMarkerSchema>;

export const MatLayoutSchema = z.object({
  mat_id: z.string(),
  kind: z.enum(["screen", "paper"]),
  title: z.string(),
  width_mm: num,
  height_mm: num,
  dictionary: z.string(),
  stage: z.object({ x_mm: num, y_mm: num, w_mm: num, h_mm: num }),
  markers: z.array(MatMarkerSchema),
  min_screen_mm: z.object({ w: num, h: num }),
});
export type MatLayout = z.output<typeof MatLayoutSchema>;

// ── capture / measurement ─────────────────────────────────────────────────────
export const CaptureCheckSchema = z.object({
  name: z.enum(["markers", "reprojection", "blur", "coverage", "tilt", "exposure", "glare", "moire", "scale"]),
  passed: z.boolean(),
  severity: z.enum(["ok", "warn", "fail"]),
  value: num.nullish(),
  threshold: num.nullish(),
  reason: z.string(),
});
export type CaptureCheck = z.output<typeof CaptureCheckSchema>;

export const CaptureReportSchema = z.object({
  passed: z.boolean(),
  checks: z.array(CaptureCheckSchema),
  retake_reason: z.string().nullish(),
});
export type CaptureReport = z.output<typeof CaptureReportSchema>;

export const HoleSchema = z.object({
  id: z.string(),
  center_mm: point2,
  diameter: MeasuredSchema,
  roundness_mm: num.default(0),
});
export type Hole = z.output<typeof HoleSchema>;

export const SlotSchema = z.object({
  id: z.string(),
  center_mm: point2,
  length: MeasuredSchema,
  width: MeasuredSchema,
  angle_deg: num,
});

export const ViewKindSchema = z.enum(["top", "side", "mating", "fit_check"]);

export const MeasurementsSchema = z.object({
  view: ViewKindSchema,
  origin: DataOriginSchema,
  outline_mm: z.array(point2),
  holes: z.array(HoleSchema).default([]),
  slots: z.array(SlotSchema).default([]),
  length: MeasuredSchema,
  width: MeasuredSchema,
  thickness: MeasuredSchema.nullish(),
  area_mm2: num,
  symmetry_axis_deg: num.nullish(),
  symmetry_score: num.nullish(),
  height_correction_scale: num.default(1),
  part_to_mat: z.array(z.array(num)).default([]),
  mask_source: z.enum(["sam-3.1", "sam3-open", "mock-threshold", "synthetic-gt"]).default("mock-threshold"),
  mask_confidence: num.nullish(),
  notes: z.array(z.string()).default([]),
});
export type Measurements = z.output<typeof MeasurementsSchema>;

export const CalibrationSchema = z.object({
  mat_id: z.string(),
  mat_kind: z.enum(["screen", "paper"]),
  markers_found: z.number().int(),
  homography: z.array(z.array(num)),
  reproj_error_px: num,
  reproj_error_mm: num,
  rectified_px_per_mm: num,
  scale_correction: num.default(1),
  pose: z.unknown().nullish(),
});

export const MeasureResultSchema = z.object({
  capture: CaptureReportSchema,
  calibration: CalibrationSchema.nullish(),
  measurements: MeasurementsSchema.nullish(),
  overlay_sha: z.string().nullish(),
  rectified_sha: z.string().nullish(),
  mask_sha: z.string().nullish(),
  overlay_url: z.string().nullish(),
});
export type MeasureResult = z.output<typeof MeasureResultSchema>;

// ── verification ──────────────────────────────────────────────────────────────
export const ParamSpecSchema = z.object({
  name: z.string(),
  default: num,
  min: num,
  max: num,
  step: num,
  unit: z.enum(["mm", "deg", ""]).default("mm"),
  affects_fit: z.boolean().default(true),
  label: z.string().default(""),
  topology: z.boolean().default(false),
});
export type ParamSpec = z.output<typeof ParamSpecSchema>;

export const ViewMetricsSchema = z.object({
  view: z.string(),
  iou: num,
  hausdorff_mm: num,
  hd95_mm: num,
  mean_mm: num,
  worst_point_mm: point2.nullish(),
  over_area_mm2: num.default(0),
  under_area_mm2: num.default(0),
});
export type ViewMetrics = z.output<typeof ViewMetricsSchema>;

export const FeatureResidualSchema = z.object({
  feature_id: z.string(),
  quantity: z.string(),
  measured_mm: num,
  model_mm: num,
  delta_mm: num,
  tol_mm: num,
  passed: z.boolean(),
});
export type FeatureResidual = z.output<typeof FeatureResidualSchema>;

export const PartTestSchema = z.object({
  id: z.string(),
  description: z.string(),
  value: num.nullable(),
  expected: num.nullable(),
  tol: num.nullable(),
  passed: z.boolean(),
  priority: z.enum(["P0", "P1"]).default("P0"),
});
export type PartTest = z.output<typeof PartTestSchema>;

export const ValiditySchema = z.object({
  is_valid: z.boolean(),
  single_solid: z.boolean(),
  watertight: z.boolean(),
  volume_mm3: num,
  bbox_mm: z.tuple([num, num, num]),
  min_wall_mm: num.nullish(),
  issues: z.array(z.string()).default([]),
});

export const VerificationSchema = z.object({
  verified: z.boolean(),
  status: z.enum(["verified", "best_effort", "failed"]),
  reasons: z.array(z.string()).default([]),
  thresholds: z.object({ hausdorff_mm: num, iou: num }).default({ hausdorff_mm: 0.5, iou: 0.97 }),
  views: z.array(ViewMetricsSchema).default([]),
  residuals: z.array(FeatureResidualSchema).default([]),
  tests: z.array(PartTestSchema).default([]),
  validity: ValiditySchema.nullish(),
  vetoes: z.array(z.object({ feature: z.string(), issue: z.string(), severity: z.enum(["blocking", "minor"]) })).default([]),
  max_error_mm: num.nullish(),
  origin: DataOriginSchema.default("real"),
  versions: z.record(z.string(), z.string()).default({}),
  hashes: z.record(z.string(), z.string()).default({}),
  ms: num.default(0),
});
export type Verification = z.output<typeof VerificationSchema>;

// ── partspec (only what the UI reads; the rest passes through untyped) ───────
export const PartSpecSchema = z
  .object({
    family: z.string(),
    units: z.literal("mm").default("mm"),
    title: z.string().default(""),
    thickness: MeasuredSchema,
    features: z.array(z.looseObject({ kind: z.string(), id: z.string() })).default([]),
    broken_region: z
      .object({ polygon_mm: z.array(point2), strategy: z.string(), note: z.string().nullish() })
      .nullish(),
    unknowns: z.array(z.object({ id: z.string(), question: z.string() })).default([]),
    intent: z.string().default(""),
    refusal: z.string().nullish(),
  })
  .loose();
export type PartSpec = z.output<typeof PartSpecSchema>;

// ── events (SSE) ──────────────────────────────────────────────────────────────
const ev = { job: z.string(), seq: z.number().int().default(0), ts: num.default(0), ctx: z.string().default("") };

export const StageNameSchema = z.enum([
  "capture",
  "measure",
  "understand",
  "ask",
  "plan",
  "build",
  "execute",
  "verify",
  "fix",
  "judge",
  "package",
  "learn",
]);
export type StageName = z.output<typeof StageNameSchema>;

export const StageEventSchema = z.object({
  ...ev,
  t: z.literal("stage"),
  stage: StageNameSchema,
  status: z.enum(["start", "ok", "fail", "skip"]),
  ms: z.number().int().nullish(),
  label: z.string().default(""),
  iter: z.number().int().nullish(),
});
export const MetricEventSchema = z.object({
  ...ev,
  t: z.literal("metric"),
  iter: z.number().int(),
  name: z.string(),
  value: num,
  threshold: num.nullish(),
  unit: z.string().default("mm"),
});
export const ArtifactEventSchema = z.object({
  ...ev,
  t: z.literal("artifact"),
  kind: z.string(),
  sha: z.string(),
  url: z.string(),
  iter: z.number().int().nullish(),
  label: z.string().default(""),
});
export const QuestionEventSchema = z.object({
  ...ev,
  t: z.literal("question"),
  id: z.string(),
  text: z.string(),
  expects: z.enum(["number_mm", "choice", "text"]).default("number_mm"),
  default: z.union([z.string(), num]).nullish(),
  choices: z.array(z.string()).nullish(),
});
export const AnswerEventSchema = z.object({
  ...ev,
  t: z.literal("answer"),
  id: z.string(),
  value: z.union([z.string(), num]),
  via: z.enum(["text", "voice"]).default("text"),
});
export const ModelCallEventSchema = z.object({
  ...ev,
  t: z.literal("model_call"),
  provider: z.string(),
  model: z.string(),
  stage: z.string(),
  mode: ProviderModeSchema,
  tokens_in: z.number().int().default(0),
  tokens_out: z.number().int().default(0),
  ms: z.number().int().default(0),
  usd: num.default(0),
  ok: z.boolean().default(true),
  error: z.string().nullish(),
});
export const IterationEventSchema = z.object({
  ...ev,
  t: z.literal("iteration"),
  iter: z.number().int(),
  strategy: z.enum(["template", "free_code", "human"]),
  edits: z.array(z.record(z.string(), z.unknown())).default([]),
  analysis: z.string().default(""),
  code_sha: z.string().nullish(),
  diff: z.string().default(""),
  hausdorff_mm: num.nullish(),
  iou: num.nullish(),
  passed_tests: z.number().int().default(0),
  total_tests: z.number().int().default(0),
});
export const LogEventSchema = z.object({
  ...ev,
  t: z.literal("log"),
  level: z.enum(["info", "warn", "error"]).default("info"),
  msg: z.string(),
});
export const DoneEventSchema = z.object({
  ...ev,
  t: z.literal("done"),
  verified: z.boolean(),
  status: z.enum(["verified", "best_effort", "failed", "refused", "cancelled"]),
  summary: z.record(z.string(), z.unknown()).default({}),
});

export const EventSchema = z.discriminatedUnion("t", [
  StageEventSchema,
  MetricEventSchema,
  ArtifactEventSchema,
  QuestionEventSchema,
  AnswerEventSchema,
  ModelCallEventSchema,
  IterationEventSchema,
  LogEventSchema,
  DoneEventSchema,
]);
export type JobEvent = z.output<typeof EventSchema>;
export type StageEvent = z.output<typeof StageEventSchema>;
export type MetricEvent = z.output<typeof MetricEventSchema>;
export type ArtifactEvent = z.output<typeof ArtifactEventSchema>;
export type QuestionEvent = z.output<typeof QuestionEventSchema>;
export type ModelCallEvent = z.output<typeof ModelCallEventSchema>;
export type IterationEvent = z.output<typeof IterationEventSchema>;
export type LogEvent = z.output<typeof LogEventSchema>;
export type DoneEvent = z.output<typeof DoneEventSchema>;

// ── jobs ──────────────────────────────────────────────────────────────────────
export const JobKindSchema = z.enum(["fix", "steer", "bake", "variant", "fit_check"]);
export const JobStatusSchema = z.enum(["queued", "running", "waiting_for_answer", "done", "failed", "cancelled"]);
export type JobStatus = z.output<typeof JobStatusSchema>;

export const JobSummarySchema = z.object({
  id: z.string(),
  kind: JobKindSchema,
  status: JobStatusSchema,
  created_at: num,
  updated_at: num,
  title: z.string().default(""),
  origin: DataOriginSchema.default("real"),
  provider_mode: ProviderModeSchema.default("mock"),
  verified: z.boolean().default(false),
  max_error_mm: num.nullish(),
  iterations: z.number().int().default(0),
  cost_usd: num.default(0),
  part_slug: z.string().nullish(),
  is_replay: z.boolean().default(false),
});
export type JobSummary = z.output<typeof JobSummarySchema>;

export const JobDetailSchema = z.object({
  summary: JobSummarySchema,
  events: z.array(EventSchema).default([]),
  partspec: PartSpecSchema.nullish(),
  measurements: z.record(z.string(), MeasurementsSchema).default({}),
  verification: VerificationSchema.nullish(),
  code: z.string().nullish(),
  params: z.array(ParamSpecSchema).default([]),
  values: z.record(z.string(), num).default({}),
  artifacts: z.record(z.string(), z.string()).default({}),
  question: QuestionEventSchema.nullish(),
});
export type JobDetail = z.output<typeof JobDetailSchema>;

// ── registry ──────────────────────────────────────────────────────────────────
export const PartFactsSchema = z.object({
  bbox_mm: z.tuple([num, num, num]),
  volume_mm3: num,
  mass_g_pla: num,
  mass_g_petg: num,
  print_minutes_est: num,
  supports_needed: z.boolean(),
  orientation: z.string(),
});
export type PartFacts = z.output<typeof PartFactsSchema>;

export const BakeResultSchema = z.object({
  cache_key: z.string(),
  part_slug: z.string(),
  version: z.number().int(),
  params: z.record(z.string(), num),
  clamped: z.record(z.string(), num).default({}),
  artifacts: z.record(z.string(), z.string()),
  facts: PartFactsSchema.nullish(),
  cache_hit: z.boolean(),
  ms: num,
});
export type BakeResult = z.output<typeof BakeResultSchema>;

export const EditResultSchema = z.object({
  transcript: z.string(),
  edits: z.array(z.object({ param: z.string(), from: num, to: num, reason: z.string().default("") })),
  not_understood: z.array(z.string()).default([]),
  confidence: num,
  mode: z.string(),
  bake: BakeResultSchema.nullish(),
});
export type EditResult = z.output<typeof EditResultSchema>;

export const PreviewResultSchema = z.object({ url: z.string(), label: z.string(), mode: z.string() });
export type PreviewResult = z.output<typeof PreviewResultSchema>;

export const FitOutlineSchema = z.object({
  mat_id: z.string(),
  outline_mm: z.array(point2),
  holes: z.array(z.object({ center_mm: point2, diameter_mm: num })).default([]),
  dims: z.array(z.object({ label: z.string(), from_mm: point2, to_mm: point2, value_mm: num })).default([]),
  placement: z.object({ cx_mm: num, cy_mm: num, theta_deg: num }),
});
export type FitOutline = z.output<typeof FitOutlineSchema>;

export const FitCheckResultSchema = z.object({
  passed: z.boolean(),
  iou: num,
  hausdorff_mm: num,
  mean_mm: num,
  reasons: z.array(z.string()).default([]),
  overlay_url: z.string(),
  capture: CaptureReportSchema,
});
export type FitCheckResult = z.output<typeof FitCheckResultSchema>;

export const ReplaySchema = z.object({
  id: z.string(),
  title: z.string(),
  origin: DataOriginSchema,
  provider_mode: z.string(),
  verified: z.boolean(),
  max_error_mm: num.nullable(),
  iterations: z.number().int(),
});
export type Replay = z.output<typeof ReplaySchema>;

export const PartStatusSchema = z.enum(["draft", "verified", "best_effort", "published"]);
export type PartStatus = z.output<typeof PartStatusSchema>;

export const PartCardSchema = z.object({
  slug: z.string(),
  title: z.string(),
  family: z.string(),
  status: PartStatusSchema,
  origin: DataOriginSchema,
  max_error_mm: num.nullish(),
  thumbnail_url: z.string().nullish(),
  params_count: z.number().int().default(0),
  topology_knobs: z.array(z.string()).default([]),
});
export type PartCard = z.output<typeof PartCardSchema>;

export const PartListSchema = z.object({
  items: z.array(PartCardSchema),
  next_cursor: z.string().nullable(),
  total: z.number().int(),
});
export type PartList = z.output<typeof PartListSchema>;

export const ProvenanceSchema = z.object({
  origin: DataOriginSchema,
  job_id: z.string().nullish(),
  photo_shas: z.array(z.string()).default([]),
  builder_model: z.string().nullish(),
  provider_mode: ProviderModeSchema.default("mock"),
  created_by: z.string().default("partsmith"),
  forked_from: z.string().nullish(),
  note: z.string().default(""),
});
export type Provenance = z.output<typeof ProvenanceSchema>;

export const LineageEntrySchema = z.looseObject({
  slug: z.string().optional(),
  version: z.number().optional(),
  note: z.string().optional(),
  created_at: num.optional(),
});

export const PartRecordSchema = z.object({
  id: z.string(),
  slug: z.string(),
  title: z.string(),
  family: z.string(),
  summary: z.string().default(""),
  tags: z.array(z.string()).default([]),
  version: z.number().int().default(1),
  status: PartStatusSchema,
  params: z.array(ParamSpecSchema),
  defaults: z.record(z.string(), num),
  code: z.string(),
  code_sha: z.string(),
  verification: VerificationSchema.nullish(),
  provenance: ProvenanceSchema,
  facts: PartFactsSchema.nullish(),
  licence: z.string().default("CC-BY-4.0"),
  created_at: num.default(0),
  mating: z.array(z.string()).default([]),
  artifacts: z.record(z.string(), z.string()).default({}),
  lineage: z.array(LineageEntrySchema).default([]),
});
export type PartRecord = z.output<typeof PartRecordSchema>;

export const VariantResultSchema = z.object({
  params: z.record(z.string(), num),
  applied: z.array(z.string()),
  not_applied: z.array(z.string()),
  confidence: num,
  mode: ProviderModeSchema,
});
export type VariantResult = z.output<typeof VariantResultSchema>;

export const FamilySchema = z.object({ family: z.string(), title: z.string(), count: z.number().int(), verified: z.number().int() });
export type FamilyInfo = z.output<typeof FamilySchema>;

export const NeedSchema = z.object({
  id: z.string(),
  query: z.string(),
  votes: z.number().int().default(1),
  status: z.enum(["open", "in_progress", "fulfilled"]).default("open"),
  created_at: num.default(0),
});
export type Need = z.output<typeof NeedSchema>;

export const StatsSchema = z.object({
  parts: z.number().int(),
  verified: z.number().int(),
  synthetic: z.number().int(),
  real: z.number().int(),
  jobs: z.number().int(),
  grams_pla: num,
});
export type Stats = z.output<typeof StatsSchema>;

// ── steer ─────────────────────────────────────────────────────────────────────
export const SteerLaneSchema = z.object({
  slug: z.string(),
  status: z.string(),
  job_id: z.string().nullish(),
  verified: z.boolean().default(false),
  max_error_mm: num.nullish(),
});
export type SteerLane = z.output<typeof SteerLaneSchema>;

export const SteerQueueItemSchema = z.looseObject({
  slug: z.string(),
  title: z.string().optional(),
  verified: z.boolean().optional(),
  max_error_mm: num.nullish(),
  status: z.string().optional(),
  judge: z.string().nullish(),
  job_id: z.string().nullish(),
});
export type SteerQueueItem = z.output<typeof SteerQueueItemSchema>;

export const SteerRunSchema = z.object({
  id: z.string(),
  brief: z.string(),
  plan: z.array(
    z.object({ slug: z.string(), title: z.string(), family: z.string(), params: z.record(z.string(), z.unknown()).default({}) }),
  ),
  lanes: z.array(SteerLaneSchema),
  queue: z.array(SteerQueueItemSchema).default([]),
});
export type SteerRun = z.output<typeof SteerRunSchema>;

// ── bench ─────────────────────────────────────────────────────────────────────
/** Bench tables are produced by `eval/`; their row shape evolves, so rows stay loosely typed and are rendered generically. */
export const BenchTableSchema = z.looseObject({
  title: z.string().optional(),
  n: z.number().optional(),
  ground_truth: z.string().optional(),
  ci: z.string().optional(),
  columns: z.array(z.string()).optional(),
  rows: z.array(z.record(z.string(), z.unknown())).optional(),
  note: z.string().optional(),
});
export type BenchTable = z.output<typeof BenchTableSchema>;

export const BenchReportSchema = z.object({
  generated_at: z.union([z.string(), num]).nullish(),
  git_sha: z.string().nullish(),
  tables: z.record(z.string(), BenchTableSchema.nullable()).default({}),
  runs: z.unknown().optional(),
  failures: z.array(z.record(z.string(), z.unknown())).default([]),
});
export type BenchReport = z.output<typeof BenchReportSchema>;
