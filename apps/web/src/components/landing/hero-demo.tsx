"use client";

import dynamic from "next/dynamic";
import { Skeleton } from "../ui/skeleton";

/**
 * The live knob demo is interactive-only (three.js, knobs, re-bakes), so its code loads after the page is interactive.
 * The placeholder has the demo's exact footprint, so nothing shifts when it arrives.
 */
const LiveKnobDemo = dynamic(() => import("./live-knob-demo").then((m) => m.LiveKnobDemo), {
  ssr: false,
  loading: () => (
    <div className="overflow-hidden rounded-xl border border-border bg-surface shadow-lg" aria-busy="true" aria-label="Loading the live demo">
      <div className="flex items-center gap-1 border-b border-border px-2 py-1.5">
        {[0, 1, 2].map((i) => (
          <Skeleton key={i} className="h-7 w-28" />
        ))}
      </div>
      <div className="grid md:h-[456px] md:grid-cols-[minmax(0,1fr)_268px]">
        <div className="aspect-[4/3] bg-[var(--viewer-bg)] bg-dots md:aspect-auto md:h-full" />
        <div className="space-y-4 border-t border-border p-4 md:border-t-0 md:border-l">
          {[0, 1, 2, 3].map((i) => (
            <Skeleton key={i} className="h-14" />
          ))}
        </div>
      </div>
    </div>
  ),
});

export function HeroDemo() {
  return <LiveKnobDemo />;
}
