/**
 * Art D — a hinge leaf drawn as a parts drawing with numbered balloons, one per knob of the real program (names, labels
 * and values are props from a stored run). Hovering or focusing a balloon's legend row highlights its feature.
 * Only knobs this drawing has a feature for are shown.
 */
import * as React from "react";
import { cn } from "@/lib/utils";
import { ArrowDefs, Balloon, useSvgId } from "./primitives";

export type CalloutKnob = { name: string; label: string; value: string };

/** Knob → where its feature is on the drawing (the balloon sits at b, its leader ends at t). */
const FEATURES: Record<string, { b: [number, number]; t: [number, number] }> = {
  knuckle_count: { b: [96, 52], t: [214, 104] },
  pin_d: { b: [574, 60], t: [470, 108] },
  hole_d: { b: [150, 314], t: [218, 214] },
  hole_count: { b: [330, 318], t: [372, 212] },
  corner_radius: { b: [580, 300], t: [524, 268] },
  length: { b: [330, 52], t: [330, 82] },
  leaf_width: { b: [600, 168], t: [566, 186] },
};

export const CALLOUT_KNOBS = Object.keys(FEATURES);

const LEAF = { x: 116, y: 122, w: 408, h: 150, r: 14 };
const HOLES = [0, 1, 2, 3].map((i) => 172 + i * 98);
const KNUCKLES = [
  [146, 252],
  [388, 494],
];

