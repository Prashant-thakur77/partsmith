/**
 * "Open in slicer" hand-off for a 3MF. Desktop slicers register a URL scheme that downloads a file from a web URL and
 * opens it: Bambu Studio (`bambustudio://open?file=<url>`) and OrcaSlicer (`orcaslicer://open?file=<url>`).
 * PrusaSlicer's scheme only accepts links from its own model site, so for it we offer the download plus a one-line
 * instruction instead. The export gate applies unchanged: blocked shows nothing, best effort only after the person's
 * acknowledgement (and the file URL then carries `ack=1`; the server re-checks it on the slicer's download).
 *
 * Kept free of runtime imports so `node --test` can load it directly.
 */
import type { ShipState } from "./ship";

export type SlicerId = "bambu" | "orca" | "prusa";

export type Slicer = {
  id: SlicerId;
  name: string;
  /** Deep link that makes the installed slicer download and open `fileUrl`, or null when it cannot take a web URL. */
  deepLink: ((fileUrl: string) => string) | null;
  /** What to do by hand when there is no deep link (or it did nothing). */
  howTo: string;
};

export const SLICERS: readonly Slicer[] = [
  {
    id: "bambu",
    name: "Bambu Studio",
    deepLink: (u) => `bambustudio://open?file=${encodeURIComponent(u)}`,
    howTo: "Nothing opened? Download the 3MF, then in Bambu Studio choose File → Import (Ctrl+I).",
  },
  {
    id: "orca",
    name: "OrcaSlicer",
    deepLink: (u) => `orcaslicer://open?file=${encodeURIComponent(u)}`,
    howTo: "Nothing opened? Download the 3MF, then in OrcaSlicer choose File → Import (Ctrl+I).",
  },
  {
    id: "prusa",
    name: "PrusaSlicer",
    deepLink: null,
    howTo: "Download the 3MF, then in PrusaSlicer choose File → Import (Ctrl+I).",
  },
];

export type SlicerHandoff =
  | { state: "hidden" }
  | { state: "needs_ack" }
  | { state: "ready"; fileUrl: string; links: { slicer: Slicer; href: string | null }[] };

/** Absolute URL of a file link (slicers download it themselves, so a relative `/api/v1/...` path is not enough). */
export function absoluteUrl(url: string, origin: string): string {
  return new URL(url, origin.endsWith("/") ? origin : `${origin}/`).href;
}

/**
 * The hand-off for one 3MF under the export gate. `fileUrl` is the gated download link exactly as the page offers it
 * (with `ack=1` already added for an acknowledged best-effort part).
 */
export function slicerHandoff(fileUrl: string | null | undefined, origin: string, ship: ShipState, ack: boolean): SlicerHandoff {
  if (!fileUrl || ship === "blocked") return { state: "hidden" };
  if (ship === "best_effort" && !ack) return { state: "needs_ack" };
  if (ship === "best_effort" && !/[?&]ack=1(&|#|$)/.test(fileUrl)) return { state: "needs_ack" }; // never hand off a link the gate will refuse
  const abs = absoluteUrl(fileUrl, origin);
  return { state: "ready", fileUrl: abs, links: SLICERS.map((s) => ({ slicer: s, href: s.deepLink ? s.deepLink(abs) : null })) };
}
