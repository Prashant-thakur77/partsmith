/**
 * Runtime-validated API types (Zod) for the `/api/v1` contract in docs/API.md.
 * Shapes mirror `packages/schemas/partsmith_schemas`; every length is millimetres.
 * Parsing happens at the API boundary (src/lib/api.ts) so components only ever see validated data.
 */
import { z } from "zod/mini";

const num = z.number();
const point2 = z.tuple([num, num]);

// ── common ────────────────────────────────────────────────────────────────────
export const SourceSchema = z.enum(["measured", "user_stated", "inferred", "cited"]);
export type Source = z.output<typeof SourceSchema>;

export const DataOriginSchema = z.enum(["real", "synthetic", "reference_object", "replay"]);
export type DataOrigin = z.output<typeof DataOriginSchema>;

export const ProviderModeSchema = z.enum(["live", "mock", "replay"]);
export type ProviderMode = z.output<typeof ProviderModeSchema>;

export const GroundTruthSourceSchema = z.enum(["synthetic_exact", "reference_spec", "ruler", "caliper", "expected_outcome"]);
export type GroundTruthSource = z.output<typeof GroundTruthSourceSchema>;

export const CitationSchema = z.object({ url: z.string(), title: z._default(z.string(), ""), quote: z._default(z.string(), "") });
export type Citation = z.output<typeof CitationSchema>;

export const MeasuredSchema = z.object({
  value: num,
  source: z._default(SourceSchema, "measured"),
  sigma_mm: z._default(num, 0),
  evidence: z.nullish(z.object({ view: z.nullish(z.string()), note: z.nullish(z.string()), citation: z.nullish(CitationSchema) })),
});
export type Measured = z.output<typeof MeasuredSchema>;

export const ApiErrorBodySchema = z.object({
  error: z.object({ code: z.string(), message: z.string(), closest_matches: z.optional(z.array(z.string())) }),
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
  key_env: z.nullable(z.string()),
  key_present: z.boolean(),
  open_weights: z.boolean(),
  where: z.string(),
  note: z._default(z.string(), ""),
});
export type ProviderStatus = z.output<typeof ProviderStatusSchema>;

export const StatusSchema = z.object({
  mode: z.enum(["live", "mock", "replay", "mixed"]),
  /** "token" when the server requires an admin token for writes, "open (dev)" when it does not. */
  admin: z.optional(z.string()),
  providers: z.array(ProviderStatusSchema),
  warnings: z._default(z.array(z.string()), []),
  jobs: z.object({ total: z.int(), verified: z.int() }),
  cost: z.object({ usd_total: num, usd_per_job_mean: z.nullable(num), n_jobs: z.int() }),
  model_calls: z._default(z.array(
      z.object({
        stage: z.string(),
        provider: z.string(),
        model: z.string(),
        mode: z.string(),
        calls: z.int(),
        failed: z._default(z.int(), 0),
        tokens_in: z._default(z.int(), 0),
        tokens_out: z._default(z.int(), 0),
        usd: z._default(num, 0),
        ms_mean: z.nullish(num),
        open_weights: z._default(z.boolean(), false),
      }),
    ), []),
  open_weights: z.nullish(z.object({
      open_weights_only: z.boolean(),
      stages_live_on_open_weights: z._default(z.array(z.string()), []),
      calls_on_open_weights: z._default(z.int(), 0),
      last_live_call_ts: z._default(z.record(z.string(), num), {}),
    })),
});
export type Status = z.output<typeof StatusSchema>;

// ── mats ──────────────────────────────────────────────────────────────────────
export const MatMarkerSchema = z.object({
  id: z.int(),
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
  name: z.enum(["markers", "reprojection", "blur", "coverage", "tilt", "exposure", "glare", "moire", "scale", "contrast", "single_part"]),
  passed: z.boolean(),
  severity: z.enum(["ok", "warn", "fail"]),
  value: z.nullish(num),
  threshold: z.nullish(num),
  reason: z.string(),
});
export type CaptureCheck = z.output<typeof CaptureCheckSchema>;

export const CaptureReportSchema = z.object({
  passed: z.boolean(),
  checks: z.array(CaptureCheckSchema),
  retake_reason: z.nullish(z.string()),
});
export type CaptureReport = z.output<typeof CaptureReportSchema>;

export const HoleSchema = z.object({
  id: z.string(),
  center_mm: point2,
  diameter: MeasuredSchema,
  roundness_mm: z._default(num, 0),
});
export type Hole = z.output<typeof HoleSchema>;

