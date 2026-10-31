"use client";

/**
 * Hero "Fig. 1": a stored run replayed as an inspection drawing. The screen mat's markers light up, the measured outline
 * draws in, dimension lines draw and their values count up to the run's own numbers, the drawing crossfades to the 3D
 * model, and the verifier's stamp lands. Every number is read from the stored run (labelled "recorded run"); with
 * reduced motion the finished drawing is shown at once. Never empty: without a stored run it shows the bare mat.
 */
import { ArrowUpRight, RotateCcw } from "lucide-react";
import dynamic from "next/dynamic";
import Link from "next/link";
import * as React from "react";
import { fmtNum, splitTitle } from "@/lib/format";
import { useMediaQuery } from "@/lib/hooks";
import { useCountUp, usePrefersReducedMotion } from "@/lib/motion";
import { cn } from "@/lib/utils";
import { LatchGlyph, MAT_H, MAT_W, MatScreen, PartOnMat } from "../art/mat-figure";
import { TitleBlock, useSvgId } from "../art/primitives";
import { ErrorState } from "../ui/error-state";
import { useStoredRun } from "./use-figure-run";

const CadViewer = dynamic(() => import("../viewer/cad-viewer").then((m) => m.CadViewer), { ssr: false });

/** Stage timings (ms after the run's data arrives), one hero step apart. */
const T = { outline: 250, dims: 1350, model: 2600, stamp: 3500 } as const;

