/**
 * The /parts banner for a search that found no close part (or only a partial one). The match label, coverage and hint
 * come from the API (`GET /parts?q=`); this only decides whether to show a banner and how to word its heading.
 * Pure and free of runtime imports so `node --test` can load it.
 */

export type MatchBanner = { tone: "warn" | "neutral"; title: string; hint: string; coveragePct: number | null };

export function matchBanner(match: string | null | undefined, coverage: number | null | undefined, hint: string | null | undefined, query: string): MatchBanner | null {
  if (!query.trim() || (match !== "none" && match !== "partial")) return null;
  const pct = typeof coverage === "number" && Number.isFinite(coverage) ? Math.round(coverage * 100) : null;
  if (match === "none") {
    return { tone: "warn", title: `No close match for “${query.trim()}”`, hint: hint ?? "", coveragePct: pct };
  }
  return { tone: "neutral", title: `Only a partial match for “${query.trim()}”`, hint: hint ?? "", coveragePct: pct };
}
