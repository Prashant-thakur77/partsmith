"use client";

import * as React from "react";
import { cn } from "@/lib/utils";

/** Before/after wipe between two aligned images (photo ↔ model render overlay). Keyboard: ←/→ move the divider. */
export function WipeSlider({
  before,
  after,
  beforeLabel,
  afterLabel,
  className,
}: {
  before: string;
  after: string;
  beforeLabel: string;
  afterLabel: string;
  className?: string;
}) {
  const [pos, setPos] = React.useState(50);
  const ref = React.useRef<HTMLDivElement>(null);
  const dragging = React.useRef(false);
  const setFromX = (clientX: number) => {
    const r = ref.current?.getBoundingClientRect();
    if (!r) return;
    setPos(Math.min(100, Math.max(0, ((clientX - r.left) / r.width) * 100)));
  };
  return (
    <div
      ref={ref}
      className={cn("relative touch-none overflow-hidden select-none", className)}
      onPointerDown={(e) => {
        dragging.current = true;
        (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
        setFromX(e.clientX);
      }}
      onPointerMove={(e) => dragging.current && setFromX(e.clientX)}
      onPointerUp={() => (dragging.current = false)}
    >
      {/* eslint-disable-next-line @next/next/no-img-element -- API artifact */}
      <img src={after} alt={afterLabel} className="absolute inset-0 size-full object-contain" draggable={false} />
      <div className="absolute inset-0" style={{ clipPath: `inset(0 ${100 - pos}% 0 0)` }}>
        {/* eslint-disable-next-line @next/next/no-img-element -- API artifact */}
        <img src={before} alt={beforeLabel} className="absolute inset-0 size-full object-contain" draggable={false} />
      </div>
      <div className="pointer-events-none absolute inset-y-0 w-px bg-white shadow-[0_0_0_1px_rgba(0,0,0,0.35)]" style={{ left: `${pos}%` }} />
      <div
        role="slider"
        tabIndex={0}
        aria-label="Compare photo and model"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={Math.round(pos)}
        aria-valuetext={`${Math.round(pos)} % ${beforeLabel}`}
        onKeyDown={(e) => {
          if (e.key === "ArrowLeft") setPos((p) => Math.max(0, p - (e.shiftKey ? 10 : 2)));
          if (e.key === "ArrowRight") setPos((p) => Math.min(100, p + (e.shiftKey ? 10 : 2)));
        }}
        className="absolute top-1/2 flex size-8 -translate-x-1/2 -translate-y-1/2 cursor-ew-resize items-center justify-center rounded-full border border-black/20 bg-white text-[11px] text-black shadow-md"
        style={{ left: `${pos}%` }}
      >
        ⇆
      </div>
      <span className="pointer-events-none absolute top-2 left-2 rounded bg-black/65 px-1.5 py-0.5 text-[11px] text-white">{beforeLabel}</span>
      <span className="pointer-events-none absolute top-2 right-2 rounded bg-black/65 px-1.5 py-0.5 text-[11px] text-white">{afterLabel}</span>
    </div>
  );
}
