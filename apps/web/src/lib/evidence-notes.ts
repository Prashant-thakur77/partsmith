/**
 * Text helpers for the evidence the workspace shows next to the verdict: knobs no test checked (`Verification.unchecked`),
 * the range a photo allows (`Measured.bound_mm`), the narrated walk-around (`narration.json`) and the voice note sent
 * with a fix job. They only word what code decided; nothing here makes or changes a number.
 *
 * Kept free of runtime imports so `node --test` can load it directly.
 */
import type { NarrationMeasured, NarrationPoint, NarrationRecord } from "./api-types";

/** Evidence note the server puts on every value measured from a narrated point (services/metrology/narration.py). */
export const NARRATION_NOTE = "pointed by Spark (narration)";

function num(v: number, decimals = 2): string {
  return v.toLocaleString("en-US", { minimumFractionDigits: decimals, maximumFractionDigits: decimals });
}

/** True when a measured value's evidence note says it came from a narrated point. */
export function isNarrated(note: string | null | undefined): boolean {
  return !!note && note.includes(NARRATION_NOTE);
}

/** "photo allows 41.20–42.00 mm", or null when there is no usable range. */
export function boundText(bound: readonly [number, number] | null | undefined): string | null {
  if (!bound || bound.length !== 2) return null;
  const [a, b] = bound;
  if (!Number.isFinite(a) || !Number.isFinite(b)) return null;
  const lo = Math.min(a, b);
  const hi = Math.max(a, b);
  return `photo allows ${num(lo)}–${num(hi)} mm`;
}

export const BOUND_TIP =
  "A thick part seen only from the top: if its ends sit lower than the stated height, the photo reads it shorter. " +
  "Any value in this range fits the photo; a side photo (or a walk-around clip) would settle it.";

/** Short reason from an unchecked value's note: the bracketed cause when there is one, else the first clause. */
export function uncheckedReason(note: string): string {
  const first = note.replace(/^\s*not measured:\s*/i, "").split(";")[0]!.trim();
  const inner = /\(([^()]{3,90})\)/.exec(first)?.[1]?.trim();
  const out = inner ?? first;
  return out.length > 90 ? `${out.slice(0, 89)}…` : out;
}

export type NarrationView = {
  /** Function, mating feature, break: words that steer the understand stage only. */
  summary: { label: string; text: string }[];
  kept: (NarrationPoint & { measured: NarrationMeasured | null })[];
  dropped: NarrationPoint[];
  /** Measured features that do not match a kept point by name (still narration-provenance). */
  otherMeasured: NarrationMeasured[];
};

/** Splits a narration record into what the panel shows. Points the server kept carry their measurement when one exists. */
export function narrationView(r: NarrationRecord): NarrationView {
  const n = r.narration;
  const summary = [
    { label: "What it does", text: n.function },
    { label: "Mating feature", text: n.mating_feature },
    { label: "The break", text: n.break_description },
  ].filter((x) => x.text.trim());
  const byId = new Map(r.measured.map((m) => [m.id, m]));
  const used = new Set<string>();
  const kept = r.points
    .filter((p) => p.ok)
    .map((p) => {
      const m = byId.get(p.name) ?? null;
      if (m) used.add(m.id);
      return { ...p, measured: m };
    });
  const dropped = r.points.filter((p) => !p.ok);
  return { summary, kept, dropped, otherMeasured: r.measured.filter((m) => !used.has(m.id)) };
}

/** "diameter 4.20 mm, depth 3.00 mm" from a measured feature's values. */
export function measuredValuesText(values: Record<string, number>): string {
  return Object.entries(values)
    .filter(([, v]) => Number.isFinite(v))
    .map(([k, v]) => `${k.replaceAll("_", " ")} ${num(v)} mm`)
    .join(", ");
}

// ── voice note sent with /jobs/fix ───────────────────────────────────────────

/** Same limit and types as the API's `check_audio` (services/api/uploads.py). */
export const VOICE_NOTE_MAX_BYTES = 15 * 1024 * 1024;
export const VOICE_NOTE_TYPES = [
  "audio/wav",
  "audio/x-wav",
  "audio/wave",
  "audio/webm",
  "audio/ogg",
  "audio/mpeg",
  "audio/mp4",
  "audio/m4a",
  "audio/x-m4a",
  "audio/aac",
  "audio/flac",
  "video/webm",
] as const;

