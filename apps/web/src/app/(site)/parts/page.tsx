import { HydrationBoundary, QueryClient, dehydrate } from "@tanstack/react-query";
import type { Metadata } from "next";
import { Suspense } from "react";
import { api, type PartsQuery } from "@/lib/api";
import { PartsClient } from "./parts-client";

export const metadata: Metadata = {
  title: "Registry",
  description: "Search verified parametric replacement parts with typed knobs, verification records and provenance.",
};

type SP = Promise<Record<string, string | string[] | undefined>>;

/** Server-renders the first page of results (same query key as the client) so the grid is in the first paint. */
export default async function PartsPage({ searchParams }: { searchParams: SP }) {
  const sp = await searchParams;
  const one = (k: string) => (typeof sp[k] === "string" ? (sp[k] as string) : "");
  const key = { q: one("q"), family: one("family"), verified: one("verified") === "true", sort: (one("sort") || undefined) as PartsQuery["sort"] };
  const qc = new QueryClient();
  await Promise.allSettled([
    qc.prefetchInfiniteQuery({
      queryKey: ["parts", key],
      queryFn: () => api.parts({ q: key.q || undefined, family: key.family || undefined, verified: key.verified, sort: key.sort, limit: 24 }),
      initialPageParam: null as string | null,
    }),
    qc.prefetchQuery({ queryKey: ["families"], queryFn: api.families }),
  ]);
  return (
    <HydrationBoundary state={dehydrate(qc)}>
      <Suspense>
        <PartsClient />
      </Suspense>
    </HydrationBoundary>
  );
}
