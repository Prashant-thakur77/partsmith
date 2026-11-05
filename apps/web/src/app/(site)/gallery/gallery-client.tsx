"use client";

import { useQuery } from "@tanstack/react-query";
import { Boxes } from "lucide-react";
import Link from "next/link";
import * as React from "react";
import { Container, PageHeader, Section } from "@/components/layout/page";
import { PartStatusBadge } from "@/components/registry/part-status";
import { Badge } from "@/components/ui/badge";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorState } from "@/components/ui/error-state";
import { Skeleton } from "@/components/ui/skeleton";
import { Toggle } from "@/components/ui/toggle";
import { BakedMesh } from "@/components/viewer/baked-mesh";
import { api, artifactUrl } from "@/lib/api";
import { productApi } from "@/lib/api-product";
import type { PartCard } from "@/lib/api-types";
import { useInView } from "@/lib/motion";

const cardCls = "group flex flex-col overflow-hidden rounded-lg border border-border bg-surface transition-colors hover:border-border-strong";

/** A part: its mesh is baked on the server once the card is near the screen, and the 3D view goes away again when it leaves. */
function Live({ queryKey, bake, poster, label }: { queryKey: string[]; bake: (signal: AbortSignal) => Promise<{ artifacts: Record<string, string> }>; poster?: string; label: string }) {
  const { ref, seen } = useInView<HTMLDivElement>({ threshold: 0, rootMargin: "100px", once: false });
  const q = useQuery({ queryKey, queryFn: ({ signal }) => bake(signal), enabled: seen, staleTime: Infinity, retry: false });
  const view = artifactUrl(q.data?.artifacts.view);
  return (
    <div ref={ref} className="h-[190px] bg-paper">
      {seen ? (
        <BakedMesh key={view ?? "poster"} file={view} label={label} poster={poster} className="h-full" />
      ) : (
        // eslint-disable-next-line @next/next/no-img-element -- an API thumbnail until the 3D view mounts
        poster ? <img src={poster} alt={label} className="size-full object-contain" loading="lazy" /> : null
      )}
    </div>
  );
}

function PartTile({ part }: { part: PartCard }) {
  return (
    <li>
      <Link href={`/parts/${encodeURIComponent(part.slug)}`} className={cardCls}>
        <Live
          queryKey={["gallery-part", part.slug]}
          bake={(signal) => api.bake(part.slug, {}, "view", signal)}
          poster={artifactUrl(part.thumbnail_url)}
          label={`3D model of ${part.title}`}
        />
        <div className="space-y-1.5 border-t border-border p-3">
          <p className="text-[14px] font-medium">{part.title}</p>
          <PartStatusBadge status={part.status} maxErrorMm={part.max_error_mm} />
          <p className="text-[12px] text-muted">
            {part.params_count} knobs · {part.origin === "synthetic" ? "from a rendered sample" : part.origin}
          </p>
        </div>
      </Link>
    </li>
  );
}

export function GalleryClient() {
  const parts = useQuery({ queryKey: ["gallery-parts"], queryFn: () => api.parts({ limit: 60 }) });
  const templates = useQuery({ queryKey: ["templates"], queryFn: productApi.templates });
  const [verifiedOnly, setVerifiedOnly] = React.useState(false);
  const items = parts.data?.items ?? [];
  const shown = verifiedOnly ? items.filter((p) => p.status === "verified") : items;
  const verified = items.filter((p) => p.status === "verified").length;
  return (
    <>
      <PageHeader
        eyebrow="Gallery"
        title="Every part, in 3D"
        description="Drag any model to turn it. Each one is a real CadQuery program with named knobs. Registry parts come from runs through the full loop; templates are starting points that have not been checked against a real part."
      />
      <Container className="space-y-12 py-8">
        <Section
          id="registry"
          title="Registry parts"
          description={parts.data ? `${verified} of ${items.length} verified by code against their photos; the rest are labelled best effort.` : undefined}
          actions={
            <Toggle pressed={verifiedOnly} onPressedChange={setVerifiedOnly}>
              Verified only
            </Toggle>
          }
        >
          {parts.isPending ? (
            <div role="status" aria-label="Loading the registry" className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {[0, 1, 2].map((i) => (
                <Skeleton key={i} className="h-[290px]" />
              ))}
            </div>
          ) : parts.isError ? (
            <ErrorState error={parts.error} what="the registry" onRetry={() => void parts.refetch()} />
          ) : !shown.length ? (
            <EmptyState icon={Boxes} title={verifiedOnly ? "No verified parts on this server yet" : "No parts published on this server yet"}>
              Run a sample through the loop, or start from a template below.
            </EmptyState>
          ) : (
            <ul className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {shown.map((p) => (
                <PartTile key={p.slug} part={p} />
              ))}
            </ul>
          )}
        </Section>
        <Section id="templates" title="Templates" description="Open one to drag every knob and see the program change. The agent plans from the bench's set; the newer ones can be built here or from a description, and no run has used them yet.">
          {templates.isPending ? (
            <div role="status" aria-label="Loading the templates">
              <Skeleton className="h-[290px]" />
            </div>
          ) : templates.isError ? (
            <ErrorState error={templates.error} what="the templates" onRetry={() => void templates.refetch()} />
          ) : (
            <ul className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {templates.data.map((t) => (
                <li key={t.name}>
                  <Link href={`/playground?t=${encodeURIComponent(t.name)}`} className={cardCls}>
                    <Live
                      queryKey={["gallery-template", t.name]}
                      bake={(signal) => productApi.templateBake(t.name, {}, signal)}
                      poster={artifactUrl(t.thumbnail_url)}
                      label={`3D model of the ${t.title} template`}
                    />
                    <div className="space-y-1.5 border-t border-border p-3">
                      <p className="text-[14px] font-medium">{t.title}</p>
                      <div className="flex flex-wrap gap-1.5">
                        <Badge tone="neutral">Template · not checked against a real part</Badge>
                        {t.in_bench === false ? <Badge tone="outline">Newer · no run has used it</Badge> : null}
                      </div>
                      <p className="text-[12px] text-muted">{t.params.length} knobs</p>
                    </div>
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </Section>
      </Container>
    </>
  );
}
