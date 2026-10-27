"use client";

import { ImageOff, Minus, Plus } from "lucide-react";
import * as React from "react";
import { artifactUrl } from "@/lib/api";
import { cn } from "@/lib/utils";
import { Switch } from "../ui/toggle";
import { WipeSlider } from "./wipe-slider";

type Layer = { key: string; label: string; url: string | undefined };

/**
 * Photo with toggleable overlay layers (mask, measurements, residual heatmap) and zoom; or a wipe comparison of the photo
 * against the model's render overlay. Overlays are images produced by the server on the same rectified frame.
 */
export function PhotoPanel({ artifacts, className }: { artifacts: Record<string, string>; className?: string }) {
  const base = artifactUrl(artifacts.rectified ?? artifacts.photo);
  const layers: Layer[] = [
    { key: "mask_overlay", label: "Mask", url: artifactUrl(artifacts.mask_overlay) },
    { key: "measure_overlay", label: "Dimensions", url: artifactUrl(artifacts.measure_overlay) },
    { key: "residual_heatmap", label: "Residual heatmap", url: artifactUrl(artifacts.residual_heatmap) },
  ];
  const render = artifactUrl(artifacts.render_overlay);
  const [mode, setMode] = React.useState<"layers" | "compare">("layers");
  const [on, setOn] = React.useState<Record<string, boolean>>({ mask_overlay: true, measure_overlay: true, residual_heatmap: false });
  const [zoom, setZoom] = React.useState(1);
  const available = layers.filter((l) => l.url);

  return (
    <div className={cn("flex min-h-0 flex-col", className)}>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2 border-b border-border px-3 py-2">
        <div className="inline-flex rounded-md border border-border bg-surface-2 p-0.5" role="radiogroup" aria-label="Photo view">
          {(["layers", "compare"] as const).map((m) => (
            <button
              key={m}
              type="button"
              role="radio"
              aria-checked={mode === m}
              disabled={m === "compare" && !render}
              onClick={() => setMode(m)}
              className={cn(
                "h-6 rounded-[4px] px-2 text-[12px] font-medium text-muted disabled:opacity-40",
                mode === m && "bg-surface text-fg shadow-sm",
              )}
            >
              {m === "layers" ? "Photo" : "Photo ↔ model"}
            </button>
          ))}
        </div>
        {mode === "layers" ? (
          <>
            {available.map((l) => (
              <Switch key={l.key} label={l.label} checked={!!on[l.key]} onCheckedChange={(v) => setOn((s) => ({ ...s, [l.key]: v }))} className="text-[12px]" />
            ))}
            <div className="ml-auto flex items-center gap-0.5">
              <button type="button" aria-label="Zoom out" onClick={() => setZoom((z) => Math.max(1, z / 1.5))} disabled={zoom <= 1} className="inline-flex size-7 items-center justify-center rounded text-muted hover:bg-surface-2 disabled:opacity-40">
                <Minus className="size-3.5" aria-hidden />
              </button>
              <span className="w-10 text-center font-mono text-[11px] text-muted tnum">{Math.round(zoom * 100)}%</span>
              <button type="button" aria-label="Zoom in" onClick={() => setZoom((z) => Math.min(6, z * 1.5))} disabled={zoom >= 6} className="inline-flex size-7 items-center justify-center rounded text-muted hover:bg-surface-2 disabled:opacity-40">
                <Plus className="size-3.5" aria-hidden />
              </button>
            </div>
          </>
        ) : null}
      </div>
      <div className="relative min-h-[240px] flex-1 overflow-hidden bg-[var(--viewer-bg)]">
        {!base ? (
          <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 text-[13px] text-muted">
            <ImageOff className="size-6 text-subtle" aria-hidden />
            Photo appears after the capture stage.
          </div>
        ) : mode === "compare" && render ? (
          <WipeSlider before={base} after={render} beforeLabel="Photo" afterLabel="Model" className="absolute inset-0" />
        ) : (
          <div className="scrollbar-thin absolute inset-0 overflow-auto" tabIndex={0} aria-label="Photo with overlays (scroll to pan when zoomed)">
            <div className="relative" style={{ width: `${zoom * 100}%`, height: `${zoom * 100}%`, minHeight: "100%" }}>
              {/* eslint-disable-next-line @next/next/no-img-element -- API artifact */}
              <img src={base} alt="Part photo on the mat" className="absolute inset-0 size-full object-contain" />
              {available.map((l) =>
                on[l.key] ? (
                  // eslint-disable-next-line @next/next/no-img-element -- API overlay
                  <img key={l.key} src={l.url} alt={`${l.label} overlay`} className="absolute inset-0 size-full animate-fade-in object-contain" />
                ) : null,
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
