"use client";

import { useQuery } from "@tanstack/react-query";
import { ArrowRight, Gauge, History, Pause, Play, RotateCcw, Server, Terminal } from "lucide-react";
import Link from "next/link";
import * as React from "react";
import { ConvergenceChart } from "@/components/jobs/convergence-chart";
import { TraceTimeline } from "@/components/jobs/trace-timeline";
import { Container, PageHeader, Section } from "@/components/layout/page";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Eyebrow } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorState } from "@/components/ui/error-state";
import { ModeBadge, OriginBadge } from "@/components/ui/provenance";
import { Skeleton } from "@/components/ui/skeleton";
import { Slider } from "@/components/ui/slider";
import { VerifiedBadge } from "@/components/ui/verified-badge";
import { api } from "@/lib/api";
import { fmtNum } from "@/lib/format";
import { STAGE_LABELS, summarizeEvents } from "@/lib/job-events";
import { cn } from "@/lib/utils";

const REPO_URL = process.env.NEXT_PUBLIC_REPO_URL ?? "";

/** Plays a stored run back event by event (labelled replay). The Verified badge appears only at the end, from the stored verification. */
function ReplayPlayer({ id }: { id: string }) {
  const job = useQuery({ queryKey: ["job", id], queryFn: () => api.job(id) });
  const events = React.useMemo(() => job.data?.events ?? [], [job.data?.events]);
  const [idx, setIdx] = React.useState(0);
  const [playing, setPlaying] = React.useState(false);
  const [speed, setSpeed] = React.useState(2);

  React.useEffect(() => {
    setIdx(0);
    setPlaying(false);
  }, [id]);

  React.useEffect(() => {
    if (!playing || idx >= events.length) {
      if (idx >= events.length && events.length) setPlaying(false);
      return;
    }
    const cur = events[idx - 1];
    const next = events[idx];
    const gap = cur && next && next.ts > cur.ts ? (next.ts - cur.ts) * 1000 : 300;
    const t = window.setTimeout(() => setIdx((i) => i + 1), Math.min(1200, Math.max(60, gap)) / speed);
    return () => window.clearTimeout(t);
  }, [playing, idx, events, speed]);

  if (job.isError) return <ErrorState error={job.error} compact what="the replay" />;
  if (!job.data) return <Skeleton className="h-80" />;

  const s = summarizeEvents(events.slice(0, idx));
  const finished = idx >= events.length && events.length > 0;
  const threshold = job.data.verification?.thresholds.hausdorff_mm ?? null;
  const last = s.convergence.filter((c) => c.hausdorff_mm != null).at(-1)?.hausdorff_mm;

  return (
    <div className="overflow-hidden rounded-xl border border-border bg-surface">
      <div className="flex flex-wrap items-center gap-2 border-b border-border px-4 py-3">
        <Badge tone="mock" upper>
          <History aria-hidden /> replay
        </Badge>
        <span className="truncate text-[14px] font-medium">{job.data.summary.title || id}</span>
        <OriginBadge origin={job.data.summary.origin} hideReal />
        <ModeBadge mode={job.data.summary.provider_mode} />
        <div className="ml-auto">
          {finished ? (
            <VerifiedBadge verification={job.data.verification} />
          ) : (
            <Badge tone="neutral">{playing ? "verifier result at the end" : "press play"}</Badge>
          )}
        </div>
      </div>
      <div className="grid grid-cols-1 gap-0 md:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
        <div className="space-y-4 border-b border-border p-4 md:border-r md:border-b-0">
          <div aria-live="polite" className="min-h-10">
            <Eyebrow>Now</Eyebrow>
            <p className="text-[15px] font-medium">
              {s.done
                ? `Finished: ${s.done.status.replace("_", " ")}`
                : s.current
                  ? `${STAGE_LABELS[s.current.stage]}${s.current.label ? ` — ${s.current.label}` : ""}`
                  : "Press play"}
            </p>
          </div>
          <div>
            <div className="mb-1.5 flex items-center justify-between">
              <Eyebrow>Max error per iteration</Eyebrow>
              {last != null ? <span className="font-mono text-[13px] tnum">{fmtNum(last)} mm</span> : null}
            </div>
            <ConvergenceChart data={s.convergence} threshold={threshold} height={170} />
          </div>
        </div>
        <div className="scrollbar-thin max-h-[360px] overflow-y-auto p-4" tabIndex={0} role="region" aria-label="Replay trace">
          <TraceTimeline summary={s} live={playing} />
        </div>
      </div>
      <div className="flex flex-wrap items-center gap-3 border-t border-border px-4 py-3">
        <Button size="sm" variant="primary" onClick={() => (finished ? (setIdx(0), setPlaying(true)) : setPlaying((p) => !p))} disabled={!events.length}>
          {playing ? <Pause aria-hidden /> : finished ? <RotateCcw aria-hidden /> : <Play aria-hidden />}
          {playing ? "Pause" : finished ? "Replay again" : "Play"}
        </Button>
        <Slider
          aria-label="Replay position"
          className="min-w-40 flex-1"
          min={0}
          max={Math.max(1, events.length)}
          step={1}
          value={[idx]}
          onValueChange={(v) => {
            setPlaying(false);
            setIdx(v[0] ?? 0);
          }}
        />
        <span className="font-mono text-[12px] text-muted tnum">
          {idx}/{events.length} events
        </span>
        <div className="inline-flex rounded-md border border-border bg-surface-2 p-0.5" role="radiogroup" aria-label="Speed">
          {[1, 2, 4].map((x) => (
            <button
              key={x}
              type="button"
              role="radio"
              aria-checked={speed === x}
              onClick={() => setSpeed(x)}
              className={cn("h-6 w-9 rounded-[4px] font-mono text-[11px] text-muted", speed === x && "bg-surface text-fg shadow-sm")}
            >
              {x}×
            </button>
          ))}
        </div>
        <Link href={`/jobs/${encodeURIComponent(id)}`} className="text-[12px] text-accent-text hover:underline">
          Open full workspace
        </Link>
      </div>
    </div>
  );
}

