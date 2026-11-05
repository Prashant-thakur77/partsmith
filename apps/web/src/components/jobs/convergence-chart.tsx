"use client";

import { CartesianGrid, LabelList, Line, LineChart, ReferenceArea, ReferenceDot, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { fmtNum } from "@/lib/format";

type Point = { iter: number; hausdorff_mm: number | null };

const NICE = [0.1, 0.2, 0.25, 0.5, 1, 2, 2.5, 5, 10, 20, 25, 50, 100];

/**
 * Outline gap (Hausdorff, mm) per iteration — the silhouette part of the max error (a round's max error can be larger
 * when a measured size is further off). The green band is the verifier's pass zone (0 … threshold); every point carries
 * its value. Data and threshold come from the job's events / verification record. When the finished job shipped an
 * earlier round (`keptIter`), that point is ringed and labelled "kept" and the later points read as discarded tries.
 */
export function ConvergenceChart({ data, threshold, height = 160, keptIter = null }: { data: Point[]; threshold: number | null; height?: number; keptIter?: number | null }) {
  const pts = data.filter((d): d is { iter: number; hausdorff_mm: number } => d.hausdorff_mm != null);
  if (pts.length === 0) {
    return (
      <div className="flex items-center justify-center rounded-md border border-dashed border-border text-[12px] text-subtle" style={{ height }}>
        The error curve appears after the first verify.
      </div>
    );
  }
  const max = Math.max(...pts.map((p) => p.hausdorff_mm), threshold ?? 0);
  const step = NICE.find((s) => (max * 1.2) / s <= 4) ?? 200;
  const top = Math.max(step, Math.ceil((max * 1.2) / step) * step);
  const yTicks = Array.from({ length: Math.round(top / step) + 1 }, (_, i) => Number((i * step).toFixed(3)));
  const iters = pts.map((p) => p.iter);
  const lo = Math.min(...iters);
  const hi = Math.max(...iters);
  const xTicks = Array.from({ length: hi - lo + 1 }, (_, i) => lo + i);
  const dp = top < 2 ? 2 : 1;
  const kept = keptIter != null ? pts.find((p) => p.iter === keptIter) ?? null : null;
  const discardedAfter = kept != null && pts.some((p) => p.iter > kept.iter);
  const tag = (iter: number) => (kept == null ? "" : iter === kept.iter ? " (kept)" : iter > kept.iter ? " (discarded)" : "");
  const summary = pts.map((p) => `iteration ${p.iter}: ${fmtNum(p.hausdorff_mm)} mm${tag(p.iter)}`).join(", ");
  return (
    <figure className="m-0">
      <div style={{ height }} aria-hidden>
        <ResponsiveContainer width="100%" height="100%">
          <LineChart accessibilityLayer={false} data={pts} margin={{ top: 18, right: 18, bottom: 0, left: 0 }}>
            <CartesianGrid stroke="var(--border)" vertical={false} />
            {threshold != null ? <ReferenceArea y1={0} y2={threshold} fill="var(--ok)" fillOpacity={0.09} stroke="none" ifOverflow="hidden" /> : null}
            {threshold != null ? (
              <ReferenceLine
                y={threshold}
                stroke="var(--ok)"
                strokeDasharray="4 3"
                label={{ value: `pass ≤ ${fmtNum(threshold)} mm`, position: "insideBottomLeft", fill: "var(--ok)", fontSize: 10, dy: -2 }}
              />
            ) : null}
            <XAxis
              dataKey="iter"
              type="number"
              domain={[lo - 0.4, hi + 0.4]}
              ticks={xTicks}
              allowDecimals={false}
              tickFormatter={(v: number) => `#${v}`}
              tick={{ fontSize: 11, fill: "var(--fg-subtle)", fontFamily: "var(--font-mono)" }}
              tickLine={false}
              axisLine={{ stroke: "var(--border)" }}
            />
            <YAxis
              domain={[0, top]}
              ticks={yTicks}
              tick={{ fontSize: 11, fill: "var(--fg-subtle)", fontFamily: "var(--font-mono)" }}
              tickLine={false}
              axisLine={false}
              width={44}
              tickFormatter={(v: number) => fmtNum(v, dp)}
            />
            <Tooltip
              cursor={{ stroke: "var(--border-strong)" }}
              contentStyle={{ background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 6, fontSize: 12 }}
              labelStyle={{ color: "var(--fg)" }}
              itemStyle={{ color: "var(--fg)" }}
              labelFormatter={(v) => `iteration ${v}${tag(Number(v))}`}
              formatter={(v) => [`${fmtNum(Number(v))} mm`, "outline gap (Hausdorff)"]}
            />
            <Line
              type="linear"
              dataKey="hausdorff_mm"
              stroke="var(--accent)"
              strokeWidth={2}
              dot={{ r: 3.5, fill: "var(--surface)", stroke: "var(--accent)", strokeWidth: 2 }}
              activeDot={{ r: 4.5 }}
              isAnimationActive
              animationDuration={500}
            >
              <LabelList dataKey="hausdorff_mm" position="top" offset={8} formatter={(v: unknown) => fmtNum(Number(v))} style={{ fontSize: 10.5, fill: "var(--fg)", fontFamily: "var(--font-mono)" }} />
            </Line>
            {kept && discardedAfter ? (
              <ReferenceDot
                x={kept.iter}
                y={kept.hausdorff_mm}
                r={7}
                fill="none"
                stroke="var(--ok)"
                strokeWidth={2}
                label={{ value: "kept", position: "right", fill: "var(--ok)", fontSize: 10.5, fontWeight: 600, dx: 2, dy: 9 }}
              />
            ) : null}
          </LineChart>
        </ResponsiveContainer>
      </div>
      {discardedAfter ? (
        <p className="mt-1 text-[11.5px] text-muted">
          Iteration #{kept!.iter} is the result. Later points are tries that were discarded.
        </p>
      ) : null}
      <figcaption className="sr-only">Outline gap (Hausdorff) by iteration: {summary}.</figcaption>
    </figure>
  );
}
