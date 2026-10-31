"use client";

/**
 * "A person signs off": a recorded review chain round by round — the code's max error after each round and what the
 * reviewer said — read from `GET /review/{job_id}`, plus the latest lines of the feedback log (`GET /review/feedback`).
 * Rounds decided by a script are labelled "scripted test review", never passed off as a person's review.
 */
import { useQuery } from "@tanstack/react-query";
import { ArrowRight, BadgeCheck, Hourglass, MessageSquareText, ShieldAlert, XCircle } from "lucide-react";
import Link from "next/link";
import * as React from "react";
import { review } from "@/lib/api-review";
import type { FeedbackEntry, ReviewRound } from "@/lib/api-types";
import { pickReviewRun } from "@/lib/figure-run";
import { fmtNum, splitTitle } from "@/lib/format";
import { DECISION_LABEL, KIND_LABEL, OUTCOME_LABEL, blockingVeto, outcomeTone } from "@/lib/review";
import { cn } from "@/lib/utils";
import { Badge } from "../ui/badge";
import { ErrorState } from "../ui/error-state";
import { Button } from "../ui/button";
import { CountUp } from "../ui/count-up";
import { Skeleton } from "../ui/skeleton";
import { useReplays } from "./use-figure-run";

/** The chain's closing line: what code decided on the last round and what the review record says, in one tone that
 * follows the review state (green only once a person accepted it). */
function ClosingPill({ verified, status }: { verified: boolean; status: string }) {
  const words = status.replaceAll("_", " ");
  const head = verified ? "Code verified the last round" : "The last round is not verified by code";
  if (status === "accepted")
    return (
      <p className="mt-6 inline-flex items-center gap-2 rounded-md border border-ok-border bg-ok-soft px-3 py-1.5 text-[13px] text-fg">
        <BadgeCheck className="size-4 text-ok" aria-hidden /> {head}; a reviewer accepted it.
      </p>
    );
  if (status === "rejected")
    return (
      <p className="mt-6 inline-flex items-center gap-2 rounded-md border border-bad-border bg-bad-soft px-3 py-1.5 text-[13px] text-fg">
        <XCircle className="size-4 text-bad" aria-hidden /> {head}; a reviewer rejected it.
      </p>
    );
  return (
    <p className="mt-6 inline-flex items-center gap-2 rounded-md border border-border-strong bg-surface-2 px-3 py-1.5 text-[13px] text-fg">
      <Hourglass className="size-4 text-muted" aria-hidden /> {head}; the review record says “{words}”: no one has signed it off yet.
    </p>
  );
}

function ByBadge({ by }: { by: string | null | undefined }) {
  if (!by) return null;
  return by === "person" ? <Badge tone="outline">a person</Badge> : <Badge tone="mock">scripted test review</Badge>;
}

/**
 * The ledger's rule for the outcome ("fixed: the next round passed verification"), without the repeated label. When the
 * number did not move but the next round passed, the chain's own judge records say why: a blocking veto on this round
 * that the next round no longer had.
 */
function outcomeWhy(e: FeedbackEntry, rounds: readonly ReviewRound[]): string {
  const why = e.outcome_why.replace(/^[a-z_ ]+:\s*/i, "");
  const at = rounds.findIndex((r) => r.job_id === e.job_id);
  const veto = at >= 0 ? blockingVeto(rounds[at]!.judge) : null;
  const next = at >= 0 ? rounds[at + 1] : undefined;
  const cleared = veto && next && next.verdict?.status === "verified" && !blockingVeto(next.judge);
  const same = e.before_mm != null && e.after_mm != null && Math.abs(e.before_mm - e.after_mm) < 0.005;
  if (cleared && same) return `${cap(why)}: the number did not move; the ${veto.text.replace(/^judge blocked it: /, "judge's block (")}) was cleared.`;
  return `${cap(why)}.`;
}

function cap(s: string): string {
  return s.charAt(0).toUpperCase() + s.slice(1);
}

