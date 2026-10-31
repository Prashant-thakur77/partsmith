"use client";

import { AlertTriangle, CheckCircle2, ChevronDown, Circle, Cpu, Loader2, MinusCircle, XCircle } from "lucide-react";
import * as React from "react";
import type { IterationEvent, ModelCallEvent } from "@/lib/api-types";
import { fmtMs, fmtNum, fmtUsd } from "@/lib/format";
import { STAGE_LABELS, type EventSummary, type StageState } from "@/lib/job-events";
import { cn } from "@/lib/utils";
import { Badge } from "../ui/badge";
import { Tooltip } from "../ui/tooltip";
import { CodeDiff } from "./code-diff";

function StageIcon({ s, live }: { s: StageState; live: boolean }) {
  if (s.status === "ok") return <CheckCircle2 className="size-4 text-ok" aria-hidden />;
  if (s.status === "fail") return <XCircle className="size-4 text-bad" aria-hidden />;
  if (s.status === "skip") return <MinusCircle className="size-4 text-subtle" aria-hidden />;
  if (s.status === "start") return live ? <Loader2 className="size-4 animate-spin text-accent" aria-hidden /> : <AlertTriangle className="size-4 text-warn" aria-hidden />;
  return <Circle className="size-4 text-border-strong" aria-hidden />;
}

const STATUS_TEXT = { ok: "done", fail: "failed", skip: "skipped", start: "running", pending: "waiting" } as const;

export function ModelCallChip({ call }: { call: ModelCallEvent }) {
  return (
    <Tooltip
      content={
        <div className="space-y-0.5 font-mono text-[11px] tnum">
          <div>{call.provider} · {call.model}</div>
          <div>
            {call.tokens_in.toLocaleString("en-US")} in / {call.tokens_out.toLocaleString("en-US")} out · {fmtMs(call.ms)} · {fmtUsd(call.usd)}
          </div>
          {call.error ? <div className="text-bad">{call.error}</div> : null}
        </div>
      }
    >
      <span
        tabIndex={0}
        className={cn(
          "inline-flex h-6 max-w-full cursor-help items-center gap-1.5 rounded-md border px-1.5 text-[11px]",
          call.ok ? "border-border bg-surface" : "border-bad-border bg-bad-soft",
          call.mode !== "live" && "bg-hatch",
        )}
      >
        <Cpu className="size-3 shrink-0 text-subtle" aria-hidden />
        <span className="truncate font-mono text-fg">{call.model}</span>
        <span className={cn("font-mono uppercase", call.mode === "live" ? "text-accent-text" : "text-subtle")}>{call.mode}</span>
        <span className="font-mono text-muted tnum">{fmtUsd(call.usd)}</span>
      </span>
    </Tooltip>
  );
}

function IterationCard({ it, threshold, defaultOpen }: { it: IterationEvent; threshold: number | null; defaultOpen: boolean }) {
  const [open, setOpen] = React.useState(defaultOpen);
  const pass = it.hausdorff_mm != null && threshold != null && it.hausdorff_mm <= threshold;
  return (
    <div className="rounded-md border border-border bg-surface">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        className="flex w-full items-center gap-2 px-3 py-2 text-left hover:bg-surface-2"
      >
        <span className="font-mono text-[11px] text-subtle">#{it.iter}</span>
        <span className="text-[12px] font-medium">{it.strategy === "template" ? "Template" : it.strategy === "free_code" ? "Free code" : "Your edit"}</span>
        <span className="ml-auto flex items-center gap-1.5 font-mono text-[11px] tnum">
          {it.hausdorff_mm != null ? (
            <span className={pass ? "text-ok" : "text-fg"}>{fmtNum(it.hausdorff_mm)} mm</span>
          ) : null}
          {it.total_tests ? <span className="text-muted">{it.passed_tests}/{it.total_tests} tests</span> : null}
        </span>
        <ChevronDown className={cn("size-3.5 text-subtle transition-transform", open && "rotate-180")} aria-hidden />
      </button>
      {open ? (
        <div className="space-y-2 border-t border-border px-3 py-2.5">
          {it.analysis ? <p className="text-[12px] leading-5 text-muted">{it.analysis}</p> : null}
          {it.iou != null ? <p className="font-mono text-[11px] text-subtle tnum">overlap (IoU) {fmtNum(it.iou, 4)}</p> : null}
          {it.edits.length ? (
            <ul className="space-y-0.5 font-mono text-[11px] text-muted">
              {it.edits.slice(0, 8).map((e, i) => (
                <li key={i} className="truncate">
                  {Object.entries(e)
                    .map(([k, v]) => `${k}=${typeof v === "number" ? fmtNum(v) : String(v)}`)
                    .join(" ")}
                </li>
              ))}
            </ul>
          ) : null}
          {it.diff ? <CodeDiff diff={it.diff} maxHeight={240} /> : null}
        </div>
      ) : null}
    </div>
  );
}

/** Stage-by-stage trace from the SSE stream: readable labels, model-call chips, iterations with diffs. */
export function IterationList({ iterations, threshold }: { iterations: IterationEvent[]; threshold: number | null }) {
  if (!iterations.length) return <p className="py-4 text-center text-[13px] text-muted">No iterations yet.</p>;
  return (
    <div className="space-y-1.5">
      {[...iterations].reverse().map((it, i) => (
        <IterationCard key={it.seq} it={it} threshold={threshold} defaultOpen={i === 0} />
      ))}
    </div>
  );
}

export function TraceTimeline({ summary, live }: { summary: EventSummary; live: boolean }) {
  const callsByStage = React.useMemo(() => {
    const m = new Map<string, ModelCallEvent[]>();
    for (const c of summary.modelCalls) m.set(c.stage, [...(m.get(c.stage) ?? []), c]);
    return m;
  }, [summary.modelCalls]);
  const visible = summary.stages.filter((s) => s.status !== "pending" || !summary.done);
  return (
    <ol className="relative space-y-0">
      {visible.map((s, idx) => {
        const calls = callsByStage.get(s.stage) ?? [];
        return (
          <li key={s.stage} className="relative grid grid-cols-[20px_minmax(0,1fr)] gap-x-3 pb-4">
            {idx < visible.length - 1 ? <span className="absolute top-5 bottom-0 left-[9.5px] w-px bg-border" aria-hidden /> : null}
            <span className="relative z-10 mt-0.5 flex size-5 items-center justify-center bg-surface">
              <StageIcon s={s} live={live} />
            </span>
            <div className="min-w-0 space-y-1.5">
              <div className="flex items-baseline justify-between gap-2">
                <span className={cn("text-[13px]", s.status === "pending" ? "text-subtle" : "font-medium text-fg")}>
                  {STAGE_LABELS[s.stage]}
                  <span className="sr-only"> — {STATUS_TEXT[s.status]}</span>
                </span>
                {s.ms != null ? <span className="shrink-0 font-mono text-[11px] text-subtle tnum">{fmtMs(s.ms)}</span> : null}
              </div>
              {s.label ? <p className="text-[12px] leading-5 text-muted">{s.label}</p> : null}
              {calls.length ? (
                <div className="flex flex-wrap gap-1">
                  {calls.slice(-4).map((c) => (
                    <ModelCallChip key={c.seq} call={c} />
                  ))}
                  {calls.length > 4 ? <Badge tone="neutral">+{calls.length - 4} more</Badge> : null}
                </div>
              ) : null}
            </div>
          </li>
        );
      })}
    </ol>
  );
}
