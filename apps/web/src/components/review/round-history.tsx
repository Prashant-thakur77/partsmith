import Link from "next/link";
import { Badge } from "@/components/ui/badge";
import { Eyebrow } from "@/components/ui/card";
import type { ReviewRound } from "@/lib/api-types";
import { timeAgo } from "@/lib/format";
import { DECISION_LABEL, pinOutcome, roundLabel, scorecardSummary, verdictText, verdictTone } from "@/lib/review";
import { cn } from "@/lib/utils";

const DECISION_TONE: Record<string, "ok" | "warn" | "neutral" | "info"> = { accept: "ok", improve: "info", reject: "neutral" };

/** Every round of a review chain: the code's verdict, the decision, the notes, and each pin's before → after mismatch. */
export function RoundHistory({ rounds, className }: { rounds: ReviewRound[]; className?: string }) {
  if (!rounds.length) return null;
  return (
    <section className={cn("space-y-3 rounded-lg border border-border bg-surface p-4", className)} aria-label="Round history">
      <Eyebrow>Round history</Eyebrow>
      <ol className="space-y-3">
        {rounds.map((r) => (
          <li key={`${r.round}-${r.job_id}`} className="space-y-1.5 border-l-2 border-border pl-3">
            <div className="flex flex-wrap items-center gap-1.5 text-[12.5px]">
              <span className="font-medium capitalize">{roundLabel(r.round)}</span>
              <Badge tone={verdictTone(r.verdict)} className="font-mono tnum">
                {verdictText(r.verdict)}
              </Badge>
              <Badge tone={r.decision ? (DECISION_TONE[r.decision] ?? "neutral") : "warn"}>{r.decision ? (DECISION_LABEL[r.decision] ?? r.decision) : "waiting"}</Badge>
              {r.at ? <span className="text-[11.5px] text-subtle">{timeAgo(r.at)}</span> : null}
            </div>
            <div className="flex flex-wrap gap-x-3 gap-y-0.5 text-[12px]">
              <Link href={`/jobs/${encodeURIComponent(r.job_id)}`} className="font-mono text-accent-text hover:underline">
                {r.job_id}
              </Link>
              <span className="font-mono text-subtle">judge: {scorecardSummary(r.judge)}</span>
            </div>
            {r.note ? <p className="text-[12.5px] text-muted">“{r.note}”</p> : null}
            {r.reason ? <p className="text-[12.5px] text-muted">Reason: “{r.reason}”</p> : null}
            {r.pins.length ? (
              <ul className="space-y-0.5 text-[12px]" aria-label={`Pins in ${roundLabel(r.round)}`}>
                {r.pins.map((p) => (
                  <li key={p.id} className="flex flex-wrap gap-x-2">
                    <span className="font-mono text-subtle">pin {p.id}</span>
                    <span className="text-muted">{p.note ? `“${p.note}”` : "no note"}</span>
                    <span className="font-mono tnum">{pinOutcome(p)}</span>
                  </li>
                ))}
              </ul>
            ) : null}
            {r.child_job ? (
              <p className="text-[12px] text-muted">
                Next round:{" "}
                <Link href={`/jobs/${encodeURIComponent(r.child_job)}`} className="font-mono text-accent-text hover:underline">
                  {r.child_job}
                </Link>
              </p>
            ) : null}
          </li>
        ))}
      </ol>
    </section>
  );
}
