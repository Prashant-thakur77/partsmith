"use client";

import { useQuery } from "@tanstack/react-query";
import { ArrowRight, ChevronRight, Inbox } from "lucide-react";
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
import { fmtErr, fmtUsd, timeAgo, splitTitle } from "@/lib/format";
import type { JobSummary } from "@/lib/api-types";
import { filterJobs, groupJobAttempts, JOB_BUCKETS, jobsSummary, jobsSummaryText, moreAttemptsText, parseJobFilter, type JobsSummary } from "@/lib/page-groups";
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
          {chip(source === "server", "Made here", s.source.server, () => set("source", source === "server" ? null : "server"))}
          {chip(source === "recorded", "Recorded", s.source.recorded, () => set("source", source === "recorded" ? null : "recorded"))}
        </div>
      ) : null}
    </div>
  );
}

function JobRow({ j }: { j: JobSummary }) {
  const recorded = j.is_replay || j.origin === "replay";
  // The status chip already carries the max gap for finished jobs; the meta line shows it only otherwise.
  const gap = j.status !== "done" && j.max_error_mm != null ? `max gap ${fmtErr(j.max_error_mm)} mm` : null;
  const when = `${timeAgo(j.created_at)} · ${j.iterations} iter`;
  // Phones drop the provenance chips, so the same facts lead the meta line in words.
  const tags = [recorded ? "recorded" : null, j.origin !== "replay" && j.origin !== "real" ? j.origin.replace(/_/g, " ") : null, j.provider_mode === "mock" ? "mock models" : null]
    .filter(Boolean)
    .join(" · ");
  return (
    <Link href={`/jobs/${encodeURIComponent(j.id)}`} className="group flex items-center gap-3 px-3 py-3 hover:bg-surface-2 sm:gap-4 sm:px-4" data-testid="job-row">
      <JobThumb id={j.id} className="self-start sm:self-center" />
      <div className="min-w-0 flex-1 space-y-1">
        <div className="line-clamp-2 text-[14px] leading-snug font-medium sm:line-clamp-1">{splitTitle(j.title || j.id).title}</div>
        {/* phones: provenance words, age and rounds; wider screens add the id and the cost */}
        <div className="truncate text-[12px] text-subtle tnum sm:font-mono sm:text-[11.5px]" data-testid="job-meta">
          <span className="hidden sm:inline">{j.id} · </span>
          {tags ? <span className="sm:hidden">{tags} · </span> : null}
          {when}
          <span className="hidden sm:inline"> · {fmtUsd(j.cost_usd)}</span>
          {gap ? ` · ${gap}` : null}
        </div>
        <div className="pt-0.5 sm:hidden">
          <JobStatusBadge job={j} />
        </div>
      </div>
      <div className="hidden shrink-0 flex-wrap items-center justify-end gap-1.5 sm:flex">
        {j.origin !== "replay" ? <OriginBadge origin={j.origin} hideReal plain /> : null}
        {recorded ? <RunBadge mode={j.provider_mode} recorded plain /> : <ModeBadge mode={j.provider_mode} hideLive />}
        <JobStatusBadge job={j} />
      </div>
      <ArrowRight className="size-4 shrink-0 text-subtle group-hover:text-fg" aria-hidden />
    </Link>
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
  // same-title runs fold into one row led by the best attempt (display only: the summary above counts every run)
  const groups = React.useMemo(() => groupJobAttempts(shown), [shown]);
  const [open, setOpen] = React.useState<ReadonlySet<string>>(new Set());
  const toggle = (k: string) =>
    setOpen((cur) => {
      const next = new Set(cur);
      if (next.has(k)) next.delete(k);
      else next.add(k);
      return next;
    });
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
              <p className="text-[12px] text-muted" data-testid="jobs-set-note">
                Listed = made here + recorded; finished = done or failed. The pass rate on the home page counts a different, fixed set of test photos:{" "}
                <Link href="/results#synthetic" className="text-accent-text underline underline-offset-2">
                  see Accuracy
                </Link>
                .
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
            {groups.map((g) => {
              const isOpen = open.has(g.key);
              return (
                <li key={g.lead.id} data-testid="job-group">
                  <JobRow j={g.lead} />
                  {g.others.length ? (
                    <>
                      <button
                        type="button"
                        aria-expanded={isOpen}
                        aria-controls={`more-${g.lead.id}`}
                        onClick={() => toggle(g.key)}
                        className="flex w-full items-center gap-1.5 border-t border-dashed border-border px-3 py-1.5 text-left text-[12px] text-muted hover:bg-surface-2 hover:text-fg sm:px-4 sm:pl-[76px]"
                      >
                        <ChevronRight className={cn("size-3.5 transition-transform", isOpen && "rotate-90")} aria-hidden />
                        {moreAttemptsText(g.others.length)} at the same part
                        <span className="text-subtle">· the best one is shown</span>
                      </button>
                      {isOpen ? (
                        <ul id={`more-${g.lead.id}`} aria-label={`Other attempts: ${splitTitle(g.lead.title || g.lead.id).title}`} className="divide-y divide-border border-t border-border bg-surface-2/40">
                          {g.others.map((o) => (
                            <li key={o.id}>
                              <JobRow j={o} />
                            </li>
                          ))}
                        </ul>
                      ) : null}
                    </>
                  ) : null}
                </li>
              );
            })}
          </ul>
          )}
          </>
        )}
      </Container>
    </>
  );
}
