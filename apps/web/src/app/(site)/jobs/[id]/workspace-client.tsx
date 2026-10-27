"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, Ban, Boxes, CircleStop, ExternalLink, FileJson, ScanLine, Upload } from "lucide-react";
import Link from "next/link";
import * as React from "react";
import { CodeDiff } from "@/components/jobs/code-diff";
import { ConvergenceChart } from "@/components/jobs/convergence-chart";
import { EditPanel } from "@/components/jobs/edit-panel";
import { ExportMenu, PreviewDialog } from "@/components/jobs/export-menu";
import { JobStatusBadge } from "@/components/jobs/job-badges";
import { PhotoPanel, imagesByView } from "@/components/jobs/photo-panel";
import { QuestionPanel } from "@/components/jobs/question-panel";
import { ResidualTable } from "@/components/jobs/residual-table";
import { IterationList, TraceTimeline } from "@/components/jobs/trace-timeline";
import { KnobPanel } from "@/components/registry/knob-panel";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Eyebrow } from "@/components/ui/card";
import { CodeBlock } from "@/components/ui/code-block";
import { ErrorState } from "@/components/ui/error-state";
import { Mm } from "@/components/ui/mm";
import { ModeBadge, OriginBadge } from "@/components/ui/provenance";
import { Skeleton } from "@/components/ui/skeleton";
import { Spinner } from "@/components/ui/spinner";
import { StatusDot } from "@/components/ui/status-dot";
import { toast } from "@/components/ui/toast";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { VerifiedBadge } from "@/components/ui/verified-badge";
import { CadViewer } from "@/components/viewer/cad-viewer";
import { api, artifactUrl } from "@/lib/api";
import type { ArtifactEvent, BakeResult, JobDetail, JobEvent, Measurements } from "@/lib/api-types";
import { fmtNum, fmtUsd, paramLabel } from "@/lib/format";
import { useBake, useCountTo, useJobBake } from "@/lib/hooks";
import { STAGE_LABELS, summarizeEvents, useJobEvents, type EventSummary, type StreamState } from "@/lib/job-events";
import { cn } from "@/lib/utils";

function mergeEvents(a: JobEvent[], b: JobEvent[]): JobEvent[] {
  const m = new Map<number, JobEvent>();
  for (const e of a) m.set(e.seq, e);
  for (const e of b) m.set(e.seq, e);
  return [...m.values()].sort((x, y) => x.seq - y.seq);
}

function announce(s: EventSummary): string {
  if (s.done) {
    const err = s.convergence.at(-1)?.hausdorff_mm;
    return `Job finished: ${s.done.status.replace("_", " ")}${err != null ? `, max error ${fmtNum(err)} millimetres` : ""}.`;
  }
  if (s.question) return `Paused with a question: ${s.question.text}`;
  const it = s.iterations.at(-1);
  if (it && s.current?.stage === "verify" && s.current.status === "ok" && it.hausdorff_mm != null) {
    return `Iteration ${it.iter}: max error ${fmtNum(it.hausdorff_mm)} millimetres.`;
  }
  if (s.current) return `${STAGE_LABELS[s.current.stage]}: ${s.current.status === "start" ? "running" : s.current.status}.`;
  return "";
}

function StreamIndicator({ state, done }: { state: StreamState; done: boolean }) {
  if (done) return null;
  const map = {
    connecting: { tone: "idle", text: "connecting" },
    live: { tone: "live", text: "live" },
    reconnecting: { tone: "warn", text: "reconnecting" },
    closed: { tone: "idle", text: "stream closed" },
    error: { tone: "bad", text: "stream lost" },
  } as const;
  const v = map[state];
  return (
    <span className="inline-flex items-center gap-1.5 text-[12px] text-muted">
      <StatusDot tone={v.tone} pulse={state === "live" || state === "connecting"} /> {v.text}
    </span>
  );
}

