"use client";

import { useMutation, useQuery } from "@tanstack/react-query";
import { ArrowLeft, BadgeCheck, Camera, Eye, Ruler, Smartphone, Upload, X, XOctagon } from "lucide-react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import * as React from "react";
import { CaptureReportView } from "@/components/fix/capture-report";
import { ScreenMat } from "@/components/mat/screen-mat";
import { PhoneHandoff } from "@/components/phone-handoff";
import { StageShell } from "@/components/mat/stage-shell";
import { useMatChoice } from "@/components/mat/use-mat-layout";
import { Button } from "@/components/ui/button";
import { ErrorState } from "@/components/ui/error-state";
import { Mm } from "@/components/ui/mm";
import { Skeleton } from "@/components/ui/skeleton";
import { Spinner } from "@/components/ui/spinner";
import { api, artifactUrl } from "@/lib/api";
import type { FitCheckResult, FitOutline } from "@/lib/api-types";
import type { ScreenCalibration } from "@/lib/calibration";
import type { StageTone } from "@/lib/stage";
import { fmtNum } from "@/lib/format";
import { useLiveFitChecks, type LiveFitCheck } from "@/lib/fit-events";
import { I18nRegion, LangToggle, useT } from "@/lib/i18n";
import { cn } from "@/lib/utils";

/** The metrology segmenter treats exactly this colour as background, so the outline never pollutes the fit-check mask. */
const OUTLINE = "#E0218A";

function OutlineSvg({ o }: { o: FitOutline }) {
  const pts = o.outline_mm.map(([x, y]) => `${x},${y}`).join(" ");
  const xs = o.outline_mm.map((p) => p[0]);
  const ys = o.outline_mm.map((p) => p[1]);
  const maxX = Math.max(...xs);
  const minY = Math.min(...ys);
  const size = Math.max(maxX - Math.min(...xs), Math.max(...ys) - minY);
  // Small parts: labels go in a legend beside the outline so they never sit on top of the part.
  const legend = size < 30;
  const font = legend ? 2.4 : Math.min(3, Math.max(2, size * 0.05));
  return (
    <g>
      <polygon points={pts} fill="none" stroke={OUTLINE} strokeWidth={0.35} strokeLinejoin="round" />
      {o.holes.map((h, i) => (
        <g key={i}>
          <circle cx={h.center_mm[0]} cy={h.center_mm[1]} r={h.diameter_mm / 2} fill="none" stroke={OUTLINE} strokeWidth={0.3} strokeDasharray="0.8 0.6" />
          <path d={`M${h.center_mm[0] - 1} ${h.center_mm[1]}h2M${h.center_mm[0]} ${h.center_mm[1] - 1}v2`} stroke={OUTLINE} strokeWidth={0.2} />
        </g>
      ))}
      {o.dims.map((d, i) => {
        const [x1, y1] = d.from_mm;
        const [x2, y2] = d.to_mm;
        const mx = (x1 + x2) / 2;
        const my = (y1 + y2) / 2;
        const ang = (Math.atan2(y2 - y1, x2 - x1) * 180) / Math.PI;
        const a = ang > 90 || ang < -90 ? ang + 180 : ang;
        return (
          <g key={i} stroke={OUTLINE} strokeWidth={0.18}>
            <line x1={x1} y1={y1} x2={x2} y2={y2} />
            {!legend ? (
              <text x={mx} y={my - font * 0.5} fill={OUTLINE} stroke="none" fontSize={font} fontFamily="var(--font-geist-mono), monospace" textAnchor="middle" transform={`rotate(${a} ${mx} ${my})`}>
                {d.label}
              </text>
            ) : null}
          </g>
        );
      })}
      {legend
        ? o.dims.map((d, i) => (
            <text key={i} x={maxX + 6} y={minY + font + i * font * 1.5} fill={OUTLINE} fontSize={font} fontFamily="var(--font-geist-mono), monospace">
              {d.label}
            </text>
          ))
        : null}
    </g>
  );
}

