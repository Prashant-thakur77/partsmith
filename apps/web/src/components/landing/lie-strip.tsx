"use client";

import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { BenchReport } from "@/lib/api-types";
import { LieCaught } from "../judges/lie-caught";
import { Skeleton } from "../ui/skeleton";

/** The judge page's caught-lie cards, read from the bench report's evidence (scripted attacks, labelled as such). */
export function LieStrip({ bench: initial }: { bench?: BenchReport | null }) {
  const q = useQuery({ queryKey: ["bench"], queryFn: api.bench, initialData: initial ?? undefined, initialDataUpdatedAt: 0, retry: false, staleTime: 300_000 });
  if (q.isPending) return <Skeleton className="h-72" />;
  return <LieCaught report={q.data?.evidence?.bypass} />;
}
