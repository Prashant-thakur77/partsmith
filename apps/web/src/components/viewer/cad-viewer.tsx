"use client";

import { useQuery, keepPreviousData } from "@tanstack/react-query";
import { Axis3D, Box, Crosshair, Grid3x3, Maximize, Palette, Rotate3D, Scissors, Spline } from "lucide-react";
import dynamic from "next/dynamic";
import * as React from "react";
import type * as THREE from "three";
import { fmtNum } from "@/lib/format";
import { cn } from "@/lib/utils";
import { useMediaQuery } from "@/lib/hooks";
import { Badge } from "../ui/badge";
import { Button } from "../ui/button";
import { Skeleton } from "../ui/skeleton";
import { Slider } from "../ui/slider";
import { Spinner } from "../ui/spinner";
import { Toggle } from "../ui/toggle";
import { Tooltip } from "../ui/tooltip";
import { SOURCE_KINDS, SOURCE_STYLES } from "@/lib/value-sources";
import { SourceIcon, SourceSwatch, sourceColor } from "../jobs/source-key";
import type { SceneSourceMark, SectionState, ViewerColors } from "./cad-scene";
import { fetchViewData, type ViewData } from "./view-data";
import { radioGroupKeys } from "@/lib/a11y";

const CadScene = dynamic(() => import("./cad-scene"), { ssr: false, loading: () => <Skeleton className="absolute inset-0 rounded-none" /> });

function readColors(): ViewerColors {
  const cs = getComputedStyle(document.documentElement);
  const v = (n: string, f: string) => cs.getPropertyValue(n).trim() || f;
  const dark = document.documentElement.dataset.theme === "dark";
  return {
    part: v("--viewer-part", "#d9d9d6"),
    edge: v("--viewer-edge", "#2b2b2b"),
    cut: dark ? "#f0803c" : "#f26a21",
    grid: dark ? "#2a2a2a" : "#dcdcdc",
    gridStrong: dark ? "#3a3a3a" : "#bdbdbd",
    measure: dark ? "#ff9a52" : "#e2550f",
    dark,
  };
}

function useViewerColors(): ViewerColors | null {
  const [c, setC] = React.useState<ViewerColors | null>(null);
  React.useEffect(() => {
    const update = () => setC(readColors());
    update();
    window.addEventListener("partsmith:theme", update);
    const mo = new MutationObserver(update);
    mo.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    return () => {
      window.removeEventListener("partsmith:theme", update);
      mo.disconnect();
    };
  }, []);
  return c;
}

function webglAvailable(): boolean {
  try {
    const c = document.createElement("canvas");
    return !!(c.getContext("webgl2") ?? c.getContext("webgl"));
  } catch {
    return false;
  }
}

class SceneBoundary extends React.Component<{ children: React.ReactNode; fallback: React.ReactNode }, { failed: boolean }> {
  override state = { failed: false };
  static getDerivedStateFromError() {
    return { failed: true };
  }
  override render() {
    return this.state.failed ? this.props.fallback : this.props.children;
  }
}

/**
 * CAD viewer for the worker's `view.json`. Keeps the previous model on screen while a re-bake loads (no camera jump),
 * so dragging a knob feels like editing, not reloading.
 */