export const SlotSchema = z.object({
  id: z.string(),
  center_mm: point2,
  length: MeasuredSchema,
  width: MeasuredSchema,
  angle_deg: num,
});

export const ViewKindSchema = z.enum(["top", "side", "mating", "fit_check", "orbit"]);

export const MeasurementsSchema = z.object({
  view: ViewKindSchema,
  origin: DataOriginSchema,
  outline_mm: z.array(point2),
  holes: z._default(z.array(HoleSchema), []),
  slots: z._default(z.array(SlotSchema), []),
  length: MeasuredSchema,
  width: MeasuredSchema,
  thickness: z.nullish(MeasuredSchema),
  area_mm2: num,
  symmetry_axis_deg: z.nullish(num),
  symmetry_score: z.nullish(num),
  height_correction_scale: z._default(num, 1),
  part_to_mat: z._default(z.array(z.array(num)), []),
  mask_source: z._default(z.enum(["sam-3.1", "sam3-open", "threshold", "mock-threshold", "synthetic-gt"]), "threshold"),
  mask_confidence: z.nullish(num),
  notes: z._default(z.array(z.string()), []),
});
export type Measurements = z.output<typeof MeasurementsSchema>;

export const CalibrationSchema = z.object({
  mat_id: z.string(),
  mat_kind: z.enum(["screen", "paper"]),
  markers_found: z.int(),
  homography: z.array(z.array(num)),
  reproj_error_px: num,
  reproj_error_mm: num,
  rectified_px_per_mm: num,
  scale_correction: z._default(num, 1),
  pose: z.nullish(z.unknown()),
});

export const MeasureResultSchema = z.object({
  capture: CaptureReportSchema,
  calibration: z.nullish(CalibrationSchema),
  measurements: z.nullish(MeasurementsSchema),
  overlay_sha: z.nullish(z.string()),
  rectified_sha: z.nullish(z.string()),
  mask_sha: z.nullish(z.string()),
  overlay_url: z.nullish(z.string()),
});
export type MeasureResult = z.output<typeof MeasureResultSchema>;

// ── verification ──────────────────────────────────────────────────────────────
export const ParamSpecSchema = z.object({
  name: z.string(),
  default: num,
  min: num,
  max: num,
  step: num,
  unit: z._default(z.enum(["mm", "deg", ""]), "mm"),
  affects_fit: z._default(z.boolean(), true),
  label: z._default(z.string(), ""),
  topology: z._default(z.boolean(), false),
});
export type ParamSpec = z.output<typeof ParamSpecSchema>;

export const ViewMetricsSchema = z.object({
  view: z.string(),
  iou: num,
  hausdorff_mm: num,
  hd95_mm: num,
  mean_mm: num,
  worst_point_mm: z.nullish(point2),
  over_area_mm2: z._default(num, 0),
  under_area_mm2: z._default(num, 0),
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
  value: z.nullable(num),
  expected: z.nullable(num),
  tol: z.nullable(num),
  passed: z.boolean(),
  priority: z._default(z.enum(["P0", "P1"]), "P0"),
});
export type PartTest = z.output<typeof PartTestSchema>;

export const ValiditySchema = z.object({
  is_valid: z.boolean(),
  single_solid: z.boolean(),
  watertight: z.boolean(),
  volume_mm3: num,
  bbox_mm: z.tuple([num, num, num]),
  min_wall_mm: z.nullish(num),
  issues: z._default(z.array(z.string()), []),
});

export const VerificationSchema = z.object({
  verified: z.boolean(),
  status: z.enum(["verified", "best_effort", "failed"]),
  reasons: z._default(z.array(z.string()), []),
  thresholds: z._default(z.object({ hausdorff_mm: num, iou: num }), { hausdorff_mm: 0.5, iou: 0.97 }),
  views: z._default(z.array(ViewMetricsSchema), []),
  residuals: z._default(z.array(FeatureResidualSchema), []),
  tests: z._default(z.array(PartTestSchema), []),
  validity: z.nullish(ValiditySchema),
  vetoes: z._default(z.array(z.object({ feature: z.string(), issue: z.string(), severity: z.enum(["blocking", "minor"]) })), []),
  max_error_mm: z.nullish(num),
  origin: z._default(DataOriginSchema, "real"),
  versions: z._default(z.record(z.string(), z.string()), {}),
  hashes: z._default(z.record(z.string(), z.string()), {}),
  ms: z._default(num, 0),
});
export type Verification = z.output<typeof VerificationSchema>;