function MeasurementsCard({ m }: { m: Measurements }) {
  return (
    <div className="space-y-2.5">
      <div className="flex items-center justify-between">
        <Eyebrow>Measured · {m.view} view</Eyebrow>
        <span className="flex items-center gap-1.5">
          <OriginBadge origin={m.origin} hideReal />
          <span className="font-mono text-[11px] text-subtle">mask: {m.mask_source}</span>
        </span>
      </div>
      <dl className="space-y-2 text-[13px]">
        <Row label="Length">
          <Mm value={m.length.value} sigma={m.length.sigma_mm} source={m.length.source} />
        </Row>
        <Row label="Width">
          <Mm value={m.width.value} sigma={m.width.sigma_mm} source={m.width.source} />
        </Row>
        {m.thickness ? (
          <Row label="Thickness">
            <Mm value={m.thickness.value} sigma={m.thickness.sigma_mm} source={m.thickness.source} />
          </Row>
        ) : null}
        {m.holes.map((h) => (
          <Row key={h.id} label={`${h.id.replace("_", " ")} Ø`}>
            <Mm value={h.diameter.value} sigma={h.diameter.sigma_mm} source={h.diameter.source} />
          </Row>
        ))}
      </dl>
    </div>
  );
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-3 border-b border-border pb-2 last:border-0">
      <dt className="shrink-0 text-muted">{label}</dt>
      <dd className="flex justify-end text-right">{children}</dd>
    </div>
  );
}

function JobActions({ id, summary }: { id: string; summary: JobDetail["summary"] }) {
  const qc = useQueryClient();
  const publish = useMutation({
    mutationFn: () => api.publish(id),
    onSuccess: (part) => {
      toast("Published to the registry", { description: part.title, tone: "ok" });
      void qc.invalidateQueries({ queryKey: ["job", id] });
    },
    onError: (e) => toast("Could not publish", { description: e instanceof Error ? e.message : String(e), tone: "bad" }),
  });
  const cancel = useMutation({
    mutationFn: () => api.cancel(id),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["job", id] }),
    onError: (e) => toast("Could not cancel", { description: e instanceof Error ? e.message : String(e), tone: "bad" }),
  });
  if (summary.is_replay) return null;
  if (summary.part_slug)
    return (
      <Button asChild variant="outline" size="sm">
        <Link href={`/parts/${encodeURIComponent(summary.part_slug)}`}>
          <Boxes aria-hidden /> Registry page
        </Link>
      </Button>
    );
  if (summary.status === "done")
    return (
      <Button variant="primary" size="sm" onClick={() => publish.mutate()} disabled={publish.isPending}>
        {publish.isPending ? <Spinner className="text-accent-fg" label="Publishing" /> : <Upload aria-hidden />} Publish
      </Button>
    );
  if (["queued", "running", "waiting_for_answer"].includes(summary.status))
    return (
      <Button variant="ghost" size="sm" onClick={() => cancel.mutate()} disabled={cancel.isPending}>
        <CircleStop aria-hidden /> Cancel
      </Button>
    );
  return null;
}