export function HeroFigure({ sheet }: { sheet: { n: number; of: number } }) {
  const uid = useSvgId("fig1");
  const reduced = usePrefersReducedMotion();
  const small = useMediaQuery("(max-width: 767px)");
  const { fig, state, replays, job } = useStoredRun("figure");
  const [stage, setStage] = React.useState(0);
  const [nonce, setNonce] = React.useState(0);
  const [view, setView] = React.useState<"drawing" | "model" | null>(null);
  const [modelMounted, setModelMounted] = React.useState(false);
  const canModel = !!fig?.viewUrl && !small;

  React.useEffect(() => {
    if (!fig) return;
    if (reduced) {
      setStage(4);
      return;
    }
    setStage(0);
    const ids = [
      setTimeout(() => setStage(1), T.outline),
      setTimeout(() => setStage(2), T.dims),
      setTimeout(() => setStage(3), T.model),
      setTimeout(() => setStage(4), T.stamp),
    ];
    return () => ids.forEach(clearTimeout);
  }, [fig, reduced, nonce]);

  const autoModel = stage >= 3 && canModel && !reduced;
  const showModel = canModel && (view ? view === "model" : autoModel);
  // mount the 3D view (hidden) as soon as the run arrives, so its geometry is loaded before the crossfade
  React.useEffect(() => {
    if (showModel || (canModel && !reduced && stage >= 1)) setModelMounted(true);
  }, [showModel, canModel, reduced, stage]);

  const lengthText = fig?.lengthMm != null ? `${fmtNum(fig.lengthMm)} mm` : null;
  const widthText = fig?.widthMm != null ? `${fmtNum(fig.widthMm)} mm` : null;
  const hole = fig?.holes[0];
  const holeText = hole ? `Ø ${fmtNum(hole.diameterMm)} mm` : null;
  const length = useCountUp(lengthText, stage >= 2);
  const width = useCountUp(widthText, stage >= 2);
  const holeLabel = useCountUp(holeText, stage >= 2);

  const title = fig ? splitTitle(fig.title.replace(/\s*·\s*review round \d+\s*$/i, "")).title : null;
  const err = fig?.maxErrorMm;
  const lim = fig?.limitMm;
  const verdict = fig ? (fig.verified ? "verified" : (fig.status ?? "best_effort").replace("_", " ")) : null;
  const summary = fig
    ? `Fig. 1, ${title} measured on the screen mat${lengthText ? `: ${lengthText}` : ""}${widthText ? ` by ${widthText}` : ""}${holeText ? `, hole ${holeText}` : ""}. Code's verdict: ${verdict}${err != null ? `, max error ${fmtNum(err)} mm` : ""}${lim != null ? ` against a ${fmtNum(lim)} mm limit` : ""}. Recorded run.`
    : state === "pending"
      ? "Fig. 1: the screen mat, loading a recorded run."
      : "Fig. 1: the screen mat with a generic part; no stored run on this server.";
  const fade = reduced ? "duration-[120ms]" : "duration-[var(--dur-hero-step)]";

  return (
    <figure className="relative">
      <div className="relative">
        {/* corner ticks: the figure sits on the sheet like a drawing view */}
        <span aria-hidden className="pointer-events-none absolute -top-2 -left-2 size-4 border-t border-l border-ink/40" />
        <span aria-hidden className="pointer-events-none absolute -top-2 -right-2 size-4 border-t border-r border-ink/40" />
        <span aria-hidden className="pointer-events-none absolute -bottom-2 -left-2 size-4 border-b border-l border-ink/40" />
        <span aria-hidden className="pointer-events-none absolute -right-2 -bottom-2 size-4 border-r border-b border-ink/40" />
        <svg viewBox={`0 0 ${MAT_W} ${MAT_H}`} className="block h-auto w-full drop-shadow-sm" role="img" aria-label={summary}>
          <MatScreen uid={uid} lit={!reduced && (state === "pending" || stage === 0)}>
            {fig && fig.outline.length > 2 ? (
              <g className={cn("transition-opacity ease-[var(--ease-out)]", fade, showModel ? "opacity-0" : "opacity-100")}>
                <PartOnMat
                  key={nonce}
                  uid={uid}
                  part={{ outline: fig.outline, holes: fig.holes }}
                  labels={{ length, width, hole: holeLabel }}
                  drawn={stage >= 1}
                  dims={stage >= 2}
                />
              </g>
            ) : state === "empty" || state === "error" ? (
              <LatchGlyph />
            ) : null}
            <text x={84} y={MAT_H - 34} className="font-mono" fontSize="10" letterSpacing="0.12em" fill="var(--fg-subtle)">
              {state === "pending" ? "READING A RECORDED RUN…" : state === "ok" ? "TOP VIEW · MEASURED ON THE MAT" : "NO STORED RUN · GENERIC PART"}
            </text>
          </MatScreen>
        </svg>

        {canModel && modelMounted ? (
          <div
            className={cn(
              "absolute overflow-hidden rounded-[6px] transition-opacity ease-[var(--ease-out)]",
              fade,
              showModel ? "opacity-100" : "pointer-events-none opacity-0",
            )}
            style={{
              left: `${(78 / MAT_W) * 100}%`,
              top: `${(76 / MAT_H) * 100}%`,
              width: `${((MAT_W - 156) / MAT_W) * 100}%`,
              height: `${((MAT_H - 152) / MAT_H) * 100}%`,
            }}
            aria-hidden={!showModel}
          >
            <CadViewer viewUrl={fig?.viewUrl} minimal className="h-full w-full" label={`3D model of ${title ?? "the part"}`} />
          </div>
        ) : null}

        {fig && stage >= 4 && err != null ? (
          <div
            key={`stamp-${nonce}`}
            className={cn(
              "absolute top-[17%] right-[6.5%] flex -rotate-6 flex-col items-center rounded-md border-2 bg-surface/90 px-2.5 py-1 font-mono leading-tight shadow-sm backdrop-blur-[2px] sm:px-3 sm:py-1.5",
              fig.verified ? "border-stamp text-stamp" : "border-warn text-warn",
              !reduced && "animate-stamp",
            )}
          >
            <span className="text-[11px] font-bold tracking-[0.18em] uppercase sm:text-[13px]">{verdict}</span>
            <span className="text-[13px] font-semibold tnum sm:text-[16px]">{fmtNum(err)} mm</span>
            {lim != null ? <span className="text-[9.5px] tracking-wide text-muted tnum sm:text-[10.5px]">limit {fmtNum(lim)} mm</span> : null}
          </div>
        ) : null}
      </div>

      <figcaption className="mt-4 space-y-2.5">
        {state === "error" ? <ErrorState error={replays.error ?? job.error} compact what="the recorded run" onRetry={() => void (replays.isError ? replays.refetch() : job.refetch())} /> : null}
        <TitleBlock
          className="rounded-md"
          cells={[
            { k: "Fig. 1 · part", v: title ?? "—", w: 1.3 },
            { k: "Source", v: fig ? `recorded run · ${fig.origin}` : "—", w: 1.9 },
            { k: "Scale", v: "1:1", w: 0.6 },
            { k: "Tolerance", v: lim != null ? `±${fmtNum(lim)} mm` : "—", w: 1 },
            { k: "Sheet", v: `${sheet.n} / ${sheet.of}`, w: 0.7 },
          ]}
        />
        <div className="flex flex-wrap items-center justify-between gap-2 text-[12px]">
          <div className="inline-flex rounded-md border border-border bg-surface p-0.5" role="group" aria-label="Figure view">
            {(["drawing", "model"] as const).map((v) => {
              const on = v === "model" ? showModel : !showModel;
              return (
                <button
                  key={v}
                  type="button"
                  aria-pressed={on}
                  disabled={v === "model" && !canModel}
                  onClick={() => setView(v)}
                  className={cn("press h-7 rounded-[5px] px-2.5 font-medium text-muted hover:text-fg disabled:opacity-40", on && "bg-surface-2 text-fg")}
                >
                  {v === "drawing" ? "Drawing" : "3D model"}
                </button>
              );
            })}
          </div>
          <div className="flex items-center gap-3">
            {!reduced && fig ? (
              <button
                type="button"
                onClick={() => (setView(null), setNonce((n) => n + 1))}
                className="press inline-flex items-center gap-1 rounded-md px-1.5 py-1 font-medium text-muted hover:bg-surface-2 hover:text-fg"
              >
                <RotateCcw className="size-3.5" aria-hidden /> Replay figure
              </button>
            ) : null}
            {fig ? (
              <Link href={`/jobs/${encodeURIComponent(fig.id)}`} className="inline-flex items-center gap-1 font-medium text-accent-text hover:underline">
                Open the run <ArrowUpRight className="size-3.5" aria-hidden />
              </Link>
            ) : null}
          </div>
        </div>
      </figcaption>
    </figure>
  );
}
