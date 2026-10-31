import { Gavel } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Eyebrow } from "@/components/ui/card";
import { ModeBadge } from "@/components/ui/provenance";
import type { Judge } from "@/lib/api-types";
import { CRITERIA, judgeModeLine, scoreTone, type JudgeRun } from "@/lib/review";
import { cn } from "@/lib/utils";

const BAR: Record<"ok" | "warn" | "bad", string> = { ok: "bg-ok", warn: "bg-warn", bad: "bg-bad" };

function ScoreBar({ score }: { score: number }) {
  const tone = scoreTone(score);
  return (
    <span className="flex gap-0.5" role="img" aria-label={`${score} out of 5`}>
      {[1, 2, 3, 4, 5].map((i) => (
        <span key={i} className={cn("h-1.5 w-4 rounded-full", i <= score ? BAR[tone] : "bg-surface-3")} aria-hidden />
      ))}
    </span>
  );
}

/** The judge's 1–5 scorecard and vetoes. Advice only: pass/fail is the verifier's, shown elsewhere. */
export function JudgeScorecard({ judge, ran, className }: { judge: Judge | null | undefined; ran?: JudgeRun | null; className?: string }) {
  const by = new Map((judge?.scores ?? []).map((s) => [s.criterion, s]));
  const modeLine = judgeModeLine(judge, ran);
  const mode = judge?.mode ?? ran?.mode ?? null;
  const model = judge?.model ?? ran?.model ?? null;
  return (
    <section className={cn("space-y-3 rounded-lg border border-border bg-surface p-4", className)} aria-label="Judge scorecard">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <Eyebrow className="flex items-center gap-1.5">
          <Gavel className="size-3.5" aria-hidden /> Judge scorecard
        </Eyebrow>
        {mode || model ? (
          <span className="flex flex-wrap items-center gap-1.5">
            {model && mode !== "mock" ? (
              <Badge tone="neutral" className="font-mono">
                {model}
              </Badge>
            ) : null}
            {mode ? <ModeBadge mode={mode} /> : null}
          </span>
        ) : null}
      </div>
      {modeLine ? (
        <p className="text-[12.5px] font-medium text-fg" data-testid="judge-mode">
          {modeLine}
          {mode === "mock" ? <span className="font-normal text-muted"> — fixed rules on what code measured; no model looked at the photo or the render.</span> : null}
        </p>
      ) : null}
      <p className="text-[12px] leading-5 text-subtle">Advice from the judge. Pass/fail comes from the measurements.</p>
      {!judge ? (
        <p className="text-[13px] text-muted">
          {ran
            ? "No scorecard was saved for this job (this run recorded vetoes only); any veto the judge raised is in the verifier's record."
            : "No scorecard for this job. The judge did not run or was not reachable."}
        </p>
      ) : (
        <>
          {judge.scores.length ? (
            <ul className="space-y-2.5" aria-label="Scores">
              {CRITERIA.map((c) => {
                const s = by.get(c.id);
                return (
                  <li key={c.id} className="space-y-0.5">
                    <div className="flex items-center justify-between gap-3">
                      <span className="text-[13px] font-medium">{c.label}</span>
                      <span className="flex items-center gap-2">
                        {s ? (
                          <>
                            <ScoreBar score={s.score} />
                            <span className="w-7 text-right font-mono text-[12px] text-muted tnum">{s.score}/5</span>
                          </>
                        ) : (
                          <span className="text-[12px] text-subtle">not scored</span>
                        )}
                      </span>
                    </div>
                    {s?.reason ? <p className="text-[12px] leading-5 text-muted">{s.reason}</p> : null}
                  </li>
                );
              })}
            </ul>
          ) : (
            <p className="text-[13px] text-muted">The judge gave no scores.</p>
          )}
          {judge.vetoes.length ? (
            <div className="space-y-1.5 border-t border-border pt-3">
              <Eyebrow>Vetoes</Eyebrow>
              <ul className="space-y-1.5">
                {judge.vetoes.map((v, i) => (
                  <li key={`${v.feature}-${i}`} className="flex items-start gap-2 text-[12.5px] leading-5">
                    <Badge tone={v.severity === "blocking" ? "bad" : "warn"}>{v.severity}</Badge>
                    <span>
                      <span className="font-mono">{v.feature}</span> <span className="text-muted">{v.issue}</span>
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
          {judge.notes ? <p className="border-t border-border pt-3 text-[12px] leading-5 text-muted">{judge.notes}</p> : null}
        </>
      )}
    </section>
  );
}
