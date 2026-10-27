import { cn } from "@/lib/utils";
import { CopyButton } from "../ui/copy-button";

/** Unified diff with +/- line colouring (text markers stay visible, so colour is not the only signal). */
export function CodeDiff({ diff, className, maxHeight = 320 }: { diff: string; className?: string; maxHeight?: number }) {
  const lines = diff.replace(/\n$/, "").split("\n");
  return (
    <div className={cn("overflow-hidden rounded-md border border-border bg-surface-2", className)}>
      <div className="flex h-8 items-center justify-between border-b border-border pr-1 pl-3">
        <span className="font-mono text-[11px] text-muted">part.py · diff</span>
        <CopyButton value={diff} />
      </div>
      <pre tabIndex={0} aria-label="Code diff" className="scrollbar-thin overflow-auto py-2 font-mono text-[11.5px] leading-[1.6]" style={{ maxHeight }}>
        {lines.map((l, i) => {
          const add = l.startsWith("+") && !l.startsWith("+++");
          const del = l.startsWith("-") && !l.startsWith("---");
          const hunk = l.startsWith("@@");
          return (
            <div
              key={i}
              className={cn(
                "px-3 whitespace-pre",
                add && "bg-ok-soft text-ok",
                del && "bg-bad-soft text-bad",
                hunk && "text-info",
                !add && !del && !hunk && "text-muted",
              )}
            >
              {l || " "}
            </div>
          );
        })}
      </pre>
    </div>
  );
}
