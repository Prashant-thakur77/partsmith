import { cn } from "@/lib/utils";

/** One line per fix iteration, shown under the error chart. Kept apart from the (lazy-loaded) agent log. */
export function ProgressLines({ lines, className }: { lines: { iter: number; text: string }[]; className?: string }) {
  if (!lines.length) return null;
  return (
    <ol className={cn("space-y-1 font-mono text-[11.5px] leading-5 text-muted tnum", className)} aria-label="Progress per iteration">
      {lines.map((l) => (
        <li key={l.iter} className="flex gap-2">
          <span className="shrink-0 text-subtle">#{l.iter}</span>
          <span className="min-w-0">{l.text}</span>
        </li>
      ))}
    </ol>
  );
}
