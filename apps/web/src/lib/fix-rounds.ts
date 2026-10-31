/**
 * Fail → fix history: one entry per build round, read only from the job's own events. A round is the `iteration` event
 * the orchestrator emits after each verify (`iter` 1 is the first build, 2… are fix rounds), with
 *  - the error: the `max_error_mm` metric of that round (the verifier's max error), else the round's Hausdorff;
 *  - per view: Hausdorff and IoU as the server wrote them (verify stage label and the next `inspect_residuals` result),
 *    each compared with the Hausdorff limit the server sent on the `hausdorff_mm` metric;
 *  - the knobs the agent changed (`iteration.edits`, else that round's committed `set_params` call);
 *  - the verdict: the round's verify stage label ("Verified" / "best effort" / "failed"), written by code;
 *  - the overlays: `residual_heatmap` artifacts tagged with that round;
 *  - which round was kept: the one whose trace context (`ctx`) the `done` event carries — the orchestrator packages and
 *    ships that round, which is not always the last one (a later, worse attempt is discarded). Fallback: the round whose
 *    max error equals the `done` summary's, then the last round.
 * Nothing is computed that the server did not already decide. Pure, so `node --test` can load it directly.
 */
import type { JobEvent } from "./api-types";

export type RoundVerdict = "verified" | "best_effort" | "failed" | "unknown";

export type RoundView = {
  view: string;
  iou: number | null;
  hausdorffMm: number | null;
  /** Hausdorff at or under the server's limit; null when the limit or the value is unknown. Not the full view rule. */
  withinLimit: boolean | null;
};

export type RoundEdit = { param: string; from: number | null; to: number | null };

export type RoundOverlay = { view: string; url: string; label: string };

export type FixRound = {
  iter: number;
  seq: number;
  /** Trace context of the round's `iteration` event ("" on old runs). */
  ctx: string;
  strategy: "template" | "free_code" | "human" | null;
  maxErrorMm: number | null;
  hausdorffMm: number | null;
  iou: number | null;
  testsPassed: number | null;
  testsTotal: number | null;
  verdict: RoundVerdict;
  /** The verify stage label for this round, verbatim (empty when missing). */
  verdictText: string;
  views: RoundView[];
  edits: RoundEdit[];
  /** True for the first build (nothing was changed yet). */
  firstBuild: boolean;
  /** A free-code round that changed the program text rather than knob values. */
  rewrote: boolean;
  overlays: RoundOverlay[];
};

export type RoundsSummary = {
  rounds: FixRound[];
  /** Final status from the `done` event; null while the job runs. */
  final: { status: string; verified: boolean } | null;
  /** The round the job shipped (its verdict and files); null while the job runs or when nothing was built. */
  keptIter: number | null;
  limitMm: number | null;
  /** Plain-words line: "Passed on the first build", "Verified after 5 rounds", "Best effort after 6 rounds", … */
  headline: string;
};

const VIEW_RE = /\b(top|side|mating|orbit|fit_check)\s*:\s*IoU\s+([0-9.]+)\s*,\s*Hausdorff\s+([0-9.]+)\s*mm/gi;

function num(v: unknown): number | null {
  return typeof v === "number" && Number.isFinite(v) ? v : null;
}

/** Per-view numbers from a server-written line such as "top: IoU 0.968, Hausdorff 0.67 mm …; side: IoU …". */
export function parseViews(text: string): { view: string; iou: number; hausdorffMm: number }[] {
  const out: { view: string; iou: number; hausdorffMm: number }[] = [];
  for (const m of text.matchAll(VIEW_RE)) {
    const iou = Number(m[2]);
    const h = Number(m[3]);
    if (!Number.isFinite(iou) || !Number.isFinite(h)) continue;
    const view = m[1]!.toLowerCase();
    if (!out.some((v) => v.view === view)) out.push({ view, iou, hausdorffMm: h });
  }
  return out;
}

/** Verdict from the verify stage's label prefix (the orchestrator writes "Verified: …", "best effort: …", "failed: …"). */
export function verdictFromLabel(label: string, status: string | null): RoundVerdict {
  if (status === "fail") return "failed";
  const l = label.trim().toLowerCase();
  if (l.startsWith("verified")) return "verified";
  if (l.startsWith("best effort")) return "best_effort";
  if (l.startsWith("failed")) return "failed";
  return "unknown";
}

