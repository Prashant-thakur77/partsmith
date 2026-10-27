"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { ErrorState } from "../ui/error-state";
import { RegistryView } from "./registry-view";

/** Client fallback when the server could not fetch the preview. */
export function RegistryPreview() {
  const q = useQuery({ queryKey: ["parts", "preview"], queryFn: () => api.parts({ limit: 8, sort: "newest" }) });
  if (q.isError) return <ErrorState error={q.error} compact what="the registry" onRetry={() => void q.refetch()} />;
  return <RegistryView items={q.data?.items ?? null} />;
}
