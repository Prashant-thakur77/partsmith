/**
 * Pure helpers for the human review page: pin coordinates, scorecard and agreement text, queue order, the decision body.
 * No React and no runtime imports, so `node --test` loads it directly. Every number shown here is passed in from the API;
 * nothing is estimated in the browser.
 */
import type { DecisionBody, ReviewAction } from "./api-review";
import type { Judge, JudgeCriterion, JobEvent, LessonTrack, ReviewPin, ReviewQueueItem, ReviewStats, ReviewVerdict } from "./api-types";

export const CRITERIA: readonly { id: JudgeCriterion; label: string }[] = [
  { id: "outline", label: "Outline" },
  { id: "features", label: "Features" },
  { id: "printability", label: "Printability" },
  { id: "fit", label: "Fit for use" },
];

const mm = (v: number) => v.toFixed(2);
/** Same rule as format.ts `fmtErr` (this file stays import-free for node --test): 3 decimals within 0.01 mm of the 0.5 mm limit. */
const errMm = (v: number) => {
  const d = Math.abs(v - 0.5) < 0.01 ? 3 : 2;
  return v.toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d });
};

// ── pins ──────────────────────────────────────────────────────────────────────
/** The rendered image box on screen (what `getBoundingClientRect()` returns for the <img>). */
export type Box = { left: number; top: number; width: number; height: number };

/** A pin being placed by the reviewer; `key` is a stable React key, the shown number is its position + 1. */
export type DraftPin = { key: number; u: number; v: number; note: string };

const round4 = (x: number) => Math.round(x * 10_000) / 10_000;
const clamp01 = (x: number) => Math.min(1, Math.max(0, x));

/**
 * Normalised (u, v) of a screen point on the rendered image: 0–1 from the image's left/top edge. Because it divides by
 * the rendered box, CSS scaling or zoom does not change the result. `null` for a point outside the image or an empty box.
 */
export function uvFromPoint(x: number, y: number, box: Box): { u: number; v: number } | null {
  if (!(box.width > 0 && box.height > 0)) return null;
  const u = (x - box.left) / box.width;
  const v = (y - box.top) / box.height;
  if (u < 0 || u > 1 || v < 0 || v > 1) return null;
  return { u: round4(u), v: round4(v) };
}

/** Same as `uvFromPoint` but clamped to the image edge (for dragging a pin past the border). */
export function uvClamped(x: number, y: number, box: Box): { u: number; v: number } | null {
  if (!(box.width > 0 && box.height > 0)) return null;
  return { u: round4(clamp01((x - box.left) / box.width)), v: round4(clamp01((y - box.top) / box.height)) };
}

/** Arrow-key nudge of a pin: 1 % of the image per press, 5 % with Shift; stays inside the image. */
export function nudge(p: { u: number; v: number }, key: string, big = false): { u: number; v: number } | null {
  const step = big ? 0.05 : 0.01;
  const d: Record<string, [number, number]> = { ArrowLeft: [-step, 0], ArrowRight: [step, 0], ArrowUp: [0, -step], ArrowDown: [0, step] };
  const m = d[key];
  if (!m) return null;
  return { u: round4(clamp01(p.u + m[0])), v: round4(clamp01(p.v + m[1])) };
}

/** How to show only the part's box of the photo: the frame's aspect ratio and where the full image sits inside it
 * (percent of the frame). `null` when there is no usable box or it already covers most of the image. Pins stay on the
 * full image's own box, so (u, v) never depend on the zoom. */
export type Zoom = { aspect: number; left: number; top: number; width: number };

export function zoomFrame(focus: readonly number[] | null | undefined, natural: { w: number; h: number } | null): Zoom | null {
  if (!focus || focus.length !== 4 || !natural || !(natural.w > 0 && natural.h > 0)) return null;
  const [u0, v0, u1, v1] = focus.map(clamp01) as [number, number, number, number];
  const du = u1 - u0;
  const dv = v1 - v0;
  if (!(du > 0.02 && dv > 0.02) || (du > 0.8 && dv > 0.8)) return null;
  return { aspect: (du * natural.w) / (dv * natural.h), left: (-u0 / du) * 100, top: (-v0 / dv) * 100, width: 100 / du };
}

/** "0.84 → 0.21 mm" from the server's local mismatch before and after the reviewer round. */
export function pinOutcome(p: Pick<ReviewPin, "before_mm" | "after_mm">): string {
  const b = p.before_mm;
  const a = p.after_mm;
  if (b == null && a == null) return "not measurable here";
  if (b != null && a != null) return `${mm(b)} → ${mm(a)} mm`;
  if (b != null) return `${mm(b)} mm before · after not measured`;
  return `before not measured · ${mm(a!)} mm after`;
}

