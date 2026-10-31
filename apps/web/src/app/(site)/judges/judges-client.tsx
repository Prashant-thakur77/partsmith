"use client";

import { useQuery } from "@tanstack/react-query";
import { ArrowRight, FlaskConical, Gauge, History, Pause, Play, RotateCcw, Server, Terminal } from "lucide-react";
import Link from "next/link";
import dynamic from "next/dynamic";
import * as React from "react";
import { TraceTimeline } from "@/components/jobs/trace-timeline";
import { ReplayCard } from "@/components/jobs/replay-card";
import { LieCaught, reportFileUrl } from "@/components/judges/lie-caught";
import { Container, PageHeader, Section } from "@/components/layout/page";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Eyebrow } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorState } from "@/components/ui/error-state";
import { ModeBadge, OriginBadge, RunBadge } from "@/components/ui/provenance";
import { Skeleton } from "@/components/ui/skeleton";
import { Slider } from "@/components/ui/slider";
import { VerifiedBadge } from "@/components/ui/verified-badge";
import { api, artifactUrl } from "@/lib/api";
import { distinctTitles, fmtNum, splitTitle } from "@/lib/format";
import { STAGE_LABELS, summarizeEvents } from "@/lib/job-events";
import type { JobEvent } from "@/lib/api-types";
import { useInView, usePrefersReducedMotion } from "@/lib/motion";
import { curateReplays, replayTitle } from "@/lib/replays";
import { cn } from "@/lib/utils";
import { radioGroupKeys } from "@/lib/a11y";

// recharts loads on demand, behind a placeholder of the chart's own height
const ConvergenceChart = dynamic(() => import("@/components/jobs/convergence-chart").then((m) => m.ConvergenceChart), {
  ssr: false,
  loading: () => (
    <div role="status" aria-label="Loading the error chart" className="h-[170px]">
      <Skeleton className="h-full" />
    </div>
  ),
});

const REPO_URL = process.env.NEXT_PUBLIC_REPO_URL ?? "";
const MODEL_ROWS = 6;

const FRAMES: { kind: string; caption: string }[] = [
  { kind: "render_overlay", caption: "Model drawn over the photo" },
  { kind: "measure_overlay", caption: "Outline and features measured in mm" },
  { kind: "mask_overlay", caption: "Segmentation mask" },
  { kind: "rectified", caption: "Photo rectified to the mat" },
  { kind: "photo", caption: "Phone photo on the screen mat" },
];

/** The latest top-view picture among `events`: the model over the photo, else what was measured, else the photo. */
function latestFrame(events: readonly JobEvent[]): { src: string; caption: string } | null {
  for (const f of FRAMES) {
    for (let i = events.length - 1; i >= 0; i--) {
      const e = events[i]!;
      if (e.t !== "artifact" || e.kind !== f.kind) continue;
      if (f.kind !== "render_overlay" && e.label && !/^top/i.test(e.label)) continue; // the top view reads best
      const src = artifactUrl(e.url);
      if (src) return { src, caption: f.caption };
    }
  }
  return null;
}

/** The picture for where the replay is; before the first picture arrives, the run's input photo. */
function replayFrame(shown: readonly JobEvent[], all: readonly JobEvent[]): { src: string; caption: string } | null {
  const now = latestFrame(shown);
  if (now) return now;
  const first = latestFrame(all.filter((e) => e.t === "artifact" && (e.kind === "photo" || e.kind === "rectified")));
  return first ? { ...first, caption: "The input photo" } : null;
}

