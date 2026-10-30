"use client";

import { useMutation } from "@tanstack/react-query";
import { AlertTriangle, Camera, CheckCircle2, ImagePlus, RefreshCw, Trash2, XCircle } from "lucide-react";
import * as React from "react";
import { radioGroupKeys } from "@/lib/a11y";
import { api } from "@/lib/api";
import { MATE_TAP_KINDS, TOP_TAP_KINDS, type AnyTapKind } from "@/lib/mate-fit";
import type { PhotoInfo } from "@/lib/photo-checks";
import { cn } from "@/lib/utils";
import { Badge } from "../ui/badge";
import { Button } from "../ui/button";
import { ErrorState } from "../ui/error-state";
import { Spinner } from "../ui/spinner";
const CaptureReportView = React.lazy(() => import("./capture-report").then((m) => ({ default: m.CaptureReportView })));

export type SlotValue = { file: File; info: PhotoInfo } | null;

/**
 * One photo input: camera (`capture="environment"`) or file upload, instant client-side checks, then the server capture
 * gate (`POST /measure`) for the views it applies to.
 */
export function PhotoSlot({
  view,
  title,
  hint,
  required,
  value,
  onChange,
  matKind,
  gate = true,
  onGate,
  compact = false,
  points,
  onPoints,
  pointsHint,
  tapKinds = TOP_TAP_KINDS,
}: {
  view: "top" | "side" | "mating";
  title: string;
  hint: string;
  required?: boolean;
  matKind?: "screen" | "paper";
  value: SlotValue;
  onChange: (v: SlotValue) => void;
  gate?: boolean;
  onGate?: (passed: boolean | null) => void;
  compact?: boolean;
  /** Tap-to-point: feature taps in image pixels, drawn on the preview (docs/API.md `points`). */
  points?: TapPoint[];
  onPoints?: (p: TapPoint[]) => void;
  pointsHint?: string;
  /** What a tap can mark on this photo (the "where it fits" photo marks a socket, shaft or slot). */
  tapKinds?: readonly TapKind[];
}) {
  const [natural, setNatural] = React.useState<{ w: number; h: number } | null>(null);
  const [tapKind, setTapKind] = React.useState<TapKind>(tapKinds[0] ?? "hole");
  const camRef = React.useRef<HTMLInputElement>(null);
  const fileRef = React.useRef<HTMLInputElement>(null);
  const [busy, setBusy] = React.useState(false);
  const [drag, setDrag] = React.useState(false);
  const measure = useMutation({
    mutationFn: (file: File) => api.measure(file, view === "mating" ? "top" : view, { matKind }),
    onSuccess: (r) => onGate?.(r.capture.passed),
    onError: () => onGate?.(null),
  });

  const accept = async (file: File | undefined) => {
    if (!file) return;
    setBusy(true);
    try {
      // Image-analysis code loads only when a photo is chosen.
      const { checkPhoto } = await import("@/lib/photo-checks");
      const info = await checkPhoto(file);
      onChange({ file, info });
      measure.reset();
      onGate?.(null);
      if (gate && info.checks.every((c) => c.level !== "fail")) measure.mutate(file);
    } finally {
      setBusy(false);
    }
  };

  React.useEffect(() => () => (value?.info.url ? URL.revokeObjectURL(value.info.url) : undefined), [value]);

  return (
    <div className="rounded-lg border border-border bg-surface">
      <div className="flex items-center justify-between gap-2 border-b border-border px-4 py-2.5">
        <div className="flex items-center gap-2">
          <h3 className="text-[13px] font-semibold">{title}</h3>
          <Badge tone={required ? "accent" : "neutral"}>{required ? "required" : "optional"}</Badge>
        </div>
        {value ? (
          <Button size="sm" variant="ghost" onClick={() => { onChange(null); measure.reset(); onGate?.(null); }} aria-label={`Remove ${title} photo`}>
            <Trash2 aria-hidden /> Remove
          </Button>
        ) : null}
      </div>
      <input ref={camRef} type="file" accept="image/*" capture="environment" className="sr-only" tabIndex={-1} aria-hidden onChange={(e) => void accept(e.target.files?.[0])} />
      <input
        ref={fileRef}
        type="file"
        accept="image/jpeg,image/png,image/heic,image/heif,image/webp"
        className="sr-only"
        tabIndex={-1}
        aria-label={`Upload ${title} photo`}
        onChange={(e) => void accept(e.target.files?.[0])}
      />
      {!value ? (
        <div
          onDragOver={(e) => {
            e.preventDefault();
            setDrag(true);
          }}
          onDragLeave={() => setDrag(false)}
          onDrop={(e) => {
            e.preventDefault();
            setDrag(false);
            void accept(e.dataTransfer.files[0]);
          }}
          className={cn(
            "m-3 flex rounded-md border border-dashed border-border-strong px-4 transition-colors",
            compact ? "flex-col gap-3 py-3 sm:flex-row sm:items-center sm:justify-between sm:text-left" : "min-h-[240px] flex-col items-center justify-center gap-3 py-10 text-center",
            drag && "border-accent bg-accent-soft",
          )}
        >
          {busy ? <Spinner /> : compact ? null : <ImagePlus className="size-8 text-subtle" aria-hidden />}
          <p className={cn("text-[12.5px] leading-5 text-muted", compact ? "max-w-md" : "max-w-xs")}>{hint}</p>
          <div className="flex flex-wrap justify-center gap-2">
            <Button size="sm" variant="solid" onClick={() => camRef.current?.click()} className="sm:hidden" aria-label={`Take photo: ${title.toLowerCase()}`}>
              <Camera aria-hidden /> Take photo
            </Button>
            <Button size="sm" variant="outline" onClick={() => fileRef.current?.click()} aria-label={`Choose file: ${title.toLowerCase()}`}>
              <ImagePlus aria-hidden /> Choose file
            </Button>
          </div>
          {compact ? null : <p className="hidden text-[11px] text-subtle sm:block">or drop an image here</p>}
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-4 p-3 sm:grid-cols-[160px_minmax(0,1fr)]">
          <div className="relative aspect-[4/3] overflow-hidden rounded-md border border-border bg-surface-2">
            {/* eslint-disable-next-line @next/next/no-img-element -- local object URL preview */}
            <img
              src={value.info.url}
              alt={`${title} preview`}
              className="absolute inset-0 size-full object-contain"
              onLoad={(e) => setNatural({ w: e.currentTarget.naturalWidth, h: e.currentTarget.naturalHeight })}
            />
            {onPoints && natural ? (
              <PointLayer natural={natural} points={points ?? []} onPoints={onPoints} title={title} kind={tapKind} />
            ) : null}
            <button
              type="button"
              onClick={() => fileRef.current?.click()}
              className="absolute right-1.5 bottom-1.5 inline-flex h-7 items-center gap-1 rounded-md bg-black/70 px-2 text-[11px] text-white hover:bg-black/85"
            >
              <RefreshCw className="size-3" aria-hidden /> Replace
            </button>
          </div>
          <div className="min-w-0 space-y-3">
            {onPoints ? (
              <div className="space-y-1.5">
              <TapKindPicker value={tapKind} onChange={setTapKind} kinds={tapKinds} />
              <p className="flex flex-wrap items-center gap-x-2 text-[12px] text-muted">
                <span>{pointsHint}</span>
                {points?.length ? (
                  <button type="button" onClick={() => onPoints([])} className="font-medium text-accent-text underline-offset-2 hover:underline">
                    Clear
                  </button>
                ) : null}
              </p>
              </div>
            ) : null}
            <ul className="space-y-1" aria-label="Instant checks">
              {value.info.checks.map((c) => {
                const Icon = c.level === "ok" ? CheckCircle2 : c.level === "warn" ? AlertTriangle : XCircle;
                return (
                  <li key={c.name} className="flex items-start gap-2 text-[12px]">
                    <Icon className={cn("mt-px size-3.5 shrink-0", c.level === "ok" ? "text-ok" : c.level === "warn" ? "text-warn" : "text-bad")} aria-hidden />
                    <span className={c.name === "resolution" ? "font-mono tnum text-muted" : "text-muted"}>{c.text}</span>
                  </li>
                );
              })}
            </ul>
            {gate ? (
              measure.isPending ? (
                <div className="flex items-center gap-2 text-[12px] text-muted" role="status">
                  <Spinner className="size-3.5" label="Checking" /> Server capture gate: finding markers, checking blur, tilt and glare…
                </div>
              ) : measure.data ? (
                <React.Suspense fallback={<Spinner className="size-3.5" label="Loading" />}>
                  <CaptureReportView report={measure.data.capture} />
                </React.Suspense>
              ) : measure.error ? (
                <ErrorState error={measure.error} compact what="the capture check" onRetry={() => measure.mutate(value.file)} className="py-4" />
              ) : null
            ) : (
              <p className="text-[12px] text-subtle">Checked by the server when the job starts.</p>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

export const TAP_KINDS = TOP_TAP_KINDS;
export { MATE_TAP_KINDS };
export type TapKind = AnyTapKind;
export type TapPoint<K extends TapKind = TapKind> = { x: number; y: number; kind: K };
const TAP_LABEL: Record<TapKind, string> = {
  hole: "Hole",
  slot: "Slot",
  tab: "Tab",
  broken_edge: "Broken edge",
  exclude: "Not it (finger, glare)",
  mate_hole: "Socket it goes into",
  mate_peg: "Shaft or pin it goes onto",
  mate_slot: "Slot or panel edge",
};
const TAP_MARK: Record<TapKind, string> = { hole: "H", slot: "S", tab: "T", broken_edge: "B", exclude: "×", mate_hole: "O", mate_peg: "P", mate_slot: "S" };
const MAX_TAPS = 32;

function TapKindPicker({ value, onChange, kinds }: { value: TapKind; onChange: (k: TapKind) => void; kinds: readonly TapKind[] }) {
  return (
    <div role="radiogroup" onKeyDown={radioGroupKeys} aria-label="What a tap marks" className="inline-flex flex-wrap gap-1">
      {kinds.map((k) => (
        <button
          key={k}
          type="button"
          role="radio"
          aria-checked={value === k}
          onClick={() => onChange(k)}
          className={cn(
            "h-7 rounded-md border px-2 text-[12px]",
            value === k ? "border-accent bg-accent-soft font-medium text-fg" : "border-border text-muted hover:text-fg",
          )}
        >
          {TAP_LABEL[k]}
        </button>
      ))}
    </div>
  );
}

/**
 * Click/tap layer over an object-contain preview: maps taps to image pixels and draws numbered markers.
 * Keyboard users get a button per marker to remove it.
 */
function PointLayer({ natural, points, onPoints, title, kind }: { natural: { w: number; h: number }; points: TapPoint[]; onPoints: (p: TapPoint[]) => void; title: string; kind: TapKind }) {
  const ref = React.useRef<HTMLDivElement>(null);
  const [box, setBox] = React.useState({ w: 0, h: 0 });
  React.useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const ro = new ResizeObserver(([e]) => e && setBox({ w: e.contentRect.width, h: e.contentRect.height }));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  const scale = box.w && box.h ? Math.min(box.w / natural.w, box.h / natural.h) : 0;
  const ox = (box.w - natural.w * scale) / 2;
  const oy = (box.h - natural.h * scale) / 2;
  return (
    <div
      ref={ref}
      className="absolute inset-0 cursor-crosshair"
      onClick={(e) => {
        if (!scale) return;
        const r = e.currentTarget.getBoundingClientRect();
        const x = (e.clientX - r.left - ox) / scale;
        const y = (e.clientY - r.top - oy) / scale;
        if (x < 0 || y < 0 || x > natural.w || y > natural.h) return;
        onPoints([...points, { x: Math.round(x), y: Math.round(y), kind }].slice(-MAX_TAPS));
      }}
      aria-label={`${title}: tap to mark features`}
      role="group"
    >
      {points.map(({ x, y, kind: k }, i) => (
        <button
          key={`${x}-${y}-${i}`}
          type="button"
          aria-label={`Remove point ${i + 1} (${TAP_LABEL[k].toLowerCase()})`}
          onClick={(e) => {
            e.stopPropagation();
            onPoints(points.filter((_, j) => j !== i));
          }}
          className="absolute flex h-5 min-w-5 px-0.5 -translate-x-1/2 -translate-y-1/2 items-center justify-center rounded-full border-2 border-white bg-accent font-mono text-[10px] font-bold text-accent-fg shadow-md"
          style={{ left: ox + x * scale, top: oy + y * scale }}
        >
          {TAP_MARK[k]}
          {i + 1}
        </button>
      ))}
    </div>
  );
}
