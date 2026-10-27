"use client";

/**
 * Laptop side of the phone fit check: follows the job's event stream (`/events?follow=1`) and returns fit-check results
 * that arrive after the page opened. The API reports a phone upload as metric events `fit_check_passed` (1/0),
 * `fit_check_iou` and `fit_check_hausdorff_mm`, then a `measure_overlay` artifact labelled "fit check on <mat>: PASS|FAIL"
 * (docs/API.md). Values come straight from those events; the verdict is the server's. Reconnects with `from_seq`.
 */
import * as React from "react";
import type { CaptureReport } from "./api-types";
import { ArtifactEventSchema, MetricEventSchema } from "./api-types";
import { apiUrl } from "./api";

export type LiveFitCheck = {
  passed: boolean;
  iou: number | null;
  hausdorff_mm: number | null;
  mean_mm: number | null;
  reasons: string[];
  overlay_url: string | null;
  capture: CaptureReport | null;
  label: string;
};

/** Folds one raw event into the list of live results (exported for tests). Unrelated events return `cur` unchanged. */
export function foldFitEvent(cur: LiveFitCheck[], raw: unknown): LiveFitCheck[] {
  if (!raw || typeof raw !== "object") return cur;
  const t = (raw as { t?: unknown }).t;
  if (t === "metric") {
    const name = (raw as { name?: unknown }).name;
    if (typeof name !== "string" || !name.startsWith("fit_check_")) return cur;
    const m = MetricEventSchema.safeParse(raw);
    if (!m.success) {
      console.error("[contract] fit_check metric event", m.error.issues, raw);
      return cur;
    }
    const v = m.data.value;
    if (m.data.name === "fit_check_passed")
      return [...cur, { passed: v >= 0.5, iou: null, hausdorff_mm: null, mean_mm: null, reasons: [], overlay_url: null, capture: null, label: "" }];
    const last = cur.at(-1);
    if (!last) return cur;
    const next = { ...last };
    if (m.data.name === "fit_check_iou") next.iou = v;
    else if (m.data.name === "fit_check_hausdorff_mm") next.hausdorff_mm = v;
    else if (m.data.name === "fit_check_mean_mm") next.mean_mm = v;
    else return cur;
    return [...cur.slice(0, -1), next];
  }
  if (t === "artifact") {
    const a = ArtifactEventSchema.safeParse(raw);
    if (!a.success || a.data.kind !== "measure_overlay" || !a.data.label.toLowerCase().startsWith("fit check")) return cur;
    const last = cur.at(-1);
    if (!last || last.overlay_url) return cur;
    return [...cur.slice(0, -1), { ...last, overlay_url: a.data.url, label: a.data.label }];
  }
  return cur;
}

export function useLiveFitChecks(jobId: string, enabled = true) {
  const [results, setResults] = React.useState<LiveFitCheck[]>([]);
  React.useEffect(() => {
    if (!enabled) return;
    const since = Date.now() / 1000;
    let last = -1;
    let es: EventSource | null = null;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let closed = false;
    const open = () => {
      if (closed) return;
      es = new EventSource(apiUrl(`/jobs/${encodeURIComponent(jobId)}/events`, { follow: 1, from_seq: last >= 0 ? last + 1 : undefined }));
      es.onmessage = (m: MessageEvent<string>) => {
        let raw: unknown;
        try {
          raw = JSON.parse(m.data);
        } catch {
          return;
        }
        const seq = (raw as { seq?: number }).seq;
        if (typeof seq === "number") last = Math.max(last, seq);
        const ts = (raw as { ts?: number }).ts ?? 0;
        if (ts < since - 1) return;
        setResults((cur) => foldFitEvent(cur, raw));
      };
      es.onerror = () => {
        es?.close();
        if (!closed) timer = setTimeout(open, 3000);
      };
    };
    open();
    return () => {
      closed = true;
      es?.close();
      if (timer) clearTimeout(timer);
    };
  }, [jobId, enabled]);
  return results;
}
