"use client";

import { ImageOff, Minus, Plus } from "lucide-react";
import * as React from "react";
import { artifactUrl } from "@/lib/api";
import type { ArtifactEvent } from "@/lib/api-types";
import { cn } from "@/lib/utils";
import { Switch } from "../ui/toggle";
import { WipeSlider } from "./wipe-slider";
import { radioGroupKeys } from "@/lib/a11y";

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

type BBox = { x0: number; y0: number; x1: number; y1: number };

/** Normalised bounding box of the white pixels in a mask image (same frame as the rectified photo). */
function useMaskBBox(url: string | undefined): BBox | null {
  const [bbox, setBbox] = React.useState<BBox | null>(null);
  React.useEffect(() => {
    setBbox(null);
    if (!url) return;
    let alive = true;
    const img = new Image();
    img.decoding = "async";
    img.onload = () => {
      if (!alive) return;
      const W = img.naturalWidth;
      const H = img.naturalHeight;
      const k = Math.min(1, 480 / Math.max(W, H));
      const w = Math.max(1, Math.round(W * k));
      const h = Math.max(1, Math.round(H * k));
      const c = document.createElement("canvas");
      c.width = w;
      c.height = h;
      const ctx = c.getContext("2d", { willReadFrequently: true });
      if (!ctx) return;
      ctx.drawImage(img, 0, 0, w, h);
      const d = ctx.getImageData(0, 0, w, h).data;
      let x0 = w, y0 = h, x1 = -1, y1 = -1;
      for (let y = 0; y < h; y++)
        for (let x = 0; x < w; x++)
          if (d[(y * w + x) * 4]! > 127) {
            if (x < x0) x0 = x;
            if (x > x1) x1 = x;
            if (y < y0) y0 = y;
            if (y > y1) y1 = y;
          }
      if (x1 >= 0) setBbox({ x0: x0 / w, y0: y0 / h, x1: (x1 + 1) / w, y1: (y1 + 1) / h });
    };
    img.src = url;
    return () => {
      alive = false;
    };
  }, [url]);
  return bbox;
}

/**
 * An image laid out to fill its box (aspect kept): either the whole image, or a crop around `bbox` with margin, times
 * `zoom`. The optional mask tint uses exactly the same geometry so it stays registered with the photo.
 */
function FramedImage({ src, alt, bbox, fit, zoom, maskUrl }: { src: string; alt: string; bbox: BBox | null; fit: "part" | "full"; zoom: number; maskUrl?: string }) {
  const box = React.useRef<HTMLDivElement>(null);
  const [size, setSize] = React.useState({ w: 0, h: 0 });
  const [nat, setNat] = React.useState<{ w: number; h: number } | null>(null);
  React.useEffect(() => {
    const el = box.current;
    if (!el) return;
    const ro = new ResizeObserver(([e]) => e && setSize({ w: e.contentRect.width, h: e.contentRect.height }));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  React.useEffect(() => setNat(null), [src]);
  let style: React.CSSProperties = { position: "absolute", inset: 0, width: "100%", height: "100%", objectFit: "contain" };
  if (nat && size.w > 0 && size.h > 0) {
    let cx0 = 0, cy0 = 0, cx1 = nat.w, cy1 = nat.h;
    if (fit === "part" && bbox) {
      const bw = (bbox.x1 - bbox.x0) * nat.w;
      const bh = (bbox.y1 - bbox.y0) * nat.h;
      const m = Math.max(0.45 * Math.max(bw, bh), 0.04 * Math.max(nat.w, nat.h));
      cx0 = Math.max(0, bbox.x0 * nat.w - m);
      cy0 = Math.max(0, bbox.y0 * nat.h - m);
      cx1 = Math.min(nat.w, bbox.x1 * nat.w + m);
      cy1 = Math.min(nat.h, bbox.y1 * nat.h + m);
    }
    const pad = 8;
    const scale = Math.min((size.w - 2 * pad) / (cx1 - cx0), (size.h - 2 * pad) / (cy1 - cy0)) * zoom;
    const cx = (cx0 + cx1) / 2;
    const cy = (cy0 + cy1) / 2;
    style = { position: "absolute", left: size.w / 2 - cx * scale, top: size.h / 2 - cy * scale, width: nat.w * scale, height: nat.h * scale, maxWidth: "none" };
  }
  return (
    <div ref={box} className="absolute inset-0 overflow-hidden">
      {/* eslint-disable-next-line @next/next/no-img-element -- API artifact */}
      <img key={src} src={src} alt={alt} style={style} className="animate-fade-in" onLoad={(e) => setNat({ w: e.currentTarget.naturalWidth, h: e.currentTarget.naturalHeight })} />
      {maskUrl && nat ? (
        <div
          aria-hidden
          className="animate-fade-in bg-accent/55"
          style={{ ...style, objectFit: undefined, maskImage: `url(${maskUrl})`, maskMode: "luminance", maskSize: "100% 100%", maskRepeat: "no-repeat" }}
        />
      ) : null}
    </div>
  );
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
  const bbox = useMaskBBox(v.rectified ? artifactUrl(v.mask_overlay) : undefined);
  const [fit, setFit] = React.useState<"part" | "full">("part");
  const canCrop = current === "rectified" && !!bbox;

  return (
    <div className={cn("flex min-h-0 flex-col", className)}>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2 border-b border-border px-3 py-2">
        {viewNames.length > 1 ? (
          <div className="inline-flex rounded-md border border-border bg-surface-2 p-0.5" role="radiogroup" onKeyDown={radioGroupKeys} aria-label="Photo view">
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
        <div className="no-scrollbar flex min-w-0 items-center gap-0.5 overflow-x-auto" role="radiogroup" onKeyDown={radioGroupKeys} aria-label="Image">
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
          {canCrop ? (
            <div className="inline-flex rounded-md border border-border bg-surface-2 p-0.5" role="radiogroup" onKeyDown={radioGroupKeys} aria-label="Framing">
              {(["part", "full"] as const).map((f) => (
                <button
                  key={f}
                  type="button"
                  role="radio"
                  aria-checked={fit === f}
                  onClick={() => {
                    setFit(f);
                    setZoom(1);
                  }}
                  className={cn("h-6 rounded-[4px] px-2 text-[12px] font-medium text-muted", fit === f && "bg-surface text-fg shadow-sm")}
                >
                  {f === "part" ? "Part" : "Full mat"}
                </button>
              ))}
            </div>
          ) : null}
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
          <div className="absolute inset-0" role="region" aria-label={`${active ?? ""} view, ${canCrop && fit === "part" ? "cropped to the part" : "full image"}`}>
            <FramedImage
              src={src}
              alt={`${active ?? ""} view: ${MODES.find((x) => x.m === current)?.label ?? ""}`}
              bbox={bbox}
              fit={canCrop ? fit : "full"}
              zoom={zoom}
              maskUrl={maskUrl && mask ? maskUrl : undefined}
            />
          </div>
        )}
      </div>
    </div>
  );
}