// ── partspec (only what the UI reads; the rest passes through untyped) ───────
export const PartSpecSchema = z.looseObject({
    family: z.string(),
    units: z._default(z.literal("mm"), "mm"),
    title: z._default(z.string(), ""),
    thickness: MeasuredSchema,
    features: z._default(z.array(z.looseObject({ kind: z.string(), id: z.string() })), []),
    broken_region: z.nullish(z.object({ polygon_mm: z.array(point2), strategy: z.string(), note: z.nullish(z.string()) })),
    unknowns: z._default(z.array(z.object({ id: z.string(), question: z.string() })), []),
    intent: z._default(z.string(), ""),
    refusal: z.nullish(z.string()),
  });
export type PartSpec = z.output<typeof PartSpecSchema>;

// ── events (SSE) ──────────────────────────────────────────────────────────────
const ev = { job: z.string(), seq: z._default(z.int(), 0), ts: z._default(num, 0), ctx: z._default(z.string(), "") };

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
  ms: z.nullish(z.int()),
  label: z._default(z.string(), ""),
  iter: z.nullish(z.int()),
});
export const MetricEventSchema = z.object({
  ...ev,
  t: z.literal("metric"),
  iter: z.int(),
  name: z.string(),
  value: num,
  threshold: z.nullish(num),
  unit: z._default(z.string(), "mm"),
});
export const ArtifactEventSchema = z.object({
  ...ev,
  t: z.literal("artifact"),
  kind: z.string(),
  sha: z.string(),
  url: z.string(),
  iter: z.nullish(z.int()),
  label: z._default(z.string(), ""),
});
export const QuestionEventSchema = z.object({
  ...ev,
  t: z.literal("question"),
  id: z.string(),
  text: z.string(),
  expects: z._default(z.enum(["number_mm", "choice", "text"]), "number_mm"),
  default: z.nullish(z.union([z.string(), num])),
  choices: z.nullish(z.array(z.string())),
});
export const AnswerEventSchema = z.object({
  ...ev,
  t: z.literal("answer"),
  id: z.string(),
  value: z.union([z.string(), num]),
  via: z._default(z.enum(["text", "voice"]), "text"),
});
export const ModelCallEventSchema = z.object({
  ...ev,
  t: z.literal("model_call"),
  provider: z.string(),
  model: z.string(),
  stage: z.string(),
  mode: ProviderModeSchema,
  tokens_in: z._default(z.int(), 0),
  tokens_out: z._default(z.int(), 0),
  ms: z._default(z.int(), 0),
  usd: z._default(num, 0),
  ok: z._default(z.boolean(), true),
  error: z.nullish(z.string()),
});
export const IterationEventSchema = z.object({
  ...ev,
  t: z.literal("iteration"),
  iter: z.int(),
  strategy: z.enum(["template", "free_code", "human"]),
  edits: z._default(z.array(z.record(z.string(), z.unknown())), []),
  analysis: z._default(z.string(), ""),
  code_sha: z.nullish(z.string()),
  diff: z._default(z.string(), ""),
  hausdorff_mm: z.nullish(num),
  iou: z.nullish(num),
  passed_tests: z._default(z.int(), 0),
  total_tests: z._default(z.int(), 0),
});
export const LogEventSchema = z.object({
  ...ev,
  t: z.literal("log"),
  level: z._default(z.enum(["info", "warn", "error"]), "info"),
  msg: z.string(),
});
export const DoneEventSchema = z.object({
  ...ev,
  t: z.literal("done"),
  verified: z.boolean(),
  status: z.enum(["verified", "best_effort", "failed", "refused", "cancelled"]),
  summary: z._default(z.record(z.string(), z.unknown()), {}),
});

export const ThoughtEventSchema = z.object({
  ...ev,
  t: z.literal("thought"),
  stage: z.string(),
  model: z._default(z.string(), ""),
  text: z.string(),
  iter: z.nullish(z.int()),
});
export const ToolCallEventSchema = z.object({
  ...ev,
  t: z.literal("tool_call"),
  stage: z.string(),
  name: z.string(),
  args: z._default(z.record(z.string(), z.unknown()), {}),
  result: z._default(z.string(), ""),
  ok: z._default(z.boolean(), true),
  ms: z._default(num, 0),
  iter: z.nullish(z.int()),
});
export const FocusEventSchema = z.object({
  ...ev,
  t: z.literal("focus"),
  feature: z._default(z.string(), ""),
  view: z._default(z.string(), "top"),
  at_mm: z.nullish(z.tuple([num, num, num])),
  label: z._default(z.string(), ""),
  iter: z.nullish(z.int()),
});

