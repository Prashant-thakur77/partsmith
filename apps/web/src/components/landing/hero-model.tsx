"use client";

/**
 * The landing hero: the verified battery cover from a recorded live run, in real 3D, with one real knob. Each knob position is
 * a separate mesh baked ahead of time by the part's CadQuery program; nothing is scaled in the browser.
 */
import { useQuery } from "@tanstack/react-query";
import { ArrowUpRight, Hand } from "lucide-react";
import Link from "next/link";
import * as React from "react";
import { BakedMesh } from "@/components/viewer/baked-mesh";
import { defaultStepIndex, fetchBakedIndex, largestSizeMm } from "@/lib/baked-models";
import { fmtNum } from "@/lib/format";
import { Badge } from "../ui/badge";
import { ErrorState } from "../ui/error-state";
import { Skeleton } from "../ui/skeleton";
import { Slider } from "../ui/slider";

const PART = "battery-cover-45mm";
const KNOB = "length";

export function HeroModel() {
  const q = useQuery({ queryKey: ["baked-index"], queryFn: ({ signal }) => fetchBakedIndex(signal), staleTime: Infinity });
  const part = q.data?.parts[PART];
  const knob = part?.knobs[KNOB];
  const [picked, setPicked] = React.useState<number | null>(null);

  // the other positions, fetched once someone reaches for the knob
  const preload = React.useCallback(() => {
    if (!knob) return;
    void import("@/components/viewer/baked-mesh-scene").then((m) => m.preloadMeshes(knob.steps.map((s) => s.file)));
  }, [knob]);

  if (q.isError) return <ErrorState error={q.error} what="the 3D model" onRetry={() => void q.refetch()} />;
  if (!part || !knob) {
    return (
      <div role="status" aria-label="Loading the 3D model">
        <Skeleton className="h-[476px] rounded-xl" />
      </div>
    );
  }
  const index = picked ?? defaultStepIndex(knob);
  const step = knob.steps[index]!;
  const [x, y, z] = step.size_mm;
  const size = `${fmtNum(x)} × ${fmtNum(y)} × ${fmtNum(z)} mm`;
  return (
    <figure className="overflow-hidden rounded-xl border border-border bg-surface shadow-md">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border px-4 py-2.5">
        <figcaption className="text-[13px] font-medium">{part.title}</figcaption>
        <div className="flex flex-wrap items-center gap-1.5">
          {part.status === "verified" ? <Badge tone="ok">verified · {fmtNum(part.max_error_mm ?? 0)} mm</Badge> : <Badge tone="warn">{part.status}</Badge>}
          <Badge tone="neutral">recorded run · rendered sample</Badge>
        </div>
      </div>
      <div className="relative bg-paper">
        <BakedMesh
          file={step.file}
          sizeMm={largestSizeMm(knob)}
          label={`3D model of the ${part.title} at ${knob.label.toLowerCase()} ${fmtNum(step.value)} ${knob.unit}. Drag to turn it.`}
          className="h-[240px] w-full sm:h-[280px]"
        />
        <span className="pointer-events-none absolute right-3 bottom-2 inline-flex items-center gap-1 text-[11.5px] text-subtle">
          <Hand className="size-3.5" aria-hidden /> drag to turn
        </span>
      </div>
      <div className="space-y-3 border-t border-border p-4">
        <div className="flex items-baseline justify-between gap-3">
          <p className="text-[13px] font-medium">Try the knob: {knob.label.toLowerCase()}</p>
          <span className="shrink-0 whitespace-nowrap font-mono text-[15px] tnum">
            {fmtNum(step.value)} {knob.unit}
          </span>
        </div>
        <div onPointerDown={preload} onFocus={preload}>
          <Slider
            aria-label={knob.label}
            aria-valuetext={`${fmtNum(step.value)} ${knob.unit}`}
            value={[index]}
            min={0}
            max={knob.steps.length - 1}
            step={1}
            onValueChange={([v]) => setPicked(v ?? 0)}
          />
        </div>
        <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1 text-[12px] text-muted">
          <span>
            Size <span className="font-mono tnum">{size}</span> · {fmtNum(step.triangles, 0)} triangles
          </span>
          <Link href="/playground" className="inline-flex items-center gap-0.5 hover:text-fg">
            Every knob, rebuilt on the server <ArrowUpRight className="size-3" aria-hidden />
          </Link>
        </div>
        <p className="text-[11.5px] leading-4 text-subtle">
          Real CadQuery output: each position is a mesh the part&apos;s program baked ahead of time. The browser does not run CAD. The
          part comes from a recorded live run on a rendered sample photo; real phone captures come next.
        </p>
      </div>
    </figure>
  );
}
