"use client";

import { Badge } from "@/components/ui/badge";
import type { Status } from "@/lib/api-types";
import { fmtInt, fmtUsd, titleCase } from "@/lib/format";
import { MODE_WORD, stageModelRows } from "@/lib/stage-models";
import { cn } from "@/lib/utils";

/** How a stage runs or how a logged call ran, in one plain word; live gets the accent, the others hatching. */
export function ModeWord({ mode }: { mode: string }) {
  return <Badge tone={mode === "live" ? "accent" : "mock"}>{MODE_WORD[mode] ?? mode}</Badge>;
}

/**
 * One row per stage: the model it is set up to use and how it runs now, beside the models actually seen in its logged
 * `model_call` events (made on this server, and in the recorded runs it serves). The two never share a column, so a
 * "live" logged call never sits under a "recorded" header.
 */
export function StageModelsTable({ s, limit, showCost = true }: { s: Status; limit?: number; showCost?: boolean }) {
  const all = stageModelRows(s);
  const rows = limit != null ? all.slice(0, limit) : all;
  const heads = ["Stage", "Set up now", "Runs now", "Seen in logged calls (model · how it ran · calls)", ...(showCost ? ["Spent here"] : [])];
  return (
    <div tabIndex={0} role="region" aria-label="Models by stage" className="scrollbar-thin overflow-x-auto rounded-lg border border-border bg-surface">
      <table className="w-full min-w-[720px] text-[13px]" data-testid="stage-models">
        <thead className="bg-surface-2 text-left text-[11px] text-subtle">
          <tr>
            {heads.map((h, i) => (
              <th key={h} scope="col" className={cn("px-3 py-2 align-bottom font-medium", i === 4 ? "text-right whitespace-nowrap" : i < 3 && "whitespace-nowrap")}>
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.key} className="border-t border-border align-top" data-stage={r.stage}>
              <th scope="row" className="px-3 py-2 text-left font-normal whitespace-nowrap">
                {r.role} <span className="text-subtle">· {titleCase(r.stage)}</span>
              </th>
              <td className="px-3 py-2">
                <span className="font-mono text-[12px]">{r.model}</span>
                {r.open ? <Badge tone="accent" className="ml-1.5">open weights</Badge> : null}
                <div className="text-[11.5px] text-subtle">{r.where}</div>
              </td>
              <td className="px-3 py-2">
                <ModeWord mode={r.mode} />
              </td>
              <td className="px-3 py-2">
                {r.seen.length ? (
                  <ul className="space-y-1">
                    {r.seen.map((m) => (
                      <li key={`${m.source}-${m.model}-${m.mode}`} className="flex flex-wrap items-center gap-x-1.5 gap-y-0.5 text-[12px]">
                        <span className="font-mono">{m.model}</span>
                        <ModeWord mode={m.mode} />
                        <span className="font-mono text-muted tnum">×{fmtInt(m.calls)}</span>
                        <span className="text-subtle">{m.source === "here" ? "made here" : "in recorded runs"}</span>
                      </li>
                    ))}
                    {r.differs ? <li className="text-[11.5px] text-subtle">A logged call used a different model than the one set up now.</li> : null}
                  </ul>
                ) : (
                  <span className="text-[12px] text-subtle">no calls logged yet</span>
                )}
              </td>
              {showCost ? <td className="px-3 py-2 text-right font-mono tnum">{r.usd > 0 ? fmtUsd(r.usd) : "—"}</td> : null}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
