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
};

export function gtLabel(gt: string | undefined, fallback = "not stated"): string {
  if (!gt) return fallback;
  return GT_LABEL[gt] ?? gt.replace(/_/g, " ");
}

export type BenchKey = (typeof BENCH_TABLES)[number]["key"];

const HEADLINE_KEYS = ["headline", "median_abs_err_mm", "median_error_mm", "mae_mm", "median_mm", "verified_rate", "pass_rate"];

export function benchHeadline(t: BenchTable): { value: string; n: number | undefined; gt: string } | null {
  const rec = t as Record<string, unknown>;
  const gt = gtLabel(typeof t.ground_truth === "string" ? t.ground_truth : undefined, "");
  const n = typeof t.n === "number" ? t.n : Array.isArray(t.rows) ? t.rows.length : undefined;
  for (const k of HEADLINE_KEYS) {
    const v = rec[k];
    if (typeof v === "string" && v) return { value: v, n, gt };
    if (typeof v === "number") {
      const isRate = k.includes("rate");
      return { value: isRate ? `${(v * 100).toFixed(1)} %` : `${v.toFixed(2)} mm`, n, gt };
    }
  }
  if (n !== undefined) return { value: `${n} cases`, n, gt };
  return null;
}

export function cellText(v: unknown): string {
  if (v === null || v === undefined) return "—";
  if (typeof v === "number") return Number.isInteger(v) ? String(v) : v.toFixed(Math.abs(v) < 10 ? 3 : 2);
  if (typeof v === "boolean") return v ? "yes" : "no";
  if (typeof v === "string") return v;
  return JSON.stringify(v);
}
