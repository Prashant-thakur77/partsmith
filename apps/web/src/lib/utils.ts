import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}

export function clamp(v: number, lo: number, hi: number): number {
  return Math.min(hi, Math.max(lo, v));
}

/** Round to the precision implied by a slider step (0.05 → 2 dp), avoiding float noise like 3.1000000000000005. */
export function snap(v: number, step: number, min = 0): number {
  if (!(step > 0)) return v;
  const dp = Math.max(decimalsForStep(step), decimalsForStep(min));
  return Number((Math.round((v - min) / step) * step + min).toFixed(dp));
}

export function decimalsForStep(step: number): number {
  if (!(step > 0) || step >= 1) return Number.isInteger(step) ? 0 : 1;
  const s = String(step);
  const i = s.indexOf(".");
  return i < 0 ? 0 : Math.min(s.length - i - 1, 4);
}
