"use client";

import { useMutation } from "@tanstack/react-query";
import { AlertTriangle, Camera, CheckCircle2, ImagePlus, RefreshCw, Trash2, XCircle } from "lucide-react";
import * as React from "react";
import { api } from "@/lib/api";
import { checkPhoto, type PhotoInfo } from "@/lib/photo-checks";
import { cn } from "@/lib/utils";
import { Badge } from "../ui/badge";
import { Button } from "../ui/button";
import { ErrorState } from "../ui/error-state";
import { Spinner } from "../ui/spinner";
import { CaptureReportView } from "./capture-report";

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
  gate = true,
  onGate,
  compact = false,
}: {
  view: "top" | "side" | "mating";
  title: string;
  hint: string;
  required?: boolean;
  value: SlotValue;
  onChange: (v: SlotValue) => void;
  gate?: boolean;
  onGate?: (passed: boolean | null) => void;
  compact?: boolean;
}) {
  const camRef = React.useRef<HTMLInputElement>(null);
  const fileRef = React.useRef<HTMLInputElement>(null);
  const [busy, setBusy] = React.useState(false);
  const [drag, setDrag] = React.useState(false);
  const measure = useMutation({
    mutationFn: (file: File) => api.measure(file, view),
    onSuccess: (r) => onGate?.(r.capture.passed),
    onError: () => onGate?.(null),
  });

  const accept = async (file: File | undefined) => {
    if (!file) return;
    setBusy(true);
    try {
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
            compact ? "flex-col gap-3 py-3 sm:flex-row sm:items-center sm:justify-between sm:text-left" : "flex-col items-center gap-3 py-7 text-center",
            drag && "border-accent bg-accent-soft",
          )}
        >
          {busy ? <Spinner /> : compact ? null : <ImagePlus className="size-6 text-subtle" aria-hidden />}
          <p className={cn("text-[12.5px] leading-5 text-muted", compact ? "max-w-md" : "max-w-xs")}>{hint}</p>
          <div className="flex flex-wrap justify-center gap-2">
            <Button size="sm" variant="solid" onClick={() => camRef.current?.click()} className="sm:hidden">
              <Camera aria-hidden /> Take photo
            </Button>
            <Button size="sm" variant="outline" onClick={() => fileRef.current?.click()}>
              <ImagePlus aria-hidden /> Choose file
            </Button>
          </div>
          {compact ? null : <p className="hidden text-[11px] text-subtle sm:block">or drop an image here</p>}
        </div>
      ) : (
        <div className="grid gap-4 p-3 sm:grid-cols-[160px_minmax(0,1fr)]">
          <div className="relative aspect-[4/3] overflow-hidden rounded-md border border-border bg-surface-2">
            {/* eslint-disable-next-line @next/next/no-img-element -- local object URL preview */}
            <img src={value.info.url} alt={`${title} preview`} className="absolute inset-0 size-full object-cover" />
            <button
              type="button"
              onClick={() => fileRef.current?.click()}
              className="absolute right-1.5 bottom-1.5 inline-flex h-7 items-center gap-1 rounded-md bg-black/70 px-2 text-[11px] text-white hover:bg-black/85"
            >
              <RefreshCw className="size-3" aria-hidden /> Replace
            </button>
          </div>
          <div className="min-w-0 space-y-3">
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
                <CaptureReportView report={measure.data.capture} />
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
