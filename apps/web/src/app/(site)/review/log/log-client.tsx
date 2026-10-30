"use client";

import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, Download, History, ImageIcon, MapPin, MessageSquareText, ThumbsDown, ThumbsUp } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import * as React from "react";
import { Container, PageHeader } from "@/components/layout/page";
import { Badge } from "@/components/ui/badge";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorState } from "@/components/ui/error-state";
import { Skeleton } from "@/components/ui/skeleton";
import { apiUrl, artifactUrl } from "@/lib/api";
import { REVIEW, review } from "@/lib/api-review";
import type { FeedbackEntry } from "@/lib/api-types";
import { useCapabilities } from "@/lib/capabilities";
import { timeAgo, titleCase } from "@/lib/format";
import { feedbackSummary, KIND_LABEL, OUTCOME_LABEL, outcomeTone, usedText } from "@/lib/review";
import { cn } from "@/lib/utils";

const KIND_ICON = { pin: MapPin, note: MessageSquareText, picture: ImageIcon, reject: ThumbsDown, accept: ThumbsUp } as const;
const OUTCOMES = ["", "fixed", "better", "not_fixed", "waiting", "rejected", "accepted"] as const;

/** A close-up of the spot the reviewer pinned: the photo zoomed around (u, v) with the pin drawn on it. */
function PinCrop({ photo, u, v, n }: { photo: string; u: number; v: number; n: number }) {
  const src = artifactUrl(photo);
  if (!src) return null;
  return (
    <div
      role="img"
      aria-label={`Close-up of pin ${n} on the photo`}
      className="relative size-24 shrink-0 overflow-hidden rounded-md border border-border bg-surface-2 bg-no-repeat"
      style={{ backgroundImage: `url("${src}")`, backgroundSize: "700%", backgroundPosition: `${u * 100}% ${v * 100}%` }}
    >
      <span
        className="absolute flex size-5 -translate-x-1/2 -translate-y-1/2 items-center justify-center rounded-full border-2 border-white bg-bad font-mono text-[10px] font-semibold text-white shadow"
        style={{ left: `${u * 100}%`, top: `${v * 100}%` }}
        aria-hidden
      >
        {n}
      </span>
    </div>
  );
}

function Entry({ e }: { e: FeedbackEntry }) {
  const Icon = KIND_ICON[e.kind];
  const used = usedText(e.used_in);
  const measured = e.before_mm != null && e.after_mm != null;
  return (
    <li className="flex gap-3 rounded-lg border border-border bg-surface p-3">
      {e.kind === "pin" && e.where && e.photo ? (
        <PinCrop photo={e.photo} u={e.where.u} v={e.where.v} n={e.where.pin} />
      ) : e.kind === "picture" && e.picture ? (
        // eslint-disable-next-line @next/next/no-img-element -- a reviewer's attached picture (API blob)
        <img src={artifactUrl(e.picture)} alt="The picture the reviewer attached" className="size-24 shrink-0 rounded-md border border-border object-cover" />
      ) : (
        <div className="flex size-24 shrink-0 items-center justify-center rounded-md border border-border bg-surface-2 text-subtle">
          <Icon className="size-6" aria-hidden />
        </div>
      )}
      <div className="min-w-0 flex-1 space-y-1.5">
        <div className="flex flex-wrap items-center gap-1.5 text-[12px]">
          <span className="inline-flex items-center gap-1 font-medium">
            <Icon className="size-3.5" aria-hidden /> {KIND_LABEL[e.kind] ?? e.kind}
          </span>
          <Badge tone={outcomeTone(e.outcome)}>{OUTCOME_LABEL[e.outcome] ?? e.outcome}</Badge>
          {measured ? (
            <span className="font-mono tnum text-muted">
              gap {e.before_mm!.toFixed(2)} → {e.after_mm!.toFixed(2)} mm <span className="text-subtle">(limit {e.limit_mm.toFixed(2)})</span>
            </span>
          ) : null}
          {e.by !== "person" ? <Badge tone="mock">test review, not a person</Badge> : null}
        </div>
        <p className="text-[14px] leading-snug">
          <span className="text-subtle">What: </span>“{e.what}”
        </p>
        <p className={cn("text-[13px] leading-snug", e.why ? "text-fg" : "text-subtle")}>
          <span className="text-subtle">Why: </span>
          {e.why ? `“${e.why}”` : "no reason given"}
        </p>
        <p className="flex flex-wrap gap-x-3 gap-y-0.5 text-[12px] text-muted">
          <Link href={`/review?job=${encodeURIComponent(e.job_id)}`} className="text-accent-text hover:underline">
            {(e.title || e.job_id).replace(/\s*·\s*review round \d+$/, "")} · round {e.round}
          </Link>
          {e.family ? <span>{titleCase(e.family)}</span> : null}
          {e.at ? <span>{timeAgo(e.at)}</span> : null}
          {e.next_job ? (
            <Link href={`/jobs/${encodeURIComponent(e.next_job)}`} className="font-mono hover:underline">
              next round {e.next_job}
            </Link>
          ) : null}
        </p>
        {used ? <p className="text-[12px] text-muted">{used}</p> : null}
      </div>
    </li>
  );
}

