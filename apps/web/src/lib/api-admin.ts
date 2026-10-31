/**
 * Admin console contract (`/api/v1/admin/*`, docs/API.md "Admin console") and the pure helpers its page uses.
 * Only `zod/mini` is imported here, so `node --test` loads this file directly. Every number the console shows is read
 * from these responses; nothing is estimated in the browser.
 */
import { z } from "zod/mini";

export const ADMIN_API = {
  overview: "/admin/overview",
  audit: "/admin/audit",
  parts: "/admin/parts",
  unpublish: "/admin/parts/{slug}/unpublish",
  republish: "/admin/parts/{slug}/republish",
  rules: "/admin/rules",
  disable: "/admin/rules/{rule_id}/disable",
  enable: "/admin/rules/{rule_id}/enable",
  demand: "/demand",
  needs: "/needs",
} as const;

const num = z.number();
const optNum = z.nullish(z.number());
const source = z._default(z.string(), "");

// ── overview ──────────────────────────────────────────────────────────────────
const ReasonsSchema = z.object({ n: num, top: z.array(z.object({ reason: z.string(), count: num })) });
export const BudgetSchema = z.object({
  day: z.string(),
  cap_usd: optNum,
  spent_usd: num,
  remaining_usd: optNum,
  calls: z._default(num, 0),
  by_stage: z._default(z.record(z.string(), num), {}),
  source,
});
export type Budget = z.output<typeof BudgetSchema>;

export const AdminOverviewSchema = z.object({
  generated_at: num,
  mode: z._default(z.string(), "mock"),
  jobs: z.object({ total: num, finished: num, verified: num, pass_rate: optNum, n: num, replays_excluded: z._default(num, 0), source }),
  rounds_to_verify: z.object({ buckets: z.array(z.object({ rounds: num, count: num })), median: optNum, n: num, source }),
  max_error: z.object({ median_mm: optNum, p90_mm: optNum, n: num, source }),
  send_back: z.object({ person: ReasonsSchema, test: ReasonsSchema, source }),
  review: z.object({ waiting: num, improving: num, accepted: num, rejected: num, waiting_replays: z._default(num, 0), n: num, source }),
  registry: z.object({ published: num, withdrawn: num, reference: num, n: num, source }),
  needs: z.object({ open: num, in_progress: num, fulfilled: num, n: num, source }),
  cost: z.object({
    usd_total: num,
    usd_per_job_mean: optNum,
    n_jobs: num,
    by_stage: z.array(z.object({ stage: z.string(), calls: num, usd: num })),
    by_model: z.array(z.object({ provider: z.string(), model: z.string(), calls: num, usd: num, modes: z._default(z.array(z.string()), []) })),
    source,
  }),
  /** Today's spend against the daily cap (newer APIs; missing reads as null). */
  budget: z.catch(z.nullish(BudgetSchema), null),
});
export type AdminOverview = z.output<typeof AdminOverviewSchema>;

// ── audit ─────────────────────────────────────────────────────────────────────
export const AuditEntrySchema = z.object({
  id: z._default(z.string(), ""),
  at: num,
  action: z.string(),
  target: z.string(),
  actor: z._default(z.string(), ""),
  before: z.optional(z.unknown()),
  after: z.optional(z.unknown()),
  note: z.nullish(z.string()),
  numbers: z.nullish(z.record(z.string(), z.unknown())),
});
export type AuditEntry = z.output<typeof AuditEntrySchema>;
export const AuditLogSchema = z.object({ items: z.array(AuditEntrySchema), total: num, actions: z._default(z.array(z.string()), []), source });

// ── parts (moderation) ────────────────────────────────────────────────────────
const WithdrawalSchema = z.object({ reason: z.string(), by: z._default(z.string(), ""), at: num });
export const CriterionSchema = z.object({
  key: z.string(),
  label: z.string(),
  ok: z.nullable(z.boolean()),
  value: z.optional(z.unknown()),
  source,
});
export type Criterion = z.output<typeof CriterionSchema>;
export const AdminPartSchema = z.object({
  slug: z.string(),
  title: z.string(),
  family: z.string(),
  status: z.string(),
  origin: z._default(z.string(), ""),
  reference: z._default(z.boolean(), false),
  created_at: z._default(num, 0),
  criteria: z.array(CriterionSchema),
  met: num,
  checked: num,
  withdrawn: z.nullish(WithdrawalSchema),
});
export type AdminPart = z.output<typeof AdminPartSchema>;
export const AdminPartsSchema = z.object({ items: z.array(AdminPartSchema), n: num, withdrawn: num, source });
export const ModerationResultSchema = z.object({ slug: z.string(), withdrawn: z.nullish(WithdrawalSchema) });

