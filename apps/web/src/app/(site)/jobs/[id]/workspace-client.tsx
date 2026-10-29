"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, Ban, Boxes, CircleStop, ExternalLink, FileJson, Info, ScanLine, Upload } from "lucide-react";
import dynamic from "next/dynamic";
import Link from "next/link";
import * as React from "react";
import { CodeDiff } from "@/components/jobs/code-diff";
import { CouponFit } from "@/components/jobs/coupon-fit";
import { EditPanel } from "@/components/jobs/edit-panel";
import { BoundNote, NarratedBadge, NarrationPanel, UncheckedList } from "@/components/jobs/evidence-notes";
import { ExportMenu, PreviewDialog } from "@/components/jobs/export-menu";
import { FixHistoryStrip } from "@/components/jobs/fix-history-strip";
import { SourceSwatch, sourceColor } from "@/components/jobs/source-key";
import { ValueSourcesPanel } from "@/components/jobs/value-sources-panel";
import { JobStatusBadge } from "@/components/jobs/job-badges";
import { FitPresets } from "@/components/jobs/fit-presets";
import { ImpactPanel } from "@/components/jobs/impact-panel";
import { ProgressLines } from "@/components/jobs/progress-lines";
import { JobExtras } from "@/components/jobs/job-extras";
import { MateFitCard } from "@/components/jobs/mate-fit-card";
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
import { ApiError, api, artifactUrl } from "@/lib/api";
import { couponFeatures } from "@/lib/coupon-fit";
import type { ArtifactEvent, BakeResult, JobDetail, JobEvent, Measured, Measurements, PartTest } from "@/lib/api-types";
import { isNarrated } from "@/lib/evidence-notes";
import { fmtNum, fmtUsd, paramLabel, splitTitle } from "@/lib/format";
import { useBake, useCountTo, useJobBake } from "@/lib/hooks";
import { STAGE_LABELS, summarizeEvents, useJobEvents, type EventSummary, type StreamState } from "@/lib/job-events";
import { VOTE_ENABLED, VoteBanner } from "@/components/vote-banner";
import { I18nRegion, LangToggle, useT } from "@/lib/i18n";
import { cn } from "@/lib/utils";
import { valueItems, valueText, type ValueItem } from "@/lib/value-sources";
import type { SceneSourceMark } from "@/components/viewer/cad-scene";

// Code-split out of the workspace's first load: the 3D viewer (its three.js scene is split again inside), the error
// chart (recharts) and the Agent tab. The page body is client-rendered after the job detail loads, so `ssr: false`
// changes no server HTML; each placeholder keeps the final size so nothing shifts, and announces itself.
const AgentLog = dynamic(() => import("@/components/jobs/agent-log").then((m) => m.AgentLog), {
  ssr: false,
  loading: () => (
    <p className="flex items-center justify-center gap-2 py-6 text-[13px] text-muted">
      <Spinner label="Loading the agent log" /> Loading the agent log…
    </p>
  ),
});
const CadViewer = dynamic(() => import("@/components/viewer/cad-viewer").then((m) => m.CadViewer), {
  ssr: false,
  loading: () => (
    <div role="status" aria-label="Loading the 3D viewer" className="relative h-[360px] sm:h-[460px] xl:h-[520px]">
      <Skeleton className="absolute inset-0 rounded-none" />
    </div>
  ),
});
const ConvergenceChart = dynamic(() => import("@/components/jobs/convergence-chart").then((m) => m.ConvergenceChart), {
  ssr: false,
  loading: () => (
    <div role="status" aria-label="Loading the error chart" className="h-[160px]">
      <Skeleton className="h-full" />
    </div>
  ),
});

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

/** One measured value: the number with its provenance, the range the photo allows (if any) and the narration badge. */
function MeasuredValue({ m }: { m: Measured }) {
  return (
    <span className="flex flex-col items-end gap-0.5">
      <Mm value={m.value} sigma={m.sigma_mm} source={m.source} citation={m.evidence?.citation} />
      {isNarrated(m.evidence?.note) ? <NarratedBadge /> : null}
      <BoundNote bound={m.bound_mm} />
    </span>
  );
}

