"use client";

import { CartesianGrid, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { fmtNum } from "@/lib/format";

type Point = { iter: number; hausdorff_mm: number | null };

/** Max error (Hausdorff, mm) per iteration with the verifier's pass threshold. Data and threshold come from job events. */
export function ConvergenceChart({ data, threshold, height = 150 }: { data: Point[]; threshold: number | null; height?: number }) {
  const pts = data.filter((d) => d.hausdorff_mm != null);
  if (pts.length === 0) {
    return (
      <div className="flex items-center justify-center rounded-md border border-dashed border-border text-[12px] text-subtle" style={{ height }}>
        The error curve appears after the first verify.
      </div>
    );
  }
  const max = Math.max(...pts.map((p) => p.hausdorff_mm!), threshold ?? 0);
  const step = [0.1, 0.2, 0.25, 0.5, 1, 2, 5, 10, 20, 50].find((s) => max / s <= 5) ?? 100;
  const top = Math.ceil((max * 1.08) / step) * step;
  const ticks = Array.from({ length: Math.round(top / step) + 1 }, (_, i) => Number((i * step).toFixed(2)));
  const summary = pts.map((p) => `iteration ${p.iter}: ${fmtNum(p.hausdorff_mm!)} mm`).join(", ");
  return (
    <figure className="m-0">
      <div style={{ height }} aria-hidden>
        <ResponsiveContainer width="100%" height="100%">
          <LineChart accessibilityLayer={false} data={pts} margin={{ top: 8, right: 12, bottom: 0, left: 0 }}>
            <CartesianGrid stroke="var(--border)" strokeDasharray="0" vertical={false} />
            <XAxis
              dataKey="iter"
              type="number"
              domain={["dataMin", "dataMax"]}
              allowDecimals={false}
              tick={{ fontSize: 11, fill: "var(--fg-subtle)", fontFamily: "var(--font-mono)" }}
              tickLine={false}
              axisLine={{ stroke: "var(--border)" }}
            />
            <YAxis
              domain={[0, top]}
              ticks={ticks}
              tick={{ fontSize: 11, fill: "var(--fg-subtle)", fontFamily: "var(--font-mono)" }}
              tickLine={false}
              axisLine={false}
              width={44}
              tickFormatter={(v: number) => fmtNum(v, step < 0.5 ? 2 : 1)}
            />
            {threshold != null ? (
              <ReferenceLine
                y={threshold}
                stroke="var(--ok)"
                strokeDasharray="4 3"
                label={{ value: `pass ≤ ${fmtNum(threshold)} mm`, position: "insideBottomLeft", fill: "var(--ok)", fontSize: 10 }}
              />
            ) : null}
            <Tooltip
              cursor={{ stroke: "var(--border-strong)" }}
              contentStyle={{ background: "var(--surface)", border: "1px solid var(--border)", borderRadius: 6, fontSize: 12 }}
              labelFormatter={(v) => `iteration ${v}`}
              formatter={(v) => [`${fmtNum(Number(v))} mm`, "max error"]}
            />
            <Line
              type="monotone"
              dataKey="hausdorff_mm"
              stroke="var(--accent)"
              strokeWidth={2}
              dot={{ r: 3, fill: "var(--surface)", stroke: "var(--accent)", strokeWidth: 2 }}
              activeDot={{ r: 4 }}
              isAnimationActive
              animationDuration={500}
            />
          </LineChart>
        </ResponsiveContainer>
      </div>
      <figcaption className="sr-only">Max error by iteration: {summary}.</figcaption>
    </figure>
  );
}
