"use client";

import { useQuery } from "@tanstack/react-query";
import { ArrowUpRight } from "lucide-react";
import Link from "next/link";
import * as React from "react";
import { api, artifactUrl } from "@/lib/api";
import { cn } from "@/lib/utils";
import { KnobPanel } from "../registry/knob-panel";
import { PartStatusBadge } from "../registry/part-status";
import { useLivePart } from "../registry/live-part";
import { ErrorState } from "../ui/error-state";
import { Skeleton } from "../ui/skeleton";
import { OriginBadge } from "../ui/provenance";
import { CadViewer } from "../viewer/cad-viewer";

/** Landing hero demo: drag knobs on a real registry part; every change re-bakes through `/parts/{slug}/bake`. */
export function LiveKnobDemo() {
  const verifiedList = useQuery({ queryKey: ["parts", "hero"], queryFn: () => api.parts({ verified: true, limit: 4, sort: "newest" }) });
  // No verified parts yet: show the closest best-effort ones — their badges say so.
  const anyList = useQuery({
    queryKey: ["parts", "hero-any"],
    queryFn: () => api.parts({ limit: 4, sort: "error" }),
    enabled: verifiedList.isSuccess && verifiedList.data.items.length === 0,
  });
  const list = verifiedList.isSuccess && verifiedList.data.items.length === 0 ? anyList : verifiedList;
  const parts = list.data?.items ?? [];
  const [slug, setSlug] = React.useState<string | null>(null);
  const active = slug ?? parts[0]?.slug ?? null;
  const live = useLivePart(active);
  const card = parts.find((p) => p.slug === active);
  const params = live.part.data?.params ?? [];

  if (list.isError) {
    return (
      <div className="overflow-hidden rounded-xl border border-border bg-surface shadow-lg">
        <ErrorState error={list.error} onRetry={() => void list.refetch()} what="the live demo" className="m-4 border-0" />
      </div>
    );
  }
  if (list.isSuccess && parts.length === 0) {
    return (
      <div className="overflow-hidden rounded-xl border border-dashed border-border-strong bg-surface p-8 text-center text-[13px] text-muted">
        The registry is empty. Seed it (<code className="font-mono">partsmith seed</code>) or publish your first fix.
      </div>
    );
  }

  return (
    <div className="overflow-hidden rounded-xl border border-border bg-surface shadow-lg">
      <div className="flex items-center gap-1 overflow-x-auto border-b border-border px-2 py-1.5 no-scrollbar" role="tablist" aria-label="Demo parts">
        {list.isPending
          ? [0, 1, 2].map((i) => <Skeleton key={i} className="h-7 w-28" />)
          : parts.map((p) => (
              <button
                key={p.slug}
                role="tab"
                aria-selected={p.slug === active}
                type="button"
                onClick={() => setSlug(p.slug)}
                className={cn(
                  "h-7 shrink-0 rounded-md px-2.5 text-[12px] font-medium text-muted transition-colors hover:text-fg",
                  p.slug === active && "bg-surface-2 text-fg",
                )}
              >
                {p.title}
              </button>
            ))}
      </div>
      {/* fixed height on desktop: loading → loaded never shifts the hero */}
      <div className="grid md:h-[456px] md:grid-cols-[minmax(0,1fr)_268px]">
        <CadViewer
          viewUrl={live.viewUrl}
          poster={artifactUrl(card?.thumbnail_url)}
          poster2x={artifactUrl(card?.thumbnail_2x_url)}
          busy={live.bake.pending}
          className="aspect-[4/3] md:aspect-auto md:h-full"
          label={card ? `3D model of ${card.title}` : "3D model"}
          emptyText={list.isPending ? "Loading…" : "No model yet."}
        />
        <div className="scrollbar-thin flex min-h-0 flex-col gap-4 border-t border-border p-4 md:overflow-y-auto md:border-t-0 md:border-l">
          {card ? (
            <div className="flex flex-wrap items-center gap-1.5">
              <PartStatusBadge status={card.status} maxErrorMm={card.max_error_mm} />
              <OriginBadge origin={card.origin} hideReal />
            </div>
          ) : (
            <Skeleton className="h-5 w-32" />
          )}
          {live.part.isPending && active ? (
            <div className="space-y-4">
              {[0, 1, 2].map((i) => (
                <Skeleton key={i} className="h-12" />
              ))}
            </div>
          ) : live.part.isError ? (
            <ErrorState error={live.part.error} compact what="this part" />
          ) : (
            <KnobPanel
              params={params.slice(0, 4)}
              values={live.values}
              onChange={live.setValues}
              bake={live.bake.data}
              pending={live.bake.pending && live.changed}
              error={live.bake.error}
              dense
            />
          )}
          {active ? (
            <Link
              href={`/parts/${encodeURIComponent(active)}`}
              className="mt-auto inline-flex items-center gap-1 text-[13px] font-medium text-accent-text hover:underline"
            >
              Open part page{params.length > 4 ? ` · all ${params.length} knobs` : ""} <ArrowUpRight className="size-3.5" aria-hidden />
            </Link>
          ) : null}
        </div>
      </div>
    </div>
  );
}