function ResultPanel({ r, onClose }: { r: FitCheckResult | LiveFitCheck; onClose: () => void }) {
  const { t } = useT();
  return (
    <div className="absolute inset-y-3 right-3 z-30 flex w-[min(400px,calc(100vw-24px))] flex-col overflow-hidden rounded-xl border border-border bg-surface text-fg shadow-lg" role="dialog" aria-label="Fit check result">
      <div className={cn("flex items-center justify-between gap-2 px-4 py-3", r.passed ? "bg-ok-soft" : "bg-bad-soft")}>
        <div className="flex items-center gap-2">
          {r.passed ? <BadgeCheck className="size-5 text-ok" aria-hidden /> : <XOctagon className="size-5 text-bad" aria-hidden />}
          <span className={cn("text-[15px] font-semibold", r.passed ? "text-ok" : "text-bad")}>{r.passed ? t("fit.pass") : t("fit.fail")}</span>
        </div>
        <button type="button" onClick={onClose} aria-label="Close result" className="rounded p-1 text-muted hover:bg-surface/60 hover:text-fg">
          <X className="size-4" aria-hidden />
        </button>
      </div>
      <div className="scrollbar-thin flex-1 space-y-4 overflow-y-auto p-4">
        {/* eslint-disable-next-line @next/next/no-img-element -- API overlay */}
        {r.overlay_url ? <img src={artifactUrl(r.overlay_url)} alt="Verifier overlay: real part versus model outline" className="w-full rounded-md border border-border" /> : null}
        <dl className="grid grid-cols-3 gap-2">
          <div className="rounded-md border border-border p-2">
            <dt className="text-[11px] text-muted">Max error</dt>
            <dd><Mm value={r.hausdorff_mm} /></dd>
          </div>
          <div className="rounded-md border border-border p-2">
            <dt className="text-[11px] text-muted">Mean</dt>
            <dd><Mm value={r.mean_mm} /></dd>
          </div>
          <div className="rounded-md border border-border p-2">
            <dt className="text-[11px] text-muted">IoU</dt>
            <dd className="font-mono text-[13px] tnum">{r.iou == null ? "—" : fmtNum(r.iou, 3)}</dd>
          </div>
        </dl>
        {r.reasons.length ? (
          <ul className="list-disc space-y-1 pl-4 text-[13px] text-muted">
            {r.reasons.map((x: string) => (
              <li key={x}>{x}</li>
            ))}
          </ul>
        ) : null}
        {r.capture ? <CaptureReportView report={r.capture} /> : null}
      </div>
    </div>
  );
}

function useFitUpload(id: string, matId: string | null) {
  return useMutation({ mutationFn: (file: File) => api.fitCheck(id, file, matId!) });
}

function FitStage({ id, cal, stage }: { id: string; cal: ScreenCalibration; stage: StageTone }) {
  const { t } = useT();
  const [showPhone, setShowPhone] = React.useState(false);
  const live = useLiveFitChecks(id);
  const latestLive = live.at(-1) ?? null;
  const { choice, isPending } = useMatChoice(cal.px_per_mm, null);
  const matId = choice?.layout.mat_id ?? null;
  const outline = useQuery({ queryKey: ["fit-outline", id, matId], queryFn: () => api.fitOutline(id, matId!), enabled: !!matId });
  const upload = useFitUpload(id, matId);
  const fileRef = React.useRef<HTMLInputElement>(null);
  const [showResult, setShowResult] = React.useState(true);

  if (isPending) return <Spinner className="text-white/60" label="Loading mat" />;
  if (!choice) return <p className="max-w-sm p-6 text-center text-[14px] text-white/80">{t("mat.tooSmall")}</p>;
  const shown = upload.data ?? latestLive;

  return (
    <>
      <div className="flex flex-col items-center gap-2">
        <ScreenMat layout={choice.layout} pxPerMm={cal.px_per_mm} rotated={choice.rotated} stage={stage} title="Screen mat with the model's outline at 1:1">
          {outline.data ? <OutlineSvg o={outline.data} /> : null}
        </ScreenMat>
        <p className="text-[11px] text-white/45">
          {outline.isPending
            ? "Loading the model outline…"
            : outline.isError
              ? "Could not load the outline."
              : t("fit.title")}
        </p>
      </div>
      {outline.isError ? (
        <div className="absolute bottom-16 left-1/2 w-[min(440px,calc(100vw-24px))] -translate-x-1/2">
          <ErrorState error={outline.error} compact what="the outline" onRetry={() => void outline.refetch()} />
        </div>
      ) : null}
      <div className="absolute bottom-3 left-3 z-20 flex flex-wrap gap-1.5">
        <input
          ref={fileRef}
          type="file"
          accept="image/*"
          capture="environment"
          className="sr-only"
          aria-label="Fit check photo"
          onChange={(e) => {
            const f = e.target.files?.[0];
            if (f) {
              setShowResult(true);
              upload.mutate(f);
            }
          }}
        />
        <Button size="sm" variant="primary" onClick={() => fileRef.current?.click()} disabled={upload.isPending || !outline.data}>
          {upload.isPending ? <Spinner className="text-accent-fg" label="Checking" /> : <Upload aria-hidden />}
          {upload.isPending ? t("fit.checking") : t("fit.upload")}
        </Button>
        <Button
          size="sm"
          variant="ghost"
          className="bg-black/60 text-white hover:bg-black/80 hover:text-white"
          onClick={() => setShowPhone((v) => !v)}
          aria-pressed={showPhone}
        >
          <Smartphone aria-hidden /> {t("mat.phone")}
        </Button>
      </div>
      {showPhone && matId && !shown ? (
        <div className="absolute bottom-14 left-3 z-20 space-y-2">
          <PhoneHandoff path={`/jobs/${encodeURIComponent(id)}/fit?phone=1&mat=${matId}`} compact dark />
          <p role="status" className="flex items-center gap-2 rounded-md bg-black/70 px-3 py-2 text-[13px] text-white">
            <span className="size-2 animate-pulse-dot rounded-full bg-accent" aria-hidden /> {t("fit.waiting")}
          </p>
        </div>
      ) : null}
      {upload.isError && showResult ? (
        <div className="absolute right-3 bottom-3 z-30 w-[min(400px,calc(100vw-24px))]">
          <ErrorState error={upload.error} compact what="the fit check" />
        </div>
      ) : null}
      {shown && showResult ? <ResultPanel r={shown} onClose={() => setShowResult(false)} /> : null}
      <div aria-live="assertive" className="sr-only">
        {latestLive ? (latestLive.passed ? t("fit.pass") : t("fit.fail")) : ""}
      </div>
    </>
  );
}

