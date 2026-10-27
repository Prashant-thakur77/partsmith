"use client";

import { ArrowRight, Check, CreditCard, Info, Minus, MonitorSmartphone, Plus, RotateCcw } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import * as React from "react";
import { Container } from "@/components/layout/page";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Kbd } from "@/components/ui/kbd";
import { Slider } from "@/components/ui/slider";
import { toast } from "@/components/ui/toast";
import {
  CARD_ASPECT,
  CARD_H_MM,
  CARD_W_MM,
  calibrationDrift,
  clearCalibration,
  saveCalibration,
  useCalibration,
  useDisplayKey,
} from "@/lib/calibration";
import { fmtNum } from "@/lib/format";
import { clamp } from "@/lib/utils";

const CSS_REFERENCE_PX_PER_MM = 96 / 25.4; // CSS reference pixel: a starting guess only
const MIN_W = 160;

export function CalibrateClient() {
  const router = useRouter();
  const next = useSearchParams().get("next");
  const { calibration, ready } = useCalibration();
  useDisplayKey();
  const drift = ready && calibration ? calibrationDrift(calibration) : null;
  const [w, setW] = React.useState<number | null>(null);
  const [maxW, setMaxW] = React.useState(900);
  const stageRef = React.useRef<HTMLDivElement>(null);
  const drag = React.useRef<{ x: number; w: number } | null>(null);

  React.useEffect(() => {
    if (!ready) return;
    const fit = () => setMaxW(Math.max(MIN_W + 40, (stageRef.current?.clientWidth ?? 900) - 8));
    fit();
    window.addEventListener("resize", fit);
    setW((cur) => cur ?? (calibration && !drift ? calibration.card_w_px : CARD_W_MM * CSS_REFERENCE_PX_PER_MM));
    return () => window.removeEventListener("resize", fit);
  }, [ready, calibration, drift]);

  const width = clamp(w ?? CARD_W_MM * CSS_REFERENCE_PX_PER_MM, MIN_W, maxW);
  const height = width / CARD_ASPECT;
  const pxPerMm = width / CARD_W_MM;

  const nudge = (d: number) => setW((cur) => clamp((cur ?? width) + d, MIN_W, maxW));

  const onKey = (e: React.KeyboardEvent) => {
    const step = e.shiftKey ? 10 : e.altKey ? 0.25 : 1;
    if (e.key === "ArrowRight" || e.key === "ArrowUp") {
      e.preventDefault();
      nudge(step);
    } else if (e.key === "ArrowLeft" || e.key === "ArrowDown") {
      e.preventDefault();
      nudge(-step);
    } else if (e.key === "Enter") {
      e.preventDefault();
      save();
    }
  };

  const save = () => {
    const cal = saveCalibration(width);
    toast("Screen calibrated", { description: `${fmtNum(cal.px_per_mm, 3)} CSS px per mm on this display.`, tone: "ok" });
    if (next && next.startsWith("/")) router.push(next);
  };

  return (
    <Container className="py-8 sm:py-10">
      <div className="grid grid-cols-1 gap-8 lg:grid-cols-[minmax(0,1fr)_320px]">
        <div className="min-w-0 space-y-5">
          <div className="space-y-2">
            <div className="text-[12px] font-medium uppercase tracking-[0.08em] text-accent-text">One-time setup · this screen</div>
            <h1 className="text-[28px] leading-tight font-semibold tracking-[-0.025em] sm:text-[32px]">Calibrate your screen with a card</h1>
            <p className="max-w-2xl text-[15px] leading-6 text-muted">
              Any bank, ID or transit card is the same size worldwide: {fmtNum(CARD_W_MM)} × {fmtNum(CARD_H_MM)} mm. Hold one flat
              against the screen with its top-left corner in the corner mark, then resize the rectangle until its edges match the card
              exactly.
            </p>
          </div>

          {drift ? (
            <div role="alert" className="flex items-start gap-3 rounded-lg border border-warn-border bg-warn-soft px-4 py-3 text-[13px] text-fg">
              <Info className="mt-0.5 size-4 shrink-0 text-warn" aria-hidden />
              <div>
                <div className="font-medium">Recheck needed</div>
                <div className="text-muted">{drift} Re-match the card so the mat stays true to size.</div>
              </div>
            </div>
          ) : null}

          <div
            ref={stageRef}
            className="relative overflow-hidden rounded-xl border border-border bg-surface bg-dots p-1"
            style={{ minHeight: Math.max(260, height + 72) }}
          >
            <div
              role="slider"
              tabIndex={0}
              aria-label="Card width on screen"
              aria-valuemin={MIN_W}
              aria-valuemax={Math.round(maxW)}
              aria-valuenow={Math.round(width)}
              aria-valuetext={`${fmtNum(width, 1)} pixels wide, ${fmtNum(pxPerMm, 3)} pixels per millimetre`}
              onKeyDown={onKey}
              className="absolute top-6 left-6 rounded-[10px] border-2 border-accent bg-accent-soft/60 outline-offset-4 transition-[box-shadow] focus-visible:shadow-[0_0_0_4px_var(--ring)]"
              style={{ width, height, borderRadius: (3.18 / CARD_W_MM) * width }}
            >
              <span className="absolute -top-[9px] -left-[9px] size-4 border-t-2 border-l-2 border-fg" aria-hidden />
              <div className="absolute inset-0 flex flex-col items-center justify-center gap-1 text-center">
                <CreditCard className="size-6 text-accent-text" aria-hidden />
                <span className="font-mono text-[13px] text-fg tnum">
                  {fmtNum(CARD_W_MM)} × {fmtNum(CARD_H_MM)} mm
                </span>
                <span className="font-mono text-[11px] text-muted tnum">{fmtNum(pxPerMm, 3)} px/mm</span>
              </div>
              <span
                aria-hidden
                onPointerDown={(e) => {
                  (e.target as HTMLElement).setPointerCapture(e.pointerId);
                  drag.current = { x: e.clientX, w: width };
                }}
                onPointerMove={(e) => {
                  if (!drag.current) return;
                  setW(clamp(drag.current.w + (e.clientX - drag.current.x), MIN_W, maxW));
                }}
                onPointerUp={() => (drag.current = null)}
                className="absolute -right-3 -bottom-3 flex size-7 cursor-nwse-resize touch-none items-center justify-center rounded-full border-2 border-accent bg-surface shadow-md"
              >
                <span className="size-2 rounded-full bg-accent" />
              </span>
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-3">
            <Button variant="outline" size="icon" aria-label="Shrink by 1 pixel" onClick={() => nudge(-1)}>
              <Minus aria-hidden />
            </Button>
            <Slider
              aria-label="Card width"
              className="max-w-sm flex-1"
              min={MIN_W}
              max={maxW}
              step={0.25}
              value={[width]}
              onValueChange={(v) => setW(v[0] ?? width)}
            />
            <Button variant="outline" size="icon" aria-label="Grow by 1 pixel" onClick={() => nudge(1)}>
              <Plus aria-hidden />
            </Button>
            <div className="text-[12px] text-muted">
              Focus the card and use <Kbd>←</Kbd> <Kbd>→</Kbd> (1 px), <Kbd>Shift</Kbd> 10 px, <Kbd>Alt</Kbd> 0.25 px
            </div>
          </div>

          <div className="flex flex-wrap gap-2">
            <Button variant="primary" size="lg" onClick={save}>
              <Check aria-hidden /> Save calibration
            </Button>
            {calibration ? (
              <Button
                variant="ghost"
                size="lg"
                onClick={() => {
                  clearCalibration();
                  setW(CARD_W_MM * CSS_REFERENCE_PX_PER_MM);
                }}
              >
                <RotateCcw aria-hidden /> Start over
              </Button>
            ) : null}
          </div>
        </div>

        <aside className="space-y-4">
          <div className="rounded-lg border border-border bg-surface p-4">
            <div className="flex items-center justify-between">
              <h2 className="text-[13px] font-semibold">This display</h2>
              {ready && calibration && !drift ? (
                <Badge tone="ok">
                  <Check aria-hidden /> calibrated
                </Badge>
              ) : (
                <Badge tone="neutral">not calibrated</Badge>
              )}
            </div>
            <dl className="mt-3 space-y-2 font-mono text-[12px] tnum">
              <Row k="scale (saved)" v={calibration ? `${fmtNum(calibration.px_per_mm, 3)} px/mm` : "—"} />
              <Row k="scale (now)" v={`${fmtNum(pxPerMm, 3)} px/mm`} />
              <Row k="device px ratio" v={ready ? fmtNum(window.devicePixelRatio, 2) : "—"} />
              <Row k="screen" v={ready ? `${window.screen.width}×${window.screen.height} px` : "—"} />
            </dl>
          </div>
          <div className="space-y-2.5 rounded-lg border border-border bg-surface p-4 text-[13px] leading-5 text-muted">
            <h2 className="text-[13px] font-semibold text-fg">Tips for a true 1:1</h2>
            <p>Look straight at the card, not from an angle — parallax makes edges look offset.</p>
            <p>Match the outer edge of the card to the outer edge of the orange line.</p>
            <p>Keep browser zoom at 100 %. If you change zoom or move to another monitor, PartSmith asks you to recheck.</p>
          </div>
          {ready && calibration && !drift ? (
            <div className="rounded-lg border border-border bg-surface p-4">
              <div className="flex items-center gap-2 text-[13px] font-semibold">
                <MonitorSmartphone className="size-4 text-muted" aria-hidden /> Next
              </div>
              <p className="mt-1 text-[13px] text-muted">Open the full-screen mat and lay your part on it.</p>
              <Button asChild variant="solid" className="mt-3 w-full">
                <Link href="/mat">
                  Open the screen mat <ArrowRight aria-hidden />
                </Link>
              </Button>
            </div>
          ) : null}
        </aside>
      </div>
    </Container>
  );
}

function Row({ k, v }: { k: string; v: string }) {
  return (
    <div className="flex justify-between gap-3">
      <dt className="font-sans text-muted">{k}</dt>
      <dd className="text-fg">{v}</dd>
    </div>
  );
}