/** "Where from" control on a measurement row: selects the value in the panel under the model. */
function WhereFrom({ item, label, tinted, onSelect }: { item: ValueItem | undefined; label: string; tinted: boolean; onSelect: (id: string) => void }) {
  if (!item) return null;
  const c = sourceColor(item.kind);
  return (
    <button
      type="button"
      onClick={() => onSelect(item.id)}
      aria-label={`Where ${label} came from`}
      className={cn("inline-flex size-6 shrink-0 items-center justify-center rounded-md text-subtle hover:bg-surface-2 hover:text-fg", tinted && c.className)}
      style={tinted ? c.style : undefined}
    >
      {tinted ? <SourceSwatch kind={item.kind} /> : <Info className="size-3.5" aria-hidden />}
    </button>
  );
}

function MeasurementsCard({
  m,
  items,
  tinted,
  onSelect,
}: {
  m: Measurements;
  items: Map<string, ValueItem>;
  tinted: boolean;
  onSelect: (id: string) => void;
}) {
  const where = (id: string, label: string) => <WhereFrom item={items.get(id)} label={label} tinted={tinted} onSelect={onSelect} />;
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
        <Row label="Length" extra={where("dim.length", "length")}>
          <MeasuredValue m={m.length} />
        </Row>
        <Row label="Width" extra={where("dim.width", "width")}>
          <MeasuredValue m={m.width} />
        </Row>
        {m.thickness ? (
          <Row label="Thickness" extra={where("dim.thickness", "thickness")}>
            <MeasuredValue m={m.thickness} />
          </Row>
        ) : null}
        {m.holes.map((h) => (
          <Row key={h.id} label={`${h.id.replace("_", " ")} Ø`} extra={where(`feature.${h.id}.diameter`, `${h.id.replace("_", " ")} diameter`)}>
            <MeasuredValue m={h.diameter} />
          </Row>
        ))}
      </dl>
    </div>
  );
}

const BROKEN_STRATEGY: Record<string, string> = {
  mirror: "mirroring the intact side",
  mating_part: "fitting the mating part",
  template: "the part template",
  user: "your description",
};

function PartTests({ tests }: { tests: PartTest[] }) {
  const p0 = tests.filter((t) => t.priority === "P0");
  const p1 = tests.filter((t) => t.priority === "P1");
  const row = (t: PartTest) => (
    <li key={t.id} className="flex items-start gap-2">
      <Badge tone={t.passed ? "ok" : t.priority === "P0" ? "bad" : "warn"} className="shrink-0">
        {t.passed ? "pass" : "fail"}
      </Badge>
      <span className="text-muted">
        {t.description}
        {t.value != null && t.expected != null ? (
          <span className="ml-1 font-mono tnum">
            ({fmtNum(t.value)} vs {fmtNum(t.expected)}
            {t.tol != null ? ` ± ${fmtNum(t.tol)}` : ""})
          </span>
        ) : null}
      </span>
    </li>
  );
  return (
    <div className="space-y-3">
      {p0.length ? (
        <div className="space-y-1.5">
          <Eyebrow>Part tests (must pass)</Eyebrow>
          <ul className="space-y-1 text-[12px]">{p0.map(row)}</ul>
        </div>
      ) : null}
      {p1.length ? (
        <div className="space-y-1.5">
          <Eyebrow>Functional probes (advisory)</Eyebrow>
          <ul className="space-y-1 text-[12px]">{p1.map(row)}</ul>
        </div>
      ) : null}
    </div>
  );
}

function Row({ label, children, extra }: { label: string; children: React.ReactNode; extra?: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-3 border-b border-border pb-2 last:border-0">
      <dt className="shrink-0 text-muted">{label}</dt>
      <dd className="flex items-center justify-end gap-1 text-right">
        {children}
        {extra}
      </dd>
    </div>
  );
}

