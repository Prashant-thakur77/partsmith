/**
 * "Fits where it goes" helpers: the tap kinds for the mating photo, the `points` payload, and plain-words rows for the
 * workspace card built from the job's `mate_fit.json` (services/agent/mating.py, services/verifier/mate_fit.py). The
 * server measures and classifies; the browser only words and shows what it sent.
 *
 * Kept free of runtime imports so `node --test` can load it directly.
 */

export const TOP_TAP_KINDS = ["hole", "slot", "tab", "broken_edge", "exclude"] as const;
export const MATE_TAP_KINDS = ["mate_hole", "mate_peg", "mate_slot", "exclude"] as const;
export type TopTapKind = (typeof TOP_TAP_KINDS)[number];
export type MateTapKind = (typeof MATE_TAP_KINDS)[number];
export type AnyTapKind = TopTapKind | MateTapKind;
export type Tap<K extends string = AnyTapKind> = { x: number; y: number; kind: K };

/** Same prefix as services/verifier/mate_fit.py TEST_PREFIX. */
export const FIT_TEST_PREFIX = "fit.mate.";

/** The `points` form field: `{"top": [...], "mating": [...]}` with empty views left out; null when nothing was tapped. */
export function pointsPayload(top: readonly Tap[] | null | undefined, mating: readonly Tap[] | null | undefined): string | null {
  const out: Record<string, Tap[]> = {};
  if (top?.length) out.top = top.map(({ x, y, kind }) => ({ x, y, kind }));
  if (mating?.length) out.mating = mating.map(({ x, y, kind }) => ({ x, y, kind }));
  return Object.keys(out).length ? JSON.stringify(out) : null;
}

export type MateLike = {
  id: string;
  kind: string;
  ok: boolean;
  material?: string | null;
  shape?: string | null;
  point_source?: string;
  size?: { value: number; sigma_mm: number } | null;
  method?: string;
  reason?: string | null;
  retake?: string | null;
};

export type PrintedLike = { title: string; clearance_mm: number; fit: string; with_preset_clearance_mm?: number | null; with_preset_fit?: string | null; clearance_source: string; clearance_label?: string; internal: boolean; text: string };

export type FitLike = {
  mate_id: string;
  mate_kind: string;
  model_feature?: string;
  model_feature_source?: string;
  model_feature_note?: string;
  model_mm?: number | null;
  mate_mm?: number | null;
  mate_sigma_mm?: number | null;
  clearance_mm?: number | null;
  clearance_sigma_mm?: number | null;
  fit?: string | null;
  fit_low?: string | null;
  fit_high?: string | null;
  passed: boolean;
  printed?: PrintedLike | null;
  text: string;
};

/** What the mate is, in words: socket, shaft, slot or panel edge. */
export function mateWord(kind: string, material?: string | null): string {
  if (kind === "mate_hole") return "socket";
  if (kind === "mate_peg") return "shaft";
  if (kind === "mate_slot") return material === "material" ? "panel edge" : "slot";
  return "mating feature";
}

const SOURCE_WORDS: Record<string, string> = {
  user: "you tapped it",
  model: "Spark pointed at it",
  mock: "picked by code (mock pointer)",
};
export function pointWord(source: string | undefined): string {
  return SOURCE_WORDS[source ?? ""] ?? "";
}

const FIX2 = (v: number) => (Math.abs(v) < 0.005 ? 0 : v).toFixed(2);

/** "Ø 6.00 ± 0.02 mm" for round mates and shafts, "width 3.00 ± 0.06 mm" for slots and panel edges. */
export function sizeText(m: Pick<MateLike, "kind" | "shape" | "size">): string | null {
  if (!m.size) return null;
  const round = m.shape === "round" || m.kind === "mate_peg";
  return `${round ? "Ø " : "width "}${FIX2(m.size.value)} ± ${FIX2(m.size.sigma_mm)} mm`;
}

export type Tone = "ok" | "warn" | "bad" | "neutral";
/** Badge tone of a fit class: does not fit is bad, a sliding fit is good, the rest are worth a look. */
export function fitTone(fit: string | null | undefined): Tone {
  if (!fit) return "neutral";
  if (fit === "does not fit") return "bad";
  if (fit === "sliding fit") return "ok";
  return "warn";
}

/** Signed clearance in words: "+0.20 mm clearance" or "0.12 mm interference". */
export function clearanceText(c: number | null | undefined, sigma?: number | null): string | null {
  if (c == null || !Number.isFinite(c)) return null;
  const s = sigma != null && sigma > 0 ? ` ± ${FIX2(sigma)}` : "";
  return c >= 0 ? `${FIX2(c)}${s} mm clearance` : `${FIX2(-c)}${s} mm interference`;
}

export type FitRow = {
  id: string;
  what: string;
  measured: string | null;
  how: string;
  pointedBy: string;
  model: string | null;
  modelNote: string;
  clearance: string | null;
  fit: string | null;
  range: string | null;
  tone: Tone;
  printer: string | null;
  problem: string | null;
};

/** One row per mate (a mate that was not measured still gets a row that says why). */
export function fitRows(result: { mates?: readonly MateLike[]; fits?: readonly FitLike[] } | null | undefined): FitRow[] {
  if (!result) return [];
  const fits = new Map((result.fits ?? []).map((f) => [f.mate_id, f]));
  return (result.mates ?? []).map((m) => {
    const f = fits.get(m.id);
    const range = f?.fit_low && f?.fit_high && f.fit_low !== f.fit_high ? `${f.fit_low} to ${f.fit_high} within ±σ` : null;
    const problem = !m.ok ? (m.retake ?? m.reason ?? "not measured") : f && f.clearance_mm == null ? f.text : null;
    return {
      id: m.id,
      what: mateWord(m.kind, m.material),
      measured: m.ok ? sizeText(m) : null,
      how: m.method ?? "",
      pointedBy: pointWord(m.point_source),
      model: f?.model_mm != null ? `${f.model_feature ?? "model feature"}: ${FIX2(f.model_mm)} mm` : null,
      modelNote: f?.model_feature_note ?? "",
      clearance: clearanceText(f?.clearance_mm, f?.clearance_sigma_mm),
      fit: f?.fit ?? null,
      range,
      tone: fitTone(f?.fit),
      printer: f?.printed?.text ?? null,
      problem,
    };
  });
}

/** The "does not fit where it goes" warning for the export menu, from the verification's own P1 tests; null when it fits. */
export function fitWarning(v: { tests: readonly { id: string; passed: boolean; value?: number | null; description: string }[] } | null | undefined): string | null {
  const bad = (v?.tests ?? []).filter((t) => t.id.startsWith(FIT_TEST_PREFIX) && !t.passed && t.value != null);
  if (!bad.length) return null;
  const what = bad[0]!.description.replace(/^fits where it goes: /, "").split("; after printing")[0]!;
  return `Does not fit where it goes: ${what.replace(/^does not fit: /, "")}${bad.length > 1 ? ` (and ${bad.length - 1} more)` : ""}.`;
}