function editsFrom(raw: unknown[]): RoundEdit[] {
  const out: RoundEdit[] = [];
  for (const e of raw) {
    if (!e || typeof e !== "object") continue;
    const o = e as Record<string, unknown>;
    if (typeof o.param !== "string" || !o.param) continue;
    out.push({ param: o.param, from: num(o.from), to: num(o.to) });
  }
  return out;
}

export function roundsFromEvents(events: readonly JobEvent[]): RoundsSummary {
  const sorted = [...events].sort((a, b) => a.seq - b.seq);
  const byIter = new Map<number, FixRound>();
  const verifyLabel = new Map<number, { label: string; status: string }>();
  const executeFailed = new Set<number>();
  const metricMax = new Map<number, number>();
  let limitMm: number | null = null;
  let final: RoundsSummary["final"] = null;
  let doneCtx = "";
  let doneMaxMm: number | null = null;
  // tool results to attach to the latest round that exists when they arrive
  let latest: FixRound | null = null;
  // Overlays arrive before their round's iteration event (the orchestrator emits them first).
  const pendingOverlays: Record<number, RoundOverlay[]> = {};

  for (const e of sorted) {
    switch (e.t) {
      case "stage":
        if (e.iter != null && e.stage === "verify" && e.status !== "start") verifyLabel.set(e.iter, { label: e.label, status: e.status });
        if (e.iter != null && e.stage === "execute" && e.status === "fail") executeFailed.add(e.iter);
        break;
      case "metric":
        if (e.name === "max_error_mm") metricMax.set(e.iter, e.value);
        if ((e.name === "hausdorff_mm" || e.name === "hausdorff") && e.threshold != null) limitMm = e.threshold;
        break;
      case "iteration": {
        const r: FixRound = {
          iter: e.iter,
          seq: e.seq,
          ctx: e.ctx,
          strategy: e.strategy,
          maxErrorMm: null,
          hausdorffMm: e.hausdorff_mm ?? null,
          iou: e.iou ?? null,
          testsPassed: e.total_tests ? e.passed_tests : null,
          testsTotal: e.total_tests || null,
          verdict: "unknown",
          verdictText: "",
          views: [],
          edits: editsFrom(e.edits),
          firstBuild: e.iter === 1 || e.analysis === "first build",
          rewrote: e.strategy === "free_code" && !!e.diff && e.edits.length === 0,
          overlays: [],
        };
        byIter.set(e.iter, r);
        latest = r;
        break;
      }
      case "artifact":
        if (e.iter != null && (e.kind === "residual_heatmap" || e.kind === "render_overlay")) {
          const r = byIter.get(e.iter);
          const view = /residual_(\w+)/i.exec(e.label)?.[1]?.toLowerCase() ?? /^(top|side|mating)\b/i.exec(e.label)?.[1]?.toLowerCase() ?? "view";
          const o = { view, url: e.url, label: e.label };
          if (r) r.overlays.push(o);
          else (pendingOverlays[e.iter] ??= []).push(o);
        }
        break;
      case "tool_call":
        if (!latest) break;
        if (e.name === "inspect_residuals" && latest.views.length < 2) {
          const vs = parseViews(e.result);
          if (vs.length > latest.views.length) latest.views = vs.map((v) => ({ ...v, withinLimit: null }));
        }
        if (e.name === "set_params" && e.ok) {
          const m = /^committed round (\d+)/i.exec(e.result);
          const target = m ? byIter.get(Number(m[1])) : null;
          const raw = Array.isArray(e.args.edits) ? (e.args.edits as unknown[]) : [];
          if (target && target.edits.length === 0) target.edits = editsFrom(raw);
        }
        break;
      case "done":
        final = { status: e.status, verified: e.verified };
        doneCtx = e.ctx;
        doneMaxMm = num(e.summary.max_error_mm);
        break;
    }
  }

  const rounds = [...byIter.values()].sort((a, b) => a.iter - b.iter);
  for (const r of rounds) {
    if (pendingOverlays[r.iter]) r.overlays.unshift(...pendingOverlays[r.iter]!);
    const v = verifyLabel.get(r.iter);
    r.verdictText = v?.label ?? "";
    r.verdict = executeFailed.has(r.iter) ? "failed" : v ? verdictFromLabel(v.label, v.status) : "unknown";
    r.maxErrorMm = metricMax.get(r.iter) ?? r.hausdorffMm;
    if (r.views.length === 0 && v) r.views = parseViews(v.label).map((x) => ({ ...x, withinLimit: null }));
    r.views = r.views.map((x) => ({ ...x, withinLimit: limitMm != null && x.hausdorffMm != null ? x.hausdorffMm <= limitMm : null }));
  }

  const keptIter = final ? keptRound(rounds, doneCtx, doneMaxMm) : null;
  return { rounds, final, keptIter, limitMm, headline: headline(rounds, final, keptIter) };
}

