/**
 * One row per pipeline stage for the model tables on /models and /judges: the model the stage is set up to use now and
 * how it runs now (from `/status` providers), beside every model actually seen in that stage's `model_call` events —
 * calls made on this server and calls in the recorded runs it serves, kept apart. Pure (type imports only), so
 * `node --test` loads it directly. Every number is a count from `/status`; nothing is estimated.
 */
import type { ModelCallAgg, ProviderStatus, Status } from "./api-types";

export type SeenModel = { model: string; mode: string; calls: number; usd: number; open: boolean; source: "here" | "recorded" };
export type StageModelRow = {
  key: string;
  stage: string;
  role: string;
  /** set up now */
  model: string;
  where: string;
  open: boolean;
  /** how the stage runs now (live | replay | mock) */
  mode: string;
  /** models seen in logged calls, most calls first; made here before recorded */
  seen: SeenModel[];
  /** true when a logged call used a different model than the one set up now */
  differs: boolean;
  /** spend from calls made on this server */
  usd: number;
};

/** Plain word for a mode, the same on every model table ("replay" reads as "recorded"). */
export const MODE_WORD: Record<string, string> = { live: "live", replay: "recorded", mock: "mock", mixed: "mixed" };

function seenOf(calls: readonly ModelCallAgg[], stage: string, source: SeenModel["source"]): SeenModel[] {
  const by = new Map<string, SeenModel>();
  for (const c of calls) {
    if (c.stage !== stage) continue;
    const k = `${c.model}|${c.mode}`;
    const m = by.get(k) ?? { model: c.model, mode: c.mode, calls: 0, usd: 0, open: false, source };
    m.calls += c.calls;
    m.usd += c.usd;
    m.open ||= c.open_weights;
    by.set(k, m);
  }
  return [...by.values()].sort((a, b) => b.calls - a.calls);
}

/** Same model, ignoring a dated suffix the provider adds ("muse-spark-open" vs "meta-models/muse-spark-open-1026"). */
export function sameModel(a: string, b: string): boolean {
  const norm = (s: string) => s.toLowerCase().replace(/^.*\//, "").replace(/-\d{3,}$/, "");
  return norm(a) === norm(b);
}

export function stageModelRows(s: Pick<Status, "providers" | "model_calls"> & { model_calls_recorded?: Status["model_calls_recorded"] }): StageModelRow[] {
  return s.providers.map((p: ProviderStatus) => {
    const seen = [...seenOf(s.model_calls, p.stage, "here"), ...seenOf(s.model_calls_recorded ?? [], p.stage, "recorded")];
    return {
      key: `${p.stage}-${p.role}`,
      stage: p.stage,
      role: p.role,
      model: p.model,
      where: p.where,
      open: p.open_weights,
      mode: p.mode,
      seen,
      differs: seen.some((m) => !sameModel(m.model, p.model)),
      usd: seen.filter((m) => m.source === "here").reduce((t, m) => t + m.usd, 0),
    };
  });
}