export function SignOff() {
  const replays = useReplays();
  const pick = React.useMemo(() => (replays.data ? pickReviewRun(replays.data) : null), [replays.data]);
  const chain = useQuery({ queryKey: ["review", "detail", pick?.id], queryFn: () => review.detail(pick!.id), enabled: !!pick, retry: false, staleTime: 120_000 });
  const log = useQuery({ queryKey: ["review", "feedback", "landing"], queryFn: () => review.feedback(), retry: false, staleTime: 120_000 });
  const rounds = chain.data?.rounds ?? [];
  const root = chain.data?.root_job;
  const entries = (log.data?.items ?? []).slice().sort((a, b) => Number(b.root_job === root) - Number(a.root_job === root)).slice(0, 3);
  const last = rounds.at(-1);
  const title = pick ? splitTitle(pick.title.replace(/\s*·\s*review round \d+\s*$/i, "")).title : "";

  const actions = (
    <div className="flex flex-wrap gap-2">
      <Button asChild variant="outline" size="sm">
        <Link href="/review">
          Open the review desk <ArrowRight aria-hidden />
        </Link>
      </Button>
      <Button asChild variant="ghost" size="sm">
        <Link href="/review/log">Feedback log</Link>
      </Button>
    </div>
  );

  if (replays.isError) return <ErrorState error={replays.error} compact what="the recorded review" onRetry={() => void replays.refetch()} />;
  if (replays.isPending || (pick && chain.isPending)) return <Skeleton className="h-72" />;
  if (!pick || chain.isError || !rounds.length)
    return (
      <div className="space-y-4">
        <p className="rounded-xl border border-dashed border-border-strong bg-surface px-5 py-6 text-[13.5px] text-muted">
          No recorded review chain on this server yet. Reviews happen on the review desk: a person pins what is wrong on the photo and sends the part back.
        </p>
        {actions}
      </div>
    );

  return (
    <div className="space-y-6">
      <div className="rounded-xl border border-border bg-surface p-5 sm:p-6" data-reveal>
        <div className="mb-5 flex flex-wrap items-center gap-2 text-[13px]">
          <span className="font-medium text-fg">{title}</span>
          <Badge tone="mock">recorded run</Badge>
          <span className="text-muted">· {rounds.length} rounds, read from the review record</span>
        </div>
        <ol className="relative grid gap-5 md:grid-flow-col md:auto-cols-fr md:gap-0" aria-label="Review rounds">
          {rounds.map((r, i) => {
            const v = r.verdict;
            const ok = v?.status === "verified";
            const veto = ok ? null : blockingVeto(r.judge);
            return (
              <li key={r.job_id} className="relative flex gap-4 md:flex-col md:gap-3 md:pr-6" data-reveal style={{ "--reveal-i": i } as React.CSSProperties}>
                {/* connector */}
                {i < rounds.length - 1 ? <span aria-hidden className="absolute top-9 left-[17px] h-[calc(100%+4px)] w-px bg-border md:top-[17px] md:left-9 md:h-px md:w-[calc(100%-2.25rem)]" /> : null}
                <span
                  className={cn(
                    "relative z-10 flex size-9 shrink-0 items-center justify-center rounded-full border font-mono text-[12px] font-semibold tnum",
                    ok ? "border-ok bg-ok-soft text-ok" : "border-border-strong bg-surface text-fg",
                  )}
                >
                  {ok ? <BadgeCheck className="size-4" aria-label="verified" /> : r.round}
                </span>
                <div className="min-w-0 space-y-1.5">
                  <div className="font-mono text-[10.5px] tracking-[0.14em] text-subtle uppercase">Round {r.round}</div>
                  <div className={cn("font-mono text-[28px] leading-none font-medium tracking-[-0.03em]", ok ? "text-ok" : "text-fg")}>
                    {v?.max_error_mm != null ? <CountUp text={`${fmtNum(v.max_error_mm)} mm`} unitClassName="ml-0.5 text-[0.5em] tracking-normal text-muted" /> : "—"}
                  </div>
                  <div className="text-[12px] text-muted">{v ? v.status.replaceAll("_", " ") : "no verdict yet"}</div>
                  {veto ? (
                    <div className="max-w-xs space-y-0.5" title={veto.detail}>
                      <p className="flex items-start gap-1 text-[12px] leading-4 text-bad">
                        <ShieldAlert className="mt-px size-3.5 shrink-0" aria-hidden /> {veto.text}
                      </p>
                      <p className="font-mono text-[10.5px] text-subtle">{veto.by}</p>
                    </div>
                  ) : null}
                  <div className="flex flex-wrap items-center gap-1.5 pt-0.5">
                    {r.decision ? <Badge tone={r.decision === "accept" ? "ok" : r.decision === "reject" ? "bad" : "neutral"}>{DECISION_LABEL[r.decision] ?? r.decision}</Badge> : <Badge tone="outline">{i === rounds.length - 1 ? chain.data!.status.replaceAll("_", " ") : "—"}</Badge>}
                    <ByBadge by={r.by} />
                  </div>
                  {r.note ? <p className="line-clamp-3 max-w-xs text-[12.5px] leading-5 text-muted">“{r.note}”</p> : null}
                </div>
              </li>
            );
          })}
        </ol>
        {last?.verdict ? <ClosingPill verified={last.verdict.status === "verified"} status={chain.data!.status} /> : null}
      </div>

      {entries.length ? (
        <div className="space-y-3" data-reveal style={{ "--reveal-i": 2 } as React.CSSProperties}>
          <h3 className="flex items-center gap-2 text-[14px] font-semibold text-fg">
            <MessageSquareText className="size-4 text-muted" aria-hidden /> From the feedback log
          </h3>
          <ul className="grid grid-cols-1 gap-3 md:grid-cols-3">
            {entries.map((e) => (
              <li key={e.id} className="flex flex-col gap-2.5 rounded-lg border border-border bg-surface p-4">
                <div className="flex flex-wrap items-center gap-1.5">
                  <Badge tone="neutral">{KIND_LABEL[e.kind] ?? e.kind}</Badge>
                  <Badge tone={outcomeTone(e.outcome)}>{OUTCOME_LABEL[e.outcome] ?? e.outcome}</Badge>
                  <ByBadge by={e.by} />
                </div>
                <p className="line-clamp-3 text-[13px] leading-5 text-fg">“{e.what}”</p>
                {e.outcome_why ? <p className="text-[12px] leading-4 text-muted">{outcomeWhy(e, rounds)}</p> : null}
                {e.before_mm != null && e.after_mm != null ? (
                  <p className="mt-auto font-mono text-[12px] text-muted tnum">
                    {e.kind === "pin" ? "gap at the pin" : "max error"} {fmtNum(e.before_mm)} → <span className={e.after_mm <= e.limit_mm ? "text-ok" : "text-fg"}>{fmtNum(e.after_mm)} mm</span> · limit {fmtNum(e.limit_mm)}
                  </p>
                ) : null}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      {actions}
    </div>
  );
}
