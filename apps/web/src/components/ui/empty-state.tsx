import type { LucideIcon } from "lucide-react";
import * as React from "react";
import { cn } from "@/lib/utils";

export function EmptyState({
  icon: Icon,
  title,
  children,
  action,
  className,
  compact = false,
}: {
  icon?: LucideIcon;
  title: string;
  children?: React.ReactNode;
  action?: React.ReactNode;
  className?: string;
  compact?: boolean;
}) {
  return (
    <div
      className={cn(
        "flex flex-col items-center justify-center rounded-lg border border-dashed border-border-strong text-center",
        compact ? "gap-2 px-4 py-6" : "gap-3 px-6 py-12",
        className,
      )}
    >
      {Icon ? (
        <div className="flex size-10 items-center justify-center rounded-full border border-border bg-surface-2 text-muted">
          <Icon className="size-[18px]" aria-hidden />
        </div>
      ) : null}
      <div className="max-w-md space-y-1">
        <p className="text-sm font-medium text-fg">{title}</p>
        {children ? <div className="text-[13px] leading-5 text-muted">{children}</div> : null}
      </div>
      {action ? <div className="mt-1 flex flex-wrap justify-center gap-2">{action}</div> : null}
    </div>
  );
}