export function FeedbackLogClient() {
  const caps = useCapabilities();
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const family = params.get("family") ?? "";
  const outcome = params.get("outcome") ?? "";
  const by = params.get("by") ?? "";
  const available = caps.has("get", REVIEW.feedback);
  const log = useQuery({
    queryKey: ["review", "feedback", family, outcome, by],
    queryFn: () => review.feedback({ family: family || undefined, outcome: outcome || undefined, by: by || undefined }),
    enabled: available,
  });
  const all = useQuery({ queryKey: ["review", "feedback", "", "", ""], queryFn: () => review.feedback(), enabled: available });
  const set = (k: string, v: string) => {
    const q = new URLSearchParams(params.toString());
    if (v) q.set(k, v);
    else q.delete(k);
    router.replace(`${pathname}${q.size ? `?${q}` : ""}`, { scroll: false });
  };
  const select = "h-8 rounded-md border border-border bg-surface px-2 text-[13px]";
  return (
    <>
      <PageHeader
        compact
        eyebrow="Review"
        title="Feedback log"
        description="Every time a part was sent back or rejected: what was wrong, why it matters, and what the measurements showed in the next round. A person's feedback that code measured as fixed is given to later jobs of the same kind of part."
        actions={
          <>
            <Link href="/review" className="inline-flex h-8 items-center gap-1.5 rounded-md border border-border bg-surface px-3 text-[13px] font-medium hover:bg-surface-2">
              <ArrowLeft className="size-4" aria-hidden /> Review queue
            </Link>
            <a
              href={apiUrl(REVIEW.feedback)}
              download="partsmith-feedback-log.json"
              className="inline-flex h-8 items-center gap-1.5 rounded-md border border-border bg-surface px-3 text-[13px] font-medium hover:bg-surface-2"
            >
              <Download className="size-4" aria-hidden /> Download (JSON)
            </a>
          </>
        }
      />
      <Container className="space-y-4 py-6">
        {!caps.ready ? (
          <Skeleton className="h-40" />
        ) : !available ? (
          <EmptyState icon={History} title="The feedback log is not available on this server yet">
            This API does not serve the feedback log.
          </EmptyState>
        ) : (
          <>
            <div className="flex flex-wrap items-end gap-3" role="group" aria-label="Filters">
              <label className="space-y-1 text-[12px] text-muted">
                <span className="block">Kind of part</span>
                <select className={select} value={family} onChange={(e) => set("family", e.target.value)}>
                  <option value="">All</option>
                  {(all.data?.families ?? []).map((f) => (
                    <option key={f} value={f}>
                      {titleCase(f)}
                    </option>
                  ))}
                </select>
              </label>
              <label className="space-y-1 text-[12px] text-muted">
                <span className="block">Result</span>
                <select className={select} value={outcome} onChange={(e) => set("outcome", e.target.value)}>
                  {OUTCOMES.map((o) => (
                    <option key={o} value={o}>
                      {o ? OUTCOME_LABEL[o] : "All"}
                    </option>
                  ))}
                </select>
              </label>
              <label className="space-y-1 text-[12px] text-muted">
                <span className="block">Reviewer</span>
                <select className={select} value={by} onChange={(e) => set("by", e.target.value)}>
                  <option value="">Everyone</option>
                  <option value="person">A person</option>
                  <option value="test">Test reviews</option>
                </select>
              </label>
              {log.data ? <p className="ml-auto text-[13px] text-muted tnum">{feedbackSummary(log.data.counts)}</p> : null}
            </div>
            {log.isPending ? (
              <Skeleton className="h-64" />
            ) : log.isError ? (
              <ErrorState error={log.error} what="the feedback log" onRetry={() => void log.refetch()} />
            ) : !log.data.items.length ? (
              <EmptyState icon={History} title={family || outcome || by ? "No feedback matches these filters" : "No feedback yet"}>
                {family || outcome || by ? "Clear a filter to see more." : "Send a part back from the review queue and it shows up here, with the result of the next round."}
              </EmptyState>
            ) : (
              <ol className="space-y-2" aria-label="Feedback, newest first">
                {log.data.items.map((e) => (
                  <Entry key={e.id} e={e} />
                ))}
              </ol>
            )}
          </>
        )}
      </Container>
    </>
  );
}
