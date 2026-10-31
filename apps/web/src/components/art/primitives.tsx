/**
 * Drawing primitives shared by the inspection-drawing art: fiducial markers, dimension lines (extension lines,
 * arrowheads, a mono pill label), balloons and a detail circle. Colours come from CSS variables, so every piece follows
 * the light / dark theme. Lines with `className="draw"` are drawn in by CSS when an ancestor has `data-drawn`.
 */
import * as React from "react";
import { markerBits } from "@/lib/drawing";
import { cn } from "@/lib/utils";

/** A stable id for SVG defs (React ids contain characters `url(#…)` does not accept). */
export function useSvgId(prefix: string): string {
  return `${prefix}${React.useId().replace(/[^a-zA-Z0-9_-]/g, "")}`;
}

/** A 4×4 fiducial marker with its one-cell border: 6×6 cells in `--marker` ink on `--marker-bg`. */
export function Marker({ x, y, size, id, className, style }: { x: number; y: number; size: number; id: number; className?: string; style?: React.CSSProperties }) {
  const c = size / 6;
  const bits = markerBits(id);
  return (
    <g className={className} style={style}>
      <rect x={x} y={y} width={size} height={size} fill="var(--marker)" />
      {bits.map((on, i) =>
        on ? null : <rect key={i} x={x + c * (1 + (i % 4))} y={y + c * (1 + Math.floor(i / 4))} width={c + 0.02} height={c + 0.02} fill="var(--marker-bg)" />,
      )}
    </g>
  );
}

/** Arrowhead markers for dimension lines; reference with `url(#${id}-a)`. */
export function ArrowDefs({ id, color = "var(--dim)" }: { id: string; color?: string }) {
  return (
    <defs>
      <marker id={`${id}-a`} viewBox="0 0 10 10" refX="10" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse" markerUnits="userSpaceOnUse">
        <path d="M0 1.5 L10 5 L0 8.5 Z" fill={color} />
      </marker>
    </defs>
  );
}

/** Mono label in a pill, centred on (x, y). Width is estimated from the text (Geist Mono ≈ 0.6 em per glyph). */
export function Pill({
  x,
  y,
  text,
  size = 11,
  tone = "dim",
  className,
}: {
  x: number;
  y: number;
  text: string;
  size?: number;
  tone?: "dim" | "stamp" | "ink" | "ok";
  className?: string;
}) {
  const w = text.length * size * 0.62 + 12;
  const h = size + 9;
  const color = tone === "dim" ? "var(--dim)" : tone === "stamp" ? "var(--stamp)" : tone === "ok" ? "var(--ok)" : "var(--ink)";
  return (
    <g className={className}>
      <rect x={x - w / 2} y={y - h / 2} width={w} height={h} rx={h / 2} fill="var(--screen)" stroke={color} strokeWidth={1} />
      <text x={x} y={y + size * 0.36} textAnchor="middle" fontSize={size} fill={color} className="font-mono tnum" style={{ fontVariantNumeric: "tabular-nums" }}>
        {text}
      </text>
    </g>
  );
}

/**
 * A dimension: dashed extension lines from the feature (`from`) out to the dimension line, a line with arrowheads at both
 * ends, and the value in a pill. `axis` "x" measures horizontally at `at` (a y position), "y" vertically at `at` (an x).
 */
export function Dimension({
  axis,
  a,
  b,
  at,
  from,
  label,
  arrows,
  delayMs = 0,
  className,
}: {
  axis: "x" | "y";
  /** start and end along the axis (svg units) */
  a: number;
  b: number;
  /** position of the dimension line across the axis */
  at: number;
  /** where each extension line starts (the feature edge), across the axis */
  from: [number, number];
  label: React.ReactNode;
  /** arrowhead defs id (ArrowDefs) */
  arrows: string;
  delayMs?: number;
  className?: string;
}) {
  const mid = (a + b) / 2;
  const gap = 3; // extension lines stop short of the part, like on a drawing
  const ext = (p: number, f: number) => {
    const dir = Math.sign(at - f) || 1;
    return axis === "x"
      ? { x1: p, y1: f + gap * dir, x2: p, y2: at + 6 * dir }
      : { x1: f + gap * dir, y1: p, x2: at + 6 * dir, y2: p };
  };
  const line = axis === "x" ? { x1: a, y1: at, x2: b, y2: at } : { x1: at, y1: a, x2: at, y2: b };
  const style = { "--draw-delay": `${delayMs}ms` } as React.CSSProperties;
  return (
    <g className={className}>
      <line {...ext(a, from[0])} stroke="var(--dim)" strokeWidth={0.9} strokeDasharray="3 3" className="draw-fade" style={style} />
      <line {...ext(b, from[1])} stroke="var(--dim)" strokeWidth={0.9} strokeDasharray="3 3" className="draw-fade" style={style} />
      <line
        {...line}
        pathLength={1}
        stroke="var(--dim)"
        strokeWidth={1}
        markerStart={`url(#${arrows}-a)`}
        markerEnd={`url(#${arrows}-a)`}
        className="draw draw-fade"
        style={{ "--draw-delay": `${delayMs + 120}ms` } as React.CSSProperties}
      />
      <g className="draw-fade" style={{ "--draw-delay": `${delayMs + 420}ms` } as React.CSSProperties} transform={axis === "x" ? `translate(${mid} ${at})` : `translate(${at} ${mid})`}>
        {label}
      </g>
    </g>
  );
}

/** A numbered BOM-style balloon with a leader to (tx, ty). */
export function Balloon({
  x,
  y,
  tx,
  ty,
  n,
  active = false,
  className,
}: {
  x: number;
  y: number;
  tx: number;
  ty: number;
  n: number;
  active?: boolean;
  className?: string;
}) {
  const r = 11;
  const d = Math.hypot(tx - x, ty - y) || 1;
  const sx = x + ((tx - x) / d) * r;
  const sy = y + ((ty - y) / d) * r;
  const color = active ? "var(--stamp)" : "var(--ink)";
  return (
    <g className={cn("transition-opacity", className)}>
      <line x1={sx} y1={sy} x2={tx} y2={ty} stroke={color} strokeWidth={0.9} />
      <circle cx={tx} cy={ty} r={2} fill={color} />
      <circle cx={x} cy={y} r={r} fill={active ? "var(--stamp-fill)" : "var(--screen)"} stroke={color} strokeWidth={active ? 1.6 : 1} />
      <text x={x} y={y + 4} textAnchor="middle" fontSize={11.5} fontWeight={600} fill={color} className="font-mono">
        {n}
      </text>
    </g>
  );
}

/** Engineering title block (HTML): a strip of labelled cells, e.g. part · scale · tolerance · sheet. */
export function TitleBlock({ cells, className }: { cells: { k: string; v: React.ReactNode; w?: number }[]; className?: string }) {
  return (
    <dl
      className={cn("grid divide-x divide-border border border-border bg-surface font-mono text-[10.5px] leading-tight", className)}
      style={{ gridTemplateColumns: cells.map((c) => `minmax(0,${c.w ?? 1}fr)`).join(" ") }}
    >
      {cells.map((c) => (
        <div key={c.k} className="min-w-0 px-2 py-1.5">
          <dt className="truncate text-[9.5px] tracking-[0.08em] text-subtle uppercase">{c.k}</dt>
          <dd className="truncate text-fg tnum">{c.v}</dd>
        </div>
      ))}
    </dl>
  );
}