export function WorkspaceClient({ id }: { id: string }) {
  const qc = useQueryClient();
  const detail = useQuery({ queryKey: ["job", id], queryFn: () => api.job(id) });
  const { events: streamed, stream, contractErrors } = useJobEvents(id);
  const events = React.useMemo(() => mergeEvents(detail.data?.events ?? [], streamed), [detail.data?.events, streamed]);
  const s = React.useMemo(() => summarizeEvents(events), [events]);
  const d: JobDetail | undefined = detail.data;

  // Pull the authoritative detail (verification, params, artifacts) whenever the stream reaches a milestone.
  const verifyCount = events.filter((e) => e.t === "stage" && e.stage === "verify" && e.status !== "start").length;
  const milestone = `${verifyCount}|${s.done?.seq ?? ""}|${s.question?.id ?? ""}|${events.some((e) => e.t === "answer") ? "a" : ""}`;
  React.useEffect(() => {
    if (milestone !== "0|||") void qc.invalidateQueries({ queryKey: ["job", id] });
  }, [milestone, id, qc]);

  const [values, setValues] = React.useState<Record<string, number> | null>(null);
  const [editBake, setEditBake] = React.useState<BakeResult | null>(null);
  React.useEffect(() => {
    if (d && values === null && Object.keys(d.values).length) setValues(d.values);
  }, [d, values]);

  const slug = d?.summary.part_slug ?? null;
  const changed = !!d && !!values && Object.entries(values).some(([k, v]) => d.values[k] !== v);
  // Published parts re-bake through the registry; unpublished jobs re-bake their own program.
  const partBake = useBake(slug, changed && slug ? values : null);
  const jobBake = useJobBake(id, changed && !slug ? values : null);
  const knobBake = slug ? partBake : jobBake;

  const views = React.useMemo(
    () => imagesByView(events.filter((e): e is ArtifactEvent => e.t === "artifact"), d?.artifacts ?? {}),
    [events, d?.artifacts],
  );
  const artifacts = React.useMemo(() => {
    const out: Record<string, string> = { ...(d?.artifacts ?? {}) };
    for (const [k, a] of Object.entries(s.artifacts)) out[k] = a.url;
    return out;
  }, [d?.artifacts, s.artifacts]);

  const viewUrl = (changed ? knobBake.data?.artifacts.view : undefined) ?? editBake?.artifacts.view ?? artifacts.view;
  const verification = d?.verification ?? null;
  const done = s.done ?? (d && ["done", "failed", "cancelled"].includes(d.summary.status) ? d.summary : null);
  const live = !done && stream === "live";
  const lastIterErr = s.convergence.filter((c) => c.hausdorff_mm != null).at(-1)?.hausdorff_mm ?? null;
  const threshold = verification?.thresholds.hausdorff_mm ?? s.metrics.findLast((m) => m.threshold != null)?.threshold ?? null;
  const counting = useCountTo(lastIterErr);
  const [liveMsg, setLiveMsg] = React.useState("");
  React.useEffect(() => {
    const t = window.setTimeout(() => setLiveMsg(announce(s)), 400);
    return () => window.clearTimeout(t);
  }, [s]);

  if (detail.isError) {
    return (
      <div className="mx-auto max-w-3xl px-4 py-16">
        <ErrorState error={detail.error} what="this job" onRetry={() => void detail.refetch()} />
      </div>
    );
  }
  if (!d) {
    return (
      <div className="space-y-4 px-4 py-6 sm:px-6">
        <Skeleton className="h-10 w-80" />
        <div className="grid grid-cols-1 gap-4 xl:grid-cols-[minmax(0,1fr)_minmax(0,1.3fr)_380px]">
          <Skeleton className="h-[420px]" />
          <Skeleton className="h-[420px]" />
          <Skeleton className="h-[420px]" />
        </div>
      </div>
    );
  }

  const sum = d.summary;
  const replay = sum.is_replay || sum.origin === "replay";
  const measurements = d.measurements.top ?? Object.values(d.measurements)[0];
  const doneStatus = s.done?.status ?? (sum.status === "done" ? (sum.verified ? "verified" : "best_effort") : sum.status === "failed" ? "failed" : null);
  const usd = s.usd || sum.cost_usd;

  return (
    <div className="pb-10">
      <div aria-live="polite" role="status" className="sr-only">
        {liveMsg}
      </div>

      {/* header */}
      <div className="border-b border-border bg-surface/50">
        <div className="flex flex-col gap-3 px-4 py-4 sm:px-6 lg:flex-row lg:items-center lg:justify-between">
          <div className="min-w-0 space-y-1.5">
            <div className="flex flex-wrap items-center gap-2">
              <h1 className="line-clamp-2 text-[18px] leading-tight font-semibold tracking-tight sm:text-[20px]">{sum.title || d.partspec?.title || "Fix job"}</h1>
              {sum.status !== "done" ? <JobStatusBadge job={sum} /> : null}
              {replay ? <OriginBadge origin="replay" /> : null}
              <OriginBadge origin={sum.origin} hideReal />
              <ModeBadge mode={sum.provider_mode} />
            </div>
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[12px] text-subtle">
              <span className="font-mono">{sum.id}</span>
              <span className="font-mono tnum">{s.modelCalls.length} model calls · {fmtUsd(usd)}</span>
              {lastIterErr != null ? (
                <span className="font-mono tnum">
                  max error <span className="text-fg">{fmtNum(counting ?? lastIterErr)} mm</span>
                  {threshold != null ? <> / limit {fmtNum(threshold)} mm</> : null}
                </span>
              ) : null}
              <StreamIndicator state={stream} done={!!done} />
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <VerifiedBadge verification={verification} pending={!done && !verification} size="lg" />
            <PreviewDialog jobId={id} photoUrl={artifactUrl(artifacts.photo)} disabled={!artifacts.view} />
            <Button asChild variant="outline" size="sm" className={cn(!artifacts.view && "pointer-events-none opacity-50")}>
              <Link href={`/jobs/${encodeURIComponent(id)}/fit`} aria-disabled={!artifacts.view}>
                <ScanLine aria-hidden /> Screen fit check
              </Link>
            </Button>
            <ExportMenu artifacts={artifacts} />
            <JobActions id={id} summary={sum} />
          </div>
        </div>
      </div>

      {contractErrors.length ? (
        <div className="px-4 pt-4 sm:px-6">
          <div role="alert" className="rounded-lg border border-bad-border bg-bad-soft px-4 py-3 text-[13px]">
            <div className="font-medium text-fg">Some live events did not match the API contract and were not shown</div>
            <ul className="mt-1 list-disc pl-5 font-mono text-[12px] text-muted">
              {contractErrors.slice(0, 5).map((e) => (
                <li key={e}>{e}</li>
              ))}
            </ul>
          </div>
        </div>
      ) : null}

      {s.question && !done ? (
        <div className="px-4 pt-4 sm:px-6">
          <QuestionPanel jobId={id} question={s.question} />
        </div>
      ) : null}

      {doneStatus && doneStatus !== "verified" ? (
        <div className="px-4 pt-4 sm:px-6">
          <div role="note" className={cn("flex items-start gap-3 rounded-lg border px-4 py-3 text-[13px]", doneStatus === "refused" ? "border-bad-border bg-bad-soft" : "border-warn-border bg-warn-soft")}>
            {doneStatus === "refused" ? <Ban className="mt-0.5 size-4 shrink-0 text-bad" aria-hidden /> : <AlertTriangle className="mt-0.5 size-4 shrink-0 text-warn" aria-hidden />}
            <div className="space-y-1">
              <div className="font-medium text-fg">
                {doneStatus === "refused"
                  ? "PartSmith won't make this part"
                  : doneStatus === "failed"
                    ? "The job failed"
                    : doneStatus === "cancelled"
                      ? "The job was cancelled"
                      : "Best effort — not verified"}
              </div>
              {d.partspec?.refusal ? <p className="text-muted">{d.partspec.refusal}</p> : null}
              {verification?.reasons.length ? (
                <ul className="list-disc space-y-0.5 pl-4 text-muted">
                  {verification.reasons.map((r) => (
                    <li key={r}>{r}</li>
                  ))}
                </ul>
              ) : null}
            </div>
          </div>
        </div>
      ) : null}

      <div className="grid grid-cols-1 gap-4 px-4 pt-4 sm:px-6 xl:grid-cols-[minmax(0,1fr)_minmax(0,1.3fr)_380px]">
        {/* centre: viewer (first on small screens) */}
        <div className="overflow-hidden rounded-lg border border-border bg-surface xl:order-2">
          <CadViewer
            viewUrl={viewUrl}
            busy={knobBake.pending && changed}
            className="h-[360px] sm:h-[460px] xl:h-[520px]"
            label="Model"
            emptyText={done ? "No model was produced." : "The model appears after the first build."}
          />
        </div>

        {/* left: photo + measurements */}
        <div className="flex flex-col gap-4 xl:order-1">
          <div className="overflow-hidden rounded-lg border border-border bg-surface">
            <PhotoPanel views={views} className="h-[360px] sm:h-[420px] xl:h-[520px]" />
          </div>
        </div>

        {/* right: convergence + trace */}
        <aside className="flex min-w-0 flex-col gap-4 xl:order-3 xl:row-span-2">
          <div className="rounded-lg border border-border bg-surface p-4">
            <div className="mb-2 flex items-center justify-between">
              <Eyebrow>Max error per iteration</Eyebrow>
              {lastIterErr != null ? <Mm value={counting ?? lastIterErr} size="sm" /> : null}
            </div>
            <ConvergenceChart data={s.convergence} threshold={threshold} />
          </div>
          <div className="rounded-lg border border-border bg-surface">
            <Tabs defaultValue="trace">
              <TabsList className="px-3">
                <TabsTrigger value="trace">Trace</TabsTrigger>
                <TabsTrigger value="iterations">
                  Iterations <span className="font-mono text-[11px] text-subtle tnum">{s.iterations.length}</span>
                </TabsTrigger>
                <TabsTrigger value="residuals">Residuals</TabsTrigger>
                <TabsTrigger value="code">Code</TabsTrigger>
              </TabsList>
              <div className="scrollbar-thin max-h-[640px] overflow-y-auto px-4 pb-4" tabIndex={0} role="region" aria-label="Job details">
                <TabsContent value="trace">
                  <TraceTimeline summary={s} live={live} />
                  {s.logs.filter((l) => l.level !== "info").length ? (
                    <div className="mt-2 space-y-1 border-t border-border pt-3">
                      {s.logs
                        .filter((l) => l.level !== "info")
                        .slice(-5)
                        .map((l) => (
                          <p key={l.seq} className={cn("text-[12px]", l.level === "error" ? "text-bad" : "text-warn")}>
                            {l.level}: {l.msg}
                          </p>
                        ))}
                    </div>
                  ) : null}
                </TabsContent>
                <TabsContent value="iterations">
                  <IterationList iterations={s.iterations} threshold={threshold} />
                </TabsContent>
                <TabsContent value="residuals" className="space-y-4">
                  <ResidualTable residuals={verification?.residuals ?? []} />
                  {verification?.tests.length ? (
                    <div className="space-y-1.5">
                      <Eyebrow>Part tests</Eyebrow>
                      <ul className="space-y-1 text-[12px]">
                        {verification.tests.map((t) => (
                          <li key={t.id} className="flex items-start gap-2">
                            <Badge tone={t.passed ? "ok" : "bad"} className="shrink-0">
                              {t.passed ? "pass" : "fail"}
                            </Badge>
                            <span className="text-muted">{t.description}</span>
                          </li>
                        ))}
                      </ul>
                    </div>
                  ) : null}
                  {verification?.views.length ? (
                    <div className="space-y-1.5">
                      <Eyebrow>Silhouette metrics</Eyebrow>
                      <table className="w-full font-mono text-[12px] tnum">
                        <caption className="sr-only">Silhouette comparison per view, millimetres</caption>
                        <thead>
                          <tr className="text-left text-[11px] text-subtle">
                            <th scope="col" className="py-1 font-sans font-medium">View</th>
                            <th scope="col" className="py-1 text-right font-sans font-medium">IoU</th>
                            <th scope="col" className="py-1 text-right font-sans font-medium">Hausdorff</th>
                            <th scope="col" className="py-1 text-right font-sans font-medium">Mean</th>
                          </tr>
                        </thead>
                        <tbody>
                          {verification.views.map((v) => (
                            <tr key={v.view} className="border-t border-border">
                              <th scope="row" className="py-1.5 text-left font-sans font-normal">{v.view}</th>
                              <td className="py-1.5 text-right">{fmtNum(v.iou, 4)}</td>
                              <td className="py-1.5 text-right">{fmtNum(v.hausdorff_mm)} mm</td>
                              <td className="py-1.5 text-right">{fmtNum(v.mean_mm)} mm</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  ) : null}
                  {artifacts.verification ? (
                    <a href={artifactUrl(artifacts.verification)} className="inline-flex items-center gap-1 text-[12px] text-accent-text hover:underline">
                      <FileJson className="size-3.5" aria-hidden /> verification.json
                    </a>
                  ) : null}
                </TabsContent>
                <TabsContent value="code" className="space-y-3">
                  {s.iterations.at(-1)?.diff ? <CodeDiff diff={s.iterations.at(-1)!.diff} maxHeight={220} /> : null}
                  {d.code ? (
                    <CodeBlock code={d.code} title="part.py" maxHeight={420} />
                  ) : (
                    <p className="py-4 text-center text-[13px] text-muted">The CAD program appears after the build stage.</p>
                  )}
                  <a href={api.runLogUrl(id)} className="inline-flex items-center gap-1 text-[12px] text-accent-text hover:underline">
                    <ExternalLink className="size-3.5" aria-hidden /> Raw run log (run.jsonl)
                  </a>
                </TabsContent>
              </div>
            </Tabs>
          </div>
        </aside>

        {/* bottom: knobs + edits */}
        <div className="grid min-w-0 grid-cols-1 gap-4 xl:order-4 xl:col-span-2 lg:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
          <div className="rounded-lg border border-border bg-surface p-4">
            {d.params.length ? (
              <>
                <KnobPanel
                  params={d.params}
                  values={values ?? d.values}
                  onChange={setValues}
                  bake={changed ? knobBake.data : editBake}
                  pending={changed && knobBake.pending}
                  error={knobBake.error}
                  title="Knobs"
                  columns={2}
                />
                <p className="mt-3 text-[12px] text-subtle">
                  {slug ? "Re-bakes the published registry part." : "Re-bakes this job's program; publish to put it in the registry."} Knob changes are not
                  re-verified against the photo.
                </p>
              </>
            ) : (
              <div className="space-y-1">
                <h2 className="text-[13px] font-semibold">Knobs</h2>
                <p className="text-[13px] text-muted">The program&apos;s typed knobs appear after the build stage.</p>
              </div>
            )}
          </div>
          <div className="space-y-5 rounded-lg border border-border bg-surface p-4">
            <EditPanel
              jobId={id}
              disabled={!d.params.length}
              onResult={(r) => {
                if (r.bake) setEditBake(r.bake);
                if (r.edits.length) setValues((cur) => ({ ...(cur ?? d.values), ...Object.fromEntries(r.edits.map((e) => [e.param, e.to])) }));
              }}
            />
            {measurements ? <MeasurementsCard m={measurements} /> : null}
            {d.partspec?.features.length ? (
              <div className="space-y-1.5">
                <Eyebrow>Features found</Eyebrow>
                <div className="flex flex-wrap gap-1.5">
                  {d.partspec.features.map((f) => (
                    <Badge key={f.id} tone="neutral" className="font-mono">
                      {f.id} · {paramLabel(f.kind)}
                    </Badge>
                  ))}
                  {d.partspec.broken_region ? <Badge tone="warn">broken region · {d.partspec.broken_region.strategy}</Badge> : null}
                </div>
              </div>
            ) : null}
          </div>
        </div>
      </div>
    </div>
  );
}