export const EventSchema = z.discriminatedUnion("t", [
  ThoughtEventSchema,
  ToolCallEventSchema,
  FocusEventSchema,
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
export type ThoughtEvent = z.output<typeof ThoughtEventSchema>;
export type ToolCallEvent = z.output<typeof ToolCallEventSchema>;
export type FocusEvent = z.output<typeof FocusEventSchema>;
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
  title: z._default(z.string(), ""),
  origin: z._default(DataOriginSchema, "real"),
  provider_mode: z._default(ProviderModeSchema, "mock"),
  verified: z._default(z.boolean(), false),
  max_error_mm: z.nullish(num),
  iterations: z._default(z.int(), 0),
  cost_usd: z._default(num, 0),
  part_slug: z.nullish(z.string()),
  is_replay: z._default(z.boolean(), false),
});
export type JobSummary = z.output<typeof JobSummarySchema>;

export const JobDetailSchema = z.object({
  summary: JobSummarySchema,
  events: z._default(z.array(EventSchema), []),
  partspec: z.nullish(PartSpecSchema),
  measurements: z._default(z.record(z.string(), MeasurementsSchema), {}),
  verification: z.nullish(VerificationSchema),
  code: z.nullish(z.string()),
  params: z._default(z.array(ParamSpecSchema), []),
  values: z._default(z.record(z.string(), num), {}),
  artifacts: z._default(z.record(z.string(), z.string()), {}),
  question: z.nullish(QuestionEventSchema),
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
  version: z.int(),
  params: z.record(z.string(), num),
  clamped: z._default(z.record(z.string(), num), {}),
  artifacts: z.record(z.string(), z.string()),
  facts: z.nullish(PartFactsSchema),
  cache_hit: z.boolean(),
  ms: num,
  facts_notes: z._default(z.record(z.string(), z.string()), {}),
});
export type BakeResult = z.output<typeof BakeResultSchema>;

export const EditResultSchema = z.object({
  transcript: z.string(),
  edits: z.array(z.object({ param: z.string(), from: num, to: num, reason: z._default(z.string(), "") })),
  not_understood: z._default(z.array(z.string()), []),
  confidence: num,
  mode: z.string(),
  bake: z.nullish(BakeResultSchema),
});
export type EditResult = z.output<typeof EditResultSchema>;

export const PreviewResultSchema = z.object({ url: z.string(), label: z.string(), mode: z.string() });
export type PreviewResult = z.output<typeof PreviewResultSchema>;

export const FitOutlineSchema = z.object({
  mat_id: z.string(),
  outline_mm: z.array(point2),
  holes: z._default(z.array(z.object({ center_mm: point2, diameter_mm: num })), []),
  dims: z._default(z.array(z.object({ label: z.string(), from_mm: point2, to_mm: point2, value_mm: num })), []),
  placement: z.object({ cx_mm: num, cy_mm: num, theta_deg: num }),
});
export type FitOutline = z.output<typeof FitOutlineSchema>;

export const FitCheckResultSchema = z.object({
  passed: z.boolean(),
  iou: num,
  // null when the photo could not be compared (e.g. no mat markers found); the reasons say why.
  hausdorff_mm: z.nullable(num),
  mean_mm: z.nullable(num),
  reasons: z._default(z.array(z.string()), []),
  overlay_url: z.nullish(z.string()),
  capture: CaptureReportSchema,
});
export type FitCheckResult = z.output<typeof FitCheckResultSchema>;

export const ReplaySchema = z.object({
  id: z.string(),
  title: z.string(),
  origin: DataOriginSchema,
  provider_mode: z.string(),
  verified: z.boolean(),
  max_error_mm: z.nullable(num),
  iterations: z.int(),
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
  max_error_mm: z.nullish(num),
  thumbnail_url: z.nullish(z.string()),
  params_count: z._default(z.int(), 0),
  topology_knobs: z._default(z.array(z.string()), []),
  verified: z.optional(z.boolean()),
  thumbnail_2x_url: z.nullish(z.string()),
  summary: z.nullish(z.string()),
  bbox_mm: z.nullish(z.tuple([num, num, num])),
  /** /matching only: why this part matches. */
  reason: z.nullish(z.string()),
});
export type PartCard = z.output<typeof PartCardSchema>;

