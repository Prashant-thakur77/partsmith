"use client";

/**
 * Landing autoplay: a real stored replay played as a silent loop — photo → segmentation mask → the error chart stepping
 * down iteration by iteration → the verifier's stamp → the fit check (when the run has one). Every number comes from the
 * replay's own events and verification record. Labelled "Replay"; with reduced motion it shows the final frame and lets
 * people step through by hand.
 */
import { useQuery } from "@tanstack/react-query";
import { BadgeCheck, ChevronLeft, ChevronRight, Pause, Play, PlayCircle } from "lucide-react";
import Link from "next/link";
import * as React from "react";
import { api, artifactUrl } from "@/lib/api";
import type { JobDetail } from "@/lib/api-types";
import { fmtNum } from "@/lib/format";
import { summarizeEvents } from "@/lib/job-events";
import { cn } from "@/lib/utils";
import { Badge } from "../ui/badge";
import { OriginBadge, RunBadge } from "../ui/provenance";

type Frame = { key: string; caption: string };
const FRAME_MS = 2600;

function usePrefersReducedMotion(): boolean {
  return React.useSyncExternalStore(
    (cb) => {
      const m = window.matchMedia("(prefers-reduced-motion: reduce)");
      m.addEventListener("change", cb);
      return () => m.removeEventListener("change", cb);
    },
    () => window.matchMedia("(prefers-reduced-motion: reduce)").matches,
    () => true,
  );
}

function useReplay() {
  const list = useQuery({ queryKey: ["replays"], queryFn: api.replays, staleTime: 300_000 });
  const pick = list.data?.find((r) => r.verified && r.iterations > 1) ?? list.data?.find((r) => r.verified) ?? null;
  const detail = useQuery({ queryKey: ["job", pick?.id], queryFn: () => api.job(pick!.id), enabled: !!pick, staleTime: 300_000 });
  return { list, pick, detail };
}

function ErrorChart({ points, upTo, threshold }: { points: { iter: number; v: number }[]; upTo: number; threshold: number }) {
  const W = 420;
  const H = 210;
  const pad = 32;
  const maxV = Math.max(threshold * 1.4, ...points.map((p) => p.v));
  const x = (i: number) => pad + (points.length <= 1 ? 0 : (i / (points.length - 1)) * (W - pad * 1.5));
  const y = (v: number) => H - pad - (v / maxV) * (H - pad * 1.6);
  const shown = points.slice(0, upTo);
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="h-full w-full" role="img" aria-label={`Max error per iteration: ${points.map((p) => `${fmtNum(p.v)} mm`).join(", ")}`}>
      <line x1={pad} x2={W - 8} y1={y(threshold)} y2={y(threshold)} stroke="var(--ok)" strokeDasharray="4 4" strokeWidth={1.2} />
      <text x={W - 10} y={y(threshold) - 5} textAnchor="end" fontSize={12} fill="var(--ok)">
        pass ≤ {fmtNum(threshold)} mm
      </text>
      <line x1={pad} x2={pad} y1={10} y2={H - pad} stroke="var(--border-strong)" />
      <line x1={pad} x2={W - 8} y1={H - pad} y2={H - pad} stroke="var(--border-strong)" />
      <polyline fill="none" stroke="var(--accent)" strokeWidth={2.2} points={shown.map((p, i) => `${x(i)},${y(p.v)}`).join(" ")} />
      {shown.map((p, i) => (
        <g key={p.iter}>
          <circle cx={x(i)} cy={y(p.v)} r={3.5} fill={p.v <= threshold ? "var(--ok)" : "var(--accent)"} />
          <text x={x(i)} y={y(p.v) - 8} textAnchor="middle" fontSize={12} fill="var(--fg)" className="tnum">
            {fmtNum(p.v)}
          </text>
          <text x={x(i)} y={H - pad + 14} textAnchor="middle" fontSize={11.5} fill="var(--fg-muted)">
            {p.iter}
          </text>
        </g>
      ))}
      <text x={pad} y={H - 2} fontSize={11.5} fill="var(--fg-muted)">
        iteration
      </text>
    </svg>
  );
}

