"use client";

import { ImageOff, Minus, Plus } from "lucide-react";
import * as React from "react";
import { artifactUrl } from "@/lib/api";
import type { ArtifactEvent } from "@/lib/api-types";
import { cn } from "@/lib/utils";
import { Switch } from "../ui/toggle";
import { WipeSlider } from "./wipe-slider";

export type ViewImages = Partial<Record<"photo" | "rectified" | "mask_overlay" | "measure_overlay" | "residual_heatmap" | "render_overlay", string>>;

const VIEW_RE = /^(top|side|mating)\b/i;
const RESIDUAL_RE = /residual_(top|side|mating)/i;

/** Group image artifacts by view (top / side / mating) using the server's labels; latest event per kind wins. */
export function imagesByView(events: ArtifactEvent[], fallback: Record<string, string>): Record<string, ViewImages> {
  const out: Record<string, ViewImages> = {};
  const kinds = new Set(["photo", "rectified", "mask_overlay", "measure_overlay", "residual_heatmap", "render_overlay"]);
  for (const e of events) {
    if (!kinds.has(e.kind)) continue;
    const view = (RESIDUAL_RE.exec(e.label)?.[1] ?? VIEW_RE.exec(e.label)?.[1] ?? "top").toLowerCase();
    (out[view] ??= {})[e.kind as keyof ViewImages] = e.url;
  }
  if (Object.keys(out).length === 0) {
    const v: ViewImages = {};
    for (const k of kinds) if (fallback[k]) v[k as keyof ViewImages] = fallback[k];
    if (Object.keys(v).length) out.top = v;
  }
  return out;
}

type Mode = "rectified" | "measured" | "residual" | "original" | "compare";

const MODES: { m: Mode; label: string; needs: (v: ViewImages) => boolean }[] = [
  { m: "rectified", label: "On the mat", needs: (v) => !!(v.rectified ?? v.photo) },
  { m: "measured", label: "Measured", needs: (v) => !!v.measure_overlay },
  { m: "residual", label: "Model vs photo", needs: (v) => !!v.residual_heatmap },
  { m: "compare", label: "Wipe", needs: (v) => !!(v.rectified && (v.render_overlay ?? v.mask_overlay)) },
  { m: "original", label: "Original", needs: (v) => !!v.photo },
];

/**
 * The photo side of the workspace: per view, the rectified photo with the part mask tinted on top (the mask draws in),
 * the measured-dimensions image, the verifier's model-vs-photo residual map, a wipe comparison and the original photo.
 */
export function PhotoPanel({ views, className }: { views: Record<string, ViewImages>; className?: string }) {
  const viewNames = Object.keys(views).sort((a, b) => ["top", "side", "mating"].indexOf(a) - ["top", "side", "mating"].indexOf(b));
  const [view, setView] = React.useState<string | null>(null);
  const active = view && views[view] ? view : (viewNames[0] ?? null);
  const v: ViewImages = (active && views[active]) || {};
  const available = MODES.filter((x) => x.needs(v));
  const [mode, setMode] = React.useState<Mode>("rectified");
  const current = available.some((x) => x.m === mode) ? mode : (available[0]?.m ?? "rectified");
  const [mask, setMask] = React.useState(true);
  const [zoom, setZoom] = React.useState(1);

  const base = artifactUrl(v.rectified ?? v.photo);
  const src =
    current === "measured"
      ? artifactUrl(v.measure_overlay)
      : current === "residual"
        ? artifactUrl(v.residual_heatmap)
        : current === "original"
          ? artifactUrl(v.photo)
          : base;
  const maskUrl = current === "rectified" && v.rectified ? artifactUrl(v.mask_overlay) : undefined;

  return (
    <div className={cn("flex min-h-0 flex-col", className)}>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2 border-b border-border px-3 py-2">
        {viewNames.length > 1 ? (
          <div className="inline-flex rounded-md border border-border bg-surface-2 p-0.5" role="radiogroup" aria-label="Photo view">
            {viewNames.map((n) => (
              <button
                key={n}
                type="button"
                role="radio"
                aria-checked={active === n}
                onClick={() => setView(n)}
                className={cn("h-6 rounded-[4px] px-2 text-[12px] font-medium capitalize text-muted", active === n && "bg-surface text-fg shadow-sm")}
              >
                {n}
              </button>
            ))}
          </div>
        ) : null}
        <div className="no-scrollbar flex min-w-0 items-center gap-0.5 overflow-x-auto" role="radiogroup" aria-label="Image">
          {available.map((x) => (
            <button
              key={x.m}
              type="button"
              role="radio"
              aria-checked={current === x.m}
              onClick={() => setMode(x.m)}
              className={cn(
                "h-7 shrink-0 rounded-md px-2 text-[12px] font-medium whitespace-nowrap text-muted hover:text-fg",
                current === x.m && "bg-surface-3 text-fg",
              )}
            >
              {x.label}
            </button>
          ))}
        </div>
        <div className="ml-auto flex items-center gap-2">
          {current === "rectified" && maskUrl ? <Switch label="Mask" checked={mask} onCheckedChange={setMask} className="text-[12px]" /> : null}
          {current !== "compare" ? (
            <div className="flex items-center gap-0.5">
              <button type="button" aria-label="Zoom out" onClick={() => setZoom((z) => Math.max(1, z / 1.5))} disabled={zoom <= 1} className="inline-flex size-7 items-center justify-center rounded text-muted hover:bg-surface-2 disabled:opacity-40">
                <Minus className="size-3.5" aria-hidden />
              </button>
              <span className="w-9 text-center font-mono text-[11px] text-muted tnum">{Math.round(zoom * 100)}%</span>
              <button type="button" aria-label="Zoom in" onClick={() => setZoom((z) => Math.min(6, z * 1.5))} disabled={zoom >= 6} className="inline-flex size-7 items-center justify-center rounded text-muted hover:bg-surface-2 disabled:opacity-40">
                <Plus className="size-3.5" aria-hidden />
              </button>
            </div>
          ) : null}
        </div>
      </div>
      <div className="relative min-h-[240px] flex-1 overflow-hidden bg-[var(--viewer-bg)]">
        {!src ? (
          <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 text-[13px] text-muted">
            <ImageOff className="size-6 text-subtle" aria-hidden />
            Photos appear after the capture stage.
          </div>
        ) : current === "compare" && base ? (
          <WipeSlider
            before={base}
            after={artifactUrl(v.render_overlay ?? v.mask_overlay)!}
            beforeLabel="Photo"
            afterLabel={v.render_overlay ? "Model" : "Mask"}
            className="absolute inset-0"
          />
        ) : (
          <div className="scrollbar-thin absolute inset-0 overflow-auto" tabIndex={0} role="region" aria-label="Photo (scroll to pan when zoomed)">
            <div className="relative" style={{ width: `${zoom * 100}%`, height: `${zoom * 100}%`, minHeight: "100%" }}>
              {/* eslint-disable-next-line @next/next/no-img-element -- API artifact */}
              <img key={src} src={src} alt={`${active ?? ""} view: ${MODES.find((x) => x.m === current)?.label ?? ""}`} className="absolute inset-0 size-full animate-fade-in object-contain p-2" />
              {maskUrl && mask ? (
                <div
                  aria-hidden
                  className="absolute inset-2 animate-fade-in bg-accent/55"
                  style={{
                    maskImage: `url(${maskUrl})`,
                    maskMode: "luminance",
                    maskSize: "contain",
                    maskRepeat: "no-repeat",
                    maskPosition: "center",
                  }}
                />
              ) : null}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
