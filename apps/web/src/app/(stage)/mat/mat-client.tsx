"use client";

import { useSearchParams } from "next/navigation";
import { ScreenMat } from "@/components/mat/screen-mat";
import { StageShell } from "@/components/mat/stage-shell";
import { useMatChoice } from "@/components/mat/use-mat-layout";
import { Spinner } from "@/components/ui/spinner";
import { fmtNum } from "@/lib/format";
import type { ScreenCalibration } from "@/lib/calibration";

function MatStage({ cal, preferred }: { cal: ScreenCalibration; preferred: string | null }) {
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
      <ScreenMat layout={choice.layout} pxPerMm={cal.px_per_mm} rotated={choice.rotated} />
      <p className="max-w-[90vw] text-center text-[11px] text-white/45">
        {choice.layout.title} · {fmtNum(choice.layout.width_mm, 0)} × {fmtNum(choice.layout.height_mm, 0)} mm · {fmtNum(cal.px_per_mm, 3)} px/mm
        {source === "static" ? " · offline copy" : ""} · Tips (top right) for glare and lighting
      </p>
    </div>
  );
}

export function MatClient() {
  const preferred = useSearchParams().get("mat");
  return (
    <StageShell exitHref="/fix" title="Screen mat" calibrateNext="/mat">
      {(cal) => <MatStage cal={cal} preferred={preferred} />}
    </StageShell>
  );
}