export const PartListSchema = z.object({
  items: z.array(PartCardSchema),
  next_cursor: z.nullable(z.string()),
  total: z.int(),
});
export type PartList = z.output<typeof PartListSchema>;

export const ProvenanceSchema = z.object({
  origin: DataOriginSchema,
  job_id: z.nullish(z.string()),
  photo_shas: z._default(z.array(z.string()), []),
  builder_model: z.nullish(z.string()),
  provider_mode: z._default(ProviderModeSchema, "mock"),
  created_by: z._default(z.string(), "partsmith"),
  forked_from: z.nullish(z.string()),
  note: z._default(z.string(), ""),
});
export type Provenance = z.output<typeof ProvenanceSchema>;

export const LineageEntrySchema = z.object({
  slug: z.string(),
  version: z.int(),
  relation: z.enum(["forked_from", "variant_of"]),
  title: z._default(z.string(), ""),
});
export type LineageEntry = z.output<typeof LineageEntrySchema>;

/** The server's export-gate decision (`can_ship`), attached to part detail. */
export const ShipDecisionSchema = z.object({
  status: z.enum(["verified", "best_effort", "blocked"]),
  reason: z._default(z.string(), ""),
  needs_ack: z._default(z.boolean(), false),
  source: z._default(z.string(), ""),
});
export type ShipDecision = z.output<typeof ShipDecisionSchema>;

export const PartRecordSchema = z.object({
  id: z.string(),
  slug: z.string(),
  title: z.string(),
  family: z.string(),
  summary: z._default(z.string(), ""),
  tags: z._default(z.array(z.string()), []),
  version: z._default(z.int(), 1),
  status: PartStatusSchema,
  params: z.array(ParamSpecSchema),
  defaults: z.record(z.string(), num),
  code: z.string(),
  code_sha: z.string(),
  verification: z.nullish(VerificationSchema),
  provenance: ProvenanceSchema,
  facts: z.nullish(PartFactsSchema),
  licence: z._default(z.string(), "CC-BY-4.0"),
  created_at: z._default(num, 0),
  mating: z._default(z.array(z.string()), []),
  artifacts: z._default(z.record(z.string(), z.string()), {}),
  lineage: z._default(z.array(LineageEntrySchema), []),
  thumbnail_url: z.nullish(z.string()),
  thumbnail_2x_url: z.nullish(z.string()),
  facts_notes: z._default(z.record(z.string(), z.string()), {}),
  fit_reports: z._default(z.array(z.record(z.string(), z.unknown())), []),
  origin: z.optional(DataOriginSchema),
  verified: z.optional(z.boolean()),
  ship: z.optional(ShipDecisionSchema),
});
export type PartRecord = z.output<typeof PartRecordSchema>;

export const VariantResultSchema = z.object({
  params: z.record(z.string(), num),
  applied: z.array(z.string()),
  not_applied: z.array(z.string()),
  confidence: num,
  mode: ProviderModeSchema,
  bake_url: z.nullish(z.string()),
});
export type VariantResult = z.output<typeof VariantResultSchema>;

export const FamilySchema = z.object({ family: z.string(), title: z.string(), count: z.int(), verified: z.int() });
export type FamilyInfo = z.output<typeof FamilySchema>;

export const NeedSchema = z.object({
  id: z.string(),
  query: z.string(),
  votes: z._default(z.int(), 1),
  status: z._default(z.enum(["open", "in_progress", "fulfilled"]), "open"),
  created_at: z._default(num, 0),
  photo_url: z.nullish(z.string()),
  /** false when this client had already voted (one vote per client fingerprint). */
  counted: z.optional(z.boolean()),
});
export type Need = z.output<typeof NeedSchema>;

export const StatsSchema = z.object({
  parts: z.int(),
  verified: z.int(),
  synthetic: z.int(),
  real: z.int(),
  reference_object: z._default(z.int(), 0),
  jobs: z.int(),
  grams_pla: num,
});
export type Stats = z.output<typeof StatsSchema>;

// ── steer ─────────────────────────────────────────────────────────────────────
export const SteerLaneSchema = z.object({
  slug: z.string(),
  status: z.enum(["queued", "running", "done", "failed"]),
  job_id: z.nullish(z.string()),
  verified: z._default(z.boolean(), false),
  max_error_mm: z.nullish(num),
  error: z.nullish(z.string()),
});
export type SteerLane = z.output<typeof SteerLaneSchema>;