export function JudgesClient() {
  const replays = useQuery({ queryKey: ["replays"], queryFn: api.replays });
  const status = useQuery({ queryKey: ["status"], queryFn: api.status });
  const [picked, setPicked] = React.useState<string | null>(null);
  const active = picked ?? replays.data?.[0]?.id ?? null;

  const steps = [
    { n: "1", title: "Watch a stored run", body: "Below: photo → mm → CAD → verify, played back from its run log.", href: "#replay", icon: History },
    { n: "2", title: "Check the numbers", body: "Bench tables with N, CI and ground-truth source.", href: "/bench", icon: Gauge },
    { n: "3", title: "See which model ran where", body: "Live vs mock per stage, open-weights paths, cost.", href: "/status", icon: Server },
    { n: "4", title: "Use it from an agent", body: "REST, MCP and llms.txt in one page.", href: "/agents", icon: Terminal },
  ];

  return (
    <>
      <PageHeader
        eyebrow="For judges"
        title="The 30-second path"
        description="No login. Every number on these pages is computed by code and comes from the API; replays, mocks and synthetic inputs are labelled wherever they appear."
        actions={
          REPO_URL ? (
            <Button asChild variant="outline">
              <a href={REPO_URL} target="_blank" rel="noreferrer">
                Source code <ArrowRight aria-hidden />
              </a>
            </Button>
          ) : null
        }
      />
      <Container className="space-y-14 py-10">
        <ol className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {steps.map((s) => (
            <li key={s.n}>
              <Link href={s.href} className="group flex h-full flex-col gap-2 rounded-lg border border-border bg-surface p-4 hover:border-border-strong">
                <div className="flex items-center justify-between">
                  <span className="font-mono text-[12px] text-accent-text">0{s.n}</span>
                  <s.icon className="size-4 text-subtle group-hover:text-fg" aria-hidden />
                </div>
                <div className="text-[14px] font-semibold">{s.title}</div>
                <p className="text-[13px] leading-5 text-muted">{s.body}</p>
              </Link>
            </li>
          ))}
        </ol>

        <Section id="replay" title="Replay a run">
          {replays.isPending ? (
            <Skeleton className="h-80" />
          ) : replays.isError ? (
            <ErrorState error={replays.error} what="stored runs" onRetry={() => void replays.refetch()} />
          ) : !active ? (
            <EmptyState icon={History} title="No stored runs yet">
              The first finished job becomes replayable here.
            </EmptyState>
          ) : (
            <div className="space-y-3">
              {replays.data.length > 1 ? (
                <div className="flex flex-wrap gap-1.5" role="radiogroup" aria-label="Stored runs">
                  {replays.data.map((r) => (
                    <button
                      key={r.id}
                      type="button"
                      role="radio"
                      aria-checked={active === r.id}
                      onClick={() => setPicked(r.id)}
                      className={cn(
                        "h-8 rounded-full border px-3 text-[12.5px]",
                        active === r.id ? "border-fg bg-fg text-bg" : "border-border bg-surface text-muted hover:text-fg",
                      )}
                    >
                      {r.title}
                    </button>
                  ))}
                </div>
              ) : null}
              <ReplayPlayer id={active} />
            </div>
          )}
        </Section>

        <Section title="Meta models in this build" description="Live from /status: what each stage runs and whether it is live or a labelled fallback.">
          {status.isError ? (
            <ErrorState error={status.error} compact what="provider status" />
          ) : !status.data ? (
            <Skeleton className="h-40" />
          ) : (
            <div tabIndex={0} role="region" aria-label="Models by stage" className="scrollbar-thin overflow-x-auto rounded-lg border border-border bg-surface">
              <table className="w-full min-w-[560px] text-[13px]">
                <thead className="bg-surface-2 text-left text-[11px] text-subtle">
                  <tr>
                    <th scope="col" className="px-3 py-2 font-medium">Stage</th>
                    <th scope="col" className="px-3 py-2 font-medium">Model</th>
                    <th scope="col" className="px-3 py-2 font-medium">Where</th>
                    <th scope="col" className="px-3 py-2 font-medium">Mode</th>
                  </tr>
                </thead>
                <tbody>
                  {status.data.providers.map((p) => (
                    <tr key={`${p.stage}-${p.role}`} className="border-t border-border">
                      <th scope="row" className="px-3 py-2 text-left font-normal">
                        {p.role} <span className="text-subtle">· {p.stage}</span>
                      </th>
                      <td className="px-3 py-2 font-mono text-[12px]">{p.model}</td>
                      <td className="px-3 py-2 text-muted">
                        {p.where}
                        {p.open_weights ? <Badge tone="accent" className="ml-1.5">open weights</Badge> : null}
                      </td>
                      <td className="px-3 py-2">
                        <ModeBadge mode={p.mode} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Section>
      </Container>
    </>
  );
}