/** Plays a stored run back event by event (labelled replay). The Verified badge appears only at the end, from the stored verification. */
function ReplayPlayer({ id }: { id: string }) {
  const job = useQuery({ queryKey: ["job", id], queryFn: () => api.job(id) });
  const events = React.useMemo(() => job.data?.events ?? [], [job.data?.events]);
  const [idx, setIdx] = React.useState(0);
  const [playing, setPlaying] = React.useState(false);
  const [speed, setSpeed] = React.useState(2);
  const traceRef = React.useRef<HTMLDivElement>(null);
  const reduced = usePrefersReducedMotion();
  const { ref: viewRef, seen } = useInView<HTMLDivElement>({ threshold: 0.35 });
  // Autoplay once per run when the player is in view (2×); with reduced motion show the final frame instead. Any touch
  // of the controls hands over to the visitor.
  const auto = React.useRef<string | null>(null);
  const takeOver = () => {
    auto.current = id;
  };

  // while playing, keep the newest stage in view inside the trace box (its own scroll only, never the page's)
  React.useEffect(() => {
    const el = traceRef.current;
    if (playing && el) el.scrollTop = el.scrollHeight;
  }, [playing, idx]);

  React.useEffect(() => {
    setIdx(0);
    setPlaying(false);
  }, [id]);

  React.useEffect(() => {
    if (!events.length || auto.current === id) return;
    if (reduced) {
      setIdx(events.length);
      setPlaying(false);
    } else if (seen) {
      auto.current = id;
      setIdx(0);
      setPlaying(true);
    }
  }, [events.length, reduced, seen, id]);

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

  // the in-view ref sits on a wrapper that exists from the first render (the player itself waits for the run)
  if (job.isError)
    return (
      <div ref={viewRef}>
        <ErrorState error={job.error} compact what="the replay" />
      </div>
    );
  if (!job.data)
    return (
      <div ref={viewRef}>
        <Skeleton className="h-80" />
      </div>
    );

  const s = summarizeEvents(events.slice(0, idx));
  const frame = replayFrame(events.slice(0, idx), events);
  const finished = idx >= events.length && events.length > 0;
  const threshold = job.data.verification?.thresholds.hausdorff_mm ?? null;
  const last = s.convergence.filter((c) => c.hausdorff_mm != null).at(-1)?.hausdorff_mm;

  return (
    <div ref={viewRef}>
    <div className="overflow-hidden rounded-xl border border-border bg-surface">
      <div className="flex flex-wrap items-center gap-2 border-b border-border px-4 py-3">
        <span className="truncate text-[14px] font-medium">{replayTitle(job.data.summary.title || id, splitTitle)}</span>
        <RunBadge mode={job.data.summary.provider_mode} recorded />
        <OriginBadge origin={job.data.summary.origin} hideReal />
        <div className="ml-auto">
          {finished ? (
            <VerifiedBadge verification={job.data.verification} />
          ) : (
            <Badge tone="neutral">{playing ? "verifier result at the end" : idx > 0 ? "paused" : "press play"}</Badge>
          )}
        </div>
      </div>
      <div className="grid grid-cols-1 gap-0 md:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
        <div className="space-y-4 border-b border-border p-4 md:border-r md:border-b-0">
          {frame ? (
            <figure className="space-y-1">
              <div className="relative aspect-[16/9] overflow-hidden rounded-md border border-border bg-surface-2">
                {/* eslint-disable-next-line @next/next/no-img-element -- API blob from the stored run */}
                <img key={frame.src} src={frame.src} alt={frame.caption} className="size-full object-contain motion-safe:animate-fade-up" decoding="async" />
              </div>
              <figcaption className="text-[11.5px] text-muted">{frame.caption}</figcaption>
            </figure>
          ) : null}
          <div aria-live={playing ? "off" : "polite"} className="min-h-10">
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
              <Eyebrow>Silhouette error per iteration</Eyebrow>
              {last != null ? <span className="font-mono text-[13px] tnum">{fmtNum(last)} mm</span> : null}
            </div>
            <ConvergenceChart data={s.convergence} threshold={threshold} height={170} />
          </div>
        </div>
        <div ref={traceRef} className="scrollbar-thin max-h-[300px] overflow-y-auto p-4 md:max-h-[520px]" tabIndex={0} role="region" aria-label="Replay trace">
          <TraceTimeline summary={s} live={playing} />
        </div>
      </div>
      <div className="flex flex-wrap items-center gap-3 border-t border-border px-4 py-3">
        <Button size="sm" variant="primary" onClick={() => (takeOver(), finished ? (setIdx(0), setPlaying(true)) : setPlaying((p) => !p))} disabled={!events.length}>
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
            takeOver();
            setPlaying(false);
            setIdx(v[0] ?? 0);
          }}
        />
        <span className="font-mono text-[12px] text-muted tnum">
          {idx}/{events.length} events
        </span>
        <div className="inline-flex rounded-md border border-border bg-surface-2 p-0.5" role="radiogroup" onKeyDown={radioGroupKeys} aria-label="Speed">
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
    </div>
  );
}