export function ParamCallouts({
  knobs,
  active,
  onActive,
  className,
}: {
  knobs: CalloutKnob[];
  active: string | null;
  onActive: (name: string | null) => void;
  className?: string;
}) {
  const uid = useSvgId("pc");
  const shown = knobs.filter((k) => FEATURES[k.name]);
  const on = (n: string) => active === n;
  const hl = (n: string) => (on(n) ? "var(--stamp)" : "var(--ink)");
  const L = LEAF;
  // leaf outline with rounded free corners (the edge away from the knuckles)
  const leaf = `M${L.x} ${L.y} H${L.x + L.w} V${L.y + L.h - L.r} A${L.r} ${L.r} 0 0 1 ${L.x + L.w - L.r} ${L.y + L.h} H${L.x + L.r} A${L.r} ${L.r} 0 0 1 ${L.x} ${L.y + L.h - L.r} Z`;
  return (
    <div className={cn("grid gap-5 md:grid-cols-[minmax(0,1.5fr)_minmax(0,1fr)] md:items-center", className)}>
      <svg viewBox="0 0 680 360" className="h-auto w-full" role="img" aria-label={`Hinge leaf with ${shown.length} numbered knobs: ${shown.map((k) => k.name).join(", ")}.`}>
        <ArrowDefs id={uid} color="var(--dim)" />
        {/* leaf */}
        <path d={leaf} fill="var(--stamp-fill)" stroke={on("corner_radius") || on("leaf_width") || on("length") ? "var(--stamp)" : "var(--ink)"} strokeWidth="1.5" className="transition-[stroke] duration-[var(--dur-state)]" />
        {/* knuckles and pin bore */}
        {KNUCKLES.map(([a, b], i) => (
          <rect key={i} x={a} y={94} width={b! - a!} height={28} rx={3} fill={on("knuckle_count") ? "var(--stamp-fill)" : "var(--screen)"} stroke={hl("knuckle_count")} strokeWidth={on("knuckle_count") ? 2 : 1.5} className="transition-[stroke,fill] duration-[var(--dur-state)]" />
        ))}
        <line x1={L.x - 10} x2={L.x + L.w + 10} y1={108} y2={108} stroke={hl("pin_d")} strokeWidth={on("pin_d") ? 1.6 : 1} strokeDasharray="10 3 2 3" />
        {/* countersunk holes */}
        {HOLES.map((x, i) => (
          <g key={x}>
            <circle cx={x} cy={212} r={15} fill="none" stroke="var(--ink)" strokeWidth="0.9" strokeOpacity="0.5" />
            <circle
              cx={x}
              cy={212}
              r={8}
              fill="var(--screen)"
              stroke={on("hole_count") || (on("hole_d") && i === 0) ? "var(--stamp)" : "var(--ink)"}
              strokeWidth={on("hole_count") || (on("hole_d") && i === 0) ? 2 : 1.4}
              className="transition-[stroke] duration-[var(--dur-state)]"
            />
            <path d={`M${x - 20} 212 H${x + 20} M${x} 192 V232`} stroke="var(--ink)" strokeWidth="0.6" strokeOpacity="0.45" strokeDasharray="6 2 1 2" />
          </g>
        ))}
        {/* corner radius arc */}
        <path d={`M${L.x + L.w} ${L.y + L.h - L.r} A${L.r} ${L.r} 0 0 1 ${L.x + L.w - L.r} ${L.y + L.h}`} fill="none" stroke={hl("corner_radius")} strokeWidth={on("corner_radius") ? 2.4 : 0} />
        {/* overall dimensions */}
        <g stroke="var(--dim)" strokeWidth="1" opacity={on("length") || on("leaf_width") ? 1 : 0.7}>
          <line x1={L.x} x2={L.x + L.w} y1={82} y2={82} markerStart={`url(#${uid}-a)`} markerEnd={`url(#${uid}-a)`} strokeWidth={on("length") ? 1.8 : 1} />
          <line x1={L.x} x2={L.x} y1={88} y2={90} strokeDasharray="3 3" />
          <line x1={L.x + L.w} x2={L.x + L.w} y1={76} y2={118} strokeDasharray="3 3" />
          <line x1={L.x} x2={L.x} y1={76} y2={118} strokeDasharray="3 3" />
          <line x1={566} x2={566} y1={94} y2={L.y + L.h} markerStart={`url(#${uid}-a)`} markerEnd={`url(#${uid}-a)`} strokeWidth={on("leaf_width") ? 1.8 : 1} />
          <line x1={L.x + L.w + 4} x2={572} y1={L.y + L.h} y2={L.y + L.h} strokeDasharray="3 3" />
          <line x1={L.x + L.w - 26} x2={572} y1={94} y2={94} strokeDasharray="3 3" />
        </g>
        {shown.map((k) => {
          const f = FEATURES[k.name]!;
          return <Balloon key={k.name} x={f.b[0]} y={f.b[1]} tx={f.t[0]} ty={f.t[1]} n={shown.indexOf(k) + 1} active={on(k.name)} className={active && !on(k.name) ? "opacity-40" : undefined} />;
        })}
      </svg>
      <ol className="space-y-1" aria-label="Knobs on this drawing">
        {shown.map((k, i) => (
          <li key={k.name}>
            <button
              type="button"
              onMouseEnter={() => onActive(k.name)}
              onMouseLeave={() => onActive(null)}
              onFocus={() => onActive(k.name)}
              onBlur={() => onActive(null)}
              onClick={() => onActive(on(k.name) ? null : k.name)}
              aria-pressed={on(k.name)}
              className={cn(
                "press flex w-full items-center gap-3 rounded-md border px-2.5 py-1.5 text-left",
                on(k.name) ? "border-accent/50 bg-accent-soft" : "border-transparent hover:bg-surface-2",
              )}
            >
              <span className={cn("flex size-6 shrink-0 items-center justify-center rounded-full border font-mono text-[11px] font-semibold", on(k.name) ? "border-stamp text-stamp" : "border-ink/60 text-fg")}>{i + 1}</span>
              <span className="min-w-0 flex-1">
                <span className="block font-mono text-[12.5px] text-fg">{k.name}</span>
                <span className="block truncate text-[12px] text-muted">{k.label}</span>
              </span>
              <span className="font-mono text-[12.5px] text-fg tnum">{k.value}</span>
            </button>
          </li>
        ))}
      </ol>
    </div>
  );
}
