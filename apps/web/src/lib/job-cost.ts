/**
 * A job's model spend, added up from its own `model_call` events (tokens, calls and USD as each call reported them).
 * Nothing is estimated here. Pure and free of runtime imports so `node --test` can load it.
 */

export type CostCall = { provider: string; model: string; stage: string; mode: "live" | "mock" | "replay"; tokens_in: number; tokens_out: number; usd: number; ok: boolean };

export type ModelCost = { model: string; provider: string; calls: number; failed: number; tokensIn: number; tokensOut: number; usd: number; live: boolean };

export type JobCost = {
  usd: number;
  tokensIn: number;
  tokensOut: number;
  calls: number;
  failed: number;
  liveCalls: number;
  perModel: ModelCost[];
  /** "replay": a recorded run; "mock": no live call (no spend); "live": at least one live call. */
  kind: "replay" | "mock" | "live";
  note: string;
};

export function jobCost(calls: readonly CostCall[], opts: { replay: boolean }): JobCost {
  const by = new Map<string, ModelCost>();
  let usd = 0;
  let tokensIn = 0;
  let tokensOut = 0;
  let failed = 0;
  let liveCalls = 0;
  for (const c of calls) {
    usd += c.usd;
    tokensIn += c.tokens_in;
    tokensOut += c.tokens_out;
    failed += c.ok ? 0 : 1;
    liveCalls += c.mode === "live" ? 1 : 0;
    const key = `${c.provider}\u0000${c.model}`;
    const m = by.get(key) ?? { model: c.model, provider: c.provider, calls: 0, failed: 0, tokensIn: 0, tokensOut: 0, usd: 0, live: false };
    m.calls += 1;
    m.failed += c.ok ? 0 : 1;
    m.tokensIn += c.tokens_in;
    m.tokensOut += c.tokens_out;
    m.usd += c.usd;
    m.live ||= c.mode === "live";
    by.set(key, m);
  }
  const perModel = [...by.values()].sort((a, b) => b.usd - a.usd || b.calls - a.calls || a.model.localeCompare(b.model));
  const kind = opts.replay ? "replay" : liveCalls > 0 ? "live" : "mock";
  const note =
    kind === "replay"
      ? liveCalls > 0
        ? "recorded cost of the original run (nothing was spent replaying it)"
        : "recorded cost of the original run — it used mock models, so no spend"
      : kind === "mock"
        ? "mock — no spend"
        : liveCalls < calls.length
          ? `live: ${liveCalls} of ${calls.length} calls went to a real model`
          : "live model calls, as each provider reported them";
  return { usd, tokensIn, tokensOut, calls: calls.length, failed, liveCalls, perModel, kind, note };
}
