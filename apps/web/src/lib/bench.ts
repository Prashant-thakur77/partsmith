/** Bench table metadata and generic readers. Values are rendered exactly as `eval/` wrote them. */
import type { BenchTable } from "./api-types";

export const BENCH_TABLES = [
  {
    key: "synthetic",
    title: "Synthetic photos",
    blurb: "Rendered photos with exact ground truth. Tests the measuring and modelling pipeline end to end.",
    gt: "synthetic exact",
    pendingLabel: "synthetic bench",
  },
  {
    key: "reference_objects",
    title: "Reference objects",
    blurb: "Standard objects with published sizes (ID-1 card, SD card, LEGO brick). Error vs the published spec.",
    gt: "published spec",
    pendingLabel: "reference-object bench",
  },
  {
    key: "real_ruler",
    title: "Real broken parts",
    blurb: "Real parts measured with a plain ruler, labelled ±0.5 mm. Never called caliper accuracy.",
    gt: "ruler ±0.5 mm",
    pendingLabel: "real-part bench",
  },
] as const;

/** Plain titles for the expected-outcome suites the report adds after the three accuracy tables. */
export const EXTRA_TITLES: Record<string, { title: string; blurb: string }> = {
  control: { title: "Intact parts: should be accepted", blurb: "Normal photos of parts that are fine. The check should say yes." },
  redteam: {
    title: "Bad photos: should be turned away",
    blurb: "Photos it must not trust (a hand in the frame, two parts, half the mat) and parts it must not make (soft or safety parts). It should reject or refuse each one.",
  },
};

export const GT_LABEL: Record<string, string> = {
  synthetic_exact: "synthetic, exact",
  reference_spec: "published spec",
  ruler: "ruler ±0.5 mm",
  caliper: "caliper",
  expected_outcome: "expected accept / reject / refuse per case",
};

export function gtLabel(gt: string | undefined, fallback = "not stated"): string {
  if (!gt) return fallback;
  return GT_LABEL[gt] ?? gt.replace(/_/g, " ");
}

export type BenchKey = (typeof BENCH_TABLES)[number]["key"];

/** The table's headline number exactly as eval wrote it, or null while the table is pending. */
export function benchHeadline(t: BenchTable): { value: string; n: number; gt: string } | null {
  if (t.status === "pending") return null;
  const gt = gtLabel(t.ground_truth, "");
  const h = t.headline as Record<string, unknown>;
  // expected-outcome suites (control, red team) count cases handled as expected: "6/6", never a length
  if (typeof h.correct === "number" && typeof h.n === "number") {
    return { value: `${h.correct}/${h.n}`, n: t.n, gt: `handled as expected · ${gt}` };
  }
  for (const [k, v] of Object.entries(h)) {
    if (typeof v !== "number") continue;
    const rate = /rate|share|frac/.test(k);
    const label = k.replace(/_mm$/, "").replace(/_/g, " ");
    const value = rate ? `${(v * 100).toFixed(1)} %` : k.endsWith("_mm") ? `${v.toFixed(2)} mm` : String(v);
    return { value, n: t.n, gt: `${label} · ${gt}` };
  }
  return t.n ? { value: `${t.n} cases`, n: t.n, gt } : null;
}

export function cellText(v: unknown): string {
  if (v === null || v === undefined) return "—";
  if (typeof v === "number") return Number.isInteger(v) ? String(v) : v.toFixed(Math.abs(v) < 10 ? 3 : 2);
  if (typeof v === "boolean") return v ? "yes" : "no";
  if (typeof v === "string") return v;
  return JSON.stringify(v);
}

