"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import * as React from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorState } from "@/components/ui/error-state";
import { Skeleton } from "@/components/ui/skeleton";
import { ruleTrack, type TaughtRule } from "@/lib/api-admin";
import { timeAgo, titleCase } from "@/lib/format";
import { adminApi } from "./api";
import { ReasonForm } from "./bits";

const SHOWN_JOBS = 6;

function RuleRow({ r }: { r: TaughtRule }) {
  const qc = useQueryClient();
  const [asking, setAsking] = React.useState(false);
  const m = useMutation({
    mutationFn: (reason: string) => adminApi.switchRule(r.id, r.disabled ? "enable" : "disable", reason),
    onSuccess: () => {
      setAsking(false);
      void qc.invalidateQueries({ queryKey: ["admin"] });
    },
  });
  const track = ruleTrack(r);
  return (
    <li className="space-y-2 rounded-lg border border-border bg-surface p-4">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <p className="flex flex-wrap items-center gap-1.5">
          <Badge tone={r.kind === "rule" ? "accent" : "info"}>{r.kind === "rule" ? "family rule" : "past feedback"}</Badge>
          <Badge tone="neutral">{r.family === "global" ? "All parts" : titleCase(r.family)}</Badge>
          {r.disabled ? <Badge tone="bad">switched off</Badge> : <Badge tone="ok">in use</Badge>}
          {r.created_at ? <span className="text-[11.5px] text-subtle">{timeAgo(r.created_at)}</span> : null}
        </p>
        {!asking ? (
          <Button size="sm" variant="outline" onClick={() => setAsking(true)}>
            {r.disabled ? "Switch on" : "Switch off"}
          </Button>
        ) : null}
      </div>
      <p className="break-words text-[14px] leading-6 text-fg">{r.text}</p>
      {r.why ? <p className="text-[12.5px] text-muted">Why: {r.why}</p> : null}
      <p className="text-[12px] text-muted tnum">{track ?? "Not given to any job yet."}</p>
      {r.used_in.length ? (
        <ul className="flex flex-wrap gap-x-3 gap-y-1 text-[12px]" aria-label="Jobs that were given it">
          {r.used_in.slice(0, SHOWN_JOBS).map((j) => (
            <li key={j}>
              <Link href={`/jobs/${encodeURIComponent(j)}`} className="font-mono text-accent-text hover:underline">
                {j}
              </Link>
            </li>
          ))}
          {r.used_in.length > SHOWN_JOBS ? <li className="text-subtle">and {r.used_in.length - SHOWN_JOBS} more</li> : null}
        </ul>
      ) : null}
      {r.origin_job ? (
        <p className="text-[12px] text-subtle">
          Came from job{" "}
          <Link href={`/jobs/${encodeURIComponent(r.origin_job)}`} className="font-mono text-accent-text hover:underline">
            {r.origin_job}
          </Link>
        </p>
      ) : null}
      {r.disabled ? (
        <p className="text-[12.5px] text-muted">
          Switched off {timeAgo(r.disabled.at)} by {r.disabled.by}: “{r.disabled.reason}”. New jobs are not given it.
        </p>
      ) : null}
      {asking ? (
        <ReasonForm
          label={r.disabled ? "Why switch it back on?" : "Why switch it off? New jobs will stop getting it."}
          confirm={r.disabled ? "Switch on" : "Switch off"}
          busy={m.isPending}
          onSubmit={(reason) => m.mutate(reason)}
          onCancel={() => setAsking(false)}
        />
      ) : null}
      {m.isError ? <ErrorState error={m.error} compact what="the change" /> : null}
    </li>
  );
}

export function RulesTab() {
  const q = useQuery({ queryKey: ["admin", "rules"], queryFn: adminApi.rules, retry: false });
  if (q.isPending) return <Skeleton className="h-64" />;
  if (q.isError) return <ErrorState error={q.error} what="the taught rules" onRetry={() => void q.refetch()} />;
  return (
    <div className="space-y-4">
      <p className="max-w-2xl text-[13px] leading-5 text-muted">
        What earlier reviews teach new jobs of the same kind: rules a person ticked, and a person’s feedback that code measured as fixed. Switch one off if it makes
        things worse. It is kept, and the change goes in the audit log.
      </p>
      <p className="text-[12px] text-muted tnum">
        {q.data.n} taught · {q.data.disabled} switched off
      </p>
      {q.data.items.length ? (
        <ul className="grid grid-cols-1 gap-3 lg:grid-cols-2">{q.data.items.map((r) => <RuleRow key={r.id} r={r} />)}</ul>
      ) : (
        <EmptyState compact title="Nothing taught yet">A rule appears here once a person accepts a part and ticks it.</EmptyState>
      )}
      <p className="text-[11px] text-subtle">From {q.data.source}</p>
    </div>
  );
}
