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
