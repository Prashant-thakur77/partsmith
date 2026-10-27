"use client";

import { useQuery } from "@tanstack/react-query";
import * as React from "react";
import { loadScreenMats } from "@/lib/mats";
import type { MatLayout } from "@/lib/api-types";

export type MatChoice = { layout: MatLayout; rotated: boolean } | null;

function useViewport() {
  return React.useSyncExternalStore(
    (cb) => {
      window.addEventListener("resize", cb);
      return () => window.removeEventListener("resize", cb);
    },
    () => `${window.innerWidth}x${window.innerHeight}`,
    () => "0x0",
  );
}

/** Loads screen mats and picks the largest that fits the current viewport at the calibrated scale (either orientation). */
export function useMatChoice(pxPerMm: number | null, preferred?: string | null, marginPx = 16) {
  const mats = useQuery({ queryKey: ["screen-mats"], queryFn: loadScreenMats, staleTime: Infinity });
  const vp = useViewport();
  const choice: MatChoice = React.useMemo(() => {
    if (!pxPerMm || !mats.data) return null;
    const [vw, vh] = vp.split("x").map(Number) as [number, number];
    const fits = (m: MatLayout, rot: boolean) => {
      const w = (rot ? m.height_mm : m.width_mm) * pxPerMm;
      const h = (rot ? m.width_mm : m.height_mm) * pxPerMm;
      return w <= vw - marginPx && h <= vh - marginPx;
    };
    const list = [...mats.data.mats].sort((a, b) => b.width_mm * b.height_mm - a.width_mm * a.height_mm);
    const pref = preferred ? list.find((m) => m.mat_id === preferred) : undefined;
    for (const m of pref ? [pref, ...list] : list) {
      if (fits(m, false)) return { layout: m, rotated: false };
      if (fits(m, true)) return { layout: m, rotated: true };
    }
    return null;
  }, [pxPerMm, mats.data, vp, preferred, marginPx]);
  return { choice, mats: mats.data?.mats ?? [], source: mats.data?.source, isPending: mats.isPending, error: mats.error, viewport: vp };
}
