import { cn } from "@/lib/utils";
import { CopyButton } from "./copy-button";

export function CodeBlock({
  code,
  title,
  language,
  className,
  maxHeight,
  wrap = false,
}: {
  code: string;
  title?: string;
  language?: string;
  className?: string;
  maxHeight?: number;
  wrap?: boolean;
}) {
  return (
    <div className={cn("overflow-hidden rounded-lg border border-border bg-surface-2", className)}>
      <div className="flex h-9 items-center justify-between gap-2 border-b border-border pr-1.5 pl-3">
        <span className="truncate font-mono text-[11px] text-muted">{title ?? language ?? ""}</span>
        <CopyButton value={code} />
      </div>
      <pre
        tabIndex={0}
        aria-label={title ? `${title} code` : "Code"}
        className={cn(
          "scrollbar-thin overflow-auto p-3.5 font-mono text-[12.5px] leading-[1.65] text-fg",
          wrap ? "whitespace-pre-wrap break-words" : "whitespace-pre",
        )}
        style={maxHeight ? { maxHeight } : undefined}
      >
        <code>{code}</code>
      </pre>
    </div>
  );
}
