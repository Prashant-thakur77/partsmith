"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "./api";

/** The top verified registry part for a search on this server (for copy-paste examples), or null while unknown. */
export function useExampleSlug(q: string, family: string): string | null {
  const r = useQuery({ queryKey: ["parts", "example-slug", q, family], queryFn: () => api.parts({ q, family, verified: true, limit: 1 }), staleTime: 300_000, retry: false });
  return r.data?.items[0]?.slug ?? null;
}
