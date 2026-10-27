"use client";

/**
 * Full-screen shell for calibrated surfaces: dark surround, wake lock, optional fullscreen, Esc to exit, auto-hiding chrome.
 * Shows a calibration gate when the screen has not been calibrated (or zoom/display changed).
 */
import { ArrowLeft, Expand, Lightbulb, Ruler, X } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import * as React from "react";
import { calibrationDrift, useCalibration, useDisplayKey, type ScreenCalibration } from "@/lib/calibration";
import { Button } from "../ui/button";
import { Spinner } from "../ui/spinner";

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
}: {
  exitHref: string;
  title: string;
  children: (cal: ScreenCalibration) => React.ReactNode;
  toolbar?: React.ReactNode;
  tips?: boolean;
  calibrateNext: string;
}) {
  const router = useRouter();
  const { calibration, ready } = useCalibration();
  useDisplayKey();
  const drift = ready && calibration ? calibrationDrift(calibration) : null;
  const ok = ready && calibration && !drift;
  const idle = useIdle();
  const [showTips, setShowTips] = React.useState(false);
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
            <h1 className="text-lg font-semibold">{drift ? "Recheck your screen scale" : "Calibrate this screen first"}</h1>
            <p className="text-[14px] leading-6 text-muted">
              {drift ??
                "The mat has to be drawn at true size. It takes 30 seconds with any bank or ID card, once per screen."}
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <Button asChild variant="primary">
              <Link href={`/calibrate?next=${encodeURIComponent(calibrateNext)}`}>Calibrate with a card</Link>
            </Button>
            <Button asChild variant="ghost">
              <Link href={exitHref}>Back</Link>
            </Button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="relative flex min-h-dvh items-center justify-center overflow-hidden bg-[#141414] text-white" data-idle={idle || undefined} style={{ cursor: idle ? "none" : undefined }}>
      <h1 className="sr-only">{title}</h1>
      {children(calibration)}
      <div
        className="pointer-events-none absolute inset-x-0 top-0 z-20 flex items-start justify-between gap-2 p-3 transition-opacity duration-300"
        style={{ opacity: idle ? 0 : 1 }}
      >
        <div className="pointer-events-auto flex items-center gap-1.5">
          <Button asChild size="sm" variant="ghost" className="bg-black/60 text-white hover:bg-black/80 hover:text-white">
            <Link href={exitHref}>
              <ArrowLeft aria-hidden /> Exit <span className="hidden text-white/60 sm:inline">(Esc)</span>
            </Link>
          </Button>
        </div>
        <div className="pointer-events-auto flex items-center gap-1.5">
          {toolbar}
          {tips ? (
            <Button size="sm" variant="ghost" className="bg-black/60 text-white hover:bg-black/80 hover:text-white" onClick={() => setShowTips((v) => !v)} aria-pressed={showTips}>
              <Lightbulb aria-hidden /> Tips
            </Button>
          ) : null}
          <Button
            size="sm"
            variant="ghost"
            className="bg-black/60 text-white hover:bg-black/80 hover:text-white"
            onClick={() => (document.fullscreenElement ? void document.exitFullscreen() : void document.documentElement.requestFullscreen?.())}
          >
            <Expand aria-hidden /> Full screen
          </Button>
        </div>
      </div>
      {showTips ? (
        <div className="absolute bottom-3 left-1/2 z-20 w-[min(560px,calc(100vw-24px))] -translate-x-1/2 rounded-lg bg-black/80 p-4 text-[13px] leading-5 text-white/85 shadow-lg backdrop-blur">
          <div className="flex items-start justify-between gap-3">
            <ul className="space-y-1.5">
              <li>Lay the screen flat (laptop opened 180° or a tablet) and set brightness to about 70 %.</li>
              <li>Kill glare: no lamp or window reflected in the screen. Move the light, not the part.</li>
              <li>Put the part in the plain white middle; keep the black squares visible around it.</li>
              <li>Photograph straight down from 20–35 cm with your phone. Night-shift / blue-light filters are fine.</li>
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
