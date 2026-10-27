"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { StatsView } from "./stats-view";

/** Client fallback when the server could not fetch the counters (e.g. API was down at render time). */
export function StatsStrip() {
  const q = useQuery({ queryKey: ["stats"], queryFn: api.stats });
  return <StatsView stats={q.data} state={q.isPending ? "pending" : q.isError ? "error" : "ok"} />;
}
