"use client";

import { useQuery } from "@tanstack/react-query";
import { ArrowRight, Inbox } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import * as React from "react";
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
import { filterJobs, JOB_BUCKETS, jobsSummary, jobsSummaryText, parseJobFilter, type JobsSummary } from "@/lib/page-groups";
import { cn } from "@/lib/utils";

/** Filter chips that live in the URL (?status=…&source=…), so a filtered list can be shared. */
function JobFilters({ s, status, source, set }: { s: JobsSummary; status: string | null; source: string | null; set: (k: "status" | "source", v: string | null) => void }) {
  const chip = (on: boolean, label: string, n: number, onClick: () => void) => (
    <button
      type="button"
      aria-pressed={on}
      onClick={onClick}
      disabled={!on && n === 0}
      className={cn(
        "inline-flex h-7 items-center gap-1.5 rounded-full border px-2.5 text-[12.5px] disabled:opacity-40",
        on ? "border-fg bg-fg text-bg" : "border-border bg-surface text-muted hover:text-fg",
      )}
    >
      {label} <span className="font-mono text-[11px] tnum opacity-80">{n}</span>
    </button>
  );
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
      <div role="group" aria-label="Filter by result" className="flex flex-wrap items-center gap-1.5">
        {chip(!status, "All", s.n, () => set("status", null))}
        {JOB_BUCKETS.filter((b) => b.id !== "in_progress" || s.bucket.in_progress > 0).map((b) =>
          chip(status === b.id, b.label, s.bucket[b.id], () => set("status", status === b.id ? null : b.id)),
        )}
      </div>
      {s.source.recorded > 0 ? (
        <div role="group" aria-label="Filter by where it ran" className="flex flex-wrap items-center gap-1.5">
          {chip(source === "recorded", "Recorded runs", s.source.recorded, () => set("source", source === "recorded" ? null : "recorded"))}
          {chip(source === "server", "Run on this server", s.source.server, () => set("source", source === "server" ? null : "server"))}
        </div>
      ) : null}
    </div>
  );
}

export function JobsClient() {
  const q = useQuery({ queryKey: ["jobs"], queryFn: () => api.jobs(50), refetchInterval: 10_000 });
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const f = parseJobFilter(params.get("status"), params.get("source"));
  const { status: fStatus, source: fSource } = f;
  const summary = React.useMemo(() => (q.data ? jobsSummary(q.data) : null), [q.data]);
  const shown = React.useMemo(() => (q.data ? filterJobs(q.data, { status: fStatus, source: fSource }) : []), [q.data, fStatus, fSource]);
  const set = (k: "status" | "source", v: string | null) => {
    const next = new URLSearchParams(params.toString());
    if (v) next.set(k, v);
    else next.delete(k);
    router.replace(`${pathname}${next.size ? `?${next}` : ""}`, { scroll: false });
  };
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
      <Container className="space-y-4 py-8">
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
          <>
          {summary ? (
            <div className="space-y-3">
              <p className="text-[14px] font-medium tnum" data-testid="jobs-summary">
                {jobsSummaryText(summary)}
                <span className="ml-2 text-[12px] font-normal text-subtle">from the {summary.n} newest jobs listed below</span>
              </p>
              <JobFilters s={summary} status={f.status} source={f.source} set={set} />
            </div>
          ) : null}
          {shown.length === 0 ? (
            <EmptyState compact icon={Inbox} title="No jobs match these filters">
              <button type="button" className="text-accent-text hover:underline" onClick={() => router.replace(pathname, { scroll: false })}>
                Clear the filters
              </button>
            </EmptyState>
          ) : (
          <ul className="divide-y divide-border overflow-hidden rounded-lg border border-border bg-surface" aria-label="Jobs">
            {shown.map((j) => (
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
          </>
        )}
      </Container>
    </>
  );
}
