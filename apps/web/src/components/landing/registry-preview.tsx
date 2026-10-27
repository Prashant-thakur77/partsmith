"use client";

import { useQuery } from "@tanstack/react-query";
import { Boxes } from "lucide-react";
import { api } from "@/lib/api";
import { PartCard, PartCardSkeleton } from "../registry/part-card";
import { EmptyState } from "../ui/empty-state";
import { ErrorState } from "../ui/error-state";

export function RegistryPreview() {
  const q = useQuery({ queryKey: ["parts", "preview"], queryFn: () => api.parts({ limit: 8, sort: "newest" }) });
  if (q.isError) return <ErrorState error={q.error} compact what="the registry" onRetry={() => void q.refetch()} />;
  if (q.isSuccess && q.data.items.length === 0)
    return (
      <EmptyState icon={Boxes} title="The registry is empty">
        Verified parts appear here as soon as the first fix job passes.
      </EmptyState>
    );
  return (
    <div className="grid grid-cols-2 gap-3 sm:gap-4 lg:grid-cols-4">
      {q.isPending ? Array.from({ length: 4 }, (_, i) => <PartCardSkeleton key={i} />) : q.data.items.map((p) => <PartCard key={p.slug} part={p} />)}
    </div>
  );
}
