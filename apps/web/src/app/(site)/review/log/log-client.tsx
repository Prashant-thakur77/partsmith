"use client";

import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, Bot, Download, History, ImageIcon, MapPin, MessageSquareText, ThumbsDown, ThumbsUp } from "lucide-react";
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
import { allTests, groupFeedback, type FeedbackBlock, type FeedbackRound } from "@/lib/page-groups";
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

function Entry({ e, testBadge }: { e: FeedbackEntry; testBadge: boolean }) {
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
          {testBadge && e.by !== "person" ? <Badge tone="mock">test review, not a person</Badge> : null}
        </div>
        <p className="text-[14px] leading-snug">
          <span className="text-subtle">What: </span>“{e.what}”
        </p>
        {e.why ? (
          <p className="text-[13px] leading-snug text-fg">
            <span className="text-subtle">Why: </span>“{e.why}”
          </p>
        ) : null}
        <p className="flex flex-wrap gap-x-3 gap-y-0.5 text-[12px] text-muted">
          <Link href={`/review?job=${encodeURIComponent(e.job_id)}`} className="text-accent-text hover:underline">
            Round {e.round} in the review queue
          </Link>
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

/** Each round's measured gap before → after as bars against the limit (all numbers from the verifier, via the log). */
function GapTrack({ rounds, limit }: { rounds: FeedbackRound[]; limit: number }) {
  const measured = rounds.filter((r) => r.before_mm != null || r.after_mm != null);
  if (!measured.length) return <p className="text-[12px] text-subtle">No gap was measured for these rounds.</p>;
  const top = Math.max(limit * 1.25, ...measured.flatMap((r) => [r.before_mm ?? 0, r.after_mm ?? 0]));
  const pct = (v: number) => `${Math.max(2, (v / top) * 100)}%`;
  const bar = (v: number | null, kind: "before" | "after") =>
    v == null ? (
      <span className="text-[11px] text-subtle">not measured</span>
    ) : (
      <span className="flex min-w-0 flex-1 items-center gap-2">
        <span className="relative h-2 min-w-0 flex-1 rounded-full bg-border">
          <span className={cn("absolute inset-y-0 left-0 rounded-full", v <= limit ? "bg-ok" : kind === "before" ? "bg-warn" : "bg-accent")} style={{ width: pct(v) }} />
          <span className="absolute -inset-y-0.5 w-px bg-ok" style={{ left: pct(limit) }} aria-hidden />
        </span>
        <span className="w-16 shrink-0 text-right font-mono text-[11.5px] tnum">{v.toFixed(2)} mm</span>
      </span>
    );
  return (
    <div className="space-y-1.5" role="group" aria-label={`Gap before and after each round, limit ${limit.toFixed(2)} mm`}>
      {measured.map((r) => (
        <div key={r.round} className="grid grid-cols-[4.5rem_minmax(0,1fr)] items-center gap-x-2 gap-y-1 text-[11.5px] sm:grid-cols-[4.5rem_minmax(0,1fr)_minmax(0,1fr)]">
          <span className="text-muted">Round {r.round}</span>
          <span className="flex min-w-0 items-center gap-1.5">
            <span className="w-10 shrink-0 text-subtle">before</span>
            {bar(r.before_mm, "before")}
          </span>
          <span className="col-start-2 flex min-w-0 items-center gap-1.5 sm:col-start-auto">
            <span className="w-10 shrink-0 text-subtle">after</span>
            {bar(r.after_mm, "after")}
          </span>
        </div>
      ))}
      <p className="text-[11px] text-subtle">
        Worst gap of the reviewed model (before) and of the model the feedback produced (after), measured by code. Green line: the {limit.toFixed(2)} mm limit.
      </p>
    </div>
  );
}

/** One part's review chain: its rounds in order, the gap track, then each piece of feedback. */
function Block({ b, testBadges }: { b: FeedbackBlock<FeedbackEntry>; testBadges: boolean }) {
  const reasons = b.entries.filter((e) => e.why).length;
  const id = `fb-${b.root.replace(/\W+/g, "-")}`;
  return (
    <li className="space-y-3 rounded-xl border border-border bg-surface p-4" aria-labelledby={id}>
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 id={id} className="text-[15px] font-semibold">
          <Link href={`/review?job=${encodeURIComponent(b.root)}`} className="hover:underline">
            {b.title}
          </Link>
        </h2>
        <p className="flex flex-wrap gap-x-2 text-[12px] text-muted tnum">
          {b.family ? <span>{titleCase(b.family)}</span> : null}
          <span>
            {b.rounds.length} round{b.rounds.length === 1 ? "" : "s"} · {b.entries.length} piece{b.entries.length === 1 ? "" : "s"} of feedback
          </span>
          <span>{reasons ? `${reasons} with a reason` : "no reason given"}</span>
        </p>
      </div>
      <GapTrack rounds={b.rounds} limit={b.limit_mm} />
      <ol className="space-y-2" aria-label={`Feedback on ${b.title}, by round`}>
        {b.entries.map((e) => (
          <Entry key={e.id} e={e} testBadge={testBadges} />
        ))}
      </ol>
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
              <>
                {allTests(log.data.items) ? (
                  <div role="note" className="flex items-start gap-2 rounded-lg border border-dashed border-border-strong bg-surface-2 px-3 py-2 text-[12.5px] text-muted">
                    <Bot className="mt-0.5 size-4 shrink-0" aria-hidden />
                    <span>
                      <span className="font-medium text-fg">Every entry below is a test review, not a person.</span> A script played the reviewer to exercise the review loop.
                    </span>
                  </div>
                ) : null}
                <ol className="space-y-4" aria-label="Feedback by part, newest first">
                  {groupFeedback(log.data.items).map((b) => (
                    <Block key={b.root} b={b} testBadges={!allTests(log.data.items)} />
                  ))}
                </ol>
              </>
            )}
          </>
        )}
      </Container>
    </>
  );
}
