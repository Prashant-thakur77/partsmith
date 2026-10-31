"use client";

/**
 * A ghost cursor that, after ~4 s on screen without anyone touching the demo, drags one slider knob a little so people
 * see the part re-bake. It runs once per page view, stops as soon as someone interacts, and never runs with reduced
 * motion. The value it sets goes through the same onChange as a real drag (and the same server bake).
 */
import * as React from "react";
import type { ParamSpec } from "@/lib/api-types";
import { useInView, usePrefersReducedMotion } from "@/lib/motion";

const IDLE_MS = 4000;
/** Once per page view, whichever demo panel is on screen. */
let ran = false;

function snap(v: number, p: ParamSpec): number {
  const s = p.step > 0 ? Math.round((v - p.min) / p.step) * p.step + p.min : v;
  return Math.min(p.max, Math.max(p.min, Number(s.toFixed(6))));
}

/** Where a knob drag ends: ~12 % of its range above the current value (or below, when that would pass the max). */
export function ghostTarget(p: ParamSpec, value: number): number {
  const span = p.max - p.min;
  const up = value + span * 0.12 <= p.max;
  return snap(value + (up ? 1 : -1) * span * 0.12, p);
}

export function GhostCursor({
  root,
  params,
  values,
  onChange,
}: {
  root: React.RefObject<HTMLElement | null>;
  params: ParamSpec[];
  values: Record<string, number>;
  onChange: (next: Record<string, number>) => void;
}) {
  const reduced = usePrefersReducedMotion();
  const { ref, seen } = useInView<HTMLSpanElement>({ threshold: 0.5 });
  const [pos, setPos] = React.useState<{ x: number; y: number; down: boolean; on: boolean } | null>(null);
  const done = React.useRef(false);
  const latest = React.useRef(values);
  latest.current = values;
  const knob = params.find((p) => !p.topology && p.max > p.min);

  React.useEffect(() => {
    const el = root.current;
    if (!el || reduced || !seen || !knob || done.current || ran) return;
    let cancelled = false;
    const timers: ReturnType<typeof setTimeout>[] = [];
    const stop = () => {
      cancelled = true;
      done.current = true;
      ran = true;
      timers.forEach(clearTimeout);
      setPos(null);
    };
    el.addEventListener("pointerdown", stop, { once: true });
    el.addEventListener("keydown", stop, { once: true });
    timers.push(
      setTimeout(() => {
        if (cancelled) return;
        const row = el.querySelector(`label[title="${CSS.escape(knob.name)}"]`)?.closest(".group\\/knob");
        const track = row?.querySelector<HTMLElement>('input[type="range"], [role="slider"]');
        if (!track) return;
        done.current = true;
        ran = true;
        const box = el.getBoundingClientRect();
        const r = track.getBoundingClientRect();
        const from = latest.current[knob.name] ?? knob.default;
        const to = ghostTarget(knob, from);
        const xAt = (v: number) => r.left - box.left + el.scrollLeft + ((v - knob.min) / (knob.max - knob.min)) * r.width;
        const y = r.top - box.top + el.scrollTop + r.height / 2;
        setPos({ x: xAt(from) + 60, y: y + 50, down: false, on: false });
        const at = (ms: number, f: () => void) => timers.push(setTimeout(() => !cancelled && f(), ms));
        at(30, () => setPos({ x: xAt(from) + 60, y: y + 50, down: false, on: true }));
        at(80, () => setPos({ x: xAt(from), y, down: false, on: true }));
        at(760, () => setPos({ x: xAt(from), y, down: true, on: true }));
        const steps = 8;
        for (let i = 1; i <= steps; i++) {
          const v = snap(from + ((to - from) * i) / steps, knob);
          at(900 + i * 110, () => {
            setPos({ x: xAt(v), y, down: true, on: true });
            onChange({ ...latest.current, [knob.name]: v });
          });
        }
        at(900 + steps * 110 + 300, () => setPos((p) => (p ? { ...p, down: false } : p)));
        at(900 + steps * 110 + 1300, () => setPos((p) => (p ? { ...p, on: false } : p)));
        at(900 + steps * 110 + 1700, () => setPos(null));
      }, IDLE_MS),
    );
    return () => {
      cancelled = true;
      timers.forEach(clearTimeout);
      el.removeEventListener("pointerdown", stop);
      el.removeEventListener("keydown", stop);
    };
  }, [root, reduced, seen, knob, onChange]);

  return (
    <>
      <span ref={ref} aria-hidden className="pointer-events-none absolute inset-x-0 top-1/3 h-px" />
      {pos ? (
        <span
          aria-hidden
          className="pointer-events-none absolute top-0 left-0 z-10 transition-[transform,opacity] duration-[600ms] ease-[var(--ease-out)]"
          style={{ transform: `translate(${pos.x - 3}px, ${pos.y - 2}px)`, opacity: pos.on ? 1 : 0, transitionDuration: pos.down ? "110ms" : undefined }}
        >
          <svg width="22" height="24" viewBox="0 0 22 24" className={pos.down ? "scale-90 transition-transform" : "transition-transform"}>
            <path d="M3 2 L3 19 L7.5 15 L10.5 21.5 L13.2 20.3 L10.3 14 L16.5 14 Z" fill="var(--fg)" stroke="var(--surface)" strokeWidth="1.4" strokeLinejoin="round" />
          </svg>
          <span className="absolute top-5 left-4 rounded bg-inverse px-1.5 py-0.5 font-mono text-[10px] whitespace-nowrap text-inverse-fg shadow-sm">demo drag</span>
        </span>
      ) : null}
    </>
  );
}
