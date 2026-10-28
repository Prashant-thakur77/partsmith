"use client";

import { Brain, ChevronDown, Crosshair, Wrench } from "lucide-react";
import * as React from "react";
import type { FocusEvent, ModelCallEvent, ThoughtEvent, ToolCallEvent } from "@/lib/api-types";
import { fmtMs } from "@/lib/format";
import { cn } from "@/lib/utils";
import { Badge } from "../ui/badge";
import { ModeBadge } from "../ui/provenance";

type AgentEvent = ThoughtEvent | ToolCallEvent | FocusEvent;

function argsSummary(args: Record<string, unknown>): string {
  return Object.entries(args)
    .slice(0, 4)
    .map(([k, v]) => {
      const s = typeof v === "number" ? (Number.isInteger(v) ? String(v) : v.toFixed(2)) : typeof v === "string" ? v : JSON.stringify(v);
      return `${k}=${s && s.length > 28 ? `${s.slice(0, 27)}…` : s}`;
    })
    .join(", ");
}

function Thought({ e, mode }: { e: ThoughtEvent; mode?: string }) {
  const [open, setOpen] = React.useState(false);
  const long = e.text.length > 180;
  return (
    <div className="rounded-md border border-border bg-surface-2/60 p-2.5">
      <div className="flex flex-wrap items-center gap-1.5 text-[11px] text-subtle">
        <Brain className="size-3.5 text-muted" aria-hidden />
        <span className="font-medium text-fg">Reasoning summary</span>
        <span className="font-mono">{e.model || e.stage}</span>
        {mode ? <ModeBadge mode={mode} /> : null}
        {e.iter != null ? <span className="font-mono">#{e.iter}</span> : null}
      </div>
      <p className={cn("mt-1.5 text-[12.5px] leading-5 whitespace-pre-line text-muted", !open && long && "line-clamp-3")}>{e.text}</p>
      {long ? (
        <button type="button" onClick={() => setOpen((v) => !v)} aria-expanded={open} className="mt-1 inline-flex items-center gap-1 text-[11.5px] font-medium text-accent-text">
          {open ? "Show less" : "Show all"} <ChevronDown className={cn("size-3 transition-transform", open && "rotate-180")} aria-hidden />
        </button>
      ) : null}
    </div>
  );
}

function ToolCall({ e }: { e: ToolCallEvent }) {
  const args = argsSummary(e.args);
  return (
    <div className="flex gap-2 py-1.5">
      <Wrench className={cn("mt-0.5 size-3.5 shrink-0", e.ok ? "text-muted" : "text-bad")} aria-hidden />
      <div className="min-w-0 flex-1 text-[12px]">
        <div className="flex flex-wrap items-baseline gap-x-1.5">
          <code className="font-mono font-medium text-fg">
            {e.name}({args})
          </code>
          <span className="font-mono text-[11px] text-subtle tnum">{fmtMs(e.ms)}</span>
          {!e.ok ? <Badge tone="bad">error</Badge> : null}
        </div>
        {e.result ? <p className="mt-0.5 line-clamp-3 text-muted">→ {e.result}</p> : null}
      </div>
    </div>
  );
}

function Focus({ e, onShow }: { e: FocusEvent; onShow?: (e: FocusEvent) => void }) {
  return (
    <div className="flex items-center gap-2 py-1.5 text-[12px]">
      <Crosshair className="size-3.5 shrink-0 text-accent-text" aria-hidden />
      <span className="min-w-0 flex-1 text-muted">
        Looking at <span className="font-medium text-fg">{e.feature || "a location"}</span>
        {e.label ? <> — {e.label}</> : null}
        {e.at_mm ? <span className="ml-1 font-mono text-[11px] text-subtle tnum">({e.at_mm.map((v) => v.toFixed(1)).join(", ")}) mm</span> : null}
      </span>
      {onShow && e.at_mm ? (
        <button type="button" onClick={() => onShow(e)} className="rounded px-1.5 py-0.5 text-[11.5px] font-medium text-accent-text hover:bg-surface-2">
          Show
        </button>
      ) : null}
    </div>
  );
}

/** Readable agent log: reasoning summaries (never raw chain of thought), tool calls with what code returned, focus points. */
export function AgentLog({ events, modelCalls, onFocus }: { events: AgentEvent[]; modelCalls: ModelCallEvent[]; onFocus?: (e: FocusEvent) => void }) {
  const modeByStage = React.useMemo(() => {
    const m = new Map<string, string>();
    for (const c of modelCalls) m.set(c.stage, c.mode);
    return m;
  }, [modelCalls]);
  if (!events.length)
    return (
      <p className="py-4 text-center text-[13px] leading-5 text-muted">
        No agent activity yet. When the fixer runs as a tool-using agent, its reasoning summaries and every tool call show up here.
      </p>
    );
  return (
    <ol className="space-y-1.5" aria-label="Agent log">
      {events.map((e) => (
        <li key={e.seq}>
          {e.t === "thought" ? <Thought e={e} mode={modeByStage.get(e.stage)} /> : e.t === "tool_call" ? <ToolCall e={e} /> : <Focus e={e} onShow={onFocus} />}
        </li>
      ))}
    </ol>
  );
}

export { ProgressLines } from "./progress-lines";
