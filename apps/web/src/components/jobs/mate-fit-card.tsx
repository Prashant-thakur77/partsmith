"use client";

/**
 * "Fits where it goes": the mate code measured on the "where it fits" photo (socket, shaft, slot or panel edge, ± σ),
 * the model's matching size measured on the CAD solid, the clearance and its class, and the printer note (with this
 * device's learned clearance when coupon reports exist). Informational: `verified` is about matching the broken part.
 * Shown only for jobs that have a mating photo (`GET /jobs/{id}/mate-fit`).
 */
import { useQuery } from "@tanstack/react-query";
import { ExternalLink, Puzzle } from "lucide-react";
import * as React from "react";
import { ApiError, api, artifactUrl } from "@/lib/api";
import { useCapabilities } from "@/lib/capabilities";
import { fitRows, type FitRow } from "@/lib/mate-fit";
import { useT } from "@/lib/i18n";
import { cn } from "@/lib/utils";
import { Badge } from "../ui/badge";
import { Eyebrow } from "../ui/card";
import { ErrorState } from "../ui/error-state";
import { Skeleton } from "../ui/skeleton";
import { useDeviceId } from "./coupon-fit";
import { SourceTag } from "./source-key";

export function useJobMateFit(jobId: string, enabled: boolean) {
  const caps = useCapabilities();
  const session = useDeviceId();
  return useQuery({
    queryKey: ["job-mate-fit", jobId, session],
    enabled: enabled && caps.has("get", "/jobs/{id}/mate-fit"),
    staleTime: 60_000,
    retry: false,
    queryFn: async () => {
      try {
        return await api.jobMateFit(jobId, session);
      } catch (e) {
        if (e instanceof ApiError && e.status === 404) return null; // no mating photo on this job
        throw e;
      }
    },
  });
}

function Line({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="grid grid-cols-1 gap-0.5 sm:grid-cols-[9.5rem_minmax(0,1fr)] sm:gap-3">
      <dt className="text-[11.5px] text-subtle">{label}</dt>
      <dd className="min-w-0 break-words text-[12.5px] text-fg">{children}</dd>
    </div>
  );
}

function MateRow({ row }: { row: FitRow }) {
  const { t } = useT();
  return (
    <li className="space-y-2 rounded-md border border-border bg-surface-2 p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-[13px] font-medium capitalize">
          {row.what} <span className="font-mono text-[11px] font-normal text-subtle normal-case">{row.id}</span>
        </p>
        {row.fit ? (
          <Badge tone={row.tone} className="font-medium">
            {row.fit}
          </Badge>
        ) : null}
      </div>
      <dl className="space-y-1.5">
        <Line label={t("mate.measured")}>
          {row.measured ? (
            <span className="flex flex-wrap items-center gap-x-2 gap-y-1">
              <span className="font-mono tnum">{row.measured}</span>
              <SourceTag kind="measured" />
              <span className="text-[11px] text-subtle">{t("mate.fromPhoto")}</span>
            </span>
          ) : (
            <span className="text-muted">{t("mate.notMeasured")}</span>
          )}
          {row.pointedBy ? <span className="block text-[11px] text-subtle">{row.pointedBy}{row.how ? ` · ${row.how}` : ""}</span> : null}
        </Line>
        {row.model ? (
          <Line label={t("mate.model")}>
            <span className="font-mono tnum">{row.model}</span>
            {row.modelNote ? <span className="block text-[11px] text-subtle">{row.modelNote}</span> : null}
          </Line>
        ) : null}
        {row.clearance ? (
          <Line label={t("mate.clearance")}>
            <span className="font-mono tnum">{row.clearance}</span>
            {row.range ? <span className="block text-[11px] text-subtle">{row.range}</span> : null}
          </Line>
        ) : null}
        {row.printer ? <Line label={t("mate.printer")}>{row.printer}</Line> : null}
      </dl>
      {row.problem ? (
        <p role="note" className={cn("text-[12px] leading-5", row.measured ? "text-muted" : "text-warn")}>
          {row.problem}
        </p>
      ) : null}
    </li>
  );
}

export function MateFitCard({ jobId, finished, overlay, className }: { jobId: string; finished: boolean; overlay?: string; className?: string }) {
  const { t } = useT();
  const q = useJobMateFit(jobId, finished);
  if (!finished || q.data === null || (!q.data && !q.isPending && !q.isError)) return null;
  if (q.isPending) return <Skeleton className={cn("h-40", className)} />;
  if (q.isError) return <ErrorState error={q.error} compact what={t("mate.title").toLowerCase()} onRetry={() => void q.refetch()} className={className} />;
  const res = q.data;
  if (!res || (!res.mates.length && !res.notes.length)) return null;
  const rows = fitRows(res);
  const href = artifactUrl(overlay);
  return (
    <section aria-labelledby={`mate-fit-${jobId}`} className={cn("space-y-3", className)}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 id={`mate-fit-${jobId}`} className="flex items-center gap-2 text-[13px] font-semibold">
          <Puzzle className="size-4 text-muted" aria-hidden /> {t("mate.title")}
        </h2>
        <Badge tone="outline">{t("mate.informational")}</Badge>
      </div>
      <p className="text-[12px] leading-5 text-muted">{t("mate.lead")}</p>
      {rows.length ? <ul className="space-y-2">{rows.map((r) => <MateRow key={r.id} row={r} />)}</ul> : null}
      {res.notes.length ? (
        <div className="space-y-0.5">
          <Eyebrow>{t("mate.notes")}</Eyebrow>
          <ul className="list-disc space-y-0.5 pl-4 text-[12px] text-muted">
            {res.notes.map((n) => (
              <li key={n} className="break-words">
                {n}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      {href ? (
        <a href={href} target="_blank" rel="noopener noreferrer" className="relative inline-flex items-center gap-1 text-[12px] font-medium text-accent-text hover:underline">
          <ExternalLink className="size-3.5" aria-hidden /> {t("mate.overlay")}
          <span className="sr-only"> (opens in a new tab)</span>
        </a>
      ) : null}
    </section>
  );
}