/** Phone mode: no mat, just take the photo and send it (the laptop shows the outline). */
function PhoneUpload({ id, matId }: { id: string; matId: string }) {
  const { t } = useT();
  const upload = useFitUpload(id, matId);
  const fileRef = React.useRef<HTMLInputElement>(null);
  return (
    <div className="mx-auto flex min-h-dvh max-w-md flex-col gap-5 bg-bg p-5">
      <div className="space-y-1.5 pt-6">
        <div className="flex items-center justify-between gap-2">
          <div className="text-[12px] font-medium uppercase tracking-[0.08em] text-accent-text">Screen fit check</div>
          <LangToggle />
        </div>
        <h1 className="text-2xl font-semibold tracking-tight">{t("fit.phoneTitle")}</h1>
        <p className="text-[14px] leading-6 text-muted">{t("fit.phoneBody")}</p>
      </div>
      <input
        ref={fileRef}
        type="file"
        accept="image/*"
        capture="environment"
        className="sr-only"
        aria-label="Fit check photo"
        onChange={(e) => e.target.files?.[0] && upload.mutate(e.target.files[0])}
      />
      <Button size="lg" variant="primary" onClick={() => fileRef.current?.click()} disabled={upload.isPending}>
        {upload.isPending ? <Spinner className="text-accent-fg" label="Checking" /> : <Camera aria-hidden />}
        {upload.isPending ? t("fit.checking") : t("fit.takePhoto")}
      </Button>
      {upload.isError ? <ErrorState error={upload.error} compact what="the fit check" /> : null}
      {upload.data ? (
        <div className="relative min-h-[520px]">
          <ResultPanel r={upload.data} onClose={() => upload.reset()} />
        </div>
      ) : null}
      <Link href={`/jobs/${encodeURIComponent(id)}`} className="text-center text-[13px] text-muted underline underline-offset-2">
        {t("fit.back")}
      </Link>
    </div>
  );
}

/** The mat whose frame the example outline is read in (any mat works: only the outline's own shape is drawn). */
const EXAMPLE_MAT = "screen-m";

/** The box an outline drawing needs: the outline, holes and dimension lines, plus room for a side legend on small parts. */
function outlineBounds(o: FitOutline): { x: number; y: number; w: number; h: number } {
  const xs = [...o.outline_mm.map((p) => p[0]), ...o.dims.flatMap((d) => [d.from_mm[0], d.to_mm[0]]), ...o.holes.flatMap((h) => [h.center_mm[0] - h.diameter_mm / 2, h.center_mm[0] + h.diameter_mm / 2])];
  const ys = [...o.outline_mm.map((p) => p[1]), ...o.dims.flatMap((d) => [d.from_mm[1], d.to_mm[1]]), ...o.holes.flatMap((h) => [h.center_mm[1] - h.diameter_mm / 2, h.center_mm[1] + h.diameter_mm / 2])];
  const ox = o.outline_mm.map((p) => p[0]);
  const oy = o.outline_mm.map((p) => p[1]);
  const small = Math.max(Math.max(...ox) - Math.min(...ox), Math.max(...oy) - Math.min(...oy)) < 30;
  const x = Math.min(...xs) - 6;
  const y = Math.min(...ys) - 6;
  return { x, y, w: Math.max(...xs) + (small ? 34 : 6) - x, h: Math.max(...ys) + 6 - y };
}

/**
 * A labelled example of the fit check, never a measurement: this job's own model outline drawn at nominal 1:1 (CSS
 * millimetres; the screen is not calibrated, so true size is not promised), and what the real check does with a photo.
 * Shown at `?example=1` and linked from the calibration gate, so the check can be seen before calibrating.
 */
