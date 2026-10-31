"use client";

import { useQuery } from "@tanstack/react-query";
import { ArrowRight, Inbox } from "lucide-react";
import Link from "next/link";
import { JobStatusBadge } from "@/components/jobs/job-badges";
import { JobThumb } from "@/components/jobs/job-thumb";
import { Container, PageHeader } from "@/components/layout/page";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorState } from "@/components/ui/error-state";
import { ModeBadge, OriginBadge, RunBadge } from "@/components/ui/provenance";
import { Skeleton } from "@/components/ui/skeleton";
import { api } from "@/lib/api";
import { fmtMm, fmtUsd, timeAgo, splitTitle } from "@/lib/format";

export function JobsClient() {
  const q = useQuery({ queryKey: ["jobs"], queryFn: () => api.jobs(50), refetchInterval: 10_000 });
  return (
    <>
      <PageHeader
        title="Recent jobs"
        description="Every fix job on this instance, newest first."
        actions={
          <Button asChild variant="primary">
            <Link href="/fix">New fix</Link>
          </Button>
        }
      />
      <Container className="py-8">
        {q.isPending ? (
          <div className="space-y-2">
            {[0, 1, 2, 3].map((i) => (
              <Skeleton key={i} className="h-14" />
            ))}
          </div>
        ) : q.isError ? (
          <ErrorState error={q.error} what="jobs" onRetry={() => void q.refetch()} />
        ) : q.data.length === 0 ? (
          <EmptyState
            icon={Inbox}
            title="No jobs yet"
            action={
              <>
                <Button asChild variant="primary" size="sm">
                  <Link href="/fix">Fix a part</Link>
                </Button>
                <Button asChild variant="outline" size="sm">
                  <Link href="/jobs/demo">Try a synthetic sample</Link>
                </Button>
              </>
            }
          >
            Start one from your own photos or run a labelled synthetic sample.
          </EmptyState>
        ) : (
          <ul className="divide-y divide-border overflow-hidden rounded-lg border border-border bg-surface">
            {q.data.map((j) => (
              <li key={j.id}>
                <Link href={`/jobs/${encodeURIComponent(j.id)}`} className="group flex items-center gap-4 px-4 py-3 hover:bg-surface-2">
                  <JobThumb id={j.id} />
                  <div className="min-w-0 flex-1 space-y-1">
                    <div className="truncate text-[14px] font-medium">{splitTitle(j.title || j.id).title}</div>
                    <div className="flex flex-wrap items-center gap-1.5 text-[12px] text-subtle">
                      <span className="font-mono">{j.id}</span>
                      <span aria-hidden>·</span>
                      <span>{timeAgo(j.created_at)}</span>
                      <span aria-hidden>·</span>
                      <span className="font-mono tnum">{j.iterations} iter</span>
                      <span aria-hidden>·</span>
                      <span className="font-mono tnum">{fmtUsd(j.cost_usd)}</span>
                      {j.max_error_mm != null ? (
                        <>
                          <span aria-hidden>·</span>
                          <span className="font-mono tnum">max gap {fmtMm(j.max_error_mm)}</span>
                        </>
                      ) : null}
                    </div>
                  </div>
                  <div className="hidden flex-wrap items-center justify-end gap-1.5 sm:flex">
                    {j.origin !== "replay" ? <OriginBadge origin={j.origin} hideReal /> : null}
                    {j.is_replay || j.origin === "replay" ? <RunBadge mode={j.provider_mode} recorded /> : <ModeBadge mode={j.provider_mode} hideLive />}
                    <JobStatusBadge job={j} />
                  </div>
                  <div className="sm:hidden">
                    <JobStatusBadge job={j} />
                  </div>
                  <ArrowRight className="size-4 shrink-0 text-subtle group-hover:text-fg" aria-hidden />
                </Link>
              </li>
            ))}
          </ul>
        )}
      </Container>
    </>
  );
}
