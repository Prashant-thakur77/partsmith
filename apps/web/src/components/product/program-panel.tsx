"use client";

import * as React from "react";
import { programLines } from "@/lib/playground";
import { cn } from "@/lib/utils";
import { CopyButton } from "../ui/copy-button";

/**
 * "This is the program": the part's CadQuery source with the PARAMS defaults rewritten to the current knob values
 * (exactly what the downloaded part.py contains); knob lines are tinted, changed ones highlighted.
 */
export function ProgramPanel({ code, values, title = "part.py", className, maxHeight = 380 }: { code: string; values: Record<string, number>; title?: string; className?: string; maxHeight?: number }) {
  const lines = React.useMemo(() => programLines(code, values), [code, values]);
  const text = React.useMemo(() => lines.map((l) => l.text).join("\n"), [lines]);
  const changed = lines.filter((l) => l.changed).length;
  const preRef = React.useRef<HTMLPreElement>(null);
  // Open at PARAMS: the knobs are the point of this panel.
  React.useEffect(() => {
    const el = preRef.current?.querySelector<HTMLElement>("[data-params-start]");
    if (el && preRef.current) preRef.current.scrollTop = Math.max(0, el.offsetTop - 8);
  }, [code]);
  const start = lines.findIndex((l) => /^PARAMS\s*=/.test(l.text));
  return (
    <div className={cn("overflow-hidden rounded-lg border border-border bg-surface-2", className)}>
      <div className="flex h-9 items-center justify-between gap-2 border-b border-border pr-1.5 pl-3">
        <span className="truncate font-mono text-[11px] text-muted">
          {title}
          {changed ? <span className="text-accent-text"> · {changed} value{changed === 1 ? "" : "s"} changed</span> : null}
        </span>
        <CopyButton value={text} />
      </div>
      <pre ref={preRef} tabIndex={0} aria-label={`${title} with the current knob values`} className="scrollbar-thin relative overflow-auto py-2 font-mono text-[12px] leading-[1.6] text-fg" style={{ maxHeight }}>
        <code>
          {lines.map((l, i) => (
            <span
              key={l.n}
              data-params-start={i === start ? "" : undefined}
              data-knob={l.knob ?? undefined}
              className={cn("block px-3.5 whitespace-pre", l.knob && "bg-surface-3/50", l.changed && "bg-accent-soft text-fg")}
            >
              <span className="mr-3 inline-block w-6 text-right text-subtle select-none" aria-hidden>
                {l.n}
              </span>
              {l.text || " "}
            </span>
          ))}
        </code>
      </pre>
    </div>
  );
}
