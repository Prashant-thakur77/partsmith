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
  public_photos: {
    title: "Public photos of real objects, pasted on a rendered mat",
    blurb: "Not phone photos, and not counted as real photos measured. Each object is cut out of a public photograph and pasted on our rendered screen mat. The paste scale comes from one published size, which is left out of the errors; only the other sizes count.",
  },
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
  published_spec_pasted: "published spec, pasted at known size",
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
  "pass@0.3": "All sizes within 0.3 mm of truth",
  "pass@0.5": "All sizes within 0.5 mm of truth",
  "pass@0.5_ci95": "All sizes within 0.5 mm, 95 % range",
  verified_rate: "Verified",
  verified_ci95: "Verified, 95 % range",
  verified_but_off: "Verified, yet a size over 0.5 mm off",
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
  if (pass) return `All sizes within ${pass[1]} mm of truth`;
  return id.replace(/_mm$/, " (mm)").replace(/_/g, " ");
}

/** Short names for bench setups; the id and the report's own description stay in the tooltip. */
export const CONFIG_LABEL: Record<string, string> = {
  B0: "One shot, no mat scale",
  B1: "One shot, no loop",
  B2: "Loop, pictures only",
  PS: "PartSmith (full pipeline)",
  "PS-open": "PartSmith, open-weights builder",
  "PS-open-all": "PartSmith, all open weights",
  "PS-noTemplate": "Loop, no templates",
  "PS-noJudge": "Loop, no judge",
  "PS-noHeightCorr": "Loop, no height fix",
};

export function configLabel(id: string): string {
  return CONFIG_LABEL[id] ?? id;
}

/**
 * Report text in plain words: setup ids ("PS", "PS-noJudge") become their names and split/suite ids lose their
 * underscores. "syn-hook-s1 · PS (synthetic, held_out)" → "syn-hook-s1 · full pipeline (synthetic, held-out)".
 */
