/**
 * Pure helpers that shape API lists for display: lessons grouped by family with duplicates folded, the jobs list summary
 * and filters, the feedback log grouped by part, and whether an origin is reachable from a phone. No React and only type
 * imports, so `node --test` loads it directly. Every number comes from the records passed in; nothing is estimated.
 */
import type { FeedbackEntry, JobSummary } from "./api-types";

// ── origins ───────────────────────────────────────────────────────────────────
/** True for origins only this computer can reach (a QR code for them would never open on a phone). */
export function isLocalOrigin(origin: string): boolean {
  try {
    const host = new URL(origin).hostname.replace(/^\[|\]$/g, "");
    return host === "localhost" || host.endsWith(".localhost") || host === "0.0.0.0" || host === "::1" || /^127\./.test(host);
  } catch {
    return false;
  }
}

// ── lessons ───────────────────────────────────────────────────────────────────
/** The fields of a lesson this module reads (structurally the `Lesson` type from api-r2). */
export type LessonLike = {
  id: string;
  scope: string;
  rule: string;
  status: string;
  created_at: number;
  evidence: Record<string, unknown>;
  links: { kind: string; id: string; page: string }[];
};

/** One card: lessons that say the same thing (same status, scope and rule, or the same template knob), newest first. */
export type LessonGroup<L extends LessonLike> = { key: string; lead: L; members: L[] };
export type LessonFamily<L extends LessonLike> = { scope: string; groups: LessonGroup<L>[]; lessons: number };

const str = (v: unknown): string | null => (typeof v === "string" && v ? v : null);

/**
 * Two lessons fold into one card when they share status and scope and either repeat the same rule text or point at the
 * same template knob (`evidence.template` + `evidence.param`): "check corner_radius" suggested by three runs is one card.
 */
export function lessonKey(l: LessonLike): string {
  const template = str(l.evidence.template);
  const param = str(l.evidence.param);
  const what = template && param ? `knob:${template}.${param}` : `rule:${l.rule.trim().replace(/\s+/g, " ").toLowerCase()}`;
  return `${l.status}|${l.scope}|${what}`;
}

/** Groups (newest lead first, larger groups first) inside families (most lessons first, then by name). */
export function groupLessons<L extends LessonLike>(list: readonly L[]): LessonFamily<L>[] {
  const groups = new Map<string, L[]>();
  for (const l of list) {
    const k = lessonKey(l);
    const g = groups.get(k);
    if (g) g.push(l);
    else groups.set(k, [l]);
  }
  const families = new Map<string, LessonGroup<L>[]>();
  for (const [key, members] of groups) {
    const sorted = [...members].sort((a, b) => b.created_at - a.created_at);
    const g: LessonGroup<L> = { key, lead: sorted[0]!, members: sorted };
    const scope = sorted[0]!.scope;
    const f = families.get(scope);
    if (f) f.push(g);
    else families.set(scope, [g]);
  }
  return [...families.entries()]
    .map(([scope, gs]) => ({
      scope,
      groups: gs.sort((a, b) => b.members.length - a.members.length || b.lead.created_at - a.lead.created_at),
      lessons: gs.reduce((n, g) => n + g.members.length, 0),
    }))
    .sort((a, b) => b.lessons - a.lessons || a.scope.localeCompare(b.scope));
}

/** One run behind a knob lesson: the knob's first-build and final value, and how that run ended (from its evidence). */
export type KnobRun = { id: string; job: string | null; page: string | null; first: number; final: number; verified: boolean | null; maxErrorMm: number | null };

/** The runs behind a knob lesson card, one row per member that records a first → final move, newest first. */
export function knobRuns(members: readonly LessonLike[]): KnobRun[] {
  const out: KnobRun[] = [];
  for (const m of members) {
    const { first, final, verified, max_error_mm: gap, job_id } = m.evidence;
    if (typeof first !== "number" || typeof final !== "number") continue;
    const link = m.links.find((l) => l.kind === "job");
    out.push({
      id: m.id,
      job: str(job_id) ?? link?.id ?? null,
      page: link?.page || null,
      first,
      final,
      verified: typeof verified === "boolean" ? verified : null,
      maxErrorMm: typeof gap === "number" ? gap : null,
    });
  }
  return out;
}

