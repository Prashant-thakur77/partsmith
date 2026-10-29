/**
 * Repair passport helpers: the id a part carries (debossed and on its repair card's QR), the reprint download link
 * and the "it broke in a new place" prefill for /fix. The ids and every decision come from the server
 * (services/registry/passport.py); this file only formats links and reads what people type.
 *
 * Kept free of runtime imports so `node --test` can load it directly.
 */

/** Crockford base32, as the server encodes ids (no I, L, O, U). */
export const PASSPORT_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ";
export const PASSPORT_LEN = 6;

/** Canonical id from what someone typed or scanned ("7kq-3mz" → "7KQ3MZ"; O reads as 0, I/L as 1), or null. */
export function normalizePassportId(raw: string): string | null {
  let s = raw.trim().toUpperCase().replace(/[-\s_]/g, "");
  s = s.replace(/O/g, "0").replace(/[IL]/g, "1");
  if (s.length !== PASSPORT_LEN) return null;
  for (const ch of s) if (!PASSPORT_ALPHABET.includes(ch)) return null;
  return s;
}

/** The id split for reading aloud or copying by hand: "7KQ 3MZ". */
export function groupPassportId(id: string): string {
  return id.length === PASSPORT_LEN ? `${id.slice(0, 3)} ${id.slice(3)}` : id;
}

/** Absolute link to the passport page (what the QR code encodes). */
export function passportLink(origin: string, id: string): string {
  return `${origin.replace(/\/+$/, "")}/p/${encodeURIComponent(id)}`;
}

export type ReprintFormat = "stl" | "3mf" | "step";

export type ReprintOptions = {
  format: ReprintFormat;
  /** Fit preset id; the server adds its clearance (or the device's learned one) to internal-fit knobs only. */
  preset?: string | null;
  /** This browser's device id: the server swaps in the clearance its coupon reports taught. */
  fitSession?: string | null;
  /** Best-effort parts only: the person acknowledged the gate's reason. */
  ack?: boolean;
  /** Deboss the passport id on the part (server decides where, or skips and says so in a header). */
  mark?: boolean;
};

/**
 * Download URL for a reprint: the passport's own gated bake route (`bake_url` from GET /passport/{id}) with the
 * format, preset, device and acknowledgement. The knob values are the passport's (no knob overrides are added).
 */
export function reprintUrl(bakeUrl: string, o: ReprintOptions): string {
  const qs = new URLSearchParams();
  qs.set("format", o.format);
  if (o.preset) qs.set("preset", o.preset);
  if (o.fitSession) qs.set("fit_session", o.fitSession);
  qs.set("download", "1");
  if (o.ack) qs.set("ack", "1");
  if (o.mark) qs.set("passport", "1");
  return `${bakeUrl}${bakeUrl.includes("?") ? "&" : "?"}${qs.toString()}`;
}

export type ShipStatus = "verified" | "best_effort" | "blocked";

/** Whether the reprint button may download right now (the server checks again; this only mirrors its decision). */
export function reprintOpen(status: ShipStatus, ack: boolean): boolean {
  return status === "verified" || (status === "best_effort" && ack);
}

/** Family and intent for /fix from its query string (the passport page's "it broke in a new place" link). */
export function fixPrefill(search: string, families: readonly string[]): { family: string; intent: string } {
  const qs = new URLSearchParams(search.startsWith("?") ? search.slice(1) : search);
  const fam = (qs.get("family") ?? "").trim();
  const intent = (qs.get("intent") ?? "").trim().slice(0, 500);
  return { family: families.includes(fam) ? fam : "", intent };
}

/** File name for a downloaded passport QR code. */
export function qrFileName(id: string, kind: "png" | "svg"): string {
  return `partsmith-passport-${id}.${kind}`;
}
