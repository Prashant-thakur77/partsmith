/**
 * The /how comparison: kinds of tools (categories only, never products or companies) against what PartSmith does.
 * Qualitative cells only — Yes / No / Partial with a short note; no measured numbers live here. PartSmith's own
 * "real millimetres" cell follows the bench: Yes only once real broken parts are benched, else Partial (synthetic so far).
 * Pure and free of runtime imports so `node --test` can load it.
 */

export type Mark = "yes" | "no" | "partial" | "text";
export type Cell = { mark: Mark; label: string; note?: string; href?: string; link?: string };
export type CompareRow = { feature: string; cells: Cell[] };

export const COMPARE_COLUMNS = ["Text-to-CAD tools", "Photo-to-3D generators", "Phone scanning apps", "Model-site customizers", "PartSmith"] as const;

const yes = (note?: string): Cell => ({ mark: "yes", label: "Yes", note });
const no = (note?: string): Cell => ({ mark: "no", label: "No", note });
const partial = (note?: string): Cell => ({ mark: "partial", label: "Partial", note });
const text = (label: string, note?: string): Cell => ({ mark: "text", label, note });

/**
 * Our cell for "real millimetres from a plain photo", from the real-part bench's sample count (`tables.real_ruler.n`;
 * null when the bench report could not be read). The claim is only as strong as what has been tested.
 */
export function realPhotoCell(realBenchN: number | null | undefined): Cell {
  const how = "one photo on a printed or on-screen mat; every size carries ±";
  if (realBenchN != null && realBenchN > 0) return { ...yes(`${how}; benched on real broken parts too`), href: "/results#real_ruler", link: "See Accuracy" };
  if (realBenchN === 0) return { ...partial(`${how}. Tested on synthetic photos so far; real-part bench pending`), href: "/results#real_ruler", link: "See Accuracy" };
  return { ...partial(`${how}. See Accuracy for what has been tested`), href: "/results", link: "See Accuracy" };
}

export function compareRows(realBenchN: number | null | undefined): CompareRow[] {
  return [
  {
    feature: "Real millimetres from a plain photo, with error bars",
    cells: [
      no("you type the sizes"),
      no("shape only; the size is a guess"),
      partial("scale from a depth sensor or many shots; no per-size error bars"),
      no("you type the sizes"),
      realPhotoCell(realBenchN),
    ],
  },
  {
    feature: "Editable knobs (parametric)",
    cells: [yes(), no("a fixed mesh"), no("a fixed mesh"), yes("the designer's sliders"), yes("named knobs in a CadQuery program")],
  },
  {
    feature: "Pass / fail decided by code against your photo",
    cells: [no(), no(), no("the scan is the only reference"), no(), yes("the model cannot mark itself verified")],
  },
  {
    feature: "Learns from your corrections",
    cells: [partial("re-prompt in a chat"), no(), no(), no(), yes("review notes and fit reports become rules once a person approves them")],
  },
  {
    feature: "Fit-test coupon",
    cells: [no(), no(), no(), partial("some designers add a test print by hand"), yes("generated from the part's own holes")],
  },
  {
    feature: "Agent access (REST + MCP)",
    cells: [partial("some offer an API"), partial("some offer an API"), no(), no(), yes("REST, MCP and llms.txt")],
  },
  {
    feature: "Cost to use",
    cells: [text("Usually paid", "credits or a plan"), text("Usually paid", "credits or a plan"), text("Varies", "app or sensor phone"), text("Free"), text("Free", "open registry; the server pays for model calls")],
  },
  ];
}

/** The table when the bench report is unavailable (our real-photo cell then points at Accuracy, claiming nothing). */
export const COMPARE_ROWS: CompareRow[] = compareRows(null);

/** Plain words for a screen reader: "PartSmith: Yes — one photo on a printed or on-screen mat…". */
export function cellText(column: string, cell: Cell): string {
  return `${column}: ${cell.label}${cell.note ? ` — ${cell.note}` : ""}`;
}