function Img({ src, alt }: { src?: string; alt: string }) {
  if (!src) return <div className="flex h-full items-center justify-center text-[12px] text-muted">not in this replay</div>;
  // eslint-disable-next-line @next/next/no-img-element -- API blob
  return <img src={src} alt={alt} className="h-full w-full object-contain" loading="lazy" decoding="async" />;
}

function frames(d: JobDetail) {
  const s = summarizeEvents(d.events);
  const photo = s.artifacts.rectified ?? s.artifacts.photo;
  const mask = s.artifacts.mask_overlay;
  const points = s.convergence.filter((c) => c.hausdorff_mm != null).map((c) => ({ iter: c.iter, v: c.hausdorff_mm as number }));
  const fitOverlay = Object.values(s.artifacts).find((a) => a.kind === "measure_overlay" && a.label.toLowerCase().startsWith("fit check"));
  const fitPassed = [...s.metrics].reverse().find((m) => m.name === "fit_check_passed");
  const list: Frame[] = [];
  if (photo) list.push({ key: "photo", caption: "1 · Phone photo on the screen mat" });
  if (mask) list.push({ key: "mask", caption: "2 · Segmentation mask, measured in mm" });
  if (points.length) list.push({ key: "chart", caption: "3 · Agent edits the CAD; the error steps down" });
  if (d.verification) list.push({ key: "stamp", caption: "4 · Code checks it against the photo" });
  if (fitOverlay) list.push({ key: "fit", caption: "5 · Fit check on the screen" });
  const render = s.artifacts.render_overlay ?? photo;
  return { list, photo, mask, render, points, fitOverlay, fitPassed, verification: d.verification };
}

