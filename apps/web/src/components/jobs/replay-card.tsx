"use client";

import { useQuery } from "@tanstack/react-query";
import { ArrowRight } from "lucide-react";
import Link from "next/link";
import * as React from "react";
import { api, artifactUrl } from "@/lib/api";
import type { ArtifactEvent, Replay } from "@/lib/api-types";
import { fmtErr, splitTitle } from "@/lib/format";
import { replayTitle, replayVerdict } from "@/lib/replays";
import { cn } from "@/lib/utils";
import { Badge } from "../ui/badge";
import { OriginBadge, RunBadge } from "../ui/provenance";
import { imagesByView } from "./photo-panel";

const TONE = { verified: "ok", "best effort": "warn", "no model": "neutral" } as const;

/**
 * A stored run as a card: a picture from the run itself (its top-view measuring overlay, else the rectified photo, else
 * the photo — all URLs the job's own record returns; no picture when there is none), the title, one provenance chip
 * and the verdict. `thumb` fetches the job record for the picture; leave it off for long lists.
 */
export function ReplayCard({
  replay: r,
  why,
  thumb = false,
  href,
  onSelect,
  selected = false,
  className,
}: {
  replay: Replay;
  why?: string;
  thumb?: boolean;
  href?: string;
  onSelect?: () => void;
  selected?: boolean;
  className?: string;
}) {
  const job = useQuery({ queryKey: ["job", r.id], queryFn: () => api.job(r.id), enabled: thumb, staleTime: 5 * 60_000 });
  const img = React.useMemo(() => {
    if (!job.data) return null;
    const views = imagesByView(job.data.events.filter((e): e is ArtifactEvent => e.t === "artifact"), job.data.artifacts);
    const v = views.top ?? Object.values(views)[0];
    return v?.measure_overlay ?? v?.rectified ?? v?.photo ?? null;
  }, [job.data]);
  // the job record knows the exact status; the list only knows verified or not
  const status = job.data?.verification?.status;
  const word = status === "best_effort" ? "best effort" : status === "verified" ? "verified" : replayVerdict(r);
  const title = replayTitle(r.title, splitTitle);

  const body = (
    <>
      {thumb ? (
        <div className="relative aspect-[16/10] overflow-hidden border-b border-border bg-surface-2">
          {img ? (
            // eslint-disable-next-line @next/next/no-img-element -- run artifact served by the API, unknown size
            <img src={artifactUrl(img)} alt={`${title}: the run's top-view photo with what code measured`} loading="lazy" decoding="async" className="size-full object-cover" />
          ) : job.isPending ? (
            <div className="skeleton size-full" />
          ) : null}
        </div>
      ) : null}
      <div className="flex flex-1 flex-col gap-2 p-3.5">
        <div className="flex items-start justify-between gap-2">
          <span className="text-[14px] leading-5 font-medium text-fg">{title}</span>
          {href ? <ArrowRight className="mt-0.5 size-4 shrink-0 text-subtle group-hover:text-fg" aria-hidden /> : null}
        </div>
        {why ? <p className="text-[12.5px] leading-5 text-muted">{why}</p> : null}
        <div className="mt-auto flex flex-wrap gap-1.5">
          <Badge tone={TONE[word]}>{word}</Badge>
          <Badge tone="neutral" className="font-mono tnum">
            {r.iterations} {r.iterations === 1 ? "round" : "rounds"} · {r.max_error_mm != null ? `${fmtErr(r.max_error_mm)} mm` : "—"}
          </Badge>
          <RunBadge mode={r.provider_mode} recorded plain />
          <OriginBadge origin={r.origin} hideReal plain />
        </div>
      </div>
    </>
  );
  const cls = cn(
    "group flex h-full w-full flex-col overflow-hidden rounded-lg border bg-surface text-left transition-colors hover:border-border-strong",
    selected ? "border-fg shadow-[0_0_0_1px_var(--fg)]" : "border-border",
    className,
  );
  if (href)
    return (
      <Link href={href} className={cls}>
        {body}
      </Link>
    );
  return (
    <button type="button" onClick={onSelect} aria-pressed={selected} className={cls}>
      {body}
    </button>
  );
}
