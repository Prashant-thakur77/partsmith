"use client";

import { ImageOff, MapPin, X } from "lucide-react";
import * as React from "react";
import { Eyebrow } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/toggle";
import { artifactUrl } from "@/lib/api";
import type { ReviewPin } from "@/lib/api-types";
import { nudge, pinOutcome, uvClamped, uvFromPoint, zoomFrame, type DraftPin } from "@/lib/review";
import { cn } from "@/lib/utils";

/**
 * The rectified top photo with reviewer pins. A click adds a numbered pin; pins can be dragged, moved with the arrow keys
 * or removed. (u, v) are relative to the rendered image box, so the on-screen size never changes what is sent.
 * Earlier rounds' pins are drawn grey with the server's before → after mismatch. With a `focus` box the frame shows only
 * the part (the whole image is laid out behind it), so (u, v) stay fractions of the full photo.
 */
export function PinPhoto({
  rectified,
  overlay,
  focus,
  pins,
  onChange,
  earlier = [],
  title = "Rectified photo",
  worst = [],
  className,
}: {
  rectified: string | null | undefined;
  overlay: string | null | undefined;
  /** The part's box on the photo, [u0, v0, u1, v1] fractions, from the API. */
  focus?: readonly number[] | null;
  pins: DraftPin[];
  /** Omit for a read-only photo (no admin token, or the round is already decided). */
  onChange?: (pins: DraftPin[]) => void;
  earlier?: ReviewPin[];
  /** The panel's small heading. */
  title?: string;
  /** The verifier's biggest gap, circled (from the API; never computed here). */
  worst?: { u: number; v: number; gap_mm: number; limit_mm: number }[];
  className?: string;
}) {
  const [showOverlay, setShowOverlay] = React.useState(true);
  const [failed, setFailed] = React.useState(false);
  const [zoomed, setZoomed] = React.useState(true);
  const [natural, setNatural] = React.useState<{ w: number; h: number } | null>(null);
  const img = React.useRef<HTMLImageElement>(null);
  const drag = React.useRef<number | null>(null);
  const nextKey = React.useRef(1);
  const src = artifactUrl(showOverlay && overlay ? overlay : rectified) ?? artifactUrl(overlay);
  const editable = !!onChange;
  const zoom = zoomFrame(focus, natural);
  const z = zoomed ? zoom : null;

  React.useEffect(() => setFailed(false), [src]);

  const box = () => img.current?.getBoundingClientRect();
  const update = (key: number, patch: Partial<DraftPin>) => onChange?.(pins.map((p) => (p.key === key ? { ...p, ...patch } : p)));
  const remove = (key: number) => onChange?.(pins.filter((p) => p.key !== key));
  const add = (u: number, v: number) => {
    const key = Math.max(nextKey.current, ...pins.map((p) => p.key + 1));
    nextKey.current = key + 1;
    onChange?.([...pins, { key, u, v, note: "" }]);
    // put the cursor in the new pin's note field
    window.setTimeout(() => document.getElementById(`pin-note-${key}`)?.focus({ preventScroll: true }), 0);
  };

  return (
    <div className={cn("overflow-hidden rounded-lg border border-border bg-surface", className)}>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2 border-b border-border px-3 py-2">
        <Eyebrow>{title}</Eyebrow>
        {editable ? <span className="text-[12px] text-muted">Click the photo where something is wrong.</span> : null}
        <div className="ml-auto flex items-center gap-3">
          {zoom ? <Switch label="Zoom to part" checked={zoomed} onCheckedChange={setZoomed} className="text-[12px]" /> : null}
          {overlay && rectified ? <Switch label="Model outline" checked={showOverlay} onCheckedChange={setShowOverlay} className="text-[12px]" /> : null}
          {editable ? (
            <button type="button" onClick={() => add(0.5, 0.5)} className="inline-flex items-center gap-1 text-[12px] text-accent-text hover:underline">
              <MapPin className="size-3.5" aria-hidden /> Add pin
            </button>
          ) : null}
        </div>
      </div>
      <div className="flex justify-center bg-[var(--viewer-bg)] p-2">
        {!src || failed ? (
          <div className="flex min-h-[200px] flex-col items-center justify-center gap-2 text-[13px] text-muted">
            <ImageOff className="size-6 text-subtle" aria-hidden />
            No rectified photo for this job.
          </div>
        ) : (
          <div
            className={cn(z ? "relative w-full overflow-hidden" : "contents")}
            style={z ? { aspectRatio: z.aspect, width: `min(100%, calc(min(62vh, 560px) * ${z.aspect.toFixed(4)}))` } : undefined}
          >
            <div
              className={cn("select-none", z ? "absolute" : "relative inline-block max-w-full", editable && "cursor-crosshair")}
              style={z ? { left: `${z.left}%`, top: `${z.top}%`, width: `${z.width}%` } : undefined}
              role={editable ? "group" : undefined}
              aria-label={editable ? "Rectified photo: click to add a pin" : undefined}
              onClick={(e) => {
                if (!editable || (e.target as HTMLElement).closest("[data-pin]")) return;
                const b = box();
                const uv = b ? uvFromPoint(e.clientX, e.clientY, b) : null;
                if (uv) add(uv.u, uv.v);
              }}
            >
              {/* eslint-disable-next-line @next/next/no-img-element -- API artifact */}
              <img
                ref={img}
                src={src}
                alt={showOverlay && overlay ? "Rectified top photo with the model outline drawn on it" : "Rectified top photo"}
                draggable={false}
                onError={() => setFailed(true)}
                onLoad={(e) => setNatural({ w: e.currentTarget.naturalWidth, h: e.currentTarget.naturalHeight })}
                className={z ? "block h-auto w-full max-w-none" : "block h-auto max-h-[min(62vh,560px)] w-auto max-w-full"}
              />
              {worst.map((w) => (
              <span
                key={`worst-${w.u}-${w.v}`}
                className="pointer-events-none absolute size-0"
                style={{ left: `${w.u * 100}%`, top: `${w.v * 100}%` }}
                title={`The verifier's biggest gap: ${w.gap_mm.toFixed(2)} mm (limit ${w.limit_mm.toFixed(2)} mm)`}
              >
                <span className="absolute size-10 -translate-x-1/2 -translate-y-1/2 animate-pulse rounded-full border-2 border-dashed border-warn" />
                <span className={cn("absolute -translate-y-[2.1rem] rounded border border-warn bg-black/75 px-1 font-mono text-[10px] whitespace-nowrap text-white tnum", w.u > 0.7 ? "right-2" : "left-2")}>
                  biggest gap {w.gap_mm.toFixed(2)} mm
                </span>
              </span>
            ))}
            {earlier.map((p) => (
                <span
                  key={`old-${p.id}-${p.u}-${p.v}`}
                  className="pointer-events-none absolute size-0"
                  style={{ left: `${p.u * 100}%`, top: `${p.v * 100}%` }}
                  title={`Earlier pin ${p.id}: ${p.note || "no note"} (${pinOutcome(p)})`}
                >
                  {/* the ring is centred on the point; the before → after label hangs to its right */}
                  <span className="absolute flex size-5 -translate-x-1/2 -translate-y-1/2 items-center justify-center rounded-full border border-white/80 bg-subtle/90 font-mono text-[10px] text-white">{p.id}</span>
                  <span className={cn("absolute -translate-y-1/2 rounded bg-black/55 px-1 font-mono text-[10px] whitespace-nowrap text-white tnum", p.u > 0.7 ? "right-3" : "left-3")}>
                    {pinOutcome(p)}
                  </span>
                </span>
              ))}
              {pins.map((p, i) => (
                <button
                  key={p.key}
                  type="button"
                  data-pin
                  disabled={!editable}
                  aria-label={`Pin ${i + 1}${p.note ? `: ${p.note}` : ""}. Drag or use the arrow keys to move; Delete removes it.`}
                  className="absolute flex size-6 -translate-x-1/2 touch-none -translate-y-1/2 cursor-grab items-center justify-center rounded-full border-2 border-white bg-bad font-mono text-[11px] font-semibold text-white shadow-md active:cursor-grabbing disabled:cursor-default"
                  style={{ left: `${p.u * 100}%`, top: `${p.v * 100}%` }}
                  onPointerDown={(e) => {
                    if (!editable) return;
                    e.currentTarget.setPointerCapture(e.pointerId);
                    drag.current = p.key;
                  }}
                  onPointerMove={(e) => {
                    if (drag.current !== p.key) return;
                    const b = box();
                    const uv = b ? uvClamped(e.clientX, e.clientY, b) : null;
                    if (uv) update(p.key, uv);
                  }}
                  onPointerUp={() => (drag.current = null)}
                  onPointerCancel={() => (drag.current = null)}
                  onKeyDown={(e) => {
                    if (e.key === "Delete" || e.key === "Backspace") {
                      e.preventDefault();
                      e.stopPropagation();
                      remove(p.key);
                      return;
                    }
                    const uv = nudge(p, e.key, e.shiftKey);
                    if (!uv) return;
                    e.preventDefault();
                    e.stopPropagation();
                    update(p.key, uv);
                  }}
                >
                  {i + 1}
                </button>
              ))}
            </div>
          </div>
        )}
      </div>
      {pins.length ? (
        <ol className="space-y-2 border-t border-border p-3" aria-label="Pin notes">
          {pins.map((p, i) => (
            <li key={p.key} className="flex items-center gap-2">
              <span className="flex size-6 shrink-0 items-center justify-center rounded-full bg-bad font-mono text-[11px] font-semibold text-white" aria-hidden>
                {i + 1}
              </span>
              <Input
                id={`pin-note-${p.key}`}
                aria-label={`Note for pin ${i + 1}`}
                value={p.note}
                maxLength={300}
                disabled={!editable}
                onChange={(e) => update(p.key, { note: e.target.value })}
                placeholder="What is wrong here? e.g. this corner was square"
                className="h-8 text-[13px]"
              />
              {editable ? (
                <button
                  type="button"
                  onClick={() => remove(p.key)}
                  aria-label={`Remove pin ${i + 1}`}
                  className="inline-flex size-8 shrink-0 items-center justify-center rounded-md text-muted hover:bg-surface-2 hover:text-fg"
                >
                  <X className="size-4" aria-hidden />
                </button>
              ) : null}
            </li>
          ))}
        </ol>
      ) : null}
    </div>
  );
}