/** Plain column headers for the raw eval column ids (the id stays available as a tooltip). */
export const COLUMN_LABEL: Record<string, string> = {
  config: "Setup",
  family: "Family",
  n: "Parts",
  dims: "Sizes checked",
  median_abs_err_mm: "Median size error (mm)",
  mean_abs_err_mm: "Mean size error (mm)",
  mean_ci95: "Mean, 95 % range",
  p90_mm: "90 % of sizes within (mm)",
  p95_err_mm: "95 % of sizes within (mm)",
  "pass@0.3": "Passed 0.3 mm",
  "pass@0.5": "Passed 0.5 mm",
  "pass@0.5_ci95": "Passed 0.5 mm, 95 % range",
  verified_rate: "Verified",
  verified_ci95: "Verified, 95 % range",
  verified_but_off: "Verified but off",
  valid_rate: "Printable solid",
  median_iters: "Median rounds",
  median_wall_s: "Median time (s)",
  usd_per_job: "$ per job",
  tokens_per_job: "Tokens per job",
  provider_modes: "Models",
  case: "Case",
  expected: "Expected",
  expected_checks: "Expected checks",
  outcome: "Outcome",
  failed_checks: "Failed checks",
  correct: "Handled as expected",
};

export function columnLabel(id: string): string {
  if (COLUMN_LABEL[id]) return COLUMN_LABEL[id];
  const pass = /^pass@([0-9.]+)$/.exec(id);
  if (pass) return `Passed ${pass[1]} mm`;
  return id.replace(/_mm$/, " (mm)").replace(/_/g, " ");
}

/** Short names for bench setups; the id and the report's own description stay in the tooltip. */
export const CONFIG_LABEL: Record<string, string> = {
  B0: "One shot, no mat scale",
  B1: "One shot, no loop",
  B2: "Loop, pictures only",
  PS: "Full loop",
  "PS-noTemplate": "Loop, no templates",
  "PS-noJudge": "Loop, no judge",
  "PS-noHeightCorr": "Loop, no height fix",
};

export function configLabel(id: string): string {
  return CONFIG_LABEL[id] ?? id;
}

/** The columns worth showing before "Show the full table" (those the table has). */
export const KEY_COLUMNS = ["config", "family", "n", "median_abs_err_mm", "p90_mm", "pass@0.5", "verified_rate", "verified_but_off"];

const NOUN: Record<string, string> = {
  synthetic: "rendered test photos",
  reference_objects: "photos of standard objects",
  real_ruler: "real broken parts",
  control: "photos of intact parts",
  redteam: "photos that should be turned away",
};

function countOf(rate: unknown, n: number): number | null {
  return typeof rate === "number" && Number.isFinite(rate) ? Math.round(rate * n) : null;
}

/**
 * One plain sentence from the table's own headline numbers (nothing typed here), e.g. "On 12 rendered test photos the
 * full loop's median size error was 0.10 mm; 3 of 12 had every size within 0.5 mm, and 2 of 12 passed the code's check."
 * Null when the headline has nothing to say.
 */
export function benchSentence(key: string, t: BenchTable): string | null {
  if (t.status === "pending") return null;
  const h = t.headline as Record<string, unknown>;
  const n = typeof h.n === "number" ? h.n : t.n;
  const noun = NOUN[key] ?? "cases";
  if (typeof h.correct === "number" && n) {
    return `${h.correct} of ${n} ${noun} were handled as expected${key === "redteam" ? " (rejected or refused)" : key === "control" ? " (accepted)" : ""}.`;
  }
  if (typeof h.median_abs_err_mm !== "number" || !n) return null;
  const who = typeof h.config === "string" ? `the ${configLabel(h.config).toLowerCase()}'s` : "the";
  const parts = [`On ${n} ${noun} ${who} median size error was ${h.median_abs_err_mm.toFixed(2)} mm`];
  const tail: string[] = [];
  for (const [k, v] of Object.entries(h)) {
    const m = /^pass_at_(\d+)_(\d+)$/.exec(k);
    const c = m ? countOf(v, n) : null;
    if (m && c != null) tail.push(`${c} of ${n} had every size within ${m[1]}.${m[2]} mm`);
  }
  const v = countOf(h.verified_rate, n);
  if (v != null) tail.push(`${v} of ${n} passed the code's check`);
  return `${parts[0]}${tail.length ? `; ${tail.join(", and ")}` : ""}.`;
}
