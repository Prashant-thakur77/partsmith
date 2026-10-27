"use client";

import { useMutation, useQuery } from "@tanstack/react-query";
import { ArrowRight, FlaskConical, History, Play } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import * as React from "react";
import { Container, PageHeader, Section } from "@/components/layout/page";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorState } from "@/components/ui/error-state";
import { ModeBadge, OriginBadge } from "@/components/ui/provenance";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { Spinner } from "@/components/ui/spinner";
import { api } from "@/lib/api";
import { fmtNum, titleCase, splitTitle } from "@/lib/format";
import { cn } from "@/lib/utils";
import { radioGroupKeys } from "@/lib/a11y";

export function DemoClient() {
  const router = useRouter();
  const samples = useQuery({ queryKey: ["demo-samples"], queryFn: api.demoSamples });
  const [picked, setPicked] = React.useState<string | null>(null);
  const sample = picked ?? samples.data?.[0]?.id ?? null;
  const sampleTitle = samples.data?.find((x) => x.id === sample)?.title;
  const [showAll, setShowAll] = React.useState(false);
  const [filter, setFilter] = React.useState("");
  const all = samples.data ?? [];
  // Curated demo samples first; the long tail (bench photos) behind "show all" with a filter.
  const featured = all.filter((x) => x.id.startsWith("demo-"));
  const rest = all.filter((x) => !x.id.startsWith("demo-"));
  const f = filter.trim().toLowerCase();
  const shown = (showAll || featured.length === 0 ? all : featured).filter((x) => !f || `${x.title} ${x.id}`.toLowerCase().includes(f));
  const run = useMutation({
    mutationFn: (s: string) => api.createDemoJob(s),
    onSuccess: (job) => router.push(`/jobs/${encodeURIComponent(job.id)}`),
  });
  const replays = useQuery({ queryKey: ["replays"], queryFn: api.replays });

  return (
    <>
      <PageHeader
        eyebrow="Try it without a part"
        title="Run a synthetic sample"
        description="A bundled, rendered photo with exact ground truth goes through the real pipeline — capture gate, measuring, CAD, verifier. Everything it produces is labelled synthetic."
      />
      <Container className="space-y-14 py-10">
        <Section title="Pick a sample" description="Each sample is a rendered part of one family on the screen mat.">
          {samples.isPending ? (
            <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3">
              {Array.from({ length: 6 }, (_, i) => (
                <Skeleton key={i} className="h-16" />
              ))}
            </div>
          ) : samples.isError ? (
            <ErrorState error={samples.error} compact what="the samples" onRetry={() => void samples.refetch()} />
          ) : (
            <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3" role="radiogroup" onKeyDown={radioGroupKeys} aria-label="Sample">
              {shown.map((x) => (
                <button
                  key={x.id}
                  type="button"
                  role="radio"
                  aria-checked={sample === x.id}
                  onClick={() => setPicked(x.id)}
                  className={cn(
                    "flex flex-col items-start gap-1.5 rounded-lg border bg-surface px-3.5 py-3 text-left transition-colors hover:border-border-strong",
                    sample === x.id ? "border-fg shadow-[0_0_0_1px_var(--fg)]" : "border-border",
                  )}
                >
                  <span className="text-[13.5px] leading-5 font-medium text-fg">{splitTitle(x.title).title}</span>
                  <span className="flex flex-wrap gap-1">
                    {x.kind === "reference_object" ? <Badge tone="info">reference object</Badge> : null}
                    {splitTitle(x.title).presets.map((p) => (
                      <Badge key={p} tone="outline">
                        {p}
                      </Badge>
                    ))}
                    {x.family_hint && x.family_hint !== "reference" ? <Badge tone="neutral">{titleCase(x.family_hint)}</Badge> : null}
                    <span className="font-mono text-[11px] text-subtle">{x.id}</span>
                  </span>
                </button>
              ))}
            </div>
          )}
          {rest.length && featured.length ? (
            <div className="flex flex-wrap items-center gap-3">
              <Button variant="ghost" size="sm" onClick={() => setShowAll((v) => !v)} aria-expanded={showAll}>
                {showAll ? "Show the demo samples only" : `Show all ${all.length} samples (incl. bench photos)`}
              </Button>
              {showAll ? (
                <Input aria-label="Filter samples" value={filter} onChange={(e) => setFilter(e.target.value)} placeholder="Filter: glare, tilt, hinge…" className="h-8 max-w-64" />
              ) : null}
            </div>
          ) : null}
          <div className="sticky bottom-0 z-10 -mx-4 flex flex-wrap items-center gap-3 border-t border-border bg-bg/90 px-4 py-3 backdrop-blur sm:static sm:mx-0 sm:border-0 sm:bg-transparent sm:p-0 sm:backdrop-blur-none">
            <Button variant="primary" size="lg" onClick={() => sample && run.mutate(sample)} disabled={run.isPending || !sample}>
              {run.isPending ? <Spinner className="text-accent-fg" label="Starting" /> : <Play aria-hidden />}
              Run this sample
            </Button>
            <Badge tone="mock">
              <FlaskConical aria-hidden /> synthetic input
            </Badge>
            {sampleTitle ? <span className="text-[13px] text-muted">{splitTitle(sampleTitle).title}</span> : null}
          </div>
          {run.isError ? <ErrorState error={run.error} compact what="the sample job" /> : null}
        </Section>

        <Section title="Or watch a recorded run" description="Replays play back a stored run log event by event. Nothing is recomputed, and they are labelled replay.">
          {replays.isPending ? (
            <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
              {[0, 1].map((i) => (
                <Skeleton key={i} className="h-24" />
              ))}
            </div>
          ) : replays.isError ? (
            <ErrorState error={replays.error} compact what="replays" onRetry={() => void replays.refetch()} />
          ) : replays.data.length === 0 ? (
            <EmptyState icon={History} title="No stored runs yet" compact>
              Runs are recorded automatically; the first finished job becomes replayable.
            </EmptyState>
          ) : (
            <ul className="grid grid-cols-1 gap-3 md:grid-cols-2">
              {replays.data.map((r) => (
                <li key={r.id}>
                  <Link
                    href={`/jobs/${encodeURIComponent(r.id)}`}
                    className="group flex items-center justify-between gap-4 rounded-lg border border-border bg-surface p-4 hover:border-border-strong"
                  >
                    <div className="min-w-0 space-y-2">
                      <div className="truncate text-[14px] font-medium">{splitTitle(r.title).title}</div>
                      <div className="flex flex-wrap gap-1.5">
                        <OriginBadge origin={r.origin} />
                        <ModeBadge mode={r.provider_mode} />
                        <Badge tone={r.verified ? "ok" : "warn"}>{r.verified ? "verified" : "not verified"}</Badge>
                        <Badge tone="neutral" className="font-mono tnum">
                          {r.iterations} iter · {r.max_error_mm != null ? `${fmtNum(r.max_error_mm)} mm` : "—"}
                        </Badge>
                      </div>
                    </div>
                    <ArrowRight className="size-4 shrink-0 text-subtle group-hover:text-fg" aria-hidden />
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
