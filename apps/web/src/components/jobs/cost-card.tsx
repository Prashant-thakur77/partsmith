"use client";

/** Per-job model spend: total USD, tokens in/out and calls, per model — added up from the job's own model_call events. */
import { Coins } from "lucide-react";
import * as React from "react";
import type { ModelCallEvent } from "@/lib/api-types";
import { fmtInt, fmtUsd } from "@/lib/format";
import { jobCost } from "@/lib/job-cost";
import { cn } from "@/lib/utils";
import { Badge } from "../ui/badge";
import { Eyebrow } from "../ui/card";

export function CostCard({ calls, replay, className }: { calls: readonly ModelCallEvent[]; replay: boolean; className?: string }) {
  const c = React.useMemo(() => jobCost(calls, { replay }), [calls, replay]);
  if (!c.calls) return null;
  return (
    <section className={cn("space-y-2 rounded-lg border border-border bg-surface p-4", className)} aria-label="Cost" data-testid="job-cost">
      <div className="flex items-center justify-between gap-2">
        <Eyebrow className="inline-flex items-center gap-1.5">
          <Coins className="size-3.5" aria-hidden /> Cost
        </Eyebrow>
        <Badge tone={c.kind === "live" ? "accent" : "neutral"}>{c.kind === "replay" ? "recorded" : c.kind}</Badge>
      </div>
      <p className="flex flex-wrap items-baseline gap-x-3 gap-y-1 font-mono text-[12.5px] text-fg tnum">
        <span className="text-[18px] font-semibold">{fmtUsd(c.usd)}</span>
        <span>
          {fmtInt(c.tokensIn)} in · {fmtInt(c.tokensOut)} out tokens
        </span>
        <span>
          {fmtInt(c.calls)} call{c.calls === 1 ? "" : "s"}
          {c.failed ? ` (${fmtInt(c.failed)} failed)` : ""}
        </span>
      </p>
      <p className="text-[12px] text-muted">{c.note}</p>
      <table className="w-full font-mono text-[11.5px] tnum">
        <caption className="sr-only">Model calls per model</caption>
        <thead>
          <tr className="text-left text-[11px] text-subtle">
            <th scope="col" className="py-1 font-sans font-medium">Model</th>
            <th scope="col" className="py-1 text-right font-sans font-medium">Calls</th>
            <th scope="col" className="py-1 text-right font-sans font-medium">Tokens</th>
            <th scope="col" className="py-1 text-right font-sans font-medium">USD</th>
          </tr>
        </thead>
        <tbody>
          {c.perModel.map((m) => (
            <tr key={`${m.provider}/${m.model}/${m.mode}`} className="border-t border-border">
              <th scope="row" className="max-w-[12rem] truncate py-1 text-left font-normal" title={`${m.provider} · ${m.model} · ${m.mode}`}>
                {m.model}
                {m.mode !== "live" ? <span className="ml-1 font-sans text-[10.5px] text-subtle">· {m.mode === "replay" ? "recorded" : m.mode}</span> : null}
              </th>
              <td className="py-1 text-right">{fmtInt(m.calls)}</td>
              <td className="py-1 text-right">{fmtInt(m.tokensIn + m.tokensOut)}</td>
              <td className="py-1 text-right">{fmtUsd(m.usd)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}
