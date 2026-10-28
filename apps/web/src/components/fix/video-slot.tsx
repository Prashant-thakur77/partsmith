"use client";

import { Trash2, Video } from "lucide-react";
import * as React from "react";
import { cn } from "@/lib/utils";
import { Badge } from "../ui/badge";
import { Button } from "../ui/button";

/** Optional orbit clip ("walk around it"): phone camera capture or file, with an instant length check (6–8 s ideal). */
export function VideoSlot({ title, hint, value, onChange }: { title: string; hint: string; value: File | null; onChange: (f: File | null) => void }) {
  const ref = React.useRef<HTMLInputElement>(null);
  const [meta, setMeta] = React.useState<{ url: string; seconds: number | null } | null>(null);
  React.useEffect(() => {
    if (!value) return setMeta(null);
    const url = URL.createObjectURL(value);
    setMeta({ url, seconds: null });
    return () => URL.revokeObjectURL(url);
  }, [value]);
  const s = meta?.seconds;
  const lengthOk = s == null || (s >= 5 && s <= 10);
  const tooBig = !!value && value.size > 60e6;
  return (
    <div className="rounded-lg border border-border bg-surface">
      <div className="flex items-center justify-between gap-2 border-b border-border px-4 py-2.5">
        <div className="flex items-center gap-2">
          <h3 className="text-[13px] font-semibold">{title}</h3>
          <Badge tone="neutral">optional</Badge>
        </div>
        {value ? (
          <Button size="sm" variant="ghost" onClick={() => onChange(null)} aria-label={`Remove ${title}`}>
            <Trash2 aria-hidden /> Remove
          </Button>
        ) : null}
      </div>
      <input
        ref={ref}
        type="file"
        accept="video/mp4,video/quicktime,video/webm"
        capture="environment"
        className="sr-only"
        tabIndex={-1}
        aria-label={`Choose file: ${title.toLowerCase()}`}
        onChange={(e) => onChange(e.target.files?.[0] ?? null)}
      />
      {!value ? (
        <div className="m-3 flex flex-col gap-3 rounded-md border border-dashed border-border-strong px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
          <p className="max-w-md text-[12.5px] leading-5 text-muted">{hint}</p>
          <Button size="sm" variant="outline" onClick={() => ref.current?.click()}>
            <Video aria-hidden /> Record or choose video
          </Button>
        </div>
      ) : (
        <div className="grid gap-4 p-3 sm:grid-cols-[160px_minmax(0,1fr)]">
          <video
            src={meta?.url}
            muted
            playsInline
            controls
            preload="metadata"
            aria-label={`${title} preview`}
            className="aspect-[4/3] w-full rounded-md border border-border bg-black object-contain"
            onLoadedMetadata={(e) => {
              // read now: React clears currentTarget before a state updater runs
              const seconds = e.currentTarget.duration;
              setMeta((m) => (m ? { ...m, seconds } : m));
            }}
          />
          <div className="space-y-1 text-[12.5px]">
            <p className="font-mono text-muted tnum">
              {value.name} · {(value.size / 1e6).toFixed(1)} MB{s != null && Number.isFinite(s) ? ` · ${s.toFixed(1)} s` : ""}
            </p>
            <p className={cn(lengthOk ? "text-muted" : "text-warn")}>
              {lengthOk ? "Keep the whole mat in view the whole time." : "Aim for 6–8 seconds: one slow circle around the part (the server accepts 5–10 s)."}
            </p>
            {tooBig ? <p className="text-bad">Over 60 MB, the server will refuse it. Record a shorter clip or at a lower resolution.</p> : null}
          </div>
        </div>
      )}
    </div>
  );
}
