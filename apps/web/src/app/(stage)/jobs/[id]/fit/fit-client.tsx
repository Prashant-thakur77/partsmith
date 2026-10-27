"use client";

import { useMutation, useQuery } from "@tanstack/react-query";
import { BadgeCheck, Camera, Link2, Upload, X, XOctagon } from "lucide-react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import * as React from "react";
import { CaptureReportView } from "@/components/fix/capture-report";
import { ScreenMat } from "@/components/mat/screen-mat";
import { StageShell } from "@/components/mat/stage-shell";
import { useMatChoice } from "@/components/mat/use-mat-layout";
import { Button } from "@/components/ui/button";
import { ErrorState } from "@/components/ui/error-state";
import { Mm } from "@/components/ui/mm";
import { Spinner } from "@/components/ui/spinner";
import { toast } from "@/components/ui/toast";
import { api, artifactUrl } from "@/lib/api";
import type { FitCheckResult, FitOutline } from "@/lib/api-types";
import type { ScreenCalibration } from "@/lib/calibration";
import type { StageTone } from "@/lib/stage";
import { fmtNum } from "@/lib/format";
import { useOrigin } from "@/lib/use-origin";
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

function ResultPanel({ r, onClose }: { r: FitCheckResult; onClose: () => void }) {
  return (
    <div className="absolute inset-y-3 right-3 z-30 flex w-[min(400px,calc(100vw-24px))] flex-col overflow-hidden rounded-xl border border-border bg-surface text-fg shadow-lg" role="dialog" aria-label="Fit check result">
      <div className={cn("flex items-center justify-between gap-2 px-4 py-3", r.passed ? "bg-ok-soft" : "bg-bad-soft")}>
        <div className="flex items-center gap-2">
          {r.passed ? <BadgeCheck className="size-5 text-ok" aria-hidden /> : <XOctagon className="size-5 text-bad" aria-hidden />}
          <span className={cn("text-[15px] font-semibold", r.passed ? "text-ok" : "text-bad")}>{r.passed ? "It fits the outline" : "Does not match yet"}</span>
        </div>
        <button type="button" onClick={onClose} aria-label="Close result" className="rounded p-1 text-muted hover:bg-surface/60 hover:text-fg">
          <X className="size-4" aria-hidden />
        </button>
      </div>
      <div className="scrollbar-thin flex-1 space-y-4 overflow-y-auto p-4">
        {/* eslint-disable-next-line @next/next/no-img-element -- API overlay */}
        <img src={artifactUrl(r.overlay_url)} alt="Verifier overlay: real part versus model outline" className="w-full rounded-md border border-border" />
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
            <dd className="font-mono text-[13px] tnum">{fmtNum(r.iou, 3)}</dd>
          </div>
        </dl>
        {r.reasons.length ? (
          <ul className="list-disc space-y-1 pl-4 text-[13px] text-muted">
            {r.reasons.map((x) => (
              <li key={x}>{x}</li>
            ))}
          </ul>
        ) : null}
        <CaptureReportView report={r.capture} />
      </div>
    </div>
  );
}

function useFitUpload(id: string, matId: string | null) {
  return useMutation({ mutationFn: (file: File) => api.fitCheck(id, file, matId!) });
}

function FitStage({ id, cal, stage }: { id: string; cal: ScreenCalibration; stage: StageTone }) {
  const origin = useOrigin();
  const { choice, isPending } = useMatChoice(cal.px_per_mm, null);
  const matId = choice?.layout.mat_id ?? null;
  const outline = useQuery({ queryKey: ["fit-outline", id, matId], queryFn: () => api.fitOutline(id, matId!), enabled: !!matId });
  const upload = useFitUpload(id, matId);
  const fileRef = React.useRef<HTMLInputElement>(null);
  const [showResult, setShowResult] = React.useState(true);

  if (isPending) return <Spinner className="text-white/60" label="Loading mat" />;
  if (!choice) return <p className="max-w-sm p-6 text-center text-[14px] text-white/80">This window is too small for a 1:1 mat. Make it bigger or go full screen.</p>;

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
              : "Lay the part exactly on the pink outline, then photograph straight down."}
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
          {upload.isPending ? "Checking fit…" : "Upload photo"}
        </Button>
        <Button
          size="sm"
          variant="ghost"
          className="bg-black/60 text-white hover:bg-black/80 hover:text-white"
          onClick={() => {
            void navigator.clipboard?.writeText(`${origin}/jobs/${encodeURIComponent(id)}/fit?phone=1&mat=${matId}`);
            toast("Phone link copied", { description: "Open it on your phone to take and send the photo." });
          }}
        >
          <Link2 aria-hidden /> Phone link
        </Button>
      </div>
      {upload.isError && showResult ? (
        <div className="absolute right-3 bottom-3 z-30 w-[min(400px,calc(100vw-24px))]">
          <ErrorState error={upload.error} compact what="the fit check" />
        </div>
      ) : null}
      {upload.data && showResult ? <ResultPanel r={upload.data} onClose={() => setShowResult(false)} /> : null}
    </>
  );
}

/** Phone mode: no mat, just take the photo and send it (the laptop shows the outline). */
function PhoneUpload({ id, matId }: { id: string; matId: string }) {
  const upload = useFitUpload(id, matId);
  const fileRef = React.useRef<HTMLInputElement>(null);
  return (
    <div className="mx-auto flex min-h-dvh max-w-md flex-col gap-5 bg-bg p-5">
      <div className="space-y-1.5 pt-6">
        <div className="text-[12px] font-medium uppercase tracking-[0.08em] text-accent-text">Screen fit check</div>
        <h1 className="text-2xl font-semibold tracking-tight">Photograph the part on the outline</h1>
        <p className="text-[14px] leading-6 text-muted">Hold the phone flat above the screen, 20–35 cm up, with every black square in view.</p>
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
        {upload.isPending ? "Checking fit…" : "Take photo"}
      </Button>
      {upload.isError ? <ErrorState error={upload.error} compact what="the fit check" /> : null}
      {upload.data ? (
        <div className="relative min-h-[520px]">
          <ResultPanel r={upload.data} onClose={() => upload.reset()} />
        </div>
      ) : null}
      <Link href={`/jobs/${encodeURIComponent(id)}`} className="text-center text-[13px] text-muted underline underline-offset-2">
        Back to the job
      </Link>
    </div>
  );
}

export function FitClient({ id }: { id: string }) {
  const sp = useSearchParams();
  const phone = sp.get("phone") === "1";
  const mat = sp.get("mat");
  if (phone && mat) return <PhoneUpload id={id} matId={mat} />;
  return (
    <StageShell exitHref={`/jobs/${encodeURIComponent(id)}`} title="Screen fit check" calibrateNext={`/jobs/${encodeURIComponent(id)}/fit`} tips={false}>
      {(cal, stage) => <FitStage id={id} cal={cal} stage={stage} />}
    </StageShell>
  );
}
