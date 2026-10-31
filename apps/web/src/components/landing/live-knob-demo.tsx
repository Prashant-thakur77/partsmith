"use client";

/**
 * Landing knob demo: turn the knobs of a real program and watch the server re-bake it. The first tab is the recorded run
 * the drawings on this page come from (`/jobs/{id}/bake`, labelled recorded run); the others are registry parts
 * (`/parts/{slug}/bake`). With an empty registry only the recorded run is offered.
 */
import { useQuery } from "@tanstack/react-query";
import { ArrowUpRight } from "lucide-react";
import Link from "next/link";
import * as React from "react";
import { api, artifactUrl } from "@/lib/api";
import type { ParamSpec } from "@/lib/api-types";
import { splitTitle } from "@/lib/format";
import { useJobBake } from "@/lib/hooks";
import { cn } from "@/lib/utils";
import { KnobPanel } from "../registry/knob-panel";
import { PartStatusBadge } from "../registry/part-status";
import { useLivePart } from "../registry/live-part";
import { ErrorState } from "../ui/error-state";
import { Skeleton } from "../ui/skeleton";
import { OriginBadge, RunBadge } from "../ui/provenance";
import { CadViewer } from "../viewer/cad-viewer";
import { GhostCursor } from "./ghost-cursor";

/** Up to four knobs: the preferred names first (those the part has), then the rest in the program's order. */
export function pickKnobs(params: ParamSpec[], prefer: readonly string[] = [], n = 4): ParamSpec[] {
  const first = prefer.map((name) => params.find((p) => p.name === name)).filter((p): p is ParamSpec => !!p);
  return [...first, ...params.filter((p) => !first.includes(p))].slice(0, n);
}

/** Highlight the knob row whose label names `name` (KnobPanel labels carry the knob name as their title). */
function useKnobHighlight(root: React.RefObject<HTMLElement | null>, name: string | null | undefined) {
  React.useEffect(() => {
    const el = root.current;
    if (!el || !name) return;
    const row = el.querySelector(`label[title="${CSS.escape(name)}"]`)?.closest<HTMLElement>(".group\\/knob");
    if (!row) return;
    const cls = ["rounded-md", "bg-accent-soft", "outline", "outline-accent/40", "outline-offset-4"];
    row.classList.add(...cls);
    return () => row.classList.remove(...cls);
  }, [root, name]);
}

type Props = {
  /** the recorded run to offer first (its program's knobs, re-baked through the job) */
  jobId?: string | null;
  /** knob names to list first */
  prefer?: readonly string[];
  /** knob to highlight (e.g. from a drawing's balloon) */
  highlight?: string | null;
};

const tabCls = (on: boolean) => cn("press h-7 shrink-0 rounded-md px-2.5 text-[12px] font-medium text-muted hover:text-fg", on && "bg-surface-2 text-fg");

function Body({ viewer, side }: { viewer: React.ReactNode; side: React.ReactNode }) {
  // fixed height on desktop: loading → loaded never shifts the page
  return (
    <div className="grid grid-cols-1 md:h-[456px] md:grid-cols-[minmax(0,1fr)_268px]">
      {viewer}
      {side}
    </div>
  );
}

// phones stack the side under the viewer: a floor at the recorded run's knob list height, so loading → loaded (and the
// placeholder in program-section) never moves the page; desktop has the fixed 456 px row
const sideCls = "scrollbar-thin relative flex min-h-[540px] flex-col gap-4 border-t border-border p-4 md:min-h-0 md:overflow-y-auto md:border-t-0 md:border-l";

function KnobSkeleton() {
  return (
    <div className="space-y-4">
      {[0, 1, 2].map((i) => (
        <Skeleton key={i} className="h-12" />
      ))}
    </div>
  );
}

