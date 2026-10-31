/**
 * Art A — "Fig. 1": the part lying on the screen mat, as an inspection drawing. A rounded screen with an 8 px dot grid,
 * fiducial markers in the corners and along the top, the measured outline (orange 12 %, 1.5 px ink) and dimension lines
 * whose labels are passed in from real run data. Without an outline it draws a generic broken latch with no numbers.
 */
import * as React from "react";
import { fitPoints, pathOf, type Pt } from "@/lib/drawing";
import { cn } from "@/lib/utils";
import { ArrowDefs, Dimension, Marker, Pill } from "./primitives";

export const MAT_W = 640;
export const MAT_H = 400;
/** The part's drawing area inside the screen (svg units). */
export const PART_BOX = { x: 136, y: 96, w: 318, h: 176 };

const CORNER = 42;
const CORNERS: [number, number][] = [
  [28, 28],
  [MAT_W - 28 - CORNER, 28],
  [28, MAT_H - 28 - CORNER],
  [MAT_W - 28 - CORNER, MAT_H - 28 - CORNER],
];
const STRIP = Array.from({ length: 9 }, (_, i) => [100 + i * 50, 39] as [number, number]);

/** The lit screen: rounded rect, dot grid, corner markers and the strip along the top. `lit` plays the ring-light once. */
export function MatScreen({ lit = false, children, uid }: { lit?: boolean; children?: React.ReactNode; uid: string }) {
  const all = [...CORNERS.map((p, i) => ({ p, s: CORNER, id: i })), ...STRIP.map((p, i) => ({ p, s: 20, id: 10 + i }))];
  // ring order: corners clockwise, then the strip left to right
  const order = [0, 1, 3, 2];
  return (
    <>
      <defs>
        <pattern id={`${uid}-dots`} width="8" height="8" patternUnits="userSpaceOnUse">
          <circle cx="4" cy="4" r="0.7" fill="var(--screen-dot)" />
        </pattern>
      </defs>
      <rect x="4" y="4" width={MAT_W - 8} height={MAT_H - 8} rx="14" fill="var(--screen)" stroke="var(--ink)" strokeWidth="1.25" />
      <rect x="14" y="14" width={MAT_W - 28} height={MAT_H - 28} rx="6" fill={`url(#${uid}-dots)`} />
      {all.map(({ p, s, id }, i) => (
        <Marker
          key={id}
          x={p[0]}
          y={p[1]}
          size={s}
          id={id}
          className={lit ? "motion-safe:animate-[ring-light_900ms_var(--ease-draft)_both]" : undefined}
          style={lit ? { animationDelay: `${(i < 4 ? order.indexOf(i) : 4 + (i - 4) * 0.5) * 140}ms` } : undefined}
        />
      ))}
      {children}
    </>
  );
}

/** Generic broken latch (no numbers): rounded body 180×56, a hole r = 10 and a jagged right end. */
export function LatchGlyph({ cx = MAT_W / 2, cy = 184 }: { cx?: number; cy?: number }) {
  const x0 = cx - 90;
  const y0 = cy - 28;
  const d = `M${x0 + 14} ${y0} H${x0 + 158} L${x0 + 166} ${y0 + 9} L${x0 + 159} ${y0 + 17} L${x0 + 172} ${y0 + 26} L${x0 + 162} ${y0 + 35} L${x0 + 176} ${y0 + 45} L${x0 + 168} ${y0 + 56} H${x0 + 14} A14 14 0 0 1 ${x0} ${y0 + 42} V${y0 + 14} A14 14 0 0 1 ${x0 + 14} ${y0} Z`;
  return (
    <g>
      <path d={d} fill="var(--stamp-fill)" stroke="var(--ink)" strokeWidth="1.5" strokeLinejoin="round" />
      <circle cx={x0 + 38} cy={cy} r="10" fill="var(--screen)" stroke="var(--ink)" strokeWidth="1.5" />
    </g>
  );
}

export type PartDrawing = {
  outline: Pt[];
  holes: { center: Pt; diameterMm: number }[];
};