export function CadViewer({
  viewUrl,
  className,
  label = "3D model",
  busy = false,
  emptyText = "No model yet.",
  toolbar = true,
  overlay,
  poster,
  poster2x,
  focus,
  sources,
}: {
  viewUrl: string | null | undefined;
  className?: string;
  label?: string;
  busy?: boolean;
  emptyText?: string;
  toolbar?: boolean;
  overlay?: React.ReactNode;
  /** Image shown until the 3D scene is ready (e.g. the part's thumbnail); three.js loads when visible and idle. */
  poster?: string | null;
  /** 2× poster (used on large screens; phones get the 1× file). */
  poster2x?: string | null;
  /** Agent focus: the camera flies to `at` (part frame, mm) and a marker pulses; `label` is shown as a caption. */
  focus?: { at: [number, number, number]; key: string; label?: string } | null;
  /** "Colour by source": values drawn on the model, tinted by where they came from. Omit to hide the toggle. */
  sources?: { marks: SceneSourceMark[]; on: boolean; onToggle: (on: boolean) => void; onSelect: (id: string) => void } | null;
}) {
  const boxRef = React.useRef<HTMLDivElement>(null);
  const [armed, setArmed] = React.useState(false);
  // Phones: 3D loads on tap (saves data/battery, and a full-width canvas would otherwise trap page scrolling).
  const small = useMediaQuery("(max-width: 767px)");
  React.useEffect(() => {
    if (armed || small) return;
    const el = boxRef.current;
    if (!el) return;
    let idle: number | undefined;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const arm = () => {
      const w = window as Window & { requestIdleCallback?: (cb: () => void, o?: { timeout: number }) => number };
      if (w.requestIdleCallback) idle = w.requestIdleCallback(() => setArmed(true), { timeout: 2500 });
      else timer = setTimeout(() => setArmed(true), 600);
    };
    const io = new IntersectionObserver((entries) => {
      if (entries.some((e) => e.isIntersecting)) {
        io.disconnect();
        arm();
      }
    });
    io.observe(el);
    const now = () => setArmed(true);
    el.addEventListener("pointerdown", now, { once: true });
    el.addEventListener("focusin", now, { once: true });
    return () => {
      io.disconnect();
      el.removeEventListener("pointerdown", now);
      el.removeEventListener("focusin", now);
      const w = window as Window & { cancelIdleCallback?: (id: number) => void };
      if (idle !== undefined) w.cancelIdleCallback?.(idle);
      if (timer) clearTimeout(timer);
    };
  }, [armed, small]);
  const q = useQuery<ViewData>({
    queryKey: ["view", viewUrl],
    queryFn: ({ signal }) => fetchViewData(viewUrl!, signal),
    enabled: !!viewUrl && armed,
    placeholderData: keepPreviousData,
    staleTime: Infinity,
    retry: 1,
  });
  const colors = useViewerColors();
  const [gl, setGl] = React.useState<boolean | null>(null);
  React.useEffect(() => setGl(webglAvailable()), []);
  const [ortho, setOrtho] = React.useState(true);
  const [edges, setEdges] = React.useState(true);
  const [grid, setGrid] = React.useState(true);
  const [section, setSection] = React.useState<SectionState>({ enabled: false, axis: "z", t: 0.5, flip: false });
  const [measuring, setMeasuring] = React.useState(false);
  const [points, setPoints] = React.useState<THREE.Vector3[]>([]);
  const [fitNonce, setFitNonce] = React.useState(0);
  const [lost, setLost] = React.useState(false);

  React.useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setMeasuring(false);
        setPoints([]);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const data = q.data;
  const dims = data ? [0, 1, 2].map((i) => data.max[i]! - data.min[i]!) : null;
  const pick = React.useCallback((p: THREE.Vector3) => setPoints((prev) => (prev.length >= 2 ? [p] : [...prev, p])), []);

  const fallback = (
    <div className="absolute inset-0 flex items-center justify-center p-6 text-center text-[13px] text-muted">
      The 3D view needs WebGL, which this browser has turned off. Downloads still work.
    </div>
  );

  return (
    <div
      ref={boxRef}
      role="group"
      aria-label={label}
      className={cn("relative isolate overflow-hidden bg-[var(--viewer-bg)] bg-dots", className)}
    >
      {data && colors && gl && !lost ? (
        <SceneBoundary fallback={fallback}>
          <div className="absolute inset-0" aria-hidden>
            <CadScene
              data={data}
              ortho={ortho}
              showEdges={edges}
              showGrid={grid}
              section={section}
              measuring={measuring}
              points={points}
              onPick={pick}
              fitNonce={fitNonce}
              colors={colors}
              onContextLost={() => setLost(true)}
              focus={focus ? { at: focus.at, key: focus.key } : null}
              sourceMarks={sources?.on ? sources.marks : null}
              onSelectSource={sources?.onSelect}
            />
          </div>
        </SceneBoundary>
      ) : gl === false || lost ? (
        fallback
      ) : q.isError ? (
        <div className="absolute inset-0 flex items-center justify-center p-6 text-center text-[13px] text-muted">
          Could not load the model geometry ({q.error instanceof Error ? q.error.message : "error"}).
        </div>
      ) : viewUrl && !armed && small ? (
        <>
          {poster ? (
            // eslint-disable-next-line @next/next/no-img-element -- API thumbnail used as the LCP poster
            <img src={poster} srcSet={poster2x ? `${poster} 640w, ${poster2x} 1280w` : undefined} sizes="(max-width: 767px) 340px, 720px" alt="" aria-hidden className="absolute inset-0 size-full object-contain p-6" fetchPriority="high" decoding="async" />
          ) : null}
          <div className="absolute inset-0 flex items-center justify-center">
            <Button variant="outline" size="sm" className="bg-surface/95 shadow-md" onClick={() => setArmed(true)}>
              <Rotate3D aria-hidden /> View in 3D
            </Button>
          </div>
        </>
      ) : viewUrl && poster && (!armed || q.isPending || !colors) ? (
        <>
          {/* eslint-disable-next-line @next/next/no-img-element -- API thumbnail used as the LCP poster */}
          <img src={poster} srcSet={poster2x ? `${poster} 640w, ${poster2x} 1280w` : undefined} sizes="(max-width: 767px) 340px, 720px" alt="" aria-hidden className="absolute inset-0 size-full object-contain p-6" fetchPriority="high" decoding="async" />
          <span className="absolute bottom-3 left-3 rounded-md border border-border bg-surface/90 px-2 py-1 text-[11px] text-muted shadow-sm">
            Loading 3D…
          </span>
        </>
      ) : viewUrl && (!armed || q.isPending || !colors) ? (
        <div className="absolute inset-0 flex flex-col items-center justify-center gap-3">
          <Box className="size-8 animate-pulse text-subtle" aria-hidden />
          <span className="text-[12px] text-muted">Loading geometry…</span>
        </div>
      ) : (
        <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 p-6 text-center">
          <Box className="size-8 text-subtle" aria-hidden />
          <span className="text-[13px] text-muted">{emptyText}</span>
        </div>
      )}

      {overlay}

      {(busy || q.isFetching) && data ? (
        <div className="absolute top-3 left-1/2 z-10 -translate-x-1/2">
          <Badge tone="neutral" className="h-6 gap-1.5 bg-surface px-2 shadow-sm">
            <Spinner className="size-3" label="Rebuilding" /> rebuilding
          </Badge>
        </div>
      ) : null}

      {dims ? (
        <div className="pointer-events-none absolute right-3 bottom-3 z-10 rounded-md border border-border bg-surface/90 px-2 py-1 font-mono text-[11px] text-muted tnum shadow-sm backdrop-blur">
          {fmtNum(dims[0]!, 1)} × {fmtNum(dims[1]!, 1)} × {fmtNum(dims[2]!, 1)} mm
        </div>
      ) : null}

      {sources?.on && data ? <MiniSourceKey marks={sources.marks} /> : null}

      {focus?.label && data ? (
        <div className={cn("pointer-events-none absolute left-3 z-10", sources?.on ? "top-24" : "top-14", "max-w-[70%] rounded-md bg-inverse px-2.5 py-1 text-[12px] text-inverse-fg shadow-md")} role="status">
          Agent is looking at: {focus.label}
        </div>
      ) : null}

      {measuring ? (
        <div className="pointer-events-none absolute bottom-14 left-1/2 z-10 -translate-x-1/2 rounded-md bg-inverse px-2.5 py-1.5 text-[12px] text-inverse-fg shadow-md">
          {points.length < 2 ? `Click point ${points.length + 1} of 2 on the part · Esc to stop` : "Click again to start a new measurement"}
        </div>
      ) : null}

      {toolbar && data ? (
        <div className="absolute top-3 right-3 z-10 flex flex-col items-end gap-2">
          <div
            role="toolbar"
            aria-label="Viewer tools"
            className="flex items-center gap-0.5 rounded-lg border border-border bg-surface/95 p-0.5 shadow-sm backdrop-blur"
          >
            <Tooltip content="Fit to view">
              <button
                type="button"
                aria-label="Fit to view"
                onClick={() => setFitNonce((n) => n + 1)}
                className="inline-flex size-8 items-center justify-center rounded-md text-muted hover:bg-surface-2 hover:text-fg"
              >
                <Maximize className="size-4" aria-hidden />
              </button>
            </Tooltip>
            <Tooltip content={ortho ? "Orthographic — switch to perspective" : "Perspective — switch to orthographic"}>
              <Toggle pressed={ortho} onPressedChange={setOrtho} aria-label="Orthographic camera" className="size-8 px-0">
                <Axis3D aria-hidden />
              </Toggle>
            </Tooltip>
            <Tooltip content="B-rep edges">
              <Toggle pressed={edges} onPressedChange={setEdges} aria-label="Show edges" className="size-8 px-0">
                <Spline aria-hidden />
              </Toggle>
            </Tooltip>
            <Tooltip content="Millimetre grid">
              <Toggle pressed={grid} onPressedChange={setGrid} aria-label="Show grid" className="size-8 px-0">
                <Grid3x3 aria-hidden />
              </Toggle>
            </Tooltip>
            <Tooltip content="Section plane">
              <Toggle
                pressed={section.enabled}
                onPressedChange={(v) => setSection((s) => ({ ...s, enabled: v }))}
                aria-label="Section plane"
                className="size-8 px-0"
              >
                <Scissors aria-hidden />
              </Toggle>
            </Tooltip>
            <Tooltip content="Measure between two points">
              <Toggle
                pressed={measuring}
                onPressedChange={(v) => {
                  setMeasuring(v);
                  setPoints([]);
                }}
                aria-label="Measure"
                className="size-8 px-0"
              >
                <Crosshair aria-hidden />
              </Toggle>
            </Tooltip>
            {sources ? (
              <Tooltip content={sources.on ? "Colour by source: on (key below the model)" : "Colour by source: where each value came from"}>
                <Toggle pressed={sources.on} onPressedChange={sources.onToggle} aria-label="Colour by source" className="size-8 px-0">
                  <Palette aria-hidden />
                </Toggle>
              </Tooltip>
            ) : null}
          </div>
          {section.enabled ? (
            <div className="w-56 space-y-2.5 rounded-lg border border-border bg-surface/95 p-3 shadow-sm backdrop-blur">
              <div className="flex items-center justify-between">
                <span className="text-[12px] font-medium">Section</span>
                <div className="inline-flex rounded-md border border-border bg-surface-2 p-0.5" role="radiogroup" onKeyDown={radioGroupKeys} aria-label="Section axis">
                  {(["x", "y", "z"] as const).map((a) => (
                    <button
                      key={a}
                      type="button"
                      role="radio"
                      aria-checked={section.axis === a}
                      onClick={() => setSection((s) => ({ ...s, axis: a }))}
                      className={cn(
                        "h-6 w-7 rounded-[4px] font-mono text-[11px] uppercase text-muted",
                        section.axis === a && "bg-surface text-fg shadow-sm",
                      )}
                    >
                      {a}
                    </button>
                  ))}
                </div>
              </div>
              <Slider
                aria-label="Section position"
                min={0}
                max={1}
                step={0.005}
                value={[section.t]}
                onValueChange={(v) => setSection((s) => ({ ...s, t: v[0] ?? s.t }))}
              />
              {data ? (
                <div className="flex items-center justify-between font-mono text-[11px] text-muted tnum">
                  <span>
                    {section.axis} ={" "}
                    {fmtNum(
                      data.min[{ x: 0, y: 1, z: 2 }[section.axis]]! +
                        (data.max[{ x: 0, y: 1, z: 2 }[section.axis]]! - data.min[{ x: 0, y: 1, z: 2 }[section.axis]]!) * section.t,
                      2,
                    )}{" "}
                    mm
                  </span>
                  <button
                    type="button"
                    onClick={() => setSection((s) => ({ ...s, flip: !s.flip }))}
                    className="rounded px-1.5 py-0.5 font-sans text-[11px] text-muted hover:bg-surface-2 hover:text-fg"
                  >
                    Flip side
                  </button>
                </div>
              ) : null}
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

/** Compact key inside the viewer for the kinds on screen; the full, described key sits in the list below the model. */
function MiniSourceKey({ marks }: { marks: SceneSourceMark[] }) {
  const kinds = SOURCE_KINDS.filter((k) => marks.some((m) => m.kind === k));
  return (
    <div aria-hidden className="pointer-events-none absolute top-3 left-3 z-10 flex max-w-[60%] flex-wrap gap-x-2.5 gap-y-1 rounded-md border border-border bg-surface/95 px-2 py-1 shadow-sm backdrop-blur">
      {kinds.length ? (
        kinds.map((k) => {
          const c = sourceColor(k);
          return (
            <span key={k} className={cn("inline-flex items-center gap-1 text-[11px] font-medium", c.className)} style={c.style}>
              <SourceSwatch kind={k} />
              <SourceIcon kind={k} className="size-3" />
              {SOURCE_STYLES[k].label}
            </span>
          );
        })
      ) : (
        <span className="text-[11px] text-muted">No value can be placed on this model; see the list below.</span>
      )}
    </div>
  );
}
