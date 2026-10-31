"use client";

/**
 * "Every part is a program": the hinge drawing with numbered balloons for the recorded run's real knobs (Art D) above
 * the live knob demo. Hovering a balloon's row highlights the same knob in the demo, whose first tab is that same
 * recorded run's program; registry parts follow.
 */
import dynamic from "next/dynamic";
import * as React from "react";
import { decimalsOf } from "@/lib/count-up";
import { fmtNum, paramLabel } from "@/lib/format";
import { useInView } from "@/lib/motion";
import { CALLOUT_KNOBS, ParamCallouts, type CalloutKnob } from "../art/param-callouts";
import { Skeleton } from "../ui/skeleton";
import { useStoredRun } from "./use-figure-run";

const LiveKnobDemo = dynamic(() => import("./live-knob-demo").then((m) => m.LiveKnobDemo), {
  ssr: false,
  loading: () => <DemoPlaceholder />,
});

function DemoPlaceholder() {
  return (
    <div role="status" className="overflow-hidden rounded-xl border border-border bg-surface shadow-lg" aria-busy="true" aria-label="Loading the live demo">
      <div className="flex items-center gap-1 border-b border-border px-2 py-1.5">
        {[0, 1, 2].map((i) => (
          <Skeleton key={i} className="h-7 w-28" />
        ))}
      </div>
      <div className="grid grid-cols-1 md:h-[456px] md:grid-cols-[minmax(0,1fr)_268px]">
        <div className="aspect-[4/3] bg-[var(--viewer-bg)] bg-dots md:aspect-auto md:h-full" />
        <div className="space-y-4 border-t border-border p-4 md:border-t-0 md:border-l">
          {[0, 1, 2, 3].map((i) => (
            <Skeleton key={i} className="h-14" />
          ))}
        </div>
      </div>
    </div>
  );
}

/** Knobs the demo lists first: the one the ghost cursor drags (a size), then the ones the drawing names. */
const DEMO_PREFER = ["length", "knuckle_count", "hole_d", "corner_radius", "leaf_width", "pin_d"] as const;

export function ProgramSection() {
  const { fig, pick } = useStoredRun("figure");
  const [active, setActive] = React.useState<string | null>(null);
  const near = useInView<HTMLDivElement>({ rootMargin: "400px", threshold: 0 });
  const knobs: CalloutKnob[] = React.useMemo(() => {
    if (!fig) return [];
    return CALLOUT_KNOBS.flatMap((name) => {
      const p = fig.params.find((x) => x.name === name);
      const v = fig.values[name];
      if (!p || v == null) return [];
      const dp = p.topology ? 0 : decimalsOf(String(p.step));
      const unit = p.unit === "deg" ? "°" : p.unit ? ` ${p.unit}` : "";
      return [{ name, label: paramLabel(p.name, p.label), value: `${fmtNum(v, dp)}${unit}` }];
    });
  }, [fig]);
  return (
    <div className="space-y-8">
      {knobs.length >= 2 ? (
        <figure className="rounded-xl border border-border bg-surface p-4 sm:p-6" data-reveal>
          <ParamCallouts knobs={knobs} active={active} onActive={setActive} />
          <figcaption className="mt-3 font-mono text-[11px] leading-4 text-subtle">
            Fig. 7 · a hinge leaf drawn with the knobs of the recorded run&apos;s program; names and values are the program&apos;s own. Hover a row to find it in the demo.
          </figcaption>
        </figure>
      ) : null}
      <div ref={near.ref} data-reveal style={{ "--reveal-i": 1 } as React.CSSProperties}>
        {near.seen ? <LiveKnobDemo jobId={pick?.id ?? null} prefer={DEMO_PREFER} highlight={active} /> : <DemoPlaceholder />}
      </div>
    </div>
  );
}