/**
 * The measured part with its dimensions. `labels` are the printed values (already formatted, maybe mid count-up);
 * `drawn` toggles the line drawing; `dims` shows the dimension layer.
 */
export function PartOnMat({
  part,
  labels,
  drawn,
  dims,
  uid,
  className,
  box = PART_BOX,
}: {
  part: PartDrawing;
  labels: { length?: string | null; width?: string | null; hole?: string | null };
  drawn: boolean;
  dims: boolean;
  uid: string;
  className?: string;
  box?: { x: number; y: number; w: number; h: number };
}) {
  const f = fitPoints(part.outline, box);
  const b = f.bbox;
  const hole = part.holes[0];
  const hc = hole ? f.map(hole.center) : null;
  const hr = hole ? (hole.diameterMm / 2) * f.scale : 0;
  return (
    <g className={className}>
      <ArrowDefs id={uid} />
      <g data-drawn={drawn ? "" : undefined}>
        <path d={pathOf(part.outline, f.map)} fill="var(--stamp-fill)" stroke="none" className="draw-fade" />
        <path d={pathOf(part.outline, f.map)} pathLength={1} fill="none" stroke="var(--ink)" strokeWidth="1.5" strokeLinejoin="round" className="draw" style={{ "--draw-delay": "0ms", transitionDuration: "var(--dur-hero-step)" } as React.CSSProperties} />
        {part.holes.map((h, i) => {
          const [x, y] = f.map(h.center);
          return (
            <circle
              key={i}
              cx={x}
              cy={y}
              r={(h.diameterMm / 2) * f.scale}
              pathLength={1}
              fill="var(--screen)"
              stroke="var(--ink)"
              strokeWidth="1.25"
              className="draw"
              style={{ "--draw-delay": `${500 + i * 90}ms` } as React.CSSProperties}
            />
          );
        })}
      </g>
      <g data-drawn={dims ? "" : undefined}>
        {labels.length ? (
          <Dimension axis="x" a={b.x} b={b.x + b.w} at={b.y + b.h + 30} from={[b.y + b.h, b.y + b.h]} arrows={uid} label={<Pill x={0} y={0} text={labels.length} />} />
        ) : null}
        {labels.width ? (
          <Dimension
            axis="y"
            a={b.y}
            b={b.y + b.h}
            at={b.x + b.w + 30}
            from={[b.x + b.w, b.x + b.w]}
            arrows={uid}
            delayMs={160}
            label={<Pill x={0} y={0} text={labels.width} />}
          />
        ) : null}
        {hc && labels.hole ? (
          <g>
            <line
              x1={hc[0] - hr * 0.72}
              y1={hc[1] - hr * 0.72}
              x2={hc[0] - 34}
              y2={b.y - 22}
              pathLength={1}
              stroke="var(--dim)"
              strokeWidth={1}
              markerStart={`url(#${uid}-a)`}
              className="draw draw-fade"
              style={{ "--draw-delay": "320ms" } as React.CSSProperties}
            />
            <line x1={hc[0] - 34} y1={b.y - 22} x2={hc[0] - 52} y2={b.y - 22} stroke="var(--dim)" strokeWidth={1} className="draw-fade" style={{ "--draw-delay": "520ms" } as React.CSSProperties} />
            <g className="draw-fade" style={{ "--draw-delay": "640ms" } as React.CSSProperties}>
              <Pill x={hc[0] - 52 - (labels.hole.length * 11 * 0.62 + 12) / 2} y={b.y - 22} text={labels.hole} />
            </g>
          </g>
        ) : null}
      </g>
    </g>
  );
}

/** Static Art A (no data, no numbers): the mat with the generic latch. For pages that only need the picture. */
export function MatFigureStatic({ className, title, uid = "matstatic" }: { className?: string; title?: string; uid?: string }) {
  return (
    <svg viewBox={`0 0 ${MAT_W} ${MAT_H}`} className={cn("h-auto w-full", className)} role={title ? "img" : undefined} aria-hidden={title ? undefined : true} aria-label={title}>
      <MatScreen uid={uid}>
        <LatchGlyph />
      </MatScreen>
    </svg>
  );
}
