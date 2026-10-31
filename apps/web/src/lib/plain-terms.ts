/**
 * Plain words for the verifier's and the agent's technical terms, for display only: the stored records (verification
 * reasons, tool results, run.jsonl) stay verbatim. Also sorts the verifier's notes into the ones a person needs for the
 * verdict and the debug lines (alignment refinement, per-view metric dumps) that belong behind a "Details" toggle.
 * Pure, so `node --test` can load it directly.
 */

const REPLACEMENTS: [RegExp, string][] = [
  [/\bP0 tests\b/g, "required tests"],
  [/\bP0 test\b/g, "required test"],
  [/\bP1 tests\b/g, "advisory checks"],
  [/\bP1 test\b/g, "advisory check"],
  [/\bP0\b/g, "required"],
  [/\bP1\b/g, "advisory"],
  // "required test bbox.x: length (long side …)" -> "required test: length (long side …)"; the description says it
  [/\b(test|tests|failed|failing):? (?:bbox|hole_\d+|side|outline)\.[a-z_.]+:\s*/g, "$1: "],
  [/\bbbox\.x\b/g, "length"],
  [/\bbbox\.y\b/g, "width"],
  [/\bbbox\.z\b/g, "height"],
  [/\bmean contour distance\b/g, "average edge gap"],
  [/\bHD95\b/g, "95th-percentile outline gap"],
  [/\bHausdorff\b/g, "outline gap"],
  [/\bIoU\b/g, "overlap (IoU)"],
  // older agent runs said "best"/"worse" for the keep rule's ranking; the rule compares shortfall, not max error
  [/worse than the best committed model — code keeps the best/g, "not closer to passing than the best committed round (judged on how close every check is to passing, not on max error); code keeps that one"],
  [/\bnow the best model\b/g, "now the closest to passing (judged on how close every check is to passing, not on max error)"],
];

export function plainTerms(text: string): string {
  let out = text;
  for (const [re, to] of REPLACEMENTS) out = out.replace(re, to);
  return out.replace(/overlap \(IoU\)\s*\(IoU\)/g, "overlap (IoU)");
}

const DEBUG = [
  /refined in the photo frame by/i,
  /\(photo frame\):\s*IoU/i,
  /\bcompared like for like\b/i,
  /small silhouette .* IoU is reported but not gated/i,
  /^\w+ view \(camera frame\)/i,
];

/** A verifier note that is a measurement-pipeline detail (how the views were aligned and scored), not a finding. A
 * view line that ends "- fails" is a finding: it carries the numbers that missed their limits. */
export function isDebugNote(line: string): boolean {
  if (/-\s*fails\s*$/.test(line)) return false;
  return DEBUG.some((re) => re.test(line));
}

/** Verifier notes split into findings (shown with the verdict) and details (behind a toggle); order kept. */
export function splitNotes(reasons: readonly string[]): { findings: string[]; details: string[] } {
  const findings: string[] = [];
  const details: string[] = [];
  for (const r of reasons) (isDebugNote(r) ? details : findings).push(r);
  return { findings, details };
}

/**
 * The failing check a best-effort reason names first, in two or three words, for a card's status chip: "the side
 * outline is off by up to 0.63 mm …" → "side outline", "the side view's average edge gap is 0.20 mm …" → "side
 * outline", "the outline length is 0.38 mm too long …" → "outline length", "the judge flagged …" → "judge flag",
 * "part test failed: …" → "part test". Reads only the reason text (written by code from the verification record);
 * null when it says nothing this recognises.
 */
export function failingCheckWord(reason: string | null | undefined): string | null {
  const r = (reason ?? "").trim();
  if (!r) return null;
  const view = /^the (\w+) (?:outline\b|view's\b)/i.exec(r);
  if (view) return `${view[1]!.toLowerCase()} outline`;
  if (/^the judge flagged\b/i.test(r)) return "judge flag";
  if (/^part test failed\b/i.test(r)) return "part test";
  const pos = /^(?:the )?([\w ]+?) is [\d.]+ mm off its measured position/i.exec(r);
  if (pos) return `${pos[1]!.replace(/_/g, " ")} position`;
  const size = /^(?:the )?([\w ]+?) is [\d.]+ mm too \w+/i.exec(r);
  if (size) return size[1]!.replace(/_/g, " ");
  return null;
}

/**
 * The failing check to lead a best-effort card with, only when its max error is inside the size limit (a "Best effort
 * · 0.498 mm" chip under a 0.50 mm limit reads like a pass); null otherwise, and the card keeps the millimetres.
 */
export function insideLimitCheckWord(status: string, maxErrorMm: number | null | undefined, reason: string | null | undefined, limitMm: number): string | null {
  if (status !== "best_effort" || maxErrorMm == null || !Number.isFinite(maxErrorMm) || maxErrorMm > limitMm) return null;
  return failingCheckWord(reason);
}