// ── verdict, judge, agreement ─────────────────────────────────────────────────
/** "verified · 0.31 mm" — the verifier's status and max error as the API sent them. */
export function verdictText(v: ReviewVerdict | null | undefined): string {
  if (!v) return "no verdict yet";
  const status = v.status.replaceAll("_", " ");
  return v.max_error_mm != null ? `${status} · ${errMm(v.max_error_mm)} mm` : status;
}

export function verdictTone(v: ReviewVerdict | null | undefined): "ok" | "warn" | "bad" | "neutral" {
  if (!v) return "neutral";
  return v.status === "verified" ? "ok" : v.status === "best_effort" ? "warn" : v.status === "failed" ? "bad" : "neutral";
}

/** One line for a scorecard: "outline 4 · features 3 · printability 5 · fit 4 · 1 blocking veto". */
/** How the judge stage ran on a job, from its own `model_call` events (the last judge call); null when it did not run. */
export type JudgeRun = { mode: string; model: string };

export function judgeRunFromEvents(events: readonly JobEvent[] | null | undefined): JudgeRun | null {
  let out: JudgeRun | null = null;
  for (const e of events ?? []) if (e.t === "model_call" && e.stage === "judge") out = { mode: e.mode, model: e.model };
  return out;
}

/** "judge: mock (rule-based)" when the judge was the deterministic stand-in (no model looked at the part), else "". */
export function judgeModeLine(j: Judge | null | undefined, ran?: JudgeRun | null): string {
  const mode = j?.mode ?? ran?.mode;
  return mode === "mock" ? "judge: mock (rule-based)" : mode === "replay" ? "judge: recorded run (replay)" : "";
}

/** The one-line scorecard ("outline 4 · features 3 · …"), led by "mock (rule-based)" when no model judged; callers
 * label it "Judge" / "judge:". */
export function scorecardSummary(j: Judge | null | undefined, ran?: JudgeRun | null): string {
  const line = judgeModeLine(j, ran).replace(/^judge: /, "");
  const body = scorecardBody(j, ran);
  return line ? `${line} · ${body}` : body;
}

function scorecardBody(j: Judge | null | undefined, ran?: JudgeRun | null): string {
  if (!j) return ran ? "no scorecard saved" : "no scorecard";
  const by = new Map(j.scores.map((s) => [s.criterion, s.score]));
  const parts = CRITERIA.filter((c) => by.has(c.id)).map((c) => `${c.id} ${by.get(c.id)}`);
  const blocking = j.vetoes.filter((v) => v.severity === "blocking").length;
  const minor = j.vetoes.length - blocking;
  if (blocking) parts.push(`${blocking} blocking veto${blocking === 1 ? "" : "es"}`);
  if (minor) parts.push(`${minor} minor veto${minor === 1 ? "" : "es"}`);
  return parts.length ? parts.join(" · ") : "no scores";
}

export function scoreTone(score: number): "ok" | "warn" | "bad" {
  return score >= 4 ? "ok" : score === 3 ? "warn" : "bad";
}

/** "Judge agreed with the reviewer in 3/4 reviews (κ 0.50)"; null until at least one review counts. */
export function agreementText(s: ReviewStats | null | undefined): string | null {
  if (!s || s.n < 1) return null;
  const kappa = s.kappa != null ? ` (κ ${s.kappa.toFixed(2)})` : "";
  return `Judge agreed with the reviewer in ${s.agree}/${s.n} review${s.n === 1 ? "" : "s"}${kappa}`;
}

export function reviewersLabel(n: number): string {
  return `${n} reviewer${n === 1 ? "" : "s"}`;
}

// ── queue ─────────────────────────────────────────────────────────────────────
const RANK: Record<string, number> = { waiting: 0, improving: 1, accepted: 2, rejected: 2 };

/** Waiting first, then running reviewer rounds, then decided chains; newest first inside each group. */
export function sortQueue<T extends Pick<ReviewQueueItem, "status" | "updated_at" | "job_id">>(items: readonly T[]): T[] {
  return [...items].sort((a, b) => (RANK[a.status] ?? 3) - (RANK[b.status] ?? 3) || b.updated_at - a.updated_at || a.job_id.localeCompare(b.job_id));
}

export function waitingCount(items: readonly Pick<ReviewQueueItem, "status">[]): number {
  return items.filter((i) => i.status === "waiting").length;
}

export function roundLabel(n: number): string {
  return `round ${n}`;
}

export const DECISION_LABEL: Record<string, string> = { accept: "accepted", improve: "sent back", reject: "rejected" };

// ── decisions ─────────────────────────────────────────────────────────────────
export type DecisionDraft = {
  pins: readonly DraftPin[];
  note: string;
  reason: string;
  rules?: readonly { text: string; keep: boolean; source_pin: number | null }[];
  publish?: boolean;
  /** Uploaded attachment keys (pasted screenshots). */
  attachments?: readonly string[];
  /** Why it matters (optional, any action). */
  why?: string;
};