export function plainBench(text: string): string {
  return text
    .replace(/\b(PS-[A-Za-z-]+|B\d)\b/g, (id) => CONFIG_LABEL[id] ?? id)
    .replace(/\bPS\b(?=\s*\()/g, "full pipeline")
    .replace(/\bPS\b/g, "PartSmith (full pipeline)")
    .replace(/\bheld_out\b/g, "held-out")
    .replace(/\breference_objects\b/g, "reference objects");
}

/**
 * Why "All sizes within 0.5 mm of truth" and "Verified" can differ in one row: the first compares the model's sizes
 * with the true part; "Verified" is the code's own check, which also needs the outline and the part tests to pass.
 * Null when the table has neither column.
 */
export function passVsVerifiedNote(columns: readonly string[]): string | null {
  const pass = columns.find((c) => /^pass@[0-9.]+$/.test(c));
  if (!pass || !columns.includes("verified_rate")) return null;
  return `“${columnLabel(pass)}” compares every measured size of the model with the true part. “Verified” is the code's own pass: it also needs the outline to match the photo and the part tests to pass, so a case can have every size right and still not be verified.`;
}

/** The columns worth showing before "Show the full table" (those the table has). */
export const KEY_COLUMNS = ["config", "family", "n", "median_abs_err_mm", "p90_mm", "pass@0.5", "verified_rate", "verified_but_off"];

const NOUN: Record<string, string> = {
  public_photos: "public photos pasted on a rendered mat",
  synthetic: "rendered test photos",
  reference_objects: "photos of standard objects",
  real_ruler: "real broken parts",
  control: "photos of intact parts",
  redteam: "photos that should be turned away",
};

function countOf(rate: unknown, n: number): number | null {
  return typeof rate === "number" && Number.isFinite(rate) ? Math.round(rate * n) : null;
}

/** How many of the table's cases passed the code's verification (headline `verified_rate` × n), or null. */
export function benchVerified(t: BenchTable | undefined): { passed: number; n: number } | null {
  if (!t || t.status === "pending") return null;
  const h = t.headline as Record<string, unknown>;
  const n = typeof h.n === "number" ? h.n : t.n;
  const passed = n ? countOf(h.verified_rate, n) : null;
  return passed != null && n ? { passed, n } : null;
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
  const who = typeof h.config === "string" ? `the ${h.config === "PS" ? "full pipeline" : configLabel(h.config).toLowerCase()}'s` : "the";
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

/** The four questions a first-time reader has about this page, each answered from the tables' own headlines. */
export type PlainAnswer = { key: string; question: string; answer: string };

export function resultsPlain(tables: Record<string, BenchTable | undefined>, separate: Record<string, BenchTable | undefined> = {}): PlainAnswer[] {
  const say = (key: string, t: BenchTable | undefined) => (t ? benchSentence(key, t) : null);
  const handled = [say("redteam", tables.redteam), say("control", tables.control)].filter(Boolean).join(" ");
  const real = tables.real_ruler;
  return [
    { key: "synthetic", question: "How close does it get?", answer: say("synthetic", tables.synthetic) ?? "This suite has not run yet." },
    { key: "public_photos", question: "On photos of real objects?", answer: say("public_photos", separate.public_photos) ?? "This suite has not run yet." },
    { key: "redteam", question: "Does it turn bad input away?", answer: handled || "These suites have not run yet." },
    { key: "real_ruler", question: "On real broken parts?", answer: (real?.n ? say("real_ruler", real) : null) ?? "Not measured yet. No real broken part has been photographed on the mat and checked with a ruler." },
  ];
}

// ── rates and case names in words ─────────────────────────────────────────────
/** Columns whose values are shares of the row's cases (0–1), shown as counts: "2/12 (17%)". */
export function isRateColumn(col: string): boolean {
  return /(^|_)rate$/.test(col) || /^pass@[0-9.]+$/.test(col);
}

const pctText = (v: number) => `${Math.round(v * 100)}%`;

/** A share as "passed/n (pct)" when the row's n is known, else "pct". The count is the share × n, rounded. */
export function rateText(v: number, n?: number | null): string {
  if (typeof n === "number" && n > 0) return `${Math.round(v * n)}/${n} (${pctText(v)})`;
  return pctText(v);
}

/** A "[0.05, 0.45]" range in its column's unit: a share range as "5–45%", a length range as "0.22–1.20 mm". */
export function rangeText(col: string, v: string): string | null {
  const m = /^\[\s*(-?[0-9.]+)\s*,\s*(-?[0-9.]+)\s*\]$/.exec(v);
  if (!m) return null;
  const [a, b] = [Number(m[1]), Number(m[2])];
  if (/^mean_ci95$/.test(col)) return `${a.toFixed(2)}–${b.toFixed(2)} mm`;
  return `${Math.round(a * 100)}–${Math.round(b * 100)}%`;
}

/** A table cell in words: shares as counts of the row's cases, 95 % ranges in their unit, everything else as before. */
export function benchCell(col: string, v: unknown, row: Record<string, unknown>): string {
  const n = typeof row.n === "number" ? row.n : null;
  if (typeof v === "number" && isRateColumn(col) && v >= 0 && v <= 1) return rateText(v, n);
  if (typeof v === "string" && /ci95$/.test(col)) return rangeText(col, v) ?? v;
  return cellText(v);
}

const CONDITION: Record<string, string> = {
  clean: "clean photo",
  tilt: "tilted photo",
  blur: "blurred photo",
  glare: "glare",
  moire: "moiré on the screen mat",
  "low-light": "low light",
  "white-part": "white part",
  paper: "printed paper mat",
  "dark-stage": "dark stage",
  "white-on-light": "white part on a light stage",
};
const SET: Record<string, string> = { syn: "rendered test photo", ref: "standard object", ctl: "intact part", rt: "should be turned away" };

/**
 * A bench case id in words: "syn-hook-tilt-s656341" → "Wall hook · tilted photo", "rt-hand-in-frame" → "Hand in
 * frame". Part names come from `titles` (template name → title, from /templates) when known; the id itself stays
 * on the page beside the label.
 */
export function caseLabel(id: string, titles: Record<string, string> = {}): string {
  const m = /^(syn|ref|ctl|rt)-(.+?)(?:-s\d+)?$/.exec(id.trim());
  if (!m) return id;
  const [, set, rest] = m as unknown as [string, string, string];
  const cond = Object.keys(CONDITION)
    .sort((a, b) => b.length - a.length)
    .find((c) => rest === c || rest.endsWith(`-${c}`));
  const part = cond ? rest.slice(0, rest.length - cond.length).replace(/-$/, "") : rest;
  const human = (s: string) => {
    const w = s.split("-").map((t) => (t.length <= 2 && set !== "rt" ? t.toUpperCase() : t));
    const out = w.join(" ");
    return out.charAt(0).toUpperCase() + out.slice(1);
  };
  const name = part ? (titles[part.replace(/-/g, "_")] ?? human(part)) : SET[set];
  return [name, cond ? CONDITION[cond] : null].filter(Boolean).join(" · ");
}

/** A failure-gallery title ("<case id> · PS (synthetic, held_out)") split into the case id and the rest. */
export function splitCaseTitle(title: string): { id: string; rest: string } {
  const i = title.indexOf(" · ");
  return i < 0 ? { id: title.trim(), rest: "" } : { id: title.slice(0, i).trim(), rest: title.slice(i + 3).trim() };
}
