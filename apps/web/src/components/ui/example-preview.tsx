import { Eye } from "lucide-react";
import * as React from "react";
import { cn } from "@/lib/utils";

/**
 * A clearly labelled example shown where a page has no records yet: hatched, dashed and headed "Example", so it is never
 * mistaken for (or mixed with) real data. `kind` says what it is made of: an illustration, recorded runs, a template.
 */
export function ExamplePreview({ title, kind, children, className }: { title: string; kind: string; children: React.ReactNode; className?: string }) {
  const id = React.useId();
  return (
    <section aria-labelledby={id} className={cn("overflow-hidden rounded-xl border border-dashed border-border-strong bg-surface-2/60", className)}>
      <div className="flex flex-wrap items-center gap-2 border-b border-dashed border-border-strong bg-hatch px-4 py-2">
        <span className="inline-flex items-center gap-1 rounded-sm bg-fg px-1.5 py-0.5 font-mono text-[10.5px] font-semibold tracking-[0.12em] text-bg uppercase">
          <Eye className="size-3" aria-hidden /> Example
        </span>
        <h2 id={id} className="text-[13px] font-semibold">
          {title}
        </h2>
        <span className="ml-auto text-[11.5px] text-muted">{kind}</span>
      </div>
      <div className="p-4">{children}</div>
    </section>
  );
}
