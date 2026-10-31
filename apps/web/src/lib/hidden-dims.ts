/**
 * Sizes the photo cannot see, typed on /fix: the named kinds the API maps to knobs (services/agent/hidden_dims.py)
 * plus "other" (the user's own words — used by the builder, never checked). Pure and free of runtime imports so
 * `node --test` can load it.
 */

export const HIDDEN_KINDS = [
  { name: "bore_d", label: "Inner bore Ø" },
  { name: "socket_depth", label: "Socket depth" },
  { name: "hole_d", label: "Hole Ø" },
  { name: "wall", label: "Wall thickness" },
  { name: "cable_d", label: "Cable / rod Ø it holds" },
] as const;

export const MAX_HIDDEN = 4;

export type HiddenRow = { kind: string; other: string; value: string };
export type HiddenDimInput = { name: string; value_mm: number };

/** The rows to send (blank rows dropped) and a plain-words problem per row index (empty when all is well). */
export function hiddenDimsPayload(rows: readonly HiddenRow[]): { dims: HiddenDimInput[]; problems: Record<number, string> } {
  const dims: HiddenDimInput[] = [];
  const problems: Record<number, string> = {};
  rows.slice(0, MAX_HIDDEN).forEach((r, i) => {
    const raw = r.value.trim().replace(",", ".");
    const name = r.kind === "other" ? r.other.trim().slice(0, 40) : r.kind;
    if (!raw && !(r.kind === "other" && name)) return; // an empty row is ignored
    const v = Number(raw);
    if (!raw || !Number.isFinite(v) || v <= 0 || v > 2000) {
      problems[i] = "Type a size in mm (more than 0)";
      return;
    }
    if (!name) {
      problems[i] = "Name the size";
      return;
    }
    dims.push({ name, value_mm: Math.round(v * 1000) / 1000 });
  });
  return { dims, problems };
}

/** Words for a row of the job page's "Sizes you gave" list. */
export function hiddenStatusText(status: string): string {
  switch (status) {
    case "checked":
      return "held by the program";
    case "mismatch":
      return "the program differs";
    case "used_not_checked":
      return "used, not checked from the photo";
    default:
      return "checked once the verdict is in";
  }
}
