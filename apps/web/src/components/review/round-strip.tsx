import { Check, CornerUpLeft, Hourglass, X } from "lucide-react";
import type { ReviewRound } from "@/lib/api-types";
import { fmtErr } from "@/lib/format";
import { verdictTone } from "@/lib/review";
import { cn } from "@/lib/utils";

const TONE_TEXT: Record<string, string> = { ok: "text-ok", warn: "text-warn", bad: "text-bad", neutral: "text-muted" };
const DECISION_ICON = { accept: Check, improve: CornerUpLeft, reject: X } as const;
const DECISION_WORD: Record<string, string> = { accept: "accepted", improve: "sent back", reject: "rejected" };

/** One line that tells the chain's story: each round's worst error (from the verifier) and what the reviewer did. */
export function RoundStrip({ rounds, className }: { rounds: ReviewRound[]; className?: string }) {
  if (rounds.length < 2) return null;
  return (
    // focusable so keyboard users can scroll it when the rounds overflow on a phone
    <ol aria-label="Rounds so far" tabIndex={0} className={cn("scrollbar-thin flex items-stretch gap-1 overflow-x-auto pb-1", className)}>
      {rounds.map((r, i) => {
        const last = i === rounds.length - 1;
        const v = r.verdict;
        const Icon = r.decision ? (DECISION_ICON[r.decision as keyof typeof DECISION_ICON] ?? Hourglass) : Hourglass;
        return (
          <li key={r.job_id} className="flex shrink-0 items-center gap-1">
            <div
              className={cn("rounded-md border px-2.5 py-1.5 text-[12px] leading-tight", last ? "border-accent bg-accent-soft" : "border-border bg-surface")}
              aria-current={last ? "step" : undefined}
            >
              <div className="font-medium">Round {r.round}</div>
              <div className={cn("font-mono tnum", TONE_TEXT[verdictTone(v)])}>
                {v?.status === "verified" ? "verified · " : ""}
                {v?.max_error_mm != null ? `${fmtErr(v.max_error_mm)} mm` : "no number"}
              </div>
              <div className="flex items-center gap-1 text-[11px] text-subtle">
                <Icon className="size-3" aria-hidden />
                {r.decision ? DECISION_WORD[r.decision] ?? r.decision : "waiting for you"}
              </div>
            </div>
            {!last ? (
              <span aria-hidden className="text-subtle">
                →
              </span>
            ) : null}
          </li>
        );
      })}
    </ol>
  );
}
