"use client";

import { useQuery } from "@tanstack/react-query";
import { Badge } from "@/components/ui/badge";
import { ErrorState } from "@/components/ui/error-state";
import { Skeleton } from "@/components/ui/skeleton";
import { budgetBar, pct, type AdminOverview } from "@/lib/api-admin";
import { fmtMm, fmtUsd, timeAgo, titleCase } from "@/lib/format";
import { cn } from "@/lib/utils";
import { adminApi } from "./api";
import { Bars, Panel, Stat } from "./bits";

function Budget({ o }: { o: AdminOverview }) {
  const b = budgetBar(o.budget);
  return (
    <Panel title="Today's model spend" source={o.budget?.source}>
      {b.share != null ? (
        <div
          className="h-2.5 overflow-hidden rounded-full bg-surface-2"
          role="meter"
          aria-label="Spent against the daily cap"
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={Math.round(b.share * 100)}
        >
          <div className={cn("h-full rounded-full", b.over ? "bg-bad" : b.share > 0.8 ? "bg-warn" : "bg-accent")} style={{ width: `${Math.round(b.share * 100)}%` }} />
        </div>
      ) : null}
      <p className={cn("text-[13px] tnum", b.over ? "text-bad" : "text-muted")}>{b.label}</p>
    </Panel>
  );
}

function Reasons({ o }: { o: AdminOverview }) {
  const p = o.send_back.person;
  return (
    <Panel title="Why parts were sent back" source={o.send_back.source}>
      {p.top.length ? (
        <Bars label="Top reasons from people" rows={p.top.map((r, i) => ({ key: `${i}-${r.reason}`, label: r.reason, value: r.count, text: `${r.count}×` }))} />
      ) : (
        <p className="text-[13px] text-muted">No send-backs from a person yet.</p>
      )}
      <p className="text-[12px] text-muted tnum">
        {p.n} note{p.n === 1 ? "" : "s"} from people. {o.send_back.test.n} from test reviews, kept apart and never counted as people.
      </p>
    </Panel>
  );
}

export function OverviewTab() {
  const q = useQuery({ queryKey: ["admin", "overview"], queryFn: adminApi.overview, retry: false });
  if (q.isPending) return <Skeleton className="h-64" />;
  if (q.isError) return <ErrorState error={q.error} what="the overview" onRetry={() => void q.refetch()} />;
  const o = q.data;
  const rounds = o.rounds_to_verify;
  return (
    <div className="space-y-4">
      <p className="flex flex-wrap items-center gap-2 text-[12px] text-muted">
        {o.mode !== "live" ? <Badge tone="mock">Providers: {o.mode}</Badge> : <Badge tone="ok">Providers: live</Badge>}
        <span>
          Counted {timeAgo(o.generated_at)}. Job numbers leave out the {o.jobs.replays_excluded} recorded run{o.jobs.replays_excluded === 1 ? "" : "s"} (replays); the review queue lists them, counted apart.
        </span>
      </p>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
        <Stat
          label="Pass rate"
          value={pct(o.jobs.pass_rate)}
          sub={`${o.jobs.verified} verified of ${o.jobs.finished} finished · ${o.jobs.total} fix jobs. Counts jobs run on this server, not the bench's fixed test photos on /results.`}
          source={o.jobs.source}
        />
        <Stat
          label="Max error, median"
          value={o.max_error.median_mm == null ? "—" : fmtMm(o.max_error.median_mm)}
          sub={`p90 ${o.max_error.p90_mm == null ? "—" : fmtMm(o.max_error.p90_mm)} · n = ${o.max_error.n}`}
          source={o.max_error.source}
        />
        <Stat
          label="Waiting for review"
          value={o.review.waiting}
          sub={`${o.review.improving} in a reviewer round · ${o.review.accepted} accepted · ${o.review.rejected} rejected · ${o.review.waiting_replays} of the waiting are recorded runs (replays)`}
          source={o.review.source}
        />
        <Stat label="Parts in search" value={o.registry.published} sub={`${o.registry.withdrawn} withdrawn · ${o.registry.reference} reference objects · ${o.registry.n} records`} source={o.registry.source} />
        <Stat label="Open requests" value={o.needs.open} sub={`${o.needs.in_progress} in progress · ${o.needs.fulfilled} done · n = ${o.needs.n}`} source={o.needs.source} />
        <Stat
          label="Model cost"
          value={fmtUsd(o.cost.usd_total)}
          sub={`${o.cost.usd_per_job_mean == null ? "—" : fmtUsd(o.cost.usd_per_job_mean)} per job · n = ${o.cost.n_jobs} jobs`}
          source={o.cost.source}
        />
      </div>
      <Budget o={o} />
      <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
        <Panel title="Rounds to verify" source={rounds.source}>
          {rounds.buckets.length ? (
            <Bars
              label="Verified jobs by fix rounds"
              rows={rounds.buckets.map((b) => ({ key: String(b.rounds), label: `${b.rounds} round${b.rounds === 1 ? "" : "s"}`, value: b.count, text: `${b.count} job${b.count === 1 ? "" : "s"}` }))}
            />
          ) : (
            <p className="text-[13px] text-muted">No verified jobs yet.</p>
          )}
          <p className="text-[12px] text-muted tnum">
            Median {rounds.median ?? "—"} · n = {rounds.n} verified jobs
          </p>
        </Panel>
        <Reasons o={o} />
        <Panel title="Cost by stage" source={o.cost.source}>
          {o.cost.by_stage.length ? (
            <Bars label="Cost by stage" rows={o.cost.by_stage.map((s) => ({ key: s.stage, label: titleCase(s.stage), value: s.usd, text: `${fmtUsd(s.usd)} · ${s.calls} calls` }))} />
          ) : (
            <p className="text-[13px] text-muted">No model calls yet.</p>
          )}
        </Panel>
        <Panel title="Cost by model" source={o.cost.source}>
          {o.cost.by_model.length ? (
            <ul className="divide-y divide-border text-[13px]">
              {o.cost.by_model.map((m) => (
                <li key={`${m.provider}/${m.model}`} className="flex flex-wrap items-baseline justify-between gap-x-3 py-1.5">
                  <span className="min-w-0 break-all font-mono text-[12px] text-fg">{m.model}</span>
                  <span className="text-muted tnum">
                    {fmtUsd(m.usd)} · {m.calls} calls · {m.provider} · {m.modes.join(", ")}
                  </span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-[13px] text-muted">No model calls yet.</p>
          )}
        </Panel>
      </div>
    </div>
  );
}