/**
 * True when a round's max error comes from a measured size (a hole, a length …) rather than the outline: `max_error_mm`
 * is the worst of the silhouette gaps and the size residuals, so it can be larger than every view's Hausdorff.
 */
export function sizeSetsMaxError(r: Pick<FixRound, "maxErrorMm" | "hausdorffMm" | "views">): boolean {
  const gaps = [r.hausdorffMm, ...r.views.map((v) => v.hausdorffMm)].filter((x): x is number => x != null);
  return r.maxErrorMm != null && gaps.length > 0 && r.maxErrorMm - Math.max(...gaps) > 0.005;
}

/** The round the finished job shipped: matched by the `done` event's trace context, else by its max error, else the last. */
export function keptRound(rounds: readonly FixRound[], doneCtx: string, doneMaxMm: number | null): number | null {
  if (rounds.length === 0) return null;
  const byCtx = doneCtx ? rounds.filter((r) => r.ctx === doneCtx) : [];
  if (byCtx.length === 1) return byCtx[0]!.iter;
  const pool = byCtx.length ? byCtx : rounds;
  if (doneMaxMm != null) {
    const byErr = pool.filter((r) => r.maxErrorMm != null && Math.abs(r.maxErrorMm - doneMaxMm) < 1e-6);
    if (byErr.length) return byErr.at(-1)!.iter;
  }
  return pool.at(-1)!.iter;
}

export function headline(rounds: FixRound[], final: RoundsSummary["final"], keptIter: number | null = null): string {
  const n = rounds.length;
  if (n === 0) return final ? "No model was built." : "No build yet.";
  const rs = n === 1 ? "1 round" : `${n} rounds`;
  if (!final) return `${rs} so far`;
  const last = rounds.at(-1)!.iter;
  const later = keptIter != null && keptIter !== last ? rounds.filter((r) => r.iter > keptIter).length : 0;
  if (later) {
    const kept = rounds.find((r) => r.iter === keptIter)!;
    const name = kept.firstBuild && kept.iter === 1 ? "the first build" : `round ${kept.iter}`;
    const tries = `${later} later ${later === 1 ? "try" : "tries"} discarded`;
    if (final.verified) return `Verified on ${name}; ${tries}`;
    if (final.status === "best_effort") return `Best effort: kept ${name} of ${n}; ${tries}`;
  }
  if (final.verified) return n === 1 ? "Passed on the first build" : `Verified after ${rs} (${n - 1} fix${n - 1 === 1 ? "" : "es"})`;
  if (final.status === "best_effort") return `Best effort after ${rs}`;
  if (final.status === "failed") return `Failed after ${rs}`;
  if (final.status === "cancelled") return `Cancelled after ${rs}`;
  if (final.status === "refused") return "Refused";
  return `${final.status.replace("_", " ")} after ${rs}`;
}

/** Short knob summary for a round: "corner_radius 2.00→1.50 mm", "first build", "program rewritten". */
export function editsText(r: Pick<FixRound, "edits" | "firstBuild" | "rewrote">): string {
  if (r.firstBuild && r.edits.length === 0) return "first build";
  if (r.rewrote) return "program rewritten (free code)";
  if (r.edits.length === 0) return "no knob changed";
  return r.edits
    .map((e) => {
      const unit = e.param.endsWith("_deg") ? "°" : /count|holes|ribs|gussets|flats|channels|spokes|grips/.test(e.param) ? "" : " mm";
      const f = (v: number) => (unit === "" ? String(Math.round(v)) : v.toFixed(2));
      return e.from != null && e.to != null ? `${e.param} ${f(e.from)}→${f(e.to)}${unit}` : e.to != null ? `${e.param} → ${f(e.to)}${unit}` : e.param;
    })
    .join(", ");
}