export function ReplayLoop() {
  const reduced = usePrefersReducedMotion();
  const { list, pick, detail } = useReplay();
  const [i, setI] = React.useState(0);
  const [step, setStep] = React.useState(0);
  const [paused, setPaused] = React.useState(false);
  const [visible, setVisible] = React.useState(true);
  const ref = React.useRef<HTMLDivElement>(null);
  const f = React.useMemo(() => (detail.data ? frames(detail.data) : null), [detail.data]);
  const n = f?.list.length ?? 0;
  const auto = !reduced && !paused && visible;

  React.useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const io = new IntersectionObserver(([e]) => setVisible(!!e?.isIntersecting && document.visibilityState === "visible"));
    io.observe(el);
    return () => io.disconnect();
  }, []);
  React.useEffect(() => {
    if (reduced && n) setI(n - 1);
  }, [reduced, n]);
  const cur = f?.list[i]?.key;
  // The chart frame reveals one iteration per tick; other frames hold for one tick.
  React.useEffect(() => {
    if (!auto || !f || !n) return;
    const t = setTimeout(
      () => {
        if (cur === "chart" && step < f.points.length) return setStep((s) => s + 1);
        setStep(0);
        setI((x) => (x + 1) % n);
      },
      cur === "chart" ? Math.max(500, FRAME_MS / Math.max(2, f.points.length)) : FRAME_MS,
    );
    return () => clearTimeout(t);
  }, [auto, f, n, cur, step]);

  const shell = (body: React.ReactNode) => (
    <div ref={ref} className="overflow-hidden rounded-xl border border-border bg-surface">
      {body}
    </div>
  );
  if (list.isError || detail.isError || (list.data && !pick))
    return shell(<p className="flex aspect-[16/10] items-center justify-center p-6 text-center text-[13px] text-muted sm:aspect-[16/7]">No stored replay is available on this server.</p>);
  if (!f || !pick) return shell(<div className="aspect-[16/10] animate-pulse bg-surface-2 sm:aspect-[16/7]" aria-busy="true" aria-label="Loading replay" />);

  const v = f.verification;
  const chartUpTo = reduced || cur !== "chart" ? f.points.length : Math.max(1, step);
  return shell(
    <>
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border px-4 py-2.5">
        <div className="flex min-w-0 items-center gap-2">
          <PlayCircle className="size-4 shrink-0 text-muted" aria-hidden />
          <span className="truncate text-[13px] font-medium">{pick.title}</span>
          <RunBadge mode={pick.provider_mode} recorded />
          <OriginBadge origin={pick.origin} hideReal />
        </div>
        <div className="flex items-center gap-1">
          <button type="button" aria-label="Previous step" onClick={() => (setStep(0), setI((x) => (x - 1 + n) % n))} className="rounded p-1 text-muted hover:bg-surface-2 hover:text-fg">
            <ChevronLeft className="size-4" aria-hidden />
          </button>
          {!reduced ? (
            <button type="button" aria-label={paused ? "Play replay" : "Pause replay"} onClick={() => setPaused((p) => !p)} className="rounded p-1 text-muted hover:bg-surface-2 hover:text-fg">
              {paused ? <Play className="size-4" aria-hidden /> : <Pause className="size-4" aria-hidden />}
            </button>
          ) : null}
          <button type="button" aria-label="Next step" onClick={() => (setStep(0), setI((x) => (x + 1) % n))} className="rounded p-1 text-muted hover:bg-surface-2 hover:text-fg">
            <ChevronRight className="size-4" aria-hidden />
          </button>
        </div>
      </div>
      <div className="relative aspect-[16/10] bg-surface-2 sm:aspect-[16/7]">
        {cur === "photo" ? <Img src={artifactUrl(f.photo?.url)} alt="Top photo of the part on the screen mat" /> : null}
        {cur === "mask" ? <Img src={artifactUrl(f.mask?.url)} alt="Segmentation mask over the photo" /> : null}
        {cur === "chart" ? (
          <div className="mx-auto h-full max-w-xl p-3">
            <ErrorChart points={f.points} upTo={chartUpTo} threshold={v?.thresholds.hausdorff_mm ?? 0.5} />
          </div>
        ) : null}
        {cur === "stamp" && v ? (
          <div className="relative flex h-full flex-col items-center justify-center gap-2 p-4 text-center">
            {f.render ? (
              // eslint-disable-next-line @next/next/no-img-element -- API blob, decorative backdrop
              <img src={artifactUrl(f.render.url)} alt="" aria-hidden className="absolute inset-0 h-full w-full object-contain opacity-25" />
            ) : null}
            <div
              className={cn(
                "relative flex items-center gap-2 rounded-lg border-2 bg-surface px-4 py-2 text-[22px] font-bold tracking-wide uppercase motion-safe:animate-[stamp_400ms_ease-out]",
                v.verified ? "border-ok text-ok" : "border-warn text-warn",
              )}
            >
              <BadgeCheck className="size-6" aria-hidden /> {v.verified ? "Verified" : v.status.replace("_", " ")}
            </div>
            <p className="relative rounded bg-surface/90 px-2 font-mono text-[13px] text-muted tnum">
              max error {fmtNum(v.max_error_mm ?? NaN)} mm · limit {fmtNum(v.thresholds.hausdorff_mm)} mm · {v.tests.filter((t) => t.passed).length}/{v.tests.length} tests
            </p>
          </div>
        ) : null}
        {cur === "fit" ? (
          <div className="relative h-full">
            <Img src={artifactUrl(f.fitOverlay?.url)} alt="Fit check overlay: the printed part on the screen outline" />
            {f.fitPassed ? (
              <Badge tone={f.fitPassed.value >= 0.5 ? "ok" : "bad"} className="absolute top-2 left-2">
                fit check {f.fitPassed.value >= 0.5 ? "passed" : "failed"}
              </Badge>
            ) : null}
          </div>
        ) : null}
      </div>
      <div className="flex h-14 items-center justify-between gap-3 px-4 text-[12px]">
        <span className="line-clamp-2 text-muted" aria-live={auto ? "off" : "polite"}>
          {f.list[i]?.caption}
        </span>
        <span className="flex items-center gap-3">
          <span className="hidden gap-1 sm:flex" aria-hidden>
            {f.list.map((fr, k) => (
              <span key={fr.key} className={cn("h-1.5 w-4 rounded-full", k === i ? "bg-accent" : "bg-border")} />
            ))}
          </span>
          <Link href={`/jobs/${encodeURIComponent(pick.id)}`} className="font-medium whitespace-nowrap text-accent-text hover:underline">
            Open the full run
          </Link>
        </span>
      </div>
    </>,
  );
}