export const SteerQueueItemSchema = z.object({
  slug: z.string(),
  title: z.string(),
  family: z.string(),
  status: z.enum(["building", "pending_review", "published", "sent_back", "rejected", "failed"]),
  job_id: z.nullish(z.string()),
  verified: z._default(z.boolean(), false),
  max_error_mm: z.nullish(num),
  params: z._default(z.record(z.string(), num), {}),
  note: z.nullish(z.string()),
});
export type SteerQueueItem = z.output<typeof SteerQueueItemSchema>;

export const SteerStateSchema = z.object({
  id: z.string(),
  brief: z.string(),
  count: z.int(),
  status: z.enum(["planning", "building", "reviewing", "done", "failed"]),
  created_at: num,
  updated_at: num,
  family_title: z._default(z.string(), ""),
  planner: z.nullish(z.object({ provider: z.string(), model: z.string(), mode: z.string() })),
  plan_job_id: z.nullish(z.string()),
  plan_notes: z._default(z.array(z.string()), []),
  label: z._default(z.string(), ""),
  plan: z.array(
    z.object({
      slug: z.string(),
      title: z.string(),
      family: z.string(),
      template: z.nullish(z.string()),
      params: z._default(z.record(z.string(), num), {}),
      why: z.nullish(z.string()),
    }),
  ),
  lanes: z.array(SteerLaneSchema),
  queue: z._default(z.array(SteerQueueItemSchema), []),
  history: z._default(z.array(
      z.object({
        slug: z.string(),
        action: z.string(),
        note: z.nullish(z.string()),
        ts: num,
        applied: z.nullish(z.array(z.string())),
        not_applied: z.nullish(z.array(z.string())),
      }),
    ), []),
});
export type SteerState = z.output<typeof SteerStateSchema>;

export const SteerSummarySchema = z.object({
  id: z.string(),
  brief: z.string(),
  count: z.int(),
  status: z.string(),
  created_at: num,
  family_title: z._default(z.string(), ""),
  pending: z._default(z.int(), 0),
  published: z._default(z.int(), 0),
});
export type SteerSummary = z.output<typeof SteerSummarySchema>;

// ── bench ─────────────────────────────────────────────────────────────────────
/** Tables are produced by `eval/`; row cells are rendered generically, exactly as written. */
export const BenchTableSchema = z.object({
  n: z._default(z.int(), 0),
  ground_truth: GroundTruthSourceSchema,
  ci: z.optional(z.unknown()),
  columns: z._default(z.array(z.string()), []),
  rows: z._default(z.array(z.record(z.string(), z.unknown())), []),
  headline: z._default(z.record(z.string(), z.unknown()), {}),
  status: z._default(z.enum(["ok", "pending"]), "ok"),
  note: z._default(z.string(), ""),
  title: z.optional(z.string()),
});
export type BenchTable = z.output<typeof BenchTableSchema>;

export const BenchReportSchema = z.object({
  status: z.enum(["ok", "pending"]),
  generated_at: z.nullish(z.union([z.string(), num])),
  git_sha: z.nullish(z.string()),
  /** Provider mode the runs used and the report's honesty label, e.g. "pipeline check — mock providers". */
  mode: z.nullish(z.string()),
  label: z.nullish(z.string()),
  notes: z._default(z.array(z.string()), []),
  tables: z.record(z.string(), BenchTableSchema),
  runs: z.optional(z.unknown()),
  failures: z._default(z.array(z.looseObject({ title: z.string(), reason: z.string(), overlay_url: z.nullish(z.string()) })), []),
});
export type BenchReport = z.output<typeof BenchReportSchema>;

// ── misc ──────────────────────────────────────────────────────────────────────
export const DemoSampleSchema = z.object({
  id: z.string(),
  title: z.string(),
  family_hint: z.nullish(z.string()),
  kind: z.enum(["template", "reference_object"]),
});
export type DemoSample = z.output<typeof DemoSampleSchema>;

export const TranscribeResultSchema = z.object({
  text: z.string(),
  mode: ProviderModeSchema,
  language: z.nullish(z.string()),
  model: z.string(),
  note: z._default(z.string(), ""),
});
export type TranscribeResult = z.output<typeof TranscribeResultSchema>;

export const FeedbackResultSchema = z.object({ id: z.string(), slug: z.string(), result: z.string(), kind: z.string() });
