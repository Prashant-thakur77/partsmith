"use client";

/**
 * Full-screen shell for calibrated surfaces: dark surround, wake lock, optional fullscreen, Esc to exit, auto-hiding chrome.
 * Shows a calibration gate when the screen has not been calibrated (or zoom/display changed).
 */
import { ArrowLeft, Expand, Lightbulb, Ruler, Smartphone, X } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import * as React from "react";
import { calibrationDrift, useCalibration, useDisplayKey, type ScreenCalibration } from "@/lib/calibration";
import { STAGE_COLOURS, setStageTone, useStageTone, type StageTone } from "@/lib/stage";
import { useT } from "@/lib/i18n";
import { cn } from "@/lib/utils";
import { PhoneHandoff } from "../phone-handoff";
import { Button } from "../ui/button";
import { Spinner } from "../ui/spinner";
import { radioGroupKeys } from "@/lib/a11y";

export function useWakeLock(active: boolean) {
  React.useEffect(() => {
    if (!active || !("wakeLock" in navigator)) return;
    let lock: WakeLockSentinel | null = null;
    let cancelled = false;
    const acquire = async () => {
      try {
        lock = await navigator.wakeLock.request("screen");
      } catch {
        lock = null;
      }
      if (cancelled) void lock?.release();
    };
    void acquire();
    const onVis = () => document.visibilityState === "visible" && void acquire();
    document.addEventListener("visibilitychange", onVis);
    return () => {
      cancelled = true;
      document.removeEventListener("visibilitychange", onVis);
      void lock?.release();
    };
  }, [active]);
}

function useIdle(ms = 2500) {
  const [idle, setIdle] = React.useState(false);
  React.useEffect(() => {
    let t: ReturnType<typeof setTimeout>;
    const wake = () => {
      setIdle(false);
      clearTimeout(t);
      t = setTimeout(() => setIdle(true), ms);
    };
    wake();
    window.addEventListener("pointermove", wake);
    window.addEventListener("pointerdown", wake);
    window.addEventListener("keydown", wake);
    return () => {
      clearTimeout(t);
      window.removeEventListener("pointermove", wake);
      window.removeEventListener("pointerdown", wake);
      window.removeEventListener("keydown", wake);
    };
  }, [ms]);
  return idle;
}

