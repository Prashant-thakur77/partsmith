/** Material and load advice for parts that carry a load (rule table: src/lib/load-notes.ts). Renders nothing otherwise. */
import { TriangleAlert } from "lucide-react";
import { loadNote, orientationAdvice } from "@/lib/load-notes";
import { cn } from "@/lib/utils";

export function LoadNoteBox({
  family,
  planOrientation,
  className,
  headingLevel = "h3",
}: {
  family: string | null | undefined;
  /** The print plan's computed orientation: when given, the strength advice defers to it. */
  planOrientation?: string | null;
  className?: string;
  headingLevel?: "h2" | "h3";
}) {
  const note = loadNote(family);
  if (!note) return null;
  const H = headingLevel;
  return (
    <section className={cn("space-y-1.5 rounded-md border border-warn-border bg-warn-soft p-3 text-[12.5px] leading-5", className)} aria-label="Printing for load" data-testid="load-note">
      <H className="flex items-center gap-1.5 text-[13px] font-semibold text-fg">
        <TriangleAlert className="size-3.5 shrink-0 text-warn" aria-hidden /> Material and load · {note.title.toLowerCase()}
      </H>
      <dl className="space-y-1 text-muted">
        <div>
          <dt className="inline font-medium text-fg">Material: </dt>
          <dd className="inline">{note.material}</dd>
        </div>
        <div>
          <dt className="inline font-medium text-fg">Which way up: </dt>
          <dd className="inline">{orientationAdvice(note, planOrientation)}</dd>
        </div>
        <div>
          <dt className="inline font-medium text-fg">Walls and infill: </dt>
          <dd className="inline">{note.walls}</dd>
        </div>
      </dl>
      <p className="font-medium text-fg">{note.warning}</p>
    </section>
  );
}