export function JudgesClient() {
  const replays = useQuery({ queryKey: ["replays"], queryFn: api.replays });
  const status = useQuery({ queryKey: ["status"], queryFn: api.status });
  const bench = useQuery({ queryKey: ["bench"], queryFn: api.bench, retry: false });
  const [picked, setPicked] = React.useState<string | null>(null);
  const [more, setMore] = React.useState(false);
  const [allModels, setAllModels] = React.useState(false);
  const playerRef = React.useRef<HTMLDivElement>(null);
  const curated = React.useMemo(() => curateReplays(replays.data ?? []), [replays.data]);
  const active = picked ?? curated.featured[0]?.replay.id ?? replays.data?.[0]?.id ?? null;
  const chipLabels = React.useMemo(() => {
    const all = replays.data ?? [];
    const labels = distinctTitles(all.map((r) => r.title));
    return Object.fromEntries(all.map((r, i) => [r.id, labels[i]!]));
  }, [replays.data]);
  const bypass = bench.data?.evidence?.bypass ?? null;
  const pick = (id: string) => {
    setPicked(id);
    const el = playerRef.current;
    if (el && el.getBoundingClientRect().top > window.innerHeight * 0.6)
      el.scrollIntoView({ behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth", block: "start" });
  };

  const steps = [
    { n: "1", title: "Watch a stored run", body: "Below: photo → mm → CAD → verify, played back from its run log.", href: "#replay", icon: History },
    { n: "2", title: "Check the numbers", body: "Results tables with N, CI and ground-truth source.", href: "/results", icon: Gauge },
    { n: "3", title: "See which model ran where", body: "Live vs mock per stage, open-weights paths, cost.", href: "/models", icon: Server },
    { n: "4", title: "Use it from an agent", body: "REST, MCP and llms.txt in one page.", href: "/agents", icon: Terminal },
  ];

  return (
    <>
      <PageHeader
        eyebrow="For judges"
        title="The 30-second path"
        description="No login. Every number on these pages is computed by code and comes from the API; replays, mocks and synthetic inputs are labelled wherever they appear."
        actions={
          <>
            <Button asChild variant="primary">
              <Link href="/jobs/demo">
                <FlaskConical aria-hidden /> Try a sample
              </Link>
            </Button>
            {REPO_URL ? (
              <Button asChild variant="outline">
                <a href={REPO_URL} target="_blank" rel="noreferrer">
                  Source code <ArrowRight aria-hidden />
                </a>
              </Button>
            ) : null}
          </>
        }
      />
      <Container className="space-y-12 py-8">
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

        <Section id="replay" title="Watch a recorded run" description="Real earlier runs, played back from their logs. Pick one; the player below steps through it.">
          {replays.isPending ? (
            <Skeleton className="h-80" />
          ) : replays.isError ? (
            <ErrorState error={replays.error} what="stored runs" onRetry={() => void replays.refetch()} />
          ) : !active ? (
            <EmptyState icon={History} title="No stored runs yet">
              The first finished job becomes replayable here.
            </EmptyState>
          ) : (
            <div className="space-y-4">
              <ul className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4" aria-label="Runs worth a look">
                {curated.featured.map((f) => (
                  <li key={f.replay.id}>
                    <ReplayCard replay={f.replay} why={f.why} thumb selected={active === f.replay.id} onSelect={() => pick(f.replay.id)} />
                  </li>
                ))}
                {bypass ? (
                  <li>
                    <a href="#lie-caught" className="group flex h-full flex-col overflow-hidden rounded-lg border border-border bg-surface hover:border-border-strong">
                      {bypass.caught[0]?.overlay ? (
                        <div className="aspect-[16/10] overflow-hidden border-b border-border bg-white">
                          {/* eslint-disable-next-line @next/next/no-img-element -- report file served by the API */}
                          <img src={reportFileUrl(bypass.caught[0].overlay)} alt="Verifier overlay from the lying-model test" loading="lazy" decoding="async" className="size-full object-cover" />
                        </div>
                      ) : null}
                      <div className="flex flex-1 flex-col gap-2 p-3.5">
                        <span className="text-[14px] leading-5 font-medium text-fg">A lying model, caught</span>
                        <p className="text-[12.5px] leading-5 text-muted">
                          A scripted model claims “verified”. Code blocked {bypass.blocked} of {bypass.attempts} such claims.
                        </p>
                        <span className="mt-auto flex flex-wrap gap-1.5">
                          <Badge tone="mock">scripted test · no model call</Badge>
                        </span>
                      </div>
                    </a>
                  </li>
                ) : null}
              </ul>
              <div ref={playerRef} className="scroll-mt-28">
                <ReplayPlayer id={active} />
              </div>
              {curated.rest.length ? (
                <div className="space-y-2">
                  <Button variant="ghost" size="sm" onClick={() => setMore((v) => !v)} aria-expanded={more}>
                    {more ? "Fewer runs" : `More runs (${curated.rest.length})`}
                  </Button>
                  {more ? (
                    <div className="flex flex-wrap gap-1.5" role="radiogroup" onKeyDown={radioGroupKeys} aria-label="More stored runs">
                      {curated.rest.map((r) => (
                        <button
                          key={r.id}
                          type="button"
                          role="radio"
                          aria-checked={active === r.id}
                          onClick={() => pick(r.id)}
                          className={cn(
                            "h-8 rounded-full border px-3 text-[12.5px]",
                            active === r.id ? "border-fg bg-fg text-bg" : "border-border bg-surface text-muted hover:text-fg",
                          )}
                        >
                          {chipLabels[r.id]}
                        </button>
                      ))}
                    </div>
                  ) : null}
                </div>
              ) : null}
            </div>
          )}
        </Section>

        <Section
          id="lie-caught"
          title="A lying model, caught"
          description="A scripted brain claims the part is verified. Code ignores the claim: the verifier measures the model against the photo and the export gate decides. Read from eval/reports/latest/bypass.json."
        >
          {bench.isPending ? (
            <Skeleton className="h-96" />
          ) : bench.isError ? (
            <ErrorState error={bench.error} compact what="the lying-model report" onRetry={() => void bench.refetch()} />
          ) : (
            <LieCaught report={bench.data.evidence?.bypass} />
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
                  {(allModels ? status.data.providers : status.data.providers.slice(0, MODEL_ROWS)).map((p) => (
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
              {status.data.providers.length > MODEL_ROWS ? (
                <div className="border-t border-border px-3 py-2">
                  <Button variant="ghost" size="sm" aria-expanded={allModels} onClick={() => setAllModels((v) => !v)}>
                    {allModels ? "Show fewer stages" : `Show all ${status.data.providers.length} stages`}
                  </Button>
                </div>
              ) : null}
            </div>
          )}
        </Section>
      </Container>
    </>
  );
}
