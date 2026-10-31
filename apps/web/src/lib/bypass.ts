/** Plain words for the lying-model evidence on /judges (`eval/bypass.py` → bench evidence). Text only, no numbers typed. */
import type { CaughtLie } from "./api-types";

/** The export line under a caught lie: "Export blocked" (+ when a person may still export it) or "Export allowed". */
export function exportLine(c: Pick<CaughtLie, "export">): { title: string; sub: string | null } {
  if (c.export.ok) return { title: "Export allowed", sub: null };
  return {
    title: "Export blocked",
    sub: c.export.requires_ack ? "A person can still export it as best effort, only after reading this reason and acknowledging it." : null,
  };
}

/** A report caption in plain words: the eval's "brain" (the scripted fake model) is called a model here. */
export function plainNote(note: string): string {
  return note
    .replace(/\bthe model built by the lying brain\b/gi, "the part the lying model built")
    .replace(/\bthe lying brain\b/gi, "the lying model").replace(/\bthe brain\b/gi, "the model").replace(/\bbrain\b/gi, "model");
}

const CHECK_WORDS: Record<string, string> = { "bbox.x": "overall length", "bbox.y": "overall width", "bbox.z": "height", residual_top: "top outline", residual_side: "side outline" };

/** A verifier check id in words: "hole_1.diameter" → "hole 1 diameter", "bbox.x" → "overall length". */
export function plainCheck(id: string): string {
  return CHECK_WORDS[id] ?? id.replace(/[._]+/g, " ").trim();
}
