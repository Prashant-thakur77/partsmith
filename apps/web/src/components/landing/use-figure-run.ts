"use client";

import { useQuery } from "@tanstack/react-query";
import * as React from "react";
import { api } from "@/lib/api";
import { figureFromJob, pickFigureRun, pickLoopRun, pickReviewRun } from "@/lib/figure-run";

/** The stored runs (`/replays`), shared by every landing section that plays one back. */
export function useReplays() {
  return useQuery({ queryKey: ["replays"], queryFn: api.replays, staleTime: 300_000 });
}

/** A stored run's job detail turned into drawing data. `which` picks the run from `/replays` (see lib/figure-run.ts). */
export function useStoredRun(which: "figure" | "loop" | "review", enabled = true) {
  const replays = useReplays();
  const pick = React.useMemo(() => {
    const list = replays.data ?? [];
    return which === "figure" ? pickFigureRun(list) : which === "loop" ? pickLoopRun(list) : pickReviewRun(list);
  }, [replays.data, which]);
  const job = useQuery({ queryKey: ["job", pick?.id], queryFn: () => api.job(pick!.id), enabled: !!pick && enabled, staleTime: 300_000 });
  const fig = React.useMemo(() => (job.data ? figureFromJob(job.data) : null), [job.data]);
  const state: "pending" | "empty" | "error" | "ok" = replays.isError || job.isError ? "error" : replays.data && !pick ? "empty" : fig ? "ok" : "pending";
  return { replays, pick, job, fig, state };
}