/** Why a voice note would be refused before uploading it, or null when it looks fine. */
export function voiceNoteProblem(type: string, size: number): string | null {
  if (size <= 0) return "The voice note is empty. Record it again.";
  if (size > VOICE_NOTE_MAX_BYTES) return `The voice note is ${(size / 1e6).toFixed(1)} MB; the limit is 15 MB. Keep it under a minute.`;
  const t = (type || "").split(";")[0]!.trim().toLowerCase();
  if (t && !(VOICE_NOTE_TYPES as readonly string[]).includes(t)) return `${t} is not an accepted audio type. Use WAV, WebM, OGG, MP3 or M4A.`;
  return null;
}

/** File name for a recorded Blob, so the server sees a sensible extension. */
export function voiceNoteName(type: string): string {
  const t = type.toLowerCase();
  const ext = t.includes("ogg") ? "ogg" : t.includes("mp4") || t.includes("m4a") || t.includes("aac") ? "m4a" : t.includes("mpeg") ? "mp3" : t.includes("wav") ? "wav" : "webm";
  return `voice-note.${ext}`;
}

/** MIME type from a file name, for files the OS hands over without one (the server checks the declared type). */
export function audioTypeFromName(name: string): string | null {
  const ext = /\.([a-z0-9]+)$/i.exec(name)?.[1]?.toLowerCase();
  const map: Record<string, string> = { wav: "audio/wav", webm: "audio/webm", ogg: "audio/ogg", oga: "audio/ogg", opus: "audio/ogg", mp3: "audio/mpeg", m4a: "audio/mp4", mp4: "audio/mp4", aac: "audio/aac", flac: "audio/flac" };
  return ext ? (map[ext] ?? null) : null;
}

/** Plain words for an upload the API refused (413 too large, 415 wrong type), else null. */
export function uploadRefusal(status: number, message: string): string | null {
  const field = /^(\w+):/.exec(message)?.[1];
  const what =
    field === "narration" ? "The voice note" : field === "orbit" ? "The walk-around clip" : field ? `The ${field} photo` : "A file";
  if (status === 413) return `${what} is too large for the server. ${message}`;
  if (status === 415) return `${what} is in a format the server does not accept. ${message}`;
  return null;
}

/**
 * "Outline verified · 4 of 6 knobs measured" for a verified record that lists the knobs no test checked; null when the
 * record is not verified or does not list unchecked knobs (older records), so nothing is claimed either way.
 */
export function verifiedScope(
  verification: { verified: boolean; unchecked: readonly { param: string }[] } | null | undefined,
  params: readonly { name: string }[],
): string | null {
  if (!verification?.verified || !verification.unchecked.length || !params.length) return null;
  const names = new Set(params.map((p) => p.name));
  const open = verification.unchecked.filter((u) => names.has(u.param)).length;
  if (!open) return null;
  return `Outline verified · ${params.length - open} of ${params.length} knobs measured`;
}

/**
 * One plain phrase for the part tests: "all 10 required part tests passed, plus 4 extra checks (4 passed)". Required
 * (P0) tests decide the verdict; extra (P1) checks are informational. Null without tests.
 */
export function testsPhrase(tests: readonly { passed: boolean; priority?: "P0" | "P1" }[]): string | null {
  if (!tests.length) return null;
  const req = tests.filter((t) => (t.priority ?? "P0") === "P0");
  const extra = tests.filter((t) => t.priority === "P1");
  const reqOk = req.filter((t) => t.passed).length;
  const head = !req.length
    ? "no required part tests"
    : reqOk === req.length
      ? req.length === 1
        ? "the required part test passed"
        : `all ${req.length} required part tests passed`
      : `${reqOk} of ${req.length} required part tests passed`;
  if (!extra.length) return head;
  const extraOk = extra.filter((t) => t.passed).length;
  return `${head}, plus ${extra.length} extra check${extra.length === 1 ? "" : "s"} (${extraOk} passed)`;
}

/** The verifier's own "Verified: all N P0 tests pass …" summary line, which `testsPhrase` already says in plain words. */
export function isTestsSummaryReason(reason: string): boolean {
  return /^Verified: all \d+ P0 tests pass/.test(reason);
}