function FitExample({ id }: { id: string }) {
  const outline = useQuery({ queryKey: ["fit-outline", id, EXAMPLE_MAT], queryFn: () => api.fitOutline(id, EXAMPLE_MAT), retry: false });
  const job = `/jobs/${encodeURIComponent(id)}`;
  const o = outline.data;
  const b = o ? outlineBounds(o) : null;
  return (
    <div className="min-h-dvh bg-bg text-fg">
      <div className="mx-auto max-w-3xl space-y-5 px-4 py-6 sm:px-8 sm:py-10">
        <Link href={job} className="inline-flex items-center gap-1 text-[13px] text-muted hover:text-fg">
          <ArrowLeft className="size-3.5" aria-hidden /> Back to the job
        </Link>
        <div className="space-y-1.5">
          <div className="text-[12px] font-medium tracking-[0.08em] text-accent-text uppercase">Screen fit check · example</div>
          <h1 className="text-2xl font-semibold tracking-tight">What the fit check looks like</h1>
        </div>
        <p role="note" className="rounded-md border border-warn-border bg-warn-soft px-3 py-2 text-[13px] leading-5 text-fg" data-testid="fit-example-note">
          <span className="font-medium">Example — calibrate your screen to check your real part.</span> Nothing on this page is measured. The drawing is this
          job&apos;s model outline at nominal 1:1 (CSS millimetres); an uncalibrated screen can draw it larger or smaller than true size.
        </p>
        <figure className="space-y-2">
          <div className="scrollbar-thin overflow-x-auto rounded-lg border border-border bg-[#f4f4f2] p-3" tabIndex={0} role="region" aria-label="Example outline drawing">
            {outline.isPending ? (
              <Skeleton className="h-40" />
            ) : outline.isError ? (
              <ErrorState error={outline.error} compact what="this job's model outline" onRetry={() => void outline.refetch()} />
            ) : o && b ? (
              <svg
                viewBox={`${b.x} ${b.y} ${b.w} ${b.h}`}
                style={{ width: `${b.w}mm`, height: `${b.h}mm` }}
                className="block max-w-none"
                role="img"
                aria-label={`Example: the model outline with ${o.holes.length} hole${o.holes.length === 1 ? "" : "s"} and its sizes ${o.dims.map((d) => d.label).join(", ")}, drawn at nominal 1:1. Not a measurement.`}
              >
                <OutlineSvg o={o} />
              </svg>
            ) : null}
          </div>
          <figcaption className="text-[12px] leading-5 text-muted">
            Example drawing: the outline, holes and sizes come from this job&apos;s model (the numbers are the model&apos;s, not a measurement of your part).
          </figcaption>
        </figure>
        <ol className="list-decimal space-y-1.5 pl-5 text-[14px] leading-6">
          <li>Calibrate this screen once with any bank or ID card (about 30 seconds).</li>
          <li>Open the fit check: the screen mat shows this outline at true size.</li>
          <li>Lay the real or printed part exactly on the pink outline and photograph straight down.</li>
          <li>Code measures the photo: largest gap and average gap in millimetres, the overlap (IoU), and an overlay picture. Pass or fail comes from those numbers.</li>
        </ol>
        <div className="flex flex-wrap gap-2">
          <Button asChild variant="primary">
            <Link href={`/calibrate?next=${encodeURIComponent(`${job}/fit`)}`}>
              <Ruler aria-hidden /> Calibrate and check my part
            </Link>
          </Button>
          <Button asChild variant="outline">
            <Link href={`${job}/fit`}>Open the fit check</Link>
          </Button>
        </div>
      </div>
    </div>
  );
}

export function FitClient({ id }: { id: string }) {
  return (
    <I18nRegion>
      <FitInner id={id} />
    </I18nRegion>
  );
}

function FitInner({ id }: { id: string }) {
  const sp = useSearchParams();
  const phone = sp.get("phone") === "1";
  const mat = sp.get("mat");
  if (phone && mat) return <PhoneUpload id={id} matId={mat} />;
  if (sp.get("example") === "1") return <FitExample id={id} />;
  return (
    <StageShell
      exitHref={`/jobs/${encodeURIComponent(id)}`}
      title="Screen fit check"
      calibrateNext={`/jobs/${encodeURIComponent(id)}/fit`}
      tips={false}
      gateExtra={
        <p className="border-t border-border pt-3 text-[13px] text-muted">
          <Link href={`/jobs/${encodeURIComponent(id)}/fit?example=1`} className="inline-flex items-center gap-1 font-medium text-accent-text hover:underline">
            <Eye className="size-3.5" aria-hidden /> See a labelled example first
          </Link>{" "}
          — this job&apos;s outline, not a measurement.
        </p>
      }
    >
      {(cal, stage) => <FitStage id={id} cal={cal} stage={stage} />}
    </StageShell>
  );
}
