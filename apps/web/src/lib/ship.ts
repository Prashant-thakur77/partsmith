import type { ShipDecision, Verification } from "./api-types";

/**
 * Mirrors the server's export gate (`can_ship`): verified ships in one click, best effort needs an explicit
 * acknowledgement (sent as `ack=1` where the API asks for it), failed is blocked. The server re-checks every download.
 */
export type ShipState = "verified" | "best_effort" | "blocked";
export function shipState(v: Verification | null | undefined, server?: ShipDecision | null): ShipState {
  if (server) return server.status;
  if (v?.verified && v.status === "verified") return "verified";
  if (v?.status === "best_effort") return "best_effort";
  return "blocked";
}

/** Artifact kinds the server gates (printable files and the zip that carries them); previews and the coupon are open. */
export const PRINTABLE_KINDS: ReadonlySet<string> = new Set(["stl", "threemf", "3mf", "step", "zip"]);

/** Add `ack=1` to a gated file link once the person acknowledged a best-effort export (the server re-checks it). */
export function withAck(url: string | undefined, ack: boolean): string | undefined {
  if (!url || !ack) return url;
  const [path = "", hash = ""] = url.split("#", 2);
  const sep = path.includes("?") ? "&" : "?";
  return `${path}${sep}ack=1${hash ? `#${hash}` : ""}`;
}
