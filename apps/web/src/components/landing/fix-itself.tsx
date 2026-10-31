"use client";

/**
 * "Watch it fix itself": the loop ring (Art E) beside the stored run playing back. The ring's centre steps through the
 * run's own per-round max error as the replay's chart reveals each round; the limit is the run's threshold.
 */
import * as React from "react";
import { fmtNum } from "@/lib/format";
import { usePrefersReducedMotion } from "@/lib/motion";
import { cn } from "@/lib/utils";
import { LoopRing } from "../art/loop-ring";
import { ReplayLoopLazy } from "./replay-loop-lazy";
import { useStoredRun } from "./use-figure-run";

export function FixItself() {
  const { fig, pick, state } = useStoredRun("loop");
  const reduced = usePrefersReducedMotion();
  const [idx, setIdx] = React.useState<number | null>(null);
  const onStep = React.useCallback((frame: string, chartStep: number) => {
    if (frame === "chart") setIdx(Math.max(0, chartStep - 1));
    else if (frame === "photo" || frame === "mask") setIdx(0);
    else setIdx(null);
  }, []);
  const rounds = fig?.rounds ?? [];
  const limit = fig?.limitMm ?? null;
  const shown = idx == null ? rounds.length - 1 : Math.min(idx, rounds.length - 1);
  return (
    <div className="grid grid-cols-1 items-start gap-8 lg:grid-cols-[minmax(0,0.8fr)_minmax(0,1.45fr)] lg:gap-10">
      <div className="space-y-5" data-reveal>
        {rounds.length && limit != null ? (
          <>
            <LoopRing rounds={rounds} index={shown} limitMm={limit} reduced={reduced} className="mx-auto max-w-[360px]" />
            <ol className="flex flex-wrap items-center justify-center gap-1.5 font-mono text-[12px]" aria-label="Max error after each round">
              {rounds.map((r, i) => (
                <li key={r.iter} className="flex items-center gap-1.5">
                  {i > 0 ? <span aria-hidden className="text-subtle">→</span> : null}
                  <span
                    className={cn(
                      "rounded-full border px-2 py-0.5 tnum transition-colors duration-[var(--dur-state)]",
                      r.mm <= limit ? "border-ok-border bg-ok-soft text-ok" : "border-border bg-surface text-fg",
                      i === shown && "ring-2 ring-accent/40",
                    )}
                  >
                    {fmtNum(r.mm)} mm
                  </span>
                </li>
              ))}
            </ol>
            <p className="text-center text-[12.5px] leading-5 text-muted">
              Max error after each round of the recorded run. The dashed green ring is its {fmtNum(limit)} mm limit; the orange ring shrinks as the agent edits and code re-measures.
            </p>
          </>
        ) : (
          <div className={cn("mx-auto aspect-square max-w-[360px] rounded-full border border-dashed border-border-strong", state === "pending" && "animate-pulse")} />
        )}
      </div>
      <div data-reveal style={{ "--reveal-i": 1 } as React.CSSProperties}>
        <ReplayLoopLazy id={pick?.id} onStep={onStep} />
      </div>
    </div>
  );
}
