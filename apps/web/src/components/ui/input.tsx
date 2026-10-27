import * as React from "react";
import { cn } from "@/lib/utils";

export const Input = React.forwardRef<HTMLInputElement, React.InputHTMLAttributes<HTMLInputElement>>(function Input(
  { className, ...props },
  ref,
) {
  return (
    <input
      ref={ref}
      className={cn(
        "h-9 w-full min-w-0 rounded-md border border-border-strong bg-surface px-3 text-sm text-fg shadow-sm transition-colors placeholder:text-subtle hover:border-subtle focus-visible:border-ring focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/30 disabled:opacity-50",
        className,
      )}
      {...props}
    />
  );
});

export const Textarea = React.forwardRef<HTMLTextAreaElement, React.TextareaHTMLAttributes<HTMLTextAreaElement>>(function Textarea(
  { className, ...props },
  ref,
) {
  return (
    <textarea
      ref={ref}
      className={cn(
        "min-h-20 w-full rounded-md border border-border-strong bg-surface px-3 py-2 text-sm leading-6 text-fg shadow-sm transition-colors placeholder:text-subtle hover:border-subtle focus-visible:border-ring focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/30",
        className,
      )}
      {...props}
    />
  );
});

export function Label({ className, ...props }: React.LabelHTMLAttributes<HTMLLabelElement>) {
  return <label className={cn("text-[13px] font-medium text-fg", className)} {...props} />;
}

export function Select({ className, children, ...props }: React.SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <select
      className={cn(
        "h-9 rounded-md border border-border-strong bg-surface pr-8 pl-3 text-sm text-fg shadow-sm hover:border-subtle focus-visible:border-ring focus-visible:outline-none",
        className,
      )}
      {...props}
    >
      {children}
    </select>
  );
}
