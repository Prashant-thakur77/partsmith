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
