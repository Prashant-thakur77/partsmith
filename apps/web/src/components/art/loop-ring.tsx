/**
 * Art E — the loop as a ring: photo → millimetres → code → verify and back. In the centre, the round's max error is a
 * circle that shrinks round by round; the dashed green circle is the pass limit. Values and the limit are props from a
 * stored run; `index` picks the round shown (the landing steps it).
 */
import * as React from "react";
import { arcPath, gaugeRadius, onCircle } from "@/lib/drawing";
import { fmtNum } from "@/lib/format";
import { cn } from "@/lib/utils";
import { ArrowDefs, useSvgId } from "./primitives";

const C = 200;
const R = 152;
const STATIONS = ["photo", "mm", "code", "verify"] as const;

export function LoopRing({
  rounds,
  index,
  limitMm,
  className,
  reduced = false,
}: {
  rounds: { iter: number; mm: number }[];
  index: number;
  limitMm: number;
  className?: string;
  reduced?: boolean;
}) {
  const uid = useSvgId("ring");
  const cur = rounds[Math.max(0, Math.min(rounds.length - 1, index))];
  const max = Math.max(limitMm * 1.6, ...rounds.map((r) => r.mm));
  const rE = gaugeRadius(cur?.mm ?? 0, max, 48, 104);
  const rT = gaugeRadius(limitMm, max, 48, 104);
  const pass = cur ? cur.mm <= limitMm : false;
  const ease = reduced ? "120ms" : "var(--dur-draw) var(--ease-draft)";
  return (
    <svg viewBox="0 0 400 400" className={cn("h-auto w-full", className)} role="img" aria-label={`The fix loop. Round ${cur?.iter ?? "—"}: max error ${cur ? fmtNum(cur.mm) : "—"} mm, limit ${fmtNum(limitMm)} mm.`}>
      <ArrowDefs id={uid} color="var(--ink)" />
      <circle cx={C} cy={C} r={R} fill="none" stroke="var(--ink-faint)" strokeWidth="14" />
      {STATIONS.map((s, i) => (
        <path key={s} d={arcPath(C, C, R, i * 90 + 17, i * 90 + 73)} fill="none" stroke="var(--ink)" strokeWidth="1.2" markerEnd={`url(#${uid}-a)`} />
      ))}
      {/* a dot that travels the loop once per round */}
      <g key={index} style={{ transformOrigin: `${C}px ${C}px` }} className={reduced ? undefined : "animate-[orbit_1600ms_var(--ease-draft)_1_both]"}>
        <circle cx={C} cy={C - R} r="4.5" fill="var(--stamp)" />
      </g>
      {STATIONS.map((s, i) => {
        const [x, y] = onCircle(C, C, R, i * 90);
        return (
          <g key={s}>
            <circle cx={x} cy={y} r="27" fill="var(--screen)" stroke="var(--ink)" strokeWidth="1.25" />
            <text x={x} y={y + 4} textAnchor="middle" fontSize="12" fontWeight="600" fill="var(--ink)" className="font-mono">
              {s}
            </text>
          </g>
        );
      })}
      {/* gauge */}
      <circle cx={C} cy={C} r={rT} fill="var(--pass)" stroke="var(--ok)" strokeWidth="1.25" strokeDasharray="5 4" />
      <circle
        cx={C}
        cy={C}
        r={rE}
        fill={pass ? "transparent" : "var(--stamp-fill)"}
        stroke={pass ? "var(--ok)" : "var(--stamp)"}
        strokeWidth="1.75"
        style={{ transition: `r ${ease}, stroke ${ease}` }}
      />
      <text x={C} y={C + 2} textAnchor="middle" fontSize="30" fontWeight="600" fill="var(--fg)" className="font-mono tnum" style={{ fontVariantNumeric: "tabular-nums" }}>
        {cur ? fmtNum(cur.mm) : "—"}
      </text>
      <text x={C} y={C + 20} textAnchor="middle" fontSize="11" fill="var(--fg-muted)" className="font-mono">
        mm
      </text>
      {/* above the largest gauge circle (r ≤ 104) and below the "photo" station, so it never crosses a ring */}
      <text x={C} y={C - 108} textAnchor="middle" fontSize="11" fill="var(--fg-muted)" className="font-mono">
        round {cur?.iter ?? "—"} of {rounds.at(-1)?.iter ?? "—"}
      </text>

    </svg>
  );
}