function RecordedPanel({ jobId, prefer, highlight }: { jobId: string; prefer?: readonly string[]; highlight?: string | null }) {
  const job = useQuery({ queryKey: ["job", jobId], queryFn: () => api.job(jobId), staleTime: 300_000 });
  const [values, setValues] = React.useState<Record<string, number> | null>(null);
  React.useEffect(() => {
    if (job.data && !values) setValues({ ...job.data.values });
  }, [job.data, values]);
  const d = job.data;
  const changed = !!d && !!values && d.params.some((p) => values[p.name] !== d.values[p.name]);
  const bake = useJobBake(jobId, changed ? values : null);
  const viewUrl = changed ? (bake.data?.artifacts.view ?? d?.artifacts.view) : d?.artifacts.view;
  const panel = React.useRef<HTMLDivElement>(null);
  useKnobHighlight(panel, highlight);
  const shown = d ? pickKnobs(d.params, prefer) : [];
  const title = d ? splitTitle(d.summary.title.replace(/\s*·\s*review round \d+\s*$/i, "")).title : "";
  return (
    <Body
      viewer={<CadViewer viewUrl={viewUrl} busy={bake.pending} className="aspect-[4/3] md:aspect-auto md:h-full" label={`3D model of ${title || "the part"}`} emptyText={d ? "No model in this run." : "Loading…"} />}
      side={
        <div ref={panel} className={sideCls}>
          {job.isError ? (
            <ErrorState error={job.error} compact what="the recorded run" />
          ) : (
            <>
              {d ? (
                <div className="flex flex-wrap items-center gap-1.5">
                  <PartStatusBadge status={d.verification?.verified ? "verified" : "best_effort"} maxErrorMm={d.verification?.max_error_mm ?? d.summary.max_error_mm} />
                  <RunBadge mode={d.summary.provider_mode} recorded />
                  <OriginBadge origin={d.summary.origin} hideReal />
                </div>
              ) : (
                <Skeleton className="h-5 w-32" />
              )}
              {d && values ? <KnobPanel params={shown} values={values} onChange={setValues} bake={bake.data} pending={bake.pending && changed} error={bake.error} dense /> : <KnobSkeleton />}
              <Link href={`/jobs/${encodeURIComponent(jobId)}`} className="mt-auto inline-flex items-center gap-1 text-[13px] font-medium text-accent-text hover:underline">
                Open the run{d && d.params.length > 4 ? ` · all ${d.params.length} knobs` : ""} <ArrowUpRight className="size-3.5" aria-hidden />
              </Link>
              {d && values ? <GhostCursor root={panel} params={shown} values={values} onChange={setValues} /> : null}
            </>
          )}
        </div>
      }
    />
  );
}

function PartPanel({ slug, prefer, highlight, card }: { slug: string; prefer?: readonly string[]; highlight?: string | null; card?: { title: string; status: Parameters<typeof PartStatusBadge>[0]["status"]; max_error_mm?: number | null; origin: Parameters<typeof OriginBadge>[0]["origin"]; thumbnail_url?: string | null; thumbnail_2x_url?: string | null } }) {
  const live = useLivePart(slug);
  const params = live.part.data?.params ?? [];
  const shown = pickKnobs(params, prefer);
  const panel = React.useRef<HTMLDivElement>(null);
  useKnobHighlight(panel, highlight);
  return (
    <Body
      viewer={
        <CadViewer
          viewUrl={live.viewUrl}
          poster={artifactUrl(card?.thumbnail_url)}
          poster2x={artifactUrl(card?.thumbnail_2x_url)}
          busy={live.bake.pending}
          className="aspect-[4/3] md:aspect-auto md:h-full"
          label={card ? `3D model of ${card.title}` : "3D model"}
          emptyText="No model yet."
        />
      }
      side={
        <div ref={panel} className={sideCls}>
          {card ? (
            <div className="flex flex-wrap items-center gap-1.5">
              <PartStatusBadge status={card.status} maxErrorMm={card.max_error_mm} />
              <OriginBadge origin={card.origin} hideReal />
            </div>
          ) : null}
          {live.part.isPending ? (
            <KnobSkeleton />
          ) : live.part.isError ? (
            <ErrorState error={live.part.error} compact what="this part" />
          ) : (
            <KnobPanel params={shown} values={live.values} onChange={live.setValues} bake={live.bake.data} pending={live.bake.pending && live.changed} error={live.bake.error} dense />
          )}
          <Link href={`/parts/${encodeURIComponent(slug)}`} className="mt-auto inline-flex items-center gap-1 text-[13px] font-medium text-accent-text hover:underline">
            Open part page{params.length > 4 ? ` · all ${params.length} knobs` : ""} <ArrowUpRight className="size-3.5" aria-hidden />
          </Link>
          {live.part.data && Object.keys(live.values).length ? <GhostCursor root={panel} params={shown} values={live.values} onChange={live.setValues} /> : null}
        </div>
      }
    />
  );
}

