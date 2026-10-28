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