export function StageShell({
  exitHref,
  title,
  children,
  toolbar,
  tips = true,
  calibrateNext,
  phonePath,
  gateExtra,
}: {
  exitHref: string;
  title: string;
  children: (cal: ScreenCalibration, stage: StageTone) => React.ReactNode;
  toolbar?: React.ReactNode;
  tips?: boolean;
  calibrateNext: string;
  /** Page the phone should open (shown as a QR code from the toolbar). */
  phonePath?: string;
  /** Extra content under the calibration gate's buttons (e.g. a link to a labelled example). */
  gateExtra?: React.ReactNode;
}) {
  const router = useRouter();
  const { t } = useT();
  const { calibration, ready } = useCalibration();
  useDisplayKey();
  const drift = ready && calibration ? calibrationDrift(calibration) : null;
  const ok = ready && calibration && !drift;
  const idle = useIdle();
  const stage = useStageTone();
  // `?stage=dark|light` (e.g. from the capture gate's "open mat with dark stage" link) sets and remembers the stage.
  React.useEffect(() => {
    const p = new URLSearchParams(window.location.search).get("stage");
    if (p === "dark" || p === "light") setStageTone(p);
  }, []);
  const [showTips, setShowTips] = React.useState(false);
  const [showPhone, setShowPhone] = React.useState(false);
  useWakeLock(!!ok);

  React.useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !document.fullscreenElement) router.push(exitHref);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [router, exitHref]);

  if (!ready) {
    return (
      <div className="flex min-h-dvh items-center justify-center bg-[#111]">
        <Spinner className="text-white/60" />
      </div>
    );
  }

  if (!ok) {
    return (
      <div className="flex min-h-dvh items-center justify-center bg-bg p-6">
        <div className="w-full max-w-md space-y-4 rounded-xl border border-border bg-surface p-6 shadow-md">
          <div className="flex size-10 items-center justify-center rounded-full border border-border bg-surface-2">
            <Ruler className="size-5 text-muted" aria-hidden />
          </div>
          <div className="space-y-1.5">
            <h1 className="text-lg font-semibold">{drift ? t("mat.recheck") : t("mat.calibrateFirst")}</h1>
            <p className="text-[14px] leading-6 text-muted">
              {drift ??
                t("mat.calibrateWhy")}
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <Button asChild variant="primary">
              <Link href={`/calibrate?next=${encodeURIComponent(calibrateNext)}`}>{t("fix.calibrate")}</Link>
            </Button>
            <Button asChild variant="ghost">
              <Link href={exitHref}>{t("mat.back")}</Link>
            </Button>
          </div>
          {gateExtra}
        </div>
      </div>
    );
  }

  return (
    <div className="relative flex min-h-dvh items-center justify-center overflow-hidden bg-[#141414] text-white" data-idle={idle || undefined} style={{ cursor: idle ? "none" : undefined }}>
      <h1 className="sr-only">{title}</h1>
      {children(calibration, stage)}
      <div
        className="pointer-events-none absolute inset-x-0 top-0 z-20 flex items-start justify-between gap-2 p-3 transition-opacity duration-300"
        style={{ opacity: idle ? 0 : 1 }}
      >
        <div className="pointer-events-auto flex items-center gap-1.5">
          <Button asChild size="sm" variant="ghost" className="bg-black/60 text-white hover:bg-black/80 hover:text-white">
            <Link href={exitHref}>
              <ArrowLeft aria-hidden /> {t("mat.exit")} <span className="hidden text-white/60 sm:inline">(Esc)</span>
            </Link>
          </Button>
        </div>
        <div className="pointer-events-auto flex flex-wrap items-center justify-end gap-1.5">
          <div className="flex items-center gap-2 rounded-md bg-black/60 py-1 pr-1 pl-2.5">
            <span className="hidden text-[12px] text-white/70 md:inline">{t("mat.stageHint")}</span>
            <span className="text-[12px] font-medium text-white/90">{t("mat.stage")}</span>
            <div role="radiogroup" onKeyDown={radioGroupKeys} aria-label="Stage colour" className="inline-flex rounded-[5px] bg-white/10 p-0.5">
              {(["light", "dark"] as const).map((tone) => (
                <button
                  key={tone}
                  type="button"
                  role="radio"
                  aria-checked={stage === tone}
                  onClick={() => setStageTone(tone)}
                  className={cn(
                    "inline-flex h-6 items-center gap-1.5 rounded-[4px] px-2 text-[12px] font-medium text-white/75 capitalize hover:text-white",
                    stage === tone && "bg-white text-black hover:text-black",
                  )}
                >
                  <span aria-hidden className="size-2.5 rounded-full border border-black/30" style={{ background: STAGE_COLOURS[tone] }} />
                  {tone}
                </button>
              ))}
            </div>
          </div>
          {toolbar}
          {phonePath ? (
            <Button
              size="sm"
              variant="ghost"
              className="hidden bg-black/60 text-white hover:bg-black/80 hover:text-white md:inline-flex"
              onClick={() => setShowPhone((v) => !v)}
              aria-pressed={showPhone}
            >
              <Smartphone aria-hidden /> {t("mat.phone")}
            </Button>
          ) : null}
          {tips ? (
            <Button size="sm" variant="ghost" className="bg-black/60 text-white hover:bg-black/80 hover:text-white" onClick={() => setShowTips((v) => !v)} aria-pressed={showTips}>
              <Lightbulb aria-hidden /> {t("mat.tips")}
            </Button>
          ) : null}
          <Button
            size="sm"
            variant="ghost"
            className="bg-black/60 text-white hover:bg-black/80 hover:text-white"
            onClick={() => (document.fullscreenElement ? void document.exitFullscreen() : void document.documentElement.requestFullscreen?.())}
          >
            <Expand aria-hidden /> {t("mat.full")}
          </Button>
        </div>
      </div>
      {showPhone && phonePath ? (
        <div className="absolute top-14 right-3 z-30">
          <PhoneHandoff path={phonePath} compact dark />
        </div>
      ) : null}
      {showTips ? (
        <div className="absolute bottom-3 left-1/2 z-20 w-[min(560px,calc(100vw-24px))] -translate-x-1/2 rounded-lg bg-black/80 p-4 text-[13px] leading-5 text-white/85 shadow-lg backdrop-blur">
          <div className="flex items-start justify-between gap-3">
            <ul className="space-y-1.5">
              <li>{t("mat.tip1")}</li>
              <li>{t("mat.tip2")}</li>
              <li>{t("mat.tip3")}</li>
              <li>{t("mat.tip4")}</li>
            </ul>
            <button type="button" aria-label="Hide tips" onClick={() => setShowTips(false)} className="rounded p-1 text-white/70 hover:bg-white/10 hover:text-white">
              <X className="size-4" aria-hidden />
            </button>
          </div>
        </div>
      ) : null}
    </div>
  );
}
