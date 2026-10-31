/**
 * Art C — the verifier's overlay as a drawing: the photo's mask (orange) with the model's outline (ink) laid over it, a
 * dashed circle at the worst point, and a leader to "DETAIL A" at 3× where the gap and the limit are printed with a green
 * pass band (± limit around the photo's edge). The outline, worst point, gap and limit are the run's own numbers; the
 * model outline is drawn as the photo outline offset by the measured gap (an illustration, captioned as such).
 */
import * as React from "react";
import { fitPoints, offsetOutline, pathOf, type Pt } from "@/lib/drawing";
import { fmtNum } from "@/lib/format";
import { cn } from "@/lib/utils";
import { Pill, useSvgId } from "./primitives";

const W = 640;
const H = 400;
const MAIN = { x: 28, y: 70, w: 330, h: 250 };
const DET = { cx: 500, cy: 176, r: 104 };
const MAG = 3;

export function VerifyOverlay({
  outline,
  worst,
  gapMm,
  limitMm,
  passed,
  drawn = true,
  className,
}: {
  outline: Pt[];
  worst: Pt | null;
  gapMm: number;
  limitMm: number;
  passed: boolean;
  drawn?: boolean;
  className?: string;
}) {
  const uid = useSvgId("vo");
  const f = fitPoints(outline, MAIN, 8);
  const model = offsetOutline(outline, Math.min(gapMm, 3));
  const w = worst ?? outline[0] ?? [0, 0];
  const [wx, wy] = f.map(w);
  const S = f.scale * MAG; // detail scale, svg units per mm
  const id: (p: Pt) => [number, number] = (p) => [p[0], p[1]];
  const photoPath = pathOf(outline, id);
  const modelPath = pathOf(model, id);
  // leader: from the worst-point circle towards the detail circle
  const dx = DET.cx - wx;
  const dy = DET.cy - wy;
  const dl = Math.hypot(dx, dy) || 1;
  const l0 = [wx + (dx / dl) * 18, wy + (dy / dl) * 18];
  const l1 = [DET.cx - (dx / dl) * DET.r, DET.cy - (dy / dl) * DET.r];
  const tone = passed ? "var(--ok)" : "var(--bad)";
  return (
    <svg
      viewBox={`0 0 ${W} ${H}`}
      className={cn("h-auto w-full", className)}
      role="img"
      aria-label={`The model's outline over the photo's outline. Detail A at ${MAG}×: the biggest gap is ${fmtNum(gapMm)} mm against a ${fmtNum(limitMm)} mm limit — ${passed ? "inside" : "outside"} the pass band.`}
      data-drawn={drawn ? "" : undefined}
    >
      <defs>
        <clipPath id={`${uid}-clip`}>
          <circle cx={DET.cx} cy={DET.cy} r={DET.r - 1} />
        </clipPath>
        <pattern id={`${uid}-dots`} width="8" height="8" patternUnits="userSpaceOnUse">
          <circle cx="4" cy="4" r="0.7" fill="var(--screen-dot)" />
        </pattern>
      </defs>
      <rect x="4" y="4" width={W - 8} height={H - 8} rx="14" fill="var(--screen)" stroke="var(--ink)" strokeWidth="1.25" />
      <rect x="14" y="14" width={W - 28} height={H - 28} rx="6" fill={`url(#${uid}-dots)`} />

      {/* main view */}
      <path d={pathOf(outline, f.map)} fill="var(--stamp-fill)" stroke="var(--stamp)" strokeWidth="1" strokeOpacity="0.55" />
      <path d={pathOf(model, f.map)} pathLength={1} fill="none" stroke="var(--ink)" strokeWidth="1.25" strokeLinejoin="round" className="draw" />
      <circle cx={wx} cy={wy} r={18} fill="none" stroke={tone} strokeWidth="1.25" strokeDasharray="4 3" className="draw-fade" style={{ "--draw-delay": "500ms" } as React.CSSProperties} />
      <line x1={l0[0]} y1={l0[1]} x2={l1[0]} y2={l1[1]} pathLength={1} stroke="var(--ink)" strokeWidth="0.9" className="draw" style={{ "--draw-delay": "650ms" } as React.CSSProperties} />
      <text x={wx} y={wy - 24} textAnchor="middle" fontSize="11" fontWeight="600" fill="var(--ink)" className="font-mono draw-fade" style={{ "--draw-delay": "650ms" } as React.CSSProperties}>
        A
      </text>

      {/* detail A, 3× */}
      <g className="draw-fade" style={{ "--draw-delay": "800ms" } as React.CSSProperties}>
        <circle cx={DET.cx} cy={DET.cy} r={DET.r} fill="var(--screen)" stroke="var(--ink)" strokeWidth="1.25" />
        <g clipPath={`url(#${uid}-clip)`}>
          <g transform={`translate(${DET.cx} ${DET.cy}) scale(${S} ${-S}) translate(${-w[0]} ${-w[1]})`}>
            <path d={photoPath} fill="none" stroke="var(--pass)" strokeWidth={2 * limitMm} strokeLinejoin="round" />
            <path d={photoPath} fill="var(--stamp-fill)" stroke="var(--stamp)" strokeWidth={1.2} vectorEffect="non-scaling-stroke" />
            <path d={modelPath} fill="none" stroke="var(--ink)" strokeWidth={1.6} vectorEffect="non-scaling-stroke" strokeLinejoin="round" />
            <circle cx={w[0]} cy={w[1]} r={2.4 / S} fill={tone} />
          </g>
        </g>
        <text x={DET.cx} y={DET.cy + DET.r + 20} textAnchor="middle" fontSize="10.5" letterSpacing="0.14em" fill="var(--fg-muted)" className="font-mono">
          DETAIL A · {MAG}:1
        </text>
        <Pill x={DET.cx} y={DET.cy + DET.r + 44} text={`gap ${fmtNum(gapMm)} mm · limit ${fmtNum(limitMm)} mm`} tone={passed ? "ok" : "stamp"} size={11} />
      </g>

      {/* legend */}
      <g className="font-mono" fontSize="10" fill="var(--fg-muted)">
        <rect x={34} y={H - 52} width={12} height={8} fill="var(--stamp-fill)" stroke="var(--stamp)" strokeWidth="0.8" />
        <text x={52} y={H - 45}>photo mask</text>
        <line x1={130} x2={146} y1={H - 48} y2={H - 48} stroke="var(--ink)" strokeWidth="1.4" />
        <text x={152} y={H - 45}>model outline (drawn offset by the gap)</text>
        <rect x={34} y={H - 36} width={12} height={8} fill="var(--pass)" />
        <text x={52} y={H - 29}>pass band ± limit</text>
      </g>
    </svg>
  );
}