export function LiveKnobDemo({ jobId, prefer, highlight }: Props = {}) {
  const verifiedList = useQuery({ queryKey: ["parts", "hero"], queryFn: () => api.parts({ verified: true, limit: 4, sort: "newest" }) });
  // No verified parts yet: show the closest best-effort ones — their badges say so.
  const anyList = useQuery({
    queryKey: ["parts", "hero-any"],
    queryFn: () => api.parts({ limit: 4, sort: "error" }),
    enabled: verifiedList.isSuccess && verifiedList.data.items.length === 0,
  });
  const list = verifiedList.isSuccess && verifiedList.data.items.length === 0 ? anyList : verifiedList;
  const parts = list.data?.items ?? [];
  const job = useQuery({ queryKey: ["job", jobId], queryFn: () => api.job(jobId!), enabled: !!jobId, staleTime: 300_000 });
  const jobTitle = job.data ? splitTitle(job.data.summary.title.replace(/\s*·\s*review round \d+\s*$/i, "")).title : null;
  const [tab, setTab] = React.useState<string | null>(null);
  const active = tab ?? (jobId ? `job:${jobId}` : parts[0] ? `part:${parts[0].slug}` : null);
  const card = parts.find((p) => `part:${p.slug}` === active);

  if (!jobId && list.isError) {
    return (
      <div className="overflow-hidden rounded-xl border border-border bg-surface shadow-lg">
        <ErrorState error={list.error} onRetry={() => void list.refetch()} what="the live demo" className="m-4 border-0" />
      </div>
    );
  }
  if (!jobId && list.isSuccess && parts.length === 0) {
    return (
      <div className="overflow-hidden rounded-xl border border-dashed border-border-strong bg-surface p-8 text-center text-[13px] text-muted">
        <p>No parts are published yet, so there are no knobs to turn here.</p>
        <p className="mt-2">
          <Link href="/jobs/demo" className="font-medium text-accent-text hover:underline">
            Try a sample
          </Link>{" "}
          or{" "}
          <Link href="/fix" className="font-medium text-accent-text hover:underline">
            fix a part
          </Link>{" "}
          to make the first one.
        </p>
      </div>
    );
  }

  return (
    <div className="overflow-hidden rounded-xl border border-border bg-surface shadow-lg">
      <div className="no-scrollbar flex items-center gap-1 overflow-x-auto border-b border-border px-2 py-1.5" role="tablist" aria-label="Demo parts">
        {jobId ? (
          <button role="tab" type="button" aria-selected={active === `job:${jobId}`} onClick={() => setTab(`job:${jobId}`)} className={tabCls(active === `job:${jobId}`)}>
            {jobTitle ?? "Recorded run"} <span className="font-normal text-subtle">· recorded run</span>
          </button>
        ) : null}
        {list.isPending && !jobId
          ? [0, 1, 2].map((i) => <Skeleton key={i} className="h-7 w-28" />)
          : parts.map((p) => (
              <button key={p.slug} role="tab" aria-selected={`part:${p.slug}` === active} type="button" onClick={() => setTab(`part:${p.slug}`)} className={tabCls(`part:${p.slug}` === active)}>
                {p.title}
              </button>
            ))}
      </div>
      {active?.startsWith("job:") && jobId ? (
        <RecordedPanel key={active} jobId={jobId} prefer={prefer} highlight={highlight} />
      ) : active?.startsWith("part:") ? (
        <PartPanel key={active} slug={active.slice(5)} prefer={prefer} highlight={highlight} card={card} />
      ) : (
        <Body viewer={<div className="aspect-[4/3] bg-[var(--viewer-bg)] bg-dots md:aspect-auto md:h-full" />} side={<div className={sideCls}><KnobSkeleton /></div>} />
      )}
    </div>
  );
}
