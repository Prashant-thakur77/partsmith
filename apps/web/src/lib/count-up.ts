/**
 * Pure helpers for counters that count up to a real value (motion.ts `useCountUp`). The target always comes from the API
 * or a stored report; these only decide what to print on the way there. Kept free of runtime imports so `node --test`
 * can load it directly.
 */

/** Ease-out cubic, clamped to 0..1. */
export function easeOutCubic(t: number): number {
  const k = Math.min(1, Math.max(0, t));
  return 1 - Math.pow(1 - k, 3);
}

/** Decimal places written in a numeric string ("0.10" → 2, "17" → 0, "1,234.5" → 1). */
export function decimalsOf(text: string): number {
  const m = /\.(\d+)/.exec(text);
  return m ? m[1]!.length : 0;
}

export type NumericText = { prefix: string; value: number; decimals: number; suffix: string; grouped: boolean };

/**
 * Split a formatted value into the number to animate and the text around it: "0.10 mm" → 0.1 with suffix " mm",
 * "US$25.75" → prefix "US$", "17/17" → 17 with suffix "/17" (only the first number counts). Null when there is no number.
 */
export function splitNumeric(text: string): NumericText | null {
  const m = /^(.*?)(-?\d[\d,]*(?:\.\d+)?)(.*)$/s.exec(text);
  if (!m) return null;
  const raw = m[2]!;
  const value = Number(raw.replace(/,/g, ""));
  if (!Number.isFinite(value)) return null;
  return { prefix: m[1]!, value, decimals: decimalsOf(raw), suffix: m[3]!, grouped: raw.includes(",") };
}

/** The number at progress `t` (0..1, eased), printed with the target's own decimals (and thousands commas if it had them). */
export function countFrame(target: number, t: number, decimals: number, grouped = false): string {
  const out = t >= 1 ? target : target * easeOutCubic(t);
  return out.toLocaleString("en-US", { minimumFractionDigits: decimals, maximumFractionDigits: decimals, useGrouping: grouped });
}

/** The whole formatted string at progress `t`; at t ≥ 1 it is exactly the input text. */
export function countText(text: string, t: number): string {
  if (t >= 1) return text;
  const n = splitNumeric(text);
  if (!n) return text;
  return `${n.prefix}${countFrame(n.value, t, n.decimals, n.grouped)}${n.suffix}`;
}

/**
 * Which value a stepping counter shows at `elapsedMs` when it walks through `values` (e.g. one error per round), holding
 * each for `stepMs`. Returns the index, clamped to the last value.
 */
export function stepIndex(values: readonly unknown[], elapsedMs: number, stepMs: number): number {
  if (!values.length) return -1;
  if (stepMs <= 0) return values.length - 1;
  return Math.min(values.length - 1, Math.max(0, Math.floor(elapsedMs / stepMs)));
}
