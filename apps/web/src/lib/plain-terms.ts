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
