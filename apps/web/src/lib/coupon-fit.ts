/**
 * Fit-test coupon feedback helpers: which mating features a coupon carries, the per-device id the server keys learned
 * clearances by (random, kept in this browser; no account), and the "coupon was downloaded" flag that reveals the
 * "How did the coupon fit?" control. The learning rule itself lives on the server (services/registry/fit_learning.py);
 * the browser only shows its result.
 *
 * Kept free of runtime imports so `node --test` can load it directly.
 */

export type CouponFeature = { id: string; label: string };
export type CouponFit = "tight" | "ok" | "loose";
export type CouponAmount = "barely" | "very";

/** Same rule as services/media/coupon.py: holes (blind holes test as through), slots and D-bores, identical sizes once. */
const COUPON_KINDS: Record<string, string> = { through_hole: "hole", blind_hole: "hole", slot: "slot", d_shaft_bore: "D-bore" };
const MAX_FEATURES = 4;
/** Same rule as services/registry/presets.py `fit_knobs`. */
export const FIT_KEYS = ["hole", "bore", "pivot", "pin", "cable", "gap", "clearance", "slot"];

function measured(f: Record<string, unknown>, key: string): number | null {
  const m = f[key];
  if (m && typeof m === "object" && typeof (m as { value?: unknown }).value === "number") return (m as { value: number }).value;
  return null;
}

/** Coupon features of a job's PartSpec (in coupon order), or of a part's fit knobs when there is no PartSpec. */
export function couponFeatures(
  specFeatures: readonly Record<string, unknown>[] | null | undefined,
  params: readonly { name: string; label?: string; unit?: string; affects_fit?: boolean; topology?: boolean }[] = [],
): CouponFeature[] {
  const out: CouponFeature[] = [];
  const seen = new Set<string>();
  for (const f of specFeatures ?? []) {
    const kind = COUPON_KINDS[String(f.kind)];
    if (!kind) continue;
    const size = [measured(f, "diameter"), measured(f, "width"), measured(f, "length")].map((v) => (v == null ? "" : v.toFixed(2))).join("|");
    const key = `${kind}|${size}`;
    if (size.replaceAll("|", "") && seen.has(key)) continue;
    seen.add(key);
    const d = measured(f, "diameter") ?? measured(f, "width");
    out.push({ id: String(f.id), label: `${String(f.id).replaceAll("_", " ")} (${kind}${d != null ? ` ${d.toFixed(1)} mm` : ""})` });
    if (out.length >= MAX_FEATURES) return out;
  }
  if (out.length) return out;
  for (const p of params) {
    if (!p.affects_fit || p.unit !== "mm" || p.topology || !FIT_KEYS.some((k) => p.name.toLowerCase().includes(k))) continue;
    out.push({ id: p.name, label: p.label || p.name.replaceAll("_", " ") });
    if (out.length >= MAX_FEATURES) break;
  }
  return out.length ? out : [{ id: "fit", label: "coupon overall" }];
}

/** Device ids the server accepts: 8–64 of [A-Za-z0-9_-]. */
export const SESSION_RE = /^[A-Za-z0-9_-]{8,64}$/;

export function newDeviceId(rand: () => number = Math.random): string {
  const abc = "abcdefghijklmnopqrstuvwxyz0123456789";
  let s = "d-";
  for (let i = 0; i < 22; i++) s += abc[Math.floor(rand() * abc.length)];
  return s;
}

type KV = { getItem(k: string): string | null; setItem(k: string, v: string): void };
const DEVICE_KEY = "partsmith.device";
export const PRESET_KEY = "partsmith.fitPreset";
const COUPON_KEY = "partsmith.couponDownloaded";
export const COUPON_EVENT = "partsmith:coupon";

/** This browser's device id (created once). Null when storage is blocked: then nothing is learned or sent. */
export function deviceId(store: KV | null): string | null {
  if (!store) return null;
  try {
    const cur = store.getItem(DEVICE_KEY);
    if (cur && SESSION_RE.test(cur)) return cur;
    const id = newDeviceId();
    store.setItem(DEVICE_KEY, id);
    return id;
  } catch {
    return null;
  }
}

export function couponDownloaded(store: KV | null): boolean {
  try {
    return !!store?.getItem(COUPON_KEY);
  } catch {
    return false;
  }
}

export function markCouponDownloaded(store: KV | null, now: number = Date.now()): void {
  try {
    store?.setItem(COUPON_KEY, String(now));
  } catch {
    /* storage blocked: the control stays behind its disclosure button */
  }
}

/** One report body for POST /fit-reports/coupon; features without an answer are left out. */
export function reportBody(
  preset: string,
  session: string,
  answers: Record<string, { fit?: CouponFit; amount?: CouponAmount | null }>,
  link: { jobId?: string; slug?: string } = {},
): { preset: string; session: string; features: { feature: string; fit: CouponFit; amount: CouponAmount | null }[]; job_id?: string; slug?: string } {
  const features = Object.entries(answers)
    .filter((e): e is [string, { fit: CouponFit; amount?: CouponAmount | null }] => !!e[1].fit)
    .map(([feature, a]) => ({ feature, fit: a.fit, amount: a.fit === "ok" ? null : (a.amount ?? null) }));
  return { preset, session, features, ...(link.jobId ? { job_id: link.jobId } : {}), ...(link.slug ? { slug: link.slug } : {}) };
}

/** Call from any coupon download link: remembers the download and reveals the feedback control on this device. */
export function noteCouponDownload(): void {
  if (typeof window === "undefined") return;
  let store: KV | null = null;
  try {
    store = window.localStorage;
  } catch {
    store = null;
  }
  markCouponDownloaded(store);
  window.dispatchEvent(new Event(COUPON_EVENT));
}
