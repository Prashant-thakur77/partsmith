"use client";

import { useSearchParams } from "next/navigation";
import { ScreenMat } from "@/components/mat/screen-mat";
import { StageShell } from "@/components/mat/stage-shell";
import { useMatChoice } from "@/components/mat/use-mat-layout";
import { Spinner } from "@/components/ui/spinner";
import { fmtNum } from "@/lib/format";
import { I18nRegion } from "@/lib/i18n";
import type { ScreenCalibration } from "@/lib/calibration";
import type { StageTone } from "@/lib/stage";

function MatStage({ cal, preferred, stage }: { cal: ScreenCalibration; preferred: string | null; stage: StageTone }) {
  const { choice, mats, isPending, source } = useMatChoice(cal.px_per_mm, preferred);
  if (isPending) return <Spinner className="text-white/60" label="Loading mat" />;
  if (!choice) {
    const smallest = [...mats].sort((a, b) => a.width_mm - b.width_mm)[0];
    return (
      <div className="max-w-sm p-6 text-center text-[14px] text-white/80">
        This window is too small for a 1:1 mat
        {smallest ? (
          <>
            {" "}
            (the smallest needs {fmtNum(smallest.min_screen_mm.w, 0)} × {fmtNum(smallest.min_screen_mm.h, 0)} mm of screen)
          </>
        ) : null}
        . Make the window bigger or go full screen.
      </div>
    );
  }
  return (
    <div className="flex flex-col items-center gap-2">
      <ScreenMat layout={choice.layout} pxPerMm={cal.px_per_mm} rotated={choice.rotated} stage={stage} />
      <p className="max-w-[90vw] text-center text-[11px] text-white/45">
        {choice.layout.title} · {fmtNum(choice.layout.width_mm, 0)} × {fmtNum(choice.layout.height_mm, 0)} mm · {fmtNum(cal.px_per_mm, 3)} px/mm
        {source === "static" ? " · offline copy" : ""} · {stage} stage · Use Dark for white or light-grey parts
      </p>
    </div>
  );
}

export function MatClient() {
  return (
    <I18nRegion>
      <MatInner />
    </I18nRegion>
  );
}

function MatInner() {
  const preferred = useSearchParams().get("mat");
  return (
    <StageShell exitHref="/fix" title="Screen mat" calibrateNext="/mat" phonePath="/fix">
      {(cal, stage) => <MatStage cal={cal} preferred={preferred} stage={stage} />}
    </StageShell>
  );
}