/** Viewer marks from the value list: one per dimension/region, one per feature (its values joined on one callout). */
function sceneMarks(items: ValueItem[], selectedId: string | null): SceneSourceMark[] {
  const out: SceneSourceMark[] = [];
  const byFeature = new Map<string, ValueItem[]>();
  for (const i of items) {
    if (!i.anchor) continue;
    if (i.featureId) {
      const list = byFeature.get(i.featureId);
      if (list) {
        list.push(i);
        continue;
      }
      byFeature.set(i.featureId, [i]);
    }
    out.push({ id: i.id, kind: i.kind, anchor: i.anchor, text: "", selected: false, unchecked: i.unchecked });
  }
  return out.map((m) => {
    const it = items.find((i) => i.id === m.id)!;
    const group = it.featureId ? byFeature.get(it.featureId)! : [it];
    const sel = group.find((g) => g.id === selectedId);
    const text = group.map((g) => (g.value == null ? g.label : `${g.label} ${valueText(g)}`)).join(" · ");
    return { ...m, id: sel?.id ?? m.id, text, selected: !!sel, unchecked: group.some((g) => g.unchecked) };
  });
}

function JobActions({ id, summary }: { id: string; summary: JobDetail["summary"] }) {
  const qc = useQueryClient();
  const publish = useMutation({
    mutationFn: (ack: boolean) => api.publish(id, undefined, ack),
    onSuccess: (part) => {
      toast("Published to the registry", { description: part.title, tone: "ok" });
      void qc.invalidateQueries({ queryKey: ["job", id] });
    },
    onError: (e) => {
      if (e instanceof ApiError && e.code === "needs_ack") return; // shown inline: the plain-words reason + "publish anyway"
      toast("Could not publish", { description: e instanceof Error ? e.message : String(e), tone: "bad" });
    },
  });
  const needsAck = publish.error instanceof ApiError && publish.error.code === "needs_ack" ? publish.error.message : null;
  const cancel = useMutation({
    mutationFn: () => api.cancel(id),
    onSuccess: (r) => {
      toast(r.status === "cancelling" ? "Stopping the job…" : "Job cancelled", {
        description: r.status === "cancelling" ? "It stops at its next check." : undefined,
      });
      void qc.invalidateQueries({ queryKey: ["job", id] });
    },
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
  if (summary.status === "done" && needsAck)
    return (
      <div role="alert" className="flex max-w-md flex-col gap-2 rounded-md border border-warn-border bg-warn-soft p-2.5 text-[12.5px]">
        <p>
          <span className="font-medium">Best effort, not verified.</span> {needsAck}
        </p>
        <div className="flex gap-2">
          <Button variant="outline" size="sm" onClick={() => publish.mutate(true)} disabled={publish.isPending}>
            I understand, publish as best effort
          </Button>
          <Button variant="ghost" size="sm" onClick={() => publish.reset()}>
            Not now
          </Button>
        </div>
      </div>
    );
  if (summary.status === "done")
    return (
      <Button variant="primary" size="sm" onClick={() => publish.mutate(false)} disabled={publish.isPending}>
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
  const [manualFocus, setManualFocus] = React.useState<{ at: [number, number, number]; key: string; label?: string } | null>(null);
  const [tintBySource, setTintBySource] = React.useState(false);
  const [selectedValue, setSelectedValue] = React.useState<string | null>(null);
  const { t } = useT();
  const artifactEvents = React.useMemo(() => events.filter((e): e is ArtifactEvent => e.t === "artifact"), [events]);
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

  const items = React.useMemo(
    () => (d ? valueItems({ partspec: d.partspec, measurements: d.measurements, verification: d.verification, artifacts: artifactEvents }) : []),
    [d, artifactEvents],
  );
  const itemsById = React.useMemo(() => new Map(items.map((i) => [i.id, i])), [items]);
  const marks = React.useMemo(() => sceneMarks(items, selectedValue), [items, selectedValue]);
  const selectFromCard = React.useCallback((id: string) => {
    setSelectedValue(id);
    const el = document.getElementById("value-sources");
    if (el) el.scrollIntoView({ behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth", block: "nearest" });
  }, []);

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
  const heading = splitTitle(sum.title || d.partspec?.title || "Fix job");
  const autoFocus = s.focus?.at_mm ? { at: s.focus.at_mm, key: `a${s.focus.seq}`, label: s.focus.feature || s.focus.label } : null;
  const focusPoint = manualFocus ?? autoFocus;

  return (
    <I18nRegion className="pb-10">
      <div aria-live="polite" role="status" className="sr-only">
        {liveMsg}
      </div>

      {/* header */}
      <div className="border-b border-border bg-surface/50">
        <div className="flex flex-col gap-3 px-4 py-4 sm:px-6 lg:flex-row lg:items-center lg:justify-between">
          <div className="min-w-0 space-y-1.5">
            <div className="flex flex-wrap items-center gap-2">
              <h1 className="line-clamp-2 text-[18px] leading-tight font-semibold tracking-tight sm:text-[20px]">{heading.title}</h1>
              {heading.presets.map((p) => (
                <Badge key={p} tone="outline">
                  {p}
                </Badge>
              ))}
              {sum.status !== "done" ? <JobStatusBadge job={sum} /> : null}
              {replay ? <OriginBadge origin="replay" /> : null}
              <OriginBadge origin={sum.origin} hideReal />
              <ModeBadge mode={sum.provider_mode} />
            </div>
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[12px] text-subtle">
              <span className="font-mono">{sum.id}</span>
              <span className="font-mono tnum">{s.modelCalls.length} model calls · {fmtUsd(usd)}</span>
              {lastIterErr != null && !verification ? (
                <span className="font-mono tnum">
                  silhouette error <span className="text-fg">{fmtNum(counting ?? lastIterErr)} mm</span>
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
                <ScanLine aria-hidden /> {t("ws.fitCheck")}
              </Link>
            </Button>
            <ExportMenu artifacts={artifacts} verification={verification} passport={done ? d?.passport : undefined} />
            <LangToggle />
            <JobActions id={id} summary={sum} />
          </div>
        </div>
      </div>

      {verification?.verified && VOTE_ENABLED ? (
        <div className="px-4 pt-4 sm:px-6">
          <VoteBanner />
        </div>
      ) : null}

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
                  ? t("ws.refused")
                  : doneStatus === "failed"
                    ? t("ws.failed")
                    : doneStatus === "cancelled"
                      ? "The job was cancelled"
                      : t("ws.bestEffort")}
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

      {verification?.unchecked.length ? (
        <div className="px-4 pt-4 sm:px-6">
          <UncheckedList items={verification.unchecked} />
        </div>
      ) : null}

      <div className="min-w-0 px-4 pt-4 empty:hidden sm:px-6">
        <FixHistoryStrip events={events} />
      </div>

      <div className="grid grid-cols-1 gap-4 px-4 pt-4 sm:px-6 xl:grid-cols-[minmax(0,1fr)_minmax(0,1.3fr)_380px]">
        {/* centre: viewer (first on small screens) */}
        <div className="overflow-hidden rounded-lg border border-border bg-surface xl:order-2">
          <CadViewer
            viewUrl={viewUrl}
            busy={knobBake.pending && changed}
            className="h-[360px] sm:h-[460px] xl:h-[520px]"
            label="Model"
            emptyText={done ? "No model was produced." : "The model appears after the first build."}
            focus={focusPoint}
            sources={items.length ? { marks, on: tintBySource, onToggle: setTintBySource, onSelect: setSelectedValue } : null}
          />
          {items.length ? (
            <div id="value-sources" className="border-t border-border p-4">
              <ValueSourcesPanel
                items={items}
                tinted={tintBySource}
                onTint={setTintBySource}
                selectedId={selectedValue}
                onSelect={setSelectedValue}
                inViewer={!!viewUrl}
              />
            </div>
          ) : null}
        </div>

        {/* left: photo + measurements */}
        <div className="flex flex-col gap-4 xl:order-1">
          <div className="overflow-hidden rounded-lg border border-border bg-surface">
            <PhotoPanel views={views} focusLabel={focusPoint?.label} className="h-[360px] sm:h-[420px] xl:h-[520px]" />
          </div>
        </div>

        {/* right: convergence + trace */}
        <aside className="flex min-w-0 flex-col gap-4 xl:order-3 xl:row-span-2">
          <div className="rounded-lg border border-border bg-surface p-4">
            <div className="mb-2 flex items-center justify-between">
              <Eyebrow>{t("ws.errorChart")}</Eyebrow>
              {lastIterErr != null ? <Mm value={counting ?? lastIterErr} size="sm" /> : null}
            </div>
            <ConvergenceChart data={s.convergence} threshold={threshold} />
            <ProgressLines lines={s.progress} className="mt-3 border-t border-border pt-3" />
          </div>
          <ImpactPanel jobId={id} finished={!!done} />
          <div className="rounded-lg border border-border bg-surface">
            <Tabs defaultValue={s.agent.length ? "agent" : "trace"}>
              <TabsList className="px-3" aria-label="Job details">
                {s.agent.length ? (
                  <TabsTrigger value="agent">
                    {t("ws.agent")} <span className="font-mono text-[11px] text-subtle tnum">{s.agent.length}</span>
                  </TabsTrigger>
                ) : null}
                <TabsTrigger value="trace">{t("ws.trace")}</TabsTrigger>
                <TabsTrigger value="iterations">
                  {t("ws.iterations")} <span className="font-mono text-[11px] text-subtle tnum">{s.iterations.length}</span>
                </TabsTrigger>
                <TabsTrigger value="residuals">{t("ws.residuals")}</TabsTrigger>
                <TabsTrigger value="code">{t("ws.code")}</TabsTrigger>
              </TabsList>
              <div className="scrollbar-thin max-h-[640px] overflow-y-auto px-4 pb-4" tabIndex={0} role="region" aria-label="Job details">
                <TabsContent value="agent">
                  <AgentLog
                    events={s.agent}
                    modelCalls={s.modelCalls}
                    onFocus={(e) => e.at_mm && setManualFocus({ at: e.at_mm, key: `m${e.seq}-${Date.now()}`, label: e.feature || e.label })}
                  />
                </TabsContent>
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
                  {verification?.tests.length ? <PartTests tests={verification.tests} /> : null}
                  {d?.partspec?.broken_region ? (
                    <div className="space-y-1 rounded-md border border-border bg-surface-2 p-2.5 text-[12px] leading-5">
                      <Eyebrow>Broken region</Eyebrow>
                      <p className="text-muted">
                        Rebuilt by <span className="font-medium text-fg">{BROKEN_STRATEGY[d.partspec.broken_region.strategy] ?? d.partspec.broken_region.strategy}</span>
                        {d.partspec.broken_region.note ? ` · ${d.partspec.broken_region.note}` : ""}.{verification?.reasons.length ? " The verifier's notes below say how it was checked." : ""}
                      </p>
                    </div>
                  ) : null}
                  {verification?.reasons.length ? (
                    <ul className="list-disc space-y-0.5 pl-4 text-[12px] text-muted" aria-label="Verifier notes">
                      {verification.reasons.map((r) => (
                        <li key={r}>{r}</li>
                      ))}
                    </ul>
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
                  title={t("ws.knobs")}
                  columns={2}
                />
                <FitPresets values={values ?? d.values} onApply={(p) => setValues((cur) => ({ ...(cur ?? d.values), ...p }))} params={d.params} />
                {artifacts.coupon ? (
                  <CouponFit features={couponFeatures(d.partspec?.features, d.params)} jobId={replay ? undefined : id} className="mt-4 border-t border-border pt-4" />
                ) : null}
                <p className="mt-3 text-[12px] text-subtle">{slug ? t("ws.knobNotePart") : t("ws.knobNoteJob")}</p>
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
            {measurements ? <MeasurementsCard m={measurements} items={itemsById} tinted={tintBySource} onSelect={selectFromCard} /> : null}
            <MateFitCard jobId={id} finished={!!done} hasMate={!!(artifacts.mate_fit || artifacts.mate_overlay)} overlay={artifacts.mate_overlay} className="border-t border-border pt-4" />
            {artifacts.narration ? <NarrationPanel url={artifacts.narration} /> : null}
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
        <JobExtras artifactEvents={artifactEvents} rectified={views.top?.rectified ?? views.top?.photo} />
      </div>
    </I18nRegion>
  );
}