// ── taught rules ──────────────────────────────────────────────────────────────
const TrackSchema = z.object({ used_in: num, accepted: num, improved: num, rejected: num });
export const TaughtRuleSchema = z.object({
  id: z.string(),
  kind: z.enum(["rule", "feedback"]),
  family: z.string(),
  text: z.string(),
  why: z._default(z.string(), ""),
  by: z.nullish(z.string()),
  created_at: optNum,
  origin_job: z.nullish(z.string()),
  used_in: z.array(z.string()),
  track: TrackSchema,
  disabled: z.nullish(WithdrawalSchema),
});
export type TaughtRule = z.output<typeof TaughtRuleSchema>;
export const TaughtRulesSchema = z.object({ items: z.array(TaughtRuleSchema), n: num, disabled: num, source });

// ── demand (GET /demand, served by newer APIs only) ──────────────────────────
export const MissedSearchSchema = z.object({
  q: z.string(),
  count: num,
  best_coverage: z.catch(z.nullish(num), null),
  /** ISO 8601 time of the latest such search. */
  last_at: z.nullish(z.string()),
});
export type MissedSearch = z.output<typeof MissedSearchSchema>;
export const DemandSchema = z.object({ needs: z._default(z.array(z.unknown()), []), missed_searches: z._default(z.array(MissedSearchSchema), []) });

// ── pure helpers ──────────────────────────────────────────────────────────────
export const ADMIN_TABS = [
  { id: "overview", label: "Overview" },
  { id: "parts", label: "Parts" },
  { id: "rules", label: "Rules" },
  { id: "audit", label: "Audit" },
  { id: "demand", label: "Demand" },
] as const;
export type AdminTab = (typeof ADMIN_TABS)[number]["id"];

/** The tab named in `?tab=`, or Overview for anything else. */
export function tabFromParam(v: string | null | undefined): AdminTab {
  return ADMIN_TABS.find((t) => t.id === v)?.id ?? "overview";
}

/** Spend against the cap as a bar: share 0..1 (clamped), a plain label, and whether the cap is reached. */
export function budgetBar(b: Budget | null | undefined): { share: number | null; label: string; over: boolean } {
  if (!b) return { share: null, label: "This server does not report a spend cap.", over: false };
  const spent = `$${b.spent_usd.toFixed(2)}`;
  if (b.cap_usd == null) return { share: null, label: `No cap set. Spent ${spent} today (${b.day} UTC).`, over: false };
  const share = b.cap_usd > 0 ? Math.min(1, b.spent_usd / b.cap_usd) : 1;
  const over = b.spent_usd >= b.cap_usd;
  return { share, label: `${spent} of $${b.cap_usd.toFixed(2)} spent today (${b.day} UTC)${over ? ". Live calls are paused." : "."}`, over };
}

/** Bar widths as shares of the largest value (0..1); all zero when every value is zero. */
export function shares(values: readonly number[]): number[] {
  const max = Math.max(0, ...values);
  return values.map((v) => (max > 0 ? Math.max(0, v) / max : 0));
}

/** "4 of 5 checks met" — counts only checks code could evaluate (ok is not null). */
export function criteriaLine(p: Pick<AdminPart, "met" | "checked">): string {
  return `${p.met} of ${p.checked} check${p.checked === 1 ? "" : "s"} met`;
}

/** A criterion's value in plain words (numbers straight from the response). */
export function criterionValue(c: Criterion): string {
  const v = c.value;
  if (v == null) return "—";
  if (typeof v === "number" || typeof v === "boolean") return String(v);
  if (typeof v === "string") return v.replaceAll("_", " ");
  if (typeof v === "object") {
    const o = v as Record<string, unknown>;
    if ("max_error_mm" in o) {
      const e = typeof o.max_error_mm === "number" ? `${o.max_error_mm.toFixed(2)} mm` : "not measured";
      const l = typeof o.limit_mm === "number" ? `${o.limit_mm.toFixed(2)} mm` : "no limit";
      return `${e} (limit ${l})`;
    }
    if ("job_id" in o) return `job ${String(o.job_id)}`;
  }
  return "—";
}

/** Text for a rule's track record, or null when no job has used it yet. */
export function ruleTrack(r: Pick<TaughtRule, "track">): string | null {
  const t = r.track;
  if (!t.used_in) return null;
  return `Given to ${t.used_in} job${t.used_in === 1 ? "" : "s"}; later reviews: ${t.accepted} accepted, ${t.improved} sent back, ${t.rejected} rejected.`;
}

/** Percent with one decimal, or "—" for null. */
export function pct(v: number | null | undefined): string {
  return v == null ? "—" : `${(v * 100).toFixed(1)}%`;
}

/** A short JSON-ish summary of an audit entry's before/after value. */
export function changeText(v: unknown): string {
  if (v == null) return "—";
  if (typeof v !== "object") return String(v);
  const parts = Object.entries(v as Record<string, unknown>).map(([k, x]) => {
    if (x == null) return `${k}: none`;
    if (typeof x === "object") {
      const r = (x as Record<string, unknown>).reason;
      return typeof r === "string" ? `${k}: "${r}"` : `${k}: yes`;
    }
    return `${k}: ${String(x)}`;
  });
  return parts.join(", ") || "—";
}

export const path = (tpl: string, key: string, id: string) => tpl.replace(`{${key}}`, encodeURIComponent(id));
