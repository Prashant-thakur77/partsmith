import { cva, type VariantProps } from "class-variance-authority";
import * as React from "react";
import { cn } from "@/lib/utils";

export const badgeVariants = cva(
  "inline-flex items-center gap-1 whitespace-nowrap rounded-[5px] border px-1.5 py-px text-[11px] font-medium leading-4 tracking-wide [&_svg]:size-3 [&_svg]:shrink-0",
  {
    variants: {
      tone: {
        neutral: "border-border bg-surface-2 text-muted",
        outline: "border-border-strong bg-transparent text-muted",
        ok: "border-ok-border bg-ok-soft text-ok",
        warn: "border-warn-border bg-warn-soft text-warn",
        bad: "border-bad-border bg-bad-soft text-bad",
        info: "border-transparent bg-info-soft text-info",
        accent: "border-transparent bg-accent-soft text-accent-text",
        inverse: "border-transparent bg-inverse text-inverse-fg",
        mock: "border-dashed border-border-strong bg-surface text-muted bg-hatch",
      },
      upper: { true: "uppercase tracking-[0.06em] text-[10px]", false: "" },
    },
    defaultVariants: { tone: "neutral", upper: false },
  },
);

export type BadgeProps = React.HTMLAttributes<HTMLSpanElement> & VariantProps<typeof badgeVariants>;

export function Badge({ className, tone, upper, ...props }: BadgeProps) {
  return <span className={cn(badgeVariants({ tone, upper }), className)} {...props} />;
}