/** Why a decision cannot be sent yet (null when it can). Improve needs a pin or a note; reject needs a reason. */
export function blocker(action: ReviewAction, d: Pick<DecisionDraft, "pins" | "note" | "reason" | "attachments">): string | null {
  if (action === "improve" && d.pins.length === 0 && !d.note.trim() && !d.attachments?.length) return "Add a pin on the photo, a note or a screenshot first.";
  if (action === "reject" && !d.reason.trim()) return "Write a short reason.";
  return null;
}

/** The POST body for a decision; only the fields that action uses are filled. */
export function decisionBody(action: ReviewAction, d: DecisionDraft): DecisionBody {
  return {
    action,
    pins: action === "improve" ? d.pins.map((p) => ({ u: p.u, v: p.v, note: p.note.trim() })) : [],
    note: action === "improve" || action === "accept" ? d.note.trim() : "",
    reason: action === "reject" ? d.reason.trim() : "",
    rules: action === "accept" ? (d.rules ?? []).filter((r) => r.text.trim()).map((r) => ({ text: r.text.trim(), keep: r.keep, source_pin: r.source_pin })) : [],
    publish: action === "accept" ? !!d.publish : false,
    attachments: action === "improve" ? [...(d.attachments ?? [])] : [],
    why: (d.why ?? "").trim(),
  };
}

// ── agents and lessons ────────────────────────────────────────────────────────
export type AgentRow = { stage: string; model: string; mode: string; calls: number; failed: number; usd: number; ms: number };

/** Model calls grouped by stage and model, in the order they first ran (from the job's own `model_call` events). */
export function agentRows(events: readonly JobEvent[]): AgentRow[] {
  const rows = new Map<string, AgentRow>();
  for (const e of events) {
    if (e.t !== "model_call") continue;
    const k = `${e.stage}\u0000${e.model}`;
    const r = rows.get(k) ?? { stage: e.stage, model: e.model, mode: e.mode, calls: 0, failed: 0, usd: 0, ms: 0 };
    r.calls += 1;
    r.failed += e.ok ? 0 : 1;
    r.usd += e.usd;
    r.ms += e.ms;
    rows.set(k, r);
  }
  return [...rows.values()];
}

/** "Used in 3 jobs · later reviews: 1 accepted, 1 improved, 0 rejected" from the server's track record. */
export function trackText(t: LessonTrack | null | undefined): string | null {
  if (!t) return null;
  if (t.used_in === 0) return "Not used in a job yet";
  const used = `Used in ${t.used_in} job${t.used_in === 1 ? "" : "s"}`;
  const reviewed = t.accepted + t.improved + t.rejected;
  if (!reviewed) return `${used} · no reviews of those jobs yet`;
  return `${used} · later reviews: ${t.accepted} accepted, ${t.improved} sent back, ${t.rejected} rejected`;
}

// ── feedback log ──────────────────────────────────────────────────────────────
export const OUTCOME_LABEL: Record<string, string> = {
  fixed: "fixed",
  better: "better, not fixed",
  not_fixed: "not fixed",
  waiting: "next round running",
  not_measured: "not measured",
  rejected: "rejected",
  accepted: "accepted",
};

export function outcomeTone(o: string): "ok" | "warn" | "bad" | "info" | "neutral" {
  return o === "fixed" || o === "accepted" ? "ok" : o === "better" ? "warn" : o === "not_fixed" ? "bad" : o === "waiting" ? "info" : "neutral";
}

export const KIND_LABEL: Record<string, string> = { pin: "Pin on the photo", note: "Note", picture: "Picture", reject: "Rejected", accept: "Accepted" };

/** "12 pieces of feedback · 5 fixed · 2 better · 1 not fixed" from the API's counts, in a fixed order. */
export function feedbackSummary(counts: Record<string, number>): string {
  const total = Object.values(counts).reduce((a, b) => a + b, 0);
  const parts = ["fixed", "better", "not_fixed", "waiting", "rejected", "accepted"].filter((k) => counts[k]).map((k) => `${counts[k]} ${OUTCOME_LABEL[k]}`);
  return [`${total} piece${total === 1 ? "" : "s"} of feedback`, ...parts].join(" · ");
}

/** "Given to 2 later jobs · their reviews: 1 accepted, 1 sent back" — whether the lesson held. */
export function usedText(u: { jobs: number; accepted: number; improved: number; rejected: number }): string | null {
  if (!u.jobs) return null;
  const reviewed = u.accepted + u.improved + u.rejected;
  const head = `Given to ${u.jobs} later job${u.jobs === 1 ? "" : "s"}`;
  return reviewed ? `${head} · their reviews: ${u.accepted} accepted, ${u.improved} sent back, ${u.rejected} rejected` : `${head} · not reviewed yet`;
}