/** "cable_clip" → "Cable Clip" (template and family names as people read them). */
export function humanName(s: string): string {
  return s.replace(/[_-]+/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

/** How a run ended, in words that follow its status: never "verified" for a best-effort run. */
export function runEnding(r: Pick<KnobRun, "verified" | "maxErrorMm">): string {
  const gap = r.maxErrorMm != null ? ` (max gap ${r.maxErrorMm.toFixed(2)} mm)` : "";
  if (r.verified === true) return `a run that passed verification${gap}`;
  if (r.verified === false) return `a run that ended best effort${gap}, so the final value is not confirmed`;
  return "one run";
}

/**
 * A lesson's wording for the page. A knob lesson that code wrote ("…: the first build set <knob> = …") is re-said from
 * its evidence (template and knob by their names, the move, and how that run actually ended), so a stored sentence that
 * called a best-effort run "verified" never shows. Other lessons (a person's wording) keep their text, with a leading
 * snake_case template name made readable.
 */
export function lessonText(l: Pick<LessonLike, "rule" | "evidence">, knobLabel?: string): string {
  const { template, param, first, final } = l.evidence;
  const codeWritten = /the first build set /.test(l.rule);
  if (codeWritten && typeof param === "string" && typeof first === "number" && typeof final === "number") {
    const [run] = knobRuns([{ id: "", scope: "", rule: "", status: "", created_at: 0, evidence: l.evidence, links: [] }]);
    const knob = knobLabel || humanName(param);
    const d = final - first;
    const who = str(template) ? `${humanName(str(template)!)}: ` : "";
    return `${who}the first build set ${knob} = ${trim(first)}; the fix loop moved it to ${trim(final)} (${d >= 0 ? "+" : "−"}${Math.abs(d).toFixed(2)}) in ${runEnding(run!)}. Check ${knob} against the measurement before building.`;
  }
  return l.rule.replace(/^([a-z0-9]+(?:_[a-z0-9]+)+):/, (_, n: string) => `${humanName(n)}:`);
}

const trim = (v: number) => String(Number(v.toFixed(2)));

/** Evidence links across a group's members, without repeats, in member order. */
export function groupLinks<L extends LessonLike>(members: readonly L[]): L["links"] {
  const seen = new Set<string>();
  const out: L["links"] = [];
  for (const m of members)
    for (const e of m.links) {
      const k = `${e.kind}:${e.id}`;
      if (!seen.has(k)) {
        seen.add(k);
        out.push(e);
      }
    }
  return out;
}

// ── jobs ──────────────────────────────────────────────────────────────────────
export type JobBucket = "verified" | "best_effort" | "failed" | "in_progress";
export type JobSource = "recorded" | "server";
type JobLike = Pick<JobSummary, "status" | "verified" | "max_error_mm" | "is_replay" | "origin">;

export const JOB_BUCKETS: readonly { id: JobBucket; label: string }[] = [
  { id: "verified", label: "Verified" },
  { id: "best_effort", label: "Best effort" },
  { id: "failed", label: "Failed" },
  { id: "in_progress", label: "In progress" },
];

/** Verified and best effort are finished jobs; failed and cancelled jobs are "failed"; anything else is still going. */
export function jobBucket(j: JobLike): JobBucket {
  if (j.status === "done") return j.verified ? "verified" : "best_effort";
  if (j.status === "failed" || j.status === "cancelled") return "failed";
  return "in_progress";
}

/** A recorded run (replayed from a stored log) or a job this server ran. */
export function jobSource(j: JobLike): JobSource {
  return j.is_replay || j.origin === "replay" ? "recorded" : "server";
}

export function median(values: readonly number[]): number | null {
  const v = values.filter(Number.isFinite).sort((a, b) => a - b);
  if (!v.length) return null;
  const mid = Math.floor(v.length / 2);
  return v.length % 2 ? v[mid]! : (v[mid - 1]! + v[mid]!) / 2;
}

export type JobsSummary = { n: number; verified: number; bucket: Record<JobBucket, number>; source: Record<JobSource, number>; medianMaxGapMm: number | null; gapN: number };

/** Counts and the median max gap over finished jobs that report one (all from the list itself). */
export function jobsSummary(list: readonly JobLike[]): JobsSummary {
  const bucket: Record<JobBucket, number> = { verified: 0, best_effort: 0, failed: 0, in_progress: 0 };
  const source: Record<JobSource, number> = { recorded: 0, server: 0 };
  const gaps: number[] = [];
  for (const j of list) {
    bucket[jobBucket(j)] += 1;
    source[jobSource(j)] += 1;
    if (j.status === "done" && j.max_error_mm != null && Number.isFinite(j.max_error_mm)) gaps.push(j.max_error_mm);
  }
  return { n: list.length, verified: bucket.verified, bucket, source, medianMaxGapMm: median(gaps), gapN: gaps.length };
}

export function jobsSummaryText(s: JobsSummary): string {
  const parts = [`${s.verified} of ${s.n} verified`];
  if (s.medianMaxGapMm != null) parts.push(`median max gap ${s.medianMaxGapMm.toFixed(2)} mm (${s.gapN} finished job${s.gapN === 1 ? "" : "s"})`);
  return parts.join(" · ");
}

/** URL filter values; unknown values read as "all". */
export function parseJobFilter(status: string | null, source: string | null): { status: JobBucket | null; source: JobSource | null } {
  return {
    status: JOB_BUCKETS.some((b) => b.id === status) ? (status as JobBucket) : null,
    source: source === "recorded" || source === "server" ? source : null,
  };
}

export function filterJobs<J extends JobLike>(list: readonly J[], f: { status: JobBucket | null; source: JobSource | null }): J[] {
  return list.filter((j) => (!f.status || jobBucket(j) === f.status) && (!f.source || jobSource(j) === f.source));
}

// ── feedback log ──────────────────────────────────────────────────────────────
type FeedbackLike = Pick<FeedbackEntry, "id" | "root_job" | "round" | "title" | "family" | "by" | "before_mm" | "after_mm" | "limit_mm" | "at"> & {
  verdict?: { max_error_mm?: number | null } | null;
  next_verdict?: { max_error_mm?: number | null } | null;
};
export type FeedbackRound = { round: number; before_mm: number | null; after_mm: number | null };
export type FeedbackBlock<E extends FeedbackLike> = { root: string; title: string; family: string | null; entries: E[]; rounds: FeedbackRound[]; limit_mm: number; latest: number };

/**
 * One block per root job (newest activity first); entries inside in round order. Per round, the worst gap of the
 * reviewed model (its verdict) → the worst gap of the model the feedback started (next round's verdict); entries
 * without verdicts fall back to the gap measured at their own pin.
 */
export function groupFeedback<E extends FeedbackLike>(items: readonly E[]): FeedbackBlock<E>[] {
  const by = new Map<string, E[]>();
  for (const e of items) {
    const g = by.get(e.root_job);
    if (g) g.push(e);
    else by.set(e.root_job, [e]);
  }
  const blocks: FeedbackBlock<E>[] = [];
  for (const [root, list] of by) {
    const entries = [...list].sort((a, b) => a.round - b.round || (a.at ?? 0) - (b.at ?? 0));
    const rounds: FeedbackRound[] = [];
    for (const e of entries) {
      const before = e.verdict?.max_error_mm ?? e.before_mm ?? null;
      const after = e.next_verdict?.max_error_mm ?? e.after_mm ?? null;
      const last = rounds.at(-1);
      if (last && last.round === e.round) {
        last.before_mm ??= before;
        last.after_mm ??= after;
      } else rounds.push({ round: e.round, before_mm: before, after_mm: after });
    }
    const head = entries[0]!;
    blocks.push({
      root,
      title: (head.title || root).replace(/\s*·\s*review round \d+$/, ""),
      family: head.family ?? null,
      entries,
      rounds,
      limit_mm: head.limit_mm,
      latest: Math.max(...entries.map((e) => e.at ?? 0)),
    });
  }
  return blocks.sort((a, b) => b.latest - a.latest);
}

/** True when every entry came from a scripted test reviewer (then one banner replaces a badge on each row). */
export function allTests(items: readonly Pick<FeedbackEntry, "by">[]): boolean {
  return items.length > 0 && items.every((e) => e.by !== "person");
}
