"use client";

import { useQuery, keepPreviousData } from "@tanstack/react-query";
import * as React from "react";
import { api } from "./api";

export function useDebounced<T>(value: T, ms: number): T {
  const [v, setV] = React.useState(value);
  React.useEffect(() => {
    const t = window.setTimeout(() => setV(value), ms);
    return () => window.clearTimeout(t);
  }, [value, ms]);
  return v;
}

function stableParams(values: Record<string, number>): Record<string, number> {
  return Object.fromEntries(Object.entries(values).sort(([a], [b]) => a.localeCompare(b)));
}

/**
 * Re-bake a registry part whenever knob values settle (debounced). Previous result stays visible while the next bake runs;
 * stale requests are aborted by TanStack Query when the key changes.
 */
export function useBake(slug: string | null | undefined, values: Record<string, number> | null, debounceMs = 220) {
  const debounced = useDebounced(values, debounceMs);
  const params = debounced ? stableParams(debounced) : null;
  const q = useQuery({
    queryKey: ["bake", slug, params],
    queryFn: ({ signal }) => api.bake(slug!, params!, "view", signal),
    enabled: !!slug && !!params && Object.keys(params).length > 0,
    placeholderData: keepPreviousData,
    staleTime: Infinity,
    retry: false,
  });
  const pending = values !== debounced || q.isFetching;
  return { ...q, pending };
}

/** Re-bake a job's current part program (before it is published) through `/jobs/{id}/bake`. */
export function useJobBake(jobId: string | null | undefined, values: Record<string, number> | null, debounceMs = 220) {
  const debounced = useDebounced(values, debounceMs);
  const params = debounced ? stableParams(debounced) : null;
  const q = useQuery({
    queryKey: ["job-bake", jobId, params],
    queryFn: ({ signal }) => api.jobBake(jobId!, params!, "view", signal),
    enabled: !!jobId && !!params && Object.keys(params).length > 0,
    placeholderData: keepPreviousData,
    staleTime: Infinity,
    retry: false,
  });
  const pending = values !== debounced || q.isFetching;
  return { ...q, pending };
}

export function useMediaQuery(query: string): boolean {
  return React.useSyncExternalStore(
    (cb) => {
      const mq = window.matchMedia(query);
      mq.addEventListener("change", cb);
      return () => mq.removeEventListener("change", cb);
    },
    () => window.matchMedia(query).matches,
    () => false,
  );
}

export function usePrefersReducedMotion(): boolean {
  return useMediaQuery("(prefers-reduced-motion: reduce)");
}

/** Animate a number towards `target` (used when residuals count down). Respects reduced motion. */
export function useCountTo(target: number | null | undefined, ms = 700): number | null {
  const reduced = usePrefersReducedMotion();
  const [v, setV] = React.useState<number | null>(target ?? null);
  const from = React.useRef<number | null>(target ?? null);
  React.useEffect(() => {
    if (target === null || target === undefined) {
      setV(null);
      from.current = null;
      return;
    }
    const start = from.current;
    if (reduced || start === null || start === target) {
      setV(target);
      from.current = target;
      return;
    }
    let raf = 0;
    const t0 = performance.now();
    const tick = (now: number) => {
      const k = Math.min(1, (now - t0) / ms);
      const e = 1 - Math.pow(1 - k, 3);
      const cur = start + (target - start) * e;
      setV(cur);
      from.current = cur;
      if (k < 1) raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [target, ms, reduced]);
  return v;
}
